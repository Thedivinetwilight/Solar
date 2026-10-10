"""APMT V1.9 — Latin-hypercube screening with rank correlations and SRC.

A cheap, honest first-order global screen. It is explicitly *not* a variance
decomposition: Sobol indices require either a 10^3-10^4 model evaluations (the
tandem solve is ~1 s, so that is V1.9-D work) or a validated surrogate. What is
reported here:

* Latin-hypercube samples inside each parameter's *registered* range (a parameter
  is never sampled outside its declared range, and ranges are never invented);
* Spearman rank correlation of each parameter with PCE (monotone association);
* standardised regression coefficients from an OLS surrogate on standardised
  inputs, with a bootstrap confidence interval;
* the surrogate's R^2, so the reader can see how much of the variation the
  linear model actually explains.

All outputs are labelled PRE-GATE / MODEL-OBSERVED / EXPLORATORY.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from ..core.numerics import make_rng
from ..device.tandem import evaluate_tandem
from ..params.registry import ParamSet, spec

DEFAULT_SCREEN_PARAMETERS = (
    "perovskite_eg_ev",
    "perovskite_thickness_nm",
    "arc_thickness_nm",
    "silicon_light_trapping",
    "photon_recycling_gain_top",
    "thermal_management_gain",
    "thermal_resistance_k_cm2_w",
    "rsh_ohm_cm2",
    "radiative_efficiency_top",
)


def lhs_matrix(names: Sequence[str], n_samples: int, seed: int = 20261003) -> np.ndarray:
    """Latin hypercube over the registered ranges of ``names`` (n x d)."""
    rng = make_rng(seed)
    d = len(names)
    u = np.empty((n_samples, d))
    for j in range(d):
        u[:, j] = (rng.permutation(n_samples) + rng.random(n_samples)) / n_samples
    out = np.empty_like(u)
    for j, name in enumerate(names):
        s = spec(name)
        out[:, j] = s.low + u[:, j] * (s.high - s.low)
    return out


def _spearman(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    rx = np.argsort(np.argsort(x, axis=0), axis=0).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean(axis=0)
    ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum(axis=0) * (ry ** 2).sum())
    return (rx * ry[:, None]).sum(axis=0) / np.where(denom == 0, np.nan, denom)


def screen(parameters: Sequence[str] = DEFAULT_SCREEN_PARAMETERS,
           n_samples: int = 96, seed: int = 20261003, model_form: str = "IQE-M1",
           n_bootstrap: int = 200,
           progress=None) -> dict:
    """Run the LHS screen and return correlations, SRCs and surrogate quality."""
    names = tuple(parameters)
    base = ParamSet.defaults()
    X = lhs_matrix(names, n_samples, seed)
    lo = np.array([spec(n).low for n in names])
    hi = np.array([spec(n).high for n in names])
    Xs = (X - lo) / (hi - lo)          # 0..1 within-range coordinates

    y = np.empty(n_samples)
    extras = np.empty((n_samples, 3))
    for i in range(n_samples):
        ps = base.with_mapping({n: float(v) for n, v in zip(names, X[i])})
        r = evaluate_tandem(ps, model_form=model_form)
        y[i] = r.pce_pct
        extras[i] = (r.voc_v, r.jsc_ma_cm2, r.detail["thermal"]["junction_k"])
        if progress is not None and (i + 1) % 16 == 0:
            progress(i + 1, n_samples)

    rho = _spearman(Xs, y)

    # OLS surrogate on standardised inputs -> standardised regression coefficients
    Xz = (Xs - Xs.mean(axis=0)) / Xs.std(axis=0)
    yz = y - y.mean()
    beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(n_samples), Xz]), y, rcond=None)
    y_hat = np.column_stack([np.ones(n_samples), Xz]) @ beta
    ss_res = float(((y - y_hat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    # Bootstrap the standardised regression coefficients on the SAME scale as
    # the point estimate (raw OLS beta on standardised inputs divided by the sd
    # of the response). V1.9 bug fix: the bootstrap loop previously kept the raw
    # beta scale, so the CI was reported in inconsistent units.
    rng = make_rng(seed + 1)
    boot = np.empty((n_bootstrap, len(names)))
    sd_y = float(y.std())
    for b in range(n_bootstrap):
        idx = rng.integers(0, n_samples, n_samples)
        bb, *_ = np.linalg.lstsq(
            np.column_stack([np.ones(n_samples), Xz[idx]]), y[idx], rcond=None)
        boot[b] = bb[1:] / sd_y if sd_y > 0 else bb[1:]

    src = beta[1:] / sd_y if sd_y > 0 else np.zeros(len(names))
    return {
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
        "method": ("Latin hypercube over registered ranges + Spearman rank "
                   "correlation + standardised-regression-coefficient OLS "
                   "surrogate with bootstrap CI. NOT a variance decomposition; "
                   "see apmt/sensitivity/sobol.py for Sobol indices (V1.9-D)."),
        "parameters": list(names),
        "n_samples": n_samples,
        "seed": seed,
        "model_form": model_form,
        "pce_mean": float(y.mean()), "pce_std": float(y.std()),
        "pce_min": float(y.min()), "pce_max": float(y.max()),
        "spearman_rho": {n: float(v) for n, v in zip(names, rho)},
        "src": {n: float(v) for n, v in zip(names, src)},
        "src_ci95": {n: [float(np.percentile(boot[:, j], 2.5)),
                         float(np.percentile(boot[:, j], 97.5))]
                     for j, n in enumerate(names)},
        "surrogate_r2": r2,
        "n_solves": n_samples,
    }
