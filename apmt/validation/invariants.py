"""APMT V1.9 — automated physical-invariant checks (directive §21).

Every model result passes through :func:`check_invariants` before it can be
reported. A violation raises :class:`InvariantViolation` (fail loudly) instead
of returning a number that quietly violates physics. The checks are:

I1  energy closure of an optical solve:      |R + T + A - 1| <= tol
I2  EQE/IQE bounds:                          0 <= EQE <= 1, 0 <= IQE <= 1
I3  EQE <= absorptance of the same layer     (no EQE without absorption)
I4  photon budget closure in current units   (incident = R + T + parasitic
                                              + absorbed_top + absorbed_bottom)
I5  current conservation: Jsc_tandem <= min(Jsc_top, Jsc_bottom) + coupling
I6  voltage limits: 0 < Voc < sum(Eg)/q and Vmp <= Voc
I7  efficiency ceiling: finite model PCE <= radiative-limit PCE with the same
    absorbed photon budget (a model must never beat detailed balance)
I8  non-negativity of every loss channel
I9  monotonicity where physics requires it: absorptance increases with absorber
    thickness; Jsc increases with IQE
I10 temperature consistency: Voc decreases with temperature at fixed optics
I11 numerical convergence status is not UNDEFINED for a reported headline value
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


class InvariantViolation(RuntimeError):
    """Raised when a computed result violates a physical invariant."""


@dataclass(frozen=True)
class InvariantReport:
    name: str
    passed: bool
    message: str
    value: Optional[float] = None
    tolerance: Optional[float] = None


def _r(name: str, passed: bool, message: str, value=None, tol=None) -> InvariantReport:
    return InvariantReport(name, bool(passed), message,
                           None if value is None else float(value),
                           None if tol is None else float(tol))


def check_optical_closure(reflectance: np.ndarray, transmittance: np.ndarray,
                          total_absorption: np.ndarray, tol: float = 1e-6) -> InvariantReport:
    resid = np.asarray(reflectance) + np.asarray(transmittance) + np.asarray(total_absorption) - 1.0
    mx = float(np.max(np.abs(resid)))
    return _r("I1-optical-closure", mx <= tol,
              f"max|R+T+A-1| = {mx:.3e} (tol {tol:.1e})", mx, tol)


def check_quantum_efficiency_bounds(eqe: np.ndarray, iqe: Optional[np.ndarray] = None,
                                    tol: float = 1e-9) -> InvariantReport:
    e = np.asarray(eqe, dtype=float)
    bad = int(np.sum((e < -tol) | (e > 1.0 + tol)))
    msg = f"{bad} EQE values outside [0, 1] (max {np.max(e):.4f})"
    if iqe is not None:
        q = np.asarray(iqe, dtype=float)
        bad += int(np.sum((q < -tol) | (q > 1.0 + tol)))
        msg += f"; IQE max {np.max(q):.4f}"
    return _r("I2-quantum-efficiency-bounds", bad == 0, msg, bad, 0.0)


def check_eqe_below_absorptance(eqe: np.ndarray, absorptance: np.ndarray,
                                tol: float = 1e-6) -> InvariantReport:
    excess = float(np.max(np.asarray(eqe) - np.asarray(absorptance)))
    return _r("I3-EQE<=absorptance", excess <= tol,
              f"max(EQE - A_absorber) = {excess:.3e}", excess, tol)


def check_photon_budget(budget: dict, tol_ma_cm2: float = 1e-6) -> InvariantReport:
    total = budget["incident_100pct_eqe"]
    parts = (budget["reflected"] + budget["transmitted"] + budget["parasitic_absorbed"]
             + budget["absorbed_top"] + budget["absorbed_bottom"])
    resid = float(parts - total)
    return _r("I4-photon-budget-closure", abs(resid) <= tol_ma_cm2,
              f"budget residual {resid:.3e} mA/cm2", resid, tol_ma_cm2)


def check_tandem_current(jsc_tandem: float, jsc_top: float, jsc_bottom: float,
                         coupling_gain: float = 0.0, tol: float = 1e-6) -> InvariantReport:
    limit = min(jsc_top, jsc_bottom) + coupling_gain + tol
    return _r("I5-tandem-current-limit", jsc_tandem <= limit,
              f"Jsc_tandem {jsc_tandem:.4f} <= min(top,bottom)+coupling "
              f"{limit:.4f}", jsc_tandem - limit, tol)


def check_voltage_limits(voc_v: float, vmp_v: float, sum_eg_ev: float,
                         tol: float = 1e-6) -> InvariantReport:
    ok = (voc_v > 0) and (voc_v <= sum_eg_ev + tol) and (vmp_v <= voc_v + tol)
    return _r("I6-voltage-limits", ok,
              f"Voc {voc_v:.4f} V (must be 0 < Voc <= sum(Eg) = {sum_eg_ev:.3f} eV), "
              f"Vmp {vmp_v:.4f} V", voc_v, sum_eg_ev)


def check_detailed_balance_ceiling(pce_pct: float, radiative_limit_pct: float,
                                   tol: float = 1e-6) -> InvariantReport:
    ok = pce_pct <= radiative_limit_pct + tol
    return _r("I7-detailed-balance-ceiling", ok,
              f"model PCE {pce_pct:.3f}% <= radiative limit {radiative_limit_pct:.3f}%",
              pce_pct - radiative_limit_pct, tol)


def check_nonnegative(losses: dict, tol: float = 1e-9) -> InvariantReport:
    bad = {k: float(v) for k, v in losses.items() if float(v) < -tol}
    return _r("I8-nonnegative-losses", not bad,
              f"negative loss channels: {bad}" if bad else "all losses >= 0",
              len(bad), 0.0)


def check_monotone_thickness(thickness_nm: Sequence[float],
                             absorptance: Sequence[float],
                             tol: float = 1e-6) -> InvariantReport:
    t = np.asarray(thickness_nm, dtype=float)
    a = np.asarray(absorptance, dtype=float)
    order = np.argsort(t)
    diffs = np.diff(a[order])
    worst = float(np.min(diffs)) if diffs.size else 0.0
    return _r("I9-monotone-absorptance-with-thickness", worst >= -tol,
              f"min dA/d_thickness = {worst:.3e} (must be >= 0)", worst, tol)


def check_voc_temperature_trend(temperatures_k: Sequence[float],
                                voc_v: Sequence[float], tol: float = 1e-9) -> InvariantReport:
    T = np.asarray(temperatures_k, float)
    V = np.asarray(voc_v, float)
    order = np.argsort(T)
    diffs = np.diff(V[order])
    worst = float(np.max(diffs)) if diffs.size else 0.0
    return _r("I10-Voc-decreases-with-temperature", worst <= tol,
              f"max dVoc/dT = {worst:.3e} V/K (must be <= 0)", worst, tol)


def check_convergence_status(status: str, quantity: str = "") -> InvariantReport:
    ok = status != "UNDEFINED"
    return _r("I11-convergence-status", ok,
              f"{quantity or 'quantity'} convergence status {status}")


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------
def check_invariants(reports: Sequence[InvariantReport],
                     raise_on_violation: bool = True) -> tuple:
    """Run a set of invariant reports; raise if any failed (default)."""
    failed = [r for r in reports if not r.passed]
    if failed and raise_on_violation:
        raise InvariantViolation(
            "physical invariant violation: "
            + "; ".join(f"{r.name}: {r.message}" for r in failed))
    return tuple(reports)


def summarize(reports: Sequence[InvariantReport]) -> dict:
    return {
        "n_checks": len(reports),
        "n_passed": sum(1 for r in reports if r.passed),
        "violations": [{"name": r.name, "message": r.message}
                       for r in reports if not r.passed],
        "checks": [{"name": r.name, "passed": r.passed, "message": r.message,
                    "value": r.value, "tolerance": r.tolerance} for r in reports],
    }
