"""APMT V1.9 — detailed-balance (Shockley-Queisser) reference model.

Level 0 of the multi-fidelity hierarchy: the radiative limit. It is the
*ceiling* against which every higher-fidelity model is compared, and it is
computed from the generalized Planck law without any fitted parameters:

    J(V) = q [ Phi_abs(Eg) - Phi_emit(V, Eg, T_cell) ]

    Phi_abs  = integral over the incident spectrum of photons with E >= Eg
               (step-function absorptivity, unit internal quantum efficiency)
    Phi_emit = (2 pi / h^3 c^2) * integral_{Eg}^{inf}
                   E^2 / (exp((E - qV)/kT) - 1) dE

with emission into one hemisphere (2 pi solid angle) at the cell temperature
and the zero-point (1/2 h nu) term omitted, i.e. the standard SQ convention.

Known-answer checks (tests/test_detailed_balance.py):
  * AM1.5G one sun, T = 300 K: the optimum bandgap lies in 1.25-1.45 eV and the
    optimum efficiency is 32.5-34.5 % (Shockley-Queisser 1961 / standard
    textbook values for AM1.5G);
  * the optimum is well defined (efficiency falls off on both sides);
  * J_sc at V = 0 equals the above-gap photon current (no double counting);
  * V_oc < Eg/q always, and V_oc decreases with temperature at fixed Eg.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..core.constants import H_J_S, C_M_S, Q_C, K_B_EV_K
from ..core.numerics import golden_section_max, trapz
from ..spectra.reference import Spectrum, reference


def blackbody_photon_flux_hemisphere(E_ev: np.ndarray, temperature_k: float,
                                     v_bias_v: float = 0.0) -> np.ndarray:
    """Spectral photon flux [photons s^-1 m^-2 eV^-1] emitted into 2 pi sr."""
    E = np.asarray(E_ev, dtype=float)
    kT = K_B_EV_K * max(temperature_k, 1.0)
    x = np.clip((E - v_bias_v) / kT, -50.0, 700.0)
    with np.errstate(over="ignore", divide="ignore"):
        occ = 1.0 / (np.exp(x) - 1.0)
    # occupation must be non-negative (Bose-Einstein with chemical potential);
    # for E < qV the truncated expression is replaced by 0 rather than a
    # negative occupation, which is the standard convention.
    occ = np.where(x > 0, occ, 0.0)
    e_j = E * Q_C                                   # photon energy in joules
    pref_j = 2.0 * np.pi * e_j ** 2 / (H_J_S ** 3 * C_M_S ** 2)   # per joule
    return pref_j * Q_C * occ                       # convert to per eV


@dataclass(frozen=True)
class SQResult:
    eg_ev: float
    jsc_ma_cm2: float
    voc_v: float
    ff: float
    pce_pct: float
    vmp_v: float
    jmp_ma_cm2: float
    temperature_k: float = 300.0
    concentration: float = 1.0
    category: str = "DETAILED-BALANCE (radiative limit, no fitted parameters)"

    def to_dict(self) -> dict:
        return {
            "eg_ev": self.eg_ev, "jsc_ma_cm2": self.jsc_ma_cm2, "voc_v": self.voc_v,
            "ff": self.ff, "pce_pct": self.pce_pct, "vmp_v": self.vmp_v,
            "jmp_ma_cm2": self.jmp_ma_cm2, "temperature_k": self.temperature_k,
            "concentration": self.concentration, "category": self.category,
        }


def _emitted_current(eg_ev: float, temperature_k: float, v_bias_v: float,
                     n_points: int = 4000, e_max_ev: float = 4.5) -> float:
    """Radiative recombination current density [A/m^2] at bias V."""
    e_lo = max(eg_ev, 1e-3)
    E = np.linspace(e_lo, max(e_max_ev, e_lo + 1.0), n_points)
    flux = blackbody_photon_flux_hemisphere(E, temperature_k, v_bias_v)
    return Q_C * trapz(flux, E)


def detailed_balance_single_junction(eg_ev: float, spectrum: Optional[Spectrum] = None,
                                     temperature_k: float = 300.0,
                                     concentration: float = 1.0,
                                     n_emission_points: int = 4000) -> SQResult:
    """Radiative-limit single junction under an arbitrary incident spectrum."""
    sp = spectrum or reference()
    if eg_ev <= 0.1 or eg_ev > 3.5:
        raise ValueError(f"bandgap {eg_ev} eV outside the model's validity range")
    if concentration <= 0:
        raise ValueError("concentration must be positive")
    if temperature_k <= 0:
        raise ValueError("temperature must be positive")

    ph_abs = sp.above_gap_photon_flux(eg_ev) * concentration
    jsc = 0.1 * Q_C * ph_abs                      # mA/cm2

    # NOTE on concentration: the absorbed photon flux scales with the
    # concentration, but the *emitted* (recombination) flux does not: emission
    # stays limited by the cell's étendue (one hemisphere) and grows only
    # through the bias-dependent Bose-Einstein factor. Scaling emission with
    # concentration would silently cancel the concentration gain.
    def current_a_m2(v: float) -> float:
        return Q_C * ph_abs - _emitted_current(eg_ev, temperature_k, v,
                                               n_emission_points)

    def current_ma_cm2(v: float) -> float:
        return 0.1 * current_a_m2(v)

    # V_oc by bisection on a bracket that must straddle the zero crossing
    lo, hi = 0.0, max(eg_ev / Q_C * Q_C, 0.5)
    hi = min(eg_ev + 0.5, 4.0)
    f_lo, f_hi = current_ma_cm2(lo), current_ma_cm2(hi)
    if f_lo <= 0:
        raise RuntimeError("non-positive short-circuit current: check spectrum/bandgap")
    if f_hi > 0:
        # widen once (never happens for physical parameters, kept for safety)
        hi, f_hi = hi * 2.0, current_ma_cm2(hi * 2.0)
        if f_hi > 0:
            raise RuntimeError("could not bracket V_oc in detailed balance")
    voc = _bisect(current_ma_cm2, lo, hi)

    def power(v: float) -> float:
        """Power density [mW/cm2] delivered at bias v (positive on (0, Voc))."""
        return v * current_ma_cm2(v)

    vmp, pmax = golden_section_max(power, 0.0, voc, tol=1e-9)
    jmp = current_ma_cm2(vmp)
    # units: V * mA/cm2 = mW/cm2; incident power = concentration * 100 mW/cm2,
    # so the efficiency in percent equals P / concentration numerically.
    pce = pmax / concentration
    ff = pmax / (voc * jsc) if voc * jsc > 0 else float("nan")
    return SQResult(eg_ev, jsc, voc, ff, pce, vmp, jmp, temperature_k, concentration)


def _bisect(f, lo: float, hi: float, tol: float = 1e-10, max_iter: int = 200) -> float:
    f_lo, f_hi = f(lo), f(hi)
    if (f_lo > 0) == (f_hi > 0):
        raise ValueError("bisection requires a sign-changing bracket")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if f_mid == 0.0 or (hi - lo) < tol:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi, f_hi = mid, f_mid
    return 0.5 * (lo + hi)


def sq_landscape(spectrum: Optional[Spectrum] = None, eg_lo: float = 0.8,
                 eg_hi: float = 2.0, n: int = 121, temperature_k: float = 300.0,
                 concentration: float = 1.0) -> list:
    """Scan the radiative limit over bandgap (returns a list of SQResult)."""
    out = []
    for eg in np.linspace(eg_lo, eg_hi, n):
        out.append(detailed_balance_single_junction(eg, spectrum, temperature_k,
                                                    concentration))
    return out


def sq_optimum(spectrum: Optional[Spectrum] = None, eg_lo: float = 0.8,
               eg_hi: float = 2.0, temperature_k: float = 300.0,
               concentration: float = 1.0) -> SQResult:
    def f(eg: float) -> float:
        return detailed_balance_single_junction(eg, spectrum, temperature_k,
                                                concentration).pce_pct
    eg_opt, _ = golden_section_max(f, eg_lo, eg_hi, tol=1e-5)
    return detailed_balance_single_junction(eg_opt, spectrum, temperature_k, concentration)


def tandem_detailed_balance(eg_top: float, eg_bottom: float,
                            spectrum: Optional[Spectrum] = None,
                            temperature_k: float = 300.0,
                            concentration: float = 1.0) -> dict:
    """Radiative limit of a series-constrained two-terminal tandem (ideal).

    The tandem current is min(J_top, J_bottom) and the voltage is the sum of the
    two subcell voltages evaluated at that common current, so this is the
    textbook two-terminal radiative limit (no luminescent coupling; the coupled
    limit is handled in the device layer).
    """
    sp = spectrum or reference()
    if eg_bottom >= eg_top:
        raise ValueError("top cell bandgap must exceed the bottom cell bandgap")
    top = detailed_balance_single_junction(eg_top, sp, temperature_k, concentration)
    # bottom cell sees the photons transmitted by the top cell
    ph_below_top = sp.photon_flux() - sp.above_gap_photon_flux(eg_top)
    m = sp.wavelength_nm
    from ..spectra.reference import photon_energy_ev
    below = photon_energy_ev(m) < eg_top
    ph_bottom_abs = trapz(sp.photon_flux_density()[below], m[below]) * concentration
    jsc_bottom = 0.1 * Q_C * ph_bottom_abs
    j_common = min(top.jsc_ma_cm2, jsc_bottom)
    v_top = _voltage_at_current(top.eg_ev, j_common, sp, temperature_k, concentration, top.jsc_ma_cm2)
    v_bot = _voltage_at_current(eg_bottom, j_common, sp, temperature_k, concentration, jsc_bottom)
    v_oc_tandem = v_top + v_bot
    return {
        "eg_top_ev": eg_top, "eg_bottom_ev": eg_bottom,
        "jsc_top_ma_cm2": top.jsc_ma_cm2, "jsc_bottom_ma_cm2": jsc_bottom,
        "jsc_tandem_ma_cm2": j_common,
        "voc_tandem_v": v_oc_tandem,
        "note": "radiative limit, series-constrained, no luminescent coupling",
        "category": "DETAILED-BALANCE",
    }


def _voltage_at_current(eg: float, j_target_ma_cm2: float, sp: Spectrum,
                        temperature_k: float, concentration: float,
                        jsc_ma_cm2: float) -> float:
    """Invert the radiative J-V of one subcell at a fixed current."""
    ph_abs = sp.above_gap_photon_flux(eg) * concentration

    def f(v: float) -> float:
        return (0.1 * (Q_C * ph_abs - _emitted_current(eg, temperature_k, v))
                - j_target_ma_cm2)
    lo, hi = 0.0, min(eg + 0.5, 4.0)
    if f(lo) < 0:
        raise RuntimeError("target current exceeds the subcell's short-circuit current")
    if f(hi) > 0:
        raise RuntimeError("could not bracket the operating voltage")
    return _bisect(f, lo, hi)
