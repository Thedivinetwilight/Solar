"""APMT V1.9 — silicon optical model (tabulated literature n,k).

Data: Green & Keevers (1995) table vendored by tools/vendor_silicon_optics.py
(300-1200 nm, 10 nm step). Outside the table the model extrapolates with an
explicit policy, because silent extrapolation is exactly the kind of hidden
assumption that produces fake results:

* below 300 nm  : clamp to the 300 nm constants (strongly absorbing; the error
                  in R/T/A is small because k is already >> 1);
* above 1200 nm : k from the last tabulated alpha with an exponential tail
                  exp(-(lambda-1200)/tail_nm); the tail length is a DOCUMENTED
                  SHAPE CONSTANT (SI_SUBGAP_TAIL_NM = 25 nm, not a registered
                  parameter -- V1.9-H doc fix) and the extrapolated region is
                  flagged in the returned object.

The model also provides a Lambertian path-length enhancement factor so that
"light trapping" is an explicit, parameterised design choice rather than a
hidden constant.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

from ..core.constants import K_B_EV_K

# Documented shape constant for the above-table exponential tail
# exp(-(lambda-1200)/tail_nm). NOT a registered parameter (V1.9-H audit).
SI_SUBGAP_TAIL_NM = 25.0

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_NPZ = os.path.join(_REPO, "data", "materials", "silicon_green_keevers_1995.npz")
_META = os.path.join(_REPO, "data", "materials", "silicon_green_keevers_1995.meta.json")


@dataclass(frozen=True)
class OpticalConstants:
    """Complex refractive index result with an extrapolation flag."""

    wavelength_nm: np.ndarray
    n: np.ndarray
    k: np.ndarray
    extrapolated_mask: np.ndarray
    provenance: str

    @property
    def alpha_cm1(self) -> np.ndarray:
        return 4.0 * np.pi * self.k / (self.wavelength_nm * 1e-7)

    def has_extrapolation(self) -> bool:
        return bool(np.any(self.extrapolated_mask))


def _load_table() -> tuple:
    if not os.path.exists(_NPZ):
        raise FileNotFoundError(
            "silicon optical constants not vendored: run "
            "tools/vendor_silicon_optics.py --write")
    d = np.load(_NPZ)
    return d["wavelength_nm"], d["alpha_cm1"], d["n"], d["k"]


_TABLE = None


def _table() -> tuple:
    global _TABLE
    if _TABLE is None:
        _TABLE = _load_table()
    return _TABLE


def _log_interp(x, xp, fp):
    return np.interp(x, xp, np.log10(np.maximum(fp, 1e-12)))


def silicon_index(wavelength_nm: np.ndarray, tail_nm: float = SI_SUBGAP_TAIL_NM) -> OpticalConstants:
    """Interpolate tabulated Si n,k onto ``wavelength_nm`` (ascending or not)."""
    wl = np.asarray(wavelength_nm, dtype=float)
    twl, talpha, tn, tk = _table()
    extrap = (wl < twl[0]) | (wl > twl[-1])

    # n: linear interpolation, clamped outside the table
    n = np.interp(wl, twl, tn)

    # alpha: log-log interpolation inside the table (alpha spans 8 decades)
    la = np.interp(wl, twl, _log_interp(twl, twl, talpha))
    alpha = 10.0 ** la

    # sub-300 nm clamp
    below = wl < twl[0]
    alpha[below] = talpha[0]
    # above-gap tail
    above = wl > twl[-1]
    if np.any(above):
        alpha_last = talpha[-1]
        alpha[above] = alpha_last * np.exp(-(wl[above] - twl[-1]) / max(tail_nm, 1e-6))

    k = alpha * (wl * 1e-7) / (4.0 * np.pi)
    prov = ("Green & Keevers 1995 tabulated Si n,k (300-1200 nm) + explicit "
            f"extrapolation policy (tail_nm={tail_nm})")
    return OpticalConstants(wl, n, k, extrap, prov)


def silicon_alpha_cm1(wavelength_nm: np.ndarray, tail_nm: float = SI_SUBGAP_TAIL_NM) -> np.ndarray:
    return silicon_index(wavelength_nm, tail_nm).alpha_cm1


# ---------------------------------------------------------------------------
# Electrical/optical coupling helpers
# ---------------------------------------------------------------------------
def absorbance_single_pass(alpha_cm1: np.ndarray, thickness_um: float,
                           path_enhancement: float = 1.0) -> np.ndarray:
    """Fraction of light absorbed on a single (optionally enhanced) pass."""
    d_cm = thickness_um * 1e-4
    return 1.0 - np.exp(-np.maximum(alpha_cm1, 0.0) * d_cm * max(path_enhancement, 1e-9))


def lambertian_path_enhancement(n: float) -> float:
    """Ideal Lambertian (Yablonovitch) 4n^2 limit for a non-absorbing medium."""
    return 4.0 * n ** 2


def varshni_bandgap(eg0_ev: float, temperature_k: float,
                    alpha_ev_k: float = 4.73e-4, beta_k: float = 636.0) -> float:
    """Varshni bandgap of silicon (defaults reproduce 1.121 eV at 298 K)."""
    return eg0_ev - alpha_ev_k * temperature_k ** 2 / (temperature_k + beta_k)


def intrinsic_carrier_density_cm3(temperature_k: float, eg_ev: float = 1.121) -> float:
    """Approximate intrinsic carrier density n_i(T) of silicon [cm^-3].

    Uses the standard closed form with the effective density-of-states masses
    of Si (Nc(300K)=2.86e19, Nv(300K)=3.10e19 cm^-3) and a T^1.5 scaling.
    """
    nc = 2.86e19 * (temperature_k / 300.0) ** 1.5
    nv = 3.10e19 * (temperature_k / 300.0) ** 1.5
    # Varshni's Eg(T) can go non-physical outside the fitted temperature window;
    # clamp the EXPONENT only (never the reported bandgap) so that n_i stays real
    # and finite instead of silently producing a complex number (numpy would cast
    # that to a float with a ComplexWarning).
    # ±300 is the widest exponent that keeps n_i (and n_i^2 in the SRH slab model)
    # representable in float64 at any T the caller can reach; the electrical
    # validity envelope in apmt.device.thermal keeps callers inside the range
    # where this function is calibrated anyway.
    expo = min(max(-eg_ev / (2.0 * K_B_EV_K * temperature_k), -700.0), 300.0)
    return float(np.sqrt(nc * nv) * np.exp(expo))


def auger_lifetime_s(wafer_cm3: float, delta_n_cm3: float,
                     c_auger_cm6_s: float = 1.0e-30) -> float:
    """Auger-limited lifetime of silicon for a given injection level.

    tau_Auger = 1 / (C_n * n^2)-type process; here the symmetric approximation
    tau = 1/(C * delta_n^2) is used with the commonly quoted C = 1e-30 cm^6/s,
    which reproduces the Auger limit of high-quality Si in the 1e15-1e17 cm^-3
    injection range. Used only for the injection-dependence cross-check; it is
    not a calibrated model of the champion device.
    """
    d = max(float(delta_n_cm3), 1e6)
    return 1.0 / (float(c_auger_cm6_s) * d ** 2)
