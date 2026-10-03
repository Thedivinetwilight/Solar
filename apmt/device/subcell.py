"""APMT V1.9 — single subcell electrical model (two-diode + Rs/Rsh).

    J(V) = Jph - J0_rad (e^{V/kT} - 1)
               - J0_SRH (e^{V/(n kT)} - 1)
               - (V + J Rs)/Rsh

with J in mA/cm2, V in V, Rs in ohm*cm2 (converted internally: 1 mA/cm2 *
1 ohm*cm2 = 1e-3 V, so the resistive drop is J[mA/cm2]*Rs[ohm cm2]/1000).

Luminescent coupling and photon recycling enter here as an *additive*
photon-flux term, not as a fudge on the ideality factor:

    photon recycling (top cell)  -> an effective reduction of J0_rad by the
                                    recycling factor R_pr: J0_rad^eff = J0_rad/R_pr
    luminescent coupling         -> a current gain in the *receiving* (bottom)
                                    cell proportional to the *radiative* part of
                                    the emitting cell's recombination current,
                                    beta * J0_rad (exp(V/(kT)) - 1)

Both effects are OFF by default (factor 1, beta 0) and are switched on only
through registered parameters, so an "APMT mechanism" is always an explicit,
ablatable model term.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..core.constants import K_B_EV_K
from ..core.numerics import bisect, golden_section_max
from .recombination import J0Budget


@dataclass(frozen=True)
class SubcellModel:
    """Parameterisation of one subcell's electrical response."""

    name: str
    jph_ma_cm2: float
    j0_budget: J0Budget
    ideality_srh: float
    rs_ohm_cm2: float = 0.0
    rsh_ohm_cm2: float = np.inf
    # mechanism switches (all default OFF)
    photon_recycling_gain: float = 1.0       # divides the radiative J0
    luminescent_coupling_in: float = 0.0     # beta received from the other cell
    radiative_coupling_source: float = 0.0   # J0_rad of the emitting cell

    def j0_rad_effective(self) -> float:
        if self.photon_recycling_gain <= 0:
            raise ValueError("photon recycling gain must be positive")
        return self.j0_budget.j0_radiative_ma_cm2 / self.photon_recycling_gain

    def j0_srh(self) -> float:
        return self.j0_budget.j0_srh_ma_cm2


def thermal_voltage_v(temperature_k: float) -> float:
    return K_B_EV_K * temperature_k


def current_density(model: SubcellModel, voltage_v: np.ndarray | float,
                    temperature_k: float) -> np.ndarray:
    """Current density [mA/cm2] at a given bias (implicit in Rs, solved exactly)."""
    V = np.atleast_1d(np.asarray(voltage_v, dtype=float))
    kT = thermal_voltage_v(temperature_k)
    j0_rad = model.j0_rad_effective()
    j0_srh = model.j0_srh()
    n_id = model.ideality_srh
    jph = model.jph_ma_cm2

    with np.errstate(over="ignore"):
        diode_rad = j0_rad * (np.expm1(np.clip(V / kT, -700, 700)))
        diode_srh = j0_srh * (np.expm1(np.clip(V / (n_id * kT), -700, 700)))
    # luminescent coupling: extra photocurrent proportional to the *radiative*
    # recombination of the partner cell (evaluated at its own bias, supplied
    # through the tandem solver; here it is simply added as a bias-independent
    # term at the subcell's own operating point -- see tandem.py).
    coupling = model.luminescent_coupling_in * model.radiative_coupling_source
    J_diode = jph + coupling - diode_rad - diode_srh

    if not np.isfinite(model.rsh_ohm_cm2) and model.rs_ohm_cm2 == 0.0:
        return J_diode

    # Solve J = J_diode(V - J Rs /1000) - (V - J Rs/1000)/Rsh for J.
    out = np.empty_like(J_diode)
    for i, v in enumerate(V):
        def f(j: float) -> float:
            vj = v - j * model.rs_ohm_cm2 / 1000.0
            shunt = vj / model.rsh_ohm_cm2 if np.isfinite(model.rsh_ohm_cm2) else 0.0
            with np.errstate(over="ignore"):
                d_rad = j0_rad * (np.expm1(min(max(vj / kT, -700), 700)))
                d_srh = j0_srh * (np.expm1(min(max(vj / (n_id * kT), -700), 700)))
            return jph + coupling - d_rad - d_srh - shunt - j
        # bracket: high current (negative bias drop) .. low current
        lo, hi = -2.0 * abs(jph) - 10.0, 2.0 * abs(jph) + 10.0
        f_lo, f_hi = f(lo), f(hi)
        if (f_lo > 0) == (f_hi > 0):
            out[i] = f(0.0) + 0.0   # fall back to the ideal solution
        else:
            out[i] = bisect(f, lo, hi, tol=1e-10)
    return out


def jv_curve(model: SubcellModel, temperature_k: float,
             v_max: Optional[float] = None, n_points: int = 400) -> tuple:
    """Return (V, J) arrays spanning [0, Voc] plus a small over-bias margin."""
    voc0 = open_circuit_voltage(model, temperature_k)
    vmax = v_max if v_max is not None else voc0 * 1.02 + 0.01
    V = np.linspace(0.0, vmax, n_points)
    return V, current_density(model, V, temperature_k)


def open_circuit_voltage(model: SubcellModel, temperature_k: float) -> float:
    """Voc [V] of the subcell (exact for the ideal two-diode model, bisection)."""
    V, J = _scan_to_voc(model, temperature_k)
    return V


def _scan_to_voc(model: SubcellModel, temperature_k: float) -> tuple:
    kT = thermal_voltage_v(temperature_k)
    jph = model.jph_ma_cm2
    # upper bracket: sum of the two diode voltages that carry Jph
    j0_rad = max(model.j0_rad_effective(), 1e-300)
    j0_srh = max(model.j0_srh(), 1e-300)
    v_hi = kT * np.log(jph / j0_rad + 1.0) + model.ideality_srh * kT * np.log(
        jph / j0_srh + 1.0) + 0.5

    def f(v: float) -> float:
        return float(current_density(model, v, temperature_k)[0])

    lo, hi = 0.0, v_hi
    for _ in range(80):
        if f(hi) < 0:
            break
        hi *= 1.5
    else:
        raise RuntimeError(f"could not bracket Voc for subcell {model.name!r}")
    return bisect(f, lo, hi, tol=1e-11), None


def maximum_power_point(model: SubcellModel, temperature_k: float) -> dict:
    """MPP of the subcell: (Vmp, Jmp, Pmax, FF)."""
    voc = open_circuit_voltage(model, temperature_k)
    jsc = float(current_density(model, 0.0, temperature_k)[0])

    def power(v: float) -> float:
        return v * float(current_density(model, v, temperature_k)[0])

    vmp, pmax = golden_section_max(power, 0.0, voc, tol=1e-10)
    jmp = float(current_density(model, vmp, temperature_k)[0])
    ff = pmax / (voc * jsc) if voc * jsc > 0 else float("nan")
    return {"voc_v": voc, "jsc_ma_cm2": jsc, "vmp_v": vmp, "jmp_ma_cm2": jmp,
            "pmax_mw_cm2": pmax, "ff": ff}


def current_at_voltage(model: SubcellModel, voltage_v: float,
                       temperature_k: float) -> float:
    return float(current_density(model, voltage_v, temperature_k)[0])


def voltage_at_current(model: SubcellModel, current_ma_cm2: float,
                       temperature_k: float) -> float:
    """Bias [V] at which the subcell carries ``current_ma_cm2`` (tandem use)."""
    voc = open_circuit_voltage(model, temperature_k)

    def f(v: float) -> float:
        return current_at_voltage(model, v, temperature_k) - current_ma_cm2

    lo, hi = 0.0, max(voc, 0.05)
    if f(lo) < 0:
        # current already exceeds the short-circuit current (should not happen
        # if the tandem current is limited correctly); extend downward
        lo = -abs(current_ma_cm2) * model.rs_ohm_cm2 / 1000.0 - 0.05
        if f(lo) < 0:
            raise RuntimeError("could not bracket the operating voltage")
    if f(hi) > 0:
        hi = hi * 1.2 + 0.05
        if f(hi) > 0:
            raise RuntimeError("could not bracket the operating voltage above Voc")
    return bisect(f, lo, hi, tol=1e-11)
