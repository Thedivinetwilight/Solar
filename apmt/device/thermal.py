"""APMT V1.9-C — thermal model rebuilt around an explicit energy balance.

Two closures are available. Both are *stated*, both are checkable, and the
default is the physical one.

``simple`` (V1.9-B, retained for lineage)
-----------------------------------------
    T_j = T_ambient + R_th,eff * G * f_heat ,   f_heat = absorption_heat_fraction

All *incident* power is treated as heat: the electrically extracted and
reflected fractions are ignored. With R_th = 2.0 K cm^2/mW (the registered
upper bound) and one sun this permits a >200 K rise, i.e. a ~500 K junction
that is not physically realisable for a glass-mounted cell. The closure has no
radiative heat-loss pathway at all, so nothing self-limits.

``energy_balance`` (V1.9-C default)
-----------------------------------
Heat load and loss are computed from the model's own optical and electrical
results:

    P_abs      = G * (1 - R - T)                [mW/cm2]  (optics, room-T constants)
    P_elec(T)  = PCE(T) * G_ref                 [mW/cm2]
    Q_heat(T)  = P_abs - P_elec(T)              (heat that must leave the junction)
    L(T)       = (T - T_amb)/R_th,eff  +  eps * sigma * (T^4 - T_amb^4)

    equilibrium:  Q_heat(T*) = L(T*)

* Only the *absorbed* power becomes heat (scaled by the registered
  ``absorption_heat_fraction``, default 1.0) (reflected/transmitted light does not
  heat the cell) and the extracted electrical power leaves as work -- this is
  the standard module energy balance.
* A radiative channel to ambient (emissivity ``thermal_emissivity``, default
  0.9) is a genuine heat-loss pathway of a glass-fronted cell; it grows as T^4
  and therefore caps extreme temperatures instead of clipping them by fiat.
* Luminescent escape (photons leaving the cell without being converted) is
  neglected, and the radiative sink is to *ambient* rather than the colder sky,
  so both are conservative for temperature.
* The optical constants are evaluated at room temperature; the resulting
  temperature dependence of R/T is second order (<1 % between 298 K and 330 K)
  and is documented rather than modelled.

The solver reports the energy-balance residual and the stability derivative
``d(Q-L)/dT < 0`` (equilibrium is stable), both of which are HARD invariants.
No type conversions are done implicitly: every energy density in this module is
mW/cm^2, every temperature K, every areal thermal resistance K cm^2 / mW.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

import numpy as np

from ..core.constants import STEFAN_BOLTZMANN_W_M2_K4
from ..params.registry import ParamSet

SUN_POWER_MW_CM2 = 100.0          # one sun = 1000 W/m^2 = 100 mW/cm^2

# Electrical model validity envelope. The electrical parameterisation (Varshni
# bandgaps, intrinsic carrier density, the SRH slab model, the calibrated
# ideality/J0 budget) is registered for temperature_k in [220, 400] K. The
# thermal solve must sometimes EVALUATE the heat load at trial temperatures far
# outside that window in order to bracket the equilibrium, so the substituter
# below returns the conservative P_elec = 0 there. Any solve whose CONVERGED
# junction temperature lands outside the window is rejected by the guard: its
# reported efficiency is an extrapolation.
ELECTRICAL_ENVELOPE_MIN_K = 220.0
ELECTRICAL_ENVELOPE_MAX_K = 400.0


class ModelValidityError(RuntimeError):
    """A converged answer lies outside the model's registered validity window.

    Raised instead of returning a number: reporting an extrapolated efficiency as
    if it were a model result is exactly the kind of manufactured certainty the
    APMT programme forbids. The guard converts this into an INVALID solve record,
    so campaigns exclude the point and report why.
    """


def assert_inside_electrical_envelope(junction_k: float, *, context: str = "") -> None:
    if not (ELECTRICAL_ENVELOPE_MIN_K <= junction_k <= ELECTRICAL_ENVELOPE_MAX_K):
        raise ModelValidityError(
            f"converged junction temperature {junction_k:.1f} K lies outside the "
            f"electrical model's registered validity window "
            f"[{ELECTRICAL_ENVELOPE_MIN_K}, {ELECTRICAL_ENVELOPE_MAX_K}] K"
            + (f" ({context})" if context else "") +
            "; the electrical parameterisation (Varshni bandgaps, n_i, SRH slab, "
            "calibrated J0 budget) is not defined beyond this range")
W_M2_TO_MW_CM2 = 0.1              # 1 W/m^2 = 0.1 mW/cm^2


@dataclass(frozen=True)
class ThermalState:
    ambient_k: float
    junction_k: float
    delta_t_k: float
    r_th_effective_k_cm2_w: float
    emissivity: float
    heat_load_mw_cm2: float
    conduction_loss_mw_cm2: float
    radiative_loss_mw_cm2: float
    residual_mw_cm2: float
    d_loss_dt_mw_cm2_k: float
    d_heat_dt_mw_cm2_k: float
    iterations: int
    converged: bool
    model: str
    closure_note: str = ""
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: (bool(v) if isinstance(v, bool) else
                    (int(v) if isinstance(v, int) else
                     (v if isinstance(v, str) else float(v))))
                for k, v in self.__dict__.items() if k != "diagnostics"} | \
               {"diagnostics": self.diagnostics}

    @property
    def stable(self) -> bool:
        return self.d_loss_dt_mw_cm2_k > self.d_heat_dt_mw_cm2_k


def radiative_loss_mw_cm2(temperature_k: float, ambient_k: float, emissivity: float) -> float:
    """Net radiative cooling to ambient [mW/cm^2] (epsilon * sigma * dT^4)."""
    if emissivity <= 0.0:
        return 0.0
    return emissivity * STEFAN_BOLTZMANN_W_M2_K4 * (
        temperature_k ** 4 - ambient_k ** 4) * W_M2_TO_MW_CM2


def loss_mw_cm2(temperature_k: float, *, ambient_k: float, r_th_eff: float,
                emissivity: float) -> float:
    conduction = (temperature_k - ambient_k) / max(r_th_eff, 1e-12)
    return conduction + radiative_loss_mw_cm2(temperature_k, ambient_k, emissivity)


def d_loss_dt(temperature_k: float, *, r_th_eff: float, emissivity: float) -> float:
    return 1.0 / max(r_th_eff, 1e-12) + emissivity * STEFAN_BOLTZMANN_W_M2_K4 * \
        4.0 * temperature_k ** 3 * W_M2_TO_MW_CM2


def simple_temperature(ps: ParamSet, ambient_k: Optional[float] = None) -> ThermalState:
    """The V1.9-B closure (all incident power as heat), retained for lineage."""
    T_amb = float(ambient_k if ambient_k is not None else ps["temperature_k"])
    r_th = ps["thermal_resistance_k_cm2_w"] * (1.0 - ps["thermal_management_gain"])
    heat = ps["irradiance_suns"] * SUN_POWER_MW_CM2 * ps["absorption_heat_fraction"]
    delta = r_th * heat
    return ThermalState(
        ambient_k=T_amb, junction_k=T_amb + delta, delta_t_k=delta,
        r_th_effective_k_cm2_w=r_th, emissivity=0.0,
        heat_load_mw_cm2=heat,
        conduction_loss_mw_cm2=delta / max(r_th, 1e-12),
        radiative_loss_mw_cm2=0.0, residual_mw_cm2=0.0,
        d_loss_dt_mw_cm2_k=1.0 / max(r_th, 1e-12), d_heat_dt_mw_cm2_k=0.0,
        iterations=1, converged=True, model="simple",
        closure_note="legacy V1.9-B closure: ALL incident power treated as heat, "
                     "no radiative cooling pathway (superseded by energy_balance)")


def solve_equilibrium(ps: ParamSet, absorbed_power_mw_cm2: float,
                      electrical_power_fn: Callable[[float], float],
                      ambient_k: Optional[float] = None,
                      tol_mw_cm2: float = 1e-4, max_iter: int = 25,
                      initial_temperature_k: Optional[float] = None) -> ThermalState:
    """Solve Q_heat(T) = L(T) for the junction temperature.

    Parameters
    ----------
    absorbed_power_mw_cm2 : optical absorbed power density at the operating
        irradiance (temperature-independent, see the module docstring).
    electrical_power_fn : callable T[K] -> extracted power density [mW/cm^2];
        called with the trial junction temperature, so the electrical model sees
        the temperature it actually operates at.
    """
    T_amb = float(ambient_k if ambient_k is not None else ps["temperature_k"])
    r_th = ps["thermal_resistance_k_cm2_w"] * (1.0 - ps["thermal_management_gain"])
    eps = float(ps["thermal_emissivity"])

    # Each electrical evaluation is a full tandem solve, so identical trial
    # temperatures are memoised inside a single equilibrium solve.
    _cache: dict = {}

    # ``absorption_heat_fraction`` = fraction of the absorbed (non-extracted)
    # power that becomes heat at the junction rather than leaving through a
    # non-thermal channel (luminescent escape, photon recycling out of the
    # stack). 1.0 is the conservative value. Without this factor the registered
    # parameter would be structurally dead -- flagged as a defect by the V1.9-C
    # inert screener, and fixed here rather than declared inert.
    # V1.9-H repair (F-heat): the documented form is f_heat * (absorbed -
    # extracted); the old code subtracted the FULL extracted power from the
    # fractioned absorbed power. Identical at the default f_heat = 1.0.
    f_heat = float(ps["absorption_heat_fraction"])

    def heat_load(T: float) -> float:
        key = round(float(T), 9)
        if key not in _cache:
            _cache[key] = f_heat * (absorbed_power_mw_cm2
                                    - electrical_power_fn(float(T)))
        return _cache[key]

    def residual(T: float) -> float:
        return loss_mw_cm2(T, ambient_k=T_amb, r_th_eff=r_th, emissivity=eps) - heat_load(T)

    # Bracket. At T_amb the loss is zero and the heat load is positive (a cell
    # always has some heat), so the residual starts negative. An analytic upper
    # bound avoids a long expansion loop in which every trial is a full electrical
    # solve: because the extracted power falls with temperature, Q(T) <= Q(T_amb),
    # so a rise of 1.5 * Q(T_amb) * R_th already guarantees L > Q:
    #     L >= (T - T_amb)/R_th = 1.5 * Q(T_amb) > Q(T).
    # Physically, this is only the *initial bracket*; the equilibrium itself is
    # solved from the full balance, and the stability invariant verifies
    # uniqueness of the solution found.
    lo = T_amb
    q_amb = heat_load(T_amb)
    hi = T_amb + 1.5 * q_amb * r_th + 5.0
    r_hi = residual(hi)
    expands = 0
    while r_hi < 0.0 and expands < 60:                       # pragma: no cover
        hi = T_amb + (hi - T_amb) * 1.4
        r_hi = residual(hi)
        expands += 1
    if r_hi < 0.0:                       # pragma: no cover - defensive
        hi = T_amb + 1000.0
        r_hi = residual(hi)

    if initial_temperature_k is not None:
        T = float(np.clip(initial_temperature_k, lo, hi))
    else:
        # initial guess: the simple closure, i.e. all the heat load assumed to
        # flow through the thermal resistance (always an over-estimate, so the
        # first Newton step brings the temperature down). This keeps the number
        # of electrical solves per thermal equilibrium small (each iteration is
        # a full tandem solve).
        T = float(np.clip(T_amb + heat_load(T_amb) * r_th, lo, hi))
    converged = False
    it = 0
    r_T = residual(T)
    for it in range(1, max_iter + 1):
        if abs(r_T) <= tol_mw_cm2:
            converged = True
            break
        # Newton step using the ANALYTIC loss derivative only. The neglected term
        # is dP_elec/dT (~0.06 mW/cm^2/K), two orders of magnitude below
        # dL/dT (~3.5 mW/cm^2/K) for a real cell, so convergence stays fast while
        # each iteration costs exactly one electrical solve. The step is
        # safeguarded by the bracket, which keeps it globally convergent for a
        # monotone residual (the stability invariant verifies that monotonicity).
        d = d_loss_dt(T, r_th_eff=r_th, emissivity=eps)
        T_new = T - r_T / d if d > 0.0 else 0.5 * (lo + hi)
        if not np.isfinite(T_new) or not (lo < T_new < hi):
            T_new = 0.5 * (lo + hi)
        r_new = residual(T_new)
        if abs(r_new) >= abs(r_T):
            T_new = 0.5 * (lo + hi)          # damp: bisect instead of overshoot
            r_new = residual(T_new)
        if r_new > 0.0:
            hi = T_new
        else:
            lo = T_new
        T, r_T = float(np.clip(T_new, lo, hi)), r_new

    Q = heat_load(T)
    cond = (T - T_amb) / max(r_th, 1e-12)
    rad = radiative_loss_mw_cm2(T, T_amb, eps)
    return ThermalState(
        ambient_k=T_amb, junction_k=T, delta_t_k=T - T_amb,
        r_th_effective_k_cm2_w=r_th, emissivity=eps,
        heat_load_mw_cm2=Q, conduction_loss_mw_cm2=cond, radiative_loss_mw_cm2=rad,
        residual_mw_cm2=(cond + rad) - Q,
        d_loss_dt_mw_cm2_k=d_loss_dt(T, r_th_eff=r_th, emissivity=eps),
        d_heat_dt_mw_cm2_k=_numeric_d_heat_dt(heat_load, T, T_amb),
        iterations=it, converged=converged, model="energy_balance",
        closure_note="heat = absorbed - extracted; loss = conduction + "
                     "radiative cooling to ambient; optical constants at 298 K",
        diagnostics={"expansions": expands, "electrical_solves": len(_cache)})


def _numeric_d_heat_dt(heat_load: Callable[[float], float], T: float,
                       T_amb: float, dT: float = 0.5) -> float:
    """d(heat load)/dT [mW/cm^2/K] by a central difference.

    The heat load falls with temperature (the cell gets less efficient), so this
    is normally negative, which *increases* thermal stability.
    """
    lo = max(T_amb, T - dT)
    return (heat_load(T + dT) - heat_load(lo)) / (T + dT - lo)
