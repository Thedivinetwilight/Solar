"""Deterministic adaptive sample selection from independent validation residuals."""
from __future__ import annotations

import numpy as np


def localize_high_errors(X: np.ndarray, residuals: np.ndarray, *,
                         low: np.ndarray | None = None, high: np.ndarray | None = None,
                         n_regions: int = 5) -> list[dict]:
    """Summarize spatial clusters around the largest absolute validation errors."""
    x = np.asarray(X, float)
    r = np.abs(np.asarray(residuals, float).reshape(-1))
    if x.ndim != 2 or len(x) != len(r) or len(r) == 0:
        raise ValueError("X and residuals must be nonempty and row-aligned")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(r)):
        raise ValueError("adaptive localization requires finite validation rows")
    order = np.argsort(-r, kind="stable")
    n_select = min(len(order), max(n_regions, 1) * max(1, int(np.ceil(len(order) * 0.08))))
    candidates = order[:n_select]
    # Greedy farthest-first clustering prevents reporting the same local error
    # spike repeatedly while retaining reproducible ordering.
    centers: list[int] = []
    for idx in candidates:
        if not centers:
            centers.append(int(idx))
        else:
            distances = np.linalg.norm(x[centers] - x[idx], axis=1)
            if float(distances.min()) > 0.12:
                centers.append(int(idx))
        if len(centers) >= n_regions:
            break
    if not centers:
        centers = [int(order[0])]
    lo = np.min(x, axis=0) if low is None else np.asarray(low, float)
    hi = np.max(x, axis=0) if high is None else np.asarray(high, float)
    regions = []
    for rank, idx in enumerate(centers, 1):
        d = np.linalg.norm(x - x[idx], axis=1)
        local = np.flatnonzero(d <= 0.12)
        if local.size == 0:
            local = np.asarray([idx])
        regions.append({
            "rank": rank, "validation_row": int(idx),
            "center": x[idx].tolist(),
            "peak_absolute_error": float(r[idx]),
            "local_n": int(local.size),
            "local_mean_absolute_error": float(np.mean(r[local])),
            "local_max_absolute_error": float(np.max(r[local])),
            "box_low": np.maximum(lo, np.min(x[local], axis=0)).tolist(),
            "box_high": np.minimum(hi, np.max(x[local], axis=0)).tolist(),
        })
    return regions


def propose_near_errors(X_validation: np.ndarray, residuals: np.ndarray, *,
                        low: np.ndarray, high: np.ndarray,
                        existing_X: np.ndarray, n_samples: int,
                        seed: int, perturbation_fraction: float = 0.06) -> np.ndarray:
    """Propose new points near high-error validation regions, never reusing labels.

    Perturbations are generated in normalized verified-box coordinates, clipped to
    the verified box, and rejected if they duplicate an existing/training/validation
    point.  The validation inputs identify regions only; their outputs are not
    copied into the training set.
    """
    xval = np.asarray(X_validation, float)
    residual = np.abs(np.asarray(residuals, float).reshape(-1))
    lo, hi = np.asarray(low, float), np.asarray(high, float)
    old = np.asarray(existing_X, float)
    if xval.ndim != 2 or len(xval) != len(residual):
        raise ValueError("validation rows and residuals must align")
    if old.ndim != 2 or old.shape[1] != xval.shape[1] or lo.shape != hi.shape:
        raise ValueError("existing points/bounds have the wrong shape")
    if np.any(hi <= lo) or n_samples < 0 or not np.all(np.isfinite(residual)):
        raise ValueError("invalid bounds, sample count or residuals")
    if n_samples == 0:
        return np.empty((0, xval.shape[1]), dtype=float)
    span = hi - lo
    zval = (xval - lo) / span
    zold = (old - lo) / span
    # Use at most the top 20% of independent validation residuals as centres.
    order = np.argsort(-residual, kind="stable")
    n_centers = min(len(order), max(4, int(np.ceil(len(order) * 0.20))))
    centers = zval[order[:n_centers]]
    rng = np.random.default_rng(int(seed))
    generated: list[np.ndarray] = []
    max_tries = max(100, n_samples * 100)
    for attempt in range(max_tries):
        center = centers[attempt % len(centers)]
        # Slightly broader exploration as attempts advance; never leave [0,1].
        scale = perturbation_fraction * (1.0 + 0.15 * (attempt // len(centers)))
        point = np.clip(center + rng.normal(0.0, scale, size=xval.shape[1]), 0.0, 1.0)
        pool = zold if not generated else np.vstack([zold, np.asarray(generated)])
        if len(pool) and float(np.min(np.linalg.norm(pool - point, axis=1))) < 1e-5:
            continue
        if len(generated) and float(np.min(np.linalg.norm(np.asarray(generated) - point, axis=1))) < 1e-5:
            continue
        generated.append(point)
        if len(generated) >= n_samples:
            break
    if len(generated) < n_samples:
        # Fill any shortage with deterministic uniform candidates; they are still
        # inside the verified domain and are explicitly counted in campaign meta.
        fill = rng.uniform(0.0, 1.0, size=(n_samples - len(generated), xval.shape[1]))
        generated.extend(list(fill))
    return lo + np.asarray(generated[:n_samples]) * span
