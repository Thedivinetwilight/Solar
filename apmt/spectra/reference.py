"""APMT V1.9 — reference spectra layer.

Layer 1 of the platform architecture (directive §3). Provides the immutable
:class:`Spectrum` object, the vendored ASTM G173-03 AM1.5G global-tilt table
(NLR distribution), photon-flux conversions, and spectrum-perturbation models
(rigid shift, scaling, LED-like band narrowing) used by the uncertainty and
spectral-mismatch analyses.

Canonical units: wavelength [nm], spectral irradiance [W m^-2 nm^-1],
integrated irradiance [W m^-2], current density [mA cm^-2].
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..core.constants import C_M_S, H_J_S, Q_C
from ..core.numerics import trapz
from ..core.units import check_dimension, q

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENDOR_NPZ = os.path.join(_REPO, "data", "spectra", "astm_g173_am15g_nlr.npz")
_VENDOR_META = os.path.join(_REPO, "data", "spectra", "astm_g173_am15g_nlr.meta.json")

# Historical project constants (V1.1 / V1.2.2), HANDOFF-QUOTED in apmt.ledger
KNOWN_IRRADIANCE_WM2 = 1000.370656
KNOWN_PHOTON_CURRENT_MA_CM2 = 68.982857
KNOWN_FINGERPRINT = "59040a85966f9c13ad394443bbafa5eb654df6aca58338a7a763f341b53d0eb0"


def photon_flux_density(wavelength_nm: np.ndarray, irradiance_w_m2_nm: np.ndarray) -> np.ndarray:
    """Spectral photon flux [photons s^-1 m^-2 nm^-1] from spectral irradiance."""
    wl = np.asarray(wavelength_nm, dtype=float)
    irr = np.asarray(irradiance_w_m2_nm, dtype=float)
    return irr * wl * 1e-9 / (H_J_S * C_M_S)


def photon_energy_ev(wavelength_nm: np.ndarray) -> np.ndarray:
    """Photon energy [eV] for vacuum wavelengths [nm]."""
    wl = np.asarray(wavelength_nm, dtype=float)
    return H_J_S * C_M_S / (wl * 1e-9) / Q_C


@dataclass(frozen=True)
class Spectrum:
    """Immutable reference spectrum with provenance and validation.

    Attributes
    ----------
    wavelength_nm : ascending vacuum wavelengths [nm]
    irradiance_w_m2_nm : spectral irradiance [W m^-2 nm^-1]
    """

    wavelength_nm: np.ndarray
    irradiance_w_m2_nm: np.ndarray
    standard: str
    provenance: dict = field(default_factory=dict)

    # -- validation ---------------------------------------------------------
    def __post_init__(self):
        wl = np.asarray(self.wavelength_nm, dtype=float)
        irr = np.asarray(self.irradiance_w_m2_nm, dtype=float)
        if wl.ndim != 1 or irr.ndim != 1 or wl.size != irr.size:
            raise ValueError("spectrum arrays must be 1-D and of equal length")
        if wl.size < 10:
            raise ValueError("spectrum too short to integrate")
        if not np.all(np.diff(wl) > 0):
            raise ValueError("wavelength grid must be strictly increasing")
        if np.any(irr < 0):
            raise ValueError("negative spectral irradiance is unphysical")
        if float(np.max(wl)) < 1000.0:
            raise ValueError("spectrum does not reach 1000 nm: insufficient for Si")
        object.__setattr__(self, "wavelength_nm", wl)
        object.__setattr__(self, "irradiance_w_m2_nm", irr)

    # -- basic integrals ----------------------------------------------------
    def mask(self, lo_nm: float, hi_nm: float) -> np.ndarray:
        return (self.wavelength_nm >= lo_nm) & (self.wavelength_nm <= hi_nm)

    def integrated_irradiance(self, lo_nm: float = 280.0, hi_nm: float = 4000.0) -> float:
        m = self.mask(lo_nm, hi_nm)
        return trapz(self.irradiance_w_m2_nm[m], self.wavelength_nm[m])

    def photon_flux(self, lo_nm: float = 280.0, hi_nm: float = 5000.0) -> float:
        """Integrated photon flux [photons s^-1 m^-2]."""
        m = self.mask(lo_nm, hi_nm)
        return trapz(photon_flux_density(self.wavelength_nm[m], self.irradiance_w_m2_nm[m]),
                     self.wavelength_nm[m])

    def jph_100eqe(self, lo_nm: float = 280.0, hi_nm: float = 5000.0) -> float:
        """Photocurrent [mA cm^-2] for EQE = 1 over the window."""
        return 0.1 * Q_C * self.photon_flux(lo_nm, hi_nm)

    def photon_flux_density(self) -> np.ndarray:
        return photon_flux_density(self.wavelength_nm, self.irradiance_w_m2_nm)

    def data_fingerprint(self) -> str:
        import hashlib
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(self.wavelength_nm).tobytes())
        h.update(np.ascontiguousarray(self.irradiance_w_m2_nm).tobytes())
        return h.hexdigest()

    # -- transformations (produce new immutable spectra) --------------------
    def scaled(self, factor: float) -> "Spectrum":
        return Spectrum(self.wavelength_nm, self.irradiance_w_m2_nm * float(factor),
                        self.standard, dict(self.provenance, scaled_by=float(factor)))

    def shifted(self, shift_nm: float) -> "Spectrum":
        """Rigid wavelength-axis shift (spectral-mismatch proxy)."""
        return Spectrum(self.wavelength_nm + float(shift_nm), self.irradiance_w_m2_nm,
                        self.standard, dict(self.provenance, shifted_nm=float(shift_nm)))

    def band_limited(self, lo_nm: float, hi_nm: float) -> "Spectrum":
        """Zero the spectrum outside a band (LED / filtered illumination proxy)."""
        m = self.mask(lo_nm, hi_nm)
        irr = np.where(m, self.irradiance_w_m2_nm, 0.0)
        return Spectrum(self.wavelength_nm, irr, self.standard,
                        dict(self.provenance, band_nm=(lo_nm, hi_nm)))

    def rescaled_to_irradiance(self, target_w_m2: float) -> "Spectrum":
        cur = self.integrated_irradiance(280.0, 4000.0)
        return self.scaled(float(target_w_m2) / cur)

    # -- physics helpers ----------------------------------------------------
    def eqe_current(self, eqe: np.ndarray, eqe_wl_nm: np.ndarray,
                    lo_nm: float = 300.0, hi_nm: float = 1250.0) -> float:
        """Photocurrent [mA cm^-2] of an EQE curve under this spectrum."""
        m = self.mask(lo_nm, hi_nm)
        wl = self.wavelength_nm[m]
        flux = self.photon_flux_density()[m]
        e = np.interp(wl, np.asarray(eqe_wl_nm, dtype=float),
                      np.asarray(eqe, dtype=float), left=0.0, right=0.0)
        check_dimension(q(float(np.max(e)) if e.size else 0.0, "1"), "1", "EQE")
        return 0.1 * Q_C * trapz(flux * e, wl)

    def above_gap_photon_flux(self, eg_ev: float, lo_nm: float = 280.0,
                              hi_nm: float = 5000.0) -> float:
        """Photon flux [photons s^-1 m^-2] with photon energy > Eg."""
        m = self.mask(lo_nm, hi_nm)
        wl = self.wavelength_nm[m]
        flux = self.photon_flux_density()[m]
        above = photon_energy_ev(wl) >= eg_ev
        wl2, flux2 = wl[above], flux[above]
        if wl2.size < 2:
            return 0.0
        return trapz(flux2, wl2)

    def above_gap_current(self, eg_ev: float, lo_nm: float = 280.0,
                          hi_nm: float = 5000.0) -> float:
        """Absorbed-photon current density [mA cm^-2] with hnu > Eg."""
        return 0.1 * Q_C * self.above_gap_photon_flux(eg_ev, lo_nm, hi_nm)


class SpectrumProvenanceError(RuntimeError):
    pass


def load_reference_spectrum(allow_library_fallback: bool = True) -> Spectrum:
    """Load the vendored ASTM G173-03 AM1.5G global table.

    Raises if the vendored table does not reproduce the historical project
    constants (silent spectral drift is impossible by construction).
    """
    if os.path.exists(_VENDOR_NPZ):
        d = np.load(_VENDOR_NPZ)
        wl = d["wavelength_nm"].astype(float)
        irr = d["irradiance_w_m2_nm"].astype(float)
        prov = {"source": "vendored NLR ASTM G173-03 table (data/spectra/)",
                "file": os.path.relpath(_VENDOR_NPZ, _REPO)}
        if os.path.exists(_VENDOR_META):
            with open(_VENDOR_META) as f:
                prov.update(json.load(f))
        sp = Spectrum(wl, irr, "ASTM G173-03 AM1.5G global tilt (37 deg)", prov)
    elif allow_library_fallback:
        from pvlib.spectrum import get_reference_spectra
        s = get_reference_spectra()
        sp = Spectrum(np.asarray(s.index, float), np.asarray(s["global"], float),
                      "ASTM G173-03 AM1.5G global tilt (37 deg)",
                      {"source": "pvlib library fallback (vendored table missing)"})
    else:
        raise SpectrumProvenanceError(
            "vendored spectrum missing and library fallback disabled; run "
            "tools/vendor_spectrum.py --write")

    irr_int = sp.integrated_irradiance(280.0, 4000.0)
    j100 = sp.jph_100eqe(280.0, 5000.0)
    if round(irr_int, 6) != KNOWN_IRRADIANCE_WM2 or round(j100, 6) != KNOWN_PHOTON_CURRENT_MA_CM2:
        raise SpectrumProvenanceError(
            f"spectrum does not reproduce the V1.1/V1.2.2 project constants: "
            f"{irr_int!r} W/m2, {j100!r} mA/cm2")
    return sp


_CACHE: Optional[Spectrum] = None


def reference() -> Spectrum:
    """Cached reference spectrum (immutable object; safe to share)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = load_reference_spectrum()
    return _CACHE
