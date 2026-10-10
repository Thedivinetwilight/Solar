"""V1.9-G — reduced-dimensional discovery protocol tests.

All tests are pure-data/synthetic (no physics solves): they pin the
predeclared subspace rule, feature scales, OOD ensemble, peak finder,
selection budgets, Saltelli handling, and statistics helpers.
"""
import pickle
import warnings

import numpy as np
import pytest

from apmt.sensitivity.sobol import saltelli_design, sobol_indices
from apmt.surrogate.data import dataset_fingerprint, mark_duplicates
from apmt.surrogate.discovery import (
    FULL_COMBO_BOXES,
    HISTORICAL_THRESHOLDS,
    LOG_SCALE_AXES,
    NEW_PREDECLARED_CRITERIA,
    OOD_PRIMARY_INDICATORS,
    PEAK_PROMINENCE_PP,
    SALTELLI_CENTRAL_BOX,
    SELECTION_K,
    SELECTION_LOCAL_SIGMA,
    SELECTION_METHODS,
    SELECTION_POOL_N,
    SELECTION_UCB_BETA,
    SLICE_CORNER_BOXES,
    apply_subspace_rule,
    assert_on_slice,
    axis_scale,
    boundary_margin,
    classify_ood_votes,
    disagreement_indicator,
    find_local_maxima,
    fit_ood_thresholds,
    knn_distance,
    local_sparsity,
    paired_bootstrap_rmse_diff,
    protocol_declaration,
    scaled_box,
    spearman_rank_corrcoef,
    split_saltelli_design,
    wilson_ci,
)
from apmt.surrogate.models import fit_regressor
from apmt.surrogate.spatial import assert_role_separation, training_buffer_radius


def test_protocol_declaration_is_complete_and_versioned():
    decl = protocol_declaration()
    assert decl["protocol_version"].startswith("v19g-discovery-protocol/")
    for key in ("seed_root", "subspace_rule", "audit", "slice_campaign", "ood",
                "saltelli", "peaks", "selection", "historical_thresholds",
                "new_predeclared_criteria", "role_discipline", "amendments"):
        assert key in decl, key
    assert decl["seed_root"] == 20261011
    assert {a["id"] for a in decl["amendments"]} == {"G-A1", "G-A2", "G-A3"}
    for crit in ("G_SLICE_ERR", "G_SLICE_BEATS_FULL", "G_OOD_RECALL",
                 "G_OOD_FPR_CAP", "G_SELECT_REPLICATION", "G_SALTELLI_STABLE"):
        assert crit in NEW_PREDECLARED_CRITERIA, crit


def test_historical_thresholds_unchanged():
    assert HISTORICAL_THRESHOLDS["pce_rmse_pp"] == 0.25
    assert HISTORICAL_THRESHOLDS["single_point_speedup"] == 10.0
    assert HISTORICAL_THRESHOLDS["withheld_recall"] == 0.50
    assert HISTORICAL_THRESHOLDS["in_box_false_ood"] == 0.10
    assert HISTORICAL_THRESHOLDS["conformal_coverage"] == 0.90


def test_subspace_rule_each_trigger_activates():
    order = ["a_st", "a_oat", "a_audit", "a_pair", "quiet"]
    out = apply_subspace_rule(
        st_max={"a_st": 0.5}, oat_pp={"a_oat": 2.0},
        audit_range_pp={"a_audit": 3.0}, rsh_above_floor_range_pp=0.0,
        feature_order=order)
    # 'a_pair' is not a confirmed pair member, so it stays fixed here.
    assert out["active"] == ["a_st", "a_oat", "a_audit"]
    assert out["fixed"] == ["a_pair", "quiet"]
    out2 = apply_subspace_rule(
        st_max={}, oat_pp={}, audit_range_pp={},
        rsh_above_floor_range_pp=0.0,
        feature_order=["perovskite_eg_ev", "quiet"])
    assert out2["active"] == ["perovskite_eg_ev"]
    assert out2["trace"]["perovskite_eg_ev"]["triggered"] == ["confirmed-pair-member"]


def test_subspace_rule_rsh_exception_both_branches():
    low = apply_subspace_rule(
        st_max={"rsh_ohm_cm2": 0.0}, oat_pp={}, audit_range_pp={"rsh_ohm_cm2": 9.0},
        rsh_above_floor_range_pp=0.1, feature_order=["rsh_ohm_cm2"])
    assert low["fixed"] == ["rsh_ohm_cm2"]
    assert "shunt-pathology" in low["trace"]["rsh_ohm_cm2"]["rationale"]
    high = apply_subspace_rule(
        st_max={}, oat_pp={}, audit_range_pp={},
        rsh_above_floor_range_pp=0.9, feature_order=["rsh_ohm_cm2"])
    assert high["active"] == ["rsh_ohm_cm2"]


def test_axis_scales_and_scaled_box():
    assert axis_scale("rsh_ohm_cm2") == "log10"
    assert axis_scale("silicon_srv_cm_s") == "log10"
    assert axis_scale("perovskite_eg_ev") == "linear"
    assert set(LOG_SCALE_AXES) == {"rsh_ohm_cm2", "silicon_srv_cm_s",
                                   "perovskite_srh_lifetime_ns"}
    lo, hi = scaled_box(50.0, 1e6, "rsh_ohm_cm2")
    assert (lo, hi) == pytest.approx((np.log10(50.0), 6.0))
    assert scaled_box(1.4, 2.0, "perovskite_eg_ev") == (1.4, 2.0)


def test_assert_on_slice():
    assert_on_slice({"a": 1.0, "b": 2.0}, {"b": 2.0})
    assert_on_slice({"b": 2.0 + 1e-12}, {"b": 2.0})
    with pytest.raises(ValueError, match="off-slice"):
        assert_on_slice({"b": 2.1}, {"b": 2.0})


def test_knn_distance_known_answer():
    z_tr = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    d = knn_distance(np.array([[0.0, 0.0]]), z_tr, k=2)
    assert d == pytest.approx([0.5])
    # k is clamped to the reference size.
    d_all = knn_distance(np.array([[0.0, 0.0]]), z_tr, k=99)
    assert d_all == pytest.approx([(0.0 + 1.0 + 1.0) / 3.0])


def test_local_sparsity_known_answer():
    z_tr = np.array([[0.0], [1.0]])
    s = local_sparsity(np.array([[0.0], [5.0]]), z_tr, radius=1.0, k=2)
    assert s[0] == pytest.approx(0.5)
    assert s[1] > 1.0


def test_boundary_margin_known_answer():
    z = np.array([[0.5, 0.5], [0.0, 0.9], [0.2, 1.0]])
    assert boundary_margin(z) == pytest.approx([0.5, 0.0, 0.0])


def test_disagreement_indicator_known_answer():
    stack = np.array([[1.0, 3.0], [2.0, 2.0]])
    assert disagreement_indicator(stack) == pytest.approx([np.sqrt(2.0), 0.0])
    assert disagreement_indicator(np.array([[1.0], [2.0]])) == pytest.approx([0.0, 0.0])


def test_fit_ood_thresholds_quantile_and_empty():
    vals = np.arange(100, dtype=float)
    thr = fit_ood_thresholds({"knn_distance": vals}, 0.10)
    assert thr["knn_distance"] == pytest.approx(np.quantile(vals, 0.90))
    with pytest.raises(ValueError, match="empty"):
        fit_ood_thresholds({"knn_distance": np.array([])}, 0.10)


def test_classify_ood_votes_rule():
    thr = {"knn_distance": 1.0, "local_sparsity": 1.0, "model_disagreement": 1.0}
    assert len(OOD_PRIMARY_INDICATORS) == 3
    v0 = classify_ood_votes({"knn_distance": 0.1, "local_sparsity": 0.1,
                              "model_disagreement": 0.1}, thr)
    assert (v0["status"], v0["n_votes"]) == ("IN_DOMAIN_VALIDATED", 0)
    v1 = classify_ood_votes({"knn_distance": 9.0, "local_sparsity": 0.1,
                              "model_disagreement": 0.1}, thr)
    assert (v1["status"], v1["n_votes"]) == ("IN_DOMAIN_UNCERTAIN", 1)
    v2 = classify_ood_votes({"knn_distance": 9.0, "local_sparsity": 9.0,
                              "model_disagreement": 0.1}, thr)
    assert (v2["status"], v2["n_votes"]) == ("OUT_OF_DOMAIN", 2)
    v3 = classify_ood_votes({"knn_distance": 9.0, "local_sparsity": 9.0,
                              "model_disagreement": 9.0}, thr)
    assert v3["status"] == "OUT_OF_DOMAIN"


def test_find_local_maxima_known_answer():
    x = np.arange(10, dtype=float)
    y = np.array([0, 1, 2, 3, 5, 3, 2, 4, 2, 1], dtype=float)
    assert find_local_maxima(x, y) == [4, 7]
    assert PEAK_PROMINENCE_PP == 0.05
    # below-prominence bump is ignored.
    assert find_local_maxima(x, np.ones(10)) == []
    # unsorted input returns indices into the original arrays.
    xs = np.array([3.0, 1.0, 2.0, 0.0, 4.0, 5.0, 6.0])
    ys = np.array([5.0, 1.0, 3.0, 0.0, 1.0, 0.0, 0.0])
    assert find_local_maxima(xs, ys) == [0]


def test_spearman_rank_corrcoef_known_answers():
    assert spearman_rank_corrcoef([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman_rank_corrcoef([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    # ties receive positional ranks under the replicated V1.9-F definition
    # (stable argsort), so a tied input still correlates rather than NaN.
    assert spearman_rank_corrcoef([1, 1, 1], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman_rank_corrcoef([1], [1]) is None


def test_wilson_ci_properties():
    w = wilson_ci(50, 100)
    assert w["rate"] == pytest.approx(0.5)
    assert 0.0 < w["ci_95_low"] < 0.5 < w["ci_95_high"] < 1.0
    narrow = wilson_ci(500, 1000)
    assert (narrow["ci_95_high"] - narrow["ci_95_low"]) < (
        w["ci_95_high"] - w["ci_95_low"])
    assert wilson_ci(0, 5)["status"] == "INSUFFICIENT_DATA"
    assert wilson_ci(8, 8)["rate"] == pytest.approx(1.0)


def test_paired_bootstrap_rmse_diff_known_answers():
    e = np.array([1.0, 4.0, 9.0, 16.0])
    same = paired_bootstrap_rmse_diff(e, e, seed=11, n_boot=200)
    assert same["rmse_difference"] == pytest.approx(0.0)
    assert same["ci_95_low"] == pytest.approx(0.0)
    assert same["ci_95_high"] == pytest.approx(0.0)
    assert same["prob_a_not_worse_than_b"] == pytest.approx(1.0)
    again = paired_bootstrap_rmse_diff(e, e, seed=11, n_boot=200)
    assert again == same
    worse = paired_bootstrap_rmse_diff(e, 4.0 * e, seed=11, n_boot=200)
    assert worse["rmse_difference"] < 0.0
    assert worse["prob_a_not_worse_than_b"] == pytest.approx(1.0)


def test_split_saltelli_design_partitions_rows():
    design = saltelli_design(("a", "b"), n_base=8, low=np.zeros(2),
                             high=np.ones(2), seed=3, second_order=True)
    assert design.n_blocks == 2 + 2 * 2
    h0 = split_saltelli_design(design, True)
    h1 = split_saltelli_design(design, False)
    assert (h0.n_base, h1.n_base) == (4, 4)
    both_a = np.vstack([h0.A, h1.A])
    key = lambda m: sorted(map(tuple, np.round(m, 12).tolist()))
    assert key(both_a) == key(design.A)
    assert split_saltelli_design(design, True).fingerprint() == h0.fingerprint()


def test_corner_boxes_wellformed():
    for name, box in SLICE_CORNER_BOXES.items():
        assert len(box) == 4
        assert all(0.0 <= v <= 1.0 for v in box), name
        assert (box[1] - box[0]) == pytest.approx(0.10)
        assert (box[3] - box[2]) == pytest.approx(0.10)
    assert set(SLICE_CORNER_BOXES) == {"V19G_SLICE_CORNER_LO_LO",
                                       "V19G_SLICE_CORNER_HI_LO"}
    assert set(FULL_COMBO_BOXES) == {"V19G_FULL_LOEG_LORSH", "V19G_FULL_HIRS_HIRTH"}
    for name, constrained in FULL_COMBO_BOXES.items():
        assert len(constrained) == 2, name
        for lo, hi in constrained.values():
            assert 0.0 <= lo < hi <= 1.0
            assert (hi - lo) == pytest.approx(0.10)


def test_saltelli_central_box_declared():
    assert SALTELLI_CENTRAL_BOX == (0.15, 0.85)


def test_training_buffer_known_answer_1d():
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    assert training_buffer_radius(x) == pytest.approx(1.0)
    assert training_buffer_radius(x) == training_buffer_radius(x)


def test_role_separation_guard():
    assert_role_separation({"A", "B"}, {"C"})
    with pytest.raises(ValueError, match="role leakage"):
        assert_role_separation({"A", "B"}, {"B", "C"})


def test_saltelli_design_deterministic_blocks():
    kw = {"names": ("x", "y", "z"), "n_base": 16, "low": np.zeros(3),
          "high": np.ones(3), "seed": 9, "second_order": True}
    d1 = saltelli_design(**kw)
    d2 = saltelli_design(**kw)
    assert d1.fingerprint() == d2.fingerprint()
    assert d1.matrix().shape == (d1.n_blocks * 16, 3)
    assert d1.n_blocks == 2 + 2 * 3


def test_sobol_degenerate_and_missing_flags():
    design = saltelli_design(("x", "y"), n_base=16, low=np.zeros(2),
                             high=np.ones(2), seed=5, second_order=False)
    n = design.n_blocks * design.n_base
    const = sobol_indices(np.full(n, 3.0), design, output="t", bootstrap=50)
    assert const.degenerate and not const.complete
    y = np.linspace(0.0, 1.0, n)
    y[::7] = np.nan
    miss = sobol_indices(y, design, output="t", bootstrap=50)
    assert not miss.complete and miss.n_missing > 0


def test_mark_duplicates_flags_repeats():
    rows = [{"sample_id": "s1", "status": "VALID_FOR_SURROGATE",
             "parameters": {"p": 1.0}, "operating_regime": {"name": "r"},
             "model_level": "L4", "model_form": "M", "physics_digest": "d"},
            {"sample_id": "s2", "status": "VALID_FOR_SURROGATE",
             "parameters": {"p": 1.0}, "operating_regime": {"name": "r"},
             "model_level": "L4", "model_form": "M", "physics_digest": "d"}]
    out = mark_duplicates(rows)
    assert out[0]["status"] == "VALID_FOR_SURROGATE"
    assert out[1]["status"] == "DUPLICATE_OR_DEPENDENT"
    assert out[1]["duplicate_of"] == "s1"


def test_dataset_fingerprint_reorder_stable():
    rows = [{"sample_id": f"s{i}", "status": "VALID_FOR_SURROGATE",
             "input_fingerprint": f"f{i}", "parameters": {"p": float(i)},
             "operating_regime": {"name": "r"}, "model_level": "L4",
             "role": "TRAIN", "outputs": {"pce_pct": float(i)}}
            for i in range(5)]
    assert dataset_fingerprint(rows) == dataset_fingerprint(rows[::-1])


def test_model_serialization_roundtrip_identical():
    rng = np.random.default_rng(0)
    x = rng.random((24, 2))
    y = 3.0 * x[:, 0] - x[:, 1] ** 2
    low = np.zeros(2)
    high = np.ones(2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        et = fit_regressor("extra_trees", x, y, feature_names=("a", "b"),
                           target_name="pce_pct", unit="%",
                           training_fingerprint="test", seed=1)
        gp = fit_regressor("gaussian_process_matern_boxnorm", x, y,
                           feature_names=("a", "b"), target_name="pce_pct",
                           unit="%", training_fingerprint="test", seed=1,
                           bounds=(low, high))
    for model in (et, gp):
        blob = pickle.dumps(model)
        back = pickle.loads(blob)
        p0, _ = model.predict(x, return_std=False)
        p1, _ = back.predict(x, return_std=False)
        np.testing.assert_allclose(p0, p1, rtol=0, atol=0)


def test_selection_budget_structure():
    assert SELECTION_METHODS == ("random_pool_baseline",
                                 "max_predicted_pce",
                                 "uncertainty_aware_disagreement_ucb",
                                 "diverse_top_quartile",
                                 "central_box_max_predicted_pce",
                                 "local_refinement_around_best")
    assert SELECTION_POOL_N == 200
    assert SELECTION_K == 6
    assert SELECTION_UCB_BETA == 1.0
    assert SELECTION_LOCAL_SIGMA == 0.02
