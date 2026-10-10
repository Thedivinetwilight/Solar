"""V1.9-F — spatial protocol, corrected GP, and batch prediction tests.

All tests are pure-data/synthetic (no physics solves): they pin the
predeclared protocol rules, the Gaussian-process normalization correction,
and the numerical identity of the batch prediction path.
"""
import numpy as np
import pytest

from apmt.surrogate.domain import fit_support_profile, leave_one_out_distances
from apmt.surrogate.engine import SurrogateBundle
from apmt.surrogate.models import (
    MODEL_FAMILIES,
    MODEL_FAMILIES_V19F,
    BoxNormalizer,
    compare_families,
    fit_regressor,
    select_family,
)
from apmt.surrogate.spatial import (
    BLOCK_AXIS_INDEX,
    BLOCK_HIGH_MIN,
    BLOCK_LOW_MAX,
    MIN_STRATUM_POINTS,
    NEW_CORNER_BOXES,
    assert_role_separation,
    assign_axis_blocks,
    denormalize,
    distance_to_training,
    lhs_in_normalized_box,
    protocol_declaration,
    stratify_by_buffer,
    summarize_distances,
    training_buffer_radius,
)


def test_protocol_declaration_is_complete_and_versioned():
    decl = protocol_declaration()
    assert decl["protocol_version"].startswith("v19f-spatial-protocol/")
    assert decl["min_stratum_points"] == MIN_STRATUM_POINTS == 8
    assert decl["block_rule"]["axis_index"] == BLOCK_AXIS_INDEX == 0
    assert set(decl["new_corner_boxes_normalized"]) == set(NEW_CORNER_BOXES)
    assert len(decl["candidate_selection_methods"]) == 4


def test_buffer_rule_is_median_loo_distance_of_training_only():
    rng = np.random.default_rng(11)
    ztr = rng.random((40, 4))
    assert training_buffer_radius(ztr) == pytest.approx(
        float(np.median(leave_one_out_distances(ztr))))
    with pytest.raises(ValueError):
        training_buffer_radius(np.zeros((1, 4)))


def test_stratify_ties_count_as_separated_and_counts_add_up():
    strat = stratify_by_buffer(np.array([0.1, 0.5, 0.5, 0.9]), 0.5)
    assert strat["n"] == 4
    assert strat["n_interpolation"] == 1
    assert strat["n_separated"] == 3
    assert strat["separated_index"] == [1, 2, 3]
    with pytest.raises(ValueError):
        stratify_by_buffer(np.array([0.1, np.nan]), 0.5)


def test_summarize_distances_reports_quantiles():
    s = summarize_distances(np.linspace(0.0, 1.0, 101))
    assert s["n"] == 101 and s["min"] == 0.0 and s["max"] == 1.0
    assert s["median"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        summarize_distances(np.empty(0))


def test_axis_blocks_use_predeclared_quartile_slabs():
    z = np.array([[0.24], [0.25], [0.50], [0.75], [0.76]])
    blocks = assign_axis_blocks(z)
    assert blocks.low_slab_index == (0,)
    assert blocks.high_slab_index == (4,)
    assert blocks.interior_index == (1, 2, 3)
    d = blocks.as_dict()
    assert d["n_low"] == 1 and d["n_high"] == 1 and d["n_interior"] == 3
    assert BLOCK_LOW_MAX == 0.25 and BLOCK_HIGH_MIN == 0.75


def test_corner_lhs_is_deterministic_and_clamped():
    a = lhs_in_normalized_box(24, 14, (0.9, 1.0, 0.0, 0.1), seed=7)
    b = lhs_in_normalized_box(24, 14, (0.9, 1.0, 0.0, 0.1), seed=7)
    assert np.array_equal(a, b)
    assert a.shape == (24, 14)
    assert np.all(a[:, 0] >= 0.9) and np.all(a[:, 0] <= 1.0)
    assert np.all(a[:, 1] >= 0.0) and np.all(a[:, 1] <= 0.1)
    assert np.all(a[:, 2:] >= 0.0) and np.all(a[:, 2:] <= 1.0)


def test_denormalize_roundtrip():
    low = np.array([1.4, 150.0])
    high = np.array([2.0, 1500.0])
    z = np.array([[0.0, 0.0], [0.5, 1.0], [1.0, 0.25]])
    x = denormalize(z, low, high)
    assert np.allclose((x - low) / (high - low), z)
    with pytest.raises(ValueError):
        denormalize(z, np.array([1.4]), high)


def test_role_separation_refuses_overlap():
    assert_role_separation({"TRAIN"}, {"VALIDATION"})
    with pytest.raises(ValueError, match="role leakage"):
        assert_role_separation({"TRAIN"}, {"TRAIN", "FINAL_HOLDOUT"})


def test_distance_to_training_matches_brute_force():
    ztr = np.array([[0.0, 0.0], [1.0, 1.0]])
    ze = np.array([[0.0, 0.0], [0.5, 0.5]])
    d = distance_to_training(ze, ztr)
    assert d == pytest.approx([0.0, np.sqrt(0.5)])


def test_box_normalizer_is_fixed_and_data_independent():
    norm = BoxNormalizer(low=[1.4, 150.0], high=[2.0, 1500.0])
    norm.fit(np.zeros((3, 2)))  # fit ignores data; bounds are fixed
    out = norm.transform(np.array([[1.4, 150.0], [2.0, 1500.0], [1.7, 825.0]]))
    assert np.allclose(out, [[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]])
    assert norm.get_params()["low"].tolist() == [1.4, 150.0]
    clone = BoxNormalizer().set_params(low=[0.0], high=[1.0])
    assert np.allclose(clone.transform(np.array([[0.25]])), [[0.25]])
    with pytest.raises(ValueError):
        BoxNormalizer().fit(np.zeros((2, 1)))
    with pytest.raises(ValueError):
        BoxNormalizer(low=[1.0], high=[1.0]).fit(np.zeros((2, 1)))


def _wide_range_data(seed=3, n=48):
    rng = np.random.default_rng(seed)
    x = 150.0 + rng.random((n, 1)) * 1350.0  # raw-unit span >> kernel scale
    y = np.sin(x[:, 0] / 200.0) + 0.01 * rng.standard_normal(n)
    return x, y


def test_plain_gp_degrades_on_raw_wide_units_but_boxnorm_learns():
    """Pins the V1.9-E GP scaling defect and the V1.9-F correction.

    With raw wide units the ARD length-scale pins at its upper bound and the
    surface is barely learned; with the documented box normalization the same
    kernel learns the smooth surface (75x lower RMSE here).
    """
    import warnings

    from apmt.surrogate.models import regression_metrics

    x, y = _wide_range_data()
    xv = np.linspace(150.0, 1500.0, 25).reshape(-1, 1)
    yv = np.sin(xv[:, 0] / 200.0)
    with warnings.catch_warnings(record=True) as plain_warnings:
        warnings.simplefilter("always")
        plain = fit_regressor("gaussian_process_matern", x, y,
                              feature_names=["w"], target_name="t", unit="u",
                              training_fingerprint="test", seed=0)
    assert any("length_scale" in str(w.message) for w in plain_warnings)
    pred_plain, _ = plain.predict(xv, return_std=False)
    rmse_plain = regression_metrics(yv, pred_plain, train_y=y)["rmse"]
    assert rmse_plain > 0.3
    assert float(plain.estimator.kernel_.k1.k2.length_scale) == pytest.approx(4.0)
    fixed = fit_regressor("gaussian_process_matern_boxnorm", x, y,
                          feature_names=["w"], target_name="t", unit="u",
                          training_fingerprint="test", seed=0,
                          bounds=(np.array([150.0]), np.array([1500.0])))
    pred_fixed, std_fixed = fixed.predict(xv, return_std=True)
    rmse_fixed = regression_metrics(yv, pred_fixed, train_y=y)["rmse"]
    assert rmse_fixed < 0.05
    assert rmse_fixed < 0.1 * rmse_plain
    assert float(np.std(pred_fixed)) > float(np.std(pred_plain))
    assert np.all(np.isfinite(std_fixed)) and np.all(std_fixed > 0)
    learned_scale = float(fixed.estimator.named_steps["gp"].kernel_.k1.k2.length_scale)
    assert 0.025 < learned_scale < 4.0
    # determinism under identical seeds
    again = fit_regressor("gaussian_process_matern_boxnorm", x, y,
                          feature_names=["w"], target_name="t", unit="u",
                          training_fingerprint="test", seed=0,
                          bounds=(np.array([150.0]), np.array([1500.0])))
    pred_again, _ = again.predict(xv, return_std=False)
    assert np.array_equal(pred_fixed, pred_again)
    with pytest.raises(ValueError, match="requires verified-box bounds"):
        fit_regressor("gaussian_process_matern_boxnorm", x, y,
                      feature_names=["w"], target_name="t", unit="u",
                      training_fingerprint="test", seed=0)


def test_v19e_family_set_and_tie_breaks_are_unchanged():
    assert MODEL_FAMILIES == ("constant", "ridge", "sparse_polynomial",
                              "extra_trees", "hist_gradient_boosting",
                              "gaussian_process_matern")
    assert MODEL_FAMILIES_V19F[-1] == "gaussian_process_matern_boxnorm"
    assert len(MODEL_FAMILIES_V19F) == 7
    # tie between original families still favors the simpler one
    assert select_family({"ridge": {"rmse": 1.0},
                          "extra_trees": {"rmse": 1.0}}) == "ridge"


def test_compare_families_accepts_seven_way_with_bounds():
    rng = np.random.default_rng(5)
    xt = rng.random((32, 2))
    yt = xt[:, 0] * 2.0 - xt[:, 1] + 0.01 * rng.standard_normal(32)
    xv = rng.random((12, 2))
    yv = xv[:, 0] * 2.0 - xv[:, 1]
    import warnings

    with warnings.catch_warnings():
        # ARD bound warnings are pinned by the dedicated GP test above.
        warnings.simplefilter("ignore")
        fitted, scores = compare_families(
            xt, yt, xv, yv, feature_names=["a", "b"], target_name="t", unit="u",
            training_fingerprint="test", seed=0, families=MODEL_FAMILIES_V19F,
            bounds=(np.zeros(2), np.ones(2)))
    assert set(fitted) == set(MODEL_FAMILIES_V19F)
    assert all(np.isfinite(scores[f]["rmse"]) for f in fitted)
    assert select_family(scores) in fitted


def _tiny_bundle():
    rng = np.random.default_rng(9)
    names = ("a", "b")
    xt = rng.random((40, 2))
    yt = xt[:, 0] + 2.0 * xt[:, 1]
    model = fit_regressor("ridge", xt, yt, feature_names=names,
                          target_name="pce_pct", unit="%",
                          training_fingerprint="tiny", seed=0)
    alt = fit_regressor("constant", xt, yt, feature_names=names,
                        target_name="pce_pct", unit="%",
                        training_fingerprint="tiny", seed=1)
    profile = fit_support_profile(
        feature_names=names, low=np.zeros(2), high=np.ones(2),
        training_X=xt, in_domain_calibration_X=rng.random((8, 2)),
        withheld_region_calibration_X=0.9 + 0.1 * rng.random((8, 2)))
    card = {"target_scale": model.target_scale, "validation_rmse": 0.1,
            "calibration_rmse": 0.1,
            "conformal_calibration_status": "SPLIT_CONFORMAL_MARGINAL_CALIBRATED"}
    model.conformal_radius = 0.25
    return SurrogateBundle(
        feature_names=names, regimes={"r": {"name": "r"}},
        low=np.zeros(2), high=np.ones(2), registry_defaults={},
        fixed_parameter_names=(), selected_models={"r": {"pce_pct": model}},
        alternative_models={"r": {"pce_pct": [alt]}},
        support_profiles={"r": profile}, model_cards={"r": {"pce_pct": card}},
        training_fingerprints={"r": "tiny"})


def test_predict_batch_matches_predict_row_for_row():
    bundle = _tiny_bundle()
    rng = np.random.default_rng(13)
    rows = [{"a": float(a), "b": float(b)} for a, b in rng.random((17, 2))]
    rows.append({"a": 0.5})  # invalid row: identical error payload expected
    batch = bundle.predict_batch(rows, regime="r")
    assert batch["batch_status"] == "BATCH_COMPLETE"
    assert batch["n_rows"] == len(rows)
    for mapping, row_out in zip(rows, batch["results"]):
        single = bundle.predict(mapping, regime="r")
        assert row_out["status"] == single["status"]
        assert row_out.get("reason") == single.get("reason")
        assert set(row_out["predictions"]) == set(single["predictions"])
        for target, entry in single["predictions"].items():
            for key in ("prediction", "raw_predictive_std", "conformal_radius",
                        "family_disagreement_std", "family_disagreement_ratio"):
                assert entry[key] == pytest.approx(row_out["predictions"][target][key],
                                                   abs=1e-9), (target, key)


def test_predict_batch_rejects_unknown_regime():
    bundle = _tiny_bundle()
    out = bundle.predict_batch([{"a": 0.1, "b": 0.2}], regime="nope")
    assert out["batch_status"] == "MODEL_UNAVAILABLE"
    assert out["results"] == []
