"""APMT V1.9 — digital-twin calibration against DIGITIZED evidence + diagnostics.

What this does (and does not do)
--------------------------------
* It fits a small, explicitly named set of *optical/collection* parameters of the
  twin to the committed, digitized Fig. S32 EQE branches of the certified
  champion (apmt.experiments.evidence).
* It reports residuals, per-curve RMSE and the resulting Jph against the
  source-reported labels.
* It is a fit to DIGITIZED figure data. The result is therefore classified
  MODEL-FIT-TO-DIGITIZED-EVIDENCE everywhere it appears, and it never counts as
  experimental validation of anything.
* It computes honest identifiability diagnostics (Jacobian SVD, condition
  number, correlation matrix, boundary hits, profile likelihood) which feed gate
  G8 -- the historical blocker.

The fit uses a robust loss (soft-L1) because digitized curves contain
outlier points at legend/text overlaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np

from ..core.numerics import array_sha256
from ..optics.stack import solve_tandem_optics
from ..params.registry import ParamSet, sample_bounds, spec
from ..spectra.reference import reference
from ..validation.identifiability import IdentifiabilityEvidence

DEFAULT_FIT_PARAMETERS = (
    "arc_thickness_nm",
    "parasitic_layer_thickness_nm",
    "perovskite_thickness_nm",
    "collection_efficiency_top",
    "collection_efficiency_bottom",
    "silicon_light_trapping",
)


@dataclass(frozen=True)
class CalibrationResult:
    parameter_names: tuple
    fitted_values: tuple
    initial_values: tuple
    lower_bounds: tuple
    upper_bounds: tuple
    objective: float
    rmse_top: float
    rmse_bottom: float
    jph_top_ma_cm2: float
    jph_bottom_ma_cm2: float
    identifiability: IdentifiabilityEvidence
    n_data_points: int
    converged: bool
    message: str
    target_fingerprint: str
    model_form: str
    category: str = "MODEL-FIT-TO-DIGITIZED-EVIDENCE"
    residuals: dict = field(default_factory=dict)

    def paramset(self, base: Optional[ParamSet] = None) -> ParamSet:
        base = base or ParamSet.defaults()
        return base.with_mapping(dict(zip(self.parameter_names, self.fitted_values)))

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "model_form": self.model_form,
            "parameter_names": list(self.parameter_names),
            "initial_values": [float(v) for v in self.initial_values],
            "fitted_values": [float(v) for v in self.fitted_values],
            "lower_bounds": [float(v) for v in self.lower_bounds],
            "upper_bounds": [float(v) for v in self.upper_bounds],
            "objective": float(self.objective),
            "n_data_points": int(self.n_data_points),
            "rmse_top": float(self.rmse_top),
            "rmse_bottom": float(self.rmse_bottom),
            "jph_top_ma_cm2": float(self.jph_top_ma_cm2),
            "jph_bottom_ma_cm2": float(self.jph_bottom_ma_cm2),
            "converged": bool(self.converged),
            "message": self.message,
            "target_fingerprint": self.target_fingerprint,
            "identifiability": self.identifiability.to_dict(),
            "residuals": {k: (float(v) if isinstance(v, (int, float)) else v)
                          for k, v in self.residuals.items()},
        }


def _model_curves(ps: ParamSet, model_form: str, wl_top: np.ndarray,
                  wl_bottom: np.ndarray, spectrum=None):
    """Evaluate the twin's EQE on the two digitized wavelength grids."""
    opt = solve_tandem_optics(ps, model_form=model_form, spectrum=spectrum)
    eqe_top = np.interp(wl_top, opt.wavelength_nm, opt.eqe_top, left=0.0, right=0.0)
    eqe_bottom = np.interp(wl_bottom, opt.wavelength_nm, opt.eqe_bottom, left=0.0, right=0.0)
    return opt, eqe_top, eqe_bottom


def _residual_vector(ps_vec, names, base_ps, model_form, targets, weight_bottom=1.0):
    try:
        ps = base_ps.with_mapping({n: float(v) for n, v in zip(names, ps_vec)})
    except ValueError:
        return np.full(_residual_size(targets), 1.0)
    opt, eqe_top, eqe_bottom = _model_curves(
        ps, model_form, targets["wavelength_top_nm"], targets["wavelength_bottom_nm"],
        spectrum=targets.get("spectrum"))
    r_top = eqe_top - targets["eqe_top"]
    r_bottom = (eqe_bottom - targets["eqe_bottom"]) * weight_bottom
    return np.concatenate([r_top, r_bottom])


def _residual_size(targets) -> int:
    return int(targets["eqe_top"].size + targets["eqe_bottom"].size)


def calibrate_twin(targets: Optional[dict] = None,
                   parameter_names: Sequence[str] = DEFAULT_FIT_PARAMETERS,
                   model_form: str = "IQE-M1",
                   base_ps: Optional[ParamSet] = None,
                   loss: str = "soft_l1",
                   max_nfev: int = 200,
                   profile: bool = True) -> CalibrationResult:
    """Fit the twin's optical/collection parameters to digitized EQE evidence."""
    from scipy.optimize import least_squares

    from ..experiments.evidence import calibration_targets
    targets = targets or calibration_targets("hzb_M1")
    base_ps = base_ps or ParamSet.defaults()
    names = tuple(parameter_names)
    x0 = np.array([base_ps[n] for n in names], dtype=float)
    lo, hi = sample_bounds(names)
    # guard against an initial point outside the (rounded) bounds
    x0 = np.clip(x0, lo, hi)

    def fun(x):
        return _residual_vector(x, names, base_ps, model_form, targets)

    sol = least_squares(fun, x0, bounds=(lo, hi), loss=loss, max_nfev=max_nfev,
                        xtol=1e-12, ftol=1e-12, gtol=1e-12)
    fitted = np.clip(sol.x, lo, hi)
    ps_fit = base_ps.with_mapping(dict(zip(names, fitted)))

    # --- residuals ---------------------------------------------------------
    opt, eqe_top, eqe_bottom = _model_curves(
        ps_fit, model_form, targets["wavelength_top_nm"],
        targets["wavelength_bottom_nm"], targets.get("spectrum"))
    r_top = eqe_top - targets["eqe_top"]
    r_bottom = eqe_bottom - targets["eqe_bottom"]
    rmse_top = float(np.sqrt(np.mean(r_top ** 2)))
    rmse_bottom = float(np.sqrt(np.mean(r_bottom ** 2)))

    # --- identifiability ---------------------------------------------------
    J = _jacobian(fun, fitted, lo, hi)
    ident = _identifiability(J, names, fitted, lo, hi, sol.fun,
                             float(np.sqrt(np.mean(sol.fun ** 2))), profile, fun)

    sp = reference()
    wl_m = opt.wavelength_nm
    return CalibrationResult(
        parameter_names=names, fitted_values=tuple(fitted),
        initial_values=tuple(x0), lower_bounds=tuple(lo), upper_bounds=tuple(hi),
        objective=float(0.5 * np.sum(sol.fun ** 2)),
        rmse_top=rmse_top, rmse_bottom=rmse_bottom,
        jph_top_ma_cm2=sp.eqe_current(opt.eqe_top, wl_m, 300, 1250),
        jph_bottom_ma_cm2=sp.eqe_current(opt.eqe_bottom, wl_m, 300, 1250),
        identifiability=ident, n_data_points=_residual_size(targets),
        converged=bool(sol.success), message=str(sol.message),
        target_fingerprint=array_sha256(targets["eqe_top"], targets["eqe_bottom"]),
        model_form=model_form,
        residuals={
            "rmse_top_pct_points": rmse_top * 100,
            "rmse_bottom_pct_points": rmse_bottom * 100,
            "max_abs_top": float(np.max(np.abs(r_top))),
            "max_abs_bottom": float(np.max(np.abs(r_bottom))),
            "bias_top": float(np.mean(r_top)),
            "bias_bottom": float(np.mean(r_bottom)),
        })


def _jacobian(fun, x: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Central-difference Jacobian of the residual vector at ``x``."""
    J = np.zeros((_n_res(fun, x), x.size))
    for i in range(x.size):
        step = max(1e-6 * max(abs(x[i]), 1.0), 1e-8)
        xp = x.copy(); xp[i] = min(x[i] + step, hi[i])
        xm = x.copy(); xm[i] = max(x[i] - step, lo[i])
        if xp[i] == xm[i]:
            continue
        J[:, i] = (fun(xp) - fun(xm)) / (xp[i] - xm[i])
    return J


def _n_res(fun, x) -> int:
    return int(np.asarray(fun(x)).size)


def _identifiability(J: np.ndarray, names: tuple, x: np.ndarray, lo: np.ndarray,
                     hi: np.ndarray, residuals: np.ndarray, rmse: float,
                     profile: bool, fun) -> IdentifiabilityEvidence:
    """SVD/correlation diagnostics, plus a coarse profile likelihood."""
    U, s, Vt = np.linalg.svd(J, full_matrices=False)
    cond = float(s[0] / s[-1]) if s.size and s[-1] > 0 else float("inf")
    # parameter correlation from the covariance approximation (J^T J)^-1
    try:
        cov = np.linalg.pinv(J.T @ J)
        d = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
        corr = cov / np.outer(d, d)
        np.fill_diagonal(corr, 1.0)
    except np.linalg.LinAlgError:  # pragma: no cover - defensive
        corr = None

    tol = 1e-6 * np.maximum(np.abs(hi - lo), 1.0)
    hits = int(np.sum((np.abs(x - lo) < tol) | (np.abs(x - hi) < tol)))

    prof = {}
    if profile:
        base_rss = float(np.sum(residuals ** 2))
        for i, name in enumerate(names):
            grid = np.linspace(lo[i], hi[i], 21)
            rss = []
            for v in grid:
                xv = x.copy(); xv[i] = v
                r = fun(xv)
                rss.append(float(np.sum(r ** 2)))
            prof[name] = {"grid": grid.tolist(), "rss": rss,
                          "flat": bool(np.min(rss) >= base_rss * 0.999)}
    return IdentifiabilityEvidence(
        condition_number=cond, boundary_hits=hits, n_parameters=len(names),
        n_data_points=int(residuals.size), singular_values=tuple(s.tolist()),
        parameter_names=names, correlation_matrix=corr,
        profile_likelihood=prof, objective_value=float(0.5*np.sum(residuals**2)),
        residual_rmse=rmse,
        notes=("Jacobian from central differences of the residual vector; "
               "correlations from the pseudo-inverse of J^T J; profile likelihood "
               "scans each parameter on a 21-point grid with the others fixed"))


def evaluate_twin(ps: ParamSet, model_form: str = "IQE-M1") -> dict:
    """Evaluate the calibrated twin and compare with the digitized targets."""
    from ..experiments.evidence import calibration_targets
    t = calibration_targets("hzb_M1")
    opt, eqe_top, eqe_bottom = _model_curves(ps, model_form, t["wavelength_top_nm"],
                                             t["wavelength_bottom_nm"], None)
    sp = reference()
    return {
        "jph_top_ma_cm2": sp.eqe_current(opt.eqe_top, opt.wavelength_nm, 300, 1250),
        "jph_bottom_ma_cm2": sp.eqe_current(opt.eqe_bottom, opt.wavelength_nm, 300, 1250),
        "rmse_top_vs_digitized": float(np.sqrt(np.mean((eqe_top - t["eqe_top"]) ** 2))),
        "rmse_bottom_vs_digitized": float(np.sqrt(np.mean((eqe_bottom - t["eqe_bottom"]) ** 2))),
        "label_top_ma_cm2": t["jph_top_label_ma_cm2"],
        "label_bottom_ma_cm2": t["jph_bottom_label_ma_cm2"],
        "digitized_top_ma_cm2": t["jph_top_digitized_ma_cm2"],
        "digitized_bottom_ma_cm2": t["jph_bottom_digitized_ma_cm2"],
        "model_form": model_form,
        "category": "MODEL-COMPARISON-AGAINST-DIGITIZED-EVIDENCE",
    }
