"""APMT V1.8 — AM1.5G-integrated Jph engine + uncertainty propagation.

Reproduces the project's historical integration convention:
  * spectrum: ASTM G173-03 AM1.5G global tilt (see apmt.spectrum)
  * default window: 300-1250 nm (V1.5/V1.6 window for Fig S32/Fig 4E;
    HANDOFF-QUOTED: S32 17.110498, Fig 4E 16.9019365812 at 300-1250 nm)
  * trapezoidal integration on the spectrum native grid.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spectrum import Spectrum, jph_from_eqe


@dataclass(frozen=True)
class JphResult:
    jph_ma_cm2: float
    lo_nm: float
    hi_nm: float
    irradiance_in_window_w_m2: float
    method: str = "trapezoid-on-native-grid"

    @property
    def uncertainty_band(self) -> None:  # placeholder for compatibility
        return None


def integrate_jph(
    eqe: np.ndarray,
    eqe_wl_nm: np.ndarray,
    spectrum: Spectrum,
    lo_nm: float = 300.0,
    hi_nm: float = 1250.0,
) -> JphResult:
    m = (spectrum.wavelength_nm >= lo_nm) & (spectrum.wavelength_nm <= hi_nm)
    irr = float(np.trapezoid(spectrum.irradiance_w_m2_nm[m],
                             spectrum.wavelength_nm[m]))
    return JphResult(
        jph_ma_cm2=jph_from_eqe(eqe, eqe_wl_nm, spectrum, lo_nm, hi_nm),
        lo_nm=lo_nm, hi_nm=hi_nm,
        irradiance_in_window_w_m2=irr,
    )


def shift_sensitivity(
    eqe: np.ndarray,
    eqe_wl_nm: np.ndarray,
    spectrum: Spectrum,
    shifts_nm: tuple = (-25, -10, 0, 10, 25),
    lo_nm: float = 300.0,
    hi_nm: float = 1250.0,
) -> dict:
    """Jph under wavelength-axis shifts of the EQE curve (V1.6 test).

    Returns {shift: Jph}. Used to show whether a shift can resolve a
    reported-vs-digitized gap (it could not in V1.6; this re-checks with the
    recovered spectrum).
    """
    out = {}
    for s in shifts_nm:
        out[s] = integrate_jph(eqe, eqe_wl_nm + s, spectrum, lo_nm, hi_nm).jph_ma_cm2
    return out


def window_sensitivity(
    eqe: np.ndarray,
    eqe_wl_nm: np.ndarray,
    spectrum: Spectrum,
    windows: tuple = ((300, 1100), (300, 1200), (300, 1250)),
) -> dict:
    return {f"{lo}-{hi}": integrate_jph(eqe, eqe_wl_nm, spectrum, lo, hi).jph_ma_cm2
            for lo, hi in windows}


def pixel_uncertainty_band(
    eqe: np.ndarray,
    eqe_wl_nm: np.ndarray,
    spectrum: Spectrum,
    dl_nm: float,
    deqe: float,
    lo_nm: float = 300.0,
    hi_nm: float = 1250.0,
) -> tuple:
    """Bounded Jph band from pixel-level digitization uncertainty.

    dl_nm: half-width of the wavelength-axis uncertainty (nm)
    deqe:  half-width of the EQE-axis uncertainty (fraction)
    The band combines the worst consistent directions (shift + vertical), a
    conservative bound, NOT a confidence interval.
    """
    eqe_hi = np.minimum(1.0, eqe + deqe)
    eqe_lo = np.maximum(0.0, eqe - deqe)
    j_hi = integrate_jph(eqe_hi, eqe_wl_nm + dl_nm, spectrum, lo_nm, hi_nm).jph_ma_cm2
    j_lo = integrate_jph(eqe_lo, eqe_wl_nm - dl_nm, spectrum, lo_nm, hi_nm).jph_ma_cm2
    return (min(j_hi, j_lo), max(j_hi, j_lo))
