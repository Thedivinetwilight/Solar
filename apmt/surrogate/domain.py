"""Empirically calibrated support and extrapolation checks.

No convex hull is constructed in the 14-D parameter space: with sparse samples it
is expensive and a high-dimensional hull would be nearly empty.  The equivalent
support diagnostics used here are the hard verified box, normalized nearest-
neighbor distance, boundary proximity, model disagreement and uncertainty.  Each
threshold is learned from campaign-specific calibration data, not a universal
constant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

IN_DOMAIN_VALIDATED = "IN_DOMAIN_VALIDATED"
IN_DOMAIN_UNCERTAIN = "IN_DOMAIN_UNCERTAIN"
OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
INVALID_INPUT = "INVALID_INPUT"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
PREDICTION_STATUSES = (IN_DOMAIN_VALIDATED, IN_DOMAIN_UNCERTAIN, OUT_OF_DOMAIN,
                       INVALID_INPUT, MODEL_UNAVAILABLE)


def normalize(X: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    X = np.asarray(X, float)
    low = np.asarray(low, float).reshape(-1)
    high = np.asarray(high, float).reshape(-1)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    if X.shape[1] != len(low) or len(low) != len(high):
        raise ValueError("X and bounds have different feature dimensions")
    span = high - low
    if np.any(span <= 0):
        raise ValueError("domain bounds must have positive width")
    return (X - low) / span


def nearest_distances(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    q = np.asarray(query, float)
    r = np.asarray(reference, float)
    if q.ndim == 1:
        q = q.reshape(1, -1)
    if r.ndim != 2 or q.ndim != 2 or r.shape[1] != q.shape[1] or len(r) == 0:
        raise ValueError("query/reference must be nonempty matrices of equal dimension")
    from scipy.spatial import cKDTree
    tree = cKDTree(r)
    distances, _ = tree.query(q, k=1, workers=1)
    return np.asarray(distances, float).reshape(-1)


def leave_one_out_distances(X: np.ndarray) -> np.ndarray:
    x = np.asarray(X, float)
    if x.ndim != 2 or len(x) < 2:
        raise ValueError("at least two points are required")
    from scipy.spatial import cKDTree
    distances, _ = cKDTree(x).query(x, k=2, workers=1)
    return np.asarray(distances[:, 1], float)


@dataclass
class SupportProfile:
    feature_names: tuple[str, ...]
    low: np.ndarray
    high: np.ndarray
    training_points_normalized: np.ndarray
    nearest_distance_ood_threshold: float
    nearest_distance_uncertain_threshold: float
    uncertainty_ratio_threshold: float
    disagreement_ratio_threshold: float
    boundary_fraction_threshold: float
    calibration: dict

    def classify(self, x: Sequence[float], *, uncertainty_ratio: float = 0.0,
                 disagreement_ratio: float = 0.0) -> dict:
        point = np.asarray(x, float).reshape(-1)
        if point.shape != (len(self.feature_names),) or not np.all(np.isfinite(point)):
            return {"status": INVALID_INPUT, "reason": "wrong shape or non-finite input"}
        lo, hi = np.asarray(self.low), np.asarray(self.high)
        if np.any(point < lo - 1e-12) or np.any(point > hi + 1e-12):
            distance = float(nearest_distances(normalize(point, lo, hi),
                                               self.training_points_normalized)[0])
            return {"status": OUT_OF_DOMAIN,
                    "reason": "outside the shared verified parameter box",
                    "nearest_distance_normalized": distance,
                    "nearest_distance_threshold": (float(self.nearest_distance_ood_threshold)
                        if np.isfinite(self.nearest_distance_ood_threshold) else None),
                    "support_calibration_fingerprint": self.calibration.get(
                        "withheld_support_calibration_data_fingerprint"),
                    "boundary_margin_fraction": float(np.min(np.minimum(
                        (point - lo) / (hi - lo), (hi - point) / (hi - lo))))}
        z = normalize(point, lo, hi)[0]
        distance = float(nearest_distances(z, self.training_points_normalized)[0])
        margin = float(np.min(np.minimum(z, 1.0 - z)))
        if distance > self.nearest_distance_ood_threshold:
            status = OUT_OF_DOMAIN
            reason = "nearest-neighbor distance exceeds calibrated support threshold"
        elif (distance > self.nearest_distance_uncertain_threshold
              or margin <= self.boundary_fraction_threshold
              or uncertainty_ratio > self.uncertainty_ratio_threshold
              or disagreement_ratio > self.disagreement_ratio_threshold):
            status = IN_DOMAIN_UNCERTAIN
            reason = "inside verified box but at a sparsely supported/boundary/uncertain point"
        else:
            status = IN_DOMAIN_VALIDATED
            reason = "inside verified box and calibrated support envelope"
        return {
            "status": status, "reason": reason,
            "nearest_distance_normalized": distance,
            "nearest_distance_threshold": (float(self.nearest_distance_ood_threshold)
                if np.isfinite(self.nearest_distance_ood_threshold) else None),
            "nearest_distance_uncertain_threshold": (
                float(self.nearest_distance_uncertain_threshold)
                if np.isfinite(self.nearest_distance_uncertain_threshold) else None),
            "boundary_margin_fraction": margin,
            "uncertainty_ratio": float(uncertainty_ratio),
            "uncertainty_ratio_threshold": (float(self.uncertainty_ratio_threshold)
                if np.isfinite(self.uncertainty_ratio_threshold) else None),
            "uncertainty_threshold_status": self.calibration.get(
                "uncertainty_threshold_status", "NOT_CALIBRATED"),
            "disagreement_ratio": float(disagreement_ratio),
            "disagreement_ratio_threshold": (float(self.disagreement_ratio_threshold)
                if np.isfinite(self.disagreement_ratio_threshold) else None),
            "disagreement_threshold_status": self.calibration.get(
                "disagreement_threshold_status", "NOT_CALIBRATED"),
            "support_calibration_fingerprint": self.calibration.get(
                "withheld_support_calibration_data_fingerprint"),
        }


def _threshold_with_fpr(in_domain: np.ndarray, withheld: np.ndarray,
                        max_false_positive_rate: float) -> tuple[float, dict]:
    in_d = np.asarray(in_domain, float).reshape(-1)
    out_d = np.asarray(withheld, float).reshape(-1)
    if in_d.size < 4 or out_d.size < 4:
        raise ValueError("support calibration needs at least four in-domain and withheld points")
    if not 0.0 <= max_false_positive_rate <= 1.0:
        raise ValueError("max_false_positive_rate must lie in [0, 1]")
    candidates = np.unique(np.concatenate([in_d, out_d]))
    best = None
    for threshold in candidates:
        fpr = float(np.mean(in_d > threshold))
        tpr = float(np.mean(out_d > threshold))
        if fpr <= max_false_positive_rate + 1e-12:
            score = (tpr, -fpr, -float(threshold))
            if best is None or score > best[0]:
                best = (score, float(threshold), fpr, tpr)
    if best is None:  # pragma: no cover - candidates always include max(in_d)
        threshold = float(np.max(in_d))
        fpr = 0.0
        tpr = float(np.mean(out_d > threshold))
    else:
        _, threshold, fpr, tpr = best
    return threshold, {
        "selection": "maximize withheld-region recall subject to calibrated in-domain FPR cap",
        "false_positive_rate_cap": float(max_false_positive_rate),
        "calibration_false_positive_rate": float(fpr),
        "calibration_withheld_recall": float(tpr),
        "n_in_domain_calibration": int(len(in_d)),
        "n_withheld_calibration": int(len(out_d)),
    }


def fit_support_profile(*, feature_names: Sequence[str], low: Sequence[float],
                        high: Sequence[float], training_X: np.ndarray,
                        in_domain_calibration_X: np.ndarray,
                        withheld_region_calibration_X: np.ndarray,
                        uncertainty_ratios: Sequence[float] = (),
                        disagreement_ratios: Sequence[float] = (),
                        boundary_fraction_threshold: float = 0.05,
                        max_false_positive_rate: float = 0.10) -> SupportProfile:
    names = tuple(feature_names)
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    train_z = normalize(np.asarray(training_X, float), lo, hi)
    in_z = normalize(np.asarray(in_domain_calibration_X, float), lo, hi)
    withheld_z = normalize(np.asarray(withheld_region_calibration_X, float), lo, hi)
    d_in = nearest_distances(in_z, train_z)
    d_ood = nearest_distances(withheld_z, train_z)
    ood_t, threshold_cal = _threshold_with_fpr(d_in, d_ood, max_false_positive_rate)
    uncertain_t = float(np.quantile(d_in, 0.90, method="higher"))
    ur = np.asarray(list(uncertainty_ratios), float)
    dr = np.asarray(list(disagreement_ratios), float)
    ur = ur[np.isfinite(ur)]
    dr = dr[np.isfinite(dr)]
    uncertainty_t = float(np.quantile(ur, 0.95, method="higher")) if ur.size else float("inf")
    disagreement_t = float(np.quantile(dr, 0.95, method="higher")) if dr.size else float("inf")
    calibration = {
        **threshold_cal,
        "nearest_distance_in_domain_q90": uncertain_t,
        "nearest_distance_withheld_q50": float(np.median(d_ood)),
        "nearest_distance_in_domain_q95": float(np.quantile(d_in, 0.95, method="higher")),
        "uncertainty_ratio_q95": (uncertainty_t if np.isfinite(uncertainty_t) else None),
        "uncertainty_threshold_status": "CALIBRATED" if ur.size else "NOT_CALIBRATED",
        "disagreement_ratio_q95": (disagreement_t if np.isfinite(disagreement_t) else None),
        "disagreement_threshold_status": "CALIBRATED" if dr.size else "NOT_CALIBRATED",
        "boundary_fraction_threshold": float(boundary_fraction_threshold),
        "support_metric": "Euclidean distance in verified-box-normalized feature coordinates",
        "convex_hull": "not computed in 14-D; nearest-neighbor distance + hard box used",
    }
    return SupportProfile(names, lo, hi, train_z, ood_t, uncertain_t,
                          uncertainty_t, disagreement_t,
                          float(boundary_fraction_threshold), calibration)


def detection_metrics(profile: SupportProfile, X_in: np.ndarray,
                      X_withheld: np.ndarray) -> dict:
    """Evaluate support classification on independent in-domain and OOD inputs."""
    statuses_in = [profile.classify(x)["status"] for x in np.asarray(X_in, float)]
    statuses_out = [profile.classify(x)["status"] for x in np.asarray(X_withheld, float)]
    false_positive = sum(s == OUT_OF_DOMAIN for s in statuses_in) / max(1, len(statuses_in))
    recall = sum(s == OUT_OF_DOMAIN for s in statuses_out) / max(1, len(statuses_out))
    uncertain_rate_in = sum(s == IN_DOMAIN_UNCERTAIN for s in statuses_in) / max(1, len(statuses_in))
    return {
        "method": "verified-box check + calibrated nearest-neighbor distance; uncertainty and family disagreement can downgrade to uncertain",
        "n_in_domain": len(statuses_in), "n_withheld": len(statuses_out),
        "in_domain_false_out_of_domain_rate": float(false_positive),
        "withheld_region_detection_recall": float(recall),
        "in_domain_uncertain_rate": float(uncertain_rate_in),
        "calibration": dict(profile.calibration),
    }
