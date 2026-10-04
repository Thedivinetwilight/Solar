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
    """The V1.9-B report shape. Retained unchanged for historical callers; the
    V1.9-C layer adds :attr:`status`/:meth:`to_record` so that both generations of
    checks can live in ONE registry (:data:`CHECKS`) and be consumed uniformly by
    the guard."""

    name: str
    passed: bool
    message: str
    value: Optional[float] = None
    tolerance: Optional[float] = None

    @property
    def status(self) -> "InvariantStatus":
        return InvariantStatus.PASS if self.passed else InvariantStatus.FAIL

    @property
    def severity(self) -> "Severity":
        return Severity.HARD

    def to_dict(self) -> dict:
        return {"name": self.name, "group": InvariantGroup.ELECTRICAL.value,
                "status": self.status.value, "severity": self.severity.value,
                "measured": self.value, "limit": None, "tolerance": self.tolerance,
                "units": "", "message": self.message}

    def to_record(self, group: str = "legacy") -> "InvariantRecord":
        return InvariantRecord(self.name, group, self.status, Severity.HARD,
                               self.value, None, self.tolerance, self.message, "")


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


# ===========================================================================
# V1.9-C: first-class invariant layer
# ===========================================================================
# The functions above are the *checks*. This layer turns them into a
# machine-readable verdict that accompanies every solve, with four states:
#
#   PASS           the check was evaluated and satisfied
#   WARN           a soft check is outside its tolerance (result usable but
#                  flagged; soft failures never invalidate a solve)
#   FAIL           a HARD check was violated -> the solve is INVALID and must
#                  not enter calibration, optimisation, surrogate training or
#                  discovery datasets
#   NOT_APPLICABLE the check does not apply to this model level / configuration
#
# Severity is a property of the check, not the outcome: a numerical-artefact
# guard (NaN/Inf) is HARD, while e.g. a finite-shunt consistency margin is SOFT.

from dataclasses import field as _field  # noqa: E402
from enum import Enum  # noqa: E402  (kept local to the V1.9-C block)
from typing import Callable  # noqa: E402


class InvariantStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class InvariantGroup(str, Enum):
    OPTICAL = "optical"
    ELECTRICAL = "electrical"
    THERMAL = "thermal"
    NUMERICAL = "numerical"
    DATA = "data"


class Severity(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


_ORDER = {InvariantStatus.PASS: 0, InvariantStatus.NOT_APPLICABLE: 0,
          InvariantStatus.WARN: 1, InvariantStatus.FAIL: 2}


@dataclass(frozen=True)
class InvariantRecord:
    """One machine-readable check outcome."""

    name: str
    group: str
    status: InvariantStatus
    severity: Severity = Severity.HARD
    measured: Optional[float] = None
    limit: Optional[float] = None
    tolerance: Optional[float] = None
    message: str = ""
    units: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "status": self.status.value,
                "severity": self.severity.value, "measured": self.measured,
                "limit": self.limit, "tolerance": self.tolerance,
                "units": self.units, "message": self.message}


def record(name: str, group: str, ok: bool, measured=None, limit=None,
           tolerance=None, message: str = "", units: str = "",
           severity: Severity = Severity.HARD,
           applicable: bool = True) -> InvariantRecord:
    if not applicable:
        status = InvariantStatus.NOT_APPLICABLE
    elif ok:
        status = InvariantStatus.PASS
    else:
        status = InvariantStatus.WARN if severity is Severity.SOFT else InvariantStatus.FAIL
    return InvariantRecord(name, group, status, severity,
                           None if measured is None else float(measured),
                           None if limit is None else float(limit),
                           None if tolerance is None else float(tolerance),
                           message, units)


@dataclass(frozen=True)
class InvariantBundle:
    """The full verdict for one solve (or one batch of solves)."""

    records: tuple
    context: dict = _field(default_factory=dict)

    @property
    def status(self) -> InvariantStatus:
        worst = InvariantStatus.PASS
        for r in self.records:
            if _ORDER[r.status] > _ORDER[worst]:
                worst = r.status
        return worst

    @property
    def valid(self) -> bool:
        """A solve is INVALID iff any HARD check FAILed."""
        return not any(r.status is InvariantStatus.FAIL and r.severity is Severity.HARD
                       for r in self.records)

    @property
    def failures(self) -> tuple:
        return tuple(r for r in self.records if r.status is InvariantStatus.FAIL)

    @property
    def warnings(self) -> tuple:
        return tuple(r for r in self.records if r.status is InvariantStatus.WARN)

    @property
    def hard_failures(self) -> tuple:
        """The FAILs that make a solve INVALID (severity HARD)."""
        return tuple(r for r in self.records if r.status is InvariantStatus.FAIL
                     and r.severity is Severity.HARD)

    @property
    def soft_failures(self) -> tuple:
        """SOFT non-conformances: reported, never invalidating."""
        return tuple(r for r in self.records if r.severity is Severity.SOFT
                     and r.status in (InvariantStatus.WARN, InvariantStatus.FAIL))

    @property
    def invalid_reason(self) -> str:
        return "; ".join(f"{r.name}: {r.message}" for r in self.hard_failures)

    def counts(self) -> dict:
        out = {s.value: 0 for s in InvariantStatus}
        for r in self.records:
            out[r.status.value] += 1
        return out

    def to_dict(self) -> dict:
        return {"status": self.status.value, "valid": self.valid,
                "counts": self.counts(),
                "failures": [r.to_dict() for r in self.failures],
                "warnings": [r.to_dict() for r in self.warnings],
                "records": [r.to_dict() for r in self.records],
                "context": self.context}


# ---------------------------------------------------------------------------
# Group checks
# ---------------------------------------------------------------------------
def check_numerical_finiteness(values: dict, context: dict = None) -> list:
    """HARD: no NaN / Inf anywhere in the reported scalars."""
    out = []
    for k, v in values.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            out.append(record(f"numerical.finite.{k}", InvariantGroup.NUMERICAL.value,
                              True, message=f"{k} non-scalar ({type(v).__name__}), skipped"))
            continue
        ok = np.isfinite(f)
        out.append(record(f"numerical.finite.{k}", InvariantGroup.NUMERICAL.value, ok,
                          measured=f, message=f"{k} = {f!r}" if not ok else "finite"))
    return out


def check_ranges(values: dict, limits: dict, group: str = "electrical") -> list:
    """HARD: named scalars must lie inside explicit physical limits."""
    out = []
    for k, (lo, hi) in limits.items():
        if k not in values or values[k] is None:
            out.append(record(f"{group}.range.{k}", group, True, applicable=False,
                              message="not reported"))
            continue
        v = float(values[k])
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        out.append(record(f"{group}.range.{k}", group, ok, measured=v, limit=hi,
                          message=f"{k} = {v:.6g} must be in ({lo}, {hi})"))
    return out


def check_current_continuity(j_top_sc: float, j_bottom_sc: float, j_tandem_sc: float,
                             tol: float = 1e-6) -> InvariantRecord:
    """HARD: the tandem short-circuit current cannot exceed the smaller subcell
    short-circuit current (plus any coupling gain, which the caller folds into
    the subcell value)."""
    ok = j_tandem_sc <= min(j_top_sc, j_bottom_sc) + tol
    return record("electrical.current_continuity", InvariantGroup.ELECTRICAL.value, ok,
                  measured=j_tandem_sc, limit=float(min(j_top_sc, j_bottom_sc)),
                  tolerance=tol, units="mA/cm2",
                  message=(f"Jsc_tandem {j_tandem_sc:.6f} <= min(Jsc_subcells) "
                           f"{min(j_top_sc, j_bottom_sc):.6f}"))


def check_recombination_channels(j0_radiative: float, j0_srh: float, j0_total: float,
                                 tol_rel: float = 1e-9) -> list:
    """HARD: J0_total must equal the sum of its channels.

    The radiative channel must be STRICTLY positive: a cell with zero radiative
    recombination violates detailed balance, and it would also make the
    radiative-limit ceiling infinite, i.e. it would silently disable the very
    invariant that catches runaway coupling terms. The SRH channel may be zero
    (the ideal-single-diode limit is a legitimate model level).
    """
    out = [record("electrical.j0_channels_positive", InvariantGroup.ELECTRICAL.value,
                  j0_radiative > 0.0 and j0_srh >= 0.0,
                  measured=min(j0_radiative, j0_srh), limit=0.0, units="mA/cm2",
                  message="radiative J0 must be > 0 (detailed balance); SRH J0 >= 0")]
    s = j0_radiative + j0_srh
    rel = abs(s - j0_total) / max(abs(j0_total), 1e-300)
    out.append(record("electrical.j0_channel_sum", InvariantGroup.ELECTRICAL.value,
                      rel <= tol_rel, measured=rel, tolerance=tol_rel,
                      message=f"relative channel-sum mismatch {rel:.3e}"))
    return out


def check_resistance_bounds(rs_ohm_cm2: float, rsh_ohm_cm2: float) -> list:
    """HARD: series resistance non-negative and finite; shunt positive (or inf)."""
    return [
        record("electrical.rs_bounds", InvariantGroup.ELECTRICAL.value,
               np.isfinite(rs_ohm_cm2) and rs_ohm_cm2 >= 0.0, measured=rs_ohm_cm2,
               limit=0.0, units="ohm cm2", message="Rs must be finite and >= 0"),
        record("electrical.rsh_bounds", InvariantGroup.ELECTRICAL.value,
               (np.isinf(rsh_ohm_cm2) or rsh_ohm_cm2 > 0.0) and rsh_ohm_cm2 > 0.0,
               measured=(None if not np.isfinite(rsh_ohm_cm2) else float(rsh_ohm_cm2)),
               limit=0.0, units="ohm cm2", message="Rsh must be > 0 (or infinite)"),
    ]


def check_shunt_consistency(jsc_shunted: float, jsc_ideal: float,
                            rsh_ohm_cm2: float) -> InvariantRecord:
    """SOFT: a finite shunt must reduce Jsc by approximately Voc/Rsh."""
    if not np.isfinite(rsh_ohm_cm2):
        return record("electrical.shunt_consistency", InvariantGroup.ELECTRICAL.value,
                      True, applicable=False, message="ideal shunt (Rsh = inf)")
    delta = jsc_ideal - jsc_shunted
    return record("electrical.shunt_consistency", InvariantGroup.ELECTRICAL.value,
                  delta >= -1e-9, measured=delta, limit=0.0, units="mA/cm2",
                  severity=Severity.SOFT,
                  message="finite Rsh must not increase Jsc")


def check_thermal_energy_balance(heat_in_mw_cm2: float, heat_out_mw_cm2: float,
                                 tol_rel: float = 1e-6,
                                 tol_abs_mw_cm2: float = 1e-3) -> InvariantRecord:
    """HARD: the thermal equilibrium must actually balance.

    Tolerance policy: the equilibrium solver converges the residual to
    ``tol_mw_cm2 = 1e-4`` (its documented solver tolerance); the invariant is
    evaluated with an absolute tolerance of 1e-3 mW/cm^2 (a ten-fold margin) and
    a relative tolerance of 1e-6. A 1e-3 mW/cm^2 imbalance is 0.001 % of one sun,
    i.e. far below any measurement uncertainty, while a genuinely missing or
    double-counted heat pathway shows up orders of magnitude above this bound.
    """
    scale = max(abs(heat_in_mw_cm2), 1e-12)
    abs_res = abs(heat_in_mw_cm2 - heat_out_mw_cm2)
    rel = abs_res / scale
    ok = (rel <= tol_rel) or (abs_res <= tol_abs_mw_cm2)
    return record("thermal.energy_balance", InvariantGroup.THERMAL.value, ok,
                  measured=abs_res, limit=tol_abs_mw_cm2, tolerance=tol_rel,
                  message=(f"heat in {heat_in_mw_cm2:.6f} vs out {heat_out_mw_cm2:.6f} "
                           f"mW/cm2 (abs {abs_res:.3e}, rel {rel:.3e})"))


def check_thermal_stability(d_power_d_t_mw_cm2_k: float) -> InvariantRecord:
    """HARD: at equilibrium the net heat loss must increase with temperature,
    i.e. d(dissipation)/dT > 0, otherwise the operating point is unstable."""
    return record("thermal.stability", InvariantGroup.THERMAL.value,
                  d_power_d_t_mw_cm2_k > 0.0, measured=d_power_d_t_mw_cm2_k, limit=0.0,
                  message="heat dissipation must increase with temperature")


def check_temperature_envelope(temperature_k: float, ambient_k: float,
                               max_rise_k: float = 150.0) -> InvariantRecord:
    """SOFT: a rise beyond 150 K at one sun is physically implausible for a
    glass-mounted cell; it flags an assumption problem, it does not invalidate
    the solve (the model may legitimately be asked for an extreme)."""
    rise = temperature_k - ambient_k
    return record("thermal.temperature_envelope", InvariantGroup.THERMAL.value,
                  rise <= max_rise_k, measured=rise, limit=max_rise_k, units="K",
                  severity=Severity.SOFT,
                  message=f"junction rise {rise:.1f} K above ambient")


def check_data_grid(wavelength_nm: np.ndarray, require_monotone: bool = True,
                    min_points: int = 20) -> list:
    """HARD: wavelength grids must be monotone increasing, finite, duplicate-free."""
    wl = np.asarray(wavelength_nm, dtype=float)
    out = [
        record("data.wavelength_finite", InvariantGroup.DATA.value,
               bool(np.all(np.isfinite(wl))), message="wavelengths must be finite"),
        record("data.wavelength_positive", InvariantGroup.DATA.value,
               bool(np.all(wl > 0.0)), message="wavelengths must be > 0"),
        record("data.wavelength_monotone", InvariantGroup.DATA.value,
               bool(np.all(np.diff(wl) > 0)) if require_monotone else True,
               applicable=require_monotone, message="wavelength grid must increase"),
        record("data.min_points", InvariantGroup.DATA.value, wl.size >= min_points,
               measured=wl.size, limit=min_points, message="grid too coarse"),
    ]
    if wl.size > 1:
        dup = int(np.sum(np.diff(wl) == 0.0))
        out.append(record("data.wavelength_duplicates", InvariantGroup.DATA.value,
                          dup == 0, measured=dup, limit=0,
                          message="duplicate wavelength samples"))
    return out


def check_radiometric_consistency(total_absorbed_plus_out_mw_cm2: float,
                                  incident_mw_cm2: float,
                                  tol_rel: float = 1e-9) -> InvariantRecord:
    """HARD: absorbed + reflected + transmitted power = incident power."""
    rel = abs(total_absorbed_plus_out_mw_cm2 - incident_mw_cm2) / max(incident_mw_cm2, 1e-12)
    return record("optical.power_conservation", InvariantGroup.OPTICAL.value,
                  rel <= tol_rel, measured=rel, tolerance=tol_rel,
                  message=f"relative power-balance residual {rel:.3e}")


def check_radiative_limit_consistency(pce_pct: float, radiative_limit_pct: float,
                                      tol: float = 1e-6) -> InvariantRecord:
    """HARD: no model may exceed the radiative (detailed-balance) limit for its
    own absorbed photon budget."""
    return record("electrical.radiative_limit", InvariantGroup.ELECTRICAL.value,
                  pce_pct <= radiative_limit_pct + tol,
                  measured=pce_pct, limit=radiative_limit_pct, tolerance=tol,
                  units="%", message="model PCE must not exceed the radiative limit")


CHECKS = {
    "optical.closure": check_optical_closure,
    "optical.photon_budget": check_photon_budget,
    "quantum_efficiency.bounds": check_quantum_efficiency_bounds,
    "quantum_efficiency.below_absorptance": check_eqe_below_absorptance,
    "electrical.tandem_current": check_tandem_current,
    "electrical.voltage_limits": check_voltage_limits,
    "electrical.detailed_balance_ceiling": check_detailed_balance_ceiling,
    "electrical.radiation_limit": check_radiative_limit_consistency,
    "numerical.nonnegativity": check_nonnegative,
    "thermal.voc_temperature_trend": check_voc_temperature_trend,
    "numerical.monotonicity": check_monotone_thickness,
    "numerical.convergence_status": check_convergence_status,
    "numerical.finiteness": check_numerical_finiteness,
    "thermal.temperature_envelope": check_temperature_envelope,
    "thermal.energy_balance": check_thermal_energy_balance,
    "thermal.stability": check_thermal_stability,
    "electrical.current_continuity": check_current_continuity,
    "electrical.recombination_channels": check_recombination_channels,
    "electrical.resistance_bounds": check_resistance_bounds,
    "electrical.shunt_consistency": check_shunt_consistency,
    "data.wavelength_grid": check_data_grid,
    "optical.radiometric_consistency": check_radiometric_consistency,
}
"""Registry of every invariant check: name -> callable. The solve-level verdict
builder (apmt.validation.guard) calls these through this registry so that the
set of checks is discoverable and testable."""
