"""APMT V1.8 — reference solar spectrum engine.

Spectrum: ASTM G173-03 AM1.5G global-tilt (37 deg), as distributed by NLR
(Netherlands Organisation for Applied Scientific Research) and shipped with
pvlib-python.

PROVENANCE RECOVERY (V1.8, 2026-09-30):
    The V1.1 project recorded an integrated irradiance of 1000.370656 W/m2 and
    V1.2.2 recorded an incident photon current of 68.982857 mA/cm2 (100% EQE,
    280-5000 nm). Both values are reproduced HERE to six decimals from the
    pvlib 0.16.1 NLR table (native 0.5 nm grid, 280-4000 nm). This identifies
    the project spectrum unambiguously:

        pvlib.spectrum.get_reference_spectra()   # standard='ASTM G173-03'
        column 'global', native grid 280.0..4000.0 nm, 2002 points.

    Source chain: ASTM G173-03 (2003) -> NLR Excel distribution
    (https://www.nlr.gov/grid/solar-resource/spectra-am1.5) -> pvlib-python
    0.16.1. The original project spectrum file was not re-uploaded to this
    repository (MISSING-VERIFIED in INCOMING/README.md); the six-decimal
    match above is the identification evidence.

Units: wavelength [nm], spectral irradiance [W m-2 nm-1].
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

Q_C = 1.602176634e-19        # elementary charge [C] (CODATA 2018, exact)
H_J_S = 6.62607015e-34       # Planck [J s] (CODATA 2018, exact)
C_M_S = 299792458.0          # speed of light [m/s] (exact)

# Known answers from the historical project (HANDOFF-QUOTED):
PROJECT_INTEGRATED_IRRADIANCE_WM2 = 1000.370656   # V1.1
PROJECT_INCIDENT_PHOTON_CURRENT_MA_CM2 = 68.982857  # V1.2.2 (100% EQE, 280-5000 nm)

SPECTRUM_PROVENANCE = {
    "standard": "ASTM G173-03, AM1.5G global tilt (37 deg)",
    "distribution": "NLR (Netherlands) Excel table, as shipped with pvlib-python",
    "distribution_url": "https://www.nlr.gov/grid/solar-resource/spectra-am1.5",
    "library": "pvlib-python 0.16.1",
    "native_grid": "280.0-4000.0 nm, 0.5 nm step, 2002 points",
    "identification": (
        "integrated irradiance 1000.370656 W/m2 and 100%-EQE incident photon "
        "current 68.982857 mA/cm2 (280-5000 nm) reproduce the V1.1/V1.2.2 "
        "project values to six decimals"
    ),
}


@dataclass(frozen=True)
class Spectrum:
    """Immutable reference spectrum with provenance."""
    wavelength_nm: np.ndarray
    irradiance_w_m2_nm: np.ndarray
    standard: str
    provenance: dict = field(default_factory=dict)

    def integrated_irradiance(self, lo_nm: float, hi_nm: float) -> float:
        m = (self.wavelength_nm >= lo_nm) & (self.wavelength_nm <= hi_nm)
        return float(np.trapezoid(self.irradiance_w_m2_nm[m], self.wavelength_nm[m]))

    def jph_100eqe(self, lo_nm: float, hi_nm: float) -> float:
        """Photocurrent [mA/cm2] from this spectrum assuming EQE = 1."""
        m = (self.wavelength_nm >= lo_nm) & (self.wavelength_nm <= hi_nm)
        wl, irr = self.wavelength_nm[m], self.irradiance_w_m2_nm[m]
        photon_flux = irr * wl * 1e-9 / (H_J_S * C_M_S)  # photons s-1 m-2 nm-1
        return 0.1 * Q_C * float(np.trapezoid(photon_flux, wl))  # A/m2 -> mA/cm2

    def data_fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.wavelength_nm).tobytes())
        h.update(np.ascontiguousarray(self.irradiance_w_m2_nm).tobytes())
        return h.hexdigest()


def load_astm_g173_am15g_global() -> Spectrum:
    """Load the project's reference spectrum (NLR/pvlib ASTME G173-03 table)."""
    from pvlib.spectrum import get_reference_spectra

    s = get_reference_spectra()  # native grid, standard='ASTM G173-03'
    return Spectrum(
        wavelength_nm=np.asarray(s.index, dtype=float),
        irradiance_w_m2_nm=np.asarray(s["global"], dtype=float),
        standard=SPECTRUM_PROVENANCE["standard"],
        provenance=dict(SPECTRUM_PROVENANCE),
    )


def jph_from_eqe(
    eqe: np.ndarray,
    eqe_wavelength_nm: np.ndarray,
    spectrum: Spectrum,
    lo_nm: float = 300.0,
    hi_nm: float = 1250.0,
) -> float:
    """AM1.5G-integrated photogenerated current [mA/cm2] from an EQE curve.

    The EQE array is interpolated onto the spectrum native grid (linear).
    Integration window defaults to 300-1250 nm, the window used by the V1.5/V1.6
    forensic integrations of Fig S32 / Fig 4E (HANDOFF-QUOTED: S32 17.110498
    at 300-1250 nm).
    """
    wl = spectrum.wavelength_nm
    m = (wl >= lo_nm) & (wl <= hi_nm)
    wl_m, irr = wl[m], spectrum.irradiance_w_m2_nm[m]
    eqe_m = np.interp(wl_m, eqe_wavelength_nm, eqe, left=0.0, right=0.0)
    photon_flux = irr * wl_m * 1e-9 / (H_J_S * C_M_S)
    return 0.1 * Q_C * float(np.trapezoid(photon_flux * eqe_m, wl_m))
