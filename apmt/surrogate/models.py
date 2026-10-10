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
        # FittedRegressor applies and stores its linear feature transform before
        # estimator fit/predict; campaign fits use the predeclared verified box.
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
    model_version: str = "v19e-surrogate-model/3"
    conformal_radius: float | None = None
    conformal_coverage: float = 0.90
    validation_metrics: dict | None = None
    raw_uncertainty_note: str = "NOT_CALIBRATED"
    calibration_fingerprint: str | None = None
    calibration_points: int = 0
    feature_low: tuple[float, ...] = ()
    feature_high: tuple[float, ...] = ()
    feature_transform: str = "training_minmax_linear_v1"

    def _transform(self, X: np.ndarray) -> np.ndarray:
        x = np.asarray(X, dtype=float)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        if x.ndim != 2 or x.shape[1] != len(self.feature_names):
            raise ValueError(f"expected n x {len(self.feature_names)} features; got {x.shape}")
        if not np.all(np.isfinite(x)):
            raise ValueError("prediction inputs must be finite")
        if self.feature_transform not in ("verified_box_linear_v1", "training_minmax_linear_v1"):
            raise ValueError(f"unsupported serialized feature transform {self.feature_transform!r}")
        low = np.asarray(self.feature_low, dtype=float)
        high = np.asarray(self.feature_high, dtype=float)
        if low.shape != (len(self.feature_names),) or high.shape != low.shape:
            raise ValueError("serialized model feature-transform metadata is incomplete")
        span = high - low
        if not np.all(np.isfinite(low)) or not np.all(np.isfinite(high)) or np.any(span <= 0):
            raise ValueError("serialized model feature-transform bounds are invalid")
        transformed = (x - low) / span
        if not np.all(np.isfinite(transformed)):
            raise ValueError("transformed prediction inputs must be finite")
        return transformed

    def predict(self, X: np.ndarray, return_std: bool = True) -> tuple[np.ndarray, np.ndarray | None]:
        x = self._transform(X)
        if self.family == "gaussian_process_matern" and return_std:
            mu, sigma = self.estimator.predict(x, return_std=True)
            mean = np.asarray(mu, float).reshape(-1)
            std = np.asarray(sigma, float).reshape(-1)
            if not np.all(np.isfinite(mean)) or not np.all(np.isfinite(std)) or np.any(std < 0):
                raise ValueError("model returned non-finite predictions or invalid predictive spread")
            return mean, std
        mu = np.asarray(self.estimator.predict(x), float).reshape(-1)
        if not np.all(np.isfinite(mu)):
            raise ValueError("model returned non-finite predictions")
        if self.family == "extra_trees" and return_std:
            # Tree spread is a disagreement diagnostic, not a calibrated posterior.
            tree_y = np.stack([t.predict(x) for t in self.estimator.estimators_], axis=0)
            std = np.std(tree_y, axis=0, ddof=1)
            if not np.all(np.isfinite(std)) or np.any(std < 0):
                raise ValueError("tree ensemble returned invalid predictive spread")
            return mu, std
        return mu, None


def fit_regressor(family: str, X: np.ndarray, y: np.ndarray, *,
                  feature_names: Sequence[str], target_name: str, unit: str,
                  training_fingerprint: str, seed: int = 0,
                  feature_low: Sequence[float] | None = None,
                  feature_high: Sequence[float] | None = None) -> FittedRegressor:
    """Fit on verified-box coordinates, or fold-local training min/max if absent.

    The transform is stored on the fitted model and repeated by ``predict``.  When
    cross-validation supplies predeclared verified bounds, no held-out fold data
    are used to estimate preprocessing.  Otherwise min/max are fitted using only
    the X rows passed to this call.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).reshape(-1)
    names = tuple(feature_names)
    if X.ndim != 2 or X.shape[0] != len(y):
        raise ValueError("X must be a 2-D matrix with one target per row")
    if X.shape[1] != len(names) or len(set(names)) != len(names):
        raise ValueError("feature dimension must match unique feature_names")
    if len(y) < 8:
        raise ValueError("at least 8 independent valid training rows are required")
    if not np.all(np.isfinite(X)) or not np.all(np.isfinite(y)):
        raise ValueError("training data must be finite; invalid rows must be filtered upstream")
    if (feature_low is None) != (feature_high is None):
        raise ValueError("feature_low and feature_high must be supplied together")
    if feature_low is None:
        low = np.min(X, axis=0)
        high = np.max(X, axis=0)
        span = high - low
        constant = span <= np.finfo(float).eps * np.maximum(1.0, np.abs(low))
        padding = np.maximum(1.0, np.abs(low)) * 0.5
        low = np.where(constant, low - padding, low)
        high = np.where(constant, high + padding, high)
        transform_name = "training_minmax_linear_v1"
    else:
        low = np.asarray(feature_low, dtype=float).reshape(-1)
        high = np.asarray(feature_high, dtype=float).reshape(-1)
        transform_name = "verified_box_linear_v1"
    if (low.shape != (X.shape[1],) or high.shape != low.shape
            or not np.all(np.isfinite(low)) or not np.all(np.isfinite(high))
            or np.any(high <= low)):
        raise ValueError("feature transform bounds must be finite and have positive width")
    if feature_low is not None:
        tol = 1e-12 * np.maximum(1.0, np.maximum(np.abs(low), np.abs(high)))
        if np.any(X < low - tol) or np.any(X > high + tol):
            raise ValueError("training features fall outside the supplied verified box")
    X_model = (X - low) / (high - low)
    if not np.all(np.isfinite(X_model)):
        raise ValueError("transformed training features must be finite")
    from threadpoolctl import threadpool_limits
    estimator = _estimator(family, X.shape[1], seed)
    t0 = time.perf_counter()
    with threadpool_limits(limits=1):
        estimator.fit(X_model, y)
    elapsed = time.perf_counter() - t0
    scale = float(np.std(y, ddof=0))
    if not np.isfinite(scale) or scale <= 1e-14:
        scale = max(float(np.ptp(y)), 1e-14)
    note = {
        "gaussian_process_matern": "GP predictive standard deviation; validate empirically",
        "extra_trees": "between-tree spread; disagreement diagnostic, not a posterior",
    }.get(family, "no native predictive variance; NOT_CALIBRATED until conformal calibration")
    return FittedRegressor(
        family=family, estimator=estimator, feature_names=names,
        target_name=target_name, unit=unit, training_fingerprint=training_fingerprint,
        n_training=len(y), training_runtime_s=elapsed, target_scale=scale,
        raw_uncertainty_note=note, feature_low=tuple(float(v) for v in low),
        feature_high=tuple(float(v) for v in high), feature_transform=transform_name)


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


def minimum_calibration_samples(coverage: float = 0.90) -> int:
    """Minimum n for a finite split-conformal order statistic at ``coverage``."""
    if not np.isfinite(coverage) or not 0.0 < coverage < 1.0:
        raise ValueError("coverage must lie strictly between zero and one")
    from fractions import Fraction
    exact = Fraction(str(float(coverage)))
    return math.ceil(exact / (1 - exact))


def _finite_vector(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim > 2 or (array.ndim == 2 and 1 not in array.shape):
        raise ValueError(f"{name} must be a vector")
    vector = array.reshape(-1)
    if vector.size == 0 or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a nonempty finite vector")
    return vector


def conformal_radius(y_true: np.ndarray, y_pred: np.ndarray, *, coverage: float = 0.90) -> float:
    """Finite-sample split-conformal absolute-residual radius.

    Marginal coverage requires exchangeability between calibration and test
    draws; it does not promise conditional coverage by parameter region. If the
    requested order statistic is n+1, no finite radius can provide the stated
    guarantee, so insufficient calibration data are rejected rather than clamped.
    """
    required = minimum_calibration_samples(coverage)
    truth = _finite_vector(y_true, "calibration truth")
    pred = _finite_vector(y_pred, "calibration prediction")
    if truth.shape != pred.shape:
        raise ValueError("calibration truth and prediction shapes must match")
    if len(truth) < required:
        raise ValueError(f"coverage {coverage:g} requires at least {required} calibration points; got {len(truth)}")
    residual = np.abs(truth - pred)
    from fractions import Fraction
    exact_coverage = Fraction(str(float(coverage)))
    k = math.ceil((len(residual) + 1) * exact_coverage)
    if k > len(residual):
        raise ValueError("requested conformal order statistic is not finite for this sample size")
    return float(np.partition(residual, k - 1)[k - 1])


def interval_metrics(y_true: np.ndarray, y_pred: np.ndarray, *, radius: float,
                     nominal_coverage: float = 0.90) -> dict:
    truth = _finite_vector(y_true, "interval truth")
    pred = _finite_vector(y_pred, "interval prediction")
    if truth.shape != pred.shape:
        raise ValueError("interval truth and prediction shapes must match")
    if not np.isfinite(nominal_coverage) or not 0.0 < nominal_coverage < 1.0:
        raise ValueError("nominal_coverage must lie strictly between zero and one")
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
    y = _finite_vector(y_true, "uncertainty truth")
    mu = _finite_vector(mean, "uncertainty mean")
    sd = _finite_vector(std, "predictive standard deviation")
    if y.shape != mu.shape or y.shape != sd.shape:
        raise ValueError("uncertainty truth, mean and standard deviation shapes must match")
    if not np.isfinite(z) or z <= 0 or np.any(sd < 0):
        raise ValueError("uncertainty multiplier must be positive and spreads nonnegative")
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
                     families: Sequence[str] = MODEL_FAMILIES,
                     feature_low: Sequence[float] | None = None,
                     feature_high: Sequence[float] | None = None) -> tuple[dict[str, FittedRegressor], dict[str, dict]]:
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
                              seed=seed + i, feature_low=feature_low,
                              feature_high=feature_high)
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
