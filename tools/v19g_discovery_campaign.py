#!/usr/bin/env python3
"""V1.9-G reduced-dimensional discovery system.

Reads the committed V1.9-E/F evidence (never mutates it), runs a first-hand
parameter audit probe, applies the predeclared subspace rule, builds an
operating-slice campaign (train/validation/calibration/final), compares the
reduced model against the full-dimensional reference and simple baselines,
develops and independently evaluates an OOD indicator ensemble, runs a fresh
Saltelli study of the V1.9-F central interaction box, investigates narrow
peaks, and compares candidate-selection methods under equal L4 budgets.

Writes:

* ``data/v19g_discovery_results.json`` — machine-readable findings;
* ``data/v19g_new_rows.json.gz`` — new physics rows with full provenance.

Exit code 0 = complete.  Negative results are recorded, not hidden.
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from apmt.sensitivity.campaign import REGIMES
from apmt.sensitivity.sobol import saltelli_design, sobol_indices
from apmt.surrogate import campaign as vc
from apmt.surrogate.data import (
    INVALID_PHYSICS,
    VALID_FOR_SURROGATE,
    dataset_fingerprint,
    load_dataset,
    mark_duplicates,
    save_dataset,
)
from apmt.surrogate.discovery import (
    AUDIT_LINEAR_POINTS,
    AUDIT_LOG_AXES,
    AUDIT_LOG_POINTS,
    FULL_COMBO_BOXES,
    MIN_STRATUM_POINTS,
    N_OOD_PER_BOX_PER_REGIME,
    OOD_DENSITY_K,
    OOD_DEV_FPR_CAP,
    OOD_KNN_K,
    PEAK_ANCHORS,
    PEAK_ARC_SCAN_POINTS,
    PEAK_EG_SCAN_POINTS,
    PEAK_MAX_REFINE,
    PEAK_REFINE_POINTS,
    PEAK_SOLVE_BUDGET,
    RSH_SATURATED_MIN_OHM_CM2,
    SALTELLI_AXES,
    SALTELLI_BOOTSTRAP,
    SALTELLI_CENTRAL_BOX,
    SALTELLI_N_BASE,
    SALTELLI_SECOND_ORDER,
    SALTELLI_SPLIT_HALF_TOL,
    SELECTION_K,
    SELECTION_LOCAL_SIGMA,
    SELECTION_METHODS,
    SELECTION_POOL_N,
    SELECTION_SEEDS,
    SELECTION_UCB_BETA,
    SLICE_CORNER_BOXES,
    SLICE_N_CALIBRATION,
    SLICE_N_FINAL,
    SLICE_N_TRAIN,
    SLICE_N_VALIDATION,
    V19E_SEED,
    V19G_SEED,
    apply_subspace_rule,
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
from apmt.surrogate.domain import (
    IN_DOMAIN_UNCERTAIN,
    IN_DOMAIN_VALIDATED,
    OUT_OF_DOMAIN,
)
from apmt.surrogate.models import (
    MODEL_FAMILIES_V19F,
    compare_families,
    conformal_radius,
    select_family,
)
from apmt.surrogate.spatial import (
    assert_role_separation,
    denormalize,
    distance_to_training,
    lhs_in_normalized_box,
    summarize_distances,
    training_buffer_radius,
)

SEED = V19G_SEED
COMMITTED_DATASET = ROOT / "data" / "v19e_surrogate_dataset_v3.json.gz"
COMMITTED_RESULTS = ROOT / "data" / "v19e_surrogate_results_v3.json"
COMMITTED_V19F_ROWS = ROOT / "data" / "v19f_new_rows.json.gz"
SENSITIVITY_ARTIFACT = ROOT / "data" / "v19_sensitivity.json"
OAT_ARTIFACT = ROOT / "data" / "v19_oat_sensitivity.json"
DEFAULT_RESULTS_PATH = ROOT / "data" / "v19g_discovery_results.json"
DEFAULT_NEW_ROWS_PATH = ROOT / "data" / "v19g_new_rows.json.gz"

REGIME_NAMES = tuple(r.name for r in REGIMES)
N_BOOT = 2000


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _rows(recs, *, regime, roles):
    return [r for r in recs
            if r.get("operating_regime", {}).get("name") == regime
            and r.get("role") in roles
            and r.get("status") == VALID_FOR_SURROGATE
            and r.get("model_level") == "L4"]


def _matrix(rows, names):
    return np.asarray([[float(r["parameters"][n]) for n in names] for r in rows], float)


def _targets(rows, target="pce_pct"):
    return np.asarray([float(r["outputs"][target]) for r in rows], float)


def _rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2)))


def _mae(y, p):
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(p, float))))


def _scaled_box_arrays(active, low_map, high_map):
    """Per-active-axis feature transform: log10 mask + scaled box arrays."""
    is_log = np.array([axis_scale(n) == "log10" for n in active])
    boxes = [scaled_box(low_map[n], high_map[n], n) for n in active]
    low_s = np.array([b[0] for b in boxes], float)
    high_s = np.array([b[1] for b in boxes], float)
    return is_log, low_s, high_s


def _to_scaled(X_phys, is_log):
    X = np.asarray(X_phys, float)
    if X.size == 0:
        return np.empty((0, len(is_log)), float)
    X = X.copy()
    if is_log.any():
        X[:, is_log] = np.log10(X[:, is_log])
    return X


def _phys_from_z01(Z, low_s, high_s, is_log):
    S = np.asarray(Z, float) * (high_s - low_s) + low_s
    if is_log.any():
        S[:, is_log] = 10.0 ** S[:, is_log]
    return S


def _znorm_scaled(X_phys, low_s, high_s, is_log):
    return (_to_scaled(X_phys, is_log) - low_s) / (high_s - low_s)


# --------------------------------------------------------------------------
# step 0: load committed evidence, verify integrity
# --------------------------------------------------------------------------
def step_verify():
    ds = load_dataset(COMMITTED_DATASET)
    committed = json.loads(COMMITTED_RESULTS.read_text())
    sens = json.loads(SENSITIVITY_ARTIFACT.read_text())
    oat = json.loads(OAT_ARTIFACT.read_text())
    frows = load_dataset(COMMITTED_V19F_ROWS)
    recs = mark_duplicates(ds["valid_records"] + ds["rejection_ledger"])
    assert ds["dataset_fingerprint"] == committed["data_contract"]["dataset_fingerprint"]
    assert dataset_fingerprint(recs) == ds["dataset_fingerprint"]
    assert dataset_fingerprint(frows["valid_records"]) == frows["dataset_fingerprint"]
    code_digest, _files = vc._physics_code_digest()
    reg_digest = vc._registry_digest()
    assert committed["metadata"]["physics_source_digest"] == code_digest
    fn = list(ds["valid_records"][0]["feature_names"])
    low_map = {n: float(sens["shared_box"]["low"][n]) for n in fn}
    high_map = {n: float(sens["shared_box"]["high"][n]) for n in fn}
    low = np.array([low_map[n] for n in fn], float)
    high = np.array([high_map[n] for n in fn], float)
    # V1.9-F baseline sanity: committed selections and 7-way validation table.
    expect = {"concentrated_3sun_25c": "extra_trees",
              "hot_ambient_1sun_65c": "hist_gradient_boosting",
              "nominal_1sun_25c": "hist_gradient_boosting"}
    for regime, fam in expect.items():
        got = committed["model_comparison"][regime]["pce_pct"][
            "selected_family_by_independent_validation"]
        assert got == fam, (regime, got)
    return {"recs": recs, "fn": fn, "low_map": low_map, "high_map": high_map,
            "low": low, "high": high, "committed": committed, "sens": sens,
            "oat": oat, "frows": frows, "code_digest": code_digest,
            "reg_digest": reg_digest}


# --------------------------------------------------------------------------
# step 1: first-hand parameter audit probe (full-box 1-D sweeps at defaults)
# --------------------------------------------------------------------------
def step_audit(ctx):
    from apmt.multifidelity.levels import options_for

    fn, low_map, high_map = ctx["fn"], ctx["low_map"], ctx["high_map"]
    new_rows: list[dict] = []
    per_axis: dict[str, dict] = {n: {"ranges": [], "n_invalid": 0, "n_valid": 0,
                                     "log_ranges": [], "rsh_above_floor": []} for n in fn}
    for ri, regime in enumerate(REGIMES):
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        for ai, name in enumerate(fn):
            lo, hi = low_map[name], high_map[name]
            grids = {"lin": np.linspace(lo, hi, AUDIT_LINEAR_POINTS)}
            if name in AUDIT_LOG_AXES:
                grids["log"] = np.logspace(np.log10(lo), np.log10(hi), AUDIT_LOG_POINTS)
            for gi, (kind, grid) in enumerate(grids.items()):
                rows, _s = vc._generate_group(
                    X=np.asarray(grid, float).reshape(-1, 1), feature_names=[name],
                    regime=regime, level="L4",
                    role=f"V19G_AUDIT_{kind.upper()}",
                    family=f"v19g-audit-{kind}-{name}-{regime.name}",
                    seed=SEED + 100 + ri * 100 + ai * 10 + gi,
                    model_form="IQE-M1", physics_digest=phys,
                    low=low_map, high=high_map,
                    solver_options=options_for("L4").to_dict())
                new_rows.extend(rows)
                ok = [float(r["outputs"]["pce_pct"]) for r in rows
                      if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")]
                per_axis[name]["n_valid"] += len(ok)
                per_axis[name]["n_invalid"] += len(rows) - len(ok)
                if len(ok) >= 2:
                    rng = float(max(ok) - min(ok))
                    per_axis[name]["ranges"].append(rng)
                    if kind == "log":
                        per_axis[name]["log_ranges"].append(rng)
                    if name == "rsh_ohm_cm2":
                        above = [float(r["outputs"]["pce_pct"]) for r, g in zip(rows, grid)
                                 if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")
                                 and g > RSH_SATURATED_MIN_OHM_CM2]
                        if len(above) >= 2:
                            per_axis[name]["rsh_above_floor"].append(max(above) - min(above))
    audit_range = {n: max(v["ranges"]) if v["ranges"] else 0.0 for n, v in per_axis.items()}
    rsh_check = max(per_axis["rsh_ohm_cm2"]["rsh_above_floor"] or [0.0])
    st_max = {}
    for n in fn:
        vals = [ctx["sens"]["regimes"][reg]["indices"]["pce_pct"]["mean_total"][n]
                for reg in REGIME_NAMES]
        st_max[n] = float(max(vals))
    oat_pp = {n: float(d["max_abs_delta_pce_pp"])
              for n, d in ctx["oat"]["params"].items()}
    decision = apply_subspace_rule(st_max=st_max, oat_pp=oat_pp,
                                   audit_range_pp=audit_range,
                                   rsh_above_floor_range_pp=rsh_check,
                                   feature_order=fn)
    # fixed values are registered defaults; they must sit inside the box.
    from apmt.params.registry import spec
    fixed_values = {n: float(spec(n).default) for n in decision["fixed"]}
    for n, v in fixed_values.items():
        assert low_map[n] <= v <= high_map[n], (n, v)
    out = {"grade": "FIRST_HAND_AUDIT (1-D full-box sweeps at registered defaults)",
           "design": ("9-pt linear grid per axis x 14 axes x 3 regimes plus 9-pt log "
                      "grids on rsh/srh/srv; seeds SEED+100+ri*100+ai*10+gi"),
           "per_axis": {n: {"audit_range_pp_max": audit_range[n],
                            "sobol_st_max": st_max[n],
                            "oat_pp": oat_pp.get(n),
                            "n_valid": per_axis[n]["n_valid"],
                            "n_invalid": per_axis[n]["n_invalid"]} for n in fn},
           "rsh_above_floor_range_pp": rsh_check,
           "decision": decision,
           "fixed_values": fixed_values}
    return out, new_rows, decision["active"], fixed_values


# --------------------------------------------------------------------------
# step 2: operating-slice campaign (fresh LHS splits, distinct seeds)
# --------------------------------------------------------------------------
def step_slice(ctx, active, fixed_values):
    from apmt.multifidelity.levels import options_for

    low_map, high_map = ctx["low_map"], ctx["high_map"]
    low_a = np.array([low_map[n] for n in active], float)
    high_a = np.array([high_map[n] for n in active], float)
    assert active[0] == "perovskite_eg_ev" and active[1] == "perovskite_thickness_nm"
    is_log, low_s, high_s = _scaled_box_arrays(active, low_map, high_map)
    stages = [("TRAIN", SLICE_N_TRAIN), ("VAL", SLICE_N_VALIDATION),
              ("CALIBRATION", SLICE_N_CALIBRATION), ("FINAL", SLICE_N_FINAL)]
    new_rows: list[dict] = []
    info: dict = {"active": list(active), "fixed_values": fixed_values,
                  "by_regime": {}}
    for ri, regime in enumerate(REGIMES):
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        regime_info: dict = {}
        for si, (stage, n) in enumerate(stages):
            seed = SEED + 1000 + ri * 10 + si
            z = lhs_in_normalized_box(n, len(active), (0.0, 1.0, 0.0, 1.0), seed)
            xa = _phys_from_z01(z, low_s, high_s, is_log)
            rows, _s = vc._generate_group(
                X=xa, feature_names=active, regime=regime, level="L4",
                role=f"V19G_SLICE_{stage}",
                family=f"v19g-slice-{stage.lower()}-{regime.name}",
                seed=seed, model_form="IQE-M1", physics_digest=phys,
                low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows)
            ok = sum(r["status"] == VALID_FOR_SURROGATE for r in rows)
            regime_info[stage] = {"seed": seed, "n_requested": len(rows),
                                  "n_valid": ok,
                                  "n_invalid": len(rows) - ok}
        info["by_regime"][regime.name] = regime_info
    info["scales"] = {n: axis_scale(n) for n in active}
    return info, new_rows, low_a, high_a, is_log, low_s, high_s


# --------------------------------------------------------------------------
# step 3: reduced vs full-dimensional reference vs baselines
# --------------------------------------------------------------------------
def _fit_slice_pce(train_rows, val_rows, cal_rows, active, low_s, high_s, is_log,
                   seed):
    xt, yt = _to_scaled(_matrix(train_rows, active), is_log), _targets(train_rows)
    xv, yv = _to_scaled(_matrix(val_rows, active), is_log), _targets(val_rows)
    xc, yc = _to_scaled(_matrix(cal_rows, active), is_log), _targets(cal_rows)
    fp = dataset_fingerprint(train_rows)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted, scores = compare_families(
            xt, yt, xv, yv, feature_names=active, target_name="pce_pct", unit="%",
            training_fingerprint=fp, seed=seed,
            families=MODEL_FAMILIES_V19F, bounds=(low_s, high_s))
    sel = select_family(scores)
    order = sorted(scores, key=lambda f: (scores[f]["rmse"],
                                          MODEL_FAMILIES_V19F.index(f)))
    alts = [fitted[f] for f in order[1:3]]
    radius = None
    if len(yc) >= MIN_STRATUM_POINTS:
        cal_pred, _ = fitted[sel].predict(xc, return_std=False)
        radius = float(conformal_radius(yc, cal_pred, coverage=0.90))
    warn_list = [f"{w.category.__name__}: {str(w.message)[:160]}" for w in caught]
    return {"fitted": fitted, "scores": scores, "selected": sel, "order": order,
            "alternatives": alts, "radius": radius, "warnings": warn_list,
            "n_train": len(yt), "n_val": len(yv), "n_cal": len(yc)}


def step_slice_models(ctx, new_rows, active, low_s, high_s, is_log, bundle):
    fn = ctx["fn"]
    out: dict = {"families": list(MODEL_FAMILIES_V19F),
                 "grade_validation": "PREDECLARED_SELECTION_SET",
                 "grade_final": "FINAL (never fit/selected/thresholded)",
                 "by_regime": {}}
    fitted_by_regime: dict = {}
    for ri, regime in enumerate(REGIME_NAMES):
        tr = _rows(new_rows, regime=regime, roles=["V19G_SLICE_TRAIN"])
        va = _rows(new_rows, regime=regime, roles=["V19G_SLICE_VAL"])
        cal = _rows(new_rows, regime=regime, roles=["V19G_SLICE_CALIBRATION"])
        fin = _rows(new_rows, regime=regime, roles=["V19G_SLICE_FINAL"])
        assert_role_separation({"V19G_SLICE_TRAIN", "V19G_SLICE_VAL",
                                "V19G_SLICE_CALIBRATION"}, {"V19G_SLICE_FINAL"})
        fit = _fit_slice_pce(tr, va, cal, active, low_s, high_s, is_log,
                             SEED + 2000 + ri)
        sel_model = fit["fitted"][fit["selected"]]
        # final-holdout predictions: reduced, full-dim reference, constant.
        xf = _to_scaled(_matrix(fin, active), is_log)
        yf = _targets(fin)
        pred_red, _ = sel_model.predict(xf, return_std=False)
        x_full14 = np.column_stack(
            [_matrix(fin, [n]) if n in active
             else np.full((len(fin), 1), float(fin[0]["parameters"][n]))
             for n in fn])
        full_model = bundle.selected_models[regime]["pce_pct"]
        full_alts = bundle.alternative_models[regime]["pce_pct"]
        pred_full, _ = full_model.predict(x_full14, return_std=False)
        const_model = fit["fitted"]["constant"]
        pred_const, _ = const_model.predict(xf, return_std=False)
        # spatial strata on the slice final set (scaled-normalized coords).
        z_tr = _znorm_scaled(_matrix(tr, active), low_s, high_s, is_log)
        z_f = (xf - low_s) / (high_s - low_s)
        buffer = training_buffer_radius(z_tr)
        dist = distance_to_training(z_f, z_tr)
        margin = boundary_margin(z_f)
        eg_pos = active.index("perovskite_eg_ev") if "perovskite_eg_ev" in active else None
        strata_masks = {
            "full": np.ones(len(yf), bool),
            "interpolation": dist < buffer,
            "separated": dist >= buffer,
            "boundary": margin < 0.05,
        }
        if eg_pos is not None:
            strata_masks["eg_low_slab"] = z_f[:, eg_pos] < 0.25
            strata_masks["eg_high_slab"] = z_f[:, eg_pos] > 0.75
        strata = {}
        for sname, mask in strata_masks.items():
            n = int(mask.sum())
            if n < MIN_STRATUM_POINTS:
                strata[sname] = {"n": n, "status": "INSUFFICIENT_DATA"}
                continue
            strata[sname] = {
                "n": n,
                "reduced_rmse": _rmse(yf[mask], pred_red[mask]),
                "full_rmse": _rmse(yf[mask], pred_full[mask]),
                "constant_rmse": _rmse(yf[mask], pred_const[mask]),
                "reduced_mae": _mae(yf[mask], pred_red[mask]),
                "reduced_bias": float(np.mean(pred_red[mask] - yf[mask])),
            }
        boot = paired_bootstrap_rmse_diff((pred_full - yf) ** 2, (pred_red - yf) ** 2,
                                           SEED + 3000 + ri, N_BOOT)
        err = np.abs(pred_red - yf)
        val_rank = [(f, float(fit["scores"][f]["rmse"])) for f in fit["order"]]
        out["by_regime"][regime] = {
            "selected_family": fit["selected"],
            "n_train": fit["n_train"], "n_val": fit["n_val"], "n_cal": fit["n_cal"],
            "n_final": len(yf),
            "validation_rmse": {f: v for f, v in val_rank},
            "validation_ranking": [f for f, _ in val_rank],
            "final_strata": strata,
            "final_abs_error_quantiles": {q: float(np.quantile(err, float(q)))
                                          for q in ("0.5", "0.9", "0.99")},
            "final_max_abs_error": float(err.max()),
            "paired_bootstrap_full_minus_reduced": boot,
            "criterion_G_SLICE_BEATS_FULL": bool(boot["ci_95_low"] > 0.0),
            "criterion_G_SLICE_ERR_le_0.50": bool(
                strata["full"].get("reduced_rmse", 9e9) <= 0.50),
            "conformal_radius_pp": fit["radius"],
            "slice_buffer_radius": float(buffer),
            "final_distance_summary": summarize_distances(dist),
            "fit_warnings": fit["warnings"],
            "boxnorm_gp_kernel": str(
                fit["fitted"]["gaussian_process_matern_boxnorm"].estimator.named_steps[
                    "gp"].kernel_)[:600],
        }
        fitted_by_regime[regime] = {
            "selected": sel_model, "alternatives": fit["alternatives"],
            "full": full_model, "full_alternatives": full_alts,
            "radius": fit["radius"], "train_rows": tr, "val_rows": va,
            "final_rows": fin, "buffer": float(buffer)}
    return out, fitted_by_regime


# --------------------------------------------------------------------------
# step 4: OOD indicator ensemble — dev thresholds, independent final eval
# --------------------------------------------------------------------------
def _ood_new_boxes(ctx, active, low_s, high_s, is_log):
    from apmt.multifidelity.levels import options_for

    fn, low_map, high_map = ctx["fn"], ctx["low_map"], ctx["high_map"]
    new_rows: list[dict] = []
    for ri, regime in enumerate(REGIMES):
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        for ci, (name, box) in enumerate(SLICE_CORNER_BOXES.items()):
            z = lhs_in_normalized_box(N_OOD_PER_BOX_PER_REGIME, len(active), box,
                                      SEED + 4000 + ri * 100 + ci)
            xa = _phys_from_z01(z, low_s, high_s, is_log)
            rows, _s = vc._generate_group(
                X=xa, feature_names=active, regime=regime, level="L4",
                role=f"V19G_OOD_{name}", family=f"v19g-ood-{name}-{regime.name}",
                seed=SEED + 4000 + ri * 100 + ci, model_form="IQE-M1",
                physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows)
        for ci, (name, constrained) in enumerate(FULL_COMBO_BOXES.items()):
            rng = np.random.default_rng(SEED + 4200 + ri * 100 + ci)
            z = rng.random((N_OOD_PER_BOX_PER_REGIME, len(fn)))
            for axis_name, (lo_n, hi_n) in constrained.items():
                ai = fn.index(axis_name)
                z[:, ai] = lo_n + rng.random(N_OOD_PER_BOX_PER_REGIME) * (hi_n - lo_n)
            xf = denormalize(z, ctx["low"], ctx["high"])
            rows, _s = vc._generate_group(
                X=xf, feature_names=fn, regime=regime, level="L4",
                role=f"V19G_OOD_{name}", family=f"v19g-ood-{name}-{regime.name}",
                seed=SEED + 4200 + ri * 100 + ci, model_form="IQE-M1",
                physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows)
    return new_rows


def _indicator_matrix(X_pred, Z_eval, Z_ref, buffer, sel_model, alt_models):
    pred, _ = sel_model.predict(np.asarray(X_pred, float), return_std=False)
    stack = np.column_stack([pred] + [m.predict(np.asarray(X_pred, float),
                                                return_std=False)[0]
                                      for m in alt_models])
    return {"knn_distance": knn_distance(np.asarray(Z_eval, float),
                                        np.asarray(Z_ref, float), k=OOD_KNN_K),
            "local_sparsity": local_sparsity(np.asarray(Z_eval, float),
                                             np.asarray(Z_ref, float), buffer,
                                             k=OOD_DENSITY_K),
            "model_disagreement": disagreement_indicator(stack),
            "boundary_margin_diag": boundary_margin(np.asarray(Z_eval, float))}


def _eval_detector(X_pred, Z_eval, Z_ref, buffer, sel_model, alt_models, thresholds):
    n = np.asarray(X_pred, float).shape[0]
    if n == 0:
        return {"n": 0, "status": "INSUFFICIENT_DATA"}
    ind = _indicator_matrix(X_pred, Z_eval, Z_ref, buffer, sel_model, alt_models)
    statuses = []
    for i in range(n):
        vote = classify_ood_votes({k: float(ind[k][i]) for k in
                                   ("knn_distance", "local_sparsity",
                                    "model_disagreement")}, thresholds)
        statuses.append(vote["status"])
    statuses = np.array(statuses)
    n_ood = int((statuses == OUT_OF_DOMAIN).sum())
    n_unc = int((statuses == IN_DOMAIN_UNCERTAIN).sum())
    return {"n": n, "n_ood": n_ood, "n_uncertain": n_unc,
            "n_validated": int((statuses == IN_DOMAIN_VALIDATED).sum()),
            "ood_rate": wilson_ci(n_ood, n),
            "uncertain_rate": (n_unc / n),
            "median_indicators": {k: float(np.median(v)) for k, v in ind.items()}}


def _xz_slice(rows, active, low_s, high_s, is_log):
    xp = _matrix(rows, active)
    return _to_scaled(xp, is_log), _znorm_scaled(xp, low_s, high_s, is_log)


def step_ood(ctx, new_rows, fitted_by_regime, active, low_s, high_s, is_log, bundle):
    fn = ctx["fn"]
    ood_rows = _ood_new_boxes(ctx, active, low_s, high_s, is_log)
    new_rows.extend(ood_rows)
    out: dict = {"grade": ("FINAL (thresholds from dev only; F-corners reused as "
                           "14-D eval; new boxes fresh)"),
                 "by_regime": {}}
    for ri, regime in enumerate(REGIME_NAMES):
        fit = fitted_by_regime[regime]
        # slice detector: reference = slice train; dev = slice val.
        _xtr, z_tr = _xz_slice(fit["train_rows"], active, low_s, high_s, is_log)
        xdv, zdv = _xz_slice(fit["val_rows"], active, low_s, high_s, is_log)
        dev_ind = _indicator_matrix(xdv, zdv, z_tr, fit["buffer"],
                                    fit["selected"], fit["alternatives"])
        thr = fit_ood_thresholds(
            {k: dev_ind[k] for k in ("knn_distance", "local_sparsity",
                                     "model_disagreement")}, OOD_DEV_FPR_CAP)
        slice_sets = {
            "slice_final_inbox": _rows(new_rows, regime=regime,
                                       roles=["V19G_SLICE_FINAL"]),
        }
        for cname in SLICE_CORNER_BOXES:
            slice_sets[f"corner_{cname}"] = _rows(
                new_rows, regime=regime, roles=[f"V19G_OOD_{cname}"])
        slice_eval = {}
        for k, v in slice_sets.items():
            xq, zq = _xz_slice(v, active, low_s, high_s, is_log)
            slice_eval[k] = _eval_detector(xq, zq, z_tr, fit["buffer"],
                                           fit["selected"], fit["alternatives"],
                                           thr)
        corner_rows = [r for k, v in slice_sets.items() if k.startswith("corner_")
                       for r in v]
        xq, zq = _xz_slice(corner_rows, active, low_s, high_s, is_log)
        pooled = _eval_detector(xq, zq, z_tr, fit["buffer"],
                                fit["selected"], fit["alternatives"], thr)
        # 14-D detector: reference = V1.9-E train; dev = V1.9-E validation.
        tr14 = [r for r in ctx["recs"] if r.get("role") in ("TRAIN", "ADAPTIVE_TRAIN")
                and r.get("status") == VALID_FOR_SURROGATE
                and r.get("operating_regime", {}).get("name") == regime]
        va14 = [r for r in ctx["recs"] if r.get("role") == "VALIDATION"
                and r.get("status") == VALID_FOR_SURROGATE
                and r.get("operating_regime", {}).get("name") == regime]
        z_tr14 = ((_matrix(tr14, fn) - ctx["low"]) / (ctx["high"] - ctx["low"]))
        buf14 = training_buffer_radius(z_tr14)
        full_model = bundle.selected_models[regime]["pce_pct"]
        full_alts = bundle.alternative_models[regime]["pce_pct"]
        xdv14 = _matrix(va14, fn)
        zdv14 = (xdv14 - ctx["low"]) / (ctx["high"] - ctx["low"])
        dev14 = _indicator_matrix(xdv14, zdv14, z_tr14, buf14, full_model,
                                  full_alts)
        thr14 = fit_ood_thresholds(
            {k: dev14[k] for k in ("knn_distance", "local_sparsity",
                                   "model_disagreement")}, OOD_DEV_FPR_CAP)
        fin14 = [r for r in ctx["recs"] if r.get("role") == "FINAL_HOLDOUT"
                 and r.get("status") == VALID_FOR_SURROGATE
                 and r.get("operating_regime", {}).get("name") == regime]
        fcorner = [r for r in ctx["frows"]["valid_records"]
                   if r.get("status") == VALID_FOR_SURROGATE
                   and r.get("operating_regime", {}).get("name") == regime
                   and str(r.get("role", "")).startswith("V19F_OOD_")]
        full_sets = {"final_holdout_inbox": fin14, "v19f_corners": fcorner}
        for cname in FULL_COMBO_BOXES:
            full_sets[f"combo_{cname}"] = _rows(
                new_rows, regime=regime, roles=[f"V19G_OOD_{cname}"])
        full_eval = {}
        for k, v in full_sets.items():
            xq = _matrix(v, fn) if v else np.empty((0, len(fn)))
            zq = (xq - ctx["low"]) / (ctx["high"] - ctx["low"]) if len(xq) else xq
            full_eval[k] = _eval_detector(xq, zq, z_tr14, buf14, full_model,
                                          full_alts, thr14)
        # invalid rows: detector vote recorded; the GUARD verdict is binding.
        invalid = [r for r in (ctx["recs"] + new_rows)
                   if r.get("model_level") == "L4"
                   and r.get("operating_regime", {}).get("name") == regime
                   and (r.get("status") == INVALID_PHYSICS or not r.get("outputs"))]
        guard_reject = 0
        for r in invalid:
            verdict = bundle.verify_candidate(
                {n: float(r["parameters"][n]) for n in fn}, regime=regime,
                run_l5=False)
            if not verdict["candidate_eligible_for_optimizer"]:
                guard_reject += 1
        out["by_regime"][regime] = {
            "slice_detector": {"dev_n": len(fit["val_rows"]),
                               "thresholds": thr,
                               "buffer": fit["buffer"],
                               "eval": slice_eval,
                               "pooled_new_corners": pooled,
                               "criterion_G_OOD_RECALL_ge_0.50": bool(
                                   (pooled.get("n_ood", 0)
                                    / max(1, pooled.get("n", 1))) >= 0.50),
                               "criterion_G_OOD_FPR_le_0.10": bool(
                                   (slice_eval["slice_final_inbox"].get("n_ood", 1)
                                    / max(1, slice_eval["slice_final_inbox"].get(
                                        "n", 1))) <= 0.10)},
            "full_detector": {"dev_n": len(va14), "thresholds": thr14,
                              "buffer_14d": float(buf14), "eval": full_eval},
            "invalid_probe": {"n_invalid": len(invalid),
                              "guard_rejected": guard_reject},
        }
    return out


# --------------------------------------------------------------------------
# step 5: fresh Saltelli study of the central interaction box
# --------------------------------------------------------------------------
def step_saltelli(ctx, new_rows):
    from apmt.multifidelity.levels import options_for

    low_map, high_map = ctx["low_map"], ctx["high_map"]
    lo_c, hi_c = SALTELLI_CENTRAL_BOX
    s_low = np.array([low_map[n] + lo_c * (high_map[n] - low_map[n])
                      for n in SALTELLI_AXES], float)
    s_high = np.array([low_map[n] + hi_c * (high_map[n] - low_map[n])
                       for n in SALTELLI_AXES], float)
    out: dict = {"grade": "FRESH_L4 (central box; no reuse of V1.9-D designs)",
                 "axes": list(SALTELLI_AXES),
                 "box_physical": {n: [float(l), float(h)] for n, l, h in
                                  zip(SALTELLI_AXES, s_low, s_high)},
                 "n_base": SALTELLI_N_BASE, "by_regime": {}}
    for ri, regime in enumerate(REGIMES):
        seed = SEED + 5000 + ri
        design = saltelli_design(SALTELLI_AXES, n_base=SALTELLI_N_BASE, low=s_low,
                                 high=s_high, seed=seed,
                                 second_order=SALTELLI_SECOND_ORDER)
        mat = design.matrix()
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        rows, _s = vc._generate_group(
            X=mat, feature_names=SALTELLI_AXES, regime=regime, level="L4",
            role="V19G_SALTELLI", family=f"v19g-saltelli-{regime.name}",
            seed=seed, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map,
            solver_options=options_for("L4").to_dict())
        assert len(rows) == mat.shape[0]
        new_rows.extend(rows)
        y = np.array([float(r["outputs"]["pce_pct"])
                      if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")
                      else np.nan for r in rows], float)
        n_invalid = int(np.isnan(y).sum())
        est = sobol_indices(y, design, output="pce_pct",
                            bootstrap=SALTELLI_BOOTSTRAP, seed=SEED + 5100 + ri)
        halves = []
        for take_even in (True, False):
            sub = split_saltelli_design(design, take_even)
            yh = np.concatenate(
                [b[np.arange(design.n_base)[0::2] if take_even
                   else np.arange(design.n_base)[1::2]]
                 for b in [y[i * design.n_base:(i + 1) * design.n_base]
                           for i in range(design.n_blocks)]])
            halves.append(sobol_indices(yh, sub, output="pce_pct",
                                        bootstrap=SALTELLI_BOOTSTRAP,
                                        seed=SEED + 5200 + ri))
        top_full = est.ranking("total")[:3]
        tops_half = [h.ranking("total")[:3] for h in halves]
        max_d = 0.0
        for n in top_full:
            i = list(est.names).index(n)
            max_d = max(max_d, abs(halves[0].total[i] - halves[1].total[i]))
        stable = tops_half[0] == tops_half[1] and max_d < SALTELLI_SPLIT_HALF_TOL
        # validity map if any invalids (no imputation, ever).
        validity = {"n_total": len(y), "n_valid": int((~np.isnan(y)).sum()),
                    "n_invalid": n_invalid}
        if n_invalid:
            zbad = (mat[np.isnan(y)] - s_low) / (s_high - s_low)
            validity["invalid_median_normalized"] = zbad.mean(axis=0).tolist()
        out["by_regime"][regime.name] = {
            "design": design.to_dict(), "complete": est.complete,
            "variance": float(est.variance), "mean": float(est.mean),
            "first": {n: float(v) for n, v in zip(est.names, est.first)},
            "total": {n: float(v) for n, v in zip(est.names, est.total)},
            "first_ci95": ({n: float(v) for n, v in zip(est.names, est.first_ci)}
                           if est.first_ci is not None else {}),
            "total_ci95": ({n: float(v) for n, v in zip(est.names, est.total_ci)}
                           if est.total_ci is not None else {}),
            "second": {f"{a}|{b}": float(v) for (a, b), v in est.second.items()},
            "split_half": [{"ranking_total": h.ranking("total"),
                            "total": {n: float(v)
                                      for n, v in zip(h.names, h.total)}}
                           for h in halves],
            "split_half_max_top3_dST": float(max_d),
            "criterion_G_SALTELLI_STABLE": bool(stable),
            "validity": validity,
        }
    return out


# --------------------------------------------------------------------------
# step 6: targeted narrow-peak investigation (arc fringes + Eg control)
# --------------------------------------------------------------------------
def step_peaks(ctx, new_rows, fitted_by_regime, active, low_a, high_a, is_log):
    from apmt.multifidelity.levels import options_for

    fn, low_map, high_map = ctx["fn"], ctx["low_map"], ctx["high_map"]
    pos = {n: i for i, n in enumerate(active)}
    arc_pos = pos.get("arc_thickness_nm")
    eg_pos = pos.get("perovskite_eg_ev")
    anchors = {"center": np.full(len(active), 0.5),
               "high_eg": np.full(len(active), 0.5),
               "low_eg": np.full(len(active), 0.5)}
    if eg_pos is not None:
        anchors["high_eg"][eg_pos] = 0.75
        anchors["low_eg"][eg_pos] = 0.25
    assert set(anchors) == set(PEAK_ANCHORS)
    out: dict = {"grade": "TARGETED (predeclared anchors/scans/budget)",
                 "arc_on_slice": arc_pos is not None,
                 "solve_budget": PEAK_SOLVE_BUDGET, "by_regime": {}}
    solves = 0
    for ri, regime in enumerate(REGIMES):
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        model = fitted_by_regime[regime.name]["selected"]
        scans: dict = {}
        # arc scans at each anchor (off-slice rows if arc is fixed: flagged).
        arc_lo, arc_hi = low_map["arc_thickness_nm"], high_map["arc_thickness_nm"]
        for anchor_name, z0 in anchors.items():
            grid = np.linspace(arc_lo, arc_hi, PEAK_ARC_SCAN_POINTS)
            xa = np.tile(z0 * (high_a - low_a) + low_a, (len(grid), 1))
            if arc_pos is not None:
                xa[:, arc_pos] = grid
                xgen, names = xa, active
            else:
                base = np.array([float(fitted_by_regime[regime.name][
                    "train_rows"][0]["parameters"][n]) for n in fn], float)
                full = np.tile(base, (len(grid), 1))
                for j, n in enumerate(active):
                    full[:, fn.index(n)] = xa[:, j]
                full[:, fn.index("arc_thickness_nm")] = grid
                xgen, names = full, fn
            rows, _s = vc._generate_group(
                X=xgen, feature_names=list(names), regime=regime, level="L4",
                role="V19G_PEAK_SCAN",
                family=f"v19g-peak-arc-{anchor_name}-{regime.name}",
                seed=SEED + 6000 + ri * 10 + list(anchors).index(anchor_name),
                model_form="IQE-M1", physics_digest=phys,
                low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows)
            solves += len(rows)
            ok = [(float(r["parameters"]["arc_thickness_nm"]),
                   float(r["outputs"]["pce_pct"])) for r in rows
                  if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")]
            xs = np.array([p[0] for p in ok])
            ys = np.array([p[1] for p in ok])
            peaks = find_local_maxima(xs, ys)
            scans[anchor_name] = {
                "n_valid": len(ok), "n_invalid": len(rows) - len(ok),
                "scan_range_pp": float(ys.max() - ys.min()) if len(ys) else None,
                "peaks_idx": peaks,
                "peaks": [{"arc_nm": float(xs[i]), "pce": float(ys[i])}
                          for i in peaks],
            }
            # surrogate comparison at scan points (on-slice only meaningful).
            if arc_pos is not None and len(ok):
                xslice = _to_scaled(
                    np.array([[float(r["parameters"][n]) for n in active]
                              for r in rows
                              if r["status"] == VALID_FOR_SURROGATE
                              and r.get("outputs")]), is_log)
                pred, _ = model.predict(xslice, return_std=False)
                scans[anchor_name]["surrogate_rmse_on_scan"] = _rmse(ys, pred)
        # Eg control scan at the center anchor.
        eg_lo, eg_hi = low_map["perovskite_eg_ev"], high_map["perovskite_eg_ev"]
        grid = np.linspace(eg_lo, eg_hi, PEAK_EG_SCAN_POINTS)
        xa = np.tile(anchors["center"] * (high_a - low_a) + low_a, (len(grid), 1))
        if eg_pos is not None:
            xa[:, eg_pos] = grid
        rows, _s = vc._generate_group(
            X=xa, feature_names=active, regime=regime, level="L4",
            role="V19G_PEAK_SCAN",
            family=f"v19g-peak-eg-center-{regime.name}",
            seed=SEED + 6050 + ri, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map,
            solver_options=options_for("L4").to_dict())
        new_rows.extend(rows)
        solves += len(rows)
        ok = [(float(r["parameters"]["perovskite_eg_ev"]),
               float(r["outputs"]["pce_pct"])) for r in rows
              if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")]
        xs = np.array([p[0] for p in ok])
        ys = np.array([p[1] for p in ok])
        scans["eg_center"] = {
            "n_valid": len(ok), "n_invalid": len(rows) - len(ok),
            "scan_range_pp": float(ys.max() - ys.min()) if len(ys) else None,
            "peaks": [{"eg_ev": float(xs[i]), "pce": float(ys[i])}
                      for i in find_local_maxima(xs, ys)],
        }
        # refinement: top peaks by scan value, bounded count.
        cands = [(p["pce"], aname, p) for aname, s in scans.items()
                 if aname in anchors for p in s["peaks"]]
        cands.sort(reverse=True)
        refined = []
        coarse_step = (arc_hi - arc_lo) / (PEAK_ARC_SCAN_POINTS - 1)
        for _v, aname, peak in cands[:PEAK_MAX_REFINE]:
            lo_r = max(arc_lo, peak["arc_nm"] - 2.0 * coarse_step)
            hi_r = min(arc_hi, peak["arc_nm"] + 2.0 * coarse_step)
            grid_r = np.linspace(lo_r, hi_r, PEAK_REFINE_POINTS)
            xa = np.tile(anchors[aname] * (high_a - low_a) + low_a,
                         (len(grid_r), 1))
            if arc_pos is not None:
                xa[:, arc_pos] = grid_r
                xgen, names = xa, active
            else:
                base = np.array([float(fitted_by_regime[regime.name][
                    "train_rows"][0]["parameters"][n]) for n in fn], float)
                full = np.tile(base, (len(grid_r), 1))
                for j, n in enumerate(active):
                    full[:, fn.index(n)] = xa[:, j]
                full[:, fn.index("arc_thickness_nm")] = grid_r
                xgen, names = full, fn
            rows_r, _s = vc._generate_group(
                X=xgen, feature_names=list(names), regime=regime, level="L4",
                role="V19G_PEAK_REFINE",
                family=f"v19g-peak-refine-{aname}-{regime.name}",
                seed=SEED + 6100 + ri * 10 + len(refined),
                model_form="IQE-M1", physics_digest=phys,
                low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows_r)
            solves += len(rows_r)
            okr = [(float(r["parameters"]["arc_thickness_nm"]),
                    float(r["outputs"]["pce_pct"])) for r in rows_r
                   if r["status"] == VALID_FOR_SURROGATE and r.get("outputs")]
            if okr:
                best = max(okr, key=lambda p: p[1])
                shift = abs(best[0] - peak["arc_nm"])
                dval = abs(best[1] - peak["pce"])
                status = ("RESOLVED" if shift <= coarse_step and dval <= 0.10
                          else "UNRESOLVED")
            else:
                best, shift, dval, status = None, None, None, "NO_VALID_POINTS"
            refined.append({"anchor": aname, "scan_peak": peak,
                            "refined_best": ({"arc_nm": best[0], "pce": best[1]}
                                             if best else None),
                            "location_shift_nm": shift,
                            "value_change_pp": dval, "status": status})
        n_reg = sum(s["n_valid"] + s["n_invalid"] for s in scans.values())
        n_reg += len(refined) * PEAK_REFINE_POINTS
        out["by_regime"][regime.name] = {"scans": scans, "refined": refined,
                                         "n_solves": n_reg}
    out["total_solves"] = solves
    assert solves <= PEAK_SOLVE_BUDGET, solves
    return out


# --------------------------------------------------------------------------
# step 7: controlled candidate-selection study on the slice
# --------------------------------------------------------------------------
def step_selection(ctx, new_rows, fitted_by_regime, active, low_a, high_a,
                   low_s, high_s, is_log):
    from apmt.multifidelity.levels import options_for

    low_map, high_map = ctx["low_map"], ctx["high_map"]
    out: dict = {"scope": "operating-slice pools (no 14-D global optimization)",
                 "budget": {"pool_n": SELECTION_POOL_N, "k": SELECTION_K,
                            "seeds": list(SELECTION_SEEDS)},
                 "methods": list(SELECTION_METHODS), "by_regime": {}}
    for ri, regime in enumerate(REGIMES):
        fit = fitted_by_regime[regime.name]
        model, alts = fit["selected"], fit["alternatives"]
        phys = vc._physics_digest_for_regime(ctx["code_digest"], ctx["reg_digest"],
                                             regime, "L4", "IQE-M1")
        regime_out: dict = {"selected_family": model.family, "per_seed": {}}
        for seed in SELECTION_SEEDS:
            rng = np.random.default_rng(seed + 77 * ri)
            zp = rng.random((SELECTION_POOL_N, len(active)))
            pool = _phys_from_z01(zp, low_s, high_s, is_log)
            pool_s = _to_scaled(pool, is_log)
            pred, _ = model.predict(pool_s, return_std=False)
            stack = np.column_stack([pred] + [a.predict(pool_s, return_std=False)[0]
                                              for a in alts])
            disagreement = disagreement_indicator(stack)
            order_pred = np.argsort(-pred, kind="stable")
            top_q = order_pred[: max(SELECTION_K * 4, len(pred) // 4)]
            znorm = _znorm_scaled(pool, low_s, high_s, is_log)
            diverse = [int(top_q[0])]
            while len(diverse) < SELECTION_K:
                rest = [i for i in top_q if i not in diverse]
                dmin = np.min(np.linalg.norm(
                    znorm[rest][:, None, :] - znorm[diverse][None, :, :],
                    axis=2), axis=1)
                diverse.append(int(rest[int(np.argmax(dmin))]))
            ucb = pred + SELECTION_UCB_BETA * disagreement
            order_ucb = np.argsort(-ucb, kind="stable")
            rng_choice = np.random.default_rng(seed + 913 * ri)
            # E: central-box max-pred (Saltelli axes inside [0.15, 0.85]).
            in_box = np.ones(len(pool), bool)
            for n in SALTELLI_AXES:
                if n in active:
                    z1 = (pool[:, active.index(n)] - low_map[n]) / (
                        high_map[n] - low_map[n])
                    in_box &= (z1 >= SALTELLI_CENTRAL_BOX[0]) & (
                        z1 <= SALTELLI_CENTRAL_BOX[1])
            order_box = np.argsort(-pred, kind="stable")
            order_box = np.array([i for i in order_box if in_box[i]] +
                                 [i for i in order_box if not in_box[i]])
            # F: local refinement around the predicted best.
            rng_loc = np.random.default_rng(seed + 131 * ri)
            jb = int(order_pred[0])
            pert = znorm[jb] + rng_loc.normal(0.0, SELECTION_LOCAL_SIGMA,
                                              (SELECTION_K - 1, len(active)))
            pert = np.clip(pert, 0.0, 1.0)
            local_extra = _phys_from_z01(pert, low_s, high_s, is_log)
            picks = {
                "random_pool_baseline": (rng_choice.choice(
                    SELECTION_POOL_N, SELECTION_K, replace=False).tolist(), None),
                "max_predicted_pce": (order_pred[:SELECTION_K].tolist(), None),
                "uncertainty_aware_disagreement_ucb": (
                    order_ucb[:SELECTION_K].tolist(), None),
                "diverse_top_quartile": (diverse, None),
                "central_box_max_predicted_pce": (
                    order_box[:SELECTION_K].tolist(), None),
                "local_refinement_around_best": ([jb], local_extra),
            }
            assert set(picks) == set(SELECTION_METHODS)
            seed_out: dict = {"methods": {},
                              "central_box_pool_n": int(in_box.sum())}
            for method, (idx, extra) in picks.items():
                xa = pool[np.array(idx, int)]
                if extra is not None:
                    xa = np.vstack([xa, np.asarray(extra, float)])
                assert xa.shape == (SELECTION_K, len(active))
                rows, _s = vc._generate_group(
                    X=xa, feature_names=active, regime=regime, level="L4",
                    role="V19G_SELECT",
                    family=f"v19g-select-{method}-{regime.name}-{seed}",
                    seed=seed, model_form="IQE-M1", physics_digest=phys,
                    low=low_map, high=high_map,
                    solver_options=options_for("L4").to_dict())
                new_rows.extend(rows)
                verified = []
                for rj, row in enumerate(rows):
                    jj = idx[rj] if rj < len(idx) else None
                    verified.append({
                        "predicted_pce": (float(pred[jj]) if jj is not None
                                          else float(model.predict(
                                              _to_scaled(xa[rj: rj + 1], is_log),
                                              return_std=False)[0][0])),
                        "disagreement": (float(disagreement[jj]) if jj is not None
                                         else None),
                        "verified_pce": (float(row["outputs"]["pce_pct"])
                                         if row["status"] == VALID_FOR_SURROGATE
                                         and row.get("outputs") else None),
                        "status": row["status"],
                        "hard_invariant_failures": row.get(
                            "hard_invariant_failures", []),
                        "sample_id": row["sample_id"]})
                ok = [v for v in verified if v["verified_pce"] is not None]
                pv = [v["predicted_pce"] for v in ok]
                vv = [v["verified_pce"] for v in ok]
                top2 = None
                if len(ok) >= 2:
                    pt = set(np.argsort(-np.array(pv), kind="stable")[:2].tolist())
                    vt = set(np.argsort(-np.array(vv), kind="stable")[:2].tolist())
                    top2 = len(pt & vt) / 2.0
                seed_out["methods"][method] = {
                    "n_verified": len(ok), "n_invalid": len(verified) - len(ok),
                    "best_verified_pce": max(vv) if ok else None,
                    "mean_verified_pce": float(np.mean(vv)) if ok else None,
                    "spearman_predicted_vs_verified": spearman_rank_corrcoef(
                        pv, vv) if len(ok) >= 2 else None,
                    "top2_recovery": top2,
                    "proposals": verified,
                }
            regime_out["per_seed"][str(seed)] = seed_out
        out["by_regime"][regime.name] = regime_out
    return out


# --------------------------------------------------------------------------
# step 8: cost benchmarks (conventions identical to V1.9-F)
# --------------------------------------------------------------------------
def step_cost(ctx, new_rows, fitted_by_regime, active, low_s, high_s, is_log,
              bundle):
    fn = ctx["fn"]
    l4_times = [float(r["runtime_s"]) for r in new_rows
                if r.get("runtime_s") is not None]
    l4_med = float(np.median(l4_times))
    bench: dict = {"l4_runtime_s": {"median": l4_med,
                                    "mean": float(np.mean(l4_times)),
                                    "n": len(l4_times)},
                   "by_regime": {}}
    for regime in REGIME_NAMES:
        fit = fitted_by_regime[regime]
        model = fit["selected"]
        fin = fit["final_rows"]
        xa = _to_scaled(_matrix(fin, active), is_log)
        t0 = time.perf_counter()
        for i in range(20):
            model.predict(xa[i: i + 1], return_std=False)
        single = (time.perf_counter() - t0) / 20.0
        big = np.tile(xa, (math.ceil(256 / max(1, len(xa))), 1))[:256]
        t0 = time.perf_counter()
        for _ in range(5):
            model.predict(big, return_std=False)
        batch256 = (time.perf_counter() - t0) / 5.0
        # OOD indicator cost per 100 queries.
        z_tr = _znorm_scaled(_matrix(fit["train_rows"], active), low_s, high_s,
                             is_log)
        z_q = z_tr[:100] if len(z_tr) >= 100 else z_tr
        t0 = time.perf_counter()
        knn_distance(z_q, z_tr, k=OOD_KNN_K)
        ood100 = time.perf_counter() - t0
        bench["by_regime"][regime] = {
            "selected_family": model.family,
            "fit_runtime_s": float(model.training_runtime_s or 0.0),
            "single_point_s": single,
            "single_point_speedup_vs_median_l4": l4_med / single,
            "batch256_s": batch256,
            "batch256_per_point_ms": batch256 / 256.0 * 1000.0,
            "batch256_amortized_speedup_vs_median_l4": l4_med / (batch256 / 256.0),
            "ood100_s": ood100,
        }
    # full-dim reference single-point cost (bundle path, V1.9-F convention).
    t0 = time.perf_counter()
    r0 = fitted_by_regime[REGIME_NAMES[0]]["final_rows"][0]
    params0 = {n: float(r0["parameters"][n]) for n in fn}
    for _ in range(5):
        bundle.predict(params0, regime=REGIME_NAMES[0])
    full_single = (time.perf_counter() - t0) / 5.0
    bench["full_reference_single_point_s"] = full_single
    bench["full_reference_single_speedup_vs_median_l4"] = l4_med / full_single
    bench["peak_rss_bytes"] = int(resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss * 1024)
    return bench


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(DEFAULT_RESULTS_PATH))
    parser.add_argument("--new-rows", default=str(DEFAULT_NEW_ROWS_PATH))
    args = parser.parse_args(argv)
    t_campaign = time.perf_counter()

    ctx = step_verify()
    audit, new_rows, active, fixed_values = step_audit(ctx)
    assert len(active) >= 2, active
    slice_info, slice_rows, low_a, high_a, is_log, low_s, high_s = step_slice(
        ctx, active, fixed_values)
    new_rows.extend(slice_rows)

    t_refit = time.perf_counter()
    bundle, _scores, _cache = vc._run_model_comparison(
        ctx["recs"], feature_names=ctx["fn"], low=ctx["low"], high=ctx["high"],
        seed=V19E_SEED + 700)
    refit_s = time.perf_counter() - t_refit
    for regime in REGIME_NAMES:
        stored = ctx["committed"]["model_comparison"][regime]["pce_pct"][
            "selected_family_by_independent_validation"]
        assert bundle.model_cards[regime]["pce_pct"][
            "selected_family_by_independent_validation"] == stored

    slice_models, fitted_by_regime = step_slice_models(
        ctx, new_rows, active, low_s, high_s, is_log, bundle)
    ood = step_ood(ctx, new_rows, fitted_by_regime, active, low_s, high_s, is_log,
                   bundle)
    saltelli = step_saltelli(ctx, new_rows)
    peaks = step_peaks(ctx, new_rows, fitted_by_regime, active, low_a, high_a,
                       is_log)
    selection = step_selection(ctx, new_rows, fitted_by_regime, active, low_a,
                               high_a, low_s, high_s, is_log)
    cost = step_cost(ctx, new_rows, fitted_by_regime, active, low_s, high_s,
                     is_log, bundle)
    cost["full_reference_refit_s"] = refit_s

    from apmt.params.registry import REGISTRY
    from apmt.repro.digest import digest_block

    results = {
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
        "status": "PRE_GATE_COMPUTATIONAL_DISCOVERY_STUDY",
        "protocol": protocol_declaration(),
        "seed": SEED,
        "v19e_seed": V19E_SEED,
        "subspace_audit": audit,
        "slice_campaign": slice_info,
        "slice_model_comparison": slice_models,
        "ood_study": ood,
        "saltelli_central_box": saltelli,
        "peak_study": peaks,
        "selection_study": selection,
        "cost": cost,
        "campaign_runtime_s": float(time.perf_counter() - t_campaign),
        "campaign": {"tool": "tools/v19g_discovery_campaign.py",
                     "registry_size": len(REGISTRY)},
        "metadata": {"seed": SEED, "physics_source_digest": ctx["code_digest"],
                     "registry_digest": ctx["reg_digest"]},
    }
    results["physics_digest"] = digest_block(results)
    vc._assert_json_finite(results)
    new_rows = mark_duplicates(new_rows)
    meta = {"seed": SEED, "campaign_id": "V1.9-G",
            "physics_source_digest": ctx["code_digest"],
            "registry_digest": ctx["reg_digest"],
            "feature_names": ctx["fn"]}
    new_artifact = save_dataset(args.new_rows, new_rows, metadata=meta,
                                extra={"campaign": "V1.9-G",
                                       "sample_count": len(new_rows)})
    # round-trip: the stored fingerprint must reproduce from the file layout
    # (valid_records carry uniques + duplicates; INVALID rows live only in
    # the ledger).
    reloaded = load_dataset(args.new_rows)
    recon = (reloaded["valid_records"]
             + [r for r in reloaded["rejection_ledger"]
                if r.get("status") == INVALID_PHYSICS])
    assert dataset_fingerprint(recon) == reloaded["dataset_fingerprint"]
    results["new_rows_artifact"] = new_artifact
    results["campaign_runtime_s"] = float(time.perf_counter() - t_campaign)
    result_file = vc._write_json(Path(args.results), results)
    print(json.dumps({"status": results["status"],
                      "result_artifact": result_file,
                      "new_rows_artifact": new_artifact}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
