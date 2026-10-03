"""APMT V1.9 — machine-checkable full-stack optical (R/T/A) evidence for G5.

Audit item F: gate G5 must not depend on a caller-supplied scalar
(``rta_max_dev``). This module defines the evidence object the gate consumes
and the checks it performs:

    closure            max |R + T + A - 1| per wavelength
    alignment          R, T and A are defined on one identical wavelength grid
    units              explicitly declared as fractions (not percent)
    coverage           fraction of the required 300-1250 nm window measured
    missing_regions    wavelength intervals with no data, reported explicitly
    uncertainty        per-wavelength uncertainties present
    monotone/positivity R,T,A >= 0

A stack that passes closure but covers only 400-900 nm (or that is missing an
uncertainty estimate) is NOT full-stack closure evidence, and the gate now
sees that distinction instead of a single number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class OpticalClosureEvidence:
    """Measured or simulated R/T/A of a complete stack, on one grid."""

    wavelength_nm: np.ndarray
    reflectance: np.ndarray
    transmittance: np.ndarray
    absorptance: np.ndarray
    units: str = "fraction"
    uncertainty_r: Optional[np.ndarray] = None
    uncertainty_t: Optional[np.ndarray] = None
    uncertainty_a: Optional[np.ndarray] = None
    category: str = "EXPERIMENTAL"
    source_id: str = ""
    device_id: str = ""
    notes: str = ""

    REQUIRED_WINDOW_NM = (300.0, 1250.0)

    # -- individual checks --------------------------------------------------
    def max_closure_error(self) -> float:
        resid = self.reflectance + self.transmittance + self.absorptance - 1.0
        return float(np.max(np.abs(resid)))

    @property
    def sizes_match(self) -> bool:
        n = self.wavelength_nm.size
        return (self.reflectance.size == n and self.transmittance.size == n
                and self.absorptance.size == n)

    @property
    def aligned(self) -> bool:
        """R/T/A share the wavelength grid (by construction: single array)."""
        return self.sizes_match and np.all(np.diff(self.wavelength_nm) > 0)

    @property
    def units_declared(self) -> bool:
        return self.units in ("fraction", "1")

    @property
    def uncertainty_present(self) -> bool:
        return all(u is not None and np.size(u) == self.wavelength_nm.size
                   for u in (self.uncertainty_r, self.uncertainty_t,
                             self.uncertainty_a))

    @property
    def physically_bounded(self) -> bool:
        return bool(np.all(self.reflectance >= -1e-9)
                    and np.all(self.transmittance >= -1e-9)
                    and np.all(self.absorptance >= -1e-9)
                    and np.all(self.reflectance <= 1.0 + 1e-9)
                    and np.all(self.transmittance <= 1.0 + 1e-9)
                    and np.all(self.absorptance <= 1.0 + 1e-9))

    def coverage_fraction(self, lo_nm: float = 300.0, hi_nm: float = 1250.0) -> float:
        """Fraction of the required window with at least one data point within 5 nm."""
        grid = np.linspace(lo_nm, hi_nm, 400)
        wl = self.wavelength_nm
        idx = np.clip(np.searchsorted(wl, grid), 0, wl.size - 1)
        left = np.clip(idx - 1, 0, wl.size - 1)
        nearest = np.minimum(np.abs(grid - wl[idx]), np.abs(grid - wl[left]))
        return float(np.mean(nearest <= 5.0))

    def missing_regions_nm(self, max_gap_nm: float = 20.0) -> list:
        """Explicit list of [lo, hi] intervals where the data have large gaps."""
        wl = self.wavelength_nm
        gaps = []
        for a, b in zip(wl[:-1], wl[1:]):
            if b - a > max_gap_nm:
                gaps.append([float(a), float(b)])
        if wl[0] > 300.0 + max_gap_nm:
            gaps.insert(0, [300.0, float(wl[0])])
        if wl[-1] < 1250.0 - max_gap_nm:
            gaps.append([float(wl[-1]), 1250.0])
        return gaps

    def is_valid_full_stack(self) -> bool:
        return (self.sizes_match and self.aligned and self.units_declared
                and self.physically_bounded and self.coverage_fraction() >= 0.95
                and not self.missing_regions_nm()
                and self.uncertainty_present)

    def to_dict(self) -> dict:
        return {
            "category": self.category, "source_id": self.source_id,
            "device_id": self.device_id, "units": self.units,
            "n_points": int(self.wavelength_nm.size),
            "wavelength_range_nm": [float(np.min(self.wavelength_nm)),
                                    float(np.max(self.wavelength_nm))],
            "max_closure_error": self.max_closure_error(),
            "coverage_fraction_300_1250": self.coverage_fraction(),
            "missing_regions_nm": self.missing_regions_nm(),
            "aligned": bool(self.aligned),
            "units_declared": bool(self.units_declared),
            "uncertainty_present": bool(self.uncertainty_present),
            "physically_bounded": bool(self.physically_bounded),
            "is_valid_full_stack": bool(self.is_valid_full_stack()),
            "notes": self.notes,
        }


def from_optics_result(result, category: str = "MODEL-OUTPUT",
                       source_id: str = "", device_id: str = "") -> OpticalClosureEvidence:
    """Build closure evidence from an :class:`apmt.optics.tmm.OpticsResult`.

    Model output can never serve as gate G5 evidence (it is self-consistent by
    construction); callers must supply ``category`` honestly and the gate's
    ``is_valid_full_stack`` check is applied to the arrays, not the label.
    """
    return OpticalClosureEvidence(
        wavelength_nm=np.asarray(result.wavelength_nm, dtype=float),
        reflectance=np.asarray(result.reflectance, dtype=float),
        transmittance=np.asarray(result.transmittance, dtype=float),
        absorptance=np.asarray(result.total_absorption, dtype=float),
        units="fraction", category=category, source_id=source_id,
        device_id=device_id,
        notes="derived from an optics solve; not a measurement")


def synthetic_evidence(n_points: int = 200, noise: float = 0.0,
                       seed: int = 0, missing_window=None,
                       with_uncertainty: bool = True) -> OpticalClosureEvidence:
    """Build synthetic full-stack evidence (used by tests and the synthetic lab).

    The construction guarantees R+T+A = 1 by building A as the complement of
    R+T, so a test can selectively break one property (units, coverage,
    uncertainty, closure) and check that the gate reacts.
    """
    rng = np.random.default_rng(seed)
    wl = np.linspace(300.0, 1250.0, n_points)
    R = 0.10 + 0.05 * np.sin(wl / 120.0)
    T = 0.05 + 0.02 * np.cos(wl / 90.0)
    if missing_window is not None:
        keep = ~((wl >= missing_window[0]) & (wl <= missing_window[1]))
        wl, R, T = wl[keep], R[keep], T[keep]
    A = 1.0 - R - T
    if noise:
        R = np.clip(R + rng.normal(0, noise, R.size), 0, 1)
        T = np.clip(T + rng.normal(0, noise, T.size), 0, 1)
    u = np.full(wl.size, 0.01) if with_uncertainty else None
    return OpticalClosureEvidence(wl, R, T, A, "fraction", u, u, u,
                                 category="EXPERIMENTAL" if with_uncertainty else "MODEL-ASSUMED",
                                 source_id="SYNTHETIC-LAB", device_id="SYN-1")
