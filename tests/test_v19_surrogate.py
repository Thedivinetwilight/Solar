"""V1.9-E surrogate contract, trust, calibration and verification regressions."""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from apmt.params.registry import ParamSet, vector_names
from apmt.surrogate.adaptive import localize_high_errors, propose_near_errors
from apmt.surrogate.campaign import (
    _assert_json_finite,
    _grouped_cv,
    _profile_l5_tolerance,
    _single_model_set,
)
from apmt.surrogate.data import (
    DATA_CONTRACT_VERSION,
    DUPLICATE_OR_DEPENDENT,
    INCOMPLETE_OUTPUT,
    INVALID_PHYSICS,
    OUTSIDE_VERIFIED_DOMAIN,
    VALID_FOR_SURROGATE,
    dataset_fingerprint,
    load_dataset,
    make_sample_record,
    mark_duplicates,
    save_dataset,
    training_rows,
)
from apmt.surrogate.domain import (
    IN_DOMAIN_UNCERTAIN,
    IN_DOMAIN_VALIDATED,
    INVALID_INPUT,
    MODEL_UNAVAILABLE,
    OUT_OF_DOMAIN,
    SupportProfile,
    detection_metrics,
    fit_support_profile,
)
from apmt.surrogate.engine import SurrogateBundle, load_bundle, save_bundle
from apmt.surrogate.models import (
    MODEL_FAMILIES,
    compare_families,
    conformal_radius,
    fit_regressor,
    grouped_kfold_indices,
    interval_metrics,
    minimum_calibration_samples,
    regression_metrics,
    select_family,
)
from apmt.synthetic.surrogate_benchmarks import (
    quadratic_interaction_surface,
    run_surrogate_synthetic_benchmarks,
    unit_lhs,
)
from apmt.validation.guard import SolveRecord
from apmt.validation.invariants import InvariantBundle, InvariantGroup, Severity, record

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
D_ARTIFACT = ROOT / "data" / "v19_sensitivity.json"
FEATURES = ("perovskite_eg_ev", "perovskite_thickness_nm")


class _FakeResult:
    def __init__(self, *, missing=()):
        fields = {"pce_pct": 19.0, "jsc_ma_cm2": 15.0, "voc_v": 1.4,
                  "ff": 0.84, "temperature_k": 310.0, "j_top_sc": 15.0,
                  "j_bottom_sc": 18.0, "current_matching_ratio": 1.2}
        for key in missing:
            fields.pop(key, None)
        self.__dict__.update(fields)
        self.coupling_converged = True
        self.detail = {"thermal": {"model": "energy_balance", "converged": True,
            "heat_load_mw_cm2": 45.0, "conduction_loss_mw_cm2": 38.0,
            "radiative_loss_mw_cm2": 7.0}}


def _fake_record(*, valid=True, params=None, campaign="fake", level="L4",
                 missing=(), runtime=0.1):
    params = params or ParamSet.defaults().to_dict()
    hard = record("test.hard", InvariantGroup.NUMERICAL.value, bool(valid),
                  severity=Severity.HARD, message="synthetic fixture")
    verdict = InvariantBundle((hard,))
    return SolveRecord(_FakeResult(missing=missing) if valid else None, verdict,
                       valid, runtime, level, params, campaign, 7, "test-solver",
                       "" if valid else "InvariantViolation: fixture failure")


def _box(names=FEATURES):
    art = json.loads(D_ARTIFACT.read_text())
    return ({n: float(art["shared_box"]["low"][n]) for n in names},
            {n: float(art["shared_box"]["high"][n]) for n in names})


def _data_row(*, valid=True, role="TRAIN", feature_names=FEATURES, params=None,
              physics_digest="physics-1", regime="nominal_1sun_25c", level="L4",
              missing=(), campaign="fake"):
    low, high = _box(feature_names)
    base = ParamSet.defaults().to_dict()
    if params:
        base.update(params)
    if "perovskite_eg_ev" in feature_names:
        base.setdefault("perovskite_eg_ev", 1.68)
    if "perovskite_thickness_nm" in feature_names:
        base.setdefault("perovskite_thickness_nm", 500.0)
    return make_sample_record(
        solve_record=_fake_record(valid=valid, params=base, campaign=campaign,
                                  level=level, missing=missing),
        feature_names=feature_names,
        regime={"name": regime, "irradiance_suns": 1.0, "temperature_k": 298.15},
        role=role, design_family=f"family-{role}", seed=7, model_form="IQE-M1",
        physics_digest=physics_digest, verified_low=low, verified_high=high,
        solver_options={"grid": 1})


def test_data_contract_has_version_full_parameter_vector_units_and_provenance():
    row = _data_row()
    assert row["contract_version"] == DATA_CONTRACT_VERSION
    assert row["status"] == VALID_FOR_SURROGATE
    assert set(vector_names()).issubset(row["parameters"])
    assert row["operating_regime"]["name"] == "nominal_1sun_25c"
    assert row["model_level"] == "L4" and row["random_seed"] == 7
    assert row["physics_digest"] == "physics-1"
    assert len(row["input_fingerprint"]) == 64
    assert row["runtime_s"] == pytest.approx(0.1)
    assert row["solver_termination_status"] == "CONVERGED_VALID"
    assert row["hard_invariants"][0]["severity"] == "HARD"
    assert row["outputs"]["pce_pct"] == 19.0
    assert row["output_units"]["pce_pct"] == "%"


def test_invalid_physics_has_no_numeric_output_payload_and_is_not_trainable():
    row = _data_row(valid=False)
    assert row["status"] == INVALID_PHYSICS
    assert row["outputs"] is None
    assert row["hard_invariant_failures"] == ["test.hard"]
    assert training_rows([row], regime_name="nominal_1sun_25c") == []


def test_outside_verified_box_and_incomplete_outputs_are_not_merged_with_valid():
    outside = _data_row(params={"perovskite_eg_ev": 2.0001})
    incomplete = _data_row(missing=("voc_v",))
    assert outside["status"] == OUTSIDE_VERIFIED_DOMAIN
    assert outside["outputs"] is not None  # diagnostic physics is retained, but never trained
    assert incomplete["status"] == INCOMPLETE_OUTPUT
    assert training_rows([outside, incomplete], regime_name="nominal_1sun_25c") == []


def test_duplicate_samples_are_audited_and_never_get_independent_weight():
    first = _data_row(role="TRAIN", campaign="design-a")
    duplicate = _data_row(role="VALIDATION", campaign="design-b")
    result = mark_duplicates([first, duplicate])
    assert result[0]["status"] == VALID_FOR_SURROGATE
    assert result[1]["status"] == DUPLICATE_OR_DEPENDENT
    assert result[1]["duplicate_of"] == result[0]["sample_id"]
    assert len(training_rows(result, regime_name="nominal_1sun_25c")) == 1


def test_fingerprints_change_with_physics_labels_but_ignore_runtime():
    a = _data_row(role="TRAIN")
    b = copy.deepcopy(a)
    b["runtime_s"] = 999.0
    assert dataset_fingerprint([a]) == dataset_fingerprint([b])
    b["outputs"]["pce_pct"] += 0.01
    assert dataset_fingerprint([a]) != dataset_fingerprint([b])
    c = _data_row(params={"perovskite_eg_ev": 1.70})
    assert a["input_fingerprint"] != c["input_fingerprint"]


def test_dataset_fingerprint_survives_json_mapping_key_reordering():
    rows = []
    for name, irradiance, temperature in (
        ("nominal_1sun_25c", 1.0, 298.15),
        ("concentrated_3sun_25c", 3.0, 298.15),
        ("hot_ambient_1sun_65c", 1.0, 338.15),
    ):
        row = _data_row(role="TRAIN", regime=name, campaign=f"{name}-campaign")
        row["operating_regime"] = {
            "name": name, "irradiance_suns": irradiance, "temperature_k": temperature,
        }
        rows.append(row)

    # The dataset is emitted with sort_keys=True; a digest must not depend on
    # the insertion order of operating-regime dictionaries before serialization.
    round_tripped = json.loads(json.dumps(rows, sort_keys=True))
    assert dataset_fingerprint(rows) == dataset_fingerprint(round_tripped)


def test_atomic_dataset_storage_separates_valid_rows_from_rejection_ledger(tmp_path):
    historical = hashlib.sha256(D_ARTIFACT.read_bytes()).hexdigest()
    good = _data_row(role="TRAIN")
    bad = _data_row(valid=False, role="TRAIN", campaign="invalid")
    target = tmp_path / "derived.json.gz"
    saved = save_dataset(target, [good, bad], metadata={"feature_units": {FEATURES[0]: "eV"}})
    artifact = load_dataset(target)
    assert saved["bytes"] > 0
    assert artifact["contract_version"] == DATA_CONTRACT_VERSION
    assert artifact["feature_schema"]["units"][FEATURES[0]] == "eV"
    assert len(artifact["valid_records"]) == 1
    assert artifact["rejection_ledger"][0]["status"] == INVALID_PHYSICS
    assert artifact["rejection_ledger"][0]["outputs"] is None
    assert artifact["physics_digest"]["sha256"] == saved["physics_digest"]
    assert hashlib.sha256(D_ARTIFACT.read_bytes()).hexdigest() == historical


def test_dataset_save_rejects_invalid_statuses_outputs_and_partition_mismatch(tmp_path):
    good = _data_row(role="TRAIN")
    invalid = _data_row(valid=False, role="TRAIN", campaign="invalid-save")
    invalid_with_labels = copy.deepcopy(invalid)
    invalid_with_labels["outputs"] = {"pce_pct": 1.0}
    with pytest.raises(ValueError, match="INVALID_PHYSICS"):
        save_dataset(tmp_path / "invalid.json.gz", [good, invalid_with_labels], metadata={})
    unknown = copy.deepcopy(good)
    unknown["status"] = "UNRECOGNIZED_STATUS"
    with pytest.raises(ValueError, match="unknown sample statuses"):
        save_dataset(tmp_path / "unknown.json.gz", [unknown], metadata={})

    target = tmp_path / "partition.json.gz"
    save_dataset(target, [good, invalid], metadata={})
    import gzip
    with gzip.open(target, "rt", encoding="utf-8") as f:
        artifact = json.load(f)
    artifact["rejection_ledger"].append(artifact["valid_records"].pop())
    with gzip.open(target, "wt", encoding="utf-8") as f:
        json.dump(artifact, f)
    with pytest.raises(ValueError, match="rejection_ledger"):
        load_dataset(target)

    malformed = tmp_path / "malformed-row.json.gz"
    save_dataset(malformed, [good], metadata={})
    with gzip.open(malformed, "rt", encoding="utf-8") as f:
        artifact = json.load(f)
    artifact["valid_records"].append(7)
    with gzip.open(malformed, "wt", encoding="utf-8") as f:
        json.dump(artifact, f)
    with pytest.raises(ValueError, match="only objects"):
        load_dataset(malformed)


def test_model_family_comparison_uses_validation_and_returns_finite_predictions():
    xtr = unit_lhs(72, 2, 13)
    xv = unit_lhs(32, 2, 14)
    f = lambda x: 1.0 + 2.0 * x[:, 0] - 0.7 * x[:, 1] + 0.3 * x[:, 0] * x[:, 1]
    models, scores = compare_families(xtr, f(xtr), xv, f(xv),
        feature_names=("x1", "x2"), target_name="y", unit="1",
        training_fingerprint="training-fingerprint", seed=5,
        feature_low=(0.0, 0.0), feature_high=(1.0, 1.0))
    assert set(models) == set(MODEL_FAMILIES)
    assert set(scores) == set(MODEL_FAMILIES)
    assert all(np.isfinite(v["rmse"]) for v in scores.values())
    assert select_family(scores) in MODEL_FAMILIES
    for model in models.values():
        assert model.feature_transform == "verified_box_linear_v1"
        assert model.feature_low == (0.0, 0.0)
        assert model.feature_high == (1.0, 1.0)
        pred, std = model.predict(xv[:3], return_std=True)
        assert pred.shape == (3,) and np.isfinite(pred).all()
        if std is not None:
            assert std.shape == (3,) and (std >= 0).all()


def test_model_rejects_nonfinite_and_missing_features_and_reports_metrics():
    X = unit_lhs(20, 2, 15)
    y = 3 * X[:, 0] - X[:, 1]
    model = fit_regressor("ridge", X, y, feature_names=("x", "y"),
                          target_name="target", unit="V",
                          training_fingerprint="fp", seed=1)
    with pytest.raises(ValueError, match="features"):
        model.predict(np.ones((2, 3)))
    with pytest.raises(ValueError, match="finite"):
        model.predict(np.array([[np.nan, 0.0]]))
    m = regression_metrics(y, model.predict(X, return_std=False)[0], train_y=y)
    assert {"rmse", "mae", "max_absolute_error", "bias",
            "normalized_rmse_train_sd", "relative_error_median_pct"} <= set(m)
    assert m["max_absolute_error"] >= m["mae"]


def test_feature_transform_is_stored_applied_and_training_only_when_unbounded():
    unit = unit_lhs(32, 2, 151)
    low = np.array([-2.0e6, 0.02])
    high = np.array([3.0e6, 0.08])
    X = low + unit * (high - low)
    y = 2.0 * unit[:, 0] - 0.5 * unit[:, 1]
    model = fit_regressor("ridge", X, y, feature_names=("wide", "small"),
                          target_name="target", unit="1", training_fingerprint="scaled",
                          feature_low=low, feature_high=high)
    X_probe = np.array([[0.4e6, 0.05]])
    expected_x = (X_probe - low) / (high - low)
    expected = model.estimator.predict(expected_x)
    pred, _ = model.predict(X_probe, return_std=False)
    assert model.feature_transform == "verified_box_linear_v1"
    assert np.allclose(pred, expected)
    with pytest.raises(ValueError, match="outside the supplied verified box"):
        fit_regressor("ridge", np.vstack([X, [high[0] + 1.0, high[1]]]),
                      np.r_[y, 0.0], feature_names=("wide", "small"),
                      target_name="target", unit="1", training_fingerprint="bad",
                      feature_low=low, feature_high=high)

    training_only = fit_regressor("ridge", X, y, feature_names=("wide", "small"),
                                  target_name="target", unit="1", training_fingerprint="fold")
    assert training_only.feature_transform == "training_minmax_linear_v1"
    assert np.allclose(training_only.feature_low, np.min(X, axis=0))
    assert np.allclose(training_only.feature_high, np.max(X, axis=0))


def test_campaign_uses_disjoint_calibration_and_grouped_cv_pooling():
    def rows(X, y, prefix, group_width):
        out = []
        for i, (x, target) in enumerate(zip(X, y)):
            out.append({
                "input_fingerprint": f"{prefix}-{i}",
                "design_point_fingerprint": f"{prefix}-point-{i}",
                "parameters": {"x": float(x[0]), "y": float(x[1])},
                "operating_regime": {"name": "synthetic"}, "model_level": "L4",
                "model_form": "synthetic", "physics_digest": "synthetic",
                "solver_options": {}, "solve_valid": True, "hard_invariants": [],
                "campaign_id": prefix, "design_family": f"{prefix}-group-{i // group_width}",
                "random_seed": 123, "role": prefix.upper(), "status": VALID_FOR_SURROGATE,
                "outputs": {"pce_pct": float(target)},
            })
        return out

    X_train = unit_lhs(36, 2, 551)
    y_train = 2.0 * X_train[:, 0] - X_train[:, 1]
    X_validation = unit_lhs(24, 2, 552)
    y_validation = 2.0 * X_validation[:, 0] - X_validation[:, 1]
    X_calibration = unit_lhs(24, 2, 553)
    y_calibration = 2.0 * X_calibration[:, 0] - X_calibration[:, 1] + 2.0
    train = rows(X_train, y_train, "train", 12)
    validation = rows(X_validation, y_validation, "validation", 24)
    calibration = rows(X_calibration, y_calibration, "calibration", 24)
    model, _, _, audit = _single_model_set(
        train_rows_=train, validation_rows=validation, calibration_rows=calibration,
        feature_names=("x", "y"), target="pce_pct", seed=554,
        training_fp=dataset_fingerprint(train), families=("ridge",))
    cal_pred, _ = model.predict(X_calibration, return_std=False)
    val_pred, _ = model.predict(X_validation, return_std=False)
    expected_calibration_q = conformal_radius(y_calibration, cal_pred, coverage=0.90)
    selection_residual_q = conformal_radius(y_validation, val_pred, coverage=0.90)
    assert audit["calibration_status"] == "SPLIT_CONFORMAL_MARGINAL_CALIBRATED"
    assert model.calibration_points == len(calibration)
    assert model.calibration_fingerprint == dataset_fingerprint(calibration)
    assert model.conformal_radius == pytest.approx(expected_calibration_q)
    assert model.conformal_radius > selection_residual_q

    uncalibrated, _, _, short_calibration = _single_model_set(
        train_rows_=train, validation_rows=validation, calibration_rows=calibration[:8],
        feature_names=("x", "y"), target="pce_pct", seed=557,
        training_fp=dataset_fingerprint(train), families=("ridge",))
    assert uncalibrated.conformal_radius is None
    assert short_calibration["calibration_status"] == "NOT_CALIBRATED"

    cv = _grouped_cv(train, ("x", "y"), "ridge", "pce_pct", 555,
                     np.zeros(2), np.ones(2))
    assert cv["status"] == "MEASURED_GROUPED_DESIGN_FAMILY_CV"
    assert cv["n_groups"] == 3 and np.isfinite(cv["pooled_rmse"])


def test_l5_tolerance_calibration_refuses_final_holdout_pairs():
    l4_final = {"operating_regime": {"name": "synthetic"}, "model_level": "L4",
                "role": "FINAL_HOLDOUT", "status": VALID_FOR_SURROGATE,
                "design_point_fingerprint": "final-point", "outputs": {"pce_pct": 10.0}}
    l5_final_pair = {"operating_regime": {"name": "synthetic"}, "model_level": "L5",
                    "role": "L5_CROSSCHECK", "status": VALID_FOR_SURROGATE,
                    "paired_design_id": "final-point", "outputs": {"pce_pct": 10.1}}
    assert _profile_l5_tolerance([l4_final, l5_final_pair]) == {}
    l4_cal = {**l4_final, "role": "CALIBRATION", "design_point_fingerprint": "cal-point"}
    l5_cal_pair = {**l5_final_pair, "paired_design_id": "cal-point", "outputs": {"pce_pct": 10.2}}
    tolerance = _profile_l5_tolerance([l4_cal, l5_cal_pair])
    assert tolerance["synthetic"]["pce_pct"] == pytest.approx(0.2)


def test_split_conformal_is_finite_sample_and_coverage_is_measured():
    truth = np.arange(1.0, 21.0)
    pred = truth + np.linspace(-0.2, 0.2, len(truth))
    radius = conformal_radius(truth, pred, coverage=0.9)
    metric = interval_metrics(truth, pred, radius=radius)
    assert radius >= np.quantile(np.abs(truth - pred), 0.85)
    assert metric["nominal_coverage"] == 0.9
    assert 0 <= metric["empirical_coverage"] <= 1
    assert metric["mean_interval_width"] == pytest.approx(2 * radius)


def test_split_conformal_rejects_impossible_finite_sample_quantiles():
    assert minimum_calibration_samples(0.90) == 9
    assert minimum_calibration_samples(0.95) == 19
    with pytest.raises(ValueError, match="at least 9 calibration points"):
        conformal_radius(np.arange(8.0), np.zeros(8), coverage=0.90)
    residuals = np.arange(1.0, 10.0)
    assert conformal_radius(residuals, np.zeros(9), coverage=0.90) == pytest.approx(9.0)
    with pytest.raises(ValueError, match="shapes must match"):
        conformal_radius(np.arange(9.0), np.zeros(8), coverage=0.90)
    with pytest.raises(ValueError, match="finite vector"):
        conformal_radius(np.r_[np.arange(8.0), np.nan], np.zeros(9), coverage=0.90)
    with pytest.raises(ValueError, match="strictly between"):
        conformal_radius(np.arange(10.0), np.zeros(10), coverage=1.0)


def test_grouped_splits_never_divide_a_design_family_and_are_reproducible():
    groups = np.repeat(["campaign-a", "campaign-b", "campaign-c"], [8, 10, 12])
    a = grouped_kfold_indices(groups, 3)
    b = grouped_kfold_indices(groups, 3)
    assert len(a) == 3
    for (tr, te), (tr2, te2) in zip(a, b):
        assert np.array_equal(tr, tr2) and np.array_equal(te, te2)
        assert not (set(groups[tr]) & set(groups[te]))


def test_support_calibration_separates_a_deliberately_withheld_region():
    train = unit_lhs(128, 2, 30)
    train = train[~((train[:, 0] > 0.82) & (train[:, 1] > 0.82))]
    inside = unit_lhs(64, 2, 31)
    withheld = np.column_stack([np.linspace(0.84, 0.99, 24),
                               np.linspace(0.99, 0.84, 24)])
    profile = fit_support_profile(feature_names=("x", "y"), low=[0, 0], high=[1, 1],
        training_X=train, in_domain_calibration_X=inside,
        withheld_region_calibration_X=withheld, max_false_positive_rate=0.10)
    test_ood = np.column_stack([np.linspace(0.85, 0.995, 24),
                                np.linspace(0.995, 0.85, 24)])
    scores = detection_metrics(profile, inside, test_ood)
    assert scores["in_domain_false_out_of_domain_rate"] <= 0.10
    assert scores["withheld_region_detection_recall"] >= 0.50
    assert profile.classify([1.1, 0.5])["status"] == OUT_OF_DOMAIN
    assert profile.classify([np.nan, 0.5])["status"] == INVALID_INPUT
    assert profile.calibration["uncertainty_threshold_status"] == "NOT_CALIBRATED"
    assert profile.classify([0.5, 0.5])["uncertainty_ratio_threshold"] is None


def test_support_boundary_downgrades_to_uncertain_not_validated():
    train = np.array([[0.5, 0.5], [0.45, 0.55], [0.55, 0.45]])
    profile = SupportProfile(("x", "y"), np.zeros(2), np.ones(2), train,
        nearest_distance_ood_threshold=10.0,
        nearest_distance_uncertain_threshold=10.0,
        uncertainty_ratio_threshold=float("inf"),
        disagreement_ratio_threshold=float("inf"),
        boundary_fraction_threshold=0.05, calibration={})
    assert profile.classify([0.01, 0.5])["status"] == IN_DOMAIN_UNCERTAIN
    assert profile.classify([0.5, 0.5])["status"] == IN_DOMAIN_VALIDATED


def test_adaptive_selection_localizes_errors_and_proposes_new_in_box_points():
    Xv = unit_lhs(80, 3, 41)
    residual = 0.01 * np.ones(len(Xv))
    hot = np.argmin(np.linalg.norm(Xv[:, :2] - np.array([0.72, 0.28]), axis=1))
    residual[hot] = 2.0
    regions = localize_high_errors(Xv, residual, low=np.zeros(3), high=np.ones(3), n_regions=3)
    assert regions and regions[0]["peak_absolute_error"] == pytest.approx(2.0)
    train = unit_lhs(50, 3, 42)
    adapt = propose_near_errors(Xv, residual, low=np.zeros(3), high=np.ones(3),
                                existing_X=np.vstack([train, Xv]), n_samples=20,
                                seed=43, perturbation_fraction=0.03)
    assert adapt.shape == (20, 3)
    assert np.all((adapt >= 0) & (adapt <= 1))
    assert min(np.linalg.norm(adapt[:, None] - Xv[None, :], axis=2).ravel()) > 0


def _small_bundle(tmp_path):
    art = json.loads(D_ARTIFACT.read_text())
    names = tuple(art["design_parameters"])
    low = np.array([art["shared_box"]["low"][n] for n in names], float)
    high = np.array([art["shared_box"]["high"][n] for n in names], float)
    default = ParamSet.defaults().to_dict()
    x0 = np.array([default[n] for n in names], float)
    rng = np.random.default_rng(77)
    X = x0 + rng.normal(0, 0.001, size=(12, len(names)))
    X = np.clip(X, low + 1e-6, high - 1e-6)
    y = np.full(12, 18.0)
    model = fit_regressor("constant", X, y, feature_names=names,
                          target_name="pce_pct", unit="%",
                          training_fingerprint="training-fp", seed=78)
    model.conformal_radius = 10.0
    z0 = (x0 - low) / (high - low)
    profile = SupportProfile(names, low, high, np.vstack([z0, (X - low) / (high - low)]),
        nearest_distance_ood_threshold=5.0, nearest_distance_uncertain_threshold=5.0,
        uncertainty_ratio_threshold=float("inf"), disagreement_ratio_threshold=float("inf"),
        boundary_fraction_threshold=0.0, calibration={"test_fixture": True})
    settings = {"name": "nominal_1sun_25c", "irradiance_suns": 1.0,
                "temperature_k": 298.15}
    fixed = tuple(n for n in vector_names() if n not in names
                  and n not in ("irradiance_suns", "temperature_k"))
    bundle = SurrogateBundle(
        feature_names=names, regimes={settings["name"]: settings}, low=low, high=high,
        registry_defaults=default, fixed_parameter_names=fixed,
        selected_models={settings["name"]: {"pce_pct": model}},
        alternative_models={settings["name"]: {"pce_pct": []}},
        support_profiles={settings["name"]: profile},
        model_cards={settings["name"]: {"pce_pct": {"target_scale": 1.0,
            "validation_rmse": 0.1}}},
        training_fingerprints={settings["name"]: "training-fp"},
        validation_l5_tolerance={settings["name"]: {"pce_pct": 10.0}})
    return bundle, {n: float(default[n]) for n in names}, tmp_path


def test_prediction_api_fails_closed_on_missing_features_unknown_regime_and_unmodeled_knobs(tmp_path):
    bundle, x, _ = _small_bundle(tmp_path)
    assert bundle.predict({"perovskite_eg_ev": x["perovskite_eg_ev"]},
                          regime="nominal_1sun_25c")["status"] == INVALID_INPUT
    assert bundle.predict(x, regime="new-regime")["status"] == MODEL_UNAVAILABLE
    typo = dict(x, perovskite_thickness_nmm=500.0)
    assert bundle.predict(typo, regime="nominal_1sun_25c")["status"] == INVALID_INPUT
    mixed_keys = dict(x)
    mixed_keys["unexpected"] = 1.0
    mixed_keys[7] = 1.0
    assert bundle.predict(mixed_keys, regime="nominal_1sun_25c")["status"] == INVALID_INPUT
    wrong_illumination = dict(x, irradiance_suns=3.0)
    assert bundle.predict(wrong_illumination, regime="nominal_1sun_25c")["status"] == MODEL_UNAVAILABLE
    changed = dict(x, perovskite_absorption_alpha_ev=5.1e4)
    out = bundle.predict(changed, regime="nominal_1sun_25c")
    assert out["status"] == MODEL_UNAVAILABLE
    valid = bundle.predict(x, regime="nominal_1sun_25c")
    assert valid["status"] in (IN_DOMAIN_VALIDATED, IN_DOMAIN_UNCERTAIN)
    assert valid["predictions"]["pce_pct"]["unit"] == "%"
    assert valid["predictions"]["pce_pct"]["conformal_interval"] is not None
    assert valid["training_data_fingerprint"] == "training-fp"


def test_high_fidelity_verification_runs_l4_and_l5_but_respects_uncertain_support(tmp_path):
    bundle, x, _ = _small_bundle(tmp_path)
    result = bundle.verify_candidate(x, regime="nominal_1sun_25c", run_l5=True)
    assert result["l4"]["model_level"] == "L4"
    assert result["l4"]["valid"] is True
    assert result["l4"]["hard_invariant_status"] == "PASS"
    assert result["l5"] is not None and result["l5"]["model_level"] == "L5"
    assert "surrogate_minus_l4" in result
    assert "training_data_fingerprint" in result
    # rsh is close to the shared box boundary, so support is explicitly
    # uncertain.  Even a valid L4/L5 result cannot waive that OOD safeguard.
    assert result["prediction"]["status"] == IN_DOMAIN_UNCERTAIN
    assert result["candidate_eligible_for_optimizer"] is False


def test_candidate_l5_crosscheck_fails_closed_without_calibrated_targets(monkeypatch, tmp_path):
    from apmt.validation import guard

    bundle, x, _ = _small_bundle(tmp_path)

    def fake_evaluate(ps, *, level, model_form, campaign_id, seed):
        missing = ("pce_pct",) if level == "L5" else ()
        return _fake_record(valid=True, params=ps.to_dict(), campaign=campaign_id,
                            level=level, missing=missing)

    monkeypatch.setattr(guard, "evaluate_guarded", fake_evaluate)
    bundle.validation_l5_tolerance = {"nominal_1sun_25c": {"pce_pct": 100.0}}
    result = bundle.verify_candidate(x, regime="nominal_1sun_25c", run_l5=True)
    assert result["l5"]["within_campaign_calibrated_tolerance"] == {"pce_pct": False}
    assert result["l5"]["delta_l5_minus_l4"]["pce_pct"] is None
    assert result["candidate_eligible_for_optimizer"] is False

    bundle.validation_l5_tolerance = {"nominal_1sun_25c": {}}
    result = bundle.verify_candidate(x, regime="nominal_1sun_25c", run_l5=True)
    assert result["l5"]["within_campaign_calibrated_tolerance"] == {"pce_pct": False}
    assert result["candidate_eligible_for_optimizer"] is False


def test_out_of_domain_candidate_cannot_advance_or_run_physics_by_default(tmp_path):
    bundle, x, _ = _small_bundle(tmp_path)
    x["perovskite_eg_ev"] = float(bundle.high[0] + 1e-3)
    result = bundle.verify_candidate(x, regime="nominal_1sun_25c", run_l5=False)
    assert result["candidate_status"] == OUT_OF_DOMAIN
    assert result["l4"] is None
    assert result["candidate_eligible_for_optimizer"] is False


def test_result_json_guard_reports_nonfinite_path_instead_of_silently_coercing():
    with pytest.raises(ValueError, match=r"\$\.support\[1\]\.threshold"):
        _assert_json_finite({"support": [0.2, {"threshold": float("inf")} ]})


def test_model_bundle_serialization_preserves_model_and_data_fingerprint(tmp_path):
    bundle, x, _ = _small_bundle(tmp_path)
    path = tmp_path / "bundle.joblib"
    saved = save_bundle(bundle, path)
    restored = load_bundle(path)
    assert saved["bytes"] > 0
    assert restored.training_fingerprints == bundle.training_fingerprints
    assert restored.predict(x, regime="nominal_1sun_25c")["predictions"]["pce_pct"]["prediction"] == pytest.approx(18.0)


def test_synthetic_benchmarks_recover_optimum_interaction_and_report_coverage():
    x = np.array([[0.27, 0.64], [0.0, 0.0], [1.0, 1.0]])
    y = quadratic_interaction_surface(x)
    assert y[0] > y[1] and y[0] > y[2]
    result = run_surrogate_synthetic_benchmarks(seed=20261009)
    analytic = result["analytic_surface"]
    assert analytic["known_optimum"] == [0.27, 0.64]
    assert analytic["optimum_coordinate_error"] < 0.08
    assert analytic["interaction_cross_difference_absolute_error"] < 0.25
    assert analytic["selection_n"] != analytic["calibration_n"]
    assert analytic["conformal_90_final_holdout"]["n"] == 256
    hetero = result["heteroscedastic_noise"]
    assert hetero["model_selection_n"] != hetero["calibration_n"]
    assert "empirical_coverage" in hetero["split_conformal_90_final_holdout"]
    assert result["withheld_region_detection"]["withheld_region_detection_recall"] >= 0.5
    invalid = result["invalid_region_guard"]
    assert invalid["invalid_physics_rows_rejected"] > 0
    assert invalid["penalty_label_in_regression_training"] is False
    assert invalid["invalid_probe_rule_passed"] is True
    assert "rmse_reduction_fraction" in result["adaptive_sampling"]
    assert result["ishigami_guard"]["false_pairs_at_n96_are_not_ground_truth"] is True
