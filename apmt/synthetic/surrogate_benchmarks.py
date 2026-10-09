"""Known-truth synthetic tests for the V1.9-E surrogate methods.

Results here validate algorithms only.  No function in this file represents the
perovskite/silicon tandem, and synthetic outputs are never merged into physics data.
"""
from __future__ import annotations

import numpy as np

from ..surrogate.adaptive import propose_near_errors
from ..surrogate.domain import detection_metrics, fit_support_profile
from ..surrogate.models import (MODEL_FAMILIES, compare_families, conformal_radius,
                               interval_metrics, regression_metrics, select_family)


def unit_lhs(n: int, d: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(int(seed))
    u = np.empty((n, d), float)
    for j in range(d):
        u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return u


def quadratic_interaction_surface(X: np.ndarray) -> np.ndarray:
    """Analytic two-variable response, maximum at (0.27, 0.64), xy term=2.0."""
    x = np.asarray(X, float)
    a, b = x[:, 0] - 0.27, x[:, 1] - 0.64
    return 1.0 - 15.0 * a * a - 8.0 * b * b + 2.0 * a * b


def narrow_bump_surface(X: np.ndarray) -> np.ndarray:
    """A smooth background plus a narrow interior feature for adaptive tests."""
    x = np.asarray(X, float)
    a, b = x[:, 0] - 0.73, x[:, 1] - 0.31
    base = 0.1 + 0.15 * x[:, 0] - 0.08 * x[:, 1]
    bump = 0.8 * np.exp(-0.5 * ((a / 0.055) ** 2 + (b / 0.075) ** 2))
    return base + bump


def run_surrogate_synthetic_benchmarks(seed: int = 20261009) -> dict:
    """Run predictive/optimum/interaction/heteroscedastic/OOD method checks."""
    # Exact analytic surface: 128 training + independent model-selection and final
    # designs.  The test design is not used to select a model or hyperparameters.
    xtr = unit_lhs(128, 2, seed)
    xval = unit_lhs(48, 2, seed + 1)
    xcal = unit_lhs(64, 2, seed + 2)
    xtest = unit_lhs(256, 2, seed + 3)
    ytr = quadratic_interaction_surface(xtr)
    yval = quadratic_interaction_surface(xval)
    ycal = quadratic_interaction_surface(xcal)
    ytest = quadratic_interaction_surface(xtest)
    train_fp = "synthetic-analytic-" + str(seed)
    fitted, val_scores = compare_families(
        xtr, ytr, xval, yval, feature_names=("x1", "x2"), target_name="synthetic_y",
        unit="1", training_fingerprint=train_fp, seed=seed)
    selected = select_family(val_scores)
    chosen = fitted[selected]
    pred, _ = chosen.predict(xtest, return_std=True)
    test_metrics = regression_metrics(ytest, pred, train_y=ytr)
    analytic_cal_prediction, _ = chosen.predict(xcal, return_std=False)
    conformal_q = conformal_radius(ycal, analytic_cal_prediction, coverage=0.90)
    conformal_test = interval_metrics(ytest, pred, radius=conformal_q)

    # Grid-only recovery is compared with a separate analytic truth; values are
    # not forced into any fit or model prior.
    grid_axis = np.linspace(0.0, 1.0, 401)
    gx, gy = np.meshgrid(grid_axis, grid_axis, indexing="ij")
    grid = np.column_stack([gx.ravel(), gy.ravel()])
    grid_y = quadratic_interaction_surface(grid)
    true_best = grid[int(np.argmax(grid_y))]
    grid_pred, _ = chosen.predict(grid, return_std=False)
    pred_best = grid[int(np.argmax(grid_pred))]

    # Check recovery of the exact interaction coefficient with the fixed sparse
    # quadratic family, on its predicted cross-difference (not on the final test).
    from sklearn.preprocessing import PolynomialFeatures
    poly = fitted["sparse_polynomial"].estimator
    coef_model = poly[-1]
    # Evaluate the learned polynomial at symmetric corners; cross-difference / 4
    # is the xy coefficient when degree-2 terms are represented in raw x units.
    corners = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    corner_pred, _ = fitted["sparse_polynomial"].predict(corners, return_std=False)
    cross_difference = float(corner_pred[3] - corner_pred[2] - corner_pred[1] + corner_pred[0])
    true_cross_difference = float(quadratic_interaction_surface(corners)[3]
                                  - quadratic_interaction_surface(corners)[2]
                                  - quadratic_interaction_surface(corners)[1]
                                  + quadratic_interaction_surface(corners)[0])

    # Heteroscedastic synthetic data: noise increases with x1.  A held-out
    # calibration set yields a split-conformal interval, checked once on a fresh
    # test set and reported separately for low/high-noise bins.
    def noisy_draw(X: np.ndarray, draw_seed: int) -> np.ndarray:
        x = np.asarray(X, float)
        rng = np.random.default_rng(draw_seed)
        sd = 0.025 + 0.18 * x[:, 0]
        return quadratic_interaction_surface(x) + rng.normal(0.0, sd)
    xntr = unit_lhs(192, 2, seed + 10)
    xnsel = unit_lhs(64, 2, seed + 11)
    xncal = unit_lhs(96, 2, seed + 12)
    xntest = unit_lhs(384, 2, seed + 13)
    yntr = noisy_draw(xntr, seed + 20)
    ynsel = noisy_draw(xnsel, seed + 21)
    yncal = noisy_draw(xncal, seed + 22)
    yntest = noisy_draw(xntest, seed + 23)
    noisy_fit, noisy_val_scores = compare_families(
        xntr, yntr, xnsel, ynsel, feature_names=("x1", "x2"), target_name="heteroscedastic_y",
        unit="1", training_fingerprint=f"synthetic-noisy-{seed}", seed=seed + 30)
    noisy_name = select_family(noisy_val_scores)
    noisy_model = noisy_fit[noisy_name]
    noisy_cal_pred, noisy_cal_std = noisy_model.predict(xncal, return_std=True)
    noisy_test_pred, noisy_test_std = noisy_model.predict(xntest, return_std=True)
    q = conformal_radius(yncal, noisy_cal_pred, coverage=0.90)
    all_interval = interval_metrics(yntest, noisy_test_pred, radius=q)
    bins = []
    for name, mask in (("low_noise_x1<0.5", xntest[:, 0] < 0.5),
                       ("high_noise_x1>=0.5", xntest[:, 0] >= 0.5)):
        m = interval_metrics(yntest[mask], noisy_test_pred[mask], radius=q)
        bins.append({"region": name, **m})
    raw_gp = {"status": "not the chosen family"}
    if noisy_name == "gaussian_process_matern":
        raw_gp = {"selected_family": noisy_name,
                  **__import__("apmt.surrogate.models", fromlist=["raw_interval_coverage"])
                  .raw_interval_coverage(yntest, noisy_test_pred, noisy_test_std)}

    # Deliberately withheld upper-right region.  Threshold calibration uses one
    # independent half; detection is evaluated on a disjoint half.
    x_support_train = unit_lhs(160, 2, seed + 40)
    x_support_train = x_support_train[~((x_support_train[:, 0] > 0.82)
                                        & (x_support_train[:, 1] > 0.82))]
    x_in_cal = unit_lhs(64, 2, seed + 41)
    x_in_test = unit_lhs(128, 2, seed + 42)
    # Independent randomized calibration/test samples drawn from the same
    # withheld corner.  A diagonal split would confound threshold transfer with
    # location within the OOD region.  Labels are support-only, never regression.
    x_ood_cal = 0.82 + 0.18 * unit_lhs(24, 2, seed + 43)
    x_ood_test = 0.82 + 0.18 * unit_lhs(24, 2, seed + 44)
    profile = fit_support_profile(
        feature_names=("x1", "x2"), low=[0, 0], high=[1, 1],
        training_X=x_support_train, in_domain_calibration_X=x_in_cal,
        withheld_region_calibration_X=x_ood_cal,
        max_false_positive_rate=0.10)
    support_scores = detection_metrics(profile, x_in_test, x_ood_test)

    # Invalid-region guard: a known-truth surface is defined only where
    # x1+x2<=1.65. The fixture gives invalid rows a conspicuous penalty solely to
    # prove that status filtering excludes the label; the regressor is fit only
    # on valid rows and the invalid region is never inferred from predictions.
    invalid_train_X = unit_lhs(512, 2, seed + 45)
    invalid_train_truth = quadratic_interaction_surface(invalid_train_X)
    invalid_train_mask = invalid_train_X[:, 0] + invalid_train_X[:, 1] <= 1.65
    penalty_label = -999.0
    raw_invalid_labels = invalid_train_truth.copy()
    raw_invalid_labels[~invalid_train_mask] = penalty_label
    invalid_fit = __import__("apmt.surrogate.models", fromlist=["fit_regressor"]).fit_regressor(
        "ridge", invalid_train_X[invalid_train_mask], raw_invalid_labels[invalid_train_mask],
        feature_names=("x1", "x2"), target_name="valid_region_y", unit="1",
        training_fingerprint=f"synthetic-valid-only-{seed}", seed=seed + 46)
    x_valid_holdout_all = unit_lhs(256, 2, seed + 47)
    x_valid_holdout = x_valid_holdout_all[
        x_valid_holdout_all[:, 0] + x_valid_holdout_all[:, 1] <= 1.65]
    y_valid_holdout = quadratic_interaction_surface(x_valid_holdout)
    pred_valid_holdout, _ = invalid_fit.predict(x_valid_holdout, return_std=False)
    invalid_probe_u = unit_lhs(32, 2, seed + 48)
    invalid_probe_x = np.column_stack([
        0.85 + 0.15 * invalid_probe_u[:, 0],
        np.minimum(1.0, 1.66 - (0.85 + 0.15 * invalid_probe_u[:, 0])
                   + 0.34 * invalid_probe_u[:, 1])])
    invalid_probe_mask = invalid_probe_x[:, 0] + invalid_probe_x[:, 1] > 1.65
    invalid_region_guard = {
        "label": "SYNTHETIC METHOD VALIDATION ONLY; NOT DEVICE EVIDENCE",
        "synthetic_validity_rule": "x1+x2<=1.65; complement is INVALID_PHYSICS inside the [0,1]^2 box",
        "raw_training_candidates": int(len(invalid_train_X)),
        "valid_training_rows": int(invalid_train_mask.sum()),
        "invalid_physics_rows_rejected": int((~invalid_train_mask).sum()),
        "invalid_fixture_uses_extreme_penalty_label_only_to_test_filtering": True,
        "penalty_label_in_regression_training": bool(
            np.any(raw_invalid_labels[invalid_train_mask] == penalty_label)),
        "model_training_fingerprint": invalid_fit.training_fingerprint,
        "valid_holdout_metrics": regression_metrics(
            y_valid_holdout, pred_valid_holdout,
            train_y=raw_invalid_labels[invalid_train_mask]),
        "invalid_probe_count": int(len(invalid_probe_x)),
        "invalid_probe_rule_passed": bool(np.all(invalid_probe_mask)),
        "invalid_region_is_never_predicted_or_scored": True,
        "validity_source": "explicit known synthetic invariant, never a learned classifier",
    }

    # Adaptive sampling diagnostic on the narrow bump, independent validation and
    # holdout. New points are chosen near validation residual maxima, never copied.
    xa_train = unit_lhs(48, 2, seed + 50)
    xa_val = unit_lhs(96, 2, seed + 51)
    xa_test = unit_lhs(256, 2, seed + 52)
    ya_train, ya_val, ya_test = (narrow_bump_surface(xa_train),
                                 narrow_bump_surface(xa_val),
                                 narrow_bump_surface(xa_test))
    adaptive_initial, _ = compare_families(
        xa_train, ya_train, xa_val, ya_val, feature_names=("x1", "x2"),
        target_name="narrow_bump", unit="1", training_fingerprint=f"adaptive-{seed}",
        seed=seed + 60, families=("ridge", "extra_trees", "gaussian_process_matern"))
    adaptive_family = select_family({k: regression_metrics(ya_val,
        v.predict(xa_val, return_std=False)[0], train_y=ya_train) for k, v in adaptive_initial.items()})
    before_model = adaptive_initial[adaptive_family]
    before_pred, _ = before_model.predict(xa_test, return_std=False)
    before = regression_metrics(ya_test, before_pred, train_y=ya_train)
    adaptive_points = propose_near_errors(
        xa_val, ya_val - before_model.predict(xa_val, return_std=False)[0],
        low=np.zeros(2), high=np.ones(2), existing_X=np.vstack([xa_train, xa_val]),
        n_samples=24, seed=seed + 61, perturbation_fraction=0.06)
    xa_aug = np.vstack([xa_train, adaptive_points])
    ya_aug = np.concatenate([ya_train, narrow_bump_surface(adaptive_points)])
    after_model = __import__("apmt.surrogate.models", fromlist=["fit_regressor"]).fit_regressor(
        adaptive_family, xa_aug, ya_aug, feature_names=("x1", "x2"),
        target_name="narrow_bump", unit="1", training_fingerprint=f"adaptive-aug-{seed}",
        seed=seed + 62)
    after_pred, _ = after_model.predict(xa_test, return_std=False)
    after = regression_metrics(ya_test, after_pred, train_y=ya_aug)

    return {
        "label": "SYNTHETIC METHOD VALIDATION ONLY; NOT DEVICE EVIDENCE",
        "seed": int(seed), "analytic_surface": {
            "truth": "1 - 15(x1-0.27)^2 - 8(x2-0.64)^2 + 2(x1-0.27)(x2-0.64)",
            "known_optimum": [0.27, 0.64], "known_interaction_coefficient": 2.0,
            "selected_family_by_validation": selected,
            "validation_scores": val_scores,
            "final_holdout_metrics": test_metrics,
            "selection_n": len(xval), "calibration_n": len(xcal),
            "calibration_metrics": regression_metrics(ycal, analytic_cal_prediction,
                                                       train_y=ytr),
            "conformal_90_final_holdout": conformal_test,
            "optimum_grid_truth": true_best.tolist(),
            "optimum_grid_prediction": pred_best.tolist(),
            "optimum_coordinate_error": float(np.linalg.norm(pred_best - true_best)),
            "interaction_cross_difference_truth": true_cross_difference,
            "interaction_cross_difference_predicted": cross_difference,
            "interaction_cross_difference_absolute_error": abs(cross_difference - true_cross_difference),
        },
        "heteroscedastic_noise": {
            "noise_sd_formula": "0.025 + 0.18*x1",
            "selected_family": noisy_name,
            "validation_scores": noisy_val_scores,
            "model_selection_n": len(xnsel), "calibration_n": len(xncal),
            "calibration_metrics": regression_metrics(yncal, noisy_cal_pred,
                                                       train_y=yntr),
            "split_conformal_90_final_holdout": all_interval,
            "coverage_by_noise_region": bins,
            "raw_uncertainty": raw_gp,
            "interpretation": "marginal split-conformal interval; conditional coverage is separately shown and not guaranteed",
        },
        "withheld_region_detection": support_scores,
        "invalid_region_guard": invalid_region_guard,
        "adaptive_sampling": {
            "surface": "smooth background + narrow Gaussian bump centered near (0.73, 0.31)",
            "selected_family": adaptive_family,
            "n_train_before": len(xa_train), "n_adaptive_physics_free_samples": len(adaptive_points),
            "holdout_before": before, "holdout_after": after,
            "rmse_reduction_fraction": float((before["rmse"] - after["rmse"])
                                               / max(before["rmse"], 1e-14)),
            "test_set_not_used_for_sampling": True,
        },
        "ishigami_guard": {
            "small_sample_pairwise_floor": 0.127726,
            "false_pairs_at_n96_are_not_ground_truth": True,
            "source": "V1.9-D estimator_validation; pairwise interaction targets only used above calibrated floor",
        },
    }
