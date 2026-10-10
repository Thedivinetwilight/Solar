"""Prediction and L4/L5 verification interfaces for downstream exploration."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .data import OUTPUT_UNITS
from .domain import (IN_DOMAIN_UNCERTAIN, IN_DOMAIN_VALIDATED, INVALID_INPUT,
                     MODEL_UNAVAILABLE, OUT_OF_DOMAIN, SupportProfile)
from .models import FittedRegressor

ENGINE_VERSION = "v19e-surrogate-engine/1.1"


def _fingerprint_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str,
                     allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass
class SurrogateBundle:
    """Fitted, per-output/per-regime model collection with support guardrails.

    Each output is selected independently using an independent validation design.
    The models carry their training-data fingerprints.  This bundle does not
    replace the reference physics solver and is not an experimental posterior.
    """

    feature_names: tuple[str, ...]
    regimes: dict[str, dict]
    low: np.ndarray
    high: np.ndarray
    registry_defaults: dict[str, float]
    fixed_parameter_names: tuple[str, ...]
    selected_models: dict[str, dict[str, FittedRegressor]]
    alternative_models: dict[str, dict[str, list[FittedRegressor]]]
    support_profiles: dict[str, SupportProfile]
    model_cards: dict[str, dict[str, dict]]
    training_fingerprints: dict[str, str]
    validation_l5_tolerance: dict[str, dict[str, float]] = field(default_factory=dict)
    specialized_models: dict[str, Any] = field(default_factory=dict)
    version: str = ENGINE_VERSION
    label: str = "PRE-GATE / MODEL-OBSERVED / EXPLORATORY"

    def predict(self, parameters: Mapping[str, float], *, regime: str) -> dict:
        """Predict all available outputs and return an explicit support status.

        Missing design features are INVALID_INPUT.  A changed parameter outside
        the trained 14-axis sensitivity design is MODEL_UNAVAILABLE rather than
        silently treated as a default.  Only the three named V1.9-D regimes are
        trained; unseen operating conditions are not interpolated.
        """
        if regime not in self.regimes:
            return {"status": MODEL_UNAVAILABLE,
                    "reason": f"no trained model for operating regime {regime!r}",
                    "predictions": {}, "model_version": self.version}
        if not isinstance(parameters, Mapping):
            return {"status": INVALID_INPUT, "reason": "parameters must be a mapping",
                    "predictions": {}, "model_version": self.version}
        accepted_names = (set(self.feature_names) | set(self.fixed_parameter_names)
                          | {"irradiance_suns", "temperature_k"})
        unknown = sorted(repr(name) for name in parameters
                         if not isinstance(name, str) or name not in accepted_names)
        if unknown:
            return {"status": INVALID_INPUT,
                    "reason": f"unknown parameter names: {unknown}",
                    "predictions": {}, "model_version": self.version}
        missing = [n for n in self.feature_names if n not in parameters]
        if missing:
            return {"status": INVALID_INPUT, "reason": f"missing features: {missing}",
                    "predictions": {}, "model_version": self.version}
        try:
            x = np.asarray([float(parameters[n]) for n in self.feature_names], dtype=float)
        except (TypeError, ValueError, OverflowError):
            return {"status": INVALID_INPUT, "reason": "features must be numeric",
                    "predictions": {}, "model_version": self.version}
        if not np.all(np.isfinite(x)):
            return {"status": INVALID_INPUT, "reason": "features must be finite",
                    "predictions": {}, "model_version": self.version}
        for name in ("irradiance_suns", "temperature_k"):
            if name not in parameters:
                continue
            expected = self.regimes[regime].get(name)
            try:
                value = float(parameters[name])
            except (ValueError, TypeError, OverflowError):
                return {"status": INVALID_INPUT, "reason": f"{name} must be numeric",
                        "predictions": {}, "model_version": self.version}
            if not np.isfinite(value):
                return {"status": INVALID_INPUT, "reason": f"{name} must be finite",
                        "predictions": {}, "model_version": self.version}
            if expected is None or not np.isclose(value, float(expected), rtol=1e-12, atol=1e-12):
                return {"status": MODEL_UNAVAILABLE,
                        "reason": f"{name}={value:g} does not match the trained regime value {expected!r}",
                        "predictions": {}, "model_version": self.version}
        changed_unmodeled = []
        for name in self.fixed_parameter_names:
            if name in parameters:
                try:
                    value = float(parameters[name])
                except (ValueError, TypeError, OverflowError):
                    return {"status": INVALID_INPUT, "reason": f"{name} must be numeric",
                            "predictions": {}, "model_version": self.version}
                if not np.isfinite(value):
                    return {"status": INVALID_INPUT, "reason": f"{name} must be finite",
                            "predictions": {}, "model_version": self.version}
                default = float(self.registry_defaults[name])
                if abs(value - default) > 1e-12 * max(1.0, abs(default)):
                    changed_unmodeled.append(name)
        if changed_unmodeled:
            return {"status": MODEL_UNAVAILABLE,
                    "reason": "surrogate was trained with these unmodeled parameters fixed at registry defaults: "
                              + ", ".join(changed_unmodeled),
                    "predictions": {}, "model_version": self.version}

        entries: dict[str, dict] = {}
        std_ratios, disagreement_ratios = [], []
        for target, model in self.selected_models.get(regime, {}).items():
            try:
                pred, raw_std = model.predict(x, return_std=True)
                mu = float(pred[0])
                if not np.isfinite(mu):
                    return {"status": MODEL_UNAVAILABLE,
                            "reason": f"non-finite prediction from {target}",
                            "predictions": {}, "model_version": self.version}
                alternatives = self.alternative_models.get(regime, {}).get(target, [])
                alt_values = [mu]
                for alt in alternatives:
                    val, _ = alt.predict(x, return_std=False)
                    if np.isfinite(val[0]):
                        alt_values.append(float(val[0]))
                disagreement = (float(np.std(alt_values, ddof=1)) if len(alt_values) > 1 else 0.0)
                card = self.model_cards[regime][target]
                radius = float(model.conformal_radius) if model.conformal_radius is not None else None
                std_value = None if raw_std is None else float(raw_std[0])
                target_scale = max(float(card.get("target_scale", model.target_scale)), 1e-14)
                std_ratio = (std_value / target_scale) if std_value is not None else 0.0
                disagreement_scale = card.get("calibration_rmse")
                if disagreement_scale is None:
                    disagreement_scale = card.get("validation_rmse", 0.0)
                disagreement_ratio = disagreement / max(float(disagreement_scale),
                                                        target_scale * 1e-8, 1e-12)
                if std_value is not None:
                    std_ratios.append(std_ratio)
                disagreement_ratios.append(disagreement_ratio)
                entries[target] = {
                    "prediction": mu, "unit": OUTPUT_UNITS.get(target, ""),
                    "model_family": model.family,
                    "model_version": model.model_version,
                    "training_data_fingerprint": model.training_fingerprint,
                    "training_points": model.n_training,
                    "calibration_data_fingerprint": model.calibration_fingerprint,
                    "calibration_points": model.calibration_points,
                    "uncertainty_calibration_status": card.get(
                        "conformal_calibration_status", "NOT_CALIBRATED"),
                    "raw_predictive_std": std_value,
                    "raw_uncertainty_status": model.raw_uncertainty_note,
                    "conformal_coverage": model.conformal_coverage if radius is not None else None,
                    "conformal_radius": radius,
                    "conformal_interval": ([mu - radius, mu + radius] if radius is not None else None),
                    "family_disagreement_std": disagreement,
                    "family_disagreement_ratio": disagreement_ratio,
                }
            except Exception as exc:  # downstream inference must fail closed
                return {"status": MODEL_UNAVAILABLE,
                        "reason": f"model prediction failed for {target}: {type(exc).__name__}: {exc}",
                        "predictions": {}, "model_version": self.version}
        if not entries:
            return {"status": MODEL_UNAVAILABLE, "reason": "no fitted target models",
                    "predictions": {}, "model_version": self.version}
        support = self.support_profiles[regime].classify(
            x, uncertainty_ratio=max(std_ratios, default=0.0),
            disagreement_ratio=max(disagreement_ratios, default=0.0))
        return {
            **support, "predictions": entries,
            "operating_regime": regime,
            "regime_conditions": dict(self.regimes[regime]),
            "model_version": self.version,
            "label": self.label,
            "training_data_fingerprint": self.training_fingerprints[regime],
            "physics_model_uncertainty": "NOT_QUANTIFIED_BY_SURROGATE",
            "experimental_uncertainty": "NOT_QUANTIFIED; NO EXPERIMENTAL DATA USED",
        }

    def verify_candidate(self, parameters: Mapping[str, float], *, regime: str,
                         run_l5: bool = True,
                         diagnostic_outside_domain: bool = False) -> dict:
        """Run an authoritative guarded L4 solve after support/uncertainty checks.

        Out-of-domain points are not evaluated by default.  If explicitly requested
        as a diagnostic and inside registered bounds, they can be solved, but they
        remain ineligible for progression.  A valid L4 result never makes an
        extrapolated surrogate prediction validated.
        """
        from ..params.registry import ParamSet
        from ..validation.guard import evaluate_guarded

        prediction = self.predict(parameters, regime=regime)
        status = prediction.get("status")
        if status in (INVALID_INPUT, MODEL_UNAVAILABLE):
            return {"candidate_status": status, "prediction": prediction,
                    "l4": None, "l5": None, "candidate_eligible_for_optimizer": False}
        xmap = dict(parameters)
        low, high = self.low, self.high
        x = np.asarray([float(xmap[n]) for n in self.feature_names], float)
        inside = bool(np.all(x >= low - 1e-12) and np.all(x <= high + 1e-12))
        if not inside and not diagnostic_outside_domain:
            return {"candidate_status": OUT_OF_DOMAIN, "prediction": prediction,
                    "l4": None, "l5": None, "candidate_eligible_for_optimizer": False,
                    "reason": "outside shared verified box; solver not run by default"}
        settings = dict(self.regimes[regime])
        values = {k: float(v) for k, v in xmap.items()
                  if k in ParamSet.defaults().names()}
        values.update({k: float(v) for k, v in settings.items()
                      if k in ParamSet.defaults().names()})
        try:
            ps = ParamSet.defaults().with_mapping(values)
        except (ValueError, KeyError, TypeError) as exc:
            return {"candidate_status": INVALID_INPUT, "prediction": prediction,
                    "l4": None, "l5": None, "candidate_eligible_for_optimizer": False,
                    "reason": f"parameter registry rejected candidate: {exc}"}
        campaign_id = "v19e-candidate-verification"
        l4_rec = evaluate_guarded(ps, level="L4", model_form="IQE-M1",
                                  campaign_id=campaign_id, seed=0)
        l4 = _record_summary(l4_rec)
        predicted_outputs = prediction.get("predictions", {})
        discrepancies: dict[str, float] = {}
        within_intervals = bool(predicted_outputs)
        if l4_rec.valid and l4_rec.result is not None:
            actual = _result_outputs(l4_rec.result)
            for name, entry in predicted_outputs.items():
                observed = actual.get(name)
                if observed is None:
                    within_intervals = False
                    continue
                discrepancies[name] = float(entry["prediction"] - observed)
                interval = entry.get("conformal_interval")
                if interval is None or not (interval[0] <= observed <= interval[1]):
                    within_intervals = False
        else:
            actual = {}
            within_intervals = False
        l5_summary = None
        l5_ok = not run_l5
        if run_l5 and l4_rec.valid:
            l5_rec = evaluate_guarded(ps, level="L5", model_form="IQE-M1",
                                      campaign_id=campaign_id + "-L5", seed=0)
            l5_summary = _record_summary(l5_rec)
            l5_ok = bool(l5_rec.valid and l5_rec.result is not None)
            if l5_ok:
                l5_outputs = _result_outputs(l5_rec.result)
                tolerance_map = self.validation_l5_tolerance.get(regime, {})
                deltas, checks = {}, {}
                for name in predicted_outputs:
                    l4_value, l5_value = actual.get(name), l5_outputs.get(name)
                    tolerance = tolerance_map.get(name)
                    try:
                        tolerance = float(tolerance)
                    except (TypeError, ValueError, OverflowError):
                        tolerance = float("nan")
                    if (l4_value is None or l5_value is None
                            or not np.isfinite(tolerance) or tolerance < 0):
                        deltas[name] = None
                        checks[name] = False
                        continue
                    delta = float(l5_value - l4_value)
                    deltas[name] = delta
                    checks[name] = abs(delta) <= tolerance
                l5_summary["delta_l5_minus_l4"] = deltas
                l5_summary["within_campaign_calibrated_tolerance"] = checks
                l5_ok = l5_ok and bool(checks) and all(checks.values())
        support_ok = status == IN_DOMAIN_VALIDATED
        l4_ok = bool(l4_rec.valid and inside)
        ready = bool(support_ok and l4_ok and within_intervals and l5_ok)
        if not l4_rec.valid:
            candidate_status = "INVALID_PHYSICS"
        elif not inside:
            candidate_status = OUT_OF_DOMAIN
        elif not support_ok:
            candidate_status = IN_DOMAIN_UNCERTAIN
        elif not within_intervals:
            candidate_status = "SURROGATE_ERROR_EXCEEDS_CONFORMAL_INTERVAL"
        elif run_l5 and not l5_ok:
            candidate_status = "L5_CROSSCHECK_FAILED_OR_OUTSIDE_CALIBRATED_TOLERANCE"
        else:
            candidate_status = "L4_VERIFIED_L5_CROSSCHECKED" if run_l5 else "L4_VERIFIED"
        return {
            "candidate_status": candidate_status,
            "candidate_eligible_for_optimizer": ready,
            "prediction_status": status,
            "prediction": prediction,
            "verified_l4_outputs": actual,
            "surrogate_minus_l4": discrepancies,
            "surrogate_error_inside_conformal_interval": within_intervals,
            "l4": l4, "l5": l5_summary,
            "hard_invariants_passed": bool(l4_rec.valid),
            "parameter_distance_from_training_coverage": prediction.get("nearest_distance_normalized"),
            "operating_regime": regime,
            "model_version": self.version,
            "training_data_fingerprint": self.training_fingerprints.get(regime),
            "note": "L4/L5 remain computational models; this record is not experimental evidence or a discovery claim",
        }


def _result_outputs(result: Any) -> dict[str, float | None]:
    detail = getattr(result, "detail", {}) or {}
    thermal = detail.get("thermal", {}) if isinstance(detail, dict) else {}
    raw = {
        "pce_pct": getattr(result, "pce_pct", None),
        "jsc_ma_cm2": getattr(result, "jsc_ma_cm2", None),
        "voc_v": getattr(result, "voc_v", None), "ff": getattr(result, "ff", None),
        "temperature_k": getattr(result, "temperature_k", None),
        "j_top_sc": getattr(result, "j_top_sc", None),
        "j_bottom_sc": getattr(result, "j_bottom_sc", None),
        "current_matching_ratio": getattr(result, "current_matching_ratio", None),
        "heat_load_mw_cm2": thermal.get("heat_load_mw_cm2"),
        "conduction_loss_mw_cm2": thermal.get("conduction_loss_mw_cm2"),
        "radiative_loss_mw_cm2": thermal.get("radiative_loss_mw_cm2"),
    }
    out = {}
    for k, v in raw.items():
        try:
            f = float(v)
            out[k] = f if np.isfinite(f) else None
        except (TypeError, ValueError, OverflowError):
            out[k] = None
    return out


def _record_summary(rec: Any) -> dict:
    return {
        "valid": bool(rec.valid), "model_level": rec.level,
        "solver": rec.solver, "runtime_s": float(rec.runtime_s),
        "hard_invariants": [r.to_dict() for r in rec.verdict.records
                            if getattr(getattr(r, "severity", None), "value", None) == "HARD"],
        "hard_invariant_status": "PASS" if rec.valid else "FAIL",
        "error": rec.error,
        "outputs": _result_outputs(rec.result) if rec.result is not None else None,
    }


def save_bundle(bundle: SurrogateBundle, path: str | Path, *, compress: int = 3) -> dict:
    """Persist the fitted model bundle without hiding its data fingerprints."""
    import joblib
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    joblib.dump(bundle, tmp, compress=compress, protocol=5)
    tmp.replace(target)
    raw = target.read_bytes()
    return {"path": str(target), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "format": "joblib",
            "version": bundle.version}


def load_bundle(path: str | Path) -> SurrogateBundle:
    import joblib
    bundle = joblib.load(path)
    if not isinstance(bundle, SurrogateBundle):
        raise TypeError("file does not contain an APMT SurrogateBundle")
    return bundle
