"""Regressor families, predeclared comparisons and calibration primitives.

Scikit-learn is an optional ``surrogate`` extra.  Models are trained per output
and per operating regime; this avoids pretending that a small three-regime data
set has learned a single universal response surface.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

MODEL_FAMILIES = (
    "constant", "ridge", "sparse_polynomial", "extra_trees",
    "hist_gradient_boosting", "gaussian_process_matern",
)
MODEL_COMPLEXITY = {name: i for i, name in enumerate(MODEL_FAMILIES)}
MODEL_CONFIG = {
    "constant": {"strategy": "mean"},
    "ridge": {"alpha": 1.0},
    "sparse_polynomial": {"degree": 2, "alpha": 1e-3, "l1_ratio": 0.8,
                           "max_iter": 20000},
    "extra_trees": {"n_estimators": 160, "min_samples_leaf": 2,
                     "max_features": 1.0, "n_jobs": 1},
    "hist_gradient_boosting": {"max_iter": 120, "learning_rate": 0.06,
                                "max_leaf_nodes": 15, "min_samples_leaf": 12,
                                "l2_regularization": 1.0},
    "gaussian_process_matern": {"kernel": "Constant * ARD-Matern(2.5) + fixed nugget",
                                "nu": 2.5, "initial_length_scale": 0.25,
                                "optimizer": "training marginal likelihood",
                                "n_restarts_optimizer": 0, "normalize_y": True},
}


def _sklearn():
    try:
        import sklearn
        return sklearn
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("surrogate models require `pip install -e '.[surrogate]'`") from exc


def _estimator(family: str, n_features: int, seed: int):
    _sklearn()
    from sklearn.dummy import DummyRegressor
    from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    from sklearn.linear_model import ElasticNet, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler

    if family == "constant":
        return DummyRegressor(strategy="mean")
    if family == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    if family == "sparse_polynomial":
        return make_pipeline(PolynomialFeatures(degree=2, include_bias=False),
                             StandardScaler(),
                             ElasticNet(alpha=1e-3, l1_ratio=0.8, max_iter=20000,
                                        selection="cyclic", random_state=int(seed)))
    if family == "extra_trees":
        return ExtraTreesRegressor(n_estimators=160, min_samples_leaf=2,
                                   max_features=1.0, n_jobs=1,
                                   random_state=int(seed))
    if family == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(max_iter=120, learning_rate=0.06,
                                             max_leaf_nodes=15,
                                             min_samples_leaf=12,
                                             l2_regularization=1.0,
                                             random_state=int(seed))
    if family == "gaussian_process_matern":
        # Features are normalized to the verified box before this is constructed;
        # the trainable ARD length-scales and amplitude are fit from training data.
        kernel = (ConstantKernel(1.0, (1e-2, 1e2))
                  * Matern(length_scale=np.full(n_features, 0.25),
                           length_scale_bounds=(0.025, 4.0), nu=2.5)
                  + WhiteKernel(noise_level=1e-8,
                                noise_level_bounds=(1e-10, 1e-3)))
        return GaussianProcessRegressor(kernel=kernel, alpha=1e-10,
                                        normalize_y=True, n_restarts_optimizer=0,
                                        random_state=int(seed), copy_X_train=True)
    raise ValueError(f"unknown surrogate family {family!r}")


@dataclass
class FittedRegressor:
    family: str
    estimator: Any
    feature_names: tuple[str, ...]
    target_name: str
    unit: str
    training_fingerprint: str
    n_training: int
    training_runtime_s: float
    target_scale: float
    model_version: str = "v19e-surrogate-model/1"
    conformal_radius: float | None = None
    conformal_coverage: float = 0.90
    validation_metrics: dict | None = None
    raw_uncertainty_note: str = "NOT_CALIBRATED"
    calibration_fingerprint: str | None = None
    calibration_points: int = 0

    def predict(self, X: np.ndarray, return_std: bool = True) -> tuple[np.ndarray, np.ndarray | None]:
        x = np.asarray(X, dtype=float)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        if x.ndim != 2 or x.shape[1] != len(self.feature_names):
            raise ValueError(f"expected n x {len(self.feature_names)} features; got {x.shape}")
        if not np.all(np.isfinite(x)):
            raise ValueError("prediction inputs must be finite")
        if self.family == "gaussian_process_matern" and return_std:
            mu, sigma = self.estimator.predict(x, return_std=True)
            return np.asarray(mu, float).reshape(-1), np.asarray(sigma, float).reshape(-1)
        mu = np.asarray(self.estimator.predict(x), float).reshape(-1)
        if self.family == "extra_trees" and return_std:
            # Tree spread is a disagreement diagnostic, not a calibrated posterior.
            tree_y = np.stack([t.predict(x) for t in self.estimator.estimators_], axis=0)
            return mu, np.std(tree_y, axis=0, ddof=1)
        return mu, None


def fit_regressor(family: str, X: np.ndarray, y: np.ndarray, *,
                  feature_names: Sequence[str], target_name: str, unit: str,
                  training_fingerprint: str, seed: int = 0) -> FittedRegressor:
    """Fit one target model; callers must already filter valid unique L4 rows."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).reshape(-1)
    if X.ndim != 2 or X.shape[0] != len(y):
        raise ValueError("X must be a 2-D matrix with one target per row")
    if X.shape[1] != len(tuple(feature_names)):
        raise ValueError("feature dimension does not match feature_names")
    if len(y) < 8:
        raise ValueError("at least 8 independent valid training rows are required")
    if not np.all(np.isfinite(X)) or not np.all(np.isfinite(y)):
        raise ValueError("training data must be finite; invalid rows must be filtered upstream")
    from threadpoolctl import threadpool_limits
    estimator = _estimator(family, X.shape[1], seed)
    t0 = time.perf_counter()
    with threadpool_limits(limits=1):
        estimator.fit(X, y)
    elapsed = time.perf_counter() - t0
    scale = float(np.std(y, ddof=0))
    if not np.isfinite(scale) or scale <= 1e-14:
        scale = max(float(np.ptp(y)), 1e-14)
    note = {
        "gaussian_process_matern": "GP predictive standard deviation; validate empirically",
        "extra_trees": "between-tree spread; disagreement diagnostic, not a posterior",
    }.get(family, "no native predictive variance; NOT_CALIBRATED until conformal calibration")
    return FittedRegressor(family, estimator, tuple(feature_names), target_name, unit,
                           training_fingerprint, len(y), elapsed, scale,
                           raw_uncertainty_note=note)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray, *,
                       train_y: np.ndarray | None = None) -> dict:
    """Metrics in output units plus scale-normalized and safe relative errors."""
    truth = np.asarray(y_true, dtype=float).reshape(-1)
    pred = np.asarray(y_pred, dtype=float).reshape(-1)
    if truth.shape != pred.shape or truth.size == 0:
        raise ValueError("truth/prediction must be nonempty vectors of equal size")
    if not np.all(np.isfinite(truth)) or not np.all(np.isfinite(pred)):
        raise ValueError("metrics require finite truth and prediction")
    err = pred - truth
    abs_err = np.abs(err)
    ref = np.asarray(train_y if train_y is not None else truth, dtype=float)
    scale = float(np.std(ref, ddof=0))
    if scale <= 1e-14:
        scale = max(float(np.ptp(ref)), 1e-14)
    floor = max(scale * 1e-6, 1e-12)
    rel_mask = np.abs(truth) > floor
    rel = abs_err[rel_mask] / np.abs(truth[rel_mask]) if np.any(rel_mask) else np.array([])
    return {
        "n": int(truth.size),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mae": float(np.mean(abs_err)),
        "max_absolute_error": float(abs_err.max()),
        "bias": float(np.mean(err)),
        "normalized_rmse_train_sd": float(np.sqrt(np.mean(err ** 2)) / scale),
        "normalization": "RMSE divided by training-target standard deviation (or training range if SD=0)",
        "relative_error_n": int(rel.size),
        "relative_error_median_pct": (float(np.median(rel) * 100.0) if rel.size else None),
        "relative_error_max_pct": (float(np.max(rel) * 100.0) if rel.size else None),
        "relative_error_exclusion_floor": floor,
        "residual_quantiles": {str(q): float(np.quantile(err, q))
                               for q in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)},
    }


def conformal_radius(y_true: np.ndarray, y_pred: np.ndarray, *, coverage: float = 0.90) -> float:
    """Finite-sample split-conformal absolute-residual radius.

    Marginal coverage requires exchangeability between the calibration and test
    draws; it does not promise conditional coverage in every parameter region.
    """
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage must lie strictly between zero and one")
    residual = np.abs(np.asarray(y_true, float).reshape(-1)
                      - np.asarray(y_pred, float).reshape(-1))
    residual = residual[np.isfinite(residual)]
    if residual.size == 0:
        raise ValueError("calibration set has no finite residuals")
    k = min(residual.size, int(math.ceil((residual.size + 1) * coverage)))
    return float(np.partition(residual, k - 1)[k - 1])


def interval_metrics(y_true: np.ndarray, y_pred: np.ndarray, *, radius: float,
                     nominal_coverage: float = 0.90) -> dict:
    truth = np.asarray(y_true, float).reshape(-1)
    pred = np.asarray(y_pred, float).reshape(-1)
    if radius < 0 or not np.isfinite(radius):
        raise ValueError("interval radius must be finite and nonnegative")
    covered = np.abs(truth - pred) <= radius
    coverage = float(np.mean(covered))
    return {
        "method": "split-conformal symmetric absolute-residual interval",
        "nominal_coverage": float(nominal_coverage),
        "empirical_coverage": coverage,
        "coverage_error": float(coverage - nominal_coverage),
        "coverage_calibration_error_abs": float(abs(coverage - nominal_coverage)),
        "radius_in_target_units": float(radius),
        "mean_interval_width": float(2.0 * radius),
        "n": int(truth.size),
    }


def raw_interval_coverage(y_true: np.ndarray, mean: np.ndarray,
                          std: np.ndarray | None, *, z: float = 1.6448536269514722) -> dict:
    """Measure nominal 90% GP/ensemble Gaussian intervals without calibration."""
    if std is None:
        return {"status": "NOT_AVAILABLE", "reason": "model family supplies no predictive spread"}
    y = np.asarray(y_true, float).reshape(-1)
    mu = np.asarray(mean, float).reshape(-1)
    sd = np.asarray(std, float).reshape(-1)
    sd = np.maximum(sd, 1e-14)
    covered = np.abs(y - mu) <= z * sd
    return {"status": "MEASURED_NOT_ASSUMED_CALIBRATED",
            "nominal_coverage": 0.90,
            "empirical_coverage": float(np.mean(covered)),
            "mean_interval_width": float(np.mean(2.0 * z * sd)),
            "mean_predictive_std": float(np.mean(sd)),
            "n": int(len(y))}


def grouped_kfold_indices(groups: Sequence[str], n_splits: int = 3) -> list[tuple[np.ndarray, np.ndarray]]:
    """Deterministic GroupKFold indices; one campaign/design family never splits."""
    g = np.asarray(groups, dtype=str)
    if g.ndim != 1 or len(g) < 2:
        raise ValueError("groups must be a one-dimensional vector")
    unique = np.unique(g)
    if len(unique) < 2:
        raise ValueError("at least two independent design families are required")
    if n_splits < 2 or n_splits > len(unique):
        raise ValueError("n_splits must be between 2 and the number of groups")
    from sklearn.model_selection import GroupKFold
    dummy = np.zeros((len(g), 1))
    return [(tr, te) for tr, te in GroupKFold(n_splits=n_splits).split(dummy, groups=g)]


def compare_families(X_train: np.ndarray, y_train: np.ndarray,
                     X_validation: np.ndarray, y_validation: np.ndarray, *,
                     feature_names: Sequence[str], target_name: str, unit: str,
                     training_fingerprint: str, seed: int = 0,
                     families: Sequence[str] = MODEL_FAMILIES) -> tuple[dict[str, FittedRegressor], dict[str, dict]]:
    """Fit all predeclared families; select later using validation RMSE only."""
    fitted: dict[str, FittedRegressor] = {}
    scores: dict[str, dict] = {}
    ytr = np.asarray(y_train, float).reshape(-1)
    yv = np.asarray(y_validation, float).reshape(-1)
    xv = np.asarray(X_validation, float)
    for i, family in enumerate(families):
        model = fit_regressor(family, X_train, ytr, feature_names=feature_names,
                              target_name=target_name, unit=unit,
                              training_fingerprint=training_fingerprint,
                              seed=seed + i)
        pred, std = model.predict(xv, return_std=True)
        scores[family] = regression_metrics(yv, pred, train_y=ytr)
        scores[family]["training_runtime_s"] = model.training_runtime_s
        scores[family]["raw_uncertainty"] = raw_interval_coverage(yv, pred, std)
        fitted[family] = model
    return fitted, scores


def select_family(scores: Mapping[str, Mapping[str, Any]]) -> str:
    """Predeclared choice: lowest independent-validation RMSE, ties favor simplicity."""
    eligible = [(float(v["rmse"]), MODEL_COMPLEXITY.get(k, 999), str(k))
                for k, v in scores.items() if np.isfinite(float(v.get("rmse", np.inf)))]
    if not eligible:
        raise ValueError("no family has a finite validation RMSE")
    return min(eligible)[2]
