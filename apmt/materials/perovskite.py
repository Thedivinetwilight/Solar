"""APMT V1.9 — perovskite absorber optical model (parameterized dispersion).

The model is deliberately *simple and explicit* so that its assumptions can be
tested and perturbed rather than hidden:

  absorption coefficient
      alpha(E) = alpha_peak * [ sqrt(max(E - Eg, 0)/1eV)             (interband)
                              + sqrt(Eu/1eV) * exp((E - Eg)/Eu) ]    (Urbach)

      The square-root interband term is the parabolic-band (Tauc) form; the
      Urbach term is continuous at Eg (a simple sqrt-only form is not), and it
      is negligible more than ~5*Eu above the gap.  `alpha_peak` is a
      registered parameter; the default reproduces the ~1e5 cm^-1
      above-gap absorption of MAPbI3-type absorbers.

  refractive index
      Wemple-DiDomenico single oscillator:
          n^2(E) - 1 = Ed * E0 / (E0^2 - E^2),  Ed = (n_inf^2 - 1) * E0,
          E0 = Eg + oscillator_ev
      Because the WD form diverges at E -> E0, (E0^2 - E^2) is floored at
      floor_frac * E0^2 (default 0.25), which caps n where the material is
      strongly absorbing anyway.  This is a documented model limitation
      (checked in tests: n stays in [1.5, 4.5] over the solar window).

  extinction coefficient from alpha: k = alpha*lambda/(4*pi).

Reference data used for the default shape parameters (LITERATURE-DERIVED):
  * MAPbI3 / triple-cation perovskites: n ~ 2.3-2.6 in the near IR, Urbach
    energies 12-25 meV, alpha > 1e5 cm^-1 above the gap;
  * the 1.68 eV champion composition of Al-Ashouri et al. (2020).
"""
from __future__ import annotations

import numpy as np

from ..core.constants import H_J_S, C_M_S, Q_C
from .silicon import OpticalConstants


def photon_energy_ev(wavelength_nm: np.ndarray) -> np.ndarray:
    wl = np.asarray(wavelength_nm, dtype=float)
    return H_J_S * C_M_S / (wl * 1e-9) / Q_C


def perovskite_alpha_cm1(eg_ev: float, alpha_peak_cm1: float, urbach_mev: float,
                         wavelength_nm: np.ndarray) -> np.ndarray:
    """Absorption coefficient [cm^-1] of the perovskite absorber.

    Piecewise, continuous and monotone:

        E <= Eg + Eu :  alpha = alpha_peak * sqrt(Eu) * exp((E-Eg)/Eu)   (Urbach)
        E >  Eg + Eu :  alpha = alpha_peak * sqrt(E-Eg)                  (Tauc)

    The two branches match exactly at E = Eg + Eu (both give
    alpha_peak*sqrt(Eu)), so the model has no discontinuity and no free
    matching constant. Restricting the exponential Urbach form to the edge
    region is essential: an exponential extended above the gap would dominate
    the interband term and produce unphysical absorption coefficients
    (>1e10 cm^-1 detected by an internal validation test in V1.9).
    """
    E = photon_energy_ev(wavelength_nm)
    Eu = max(urbach_mev, 1e-6) * 1e-3
    edge = eg_ev + Eu
    urbach = np.sqrt(Eu) * np.exp(np.clip((E - eg_ev) / Eu, -700.0, 700.0))
    tauc = np.sqrt(np.maximum(E - eg_ev, 0.0))
    shape = np.where(E <= edge, urbach, tauc)
    alpha = alpha_peak_cm1 * shape
    if np.any(alpha > 5.0e6):
        raise ValueError(
            "perovskite absorption coefficient exceeds 5e6 cm^-1; the dispersion "
            "parameters are outside the model's validity range")
    return alpha


def perovskite_index(eg_ev: float, alpha_peak_cm1: float, urbach_mev: float,
                     n_inf: float, oscillator_ev: float,
                     wavelength_nm: np.ndarray, floor_frac: float = 0.25
                     ) -> OpticalConstants:
    """Complex refractive index of the perovskite absorber."""
    wl = np.asarray(wavelength_nm, dtype=float)
    E = photon_energy_ev(wl)
    alpha = perovskite_alpha_cm1(eg_ev, alpha_peak_cm1, urbach_mev, wl)
    k = alpha * (wl * 1e-7) / (4.0 * np.pi)

    E0 = max(eg_ev + oscillator_ev, 0.2)
    Ed = max(n_inf ** 2 - 1.0, 1e-3) * E0
    denom = np.maximum(E0 ** 2 - E ** 2, floor_frac * E0 ** 2)
    n = np.sqrt(1.0 + Ed * E0 / denom)

    prov = ("parameterized perovskite dispersion: Tauc+Urbach alpha, "
            "Wemple-DiDomenico index (see apmt/materials/perovskite.py docstring)")
    return OpticalConstants(wl, n, k, np.zeros_like(wl, dtype=bool), prov)


def perovskite_bandgap_temperature(eg_at_reference_ev: float, temperature_k: float,
                                   reference_k: float, coefficient_ev_k: float) -> float:
    """Linear temperature-dependent bandgap: Eg(T) = Eg(T_ref) + dEg/dT*(T-T_ref)."""
    return eg_at_reference_ev + coefficient_ev_k * (temperature_k - reference_k)


def urbach_absorption_edge_nm(eg_ev: float) -> float:
    """Wavelength [nm] of the band edge (alpha = Eg)."""
    return float(H_J_S * C_M_S / (eg_ev * Q_C) * 1e9)
