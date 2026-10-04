"""V1.9-D — global sensitivity: estimator, design, validity handling, campaign.

The centrepiece is a KNOWN-ANSWER test: the Sobol estimators are verified against
the Ishigami function, whose indices are known analytically. Without that, a
variance-decomposition implementation is unfalsifiable — a wrong normalisation or
a swapped block would still produce plausible-looking numbers.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from apmt.params.registry import ParamSet, spec
from apmt.sensitivity.campaign import (DESIGN_PARAMETERS, OUTPUTS, REGIMES,
                                       box_at_scale, estimator_validation,
                                       extract_outputs, interaction_study,
                                       local_sensitivity, per_axis_validity_envelope,
                                       rank_disagreements, run_regime, spearman_rank,
                                       validated_box)
from apmt.sensitivity.sobol import (ISHIGAMI_ANALYTIC, ishigami, ishigami_design,
                                    saltelli_design, sobol_indices)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT = os.path.join(HERE, "data", "v19_sensitivity.json")


# ---------------------------------------------------------------------------
# estimator: known answers
# ---------------------------------------------------------------------------
def test_sobol_indices_match_the_analytic_ishigami_values():
    """Known-answer test against closed-form indices (Saltelli et al. 2010)."""
    design = ishigami_design(n_base=4096, seed=5)
    res = sobol_indices(ishigami(design.matrix()), design, output="f", bootstrap=0)
    assert res.complete and not res.degenerate
    # the variance estimator is itself a Monte Carlo estimate over 2N points; the
    # tolerance is set to its sampling error, not to zero
    assert res.variance == pytest.approx(ISHIGAMI_ANALYTIC["variance"], rel=0.05)
    for i, name in enumerate(design.names):
        assert res.total[i] == pytest.approx(ISHIGAMI_ANALYTIC["ST"][name], abs=0.05), name
        if name != "x3":
            assert res.first[i] == pytest.approx(ISHIGAMI_ANALYTIC["S1"][name], abs=0.05)
    # x3 has zero first-order index but a non-zero total-order index: the exact
    # signature of an interaction, and the reason a local/OAT scan cannot see it
    assert res.first[2] == pytest.approx(0.0, abs=0.03)
    assert res.total[2] > 0.15
    assert res.second[("x1", "x3")] == pytest.approx(0.2437, abs=0.05)


def test_total_order_is_never_below_first_order_for_a_real_function():
    design = ishigami_design(n_base=512, seed=9)
    res = sobol_indices(ishigami(design.matrix()), design, bootstrap=0)
    assert np.all(res.total >= res.first - 0.03)


def test_estimator_error_at_the_campaign_sample_size_is_documented():
    """The campaign runs N=96, so the error at N=96 must be measured and bounded.

    This test does not assert that the estimator is precise at N=96 — it records
    that it is NOT, which is why the campaign averages replicates and reports a
    spread instead of pretending one design gives the truth.
    """
    worst = 0.0
    for seed in (1, 2, 3):
        design = ishigami_design(n_base=96, seed=seed)
        res = sobol_indices(ishigami(design.matrix()), design, bootstrap=0)
        worst = max(worst, max(abs(res.total[i] - ISHIGAMI_ANALYTIC["ST"][n])
                               for i, n in enumerate(design.names)))
    assert 0.02 < worst < 0.45, f"unexpected N=96 error {worst}"
    # replicates genuinely reduce it (used by the campaign aggregation)
    errs = []
    for seed in (1, 2, 3, 4, 5, 6):
        d = ishigami_design(n_base=512, seed=seed)
        errs.append(max(abs(sobol_indices(ishigami(d.matrix()), d).total[i]
                            - ISHIGAMI_ANALYTIC["ST"][n])
                        for i, n in enumerate(d.names)))
    assert max(errs) < 0.15


def test_bootstrap_ci_covers_the_analytic_value():
    design = ishigami_design(n_base=1024, seed=3)
    res = sobol_indices(ishigami(design.matrix()), design, bootstrap=50)
    assert res.total_ci is not None and np.all(res.total_ci > 0)
    assert abs(res.total[0] - ISHIGAMI_ANALYTIC["ST"]["x1"]) <= 3 * res.total_ci[0] + 0.05


# ---------------------------------------------------------------------------
# design
# ---------------------------------------------------------------------------
def test_saltelli_design_structure_and_reproducibility():
    names = ("a", "b", "c")
    low = np.array([0.0, 0.0, 0.0])
    high = np.array([1.0, 2.0, 3.0])
    d = saltelli_design(names, n_base=16, low=low, high=high, seed=42)
    assert d.n_blocks == 2 + 2 * 3
    assert d.matrix().shape == (d.n_blocks * 16, 3)
    # AB_i differs from A in EXACTLY column i
    for i in range(3):
        diff = np.flatnonzero(np.any(d.AB[i] != d.A, axis=1))
        assert len(diff) == 16
        assert np.array_equal(d.AB[i][:, i], d.B[:, i])
        same = [j for j in range(3) if j != i]
        assert np.array_equal(d.AB[i][:, same], d.A[:, same])
    # the same seed rebuilds the same design; a different seed does not
    d2 = saltelli_design(names, n_base=16, low=low, high=high, seed=42)
    assert d.fingerprint() == d2.fingerprint()
    d3 = saltelli_design(names, n_base=16, low=low, high=high, seed=43)
    assert d.fingerprint() != d3.fingerprint()
    assert d.to_dict()["n_evaluations"] == d.n_blocks * 16


def test_design_never_leaves_the_box():
    low = np.array([1.0, -5.0])
    high = np.array([2.0, 5.0])
    d = saltelli_design(("a", "b"), n_base=32, low=low, high=high, seed=1)
    m = d.matrix()
    assert m[:, 0].min() >= 1.0 and m[:, 0].max() <= 2.0
    assert m[:, 1].min() >= -5.0 and m[:, 1].max() <= 5.0


# ---------------------------------------------------------------------------
# INVALID / degenerate handling (the part no off-the-shelf library does)
# ---------------------------------------------------------------------------
def test_invalid_points_are_flagged_never_imputed():
    design = ishigami_design(n_base=64, seed=4)
    y = ishigami(design.matrix())
    y = y.copy()
    y[:7] = np.nan                     # 7 lost evaluations
    res = sobol_indices(y, design, output="f", bootstrap=0)
    assert res.complete is False
    assert res.n_missing == 7
    assert res.bootstrap == 0          # no CI is offered for an incomplete design
    assert np.isfinite(res.total).all()   # usable numbers, explicitly flagged


def test_all_invalid_output_is_not_applicable_not_zero():
    design = ishigami_design(n_base=32, seed=4)
    res = sobol_indices(np.full(design.n_blocks * 32, np.nan), design)
    assert res.not_applicable is True
    assert np.isnan(res.total).all()
    assert "not produced" in res.as_dict()["reason"]


def test_zero_variance_output_gives_undefined_not_zero_indices():
    """A constant output has no variance: normalising by it would manufacture
    indices from numerical noise (found when the L2 screening tried to analyse the
    junction temperature, which is fixed at a fixed-temperature level)."""
    design = ishigami_design(n_base=32, seed=6)
    res = sobol_indices(np.full(design.n_blocks * 32, 300.0), design)
    assert res.degenerate is True
    assert np.isnan(res.total).all() and np.isnan(res.first).all()
    assert "zero variance" in res.as_dict()["reason"]


# ---------------------------------------------------------------------------
# validity envelope / sampling box
# ---------------------------------------------------------------------------
def test_validity_envelope_stays_inside_the_registered_range():
    """Regression: the first implementation applied the direction sign twice and
    walked outside the registered range, reporting e.g. 460 um for a 60-400 um
    range. Reachable values must always be inside the declared interval."""
    names = ("silicon_thickness_um", "silicon_light_trapping")
    env = per_axis_validity_envelope(names, REGIMES[1], level="L2", n_scan=3)
    for name in names:
        s = spec(name)
        d = env["per_parameter"][name]
        assert s.low - 1e-9 <= d["low"] <= s.high + 1e-9
        assert s.low - 1e-9 <= d["high"] <= s.high + 1e-9
        assert d["low"] <= d["high"]


def test_nominal_box_is_the_registered_box_and_probes_fully_valid():
    box = validated_box(DESIGN_PARAMETERS, REGIMES[0], level="L2", n_probe=6,
                        seed=11, n_bisect=1)
    assert box["ok"] is True
    assert box["registered_box_used"] is True
    lo_reg, hi_reg = box_at_scale(DESIGN_PARAMETERS, 1.0)
    assert np.allclose(box["low"], lo_reg) and np.allclose(box["high"], hi_reg)
    assert box["probe_history"][-1]["n_invalid"] == 0


def test_concentrated_regime_restricts_the_thermal_axis_and_verifies_the_box():
    """Under 3 suns the thermal-resistance axis is the binding validity constraint;
    the box must be restricted there and then VERIFIED by a probe (a single-axis
    envelope is necessary, not sufficient: joint corners can still fail)."""
    box = validated_box(DESIGN_PARAMETERS, REGIMES[1], level="L4", n_probe=12,
                        seed=13, n_bisect=2)
    assert box["ok"] is True
    assert "thermal_resistance_k_cm2_w" in box["restricted_axes"]
    i = DESIGN_PARAMETERS.index("thermal_resistance_k_cm2_w")
    assert box["high"][i] < spec("thermal_resistance_k_cm2_w").high
    assert box["probe_history"][-1]["n_invalid"] == 0
    # every other axis keeps its registered range under concentration
    lo_reg, hi_reg = box_at_scale(DESIGN_PARAMETERS, 1.0)
    for j, name in enumerate(DESIGN_PARAMETERS):
        if name != "thermal_resistance_k_cm2_w":
            assert box["low"][j] == pytest.approx(lo_reg[j])
            assert box["high"][j] == pytest.approx(hi_reg[j])


def test_shared_box_is_the_per_axis_intersection_and_valid_in_every_regime():
    """Regression: the first driver built the shared box by taking the smallest
    mean-width scale and re-inflating a UNIFORM box, which discarded the per-axis
    envelope. Under concentration that produced a design with ~50% invalid points.
    The shared box must be a component-wise subset of every per-regime box."""
    from apmt.sensitivity.campaign import shared_validated_box
    names = ("thermal_resistance_k_cm2_w", "arc_thickness_nm")
    box = shared_validated_box(names, REGIMES[:2], level="L2", n_probe=8, seed=77,
                               n_bisect=1)
    assert box["ok"] is True
    for reg_name, per in box["per_regime"].items():
        assert np.all(box["low"] >= per["low"] - 1e-9)
        assert np.all(box["high"] <= per["high"] + 1e-9)
    # the thermal axis is the constrained one; the optical axis stays registered
    j = names.index("arc_thickness_nm")
    lo_reg, hi_reg = box_at_scale(names, 1.0)
    assert box["low"][j] == pytest.approx(lo_reg[j])
    assert box["high"][j] == pytest.approx(hi_reg[j])
    assert box["probe_history"][-1]["n_invalid"] == 0


def test_invalid_solve_is_invalid_in_the_verdict_too():
    """Engine hardening: a solve that raises because the operating point left the
    electrical validity envelope must be INVALID in ``verdict`` as well as in
    ``valid``. Before this, the bundle was empty and reported status PASS, so a
    consumer reading the verdict would have accepted an out-of-envelope corner."""
    from apmt.validation.guard import evaluate_guarded
    ps = ParamSet.defaults().with_mapping({"irradiance_suns": 10.0,
                                           "thermal_resistance_k_cm2_w": 2.0})
    rec = evaluate_guarded(ps, level="L4", campaign_id="envelope-test")
    assert rec.valid is False
    assert rec.verdict.valid is False
    assert rec.verdict.status.value == "FAIL"
    assert "numerical.solve_completed" in [f.name for f in rec.verdict.failures]
    assert "ModelValidityError" in rec.error


def test_extract_outputs_returns_nan_for_an_invalid_record():
    from apmt.validation.guard import evaluate_guarded
    rec = evaluate_guarded(ParamSet.defaults().with_mapping({"irradiance_suns": 10.0}),
                           level="L4")
    out = extract_outputs(rec)
    assert set(out) == set(OUTPUTS)
    assert all(not np.isfinite(v) for v in out.values())


# ---------------------------------------------------------------------------
# campaign mechanics
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def smoke_regime():
    box = validated_box(DESIGN_PARAMETERS, REGIMES[0], level="L2", n_probe=6,
                        seed=21, n_bisect=1)
    return run_regime(REGIMES[0], box=box, level="L2", n_base=12, replicates=1,
                      second_order=False, bootstrap=0, screening_level=None,
                      campaign_id="pytest-smoke")


def test_run_regime_reports_indices_and_labelled_provenance(smoke_regime):
    assert smoke_regime["status"] == "OK"
    assert set(smoke_regime["indices"]) == set(OUTPUTS)
    idx = smoke_regime["indices"]["pce_pct"]
    assert idx["n_replicates"] == 1
    assert len(idx["mean_total"]) == len(DESIGN_PARAMETERS)
    assert idx["ranking_total"][0] in DESIGN_PARAMETERS
    assert smoke_regime["regime"]["settings"]["irradiance_suns"] == 1.0
    assert set(smoke_regime["box"]["low"]) == set(DESIGN_PARAMETERS)


def test_campaign_box_is_never_larger_than_the_registered_box(smoke_regime):
    lo_reg, hi_reg = box_at_scale(DESIGN_PARAMETERS, 1.0)
    lo = np.array([smoke_regime["box"]["low"][n] for n in DESIGN_PARAMETERS])
    hi = np.array([smoke_regime["box"]["high"][n] for n in DESIGN_PARAMETERS])
    assert np.all(lo >= lo_reg - 1e-9) and np.all(hi <= hi_reg + 1e-9)


def test_screening_comparison_is_labelled_and_skips_undefined_outputs():
    box = validated_box(DESIGN_PARAMETERS, REGIMES[0], level="L2", n_probe=6,
                        seed=31, n_bisect=1)
    res = run_regime(REGIMES[0], box=box, level="L4", n_base=8, replicates=1,
                     second_order=False, bootstrap=0, screening_level="L2",
                     campaign_id="pytest-screen")
    scr = res["screening"]
    assert "SCREENING ONLY" in scr["label"]
    # the junction temperature does not vary at L2 -> UNDEFINED, not zero
    assert scr["per_output"]["temperature_k"]["not_applicable"] is True
    assert "zero variance" in scr["per_output"]["temperature_k"]["reason"]
    assert res["screening_vs_reference"]["temperature_k"]["agreement"] == "NOT-APPLICABLE"


def test_rejection_ledger_accounts_for_every_invalid_point(smoke_regime):
    led = smoke_regime["registered_box_validity"]
    assert led["n_valid"] + led["n_invalid"] == led["n_total"]
    for entry in smoke_regime["designs"]:
        r = entry["rejections"]
        assert r["n_valid"] + r["n_invalid"] == r["n_total"]


def test_local_sensitivity_is_separated_from_the_global_analysis(smoke_regime):
    loc = smoke_regime["local_sensitivity"]
    assert "LOCAL" in loc["label"]
    assert loc["n_valid"] >= len(DESIGN_PARAMETERS) - 2
    # the OAT ranking and the global ranking are different quantities (they cover
    # the same parameters, so it is the ORDER that must differ)
    global_rank = smoke_regime["indices"]["pce_pct"]["ranking_total"]
    assert loc["ranking"] != global_rank
    assert set(loc["ranking"]) == set(global_rank)


def test_spearman_and_rank_disagreement_helpers():
    a = {"x": 0.5, "y": 0.3, "z": 0.05, "w": 0.01}
    assert spearman_rank(list(a.values()), list(a.values())) == pytest.approx(1.0)
    assert spearman_rank([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    other = {"x": 0.5, "y": 0.01, "z": 0.05, "w": 0.3}     # y and w swapped
    dis = rank_disagreements(a, other)
    assert {d["parameter"] for d in dis} >= {"y"}
    assert all(d["delta_index"] > 0 for d in dis)


def test_pairwise_indices_are_not_reportable_at_the_campaign_sample_size():
    """Self-falsification result that shapes the whole campaign: at N=96 the
    pairwise estimator produces ~0.5-magnitude indices where the analytic value is
    exactly zero. The campaign therefore forbids pairwise reporting at that N."""
    spurious, known = [], []
    for seed in range(5):
        d = ishigami_design(n_base=96, seed=seed)
        res = sobol_indices(ishigami(d.matrix()), d, bootstrap=0)
        spurious.append(max(abs(res.second[("x1", "x2")]),
                            abs(res.second[("x2", "x3")])))
        known.append(res.second[("x1", "x3")])
    # spurious pairs reach a magnitude comparable with a REAL interaction (0.24)
    assert max(spurious) > 0.15, ("if this ever stops being true, the interaction "
                                 "study can be simplified")
    # and the estimate of the one real pair is not stable across designs
    assert max(known) - min(known) > 0.15


def test_estimator_validation_calibrates_a_real_detection_floor():
    v = estimator_validation(n_base_main=64, n_base_pairs=384, n_dim_pairs=4,
                             seeds=(1, 2))
    pair = v["pairwise_order"]
    # a real noise floor: too large to ignore, small enough to be useful
    assert 0.02 < pair["detection_floor"] < 0.45
    # the structural check (pairs with an inert variable) is zero by construction
    assert pair["structural_zero_check"] < 1e-9
    assert v["first_total_order"]["max_abs_error_total_order"] > 0.01
    assert "not a physics result" in v["purpose"]


def test_interaction_budget_is_reported_instead_of_raw_pairs(smoke_regime):
    idx = smoke_regime["indices"]["pce_pct"]
    assert idx["pairwise_indices_reportable"] is False
    assert "dominated by estimator variance" in idx["pairwise_indices_note"]
    assert "kept only for audit" in idx["pairwise_indices_note"]
    budget = idx["interaction_budget"]
    assert set(budget) == set(DESIGN_PARAMETERS)
    # S_T >= S_1 up to estimator noise for the dominant parameter, so the budget
    # of the strongest parameter is non-negative
    top = idx["ranking_total"][0]
    assert budget[top] > -0.6


def test_interaction_study_flags_sub_floor_pairs():
    box = validated_box(("perovskite_eg_ev", "rs_ohm_cm2"), REGIMES[0], level="L2",
                        n_probe=6, seed=51, n_bisect=1)
    study = interaction_study(("perovskite_eg_ev", "rs_ohm_cm2"), REGIMES[0], box,
                              level="L2", n_base=16, seed=3, detection_floor=0.15,
                              campaign_id="pytest-interactions")
    assert study["parameters"] == ["perovskite_eg_ev", "rs_ohm_cm2"]
    assert "defaults" in study["scope_note"]
    per = study["per_output"]["pce_pct"]
    assert set(per["pairs"]) == {"perovskite_eg_ev|rs_ohm_cm2"}
    for k, v in per["reportable_pairs"].items():
        assert abs(v) >= study["detection_floor"]
    assert per["interaction_budget"]


# ---------------------------------------------------------------------------
# committed campaign artifact
# ---------------------------------------------------------------------------
def test_committed_sensitivity_artifact_is_verifiable():
    if not os.path.exists(ARTIFACT):                        # pragma: no cover
        pytest.skip("sensitivity artifact not generated in this checkout")
    from apmt.repro.digest import physics_digest
    with open(ARTIFACT) as f:
        art = json.load(f)
    assert art["physics_digest"]["sha256"] == physics_digest(art)
    assert art["label"].startswith("PRE-GATE")
    assert art["levels"]["analysis"] == "L4"
    assert art["design_parameters"] == list(DESIGN_PARAMETERS)
    assert art["unreachable_regimes"], "the unreachable regimes must be recorded"
    for name, res in art["regimes"].items():
        assert res["status"] == "OK"
        assert res["level"] == "L4"
        # every regime records its own rejection accounting
        assert "registered_box_validity" in res
        assert res["registered_box_validity"]["n_total"] > 0
    for key in ("python", "numpy", "git_commit", "registry_defaults_fingerprint"):
        assert key in art["metadata"]
    # the L5 verification is present and correlates with L4
    l5 = art["l5_verification"]
    assert l5 is not None and "vs_l4_pce_pct" in l5
    assert l5["vs_l4_pce_pct"]["spearman_rank_correlation"] > 0.2
    # estimator calibration and the calibrated interaction study are part of the
    # artifact: no interaction may be reported without its measured noise floor
    ev = art["estimator_validation"]
    assert ev["pairwise_order"]["detection_floor"] > 0.02
    study = art["interaction_study"]
    assert study["detection_floor"] == ev["pairwise_order"]["detection_floor"]
    assert study["results"], "the interaction study must cover at least one regime"
    for res in study["results"].values():
        assert res["level"] == "L4"
        for per in res["per_output"].values():
            for k, v in per["reportable_pairs"].items():
                assert abs(v) >= study["detection_floor"], k
    for name, res in art["regimes"].items():
        assert res["indices"]["pce_pct"]["pairwise_indices_reportable"] is False
