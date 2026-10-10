#!/usr/bin/env python3
"""V1.9-F surrogate reliability, spatial generalization, optimization readiness.

Reads the committed V1.9-E evidence (never mutates it), refits the documented
models from committed rows with documented seeds, evaluates the predeclared
spatial protocol (``apmt/surrogate/spatial.py``), runs bounded new L4/L5
physics for withheld corners and controlled candidate selection, and writes:

* ``data/v19f_reliability_results.json`` — machine-readable findings;
* ``data/v19f_new_rows.json.gz`` — new physics rows with full provenance.

Exit code 0 = complete.  Negative results are recorded, not hidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from apmt.sensitivity.campaign import REGIMES
from apmt.surrogate import campaign as vc
from apmt.surrogate.data import (
    OUTPUT_NAMES,
    VALID_FOR_SURROGATE,
    dataset_fingerprint,
    load_dataset,
    mark_duplicates,
    save_dataset,
    training_rows,
)
from apmt.surrogate.domain import (
    IN_DOMAIN_UNCERTAIN,
    IN_DOMAIN_VALIDATED,
    OUT_OF_DOMAIN,
    fit_support_profile,
    normalize,
)
from apmt.surrogate.models import (
    MODEL_FAMILIES_V19F,
    compare_families,
    conformal_radius,
    fit_regressor,
    interval_metrics,
    raw_interval_coverage,
    regression_metrics,
    select_family,
)
from apmt.surrogate.spatial import (
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

SEED = 20261010
V19E_SEED = 20261009
COMMITTED_DATASET = ROOT / "data" / "v19e_surrogate_dataset_v3.json.gz"
COMMITTED_RESULTS = ROOT / "data" / "v19e_surrogate_results_v3.json"
SENSITIVITY_ARTIFACT = ROOT / "data" / "v19_sensitivity.json"
DEFAULT_RESULTS_PATH = ROOT / "data" / "v19f_reliability_results.json"
DEFAULT_NEW_ROWS_PATH = ROOT / "data" / "v19f_new_rows.json.gz"

REGIME_NAMES = tuple(r.name for r in REGIMES)
N_NEW_CORNER_PER_REGIME = 24
CANDIDATE_K = 6
CANDIDATE_SEEDS = (SEED + 3100, SEED + 3101, SEED + 3102)
CANDIDATE_POOL_N = 200


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_committed() -> tuple[dict, dict, list[dict]]:
    ds = load_dataset(COMMITTED_DATASET)
    with open(COMMITTED_RESULTS) as f:
        results = json.load(f)
    recs = mark_duplicates(ds["valid_records"] + ds["rejection_ledger"])
    assert ds["dataset_fingerprint"] == results["data_contract"]["dataset_fingerprint"]
    assert dataset_fingerprint(recs) == ds["dataset_fingerprint"]
    return ds, results, recs


def _feature_box(sens: dict) -> tuple[list[str], np.ndarray, np.ndarray]:
    fn = list(sens["design_parameters"])
    low = np.array([sens["shared_box"]["low"][n] for n in fn], float)
    high = np.array([sens["shared_box"]["high"][n] for n in fn], float)
    return fn, low, high


def _rows(recs, *, regime, level="L4", roles, status=VALID_FOR_SURROGATE) -> list[dict]:
    roles = {r for r in roles}
    return [r for r in recs if r.get("role") in roles
            and r.get("status") == status and r.get("model_level") == level
            and r.get("operating_regime", {}).get("name") == regime]


def _matrix(rows, names) -> np.ndarray:
    return np.array([[float(r["parameters"][n]) for n in names] for r in rows], float)


def _targets(rows, target) -> np.ndarray:
    return np.array([float(r["outputs"][target]) for r in rows], float)


def _metrics_or_insufficient(y_true, y_pred, *, train_y) -> dict:
    if len(y_true) < MIN_STRATUM_POINTS:
        return {"status": "INSUFFICIENT_POINTS", "n": len(y_true),
                "min_stratum_points": MIN_STRATUM_POINTS}
    out = regression_metrics(np.asarray(y_true, float), np.asarray(y_pred, float),
                             train_y=np.asarray(train_y, float))
    out["status"] = "MEASURED"
    return out


# --------------------------------------------------------------------------
# step 1: refit fidelity gate
# --------------------------------------------------------------------------
def step_refit_fidelity(recs, committed, fn, low, high) -> tuple[dict, object, dict]:
    """Refit the exact V1.9-E global models; abort unless metrics reproduce."""
    t0 = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bundle, _scores, cache = vc._run_model_comparison(
            recs, feature_names=fn, low=low, high=high, seed=V19E_SEED + 700)
    wall = time.perf_counter() - t0
    max_diff = 0.0
    worst = None
    for regime in REGIME_NAMES:
        for target in OUTPUT_NAMES:
            stored = committed["model_comparison"][regime][target]
            refit_card = bundle.model_cards[regime][target]
            assert (refit_card["selected_family_by_independent_validation"]
                    == stored["selected_family_by_independent_validation"])
            assert refit_card["training_fingerprint"] == stored["training_fingerprint"]
            for fam, sc in stored["model_family_scores"].items():
                refit_rmse = refit_card["model_family_scores"][fam]["rmse"]
                diff = abs(refit_rmse - sc["rmse"])
                if diff > max_diff:
                    max_diff, worst = diff, (regime, target, fam)
        stored_prof = committed["final_holdout"][regime]["support_profile"]
        prof = bundle.support_profiles[regime]
        for key, attr in (("nearest_distance_ood_threshold",
                           "nearest_distance_ood_threshold"),
                          ("nearest_distance_uncertain_threshold",
                           "nearest_distance_uncertain_threshold")):
            diff = abs(float(getattr(prof, attr)) - float(stored_prof[key]))
            max_diff = max(max_diff, diff)
    assert max_diff <= 1e-9, (max_diff, worst)
    return ({
        "status": "REFIT_BIT_IDENTICAL",
        "max_abs_validation_rmse_or_threshold_diff": max_diff,
        "refit_wall_s": wall,
        "sklearn_warnings_during_refit": [
            {"category": w.category.__name__, "message": str(w.message)[:300],
             "filename": str(w.filename).split("/")[-1], "lineno": int(w.lineno)}
            for w in caught],
    }, bundle, cache)


# --------------------------------------------------------------------------
# step 2: spatial stratification of untouched evaluation rows
# --------------------------------------------------------------------------
def step_spatial(bundle, cache, recs, fn, low, high) -> dict:
    out: dict = {"protocol": protocol_declaration(), "by_regime": {}}
    for regime in REGIME_NAMES:
        train_rows = cache["train"][regime]
        xtr = _matrix(train_rows, fn)
        ztr = normalize(xtr, low, high)
        buffer = training_buffer_radius(ztr)
        train_y_pce = _targets(train_rows, "pce_pct")
        model = bundle.selected_models[regime]["pce_pct"]
        regime_out: dict = {
            "buffer_radius": buffer,
            "n_train": len(train_rows),
            "eval_sets": {},
        }
        eval_roles = {
            "VALIDATION_diagnostic": ["VALIDATION"],
            "CALIBRATION_diagnostic": ["CALIBRATION"],
            "FINAL_HOLDOUT_final": ["FINAL_HOLDOUT"],
            "BOUNDARY_VALIDATION_final": ["BOUNDARY_VALIDATION"],
            "OOD_FINAL_withheld_corner_final": ["OOD_FINAL"],
        }
        for label, roles in eval_roles.items():
            rows = _rows(recs, regime=regime, roles=roles)
            if not rows:
                regime_out["eval_sets"][label] = {"n": 0, "status": "NO_ROWS"}
                continue
            xe = _matrix(rows, fn)
            ze = normalize(xe, low, high)
            dist = distance_to_training(ze, ztr)
            strat = stratify_by_buffer(dist, buffer)
            ye = _targets(rows, "pce_pct")
            pred, _ = model.predict(xe, return_std=False)
            blocks = assign_axis_blocks(ze).as_dict()
            detail: dict = {
                "n": len(rows),
                "distance_summary": summarize_distances(dist),
                "strata": strat,
                "pce_full": _metrics_or_insufficient(ye, pred, train_y=train_y_pce),
                "pce_interpolation": _metrics_or_insufficient(
                    ye[strat["interpolation_index"]], pred[strat["interpolation_index"]],
                    train_y=train_y_pce),
                "pce_separated": _metrics_or_insufficient(
                    ye[strat["separated_index"]], pred[strat["separated_index"]],
                    train_y=train_y_pce),
                "axis_blocks": blocks,
                "pce_low_slab": _metrics_or_insufficient(
                    ye[blocks["low_slab_index"]], pred[blocks["low_slab_index"]],
                    train_y=train_y_pce),
                "pce_high_slab": _metrics_or_insufficient(
                    ye[blocks["high_slab_index"]], pred[blocks["high_slab_index"]],
                    train_y=train_y_pce),
            }
            # all-target RMSE on the full set and the separated stratum only
            detail["all_targets_rmse_full"] = {}
            detail["all_targets_rmse_separated"] = {}
            for target in OUTPUT_NAMES:
                mt = bundle.selected_models[regime][target]
                yt = _targets(rows, target)
                pt, _ = mt.predict(xe, return_std=False)
                detail["all_targets_rmse_full"][target] = float(
                    np.sqrt(np.mean((pt - yt) ** 2)))
                si = np.asarray(strat["separated_index"], dtype=int)
                detail["all_targets_rmse_separated"][target] = (
                    float(np.sqrt(np.mean((pt[si] - yt[si]) ** 2)))
                    if len(si) >= MIN_STRATUM_POINTS else None)
            regime_out["eval_sets"][label] = detail
        out["by_regime"][regime] = regime_out
    return out


# --------------------------------------------------------------------------
# step 3: diagnostic block refits (tested on VALIDATION rows in slabs only)
# --------------------------------------------------------------------------
def step_block_refits(recs, fn, low, high, committed) -> dict:
    assert_role_separation({"TRAIN", "ADAPTIVE_TRAIN"}, {"VALIDATION"})
    out: dict = {"grade": "DIAGNOSTIC (selection-set reuse; FINAL rows untouched)",
                 "by_regime": {}}
    for ri, regime in enumerate(REGIME_NAMES):
        tr = training_rows(recs, regime_name=regime, level="L4")
        va = _rows(recs, regime=regime, roles=["VALIDATION"])
        ztr = normalize(_matrix(tr, fn), low, high)
        zva = normalize(_matrix(va, fn), low, high)
        block_tr = assign_axis_blocks(ztr)
        block_va = assign_axis_blocks(zva)
        regime_out: dict = {
            "n_train": len(tr), "n_validation": len(va),
            "train_blocks": block_tr.as_dict(), "validation_blocks": block_va.as_dict(),
            "slabs": {},
        }
        yt_tr_full = _targets(tr, "pce_pct")
        for slab, tr_idx, va_idx in (
                ("LOW", [i for i in range(len(tr)) if i not in block_tr.low_slab_index],
                 list(block_va.low_slab_index)),
                ("HIGH", [i for i in range(len(tr)) if i not in block_tr.high_slab_index],
                 list(block_va.high_slab_index))):
            if len(va_idx) < MIN_STRATUM_POINTS or len(tr_idx) < 16:
                regime_out["slabs"][slab] = {"status": "INSUFFICIENT_POINTS",
                                             "n_train_outside_slab": len(tr_idx),
                                             "n_validation_in_slab": len(va_idx)}
                continue
            xt, yt = _matrix([tr[i] for i in tr_idx], fn), yt_tr_full[tr_idx]
            xv = _matrix([va[i] for i in va_idx], fn)
            yv = _targets([va[i] for i in va_idx], "pce_pct")
            fp = dataset_fingerprint([tr[i] for i in tr_idx])
            # reference: full-train model evaluated on the same slab rows.
            # The family is the V1.9-E validation-selected family (read from
            # committed results for comparability, not re-selected here).
            family = committed["model_comparison"][regime]["pce_pct"][
                "selected_family_by_independent_validation"]
            ref = fit_regressor(family,
                                _matrix(tr, fn), yt_tr_full, feature_names=fn,
                                target_name="pce_pct", unit="%",
                                training_fingerprint=dataset_fingerprint(tr),
                                seed=SEED + 100 + ri)
            # diagnostic: slab-withheld refit (same family, fewer rows)
            new = fit_regressor(ref.family, xt, yt, feature_names=fn,
                                target_name="pce_pct", unit="%",
                                training_fingerprint=fp, seed=SEED + 100 + ri)
            pr, _ = ref.predict(xv, return_std=False)
            pn, _ = new.predict(xv, return_std=False)
            regime_out["slabs"][slab] = {
                "status": "MEASURED",
                "family": ref.family,
                "n_train_outside_slab": len(tr_idx),
                "n_validation_in_slab": len(va_idx),
                "full_train_model_on_slab": regression_metrics(yv, pr, train_y=yt_tr_full),
                "slab_withheld_refit_on_slab": regression_metrics(yv, pn, train_y=yt),
            }
        out["by_regime"][regime] = regime_out
    return out


# --------------------------------------------------------------------------
# step 4: seven-family comparison with the corrected GP
# --------------------------------------------------------------------------
def step_families(bundle, cache, recs, fn, low, high, committed) -> dict:
    out: dict = {"families": list(MODEL_FAMILIES_V19F),
                 "grade_validation": "PREDECLARED_SELECTION_SET",
                 "grade_holdout": "DIAGNOSTIC_POST_HOC_RANKING (selection stays validation-based)",
                 "by_regime": {}}
    for ri, regime in enumerate(REGIME_NAMES):
        tr, va = cache["train"][regime], cache["validation"][regime]
        final = _rows(recs, regime=regime, roles=["FINAL_HOLDOUT"])
        xt = _matrix(tr, fn)
        yt = _targets(tr, "pce_pct")
        xv = _matrix(va, fn)
        yv = _targets(va, "pce_pct")
        xf = _matrix(final, fn)
        yf = _targets(final, "pce_pct")
        fp = dataset_fingerprint(tr)
        # Identical seed to the V1.9-E campaign PCE fits (target index 0), so
        # the original six families reproduce bit-for-bit and only the
        # corrected GP adds a new comparison point.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fitted, scores = compare_families(
                xt, yt, xv, yv, feature_names=fn, target_name="pce_pct", unit="%",
                training_fingerprint=fp, seed=V19E_SEED + 700 + 1000 * ri,
                families=MODEL_FAMILIES_V19F, bounds=(low, high))
        for fam in committed["model_comparison"][regime]["pce_pct"]["model_family_scores"]:
            assert abs(scores[fam]["rmse"] - committed["model_comparison"][regime][
                "pce_pct"]["model_family_scores"][fam]["rmse"]) <= 1e-9, (regime, fam)
        holdout_rmse = {}
        for fam, model in fitted.items():
            pred, _ = model.predict(xf, return_std=False)
            holdout_rmse[fam] = float(np.sqrt(np.mean((pred - yf) ** 2)))
        val_rank = sorted(scores, key=lambda f: (scores[f]["rmse"],
                                                 MODEL_FAMILIES_V19F.index(f)))
        gp = fitted["gaussian_process_matern_boxnorm"]
        gp_kernel = str(gp.estimator.named_steps["gp"].kernel_)
        # paired bootstrap of validation-RMSE differences vs the selected
        # family: quantifies selection uncertainty at n ~= 64 (B=2000,
        # fixed seed; no physics).
        sel = select_family(scores)
        boot_rng = np.random.default_rng(SEED + 4000 + ri)
        n_val = len(yv)
        e_sel = (fitted[sel].predict(xv, return_std=False)[0] - yv) ** 2
        rmse_sel = float(np.sqrt(np.mean(e_sel)))
        boot: dict = {}
        n_boot = 2000
        for fam, model in fitted.items():
            if fam == sel:
                continue
            e_other = (model.predict(xv, return_std=False)[0] - yv) ** 2
            rmse_other = float(np.sqrt(np.mean(e_other)))
            idx = boot_rng.integers(0, n_val, size=(n_boot, n_val))
            diffs = np.sqrt(np.mean(e_other[idx], axis=1)) - np.sqrt(
                np.mean(e_sel[idx], axis=1))
            boot[fam] = {
                "rmse_difference_other_minus_selected": rmse_other - rmse_sel,
                "ci_95_low": float(np.quantile(diffs, 0.025)),
                "ci_95_high": float(np.quantile(diffs, 0.975)),
                "prob_other_not_worse": float(np.mean(diffs <= 0.0)),
                "n_bootstrap": n_boot,
            }
        out["by_regime"][regime] = {
            "selected_by_validation_v19e": bundle.model_cards[regime]["pce_pct"][
                "selected_family_by_independent_validation"],
            "selected_by_validation_v19f_7way": select_family(scores),
            "validation_rmse": {f: scores[f]["rmse"] for f in val_rank},
            "selection_bootstrap_vs_selected": boot,
            "validation_ranking": val_rank,
            "holdout_rmse_diagnostic": holdout_rmse,
            "holdout_ranking_diagnostic": sorted(holdout_rmse, key=holdout_rmse.get),
            "boxnorm_gp_kernel": gp_kernel[:600],
            "boxnorm_gp_raw_holdout": raw_interval_coverage(
                yf, *gp.predict(xf, return_std=True)),
            "warnings": [{"category": w.category.__name__,
                          "message": str(w.message)[:250]} for w in caught],
        }
    return out


# --------------------------------------------------------------------------
# step 5: calibration audit by region
# --------------------------------------------------------------------------
def step_calibration(bundle, cache, recs, fn, low, high, spatial) -> dict:
    out: dict = {"method": "split-conformal marginal intervals; empirical coverage "
                           "re-measured per stratum (diagnostic, not conditional guarantee)",
                 "finite_sample": {"n_calibration": 64, "coverage": 0.90,
                                   "k_order_statistic": math.ceil(65 * 0.90)},
                 "by_regime": {}}
    for regime in REGIME_NAMES:
        model = bundle.selected_models[regime]["pce_pct"]
        radius = float(model.conformal_radius)
        regime_out: dict = {"conformal_radius_pp": radius, "strata": {}}
        train_rows = cache["train"][regime]
        ztr = normalize(_matrix(train_rows, fn), low, high)
        for label, roles in (("FINAL_HOLDOUT", ["FINAL_HOLDOUT"]),
                             ("BOUNDARY_VALIDATION", ["BOUNDARY_VALIDATION"]),
                             ("OOD_FINAL_corner", ["OOD_FINAL"])):
            rows = _rows(recs, regime=regime, roles=roles)
            if not rows:
                continue
            xe = _matrix(rows, fn)
            ye = _targets(rows, "pce_pct")
            pred, _ = model.predict(xe, return_std=False)
            dist = distance_to_training(normalize(xe, low, high), ztr)
            buffer = spatial["by_regime"][regime]["buffer_radius"]
            regime_out["strata"][label] = {
                "full": interval_metrics(ye, pred, radius=radius),
                "interpolation": (interval_metrics(ye[dist < buffer], pred[dist < buffer],
                                                  radius=radius)
                                  if int(np.sum(dist < buffer)) >= MIN_STRATUM_POINTS
                                  else {"status": "INSUFFICIENT_POINTS",
                                        "n": int(np.sum(dist < buffer))}),
                "separated": (interval_metrics(ye[dist >= buffer], pred[dist >= buffer],
                                               radius=radius)
                              if int(np.sum(dist >= buffer)) >= MIN_STRATUM_POINTS
                              else {"status": "INSUFFICIENT_POINTS",
                                    "n": int(np.sum(dist >= buffer))}),
            }
        out["by_regime"][regime] = regime_out
    return out


# --------------------------------------------------------------------------
# step 6: new withheld-corner physics + frozen-detector evaluation
# --------------------------------------------------------------------------
def _corner_designs(fn, low, high, regime_index: int) -> dict[str, np.ndarray]:
    designs = {}
    for ci, (name, box) in enumerate(NEW_CORNER_BOXES.items()):
        z = lhs_in_normalized_box(N_NEW_CORNER_PER_REGIME, len(fn), box,
                                  SEED + 2000 + regime_index * 100 + ci)
        designs[name] = denormalize(z, low, high)
    return designs


def step_new_corners(recs, fn, low, high, low_map, high_map, sens,
                     code_digest, reg_digest, bundle) -> tuple[dict, list[dict]]:
    from apmt.multifidelity.levels import options_for

    new_rows: list[dict] = []
    eval_out: dict = {"grade": "FINAL (frozen V1.9-E thresholds; no tuning on new labels)",
                      "n_per_corner_per_regime": N_NEW_CORNER_PER_REGIME,
                      "design": "independent uniform LHS inside each predeclared corner box; "
                                "seed = SEED + 2000 + regime_index * 100 + corner_index",
                      "corner_boxes_normalized": {k: list(v)
                                                  for k, v in NEW_CORNER_BOXES.items()},
                      "by_regime": {}}
    for ri, regime in enumerate(REGIMES):
        phys = vc._physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        designs = _corner_designs(fn, low, high, ri)
        regime_out: dict = {"corners": {}}
        all_corner_x = []
        for name, X in designs.items():
            rows, _summary = vc._generate_group(
                X=X, feature_names=fn, regime=regime, level="L4",
                role=f"V19F_OOD_{name}", family=f"v19f-newcorner-{name}-{regime.name}",
                seed=SEED + 2000 + ri * 100, model_form="IQE-M1",
                physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            new_rows.extend(rows)
            valid = [r for r in rows if r["status"] == VALID_FOR_SURROGATE]
            corner_x = _matrix(valid, fn) if valid else np.empty((0, len(fn)))
            all_corner_x.append(corner_x)
            regime_out["corners"][name] = {
                "n_requested": len(rows),
                "n_valid": len(valid),
                "n_invalid": sum(r["status"] != VALID_FOR_SURROGATE for r in rows),
            }
        profile = bundle.support_profiles[regime.name]
        final_rows = _rows(recs, regime=regime.name, roles=["FINAL_HOLDOUT"])
        in_x = _matrix(final_rows, fn)
        # per-corner recall with trigger decomposition
        for name in designs:
            corner_rows = [r for r in new_rows
                           if r.get("role") == f"V19F_OOD_{name}"
                           and r.get("operating_regime", {}).get("name") == regime.name
                           and r.get("status") == VALID_FOR_SURROGATE]
            statuses = [profile.classify(
                [float(r["parameters"][n]) for n in fn])["status"] for r in corner_rows]
            regime_out["corners"][name]["recall_out_of_domain"] = (
                float(np.mean([s == OUT_OF_DOMAIN for s in statuses])) if statuses else None)
            regime_out["corners"][name]["uncertain_rate"] = (
                float(np.mean([s == IN_DOMAIN_UNCERTAIN for s in statuses]))
                if statuses else None)
            regime_out["corners"][name]["validated_rate"] = (
                float(np.mean([s == IN_DOMAIN_VALIDATED for s in statuses]))
                if statuses else None)
        pooled = np.vstack(all_corner_x) if any(len(a) for a in all_corner_x) else np.empty((0, len(fn)))
        regime_out["pooled_new_corner_recall"] = (
            float(np.mean([profile.classify(x)["status"] == OUT_OF_DOMAIN for x in pooled]))
            if len(pooled) else None)
        regime_out["pooled_new_corner_n"] = len(pooled)
        in_statuses = [profile.classify(x)["status"] for x in in_x]
        regime_out["in_box_final_false_ood_rate"] = float(
            np.mean([s == OUT_OF_DOMAIN for s in in_statuses]))
        regime_out["in_box_final_uncertain_rate"] = float(
            np.mean([s == IN_DOMAIN_UNCERTAIN for s in in_statuses]))
        regime_out["in_box_final_n"] = len(in_statuses)
        eval_out["by_regime"][regime.name] = regime_out
    return eval_out, new_rows


# --------------------------------------------------------------------------
# step 7: invalid rows vs detector (detector must not replace invariants)
# --------------------------------------------------------------------------
def step_invalid_probe(bundle, recs, fn) -> dict:
    invalid = [r for r in recs if r.get("status") != VALID_FOR_SURROGATE
               and r.get("model_level") == "L4"]
    detail = []
    for r in invalid:
        regime = r["operating_regime"]["name"]
        x = [float(r["parameters"][n]) for n in fn]
        support = bundle.support_profiles[regime].classify(x)["status"]
        verdict = bundle.verify_candidate({n: float(r["parameters"][n]) for n in fn},
                                          regime=regime, run_l5=False)
        detail.append({"sample_id": r["sample_id"], "regime": regime, "role": r["role"],
                       "status": r["status"], "reason": r.get("status_reason", ""),
                       "support_status": support,
                       "verify_candidate_status": verdict["candidate_status"],
                       "eligible": verdict["candidate_eligible_for_optimizer"]})
    return {"n_invalid_probed": len(detail),
            "support_status_counts": {s: sum(d["support_status"] == s for d in detail)
                                      for s in (IN_DOMAIN_VALIDATED, IN_DOMAIN_UNCERTAIN,
                                                OUT_OF_DOMAIN)},
            "any_eligible": any(d["eligible"] for d in detail),
            "rows": detail}


# --------------------------------------------------------------------------
# step 8: controlled candidate-selection study on the 3-D optimum slices
# --------------------------------------------------------------------------
def _refit_slice_model(recs, regime, names3, seed):
    tr3 = [r for r in recs if r.get("role") == "OPTIMUM_TRAIN"
           and r.get("status") == VALID_FOR_SURROGATE
           and r.get("operating_regime", {}).get("name") == regime]
    va3 = [r for r in recs if r.get("role") == "OPTIMUM_VALIDATION"
           and r.get("status") == VALID_FOR_SURROGATE
           and r.get("operating_regime", {}).get("name") == regime]
    cal3 = [r for r in recs if r.get("role") == "OPTIMUM_CALIBRATION"
            and r.get("status") == VALID_FOR_SURROGATE
            and r.get("operating_regime", {}).get("name") == regime]
    fp3 = dataset_fingerprint(tr3)
    model, alts, scores, cal = vc._single_model_set(
        train_rows_=tr3, validation_rows=va3, calibration_rows=cal3,
        feature_names=names3, target="pce_pct", seed=seed, training_fp=fp3)
    return model, alts, scores, cal, tr3, va3, cal3


def step_optimum_slice(recs, fn, low_map, high_map, code_digest, reg_digest,
                       committed) -> tuple[dict, list[dict]]:
    from apmt.multifidelity.levels import options_for
    from apmt.params.registry import ParamSet

    names3 = list(vc.OPTIMUM_AXES)
    low3 = np.array([low_map[n] for n in names3], float)
    high3 = np.array([high_map[n] for n in names3], float)
    out: dict = {"scope": "three-input L4 slice surrogate per regime (V1.9-E scope)",
                 "budget": {"pool_n": CANDIDATE_POOL_N, "k_per_method": CANDIDATE_K,
                            "seeds": list(CANDIDATE_SEEDS)},
                 "by_regime": {}}
    new_rows: list[dict] = []
    for ri, regime in enumerate(REGIMES):
        model, alts, _scores, _cal, tr3, _va3, _cal3 = _refit_slice_model(
            recs, regime.name, names3, V19E_SEED + 920 + ri)
        stored = committed["interior_optimum_recovery"][regime.name]
        assert model.family == stored["selected_family"], (regime.name, model.family)
        # diagnosis: training coverage near the verification curves
        curve_rows = [r for r in recs if r.get("role") == "OPTIMUM_FINAL_VERIFICATION"
                      and r.get("status") == VALID_FOR_SURROGATE
                      and r.get("operating_regime", {}).get("name") == regime.name]
        xtr3 = _matrix(tr3, names3)
        z_tr3 = (xtr3 - low3) / (high3 - low3)
        curve_diagnostics = {}
        for axis in names3:
            axis_rows = [r for r in curve_rows if axis in r.get("design_family", "")]
            xc = _matrix(axis_rows, names3)
            dist = distance_to_training((xc - low3) / (high3 - low3), z_tr3)
            curve_diagnostics[axis] = {"n_curve_points": len(axis_rows),
                                       "distance_summary": summarize_distances(dist)}
        regime_out: dict = {
            "selected_family": model.family,
            "curve_coverage_diagnostics": curve_diagnostics,
            "per_seed": {},
        }
        base_vec = ParamSet.defaults().with_mapping(regime.settings).to_vector(fn)
        axis_index = {n: fn.index(n) for n in names3}
        for seed in CANDIDATE_SEEDS:
            rng = np.random.default_rng(seed + 77 * ri)
            pool3 = low3 + rng.random((CANDIDATE_POOL_N, 3)) * (high3 - low3)
            pred, _ = model.predict(pool3, return_std=False)
            alt_stack = np.column_stack([pred] + [a.predict(pool3, return_std=False)[0]
                                                  for a in alts])
            disagreement = (np.std(alt_stack, axis=1, ddof=1) if alt_stack.shape[1] > 1
                            else np.zeros(len(pred)))
            order_pred = np.argsort(-pred, kind="stable")
            top_q = order_pred[: max(CANDIDATE_K * 4, len(pred) // 4)]
            # diverse: farthest-point over the top quartile in normalized coords
            znorm = (pool3 - low3) / (high3 - low3)
            diverse = [int(top_q[0])]
            while len(diverse) < CANDIDATE_K:
                rest = [i for i in top_q if i not in diverse]
                dmin = np.min(
                    np.linalg.norm(znorm[rest][:, None, :] - znorm[diverse][None, :, :],
                                   axis=2), axis=1)
                diverse.append(int(rest[int(np.argmax(dmin))]))
            ucb = pred + disagreement
            order_ucb = np.argsort(-ucb, kind="stable")
            rng_choice = np.random.default_rng(seed + 913 * ri)
            picks = {
                "max_predicted_pce": order_pred[:CANDIDATE_K].tolist(),
                "uncertainty_aware_disagreement_ucb": order_ucb[:CANDIDATE_K].tolist(),
                "diverse_top_quartile": diverse,
                "random_pool_baseline": rng_choice.choice(
                    CANDIDATE_POOL_N, CANDIDATE_K, replace=False).tolist(),
            }
            seed_out: dict = {"methods": {}}
            for method, idx in picks.items():
                verified, proposals = [], []
                for j in idx:
                    full = np.array(base_vec, float)
                    for aj, name in enumerate(names3):
                        full[axis_index[name]] = pool3[j, aj]
                    proposals.append(full)
                Xfull = np.vstack(proposals)
                phys = vc._physics_digest_for_regime(code_digest, reg_digest, regime,
                                                     "L4", "IQE-M1")
                rows, _summary = vc._generate_group(
                    X=Xfull, feature_names=fn, regime=regime, level="L4",
                    role="V19F_CANDIDATE_VERIFY",
                    family=f"v19f-candidate-{method}-{regime.name}-{seed}",
                    seed=seed, model_form="IQE-M1", physics_digest=phys,
                    low=low_map, high=high_map,
                    solver_options=options_for("L4").to_dict())
                new_rows.extend(rows)
                for row, j in zip(rows, idx):
                    verified.append({
                        "predicted_pce": float(pred[j]),
                        "disagreement": float(disagreement[j]),
                        "verified_pce": (float(row["outputs"]["pce_pct"])
                                         if row["status"] == VALID_FOR_SURROGATE
                                         and row.get("outputs") else None),
                        "status": row["status"],
                        "sample_id": row["sample_id"]})
                ok = [v for v in verified if v["verified_pce"] is not None]
                if len(ok) >= 2:
                    rp = np.argsort(np.argsort([v["predicted_pce"] for v in ok]))
                    rv = np.argsort(np.argsort([v["verified_pce"] for v in ok]))
                    spearman = float(np.corrcoef(rp, rv)[0, 1])
                else:
                    spearman = None
                seed_out["methods"][method] = {
                    "n_verified": len(ok), "n_invalid": len(verified) - len(ok),
                    "best_verified_pce": (max(v["verified_pce"] for v in ok)
                                          if ok else None),
                    "mean_verified_pce": (float(np.mean([v["verified_pce"] for v in ok]))
                                          if ok else None),
                    "spearman_predicted_vs_verified": spearman,
                    "proposals": verified,
                }
            regime_out["per_seed"][str(seed)] = seed_out
        out["by_regime"][regime.name] = regime_out
    return out, new_rows


# --------------------------------------------------------------------------
# step 9: interaction support characterization
# --------------------------------------------------------------------------
def step_interaction(recs, fn, low_map, high_map, committed) -> dict:
    from apmt.surrogate.domain import IN_DOMAIN_UNCERTAIN as UNC
    from apmt.surrogate.domain import IN_DOMAIN_VALIDATED as VAL
    from apmt.surrogate.domain import OUT_OF_DOMAIN as OOD

    axes = list(vc.INTERACTION_AXES)
    lo4 = np.array([low_map[n] for n in axes], float)
    hi4 = np.array([high_map[n] for n in axes], float)
    nominal = "nominal_1sun_25c"
    tr = [r for r in recs if r.get("role") == "INTERACTION_TRAIN"
          and r.get("status") == VALID_FOR_SURROGATE]
    va = [r for r in recs if r.get("role") == "INTERACTION_VALIDATION"
          and r.get("status") == VALID_FOR_SURROGATE]
    cal = [r for r in recs if r.get("role") == "INTERACTION_CALIBRATION"
           and r.get("status") == VALID_FOR_SURROGATE]
    final = [r for r in recs if r.get("role") == "INTERACTION_FINAL"
             and r.get("status") == VALID_FOR_SURROGATE]
    Xi_tr, yi_tr = vc._xy(tr, axes, "pce_pct")
    Xi_va, yi_va = vc._xy(va, axes, "pce_pct")
    Xi_cal, yi_cal = vc._xy(cal, axes, "pce_pct")
    fp = dataset_fingerprint(tr)
    fits, scores = compare_families(
        Xi_tr, yi_tr, Xi_va, yi_va, feature_names=axes, target_name="pce_pct",
        unit="%", training_fingerprint=fp, seed=V19E_SEED + 1110)
    selected = select_family(scores)
    stored = committed["interaction_recovery"]
    assert selected == stored["slice_selected_family"], (selected, stored["slice_selected_family"])
    model = fits[selected]
    _q = conformal_radius(yi_cal, model.predict(Xi_cal, return_std=False)[0], coverage=0.90)
    assert _q is not None
    # refit the 4-D support profile from the same calibration rows
    in_rows = [r for r in recs if r.get("role") == "SUPPORT_IN_CAL"
               and r.get("operating_regime", {}).get("name") == nominal]
    ood_rows = [r for r in recs if r.get("role") == "OOD_CALIBRATION"
                and r.get("operating_regime", {}).get("name") == nominal]
    X_in4 = _matrix(in_rows, axes)
    X_ood4 = _matrix(ood_rows, axes)
    p_in4 = _matrix(tr, axes)
    cal_rmse = float(regression_metrics(
        yi_cal, model.predict(Xi_cal, return_std=False)[0], train_y=yi_tr)["rmse"])
    ordered = sorted(scores, key=lambda f: (scores[f]["rmse"], f))
    alts = [fits[k] for k in ordered if k != selected][:2]
    disagreement, uncertainty = [], []
    for x in Xi_cal:
        mu, sd = model.predict(x, return_std=True)
        vals = [float(mu[0])] + [float(a.predict(x, return_std=False)[0][0]) for a in alts]
        disagreement.append(float(np.std(vals, ddof=1)) / max(cal_rmse, 1e-12))
        if sd is not None:
            uncertainty.append(float(sd[0]) / max(model.target_scale, 1e-12))
    profile = fit_support_profile(
        feature_names=axes, low=lo4, high=hi4, training_X=p_in4,
        in_domain_calibration_X=X_in4, withheld_region_calibration_X=X_ood4,
        uncertainty_ratios=uncertainty, disagreement_ratios=disagreement,
        max_false_positive_rate=0.10)
    stored_prof = stored["support_detection_profile"]
    assert abs(profile.nearest_distance_ood_threshold
               - stored_prof["nearest_distance_ood_threshold"]) <= 1e-9
    Xint = _matrix(final, axes)
    _y_true = _targets(final, "pce_pct")
    _y_pred, _ = model.predict(Xint, return_std=False)
    statuses = [profile.classify(x)["status"] for x in Xint]
    counts = {s: sum(1 for z in statuses if z == s) for s in (VAL, UNC, OOD)}
    assert counts == {k: stored["support_status_counts_on_full_interaction_design"][k]
                      for k in counts}, counts
    z = normalize(Xint, lo4, hi4)
    by_status_coords = {}
    for s in (VAL, UNC, OOD):
        mask = np.array([z_ == s for z_ in statuses])
        by_status_coords[s] = (
            {"n": int(mask.sum()),
             "per_axis_median_normalized": np.median(z[mask], axis=0).round(4).tolist(),
             "per_axis_mean_normalized": np.mean(z[mask], axis=0).round(4).tolist()}
            if mask.sum() else {"n": 0})
    # candidate supported sub-region (HYPOTHESIS ONLY): central box where the
    # validated share is highest; requires fresh Saltelli verification.
    central = np.all((z >= 0.15) & (z <= 0.85), axis=1)
    central_statuses = [s for s, m in zip(statuses, central) if m]
    hypothesis = {
        "grade": "HYPOTHESIS_NOT_VALIDATED",
        "region": "normalized [0.15, 0.85]^4 on the interaction axes",
        "n_design_points_inside": int(central.sum()),
        "validated_share_inside": (float(np.mean([s == VAL for s in central_statuses]))
                                   if central_statuses else None),
        "note": "defining a supported region from the same design that estimated "
                "the pair effect would be circular; a fresh Saltelli design inside "
                "this box is required before any reportable claim (NOT_RUN)",
    }
    return {
        "refit_status": "REFIT_BIT_IDENTICAL",
        "selected_family": selected,
        "support_counts": counts,
        "support_status_by_coordinates": by_status_coords,
        "pair_l4": stored["new_l4_pair_estimate"],
        "pair_surrogate": stored["surrogate_pair_estimate"],
        "surrogate_pair_reportable": stored[
            "surrogate_pair_reportable_only_if_domain_and_calibration_pass"],
        "supported_subregion_hypothesis": hypothesis,
        "saltelli_on_validated_subset": "NOT_ESTIMABLE (subset breaks the "
                                        "structured design); full-design surrogate "
                                        "pair stays NOT_REPORTABLE",
    }


# --------------------------------------------------------------------------
# step 10: cost benchmarks
# --------------------------------------------------------------------------
def step_cost(bundle, recs, fn, low, high, refit_wall_s) -> dict:
    l4_times = [float(s["runtime_s"]) for s in recs
                if s.get("model_level") == "L4" and s.get("runtime_s", 0) > 0]
    regime = REGIME_NAMES[0]
    probe = {n: float((low[i] + high[i]) / 2.0) for i, n in enumerate(fn)}
    n_timing = 64
    t0 = time.perf_counter()
    for _ in range(n_timing):
        bundle.predict(probe, regime=regime)
    single_total = time.perf_counter() - t0
    single_latency = single_total / n_timing
    Xb = vc._lhs_box(256, low, high, SEED + 1500, exclude_withheld_corner=True)
    maps = [{n: float(v) for n, v in zip(fn, row)} for row in Xb]
    t0 = time.perf_counter()
    out = bundle.predict_batch(maps, regime=regime)
    batch_wall = time.perf_counter() - t0
    assert out["batch_status"] == "BATCH_COMPLETE"
    l4_median = float(np.median(l4_times))
    batch_per_point = batch_wall / len(maps)
    return {
        "l4_solve_runtime_s_median_committed": l4_median,
        "bundle_single_prediction_latency_s": single_latency,
        "single_speedup_vs_median_l4": l4_median / single_latency,
        "predeclared_minimum_speedup": vc.MIN_SURROGATE_SPEEDUP_VS_L4,
        "single_speedup_target_met": bool(
            l4_median / single_latency >= vc.MIN_SURROGATE_SPEEDUP_VS_L4),
        "batch_256_wall_s": batch_wall,
        "batch_amortized_s_per_point": batch_per_point,
        "batch_amortized_speedup_vs_median_l4": l4_median / batch_per_point,
        "batch_numerics": "row-identical to predict() within 1e-9 (verified in tests)",
        "refit_wall_s": refit_wall_s,
        "note": "single-point latency target unchanged (NOT_MET); batch "
                "throughput is the deployment path and is reported separately",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--new-rows", type=Path, default=DEFAULT_NEW_ROWS_PATH)
    parser.add_argument("--skip-physics", action="store_true",
                        help="run refit-only analyses; skip new L4/L5 solves")
    args = parser.parse_args(argv)

    t_campaign = time.perf_counter()
    ds, committed, recs = _load_committed()
    with open(SENSITIVITY_ARTIFACT) as _f:
        sens = json.load(_f)
    fn, low, high = _feature_box(sens)
    low_map = {k: float(v) for k, v in sens["shared_box"]["low"].items()}
    high_map = {k: float(v) for k, v in sens["shared_box"]["high"].items()}
    code_digest, code_files = vc._physics_code_digest()
    reg_digest = vc._registry_digest()
    assert code_digest == committed["metadata"]["physics_source_digest"]
    assert reg_digest == committed["metadata"]["registry_digest"]

    print("V1.9-F step 1/10: refit fidelity gate", flush=True)
    refit, bundle, cache = step_refit_fidelity(recs, committed, fn, low, high)
    print("V1.9-F step 2/10: spatial stratification", flush=True)
    spatial = step_spatial(bundle, cache, recs, fn, low, high)
    print("V1.9-F step 3/10: diagnostic block refits", flush=True)
    blocks = step_block_refits(recs, fn, low, high, committed)
    print("V1.9-F step 4/10: seven-family comparison", flush=True)
    families = step_families(bundle, cache, recs, fn, low, high, committed)
    print("V1.9-F step 5/10: calibration audit", flush=True)
    calibration = step_calibration(bundle, cache, recs, fn, low, high, spatial)

    new_rows: list[dict] = []
    if args.skip_physics:
        ood = {"status": "NOT_RUN (--skip-physics)"}
        invalid_probe = {"status": "NOT_RUN (--skip-physics)"}
        optimum = {"status": "NOT_RUN (--skip-physics)"}
    else:
        print("V1.9-F step 6/10: new withheld-corner physics", flush=True)
        ood, corner_rows = step_new_corners(recs, fn, low, high, low_map, high_map,
                                            sens, code_digest, reg_digest, bundle)
        new_rows.extend(corner_rows)
        print("V1.9-F step 7/10: invalid-row probe", flush=True)
        invalid_probe = step_invalid_probe(bundle, recs, fn)
        print("V1.9-F step 8/10: candidate-selection study", flush=True)
        optimum, cand_rows = step_optimum_slice(recs, fn, low_map, high_map,
                                                code_digest, reg_digest, committed)
        new_rows.extend(cand_rows)
    print("V1.9-F step 9/10: interaction support", flush=True)
    interaction = step_interaction(recs, fn, low_map, high_map, committed)
    print("V1.9-F step 10/10: cost benchmarks", flush=True)
    cost = step_cost(bundle, recs, fn, low, high, refit["refit_wall_s"])

    meta = vc._environment_metadata(SEED, code_digest, code_files)
    meta.update({
        "campaign_id": "v19f-reliability-20261010",
        "seed": SEED,
        "committed_dataset_sha256": _sha_bytes(COMMITTED_DATASET.read_bytes()),
        "committed_results_sha256": _sha_bytes(COMMITTED_RESULTS.read_bytes()),
        "committed_dataset_fingerprint": ds["dataset_fingerprint"],
        "feature_names": fn,
        "new_roles": sorted({r.get("role", "") for r in new_rows}),
    })
    results = {
        "campaign": "V1.9-F surrogate reliability, spatial generalization, "
                    "optimization readiness",
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY; no experimental data or claim",
        "seed": SEED,
        "v19e_seed": V19E_SEED,
        "metadata": meta,
        "protocol": protocol_declaration(),
        "refit_fidelity": refit,
        "spatial_stratification": spatial,
        "diagnostic_block_refits": blocks,
        "family_comparison_7way": families,
        "calibration_by_region": calibration,
        "new_corner_ood": ood,
        "invalid_row_probe": invalid_probe,
        "optimum_slice_selection_study": optimum,
        "interaction_support": interaction,
        "cost": cost,
        "campaign_runtime_s": float(time.perf_counter() - t_campaign),
        "status": "PRE_GATE_COMPUTATIONAL_RELIABILITY_AUDIT",
    }
    vc._assert_json_finite(results)
    new_rows = mark_duplicates(new_rows)
    new_artifact = save_dataset(args.new_rows, new_rows, metadata=meta,
                                extra={"campaign": "V1.9-F",
                                       "sample_count": len(new_rows)})
    results["new_rows_artifact"] = new_artifact
    results["campaign_runtime_s"] = float(time.perf_counter() - t_campaign)
    result_file = vc._write_json(Path(args.results), results)
    print(json.dumps({"status": results["status"],
                      "result_artifact": result_file,
                      "new_rows_artifact": new_artifact}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
