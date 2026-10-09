"""Reproducible V1.9-E data generation, benchmarking and surrogate training."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..device.batch import batch_evaluate
from ..multifidelity.levels import options_for
from ..params.registry import ParamSet, all_specs, spec, vector_names
from ..sensitivity.campaign import DESIGN_PARAMETERS, REGIMES
from ..sensitivity.sobol import saltelli_design, sobol_indices
from ..validation.guard import evaluate_guarded
from .adaptive import localize_high_errors, propose_near_errors
from .data import (DUPLICATE_OR_DEPENDENT, INVALID_PHYSICS, OUTSIDE_VERIFIED_DOMAIN,
                   VALID_FOR_SURROGATE, OUTPUT_NAMES, OUTPUT_UNITS, dataset_fingerprint,
                   make_sample_record, mark_duplicates, physics_configuration_digest,
                   save_dataset, summarize_samples, training_rows)
from .domain import (IN_DOMAIN_UNCERTAIN, IN_DOMAIN_VALIDATED, MODEL_UNAVAILABLE,
                     OUT_OF_DOMAIN, detection_metrics, fit_support_profile,
                     nearest_distances, normalize)
from .engine import SurrogateBundle, save_bundle
from .models import (MODEL_FAMILIES, compare_families, conformal_radius,
                     interval_metrics, raw_interval_coverage, regression_metrics,
                     select_family, fit_regressor, grouped_kfold_indices)

ROOT = Path(__file__).resolve().parents[2]
SENSITIVITY_ARTIFACT = ROOT / "data" / "v19_sensitivity.json"
DEFAULT_DATASET_PATH = ROOT / "data" / "v19e_surrogate_dataset_v3.json.gz"
DEFAULT_RESULTS_PATH = ROOT / "data" / "v19e_surrogate_results_v3.json"
DEFAULT_MODEL_PATH = ROOT / "data" / "v19e_surrogate_models_v3.joblib"
INTERACTION_AXES = ("perovskite_eg_ev", "perovskite_thickness_nm",
                    "rs_ohm_cm2", "arc_thickness_nm")
OPTIMUM_AXES = ("perovskite_eg_ev", "perovskite_thickness_nm", "arc_thickness_nm")
REGIME_NAMES = tuple(r.name for r in REGIMES)
ACCURACY_TARGET_PCE_RMSE_PP = 0.25
MARGINAL_IMPROVEMENT_FRACTION = 0.05
MIN_SURROGATE_SPEEDUP_VS_L4 = 10.0


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False, default=str).encode()
    return _sha_bytes(raw)


def _git(command: Sequence[str], default: str = "UNKNOWN") -> str:
    try:
        return subprocess.check_output(["git", *command], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return default


def _registry_digest() -> str:
    rows = [{"name": s.name, "unit": s.unit, "default": float(s.default),
             "low": float(s.low), "high": float(s.high), "fixed": bool(s.fixed),
             "category": str(getattr(s.category, "value", s.category)),
             "range_class": str(getattr(s.range_class, "value", s.range_class))}
            for s in all_specs()]
    return _canonical_sha(rows)


def _physics_code_digest() -> tuple[str, dict[str, str]]:
    relative = (
        "apmt/core/constants.py", "apmt/core/numerics.py", "apmt/params/registry.py",
        "apmt/spectra/reference.py", "apmt/materials/perovskite.py",
        "apmt/materials/silicon.py", "apmt/optics/tmm.py", "apmt/optics/stack.py",
        "apmt/device/recombination.py", "apmt/device/subcell.py", "apmt/device/tandem.py",
        "apmt/device/thermal.py", "apmt/multifidelity/levels.py",
        "apmt/validation/invariants.py", "apmt/validation/guard.py",
        "data/spectra/astm_g173_am15g_nlr.npz",
        "data/materials/silicon_green_keevers_1995.npz",
    )
    hashes = {name: _sha_bytes((ROOT / name).read_bytes()) for name in relative}
    return _canonical_sha(hashes), hashes


def _environment_metadata(seed: int, code_digest: str, code_files: Mapping[str, str]) -> dict:
    try:
        import sklearn
        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = "NOT_INSTALLED"
    try:
        import scipy
        scipy_version = scipy.__version__
    except Exception:
        scipy_version = "NOT_INSTALLED"
    try:
        import numpy
        numpy_version = numpy.__version__
    except Exception:
        numpy_version = "NOT_INSTALLED"
    try:
        import psutil
        memory = int(psutil.Process().memory_info().rss)
    except Exception:
        memory = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    return {
        "git_commit_at_data_generation": _git(["rev-parse", "HEAD"]),
        "git_dirty_at_data_generation": bool(_git(["status", "--porcelain"])),
        "branch": _git(["branch", "--show-current"]),
        "python": platform.python_version(), "numpy": numpy_version,
        "scipy": scipy_version, "scikit_learn": sklearn_version,
        "platform": platform.platform(), "processor": platform.processor(),
        "seed_root": int(seed), "registry_size": len(all_specs()),
        "registry_digest": _registry_digest(),
        "physics_source_digest": code_digest,
        "physics_source_file_sha256": dict(code_files),
        "operating_system": os.name,
        "start_rss_bytes": memory,
    }


def _audit_existing_data() -> dict:
    """Count what the committed V1.9-D artifacts actually retain as row data."""
    if not SENSITIVITY_ARTIFACT.exists():
        raise FileNotFoundError(SENSITIVITY_ARTIFACT)
    with SENSITIVITY_ARTIFACT.open() as f:
        art = json.load(f)
    from ..repro.digest import physics_digest
    digest_ok = physics_digest(art) == art.get("physics_digest", {}).get("sha256")
    curve = {}
    for name, entry in art.get("response_shape", {}).items():
        axes = entry.get("per_parameter", {})
        curve[name] = {
            "level": entry.get("level"), "axes": len(axes),
            "stored_pce_only_curve_values": int(sum(
                len(row.get("curve", {}).get("pce_pct", [])) for row in axes.values())),
            "aggregate_valid_curve_points": int(sum(row.get("n_valid", 0)
                                                     for row in axes.values())),
            "outputs_per_curve_point": ["pce_pct"],
            "row_level_hard_invariant_records": False,
        }
    levels = {r: {lv: {"eligible_complete_rows": 0,
                       "reason": "no persisted raw per-point parameter/output/invariant table"}
                  for lv in ("L4", "L5")}
              for r in REGIME_NAMES}
    other: dict = {}
    oat_path = ROOT / "data" / "v19_oat_sensitivity.json"
    if oat_path.exists():
        oat = json.loads(oat_path.read_text())
        other["oat"] = {"stored_axis_point_rows": int(sum(
            len(v.get("points", [])) for v in oat.get("params", {}).values())),
            "axis_count": len(oat.get("params", {})),
            "complete_hard_invariant_contract": False,
            "eligible_multivariate_rows": 0}
    engine_path = ROOT / "data" / "v19_engine_campaign.json"
    if engine_path.exists():
        engine = json.loads(engine_path.read_text())
        other["engine"] = {
            "oracle_agreement_rows": len(engine.get("oracle_agreement", {}).get("rows", [])),
            "fidelity_divergence_parameter_points": len(engine.get("divergence", {}).get("rows", [])),
            "each_divergence_point_has_paired_levels": list(
                engine.get("divergence", {}).get("levels", {})),
            "feature_dimension": len(engine.get("divergence", {}).get("parameters", [])),
            "eligible_multivariate_rows": 0,
            "reason": "small six-axis paired diagnostic; lacks row-level hard invariants and full 14-axis design support"}
    mechanism_path = ROOT / "data" / "v19_mechanism_campaign.json"
    if mechanism_path.exists():
        mech = json.loads(mechanism_path.read_text())
        other["mechanism"] = {"lhs_summary_n": mech.get("lhs", {}).get("n_samples"),
                              "stored_per_point_rows": 0,
                              "eligible_multivariate_rows": 0}
    d_counts = {}
    for reg, section in art.get("regimes", {}).items():
        d_counts[reg] = {
            "level": section.get("level"),
            "sobol_design_replicates": len(section.get("designs", [])),
            "sobol_samples_per_replicate": [d.get("n_base") for d in section.get("designs", [])],
            "reported_l4_evaluations": int(sum(d.get("n_evaluations", 0)
                                                for d in section.get("designs", []))),
            "raw_outputs_persisted": False,
            "eligible_rows": 0,
        }
    interaction_evals = int(sum(
        item.get("design", {}).get("n_evaluations", 0)
        for item in art.get("interaction_study", {}).get("results", {}).values()))
    return {
        "audited_at_commit": _git(["rev-parse", "HEAD"]),
        "sensitivity_artifact_sha256": _sha_bytes(SENSITIVITY_ARTIFACT.read_bytes()),
        "sensitivity_physics_digest_verified": bool(digest_ok),
        "feature_dimensions": len(art.get("design_parameters", [])),
        "regimes": list(art.get("regimes", {})),
        "analysis_fidelity": art.get("levels", {}).get("analysis"),
        "verification_fidelity": art.get("levels", {}).get("verification"),
        "eligible_complete_independent_rows_by_regime_and_fidelity": levels,
        "v19d_sobol": d_counts,
        "v19d_interaction_l4_evaluations_summary_only": interaction_evals,
        "v19d_l5": {"n_base": art.get("l5_verification", {}).get("n_base"),
                    "eligible_rows": 0, "raw_paired_rows_persisted": False},
        "one_dimensional_pce_curve_rows_not_multivariate_training": curve,
        "other_partial_artifacts": other,
        "leakage_and_dependence": {
            "sobol_blocks": "A/B/AB/BA paired blocks are dependent by design; not independent iid rows",
            "replicates": "two deterministic Sobol design families per regime; raw rows not retained",
            "crosscheck": "LHS cross-check reuses the Sobol A blocks, not an independent validation set",
            "l5": "L5 is paired with L4 for fidelity comparison, not an independent experimental observation",
            "response_shapes": "14 one-dimensional sweeps per regime share default-background slices; only PCE is stored",
            "exact_historical_duplicate_count": "UNRESOLVABLE from aggregate/fingerprint-only artifacts",
        },
        "eligible_training_points": 0,
        "conclusion": "V1.9-D retained design seeds/fingerprints and summaries, not row-level multivariate training records; existing sample count for contract-compliant regression is zero. New independently seeded L4 data are required.",
    }


def _unit_lhs(n: int, d: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(int(seed))
    u = np.empty((n, d), float)
    for j in range(d):
        u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return u


def _is_withheld_corner(X: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    z = normalize(np.asarray(X, float), low, high)
    return (z[:, 0] >= 0.90) & (z[:, 1] >= 0.90)


def _lhs_box(n: int, low: np.ndarray, high: np.ndarray, seed: int, *,
             exclude_withheld_corner: bool = False,
             existing: np.ndarray | None = None) -> np.ndarray:
    """Space-filling LHS inside verified bounds; optional reserved corner is excluded."""
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    if n < 1:
        return np.empty((0, len(lo)), float)
    accepted: list[np.ndarray] = []
    old = (np.empty((0, len(lo))) if existing is None else np.asarray(existing, float))
    scale = hi - lo
    for batch_i in range(32):
        need = n - len(accepted)
        if need <= 0:
            break
        candidate_n = max(need * 2, 32)
        unit = _unit_lhs(candidate_n, len(lo), seed + batch_i * 104729)
        cand = lo + unit * scale
        if exclude_withheld_corner:
            cand = cand[~_is_withheld_corner(cand, lo, hi)]
        prior = old if not accepted else np.vstack([old, np.asarray(accepted)])
        if len(prior) and len(cand):
            zc, zp = normalize(cand, lo, hi), normalize(prior, lo, hi)
            keep = np.ones(len(cand), bool)
            # cKDTree keeps candidate screening linearithmic in the sample count.
            from scipy.spatial import cKDTree
            distance, _ = cKDTree(zp).query(zc, k=1, workers=1)
            keep &= distance > 1e-7
            cand = cand[keep]
        for row in cand:
            accepted.append(row)
            if len(accepted) >= n:
                break
    if len(accepted) < n:
        raise RuntimeError(f"could not construct {n} unique LHS points inside verified box")
    return np.asarray(accepted[:n])


def _boundary_design(n: int, low: np.ndarray, high: np.ndarray, seed: int) -> np.ndarray:
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    X = _lhs_box(n, lo, hi, seed, exclude_withheld_corner=True)
    z = normalize(X, lo, hi)
    for i in range(n):
        j = i % X.shape[1]
        side = 0.025 if (i // X.shape[1]) % 2 == 0 else 0.975
        z[i, j] = side
    out = lo + z * (hi - lo)
    # A fixed-boundary design may fall into the reserved two-axis corner; replace
    # those rows with interior points and repeat the boundary on a different axis.
    bad = _is_withheld_corner(out, lo, hi)
    for i in np.flatnonzero(bad):
        j = (int(i) + 2) % out.shape[1]
        z[i, 0] = 0.50
        z[i, j] = 0.025 if i % 2 == 0 else 0.975
    return lo + z * (hi - lo)


def _withheld_corner_design(n: int, low: np.ndarray, high: np.ndarray,
                            seed: int) -> np.ndarray:
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    u = _unit_lhs(n, len(lo), seed)
    u[:, 0] = 0.90 + 0.10 * u[:, 0]
    u[:, 1] = 0.90 + 0.10 * u[:, 1]
    return lo + u * (hi - lo)


def _full_design_from_subspace(subspace: np.ndarray, names: Sequence[str],
                               regime_settings: Mapping[str, float]) -> np.ndarray:
    defaults = ParamSet.defaults().with_mapping(regime_settings)
    full_names = tuple(names)
    X = np.tile(defaults.to_vector(full_names), (len(subspace), 1))
    lookup = {n: i for i, n in enumerate(full_names)}
    for j, name in enumerate(OPTIMUM_AXES):
        X[:, lookup[name]] = np.asarray(subspace)[:, j]
    return X


def _regime_meta(regime) -> dict:
    return {"name": regime.name, **{k: float(v) for k, v in regime.settings.items()}}


def _base_for_regime(regime) -> ParamSet:
    return ParamSet.defaults().with_mapping(regime.settings)


def _generate_group(*, X: np.ndarray, feature_names: Sequence[str], regime,
                    level: str, role: str, family: str, seed: int,
                    model_form: str, physics_digest: str,
                    low: Mapping[str, float], high: Mapping[str, float],
                    solver_options: Mapping[str, Any]) -> tuple[list[dict], dict]:
    campaign_id = f"v19e-{family}-{regime.name}-{level.lower()}"
    X = np.asarray(X, float)
    recs, summary = batch_evaluate(
        X, tuple(feature_names), level=level,
        model_form=model_form, campaign_id=campaign_id, seed=int(seed),
        base=_base_for_regime(regime), warm_start=False, workers=1)
    from dataclasses import replace
    base_params = _base_for_regime(regime).to_dict()
    rows = []
    for i, rec in enumerate(recs):
        # evaluate_guarded historically omits parameter_values when the solve
        # raises. Reconstruct the full input vector from the immutable design row
        # so failed attempts remain auditable instead of becoming unresolved.
        params = dict(base_params)
        params.update({n: float(v) for n, v in zip(feature_names, X[i])})
        params.update(getattr(rec, "parameter_values", {}) or {})
        rec = replace(rec, parameter_values=params)
        rows.append(make_sample_record(
            solve_record=rec, feature_names=feature_names, regime=_regime_meta(regime),
            role=role, design_family=family, seed=seed, model_form=model_form,
            physics_digest=physics_digest, verified_low=low, verified_high=high,
            solver_options=solver_options, paired_design_id=""))
    return rows, summary.to_dict()


def _append_and_checkpoint(samples: list[dict], new_rows: list[dict], *,
                           dataset_path: Path, metadata: dict, progress: dict) -> list[dict]:
    samples.extend(new_rows)
    samples[:] = mark_duplicates(samples)
    save_dataset(dataset_path, samples, metadata=metadata, extra={"progress": progress})
    return samples


def _xy(rows: Sequence[dict], names: Sequence[str], target: str) -> tuple[np.ndarray, np.ndarray]:
    keep = [r for r in rows if r.get("outputs") is not None
            and r["outputs"].get(target) is not None
            and np.isfinite(float(r["outputs"][target]))]
    if not keep:
        return np.empty((0, len(names)), float), np.empty(0, float)
    return (np.asarray([[float(r["parameters"][n]) for n in names] for r in keep], float),
            np.asarray([float(r["outputs"][target]) for r in keep], float))


def _monitor_stage(train_rows: Sequence[dict], validation_rows: Sequence[dict],
                   names: Sequence[str], seed: int, stage: str) -> dict:
    xt, yt = _xy(train_rows, names, "pce_pct")
    xv, yv = _xy(validation_rows, names, "pce_pct")
    if len(xt) < 8 or len(xv) < 8:
        raise RuntimeError("insufficient valid training/validation points for stage measurement")
    fingerprint = dataset_fingerprint(train_rows)
    models, scores = compare_families(
        xt, yt, xv, yv, feature_names=names, target_name="pce_pct", unit="%",
        training_fingerprint=fingerprint, seed=seed,
        families=("ridge", "extra_trees", "gaussian_process_matern"))
    selected = select_family(scores)
    model = models[selected]
    pred, _ = model.predict(xv, return_std=False)
    residual = pred - yv
    return {"stage": stage, "selected_monitor_family": selected,
            "n_train": len(yt), "n_validation": len(yv),
            "validation_metrics": regression_metrics(yv, pred, train_y=yt),
            "family_scores": scores, "validation_X": xv, "validation_y": yv,
            "validation_residual": residual, "fit_model": model}


def _clean_stage_monitor(stage: dict) -> dict:
    return {k: v for k, v in stage.items()
            if k not in ("validation_X", "validation_y", "validation_residual", "fit_model")}


def _optimum_reference() -> dict:
    art = json.loads(SENSITIVITY_ARTIFACT.read_text())
    out = {}
    for regime, data in art["response_shape"].items():
        per_parameter = data["per_parameter"]
        out[regime] = {}
        for name in OPTIMUM_AXES:
            entry = per_parameter[name]
            x = np.asarray(entry["curve"]["x"], float)
            y = np.asarray(entry["curve"]["pce_pct"], float)
            idx = int(np.argmax(y))
            step = float(np.median(np.diff(x))) if len(x) > 1 else float("nan")
            out[regime][name] = {
                "source": "data/v19_sensitivity.json response_shape (21-point L4 1-D slice)",
                "x_at_max": float(entry["x_at_max"]), "pce_max_pct": float(entry["pce_max"]),
                "sampled_x_at_max": float(x[idx]),
                "grid_step": step, "grid_half_step_resolution_not_statistical_ci": step / 2.0,
                "n_curve_points": int(len(x)), "all_other_parameters": "registered defaults",
            }
    return out


def _profile_l5_tolerance(samples: Sequence[dict]) -> dict:
    by_key = {}
    for row in samples:
        if row.get("role") not in ("L5_CROSSCHECK", "INTERACTION_L5_CROSSCHECK"):
            continue
        if row.get("model_level") != "L5" or row.get("status") != VALID_FOR_SURROGATE:
            continue
        by_key[(row["operating_regime"]["name"], row.get("paired_design_id"))] = row
    l4_lookup = {}
    for row in samples:
        if (row.get("model_level") == "L4"
                and row.get("role") in ("CALIBRATION", "INTERACTION_CALIBRATION")
                and row.get("status") == VALID_FOR_SURROGATE):
            l4_lookup[(row["operating_regime"]["name"], row.get("design_point_fingerprint"))] = row
    deltas: dict[str, dict[str, list[float]]] = {}
    for (regime, pair_id), l5 in by_key.items():
        l4 = l4_lookup.get((regime, pair_id))
        if l4 is None or l4.get("outputs") is None or l5.get("outputs") is None:
            continue
        for target in OUTPUT_NAMES:
            a, b = l4["outputs"].get(target), l5["outputs"].get(target)
            if a is not None and b is not None:
                deltas.setdefault(regime, {}).setdefault(target, []).append(abs(float(b) - float(a)))
    out = {}
    for regime, target_values in deltas.items():
        out[regime] = {target: float(np.quantile(vals, 0.95, method="higher"))
                       for target, vals in target_values.items() if vals}
    return out


def _metrics_by_region(model, train_y: np.ndarray, X_test: np.ndarray,
                       y_test: np.ndarray, low: np.ndarray, high: np.ndarray,
                       X_train: np.ndarray) -> dict:
    pred, raw_std = model.predict(X_test, return_std=True)
    metrics = regression_metrics(y_test, pred, train_y=train_y)
    z = normalize(X_test, low, high)
    edge = np.any(np.minimum(z, 1.0 - z) <= 0.05, axis=1)
    metrics["boundary_region"] = ({"n": int(edge.sum()), **regression_metrics(
        y_test[edge], pred[edge], train_y=train_y)} if np.any(edge) else {"n": 0})
    d = nearest_distances(z, normalize(X_train, low, high))
    quartiles = np.quantile(d, [0.25, 0.50, 0.75])
    by_distance = []
    left = -np.inf
    for q, right in enumerate((*quartiles, np.inf), 1):
        mask = (d > left) & (d <= right)
        by_distance.append({"nearest_distance_quartile": q, "n": int(mask.sum()),
                            **(regression_metrics(y_test[mask], pred[mask], train_y=train_y)
                               if np.any(mask) else {})})
        left = right
    metrics["error_by_nearest_training_distance_quartile"] = by_distance
    metrics["raw_predictive_uncertainty_on_holdout"] = raw_interval_coverage(
        y_test, pred, raw_std)
    worst = np.argsort(-np.abs(pred - y_test))[:min(5, len(y_test))]
    metrics["worst_residual_rows"] = [{"test_row": int(i),
        "absolute_error": float(abs(pred[i] - y_test[i])),
        "nearest_training_distance": float(d[i]),
        "normalized_coordinates": z[i].round(6).tolist()} for i in worst]
    return metrics


def _grouped_cv(train_rows: Sequence[dict], feature_names: Sequence[str],
                family: str, target: str, seed: int, low: np.ndarray,
                high: np.ndarray) -> dict:
    valid = [r for r in train_rows if r.get("outputs") is not None
             and r["outputs"].get(target) is not None]
    if len(valid) < 12:
        return {"status": "BLOCKED_INSUFFICIENT_ROWS", "n": len(valid)}
    X = np.asarray([[r["parameters"][n] for n in feature_names] for r in valid], float)
    y = np.asarray([r["outputs"][target] for r in valid], float)
    groups = np.asarray([r["design_family"] for r in valid], str)
    n_splits = min(3, len(np.unique(groups)))
    if n_splits < 2:
        return {"status": "BLOCKED_INSUFFICIENT_INDEPENDENT_DESIGN_FAMILIES",
                "n_groups": int(len(np.unique(groups)))}
    fold_results = []
    for fold, (tr, te) in enumerate(grouped_kfold_indices(groups, n_splits), 1):
        fp = dataset_fingerprint([valid[i] for i in tr])
        model = fit_regressor(family, X[tr], y[tr], feature_names=feature_names,
                              target_name=target, unit=OUTPUT_UNITS[target],
                              training_fingerprint=fp, seed=seed + fold)
        pred, _ = model.predict(X[te], return_std=False)
        fold_results.append({"fold": fold,
                             "held_out_design_families": sorted(set(groups[te])),
                             "n_train": int(len(tr)), "n_test": int(len(te)),
                             **regression_metrics(y[te], pred, train_y=y[tr])})
    return {"status": "MEASURED_GROUPED_DESIGN_FAMILY_CV",
            "n_groups": int(len(np.unique(groups))), "n_splits": n_splits,
            "groups": sorted(set(groups)), "folds": fold_results,
            "pooled_rmse": float(np.sqrt(sum(
                r["rmse"] ** 2 * r["n_test"] for r in fold_results)
                / sum(r["n_test"] for r in fold_results)))}


def _metrics_on_selected_model(model, rows: Sequence[dict], names: Sequence[str],
                               train_y: np.ndarray, radius: float) -> dict:
    X, y = _xy(rows, names, model.target_name)
    if len(y) == 0:
        return {"n": 0, "status": "NO_VALID_ROWS"}
    pred, std = model.predict(X, return_std=True)
    out = {"metrics": regression_metrics(y, pred, train_y=train_y),
           "conformal_interval": interval_metrics(y, pred, radius=radius,
                                                   nominal_coverage=model.conformal_coverage),
           "raw_predictive_uncertainty": raw_interval_coverage(y, pred, std)}
    return out


def _single_model_set(*, train_rows_: Sequence[dict], validation_rows: Sequence[dict],
                      calibration_rows: Sequence[dict] | None,
                      feature_names: Sequence[str], target: str, seed: int,
                      training_fp: str, families: Sequence[str] = MODEL_FAMILIES) -> tuple:
    """Select on VALIDATION, then calibrate once on disjoint CALIBRATION rows."""
    xt, yt = _xy(train_rows_, feature_names, target)
    xv, yv = _xy(validation_rows, feature_names, target)
    if len(xt) < 8 or len(xv) < 8:
        raise RuntimeError(f"insufficient rows to fit {target}: train={len(xt)} validation={len(xv)}")
    fitted, scores = compare_families(
        xt, yt, xv, yv, feature_names=feature_names, target_name=target,
        unit=OUTPUT_UNITS[target], training_fingerprint=training_fp,
        seed=seed, families=families)
    ordered = sorted(scores, key=lambda f: (scores[f]["rmse"],
                                            MODEL_FAMILIES.index(f)))
    chosen = fitted[ordered[0]]
    calibration_rows = list(calibration_rows or [])
    xc, yc = _xy(calibration_rows, feature_names, target)
    calibration_status = "NOT_CALIBRATED"
    calibration_metrics = None
    q = None
    if len(yc) >= 8:
        cal_pred, _ = chosen.predict(xc, return_std=False)
        q = conformal_radius(yc, cal_pred, coverage=0.90)
        calibration_metrics = regression_metrics(yc, cal_pred, train_y=yt)
        calibration_status = "SPLIT_CONFORMAL_MARGINAL_CALIBRATED"
    chosen.conformal_radius = q
    chosen.validation_metrics = scores[ordered[0]]
    chosen.calibration_fingerprint = (dataset_fingerprint(calibration_rows)
                                     if calibration_rows else None)
    chosen.calibration_points = len(yc)
    alternatives = [fitted[name] for name in ordered[1:3]]
    return chosen, alternatives, scores, {
        "X": xv, "y": yv, "train_y": yt,
        "calibration_X": xc, "calibration_y": yc,
        "calibration_status": calibration_status,
        "calibration_metrics": calibration_metrics,
        "ordered_families": ordered,
        "validation_predictions": {
            f: fitted[f].predict(xv, return_std=True) for f in ordered}}


def _run_model_comparison(samples: list[dict], *, feature_names: Sequence[str],
                          low: np.ndarray, high: np.ndarray, seed: int) -> tuple[
                              SurrogateBundle, dict, dict]:
    selected_models: dict[str, dict[str, Any]] = {}
    alternatives: dict[str, dict[str, list[Any]]] = {}
    cards: dict[str, dict[str, dict]] = {}
    fingerprints, support_profiles, output_scores = {}, {}, {}
    train_cache, validation_cache, calibration_cache = {}, {}, {}
    for ri, regime_name in enumerate(REGIME_NAMES):
        tr = training_rows(samples, regime_name=regime_name, level="L4")
        va = [r for r in samples if r.get("role") == "VALIDATION"
              and r.get("status") == VALID_FOR_SURROGATE
              and r.get("model_level") == "L4"
              and r.get("operating_regime", {}).get("name") == regime_name]
        cal = [r for r in samples if r.get("role") == "CALIBRATION"
               and r.get("status") == VALID_FOR_SURROGATE
               and r.get("model_level") == "L4"
               and r.get("operating_regime", {}).get("name") == regime_name]
        if len(tr) < 16 or len(va) < 8:
            raise RuntimeError(f"contract-compliant rows insufficient for {regime_name}: {len(tr)} / {len(va)}")
        train_fp = dataset_fingerprint(tr)
        fingerprints[regime_name] = train_fp
        train_cache[regime_name], validation_cache[regime_name] = tr, va
        calibration_cache[regime_name] = cal
        selected_models[regime_name], alternatives[regime_name], cards[regime_name] = {}, {}, {}
        output_scores[regime_name] = {}
        calibration_uncertainty, calibration_disagreement = [], []
        for oi, target in enumerate(OUTPUT_NAMES):
            target_tr = [r for r in tr if r.get("outputs", {}).get(target) is not None]
            target_va = [r for r in va if r.get("outputs", {}).get(target) is not None]
            target_cal = [r for r in cal if r.get("outputs", {}).get(target) is not None]
            if len(target_tr) < 8 or len(target_va) < 8:
                output_scores[regime_name][target] = {"status": "MODEL_UNAVAILABLE",
                    "n_train": len(target_tr), "n_validation": len(target_va),
                    "n_calibration": len(target_cal)}
                continue
            target_fp = dataset_fingerprint(target_tr)
            model, other_models, scores, cv = _single_model_set(
                train_rows_=target_tr, validation_rows=target_va,
                calibration_rows=target_cal, feature_names=feature_names, target=target,
                seed=seed + 1000 * ri + oi * 31,
                training_fp=target_fp)
            selected_models[regime_name][target] = model
            alternatives[regime_name][target] = other_models
            xt, yt = _xy(target_tr, feature_names, target)
            xv, yv = _xy(target_va, feature_names, target)
            xc, yc = _xy(target_cal, feature_names, target)
            target_scale = model.target_scale
            cal_rmse = (cv["calibration_metrics"]["rmse"]
                        if cv["calibration_metrics"] is not None else None)
            if len(yc):
                _, cal_std = model.predict(xc, return_std=True)
                cal_uncertainty = (cal_std / max(target_scale, 1e-14)
                                   if cal_std is not None else np.empty(0, float))
                compare_models = [model, *other_models]
                pp = np.column_stack([m.predict(xc, return_std=False)[0]
                                      for m in compare_models])
                disagree = (np.std(pp, axis=1, ddof=1) if pp.shape[1] > 1
                            else np.zeros(len(yc)))
                disagree_ratio = disagree / max(cal_rmse or 0.0,
                                                target_scale * 1e-8, 1e-12)
            else:
                cal_uncertainty = disagree_ratio = np.empty(0, float)
            calibration_uncertainty.extend(cal_uncertainty.tolist())
            calibration_disagreement.extend(disagree_ratio.tolist())
            cards[regime_name][target] = {
                "target": target, "unit": OUTPUT_UNITS[target],
                "selected_family_by_independent_validation": model.family,
                "training_fingerprint": target_fp,
                "training_points": len(yt), "validation_points": len(yv),
                "calibration_points": len(yc),
                "calibration_data_fingerprint": model.calibration_fingerprint,
                "target_scale_train_sd_or_range": target_scale,
                "validation_rmse": float(scores[model.family]["rmse"]),
                "calibration_rmse": cal_rmse,
                "conformal_90_radius": (float(model.conformal_radius)
                                         if model.conformal_radius is not None else None),
                "conformal_calibration_n": len(yc),
                "conformal_calibration_status": cv["calibration_status"],
                "uncertainty_calibration": (
                    "split-conformal marginal calibration on a disjoint L4 CALIBRATION design; "
                    "not a physics posterior" if model.conformal_radius is not None
                    else "NOT_CALIBRATED: insufficient independent calibration rows"),
                "model_family_scores": scores,
                "top_families_for_disagreement": [model.family] + [m.family for m in other_models],
                "raw_uncertainty_note": model.raw_uncertainty_note,
                "all_rows_level": "L4",
                "not_experimental": True,
            }
            output_scores[regime_name][target] = cards[regime_name][target]
        # Geometric support points are kept separate from the withheld corner.
        support_in = [r for r in samples if r.get("role") == "SUPPORT_IN_CAL"
                      and r.get("status") in (VALID_FOR_SURROGATE, DUPLICATE_OR_DEPENDENT)
                      and r.get("operating_regime", {}).get("name") == regime_name]
        support_ood = [r for r in samples if r.get("role") == "OOD_CALIBRATION"
                       and r.get("operating_regime", {}).get("name") == regime_name]
        if len(support_in) < 4 or len(support_ood) < 4:
            raise RuntimeError(f"support calibration points missing for {regime_name}")
        xtr, _ = _xy(tr, feature_names, "pce_pct")
        xin = np.asarray([[r["parameters"][n] for n in feature_names] for r in support_in], float)
        xood = np.asarray([[r["parameters"][n] for n in feature_names] for r in support_ood], float)
        profile = fit_support_profile(
            feature_names=feature_names, low=low, high=high,
            training_X=xtr, in_domain_calibration_X=xin,
            withheld_region_calibration_X=xood,
            uncertainty_ratios=calibration_uncertainty,
            disagreement_ratios=calibration_disagreement,
            boundary_fraction_threshold=0.05, max_false_positive_rate=0.10)
        profile.calibration.update({
            "in_domain_support_data_fingerprint": dataset_fingerprint(support_in),
            "withheld_support_calibration_data_fingerprint": dataset_fingerprint(support_ood),
            "predictive_uncertainty_calibration_data_fingerprint": dataset_fingerprint(cal),
            "support_threshold_calibration_is_separate_from_prediction_calibration": True})
        support_profiles[regime_name] = profile
    regimes = {r.name: {"name": r.name, **r.settings} for r in REGIMES}
    defaults = ParamSet.defaults().to_dict()
    fixed_names = tuple(n for n in vector_names() if n not in feature_names
                        and n not in ("irradiance_suns", "temperature_k"))
    bundle = SurrogateBundle(
        feature_names=tuple(feature_names), regimes=regimes, low=np.asarray(low),
        high=np.asarray(high), registry_defaults=defaults,
        fixed_parameter_names=fixed_names, selected_models=selected_models,
        alternative_models=alternatives, support_profiles=support_profiles,
        model_cards=cards, training_fingerprints=fingerprints)
    return bundle, output_scores, {"train": train_cache, "validation": validation_cache,
                                  "calibration": calibration_cache}


def _serialize_profile(profile) -> dict:
    return {"feature_names": list(profile.feature_names),
            "nearest_distance_ood_threshold": (float(profile.nearest_distance_ood_threshold)
                if np.isfinite(profile.nearest_distance_ood_threshold) else None),
            "nearest_distance_uncertain_threshold": (
                float(profile.nearest_distance_uncertain_threshold)
                if np.isfinite(profile.nearest_distance_uncertain_threshold) else None),
            "uncertainty_ratio_threshold": (float(profile.uncertainty_ratio_threshold)
                if np.isfinite(profile.uncertainty_ratio_threshold) else None),
            "disagreement_ratio_threshold": (float(profile.disagreement_ratio_threshold)
                if np.isfinite(profile.disagreement_ratio_threshold) else None),
            "uncertainty_threshold_status": profile.calibration.get(
                "uncertainty_threshold_status", "NOT_CALIBRATED"),
            "disagreement_threshold_status": profile.calibration.get(
                "disagreement_threshold_status", "NOT_CALIBRATED"),
            "boundary_fraction_threshold": profile.boundary_fraction_threshold,
            "calibration": profile.calibration}


def _physics_digest_for_regime(code_digest: str, registry_digest: str,
                               regime, level: str, model_form: str) -> str:
    return physics_configuration_digest(
        model_code_digest=code_digest, registry_digest=registry_digest,
        level=level, model_form=model_form, regime=_regime_meta(regime),
        solver_options=options_for(level).to_dict())


def _all_candidate_points(samples: Sequence[dict], regime: str, role: str,
                          level: str = "L4") -> list[dict]:
    return [r for r in samples if r.get("role") == role and r.get("model_level") == level
            and r.get("operating_regime", {}).get("name") == regime]


def _row_matrix(rows: Sequence[dict], names: Sequence[str]) -> np.ndarray:
    return np.asarray([[float(r["parameters"][n]) for n in names] for r in rows], float)


def _assert_json_finite(value: Any, path: str = "$") -> None:
    """Fail with a precise location instead of hiding NaN/Inf in report JSON."""
    if isinstance(value, np.ndarray):
        for i, item in enumerate(value):
            _assert_json_finite(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_json_finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_json_finite(item, f"{path}[{i}]")
    elif isinstance(value, (float, np.floating)) and not np.isfinite(value):
        raise ValueError(f"non-finite result value at {path}: {value!r}; report NOT_CALIBRATED/undefined explicitly")


def _write_json(path: Path, data: dict) -> dict:
    from ..repro.digest import digest_block
    _assert_json_finite(data)
    body = dict(data)
    body["physics_digest"] = digest_block(body)
    raw = json.dumps(body, indent=1, sort_keys=True, allow_nan=False,
                     default=str).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
            "sha256": _sha_bytes(raw), "physics_digest": body["physics_digest"]["sha256"]}


def run_campaign(*, seed: int = 20261009,
                 dataset_path: Path = DEFAULT_DATASET_PATH,
                 results_path: Path = DEFAULT_RESULTS_PATH,
                 model_path: Path = DEFAULT_MODEL_PATH,
                 initial_n: int = 128, stage2_n: int = 256,
                 adaptive_n: int = 32, validation_n: int = 64,
                 calibration_n: int = 64, final_n: int = 96,
                 interaction_n: int = 768,
                 run_l5: bool = True) -> dict:
    """Execute staged L4 sampling, independent validation, model comparison and checks.

    Predeclared stopping policy for the global PCE monitor: target 0.25 percentage
    points RMSE on the independent validation design; if missed, add an adaptive
    batch and then a global LHS extension.  A second adaptive batch is permitted
    only while its previous batch improved RMSE by at least 5%; it is capped at 32
    points per regime.  Family selection/adaptive acquisition use VALIDATION rows;
    conformal calibration uses disjoint CALIBRATION rows; FINAL_HOLDOUT is never
    used to choose models, calibrate uncertainty or acquire samples.
    """
    t_campaign = time.perf_counter()
    dataset_path, results_path, model_path = map(Path, (dataset_path, results_path, model_path))
    if not dataset_path.is_absolute():
        dataset_path = ROOT / dataset_path
    if not results_path.is_absolute():
        results_path = ROOT / results_path
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    audit = _audit_existing_data()
    if not audit["sensitivity_physics_digest_verified"]:
        raise RuntimeError("V1.9-D artifact physics digest failed; refusing to build on unverified data")
    artifact = json.loads(SENSITIVITY_ARTIFACT.read_text())
    feature_names = tuple(artifact["design_parameters"])
    if feature_names != tuple(DESIGN_PARAMETERS):
        raise RuntimeError("V1.9-D feature contract differs from current sensitivity registry")
    low_map = {k: float(v) for k, v in artifact["shared_box"]["low"].items()}
    high_map = {k: float(v) for k, v in artifact["shared_box"]["high"].items()}
    low = np.asarray([low_map[n] for n in feature_names], float)
    high = np.asarray([high_map[n] for n in feature_names], float)
    reg_digest = _registry_digest()
    code_digest, code_files = _physics_code_digest()
    metadata = _environment_metadata(seed, code_digest, code_files)
    metadata.update({"campaign_id": "v19e-surrogate-20261009",
                     "data_contract_version": "apmt-surrogate-data/1.0",
                     "feature_names": list(feature_names),
                     "feature_units": {n: spec(n).unit for n in feature_names},
                     "shared_verified_box_low": low_map,
                     "shared_verified_box_high": high_map,
                     "sampling_policy": "independent randomized Latin hypercube; corner [0.90,1]^2 reserved for support/OOD testing",
                     "selection_validation_n_per_regime": int(validation_n),
                     "prediction_calibration_n_per_regime": int(calibration_n),
                     "final_holdout_n_per_regime": int(final_n),
                     "calibration_seeds": {r.name: int(seed + 150 + 1000 * i)
                                           for i, r in enumerate(REGIMES)},
                     "model_level_primary": "L4", "model_level_crosscheck": "L5",
                     "model_form": "IQE-M1",
                     "solver_options": {lv: options_for(lv).to_dict() for lv in ("L4", "L5")},
                     "training_data_is_experimental": False,
                     "excluded_historical_artifacts_sha256": {
                         "data/v19_sensitivity.json": audit["sensitivity_artifact_sha256"]}})
    samples: list[dict] = []
    progress: dict = {"phase": "started", "groups_completed": [], "seed": int(seed)}
    solver_benchmarks: list[dict] = []

    # Independently randomized selection, calibration and final designs are fixed
    # before adaptive sampling.  CALIBRATION and FINAL_HOLDOUT are never queried
    # by acquisition or used to select families; no design reuses another's rows.
    validation_mats, calibration_mats, final_mats = {}, {}, {}
    for ri, regime in enumerate(REGIMES):
        validation_mats[regime.name] = _lhs_box(validation_n, low, high,
            seed + 100 + 1000 * ri, exclude_withheld_corner=True)
        calibration_mats[regime.name] = _lhs_box(calibration_n, low, high,
            seed + 150 + 1000 * ri, exclude_withheld_corner=True,
            existing=validation_mats[regime.name])
        final_mats[regime.name] = _lhs_box(final_n, low, high,
            seed + 200 + 1000 * ri, exclude_withheld_corner=True,
            existing=np.vstack([validation_mats[regime.name], calibration_mats[regime.name]]))

    stage_history: dict[str, list[dict]] = {r.name: [] for r in REGIMES}
    train_family_mats: dict[str, list[np.ndarray]] = {r.name: [] for r in REGIMES}
    # Stage 1: independently seeded initial LHS and fresh L4 validation/final data.
    for ri, regime in enumerate(REGIMES):
        phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        X = _lhs_box(initial_n, low, high, seed + 10 + 1000 * ri,
                     exclude_withheld_corner=True)
        rows, summary = _generate_group(X=X, feature_names=feature_names, regime=regime,
            level="L4", role="TRAIN", family=f"global-lhs-stage1-{regime.name}",
            seed=seed + 10 + ri, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={**progress, "phase": "stage1-train", "regime": regime.name})
        solver_benchmarks.append({"role": "TRAIN_STAGE1", "regime": regime.name, **summary})
        train_family_mats[regime.name].append(X)
        rows, summary = _generate_group(X=validation_mats[regime.name], feature_names=feature_names,
            regime=regime, level="L4", role="VALIDATION", family=f"independent-validation-{regime.name}",
            seed=seed + 100 + ri, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={**progress, "phase": "validation", "regime": regime.name})
        solver_benchmarks.append({"role": "VALIDATION", "regime": regime.name, **summary})
        rows, summary = _generate_group(X=final_mats[regime.name], feature_names=feature_names,
            regime=regime, level="L4", role="FINAL_HOLDOUT", family=f"untouched-final-lhs-{regime.name}",
            seed=seed + 200 + ri, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={**progress, "phase": "final-holdout", "regime": regime.name})
        solver_benchmarks.append({"role": "FINAL_HOLDOUT", "regime": regime.name, **summary})

    # Stage-by-stage adaptive selection is driven only by validation residuals.
    stage_thresholds = {"pce_rmse_target_pp": ACCURACY_TARGET_PCE_RMSE_PP,
                        "marginal_improvement_stop_fraction": MARGINAL_IMPROVEMENT_FRACTION,
                        "max_adaptive_batches": 2,
                        "minimum_surrogate_speedup_vs_median_l4": MIN_SURROGATE_SPEEDUP_VS_L4}
    adaptive_counts: dict[str, int] = {}
    for ri, regime in enumerate(REGIMES):
        tr = training_rows(samples, regime_name=regime.name, level="L4", allowed_roles=("TRAIN",))
        va = [r for r in samples if r.get("role") == "VALIDATION"
              and r.get("status") == VALID_FOR_SURROGATE
              and r.get("operating_regime", {}).get("name") == regime.name]
        monitor = _monitor_stage(tr, va, feature_names, seed + 300 + ri, "after_stage1")
        stage_history[regime.name].append(_clean_stage_monitor(monitor))
        previous_rmse = monitor["validation_metrics"]["rmse"]
        if previous_rmse > ACCURACY_TARGET_PCE_RMSE_PP:
            Xtr = np.asarray([[r["parameters"][n] for n in feature_names] for r in tr], float)
            Xval, residual = monitor["validation_X"], monitor["validation_residual"]
            regions = localize_high_errors(Xval, residual, low=low, high=high, n_regions=5)
            candidates = propose_near_errors(Xval, residual, low=low, high=high,
                existing_X=np.vstack([Xtr, Xval]), n_samples=adaptive_n,
                seed=seed + 310 + ri, perturbation_fraction=0.06)
            bad = _is_withheld_corner(candidates, low, high)
            if np.any(bad):
                replacement = _lhs_box(int(bad.sum()), low, high, seed + 311 + ri,
                                       exclude_withheld_corner=True,
                                       existing=np.vstack([Xtr, Xval, candidates[~bad]]))
                candidates[bad] = replacement
            phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
            rows, summary = _generate_group(X=candidates, feature_names=feature_names,
                regime=regime, level="L4", role="ADAPTIVE_TRAIN",
                family=f"adaptive-high-error-{regime.name}-1", seed=seed + 310 + ri,
                model_form="IQE-M1", physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                metadata=metadata, progress={"phase": "adaptive-1", "regime": regime.name})
            solver_benchmarks.append({"role": "ADAPTIVE_TRAIN", "regime": regime.name, **summary})
            tr = training_rows(samples, regime_name=regime.name, level="L4")
            monitor = _monitor_stage(tr, va, feature_names, seed + 320 + ri, "after_adaptive_batch_1")
            monitor["sampled_error_regions"] = regions
            monitor["adaptive_batch_n"] = len(rows)
            stage_history[regime.name].append(_clean_stage_monitor(monitor))
            adaptive_counts[regime.name] = len(rows)
            current_rmse = monitor["validation_metrics"]["rmse"]
            improvement = (previous_rmse - current_rmse) / max(previous_rmse, 1e-14)
            previous_rmse = current_rmse
        else:
            improvement = 0.0
            adaptive_counts[regime.name] = 0

        # Stage 2: add an independently seeded global LHS batch unless the
        # predeclared absolute-accuracy target was reached already.
        if previous_rmse > ACCURACY_TARGET_PCE_RMSE_PP:
            Xexisting = np.vstack(train_family_mats[regime.name])
            existing_train = training_rows(samples, regime_name=regime.name, level="L4")
            Xexisting = np.vstack([Xexisting, np.asarray([
                [r["parameters"][n] for n in feature_names] for r in existing_train
                if r.get("role") == "ADAPTIVE_TRAIN"], float)]) if any(
                    r.get("role") == "ADAPTIVE_TRAIN" and r.get("operating_regime", {}).get("name") == regime.name
                    for r in existing_train) else Xexisting
            X2 = _lhs_box(stage2_n, low, high, seed + 400 + 1000 * ri,
                          exclude_withheld_corner=True, existing=Xexisting)
            phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
            rows, summary = _generate_group(X=X2, feature_names=feature_names, regime=regime,
                level="L4", role="TRAIN", family=f"global-lhs-stage2-{regime.name}",
                seed=seed + 400 + ri, model_form="IQE-M1", physics_digest=phys,
                low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
            samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                metadata=metadata, progress={"phase": "stage2-global-lhs", "regime": regime.name})
            solver_benchmarks.append({"role": "TRAIN_STAGE2", "regime": regime.name, **summary})
            train_family_mats[regime.name].append(X2)
            tr = training_rows(samples, regime_name=regime.name, level="L4")
            monitor2 = _monitor_stage(tr, va, feature_names, seed + 410 + ri, "after_stage2_global_lhs")
            monitor2["prior_validation_rmse"] = previous_rmse
            monitor2["relative_improvement_from_prior_stage"] = float(
                (previous_rmse - monitor2["validation_metrics"]["rmse"])
                / max(previous_rmse, 1e-14))
            stage_history[regime.name].append(_clean_stage_monitor(monitor2))
            final_rmse = monitor2["validation_metrics"]["rmse"]
            marginal = monitor2["relative_improvement_from_prior_stage"]
            # One final adaptive batch only if the model remains above target and
            # the previous independent batch gave a material validation gain.
            if final_rmse > ACCURACY_TARGET_PCE_RMSE_PP and marginal >= MARGINAL_IMPROVEMENT_FRACTION:
                tr = training_rows(samples, regime_name=regime.name, level="L4")
                Xtr = np.asarray([[r["parameters"][n] for n in feature_names] for r in tr], float)
                candidates = propose_near_errors(monitor2["validation_X"],
                    monitor2["validation_residual"], low=low, high=high,
                    existing_X=np.vstack([Xtr, monitor2["validation_X"]]),
                    n_samples=adaptive_n, seed=seed + 420 + ri,
                    perturbation_fraction=0.05)
                bad = _is_withheld_corner(candidates, low, high)
                if np.any(bad):
                    replacement = _lhs_box(int(bad.sum()), low, high, seed + 421 + ri,
                                           exclude_withheld_corner=True,
                                           existing=np.vstack([Xtr, candidates[~bad]]))
                    candidates[bad] = replacement
                rows, summary = _generate_group(X=candidates, feature_names=feature_names,
                    regime=regime, level="L4", role="ADAPTIVE_TRAIN",
                    family=f"adaptive-high-error-{regime.name}-2", seed=seed + 420 + ri,
                    model_form="IQE-M1", physics_digest=phys, low=low_map, high=high_map,
                    solver_options=options_for("L4").to_dict())
                samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                    metadata=metadata, progress={"phase": "adaptive-2", "regime": regime.name})
                solver_benchmarks.append({"role": "ADAPTIVE_TRAIN", "regime": regime.name, **summary})
                adaptive_counts[regime.name] += len(rows)
                tr = training_rows(samples, regime_name=regime.name, level="L4")
                monitor3 = _monitor_stage(tr, va, feature_names, seed + 430 + ri,
                                          "after_adaptive_batch_2")
                monitor3["prior_validation_rmse"] = final_rmse
                monitor3["relative_improvement_from_prior_stage"] = float(
                    (final_rmse - monitor3["validation_metrics"]["rmse"])
                    / max(final_rmse, 1e-14))
                stage_history[regime.name].append(_clean_stage_monitor(monitor3))

    # Prediction-calibration points are physically generated from a third
    # independent design.  They are withheld from family selection and adaptive
    # acquisition; only the selected model's residuals are used for conformal q.
    for ri, regime in enumerate(REGIMES):
        phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        rows, summary = _generate_group(X=calibration_mats[regime.name],
            feature_names=feature_names, regime=regime, level="L4", role="CALIBRATION",
            family=f"prediction-calibration-{regime.name}", seed=seed + 150 + ri,
            model_form="IQE-M1", physics_digest=phys, low=low_map, high=high_map,
            solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={"phase": "prediction-calibration", "regime": regime.name})
        solver_benchmarks.append({"role": "CALIBRATION", "regime": regime.name, **summary})

    # Separate support calibration: in-domain L4 rows and a held-out verified-box
    # corner. Independent withheld-corner draws calibrate and test OOD thresholds.
    for ri, regime in enumerate(REGIMES):
        phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        X_in = _lhs_box(48, low, high, seed + 500 + ri * 1000,
                        exclude_withheld_corner=True)
        rows, summary = _generate_group(X=X_in, feature_names=feature_names, regime=regime,
            level="L4", role="SUPPORT_IN_CAL", family=f"support-in-domain-cal-{regime.name}",
            seed=seed + 500 + ri, model_form="IQE-M1", physics_digest=phys,
            low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={"phase": "support-in-calibration", "regime": regime.name})
        solver_benchmarks.append({"role": "SUPPORT_IN_CAL", "regime": regime.name, **summary})
        # Independent randomized designs in the same reserved corner avoid a
        # geometric split (e.g. one half of a diagonal) that would not be
        # exchangeable between OOD-threshold calibration and final detection.
        for half, role in enumerate(("OOD_CALIBRATION", "OOD_FINAL")):
            sub = _withheld_corner_design(24, low, high, seed + 510 + ri * 1000 + half)
            rows, summary = _generate_group(X=sub, feature_names=feature_names, regime=regime,
                level="L4", role=role, family=f"withheld-corner-{role.lower()}-{regime.name}",
                seed=seed + 510 + ri + half, model_form="IQE-M1", physics_digest=phys,
                low=low_map, high=high_map, solver_options=options_for("L4").to_dict())
            samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                metadata=metadata, progress={"phase": role.lower(), "regime": regime.name})
            solver_benchmarks.append({"role": role, "regime": regime.name, **summary})

    # Boundary validation points stay inside the D shared box and are never fed
    # to the training regressors.
    boundary_mats = {}
    for ri, regime in enumerate(REGIMES):
        boundary_mats[regime.name] = _boundary_design(48, low, high, seed + 600 + ri * 1000)
        phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        rows, summary = _generate_group(X=boundary_mats[regime.name], feature_names=feature_names,
            regime=regime, level="L4", role="BOUNDARY_VALIDATION",
            family=f"boundary-validation-{regime.name}", seed=seed + 600 + ri,
            model_form="IQE-M1", physics_digest=phys, low=low_map, high=high_map,
            solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={"phase": "boundary-validation", "regime": regime.name})
        solver_benchmarks.append({"role": "BOUNDARY_VALIDATION", "regime": regime.name, **summary})

    # Fit the 14-D global family comparison on unique VALID L4 rows only.
    bundle, model_scores, cache = _run_model_comparison(
        samples, feature_names=feature_names, low=low, high=high, seed=seed + 700)

    # Leakage-resistant grouped CV by independent training design family (PCE),
    # plus independent-validation model selection and untouched global final test.
    grouped_cv = {}
    holdout_results = {}
    train_rows_by_regime = cache["train"]
    for ri, regime in enumerate(REGIMES):
        regime_name = regime.name
        pce_card = bundle.model_cards[regime_name]["pce_pct"]
        pce_family = pce_card["selected_family_by_independent_validation"]
        grouped_cv[regime_name] = _grouped_cv(
            train_rows_by_regime[regime_name], feature_names, pce_family, "pce_pct",
            seed + 800 + ri, low, high)
        final_rows = [r for r in samples if r.get("role") == "FINAL_HOLDOUT"
                      and r.get("model_level") == "L4"
                      and r.get("status") == VALID_FOR_SURROGATE
                      and r.get("operating_regime", {}).get("name") == regime_name]
        holdout_results[regime_name] = {}
        for target, model in bundle.selected_models[regime_name].items():
            train_y = _xy(train_rows_by_regime[regime_name], feature_names, target)[1]
            holdout_results[regime_name][target] = _metrics_by_region(
                model, train_y, _row_matrix(final_rows, feature_names),
                np.asarray([r["outputs"][target] for r in final_rows], float),
                low, high, _row_matrix(train_rows_by_regime[regime_name], feature_names))
            holdout_results[regime_name][target]["conformal_interval_final_holdout"] = interval_metrics(
                np.asarray([r["outputs"][target] for r in final_rows], float),
                model.predict(_row_matrix(final_rows, feature_names), return_std=False)[0],
                radius=float(model.conformal_radius), nominal_coverage=0.90)
        support_in = _all_candidate_points(samples, regime_name, "FINAL_HOLDOUT")
        support_ood = _all_candidate_points(samples, regime_name, "OOD_FINAL")
        support_in_x = _row_matrix([r for r in support_in if r.get("status") == VALID_FOR_SURROGATE], feature_names)
        support_ood_x = _row_matrix(support_ood, feature_names)
        holdout_results[regime_name]["support_detection"] = detection_metrics(
            bundle.support_profiles[regime_name], support_in_x, support_ood_x)
        holdout_results[regime_name]["support_profile"] = _serialize_profile(
            bundle.support_profiles[regime_name])

    # V1.9-D interior optima: a separately scoped three-axis response-slice
    # model, trained only from newly generated L4 points, then checked on fresh
    # full-range 1-D L4 curves.  Historical reported maxima are never labels.
    optimum_reference = _optimum_reference()
    optimum_metrics = {}
    specialized_models: dict[str, Any] = {}
    for ri, regime in enumerate(REGIMES):
        names3 = OPTIMUM_AXES
        low3 = np.asarray([low_map[n] for n in names3], float)
        high3 = np.asarray([high_map[n] for n in names3], float)
        Xtr3 = _lhs_box(128, low3, high3, seed + 900 + 1000 * ri,
                        exclude_withheld_corner=True)
        Xva3 = _lhs_box(64, low3, high3, seed + 910 + 1000 * ri,
                        exclude_withheld_corner=True, existing=Xtr3)
        Xcal3 = _lhs_box(calibration_n, low3, high3, seed + 915 + 1000 * ri,
                         exclude_withheld_corner=True, existing=np.vstack([Xtr3, Xva3]))
        phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L4", "IQE-M1")
        for Xsub, role, fam, sd in (
                (Xtr3, "OPTIMUM_TRAIN", f"optimum-slice-train-{regime.name}", seed + 900 + ri),
                (Xva3, "OPTIMUM_VALIDATION", f"optimum-slice-val-{regime.name}", seed + 910 + ri),
                (Xcal3, "OPTIMUM_CALIBRATION", f"optimum-slice-cal-{regime.name}", seed + 915 + ri)):
            Xfull = _full_design_from_subspace(Xsub, feature_names, regime.settings)
            rows, summary = _generate_group(X=Xfull, feature_names=feature_names, regime=regime,
                level="L4", role=role, family=fam, seed=sd, model_form="IQE-M1",
                physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                metadata=metadata, progress={"phase": role.lower(), "regime": regime.name})
            solver_benchmarks.append({"role": role, "regime": regime.name, **summary})
        tr3 = [r for r in samples if r.get("role") == "OPTIMUM_TRAIN"
               and r.get("status") == VALID_FOR_SURROGATE
               and r.get("operating_regime", {}).get("name") == regime.name]
        va3 = [r for r in samples if r.get("role") == "OPTIMUM_VALIDATION"
               and r.get("status") == VALID_FOR_SURROGATE
               and r.get("operating_regime", {}).get("name") == regime.name]
        cal3 = [r for r in samples if r.get("role") == "OPTIMUM_CALIBRATION"
                and r.get("status") == VALID_FOR_SURROGATE
                and r.get("operating_regime", {}).get("name") == regime.name]
        fp3 = dataset_fingerprint(tr3)
        optimum_model, optimum_alts, opt_scores, opt_calibration = _single_model_set(
            train_rows_=tr3, validation_rows=va3, calibration_rows=cal3,
            feature_names=names3, target="pce_pct", seed=seed + 920 + ri,
            training_fp=fp3)
        optimum_model_key = f"optima_slice_pce:{regime.name}"
        specialized_models[optimum_model_key] = {"model": optimum_model,
            "alternatives": optimum_alts, "feature_names": names3,
            "training_fingerprint": fp3,
            "validation_scores": opt_scores,
            "calibration_status": opt_calibration["calibration_status"],
            "calibration_n": len(opt_calibration["calibration_y"]),
            "calibration_rmse": opt_calibration["calibration_metrics"]["rmse"]
                if opt_calibration["calibration_metrics"] is not None else None}
        # Three new, independent, off-grid L4 response curves (41 points each).
        shape_rows_by_name = {}
        background = ParamSet.defaults().with_mapping(regime.settings).to_vector(feature_names)
        axis_indices = {n: feature_names.index(n) for n in OPTIMUM_AXES}
        for axis_i, name in enumerate(OPTIMUM_AXES):
            grid = np.linspace(low_map[name], high_map[name], 41)
            Xcurve = np.tile(background, (len(grid), 1))
            Xcurve[:, axis_indices[name]] = grid
            rows, summary = _generate_group(X=Xcurve, feature_names=feature_names, regime=regime,
                level="L4", role="OPTIMUM_FINAL_VERIFICATION",
                family=f"optimum-curve-verification-{regime.name}-{name}",
                seed=seed + 930 + ri * 10 + axis_i, model_form="IQE-M1",
                physics_digest=phys, low=low_map, high=high_map,
                solver_options=options_for("L4").to_dict())
            samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                metadata=metadata, progress={"phase": "optimum-verification", "regime": regime.name,
                                            "parameter": name})
            solver_benchmarks.append({"role": "OPTIMUM_FINAL_VERIFICATION",
                                      "regime": regime.name, "parameter": name, **summary})
            shape_rows_by_name[name] = rows
        optimum_metrics[regime.name] = {"scope": "three-input L4 slice surrogate at other registry defaults; not the 14-D general model",
            "training_points": len(tr3), "validation_points": len(va3),
            "calibration_points": len(cal3),
            "calibration_status": opt_calibration["calibration_status"],
            "selected_family": optimum_model.family,
            "training_data_fingerprint": fp3,
            "validation_family_scores": opt_scores,
            "reported_v19d_grid_optima": optimum_reference[regime.name],
            "verified_curves": {}}
        for name in OPTIMUM_AXES:
            rows = [r for r in shape_rows_by_name[name]
                    if r.get("status") == VALID_FOR_SURROGATE and r.get("outputs")]
            Xcurve = np.asarray([[r["parameters"][n] for n in names3] for r in rows], float)
            # The 3-D model receives its actual three varying features plus the
            # two fixed defaults for the remaining optimum axes.
            y_true = np.asarray([r["outputs"]["pce_pct"] for r in rows], float)
            x_coord = np.asarray([r["parameters"][name] for r in rows], float)
            Xslice = Xcurve.copy()
            pred, std = optimum_model.predict(Xslice, return_std=True)
            idx_true, idx_pred = int(np.argmax(y_true)), int(np.argmax(pred))
            local_order = np.argsort(-pred)[:3]
            optimum_metrics[regime.name]["verified_curves"][name] = {
                "n_l4_verification_points": int(len(rows)),
                "curve_l4_physics_max_x": float(x_coord[idx_true]),
                "curve_surrogate_max_x": float(x_coord[idx_pred]),
                "reported_v19d_max_x": optimum_reference[regime.name][name]["x_at_max"],
                "surrogate_minus_l4_at_l4_argmax": float(pred[idx_true] - y_true[idx_true]),
                "l4_minus_surrogate_rmse": float(np.sqrt(np.mean((pred - y_true) ** 2))),
                "max_absolute_error": float(np.max(np.abs(pred - y_true))),
                "argmax_coordinate_error": float(abs(x_coord[idx_pred] - x_coord[idx_true])),
                "l4_argmax_within_reported_grid_half_step": bool(
                    abs(x_coord[idx_true] - optimum_reference[regime.name][name]["x_at_max"])
                    <= optimum_reference[regime.name][name]["grid_half_step_resolution_not_statistical_ci"]
                    + (high_map[name] - low_map[name]) / 40.0 / 2.0),
                "top_predicted_points": [{"x": float(x_coord[j]),
                                           "predicted_pce_pct": float(pred[j]),
                                           "raw_gp_or_tree_std": (float(std[j]) if std is not None else None)}
                                          for j in local_order],
                "curve_prediction_is_not_a_verified_design": True,
            }

    # Dedicated nominal four-axis interaction surrogate.  It uses a separately
    # scoped slice LHS design and a fresh N=768 Saltelli L4 design (not the noisy
    # small-N general pair table from V1.9-D).
    nominal = next(r for r in REGIMES if r.name == "nominal_1sun_25c")
    lo4 = np.asarray([low_map[n] for n in INTERACTION_AXES], float)
    hi4 = np.asarray([high_map[n] for n in INTERACTION_AXES], float)
    interaction_calibration_n = max(128, 2 * int(calibration_n))
    Xi_train = _lhs_box(512, lo4, hi4, seed + 1100, exclude_withheld_corner=True)
    Xi_val = _lhs_box(128, lo4, hi4, seed + 1101, exclude_withheld_corner=True,
                      existing=Xi_train)
    Xi_cal = _lhs_box(interaction_calibration_n, lo4, hi4, seed + 1102,
                      exclude_withheld_corner=True,
                      existing=np.vstack([Xi_train, Xi_val]))
    phys_nom = _physics_digest_for_regime(code_digest, reg_digest, nominal, "L4", "IQE-M1")
    for Xi, role, fam, sd in (
            (Xi_train, "INTERACTION_TRAIN", "interaction-slice-train-nominal", seed + 1100),
            (Xi_val, "INTERACTION_VALIDATION", "interaction-slice-val-nominal", seed + 1101),
            (Xi_cal, "INTERACTION_CALIBRATION", "interaction-slice-cal-nominal", seed + 1102)):
        Xfull = np.tile(ParamSet.defaults().with_mapping(nominal.settings).to_vector(feature_names),
                        (len(Xi), 1))
        for j, name in enumerate(INTERACTION_AXES):
            Xfull[:, feature_names.index(name)] = Xi[:, j]
        rows, summary = _generate_group(X=Xfull, feature_names=feature_names, regime=nominal,
            level="L4", role=role, family=fam, seed=sd, model_form="IQE-M1",
            physics_digest=phys_nom, low=low_map, high=high_map,
            solver_options=options_for("L4").to_dict())
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={"phase": role.lower(), "regime": nominal.name})
        solver_benchmarks.append({"role": role, "regime": nominal.name, **summary})
    interaction_train_rows = [r for r in samples if r.get("role") == "INTERACTION_TRAIN"
                              and r.get("status") == VALID_FOR_SURROGATE]
    interaction_val_rows = [r for r in samples if r.get("role") == "INTERACTION_VALIDATION"
                            and r.get("status") == VALID_FOR_SURROGATE]
    interaction_cal_rows = [r for r in samples if r.get("role") == "INTERACTION_CALIBRATION"
                             and r.get("status") == VALID_FOR_SURROGATE]
    Xi_tr, yi_tr = _xy(interaction_train_rows, INTERACTION_AXES, "pce_pct")
    Xi_va, yi_va = _xy(interaction_val_rows, INTERACTION_AXES, "pce_pct")
    Xi_cal_actual, yi_cal = _xy(interaction_cal_rows, INTERACTION_AXES, "pce_pct")
    interaction_fp = dataset_fingerprint(interaction_train_rows)
    interaction_fits, interaction_scores = compare_families(
        Xi_tr, yi_tr, Xi_va, yi_va, feature_names=INTERACTION_AXES,
        target_name="pce_pct", unit="%", training_fingerprint=interaction_fp,
        seed=seed + 1110)
    interaction_selected = select_family(interaction_scores)
    interaction_model = interaction_fits[interaction_selected]
    interaction_calibration_status = "NOT_CALIBRATED"
    interaction_calibration_metrics = None
    interaction_q = None
    if len(yi_cal) >= 8:
        interaction_cal_pred, _ = interaction_model.predict(Xi_cal_actual, return_std=False)
        interaction_q = conformal_radius(yi_cal, interaction_cal_pred, coverage=0.90)
        interaction_calibration_metrics = regression_metrics(yi_cal, interaction_cal_pred,
                                                               train_y=yi_tr)
        interaction_calibration_status = "SPLIT_CONFORMAL_MARGINAL_CALIBRATED"
    interaction_model.conformal_radius = interaction_q
    interaction_model.calibration_fingerprint = (dataset_fingerprint(interaction_cal_rows)
                                                 if interaction_cal_rows else None)
    interaction_model.calibration_points = len(yi_cal)
    interaction_alternatives = [interaction_fits[k] for k in sorted(
        interaction_scores, key=lambda f: (interaction_scores[f]["rmse"], MODEL_FAMILIES.index(f)))
        if k != interaction_selected][:2]
    specialized_models["interaction_slice_pce:nominal_1sun_25c"] = {
        "model": interaction_model, "alternatives": interaction_alternatives,
        "feature_names": INTERACTION_AXES, "training_fingerprint": interaction_fp,
        "validation_scores": interaction_scores,
        "calibration_status": interaction_calibration_status,
        "calibration_n": len(yi_cal), "conformal_90_radius": interaction_q}
    # Slice-level statistical support profile, calibrated using independent in-box
    # validation and the reserved high-Eg/high-thickness corner projected to 4-D.
    support_in_rows = [r for r in samples if r.get("role") == "SUPPORT_IN_CAL"
                       and r.get("operating_regime", {}).get("name") == nominal.name]
    support_ood_rows = [r for r in samples if r.get("role") == "OOD_CALIBRATION"
                        and r.get("operating_regime", {}).get("name") == nominal.name]
    X_in4 = np.asarray([[r["parameters"][n] for n in INTERACTION_AXES]
                        for r in support_in_rows], float)
    X_ood4 = np.asarray([[r["parameters"][n] for n in INTERACTION_AXES]
                         for r in support_ood_rows], float)
    p_in4 = np.asarray([[r["parameters"][n] for n in INTERACTION_AXES]
                        for r in interaction_train_rows], float)
    interaction_disagreement = []
    interaction_uncertainty = []
    for x in Xi_cal_actual:
        mu, sd = interaction_model.predict(x, return_std=True)
        vals = [float(mu[0])]
        for alt in interaction_alternatives:
            vals.append(float(alt.predict(x, return_std=False)[0][0]))
        disagreement_scale = (interaction_calibration_metrics["rmse"]
                              if interaction_calibration_metrics is not None
                              else interaction_scores[interaction_selected]["rmse"])
        interaction_disagreement.append(float(np.std(vals, ddof=1)) / max(
            disagreement_scale, 1e-12))
        if sd is not None:
            interaction_uncertainty.append(float(sd[0])
                                           / max(interaction_model.target_scale, 1e-12))
    interaction_profile = fit_support_profile(
        feature_names=INTERACTION_AXES, low=lo4, high=hi4, training_X=p_in4,
        in_domain_calibration_X=X_in4, withheld_region_calibration_X=X_ood4,
        uncertainty_ratios=interaction_uncertainty,
        disagreement_ratios=interaction_disagreement,
        max_false_positive_rate=0.10)
    interaction_profile.calibration.update({
        "in_domain_support_data_fingerprint": dataset_fingerprint(support_in_rows),
        "withheld_support_calibration_data_fingerprint": dataset_fingerprint(support_ood_rows),
        "predictive_uncertainty_calibration_data_fingerprint": interaction_model.calibration_fingerprint,
        "support_threshold_calibration_is_separate_from_prediction_calibration": True})

    design = saltelli_design(INTERACTION_AXES, n_base=interaction_n, low=lo4,
                             high=hi4, seed=seed + 1200, second_order=True)
    Xint = design.matrix()
    rows, int_summary = _generate_group(X=Xint, feature_names=INTERACTION_AXES,
        regime=nominal, level="L4", role="INTERACTION_FINAL",
        family="fresh-saltelli-n768-nominal", seed=seed + 1200,
        model_form="IQE-M1", physics_digest=phys_nom, low=low_map, high=high_map,
        solver_options=options_for("L4").to_dict())
    samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
        metadata=metadata, progress={"phase": "interaction-final-l4", "regime": nominal.name})
    solver_benchmarks.append({"role": "INTERACTION_FINAL", "regime": nominal.name, **int_summary})
    y_true = np.asarray([r["outputs"]["pce_pct"] if r.get("status") == VALID_FOR_SURROGATE
                         and r.get("outputs") else np.nan for r in rows], float)
    interaction_sobol_l4 = sobol_indices(y_true, design, output="pce_pct", bootstrap=200,
                                         seed=seed + 1201).as_dict()
    y_pred, pred_std = interaction_model.predict(Xint, return_std=True)
    interaction_sobol_surrogate = sobol_indices(y_pred, design, output="pce_pct", bootstrap=200,
                                                seed=seed + 1202).as_dict()
    interaction_support = [interaction_profile.classify(x) for x in Xint]
    support_counts = {s: sum(1 for z in interaction_support if z["status"] == s)
                      for s in (IN_DOMAIN_VALIDATED, IN_DOMAIN_UNCERTAIN, OUT_OF_DOMAIN)}
    old_interaction = artifact["interaction_study"]["results"][nominal.name]["per_output"]["pce_pct"]
    interaction_pair = "perovskite_eg_ev|perovskite_thickness_nm"
    detection_floor = float(artifact["interaction_study"]["detection_floor"])
    true_pair = float(interaction_sobol_l4.get("second", {}).get(interaction_pair, float("nan")))
    predicted_pair = float(interaction_sobol_surrogate.get("second", {}).get(interaction_pair, float("nan")))
    interaction_result = {
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY; interaction is a computational target",
        "axes": list(INTERACTION_AXES), "regime": nominal.name,
        "n_base": interaction_n, "n_l4_evaluations": int(int_summary["n_requested"]),
        "saltelli_design_fingerprint": design.fingerprint(),
        "slice_training_n": len(interaction_train_rows),
        "slice_validation_n": len(interaction_val_rows),
        "slice_calibration_n": len(interaction_cal_rows),
        "slice_calibration_status": interaction_calibration_status,
        "slice_calibration_metrics": interaction_calibration_metrics,
        "slice_conformal_90_radius_pp": interaction_q,
        "slice_selected_family": interaction_selected,
        "slice_training_fingerprint": interaction_fp,
        "slice_validation_scores": interaction_scores,
        "reference_v19d_pair": old_interaction.get("reportable_pairs", {}).get(interaction_pair),
        "reference_v19d_detection_floor": detection_floor,
        "new_l4_saltelli_indices": interaction_sobol_l4,
        "surrogate_saltelli_indices": interaction_sobol_surrogate,
        "new_l4_pair_estimate": true_pair,
        "surrogate_pair_estimate": predicted_pair,
        "pair_difference_surrogate_minus_l4": predicted_pair - true_pair,
        "pair_sign_recovered": bool(np.sign(true_pair) == np.sign(predicted_pair)),
        "new_l4_pair_reportable_above_calibrated_floor": bool(
            np.isfinite(true_pair) and abs(true_pair) >= detection_floor
            and interaction_sobol_l4.get("complete", False)),
        "surrogate_pair_reportable_only_if_domain_and_calibration_pass": bool(
            np.isfinite(predicted_pair) and abs(predicted_pair) >= detection_floor
            and interaction_sobol_surrogate.get("complete", False)
            and support_counts[OUT_OF_DOMAIN] == 0
            and support_counts[IN_DOMAIN_UNCERTAIN] == 0),
        "support_status_counts_on_full_interaction_design": support_counts,
        "support_detection_profile": _serialize_profile(interaction_profile),
        "prediction_interval_on_design": (interval_metrics(y_true, y_pred,
            radius=interaction_q, nominal_coverage=0.90) if np.all(np.isfinite(y_true)) else
            {"status": "INCOMPLETE_L4_DESIGN"}),
        "uncertainty_note": "the historical N=96 pair table is not used as truth; new pair results are compared to the N=768, d=4 calibrated floor (0.127726); no pairwise bootstrap CI is claimed",
    }

    # Independently selected L5 cross-checks use paired L4 CALIBRATION points,
    # never the untouched final holdout or the dedicated interaction test design.
    l5_pairs = []
    if run_l5:
        for ri, regime in enumerate(REGIMES):
            selected = [r for r in samples if r.get("role") == "CALIBRATION"
                        and r.get("status") == VALID_FOR_SURROGATE
                        and r.get("operating_regime", {}).get("name") == regime.name][:12]
            Xl5 = _row_matrix(selected, feature_names)
            if len(Xl5):
                pair_lookup = [r.get("design_point_fingerprint", "") for r in selected]
                phys = _physics_digest_for_regime(code_digest, reg_digest, regime, "L5", "IQE-M1")
                rows, summary = _generate_group(X=Xl5, feature_names=feature_names, regime=regime,
                    level="L5", role="L5_CROSSCHECK",
                    family=f"l5-crosscheck-global-calibration-{regime.name}",
                    seed=seed + 1300 + ri, model_form="IQE-M1", physics_digest=phys,
                    low=low_map, high=high_map, solver_options=options_for("L5").to_dict())
                for row, pair_id in zip(rows, pair_lookup):
                    row["paired_design_id"] = pair_id
                samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
                    metadata=metadata, progress={"phase": "l5-global-crosscheck", "regime": regime.name})
                solver_benchmarks.append({"role": "L5_CROSSCHECK", "regime": regime.name, **summary})
                l5_pairs.extend((regime.name, pair_id) for pair_id in pair_lookup)
        # Pair up to 32 fresh L4 interaction-slice CALIBRATION points with L5;
        # Saltelli L4 points remain an untouched interaction verification design.
        interaction_rows = [r for r in samples
            if r.get("role") == "INTERACTION_CALIBRATION"
            and r.get("status") == VALID_FOR_SURROGATE
            and r.get("operating_regime", {}).get("name") == nominal.name]
        n_cross = min(32, len(interaction_rows))
        cross_idx = (np.unique(np.linspace(0, len(interaction_rows) - 1, n_cross,
                                           dtype=int)) if n_cross else np.empty(0, int))
        X4_l5 = _row_matrix([interaction_rows[i] for i in cross_idx], INTERACTION_AXES)
        paired = [interaction_rows[i]["design_point_fingerprint"] for i in cross_idx]
        phys = _physics_digest_for_regime(code_digest, reg_digest, nominal, "L5", "IQE-M1")
        rows, summary = _generate_group(X=X4_l5, feature_names=INTERACTION_AXES,
            regime=nominal, level="L5", role="INTERACTION_L5_CROSSCHECK",
            family="l5-crosscheck-interaction-calibration", seed=seed + 1310,
            model_form="IQE-M1", physics_digest=phys, low=low_map, high=high_map,
            solver_options=options_for("L5").to_dict())
        for row, pair_id in zip(rows, paired):
            row["paired_design_id"] = pair_id
        samples = _append_and_checkpoint(samples, rows, dataset_path=dataset_path,
            metadata=metadata, progress={"phase": "l5-interaction-crosscheck", "regime": nominal.name})
        solver_benchmarks.append({"role": "INTERACTION_L5_CROSSCHECK",
                                  "regime": nominal.name, **summary})
        l5_pairs.extend((nominal.name, pair_id) for pair_id in paired)

    # Training data for support-aware model bundle is strictly unique valid L4.
    l5_tolerance = _profile_l5_tolerance(samples) if run_l5 else {}
    bundle.validation_l5_tolerance = l5_tolerance
    bundle.specialized_models = specialized_models
    model_file = save_bundle(bundle, model_path)

    # A separate proposal design; top predicted PCE is verified by L4, then L5.
    candidate_results = {}
    for ri, regime in enumerate(REGIMES):
        proposals = _lhs_box(48, low, high, seed + 1400 + ri * 1000,
                             exclude_withheld_corner=True)
        predictions = [bundle.predict(dict(zip(feature_names, row)), regime=regime.name)
                       for row in proposals]
        scored = []
        for i, pred in enumerate(predictions):
            pce = pred.get("predictions", {}).get("pce_pct", {}).get("prediction", -np.inf)
            scored.append((float(pce), i, pred.get("status", MODEL_UNAVAILABLE)))
        validated = [s for s in scored if s[2] == IN_DOMAIN_VALIDATED]
        pool = validated if validated else scored
        _, chosen_i, _ = max(pool)
        chosen = proposals[chosen_i]
        candidate_results[regime.name] = bundle.verify_candidate(
            dict(zip(feature_names, chosen)), regime=regime.name, run_l5=run_l5)
        candidate_results[regime.name]["candidate_parameters"] = {
            k: float(v) for k, v in zip(feature_names, chosen)}
        candidate_results[regime.name]["candidate_id"] = _canonical_sha({
            "x": [float(v).hex() for v in chosen], "regime": regime.name})[:24]
        candidate_results[regime.name]["selection_rule"] = (
            "highest predicted PCE among IN_DOMAIN_VALIDATED proposal points; if none, "
            "highest among uncertain/OOD points is still physics-checked but cannot advance")
        candidate_results[regime.name]["n_proposals"] = len(proposals)
        candidate_results[regime.name]["n_validated_support_proposals"] = len(validated)

    # Performance timing includes the real status/support path, not only a raw
    # estimator call.  Physics solves remain mandatory for candidate acceptance.
    probe_regime = REGIME_NAMES[0]
    probe_x = {n: float(ParamSet.defaults().with_mapping(
        next(r for r in REGIMES if r.name == probe_regime).settings)[n]) for n in feature_names}
    for n in feature_names:
        probe_x[n] = float((low_map[n] + high_map[n]) / 2.0)
    n_timing = 256
    t0 = time.perf_counter()
    for _ in range(n_timing):
        bundle.predict(probe_x, regime=probe_regime)
    inference_total = time.perf_counter() - t0
    single_latency = inference_total / n_timing
    Xbench = _lhs_box(256, low, high, seed + 1500, exclude_withheld_corner=True)
    t0 = time.perf_counter()
    preds_bench = [bundle.predict(dict(zip(feature_names, row)), regime=probe_regime)
                   for row in Xbench]
    batch_wall = time.perf_counter() - t0
    batch_rate = len(Xbench) / max(batch_wall, 1e-12)
    l4_times = [float(s["runtime_s"]) for s in samples
                if s.get("model_level") == "L4" and s.get("runtime_s", 0) > 0]
    l5_times = [float(s["runtime_s"]) for s in samples
                if s.get("model_level") == "L5" and s.get("runtime_s", 0) > 0]
    l4_mean, l4_median = float(np.mean(l4_times)), float(np.median(l4_times))
    l5_median = float(np.median(l5_times)) if l5_times else None
    efficiency = {
        "l4_solve_runtime_s_mean": l4_mean, "l4_solve_runtime_s_median": l4_median,
        "l4_solve_runtime_s_p95": float(np.quantile(l4_times, 0.95)) if l4_times else None,
        "l5_solve_runtime_s_median": l5_median,
        "surrogate_bundle_single_prediction_latency_s": single_latency,
        "surrogate_single_prediction_throughput_per_s": 1.0 / max(single_latency, 1e-12),
        "surrogate_batch_256_elapsed_s": batch_wall,
        "surrogate_batch_256_predictions_per_second": batch_rate,
        "measured_l4_to_surrogate_single_speedup": l4_median / single_latency if l4_median else None,
        "measured_l4_batch_throughput_solve_rate_per_s": (len(l4_times)
            / sum(float(s.get("wall_clock_s", 0.0)) for s in solver_benchmarks
                  if s.get("level") == "L4" and s.get("wall_clock_s", 0) > 0)
            if any(s.get("level") == "L4" and s.get("wall_clock_s", 0) > 0
                   for s in solver_benchmarks) else None),
        "surrogate_training_seconds_sum": float(sum(
            model.training_runtime_s for by_target in bundle.selected_models.values()
            for model in by_target.values())),
        "model_file_bytes": int(model_file["bytes"]),
        "rss_peak_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
        "valid_l4_solve_records": int(sum(1 for s in samples
            if s.get("model_level") == "L4" and s.get("status") == VALID_FOR_SURROGATE)),
        "number_of_physics_solves_actually_replaced": 0,
        "efficiency_note": "reported speedups are prediction-cost comparisons only; all promising candidates still receive L4 (and selected L5) verification",
    }
    measured_speedup = efficiency["measured_l4_to_surrogate_single_speedup"]
    efficiency["predeclared_minimum_speedup_vs_median_l4"] = MIN_SURROGATE_SPEEDUP_VS_L4
    efficiency["speedup_target_met"] = bool(
        measured_speedup is not None and measured_speedup >= MIN_SURROGATE_SPEEDUP_VS_L4)

    # Run all synthetic methods on known functions.  They are isolated from the
    # physical training data, labels and candidate rankings.
    from ..synthetic.surrogate_benchmarks import run_surrogate_synthetic_benchmarks
    synthetic = run_surrogate_synthetic_benchmarks(seed + 1600)

    # Convert unmet predeclared thresholds and weak diagnostics into explicit
    # negative results; do not imply success from campaign completion alone.
    stopping_reason_by_regime = {}
    negative_results = []
    for regime_name, stages in stage_history.items():
        final_stage = stages[-1]
        final_rmse = float(final_stage["validation_metrics"]["rmse"])
        if final_rmse <= ACCURACY_TARGET_PCE_RMSE_PP:
            reason = "predeclared independent-validation PCE RMSE target met"
        elif final_stage["stage"] == "after_stage2_global_lhs":
            marginal = float(final_stage.get("relative_improvement_from_prior_stage", 0.0))
            reason = ("PCE RMSE target not met; second adaptive batch withheld because "
                      f"stage2 relative improvement {marginal:.4g} < "
                      f"{MARGINAL_IMPROVEMENT_FRACTION:.4g}"
                      if marginal < MARGINAL_IMPROVEMENT_FRACTION else
                      "PCE RMSE target not met after the predeclared global LHS budget")
        else:
            reason = "PCE RMSE target not met after the predeclared adaptive budget"
        stopping_reason_by_regime[regime_name] = reason
        if final_rmse > ACCURACY_TARGET_PCE_RMSE_PP:
            negative_results.append({"regime": regime_name,
                "criterion": "independent_validation_pce_rmse_pp",
                "target": ACCURACY_TARGET_PCE_RMSE_PP,
                "observed": final_rmse, "outcome": "NOT_MET",
                "stopping_reason": reason})
        recall = holdout_results[regime_name]["support_detection"][
            "withheld_region_detection_recall"]
        if recall < 0.50:
            negative_results.append({"regime": regime_name,
                "criterion": "withheld_region_detection_recall",
                "target": 0.50, "observed": recall, "outcome": "WEAK_ON_FINAL_OOD_REGION"})
        if not candidate_results[regime_name]["candidate_eligible_for_optimizer"]:
            negative_results.append({"regime": regime_name,
                "criterion": "surrogate_candidate_promotion",
                "outcome": "NO_CANDIDATE_PROMOTED",
                "candidate_status": candidate_results[regime_name].get("candidate_status"),
                "reason": "support, conformal, hard-invariant and L5 gates are conjunctive"})
    speedup = efficiency["measured_l4_to_surrogate_single_speedup"]
    if speedup is None or speedup < MIN_SURROGATE_SPEEDUP_VS_L4:
        negative_results.append({"criterion": "prediction_speedup_vs_median_l4",
            "target": MIN_SURROGATE_SPEEDUP_VS_L4, "observed": speedup,
            "outcome": "NOT_MET"})
    if not interaction_result["new_l4_pair_reportable_above_calibrated_floor"]:
        negative_results.append({"criterion": "dedicated_interaction_reportability",
            "interaction": "perovskite_eg_ev|perovskite_thickness_nm",
            "outcome": "NOT_REPORTABLE_AT_PREDECLARED_N768_DETECTION_FLOOR"})

    # Per-regime training/validation/final counts after duplicate filtering.
    samples = mark_duplicates(samples)
    summary = summarize_samples(samples)
    count_table = {}
    for regime in REGIME_NAMES:
        count_table[regime] = {}
        for level in ("L4", "L5"):
            subset = [s for s in samples if s.get("operating_regime", {}).get("name") == regime
                      and s.get("model_level") == level]
            count_table[regime][level] = {
                "total_records": len(subset),
                "valid_unique_records": sum(s.get("status") == VALID_FOR_SURROGATE for s in subset),
                "invalid_physics_excluded": sum(s.get("status") == INVALID_PHYSICS for s in subset),
                "outside_verified_domain": sum(s.get("status") == OUTSIDE_VERIFIED_DOMAIN for s in subset),
                "duplicates_or_dependent": sum(s.get("status") == DUPLICATE_OR_DEPENDENT for s in subset),
                "training_records": sum(s.get("status") == VALID_FOR_SURROGATE
                                         and s.get("role") in ("TRAIN", "ADAPTIVE_TRAIN")
                                         for s in subset),
                "validation_or_holdout": sum(s.get("role") in
                    ("VALIDATION", "FINAL_HOLDOUT", "BOUNDARY_VALIDATION")
                    and s.get("status") == VALID_FOR_SURROGATE for s in subset),
            }
    results = {
        "campaign": "V1.9-E validated surrogate research engine",
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY; no experimental data or claim",
        "seed": int(seed), "audit": audit,
        "metadata": metadata,
        "data_contract": {"version": "apmt-surrogate-data/1.0",
            "input_features": list(feature_names),
            "full_registry_vector_preserved": list(vector_names()),
            "held_fixed_parameters": list(bundle.fixed_parameter_names),
            "held_fixed_values": {n: bundle.registry_defaults[n]
                                  for n in bundle.fixed_parameter_names},
            "operating_regime_features": "regime key and irradiance_suns/temperature_k metadata; separate regime-specific model",
            "outputs": {n: {"unit": OUTPUT_UNITS[n], "target": True} for n in OUTPUT_NAMES},
            "status_values": [VALID_FOR_SURROGATE, INVALID_PHYSICS,
                              OUTSIDE_VERIFIED_DOMAIN, "INCOMPLETE_OUTPUT",
                              DUPLICATE_OR_DEPENDENT, "UNRESOLVED_DATA"],
            "invalid_outputs_written": False,
            "training_rows_are_unique_and_valid_l4_only": True,
            "design_roles": {"TRAIN/ADAPTIVE_TRAIN": "fit only; valid unique L4",
                "VALIDATION": "family selection and adaptive acquisition",
                "CALIBRATION": "separate marginal conformal/raw-uncertainty calibration",
                "FINAL_HOLDOUT": "untouched final prediction assessment",
                "SUPPORT_IN_CAL/OOD_CALIBRATION": "separate support/OOD threshold calibration",
                "OOD_FINAL": "independent OOD detection assessment",
                "BOUNDARY_VALIDATION": "separate edge-region residual assessment",
                "L5_CROSSCHECK": "paired numerical-fidelity checks, not training"},
            "dataset_fingerprint": dataset_fingerprint(samples),
            "training_fingerprints_by_regime": bundle.training_fingerprints,
            "rejection_ledger_preserved": True},
        "actual_points_by_regime_and_fidelity": count_table,
        "dataset_summary": summary,
        "staged_sampling": {"policy": "LHS stage1 -> independent validation -> residual-local adaptive batch -> LHS stage2 -> optional second adaptive batch; every stage re-evaluated on validation",
            "predeclared_stopping_thresholds": stage_thresholds,
            "per_regime": stage_history,
            "stopping_reason_by_regime": stopping_reason_by_regime,
            "criteria_outcome": {r: {"final_validation_pce_rmse_pp": float(v[-1]["validation_metrics"]["rmse"]),
                "accuracy_target_met": bool(v[-1]["validation_metrics"]["rmse"]
                    <= ACCURACY_TARGET_PCE_RMSE_PP)} for r, v in stage_history.items()},
            "efficiency_speedup_target_met": efficiency["speedup_target_met"],
            "adaptive_samples_added": adaptive_counts,
            "max_global_train_per_regime": initial_n + stage2_n + 2 * adaptive_n,
            "validation_design_families": "fresh independent L4 LHS; used for family selection/adaptive acquisition, not fit",
            "calibration_design_families": "disjoint fresh L4 LHS; used only for conformal/raw-spread calibration after family selection",
            "final_holdout_design_families": "fresh independent L4 LHS; never used for fitting, model-family choice, calibration, threshold selection, or adaptive acquisition"},
        "model_comparison": model_scores,
        "grouped_design_family_cross_validation": grouped_cv,
        "final_holdout": holdout_results,
        "extrapolation_detection": {
            "global_by_regime": {r: holdout_results[r]["support_detection"] for r in REGIME_NAMES},
            "withheld_region": "verified-box corner with normalized perovskite Eg and absorber thickness both >=0.90; excluded from all 14-D global/adaptive training designs; independent randomized L4 corner draws calibrate and test thresholds",
            "known_out_of_domain": "points outside the shared verified box must return OUT_OF_DOMAIN before prediction acceptance",
            "complementary_diagnostics": ["verified-box hard check", "nearest-neighbor distance normalized to verified ranges", "boundary proximity", "predictive spread", "top-family disagreement"],
            "feasibility_classifier": "not added; support/OOD status is not an invariant or a proof of physical validity"},
        "interior_optimum_recovery": optimum_metrics,
        "interaction_recovery": interaction_result,
        "l5_crosscheck": {"available": bool(run_l5),
            "paired_l4_l5_tolerance_q95_by_regime": l5_tolerance,
            "pairing": "same parameter inputs, distinct L4/L5 model levels; cross-check rows excluded from regression training",
            "n_l5_records": len(l5_times),
            "n_paired_l4_l5_design_points": len(l5_pairs),
            "paired_l4_design_point_sample": l5_pairs[:8],
            "calibration_split_role": "L5 tolerances are profiled only on paired L4/L5 CALIBRATION designs; FINAL_HOLDOUT and interaction Saltelli verification remain untouched",
            "physics_independence_note": "L5 is a numerical-refinement level in the same physics code, not an independent physical model or experiment"},
        "verified_candidate_probes": candidate_results,
        "performance": efficiency,
        "solver_batch_benchmarks": solver_benchmarks,
        "synthetic_method_validation": synthetic,
        "negative_results": negative_results,
        "limitations": [
            "14-D global training sizes are finite and sparse relative to the full tensor product; per-output holdout errors govern trust.",
            "Three trained operating regimes only; no interpolation to new irradiance, temperature, spectrum, or angle.",
            "29 registry parameters outside the 14 sensitivity axes are fixed at registry defaults; changes return MODEL_UNAVAILABLE.",
            "Conformal intervals give marginal prediction coverage only under exchangeability; conditional coverage, physics-model uncertainty and experiment uncertainty are distinct/not established.",
            "Shared-box validity is empirically probed rather than a mathematical proof that every point in the box is valid.",
            "L5 uses the same physical model with finer numerical resolution; it is not independent validation of model form.",
            "GP and tree spreads are empirical uncertainty diagnostics, not experimental or physical confidence intervals.",
        ],
        "files": {"dataset": str(dataset_path.relative_to(ROOT)),
                  "model_bundle": str(model_path.relative_to(ROOT))},
        "campaign_runtime_s": float(time.perf_counter() - t_campaign),
        "status": "PRE_GATE_COMPUTATIONAL_SURROGATE_FOUNDATION",
    }
    dataset_summary = save_dataset(dataset_path, samples, metadata=metadata,
        extra={"campaign": "V1.9-E", "training_fingerprints": bundle.training_fingerprints,
               "sample_count": len(samples), "progress": {"phase": "complete"}})
    results["dataset_artifact"] = dataset_summary
    model_file["path"] = str(model_path.relative_to(ROOT))
    results["model_artifact"] = model_file
    results["campaign_runtime_s"] = float(time.perf_counter() - t_campaign)
    result_file = _write_json(results_path, results)
    return {"results": results, "result_artifact": result_file,
            "dataset_artifact": dataset_summary, "model_artifact": model_file,
            "samples": samples, "bundle": bundle}
