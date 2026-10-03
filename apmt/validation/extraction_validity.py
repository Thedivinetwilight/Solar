"""APMT V1.9 — machine-checkable validity classification of extracted curves.

Motivation (directive §2C): the 900-dpi re-render of Fig. 4E produced a 1-R
trace with a suspiciously tiny integrated value. Before that number can be used
or ignored, the extraction itself must be classified. This module implements
the classification with explicit, testable criteria so that a *failed
segmentation* can never be mistaken for a *physical result*.

Criteria (all must pass for USABLE):

  C1  point count            >= min_points (default 25)
  C2  wavelength coverage    the covered fraction of the curve's wavelength
                             span must be >= min_coverage (default 0.60)
  C3  amplitude plausibility the median value must lie in
                             [min_median_pct, max_median_pct] — for 1-R of a
                             planar tandem, 80-100 %; a trace whose median is
                             ~5 % has captured background, not the curve
  C4  dynamic range          p95 - p05 must be <= max_range_pct (a 1-R trace
                             should be nearly flat; a large spread indicates
                             contamination by other image features)
  C5  monotone plausibility  the fraction of strictly-increasing steps must be
                             below max_fraction_increasing (a 1-R curve is not
                             a monotone staircase)

The classification result records every criterion's measured value so that a
reviewer can see *why* a trace was rejected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ValidityResult:
    valid: bool
    reason: str
    detail: str
    metrics: dict

    def to_dict(self) -> dict:
        return {"valid": self.valid, "reason": self.reason, "detail": self.detail,
                "metrics": self.metrics}


def classify_one_minus_r(wavelength_nm: np.ndarray, values_pct: np.ndarray,
                         expect_plateau_pct: float = 95.0,
                         min_points: int = 25, min_coverage: float = 0.60,
                         min_median_pct: float = 80.0, max_median_pct: float = 100.5,
                         max_range_pct: float = 8.0,
                         max_fraction_increasing: float = 0.80) -> ValidityResult:
    """Classify a digitized 1-R trace as USABLE or INVALID.

    ``expect_plateau_pct`` documents the physically expected plateau (a
    well-anti-reflected planar tandem has 1-R around 95-98 %); it is used only
    for reporting the deviation, not as a pass criterion by itself.
    """
    wl = np.asarray(wavelength_nm, dtype=float)
    v = np.asarray(values_pct, dtype=float)
    n = int(v.size)
    metrics = {"n_points": n}

    if n == 0:
        return ValidityResult(False, "EMPTY_EXTRACTION",
                              "no pixels were traced at all", metrics)

    span_lo, span_hi = float(np.min(wl)), float(np.max(wl))
    expected_span = 300.0, 1250.0
    coverage = (span_hi - span_lo) / (expected_span[1] - expected_span[0])
    # fraction of the expected grid actually sampled (gap-aware)
    dense = np.linspace(expected_span[0], expected_span[1], 400)
    idx = np.searchsorted(wl, dense)
    idx = np.clip(idx, 0, n - 1)
    left = np.clip(idx - 1, 0, n - 1)
    nearest = np.minimum(np.abs(dense - wl[idx]), np.abs(dense - wl[left]))
    sampled_fraction = float(np.mean(nearest <= 10.0))

    med = float(np.median(v))
    p05, p95 = float(np.percentile(v, 5)), float(np.percentile(v, 95))
    rng = p95 - p05
    diffs = np.diff(v)
    frac_inc = float(np.mean(diffs > 0)) if diffs.size else 0.0

    metrics.update({
        "coverage_fraction_of_span": coverage,
        "sampled_fraction": sampled_fraction,
        "median_pct": med,
        "p05_pct": p05, "p95_pct": p95, "range_pct": rng,
        "fraction_increasing": frac_inc,
        "expected_plateau_pct": expect_plateau_pct,
    })

    # Hard violations make the trace INVALID for any use; weak support makes it
    # LOW_SUPPORT (usable only as a qualitative sanity check).
    hard, weak = [], []
    if not (min_median_pct <= med <= max_median_pct):
        hard.append(f"C3 median {med:.2f}% outside [{min_median_pct}, "
                    f"{max_median_pct}]%")
    if rng > max_range_pct:
        hard.append(f"C4 range {rng:.2f}% > {max_range_pct}%")
    if frac_inc > max_fraction_increasing:
        hard.append(f"C5 fraction increasing {frac_inc:.2f} > "
                    f"{max_fraction_increasing}")
    if n < min_points:
        weak.append(f"C1 point count {n} < {min_points}")
    if sampled_fraction < min_coverage:
        weak.append(f"C2 sampled fraction {sampled_fraction:.2f} < {min_coverage}")

    if hard:
        return ValidityResult(False, "INVALID_EXTRACTION",
                              "; ".join(hard + weak), metrics)
    if weak:
        return ValidityResult(False, "LOW_SUPPORT",
                              "; ".join(weak), metrics)
    dev = abs(med - expect_plateau_pct)
    return ValidityResult(True, "USABLE",
                          f"passed all criteria; median {med:.2f}% vs expected "
                          f"plateau {expect_plateau_pct:.1f}% (deviation {dev:.2f}%)",
                          metrics)


def classify_eqe_branch(wavelength_nm: np.ndarray, values_pct: np.ndarray,
                        max_eqe_pct: float = 100.0) -> ValidityResult:
    """Classify a digitized EQE branch (basic physical sanity only)."""
    wl = np.asarray(wavelength_nm, dtype=float)
    v = np.asarray(values_pct, dtype=float)
    metrics = {"n_points": int(v.size), "max_pct": float(np.max(v)) if v.size else None,
               "min_pct": float(np.min(v)) if v.size else None}
    if v.size == 0:
        return ValidityResult(False, "EMPTY_EXTRACTION", "no points", metrics)
    if np.any(v < -0.5):
        return ValidityResult(False, "INVALID_EXTRACTION",
                              "negative EQE values present", metrics)
    if np.max(v) > max_eqe_pct + 1.0:
        return ValidityResult(False, "INVALID_EXTRACTION",
                              f"EQE above {max_eqe_pct}% (physical bound)", metrics)
    if v.size < 10:
        return ValidityResult(False, "LOW_SUPPORT",
                              f"only {v.size} points; use with caution", metrics)
    return ValidityResult(True, "USABLE", "EQE branch within physical bounds", metrics)
