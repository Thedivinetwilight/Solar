"""APMT V1.9-G — reduced-dimensional discovery protocol.

Predeclared protocol (``v19g-discovery-protocol/1.0``) for the G discovery
campaign.  This module contains ONLY declarations and deterministic helpers
(seeds, boxes, budgets, decision rules, acceptance criteria); it performs no
physics and inspects no evaluation results.  The campaign tool
``tools/v19g_discovery_campaign.py`` executes the steps in order and records
this declaration verbatim in its results artifact.

Design principles (binding on the campaign):

* The reduced subspace is chosen by the documented decision rule from
  sensitivity evidence plus the first-hand audit probe — never from the
  accuracy of any model on the final test data.
* Fixed parameters sit at registered defaults (asserted inside the verified
  box); conclusions are valid only on the resulting operating slice.
* Spatial buffers and OOD thresholds are derived from training/dev geometry
  only; final evaluation sets are generated afterwards with distinct seeds.
* No unrestricted 14-D optimization anywhere: candidate pools live on the
  operating slice, and every proposal is L4-verified before any comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

V19G_PROTOCOL_VERSION = "v19g-discovery-protocol/1.0"
V19G_SEED = 20261011
V19E_SEED = 20261009
V19F_SEED = 20261010

# ---------------------------------------------------------------------------
# phase 3: subspace decision rule inputs (thresholds are predeclared; the
# EVIDENCE values come from committed artifacts plus the step-1 audit probe)
# ---------------------------------------------------------------------------

#: Sobol total-order share (max over regimes, V1.9-D L4, N=96 x2) above which
#: an axis is active regardless of other evidence.
ST_ACTIVE_THRESHOLD = 0.03
#: OAT |dPCE| (V1.9 nominal-baseline probe, committed) above which an axis is
#: active regardless of other evidence.
OAT_ACTIVE_THRESHOLD_PP = 0.5
#: First-hand audit full-box 1-D PCE range (max over regimes) above which an
#: axis is active regardless of other evidence.
AUDIT_RANGE_THRESHOLD_PP = 0.5
#: Pairs with L4-estimated second-order index above the estimator detection
#: floor (V1.9-D interaction study: Eg x thickness = +0.234 nominal, floor
#: 0.128).  Members are kept coupled (both active).
CONFIRMED_INTERACTING_PAIRS = (("perovskite_eg_ev", "perovskite_thickness_nm"),)
#: rsh rationale check: the slice fixes rsh at its registered default
#: (saturated regime) and declares shunted designs out of scope, UNLESS the
#: audit log-sweep shows > 0.5 pp variation strictly above this floor.
RSH_SATURATED_MIN_OHM_CM2 = 1000.0

#: Axes probed on a log grid in addition to the linear grid (multi-decade
#: spans where a linear grid cannot resolve low-end structure).
AUDIT_LOG_AXES = ("rsh_ohm_cm2", "perovskite_srh_lifetime_ns", "silicon_srv_cm_s")
AUDIT_LINEAR_POINTS = 9
AUDIT_LOG_POINTS = 9

# ---------------------------------------------------------------------------
# slice campaign budgets (per regime; LHS in the verified box on active axes)
# ---------------------------------------------------------------------------
#: Amendment G-A2 (recorded before any slice evaluation): 448 matches the
#: V1.9-E nominal per-regime training count (TRAIN+ADAPTIVE_TRAIN = 448;
#: conc 443, hot 447 after invalids), giving the reduced model equivalent
#: data access to the full-dimensional reference (mission phase 3C).
SLICE_N_TRAIN = 448
SLICE_N_VALIDATION = 64
SLICE_N_CALIBRATION = 64
SLICE_N_FINAL = 96

#: Amendment G-A1 (recorded before any slice evaluation): multi-decade axes
#: are modeled, sampled, and measured in log10 once active.  The audit probe
#: forced this: rsh varies 16.7 pp full-box (0.82 pp strictly above 1000
#: ohm*cm^2, failing the predeclared saturation check) and si_srv 0.62 pp,
#: so both are active, and a linear parameterization over 3-4 decades would
#: repeat the V1.9-F raw-units lesson (all design mass where nothing
#: happens).  Scales are FIXED box transforms (leak-free by construction).
LOG_SCALE_AXES = ("rsh_ohm_cm2", "silicon_srv_cm_s", "perovskite_srh_lifetime_ns")

# ---------------------------------------------------------------------------
# OOD detector study
# ---------------------------------------------------------------------------
#: Per-indicator development false-positive cap (same bar as the historical
#: in-box false-OOD cap 0.10; applied on dev data, never on final eval).
OOD_DEV_FPR_CAP = 0.10
#: Ensemble rule: OUT_OF_DOMAIN iff >= 2 of the 3 primary indicators fire;
#: UNCERTAIN iff exactly 1 fires; VALIDATED iff 0 fire.  Box membership and
#: the physical-invariant guard override the vote (documented in classify).
OOD_PRIMARY_INDICATORS = ("knn_distance", "local_sparsity", "model_disagreement")
OOD_VOTES_FOR_OOD = 2
OOD_KNN_K = 5
OOD_DENSITY_K = 10

#: New withheld slice-corner boxes (normalized ACTIVE coordinates; first two
#: active axes constrained to 10% edges, remaining axes full range).  Mirror
#: of the V1.9-F corner style.  ACTIVE axes order is the slice order recorded
#: by the campaign; boxes apply to positions 0 and 1 (Eg, thickness).
SLICE_CORNER_BOXES = {
    "V19G_SLICE_CORNER_LO_LO": (0.00, 0.10, 0.00, 0.10),
    "V19G_SLICE_CORNER_HI_LO": (0.90, 1.00, 0.00, 0.10),
}
#: New withheld 14-D combination boxes (normalized FULL coordinates, full
#: 14-feature order): low-end shunt pathology corner and high-loss corner.
FULL_COMBO_BOXES = {
    # perovskite_eg_ev x rsh_ohm_cm2 low corner (positions 0 and 12)
    "V19G_FULL_LOEG_LORSH": {"perovskite_eg_ev": (0.00, 0.10),
                             "rsh_ohm_cm2": (0.00, 0.10)},
    # rs_ohm_cm2 x thermal_resistance high corner (positions 11 and 13)
    "V19G_FULL_HIRS_HIRTH": {"rs_ohm_cm2": (0.90, 1.00),
                             "thermal_resistance_k_cm2_w": (0.90, 1.00)},
}
N_OOD_PER_BOX_PER_REGIME = 24

# ---------------------------------------------------------------------------
# Saltelli central interaction box (tests the V1.9-F HYPOTHESIS_NOT_VALIDATED
# box [0.15, 0.85]^4 with FRESH L4 solves; no reuse of the V1.9-D design)
# ---------------------------------------------------------------------------
SALTELLI_AXES = ("perovskite_eg_ev", "perovskite_thickness_nm",
                 "rs_ohm_cm2", "arc_thickness_nm")
#: Normalized central box (fraction of the verified box per axis).
SALTELLI_CENTRAL_BOX = (0.15, 0.85)
SALTELLI_N_BASE = 256
SALTELLI_SECOND_ORDER = True
SALTELLI_BOOTSTRAP = 200
#: Convergence criterion: top-3 total-order rank order identical across the
#: two split halves AND every top-3 |ΔST| < this value.
SALTELLI_SPLIT_HALF_TOL = 0.10

# ---------------------------------------------------------------------------
# peak refinement (arc fringes + Eg control; bounded physics budget)
# ---------------------------------------------------------------------------
#: Anchors in normalized ACTIVE coordinates: slice center, high-Eg edge,
#: low-Eg edge (positions index the campaign-recorded active order).
PEAK_ANCHORS = {
    "center": "all 0.5",
    "high_eg": "axis0=0.75, rest 0.5",
    "low_eg": "axis0=0.25, rest 0.5",
}
PEAK_ARC_SCAN_POINTS = 41
PEAK_EG_SCAN_POINTS = 21
#: A candidate peak is an interior local maximum exceeding both second
#: neighbors by more than this prominence (pp).
PEAK_PROMINENCE_PP = 0.05
PEAK_MAX_REFINE = 5
PEAK_REFINE_POINTS = 9
#: Hard cap on new L4 solves for the whole peak study (all regimes).
#: Amendment G-A3: 300 -> 600.  The original cap was arithmetically
#: inconsistent with the predeclared scan design (3 regimes x (3 x 41 arc +
#: 21 Eg) = 432 scans before any refinement; max with refinement 567).
#: Recorded after a loud budget assertion (450 solves) and BEFORE any peak
#: result was examined; the scan design itself is unchanged.
PEAK_SOLVE_BUDGET = 600

# ---------------------------------------------------------------------------
# candidate selection (slice pools; identical budgets per method)
# ---------------------------------------------------------------------------
SELECTION_POOL_N = 200
SELECTION_K = 6
SELECTION_SEEDS = (20265110, 20265111, 20265112)
SELECTION_METHODS = ("random_pool_baseline",
                     "max_predicted_pce",
                     "uncertainty_aware_disagreement_ucb",
                     "diverse_top_quartile",
                     "central_box_max_predicted_pce",
                     "local_refinement_around_best")
#: UCB = pred + BETA * disagreement (beta = 1.0 replicates V1.9-F exactly).
SELECTION_UCB_BETA = 1.0
#: Method F perturbation scale (normalized active coords, clipped to box).
SELECTION_LOCAL_SIGMA = 0.02

MIN_STRATUM_POINTS = 8

# ---------------------------------------------------------------------------
# acceptance criteria
# ---------------------------------------------------------------------------
HISTORICAL_THRESHOLDS = {
    "pce_rmse_pp": 0.25,
    "single_point_speedup": 10.0,
    "withheld_recall": 0.50,
    "in_box_false_ood": 0.10,
    "conformal_coverage": 0.90,
}
#: New criteria for V1.9-G (pass/fail judged on FINAL evaluation only).
NEW_PREDECLARED_CRITERIA = {
    # reduced slice model PCE RMSE on slice FINAL (pp); the historical 0.25
    # target is ALSO reported but this phase does not re-target it.
    "G_SLICE_ERR": 0.50,
    # reduced model beats the full-dimensional reference on slice Final:
    # paired-bootstrap 95% CI of (full - reduced) RMSE must exclude 0 below.
    "G_SLICE_BEATS_FULL": "paired bootstrap dRMSE(full-reduced) CI lower bound > 0",
    # ensemble OOD recall on NEW withheld slice corners with dev-set FPR cap.
    "G_OOD_RECALL": 0.50,
    "G_OOD_FPR_CAP": 0.10,
    # replication of the V1.9-F region-finding result on the slice: guided
    # methods' median best-verified >= random's in at least 7/9 regime-seeds.
    "G_SELECT_REPLICATION": "guided >= random in >=7/9 regime-seeds, 0 losses worse",
    # Saltelli split-half stability (see SALTELLI_SPLIT_HALF_TOL).
    "G_SALTELLI_STABLE": "top-3 rank order identical across halves, |dST| < 0.10",
}


def apply_subspace_rule(*, st_max: Mapping[str, float],
                        oat_pp: Mapping[str, float],
                        audit_range_pp: Mapping[str, float],
                        rsh_above_floor_range_pp: float,
                        feature_order: Sequence[str]) -> dict:
    """Apply the predeclared subspace decision rule (phase 3B).

    Every axis is judged ONLY on sensitivity/audit evidence.  No model
    accuracy on any test set enters this decision.  Returns the active set,
    the fixed set, and the per-axis rationale trace.
    """
    pair_members = {n for pair in CONFIRMED_INTERACTING_PAIRS for n in pair}
    active, fixed, trace = [], [], {}
    for name in feature_order:
        reasons = []
        if st_max.get(name, 0.0) > ST_ACTIVE_THRESHOLD:
            reasons.append(f"ST({st_max[name]:.3f})>0.03")
        if oat_pp.get(name, 0.0) > OAT_ACTIVE_THRESHOLD_PP:
            reasons.append(f"OAT({oat_pp[name]:.2f}pp)>0.5")
        if audit_range_pp.get(name, 0.0) > AUDIT_RANGE_THRESHOLD_PP:
            reasons.append(f"audit({audit_range_pp[name]:.2f}pp)>0.5")
        if name in pair_members:
            reasons.append("confirmed-pair-member")
        if name == "rsh_ohm_cm2":
            if rsh_above_floor_range_pp > AUDIT_RANGE_THRESHOLD_PP:
                reasons.append(f"rsh-check-failed({rsh_above_floor_range_pp:.2f}pp)>0.5")
                active.append(name)
            else:
                fixed.append(name)
                trace[name] = {"decision": "FIXED",
                               "rationale": "shunt-pathology out of slice scope; "
                                            f"log-sweep above {RSH_SATURATED_MIN_OHM_CM2:g} = "
                                            f"{rsh_above_floor_range_pp:.3f} pp <= 0.5",
                               "triggered": reasons}
            continue
        if reasons:
            active.append(name)
        else:
            fixed.append(name)
        trace[name] = {"decision": "ACTIVE" if reasons else "FIXED",
                       "triggered": reasons}
    return {"active": active, "fixed": fixed, "trace": trace,
            "rule": {"ST": ST_ACTIVE_THRESHOLD, "OAT_pp": OAT_ACTIVE_THRESHOLD_PP,
                     "audit_pp": AUDIT_RANGE_THRESHOLD_PP,
                     "pairs": [list(p) for p in CONFIRMED_INTERACTING_PAIRS],
                     "rsh_floor": RSH_SATURATED_MIN_OHM_CM2}}


def axis_scale(name: str) -> str:
    """Fixed feature scale for an active axis ('log10' or 'linear')."""
    return "log10" if name in LOG_SCALE_AXES else "linear"


def scaled_box(low: float, high: float, name: str) -> tuple[float, float]:
    """Physical box endpoints mapped to feature (scaled) coordinates."""
    import math

    if axis_scale(name) == "log10":
        return math.log10(low), math.log10(high)
    return float(low), float(high)


def assert_on_slice(x_full: Mapping[str, float], fixed_values: Mapping[str, float],
                    tol: float = 1e-9) -> None:
    """Raise unless every fixed parameter equals its slice value."""
    for name, value in fixed_values.items():
        got = float(x_full[name])
        if abs(got - float(value)) > tol:
            raise ValueError(f"off-slice query: {name}={got} != slice {value}")


def knn_distance(Z_eval: np.ndarray, Z_train: np.ndarray, k: int = OOD_KNN_K) -> np.ndarray:
    """Mean distance to the k nearest training points (normalized coords)."""
    d = np.linalg.norm(Z_eval[:, None, :] - Z_train[None, :, :], axis=2)
    k = min(k, d.shape[1])
    return np.mean(np.partition(d, k - 1, axis=1)[:, :k], axis=1)


def local_sparsity(Z_eval: np.ndarray, Z_train: np.ndarray,
                   radius: float, k: int = OOD_DENSITY_K) -> np.ndarray:
    """Local sparsity: k-NN mean distance divided by the buffer radius.

    Values > 1 mark neighborhoods sparser than the training-typical scale.
    """
    return knn_distance(Z_eval, Z_train, k=k) / float(radius)


def boundary_margin(Z_eval: np.ndarray) -> np.ndarray:
    """Minimum normalized margin to any box face (0 = on the boundary)."""
    return np.minimum(Z_eval.min(axis=1), 1.0 - Z_eval.max(axis=1))


def disagreement_indicator(pred_stack: np.ndarray) -> np.ndarray:
    """Sample std across [selected + alternatives] (V1.9-F definition)."""
    pred_stack = np.asarray(pred_stack, float)
    if pred_stack.shape[1] < 2:
        return np.zeros(pred_stack.shape[0], float)
    return np.std(pred_stack, axis=1, ddof=1)


def fit_ood_thresholds(dev_indicators: Mapping[str, np.ndarray],
                        fpr_cap: float = OOD_DEV_FPR_CAP) -> dict[str, float]:
    """Per-indicator thresholds at the (1 - fpr_cap) dev quantile.

    Higher indicator values = less supported.  Dev data must be in-box
    non-final rows; final evaluation data must NEVER enter here.
    """
    out = {}
    for name, vals in dev_indicators.items():
        vals = np.asarray(vals, float)
        if len(vals) == 0:
            raise ValueError(f"empty dev indicator vector: {name}")
        out[name] = float(np.quantile(vals, 1.0 - fpr_cap))
    return out


def classify_ood_votes(indicators: Mapping[str, float],
                       thresholds: Mapping[str, float]) -> dict:
    """Apply the predeclared >=2-of-3 ensemble rule to one query."""
    votes = {n: bool(indicators[n] > thresholds[n]) for n in OOD_PRIMARY_INDICATORS}
    n_fire = sum(votes.values())
    if n_fire >= OOD_VOTES_FOR_OOD:
        status = "OUT_OF_DOMAIN"
    elif n_fire == 1:
        status = "IN_DOMAIN_UNCERTAIN"
    else:
        status = "IN_DOMAIN_VALIDATED"
    return {"status": status, "votes": votes, "n_votes": n_fire}


def find_local_maxima(x: np.ndarray, y: np.ndarray,
                      prominence_pp: float = PEAK_PROMINENCE_PP) -> list[int]:
    """Interior local maxima exceeding both second neighbors by prominence."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    order = np.argsort(x, kind="stable")
    ys = y[order]
    peaks = []
    for i in range(2, len(ys) - 2):
        local = ys[i] > ys[i - 1] and ys[i] >= ys[i + 1]
        prom = ys[i] - ys[i - 2] > prominence_pp and ys[i] - ys[i + 2] > prominence_pp
        if local and prom:
            peaks.append(int(order[i]))
    return peaks


def spearman_rank_corrcoef(a: Sequence[float], b: Sequence[float]) -> float | None:
    """V1.9-F rank-correlation definition (average ranks NOT used; replicate)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return None
    ra = np.argsort(np.argsort(a, kind="stable"), kind="stable")
    rb = np.argsort(np.argsort(b, kind="stable"), kind="stable")
    with np.errstate(all="ignore"):
        c = np.corrcoef(ra, rb)[0, 1]
    return None if not np.isfinite(c) else float(c)


def wilson_ci(k: int, n: int) -> dict:
    """95% Wilson score interval for a binomial rate (or INSUFFICIENT_DATA)."""
    import math

    from apmt.surrogate.spatial import MIN_STRATUM_POINTS as _MIN_N

    if n < _MIN_N:
        return {"status": "INSUFFICIENT_DATA", "n": n}
    z = 1.959963984540054
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return {"rate": p, "ci_95_low": max(0.0, center - half),
            "ci_95_high": min(1.0, center + half), "n": n, "k": k}


def paired_bootstrap_rmse_diff(e_a, e_b, seed: int, n_boot: int = 2000) -> dict:
    """Paired bootstrap of RMSE(a) - RMSE(b); diff, CI, P(a <= b)."""
    e_a = np.asarray(e_a, float)
    e_b = np.asarray(e_b, float)
    n = len(e_a)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    diffs = np.sqrt(np.mean(e_a[idx], axis=1)) - np.sqrt(np.mean(e_b[idx], axis=1))
    return {"rmse_difference": float(np.sqrt(np.mean(e_a)) - np.sqrt(np.mean(e_b))),
            "ci_95_low": float(np.quantile(diffs, 0.025)),
            "ci_95_high": float(np.quantile(diffs, 0.975)),
            "prob_a_not_worse_than_b": float(np.mean(diffs <= 0.0)),
            "n_bootstrap": n_boot}


def split_saltelli_design(design, take_even: bool):
    """Even/odd split-half of a Saltelli design (same estimator, N/2 rows)."""
    from apmt.sensitivity.sobol import SaltelliDesign

    n = design.n_base
    idx = np.arange(n)[0::2] if take_even else np.arange(n)[1::2]
    ba = design.BA[:, idx, :] if design.BA is not None else None
    return SaltelliDesign(names=design.names, n_base=len(idx), low=design.low,
                          high=design.high, A=design.A[idx], B=design.B[idx],
                          AB=design.AB[:, idx, :], BA=ba, seed=design.seed)


def protocol_declaration() -> dict:
    """Verbatim predeclared protocol record for the results artifact."""
    return {
        "protocol_version": V19G_PROTOCOL_VERSION,
        "seed_root": V19G_SEED,
        "subspace_rule": {"ST_threshold": ST_ACTIVE_THRESHOLD,
                          "OAT_threshold_pp": OAT_ACTIVE_THRESHOLD_PP,
                          "audit_threshold_pp": AUDIT_RANGE_THRESHOLD_PP,
                          "confirmed_pairs": [list(p) for p in CONFIRMED_INTERACTING_PAIRS],
                          "rsh_floor": RSH_SATURATED_MIN_OHM_CM2,
                          "rsh_note": "fixed at default unless log-sweep above floor > 0.5 pp"},
        "audit": {"linear_points": AUDIT_LINEAR_POINTS, "log_points": AUDIT_LOG_POINTS,
                  "log_axes": list(AUDIT_LOG_AXES)},
        "slice_campaign": {"n_train": SLICE_N_TRAIN, "n_validation": SLICE_N_VALIDATION,
                           "n_calibration": SLICE_N_CALIBRATION, "n_final": SLICE_N_FINAL},
        "ood": {"dev_fpr_cap": OOD_DEV_FPR_CAP, "rule": ">=2 of 3 primary fire",
                "primary": list(OOD_PRIMARY_INDICATORS), "k": OOD_KNN_K,
                "density_k": OOD_DENSITY_K,
                "slice_corners": {k: list(v) for k, v in SLICE_CORNER_BOXES.items()},
                "full_combos": {k: {a: list(v) for a, v in b.items()}
                                for k, b in FULL_COMBO_BOXES.items()},
                "n_per_box_per_regime": N_OOD_PER_BOX_PER_REGIME},
        "saltelli": {"axes": list(SALTELLI_AXES),
                     "central_box_normalized": list(SALTELLI_CENTRAL_BOX),
                     "n_base": SALTELLI_N_BASE, "second_order": SALTELLI_SECOND_ORDER,
                     "bootstrap": SALTELLI_BOOTSTRAP,
                     "split_half_tol": SALTELLI_SPLIT_HALF_TOL},
        "peaks": {"anchors": PEAK_ANCHORS, "arc_points": PEAK_ARC_SCAN_POINTS,
                  "eg_points": PEAK_EG_SCAN_POINTS, "prominence_pp": PEAK_PROMINENCE_PP,
                  "max_refine": PEAK_MAX_REFINE, "refine_points": PEAK_REFINE_POINTS,
                  "solve_budget": PEAK_SOLVE_BUDGET},
        "selection": {"pool_n": SELECTION_POOL_N, "k": SELECTION_K,
                      "seeds": list(SELECTION_SEEDS), "methods": list(SELECTION_METHODS),
                      "ucb_beta": SELECTION_UCB_BETA, "local_sigma": SELECTION_LOCAL_SIGMA},
        "min_stratum_points": MIN_STRATUM_POINTS,
        "log_scale_axes": list(LOG_SCALE_AXES),
        "amendments": [
            {"id": "G-A1", "when": "after step-1 audit, before any slice physics",
             "change": "log10 feature/sampling/distance scale for multi-decade "
                       "active axes (rsh, si_srv)",
             "reason": "audit forced rsh+si_srv active (16.7/0.62 pp); linear "
                       "parameterization over 3-4 decades is indefensible",
             "leakage": "none: fixed box transforms, no test data existed"},
            {"id": "G-A2", "when": "after step-1 audit, before any slice physics",
             "change": "SLICE_N_TRAIN 300 -> 448",
             "reason": "equivalent data access to the V1.9-E reference "
                       "(nominal TRAIN+ADAPTIVE_TRAIN = 448)",
             "leakage": "none: no test data existed"},
            {"id": "G-A3", "when": "after loud budget assertion, before any "
                                   "peak result examined",
             "change": "PEAK_SOLVE_BUDGET 300 -> 600",
             "reason": "original cap inconsistent with the predeclared scan "
                       "design (432 scans + <=135 refinements = 567 max)",
             "leakage": "none: scan design unchanged, no peak seen"},
        ],
        "historical_thresholds": HISTORICAL_THRESHOLDS,
        "new_predeclared_criteria": NEW_PREDECLARED_CRITERIA,
        "role_discipline": ("audit/slice/saltelli/peak/select/ood rows carry V19G_* roles; "
                            "V1.9-E FINAL rows never fit or select; G slice FINAL rows "
                            "never fit, select, or set thresholds"),
    }
