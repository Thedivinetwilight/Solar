"""APMT V1.8 — EQE digitization pipeline (Objective A).

Three independent digitization methods are supported and each must run with
its own calibration/provenance record:

  1. manual          — manually selected points + axis calibration
  2. color_seg       — color/curve segmentation in RGB
  3. independent     — alternative route (grayscale/edge-follow or a
                       second segmentation color space), used as cross-check

HARD RULE (Objective A.10, V1.8): no vertical scaling or offset may be
applied to a digitized EQE curve unless a primary source explicitly
documents it. apply_transform() enforces this and raises otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


class UnsupportedRescaleError(RuntimeError):
    pass


@dataclass(frozen=True)
class AxisCalibration:
    """Affine pixel -> data calibration for one axis, with uncertainty."""
    pixel_a: float          # data = pixel_a * pixel + pixel_b
    pixel_b: float
    data_unit: str          # 'nm' or 'EQE'
    pixel_uncertainty: float = 1.0   # in pixel units
    calibration_evidence: str = ""   # which ticks were used

    def to_data(self, pixels: np.ndarray) -> np.ndarray:
        return self.pixel_a * np.asarray(pixels, dtype=float) + self.pixel_b

    def data_per_pixel(self) -> float:
        return abs(self.pixel_a)


@dataclass(frozen=True)
class DigitizationProvenance:
    """Full provenance of one digitization run (Objective A.2)."""
    source_id: str
    source_url: str
    source_sha256: str
    page: str
    figure: str
    crop_box_px: tuple
    image_resolution_px_per_inch: Optional[float]
    method: str                                   # manual | color_seg | independent
    branch_label: str                             # HZB Si | HZB perovskite | Sahli Si | Sahli perovskite | 1-R
    parameters: dict = field(default_factory=dict)
    pixel_uncertainty_nm: float = 1.0
    notes: str = ""


@dataclass
class DigitizedEQE:
    wavelength_nm: np.ndarray
    eqe: np.ndarray
    calibration_x: AxisCalibration
    calibration_y: AxisCalibration
    provenance: DigitizationProvenance

    def sorted(self) -> "DigitizedEQE":
        order = np.argsort(self.wavelength_nm)
        return DigitizedEQE(
            self.wavelength_nm[order], self.eqe[order],
            self.calibration_x, self.calibration_y, self.provenance,
        )


def digitize_manual(
    points_px: np.ndarray,
    cal_x: AxisCalibration,
    cal_y: AxisCalibration,
    prov: DigitizationProvenance,
) -> DigitizedEQE:
    """Method 1: manually selected (x_px, y_px) points through calibration."""
    if prov.method != "manual":
        raise ValueError("prov.method must be 'manual'")
    pts = np.asarray(points_px, dtype=float)
    return DigitizedEQE(cal_x.to_data(pts[:, 0]), cal_y.to_data(pts[:, 1]),
                        cal_x, cal_y, prov)


def _segmentize(xs: list, ys: list, max_gap_px: int, min_segment_cols: int):
    """Split the per-column trace into segments at gaps > max_gap_px and keep
    only segments with >= min_segment_cols columns (isolated legend dots are
    rejected; the curve is the long run)."""
    if not xs:
        return [], []
    segments = [[(xs[0], ys[0])]]
    for x, y in zip(xs[1:], ys[1:]):
        if x - segments[-1][-1][0] > max_gap_px:
            segments.append([])
        segments[-1].append((x, y))
    kept = [s for s in segments if len(s) >= min_segment_cols]
    if not kept:
        return [], []
    # keep the longest segment (the curve); legends are short runs
    longest = max(kept, key=len)
    return [p[0] for p in longest], [p[1] for p in longest]


def digitize_color_segmentation(
    image_rgb: np.ndarray,
    color_test: Callable[[np.ndarray], np.ndarray],
    cal_x: AxisCalibration,
    cal_y: AxisCalibration,
    prov: DigitizationProvenance,
    min_line_px: int = 2,
    max_gap_px: int = 4,
    min_segment_cols: int = 5,
) -> DigitizedEQE:
    """Method 2: segment the curve by color, then take per-column centroid.

    color_test(rgb_row_3array) -> bool mask for that row.
    The crop should separate the legend from the curve (recorded in
    provenance); additionally, short isolated runs (< min_segment_cols) and
    all but the longest x-continuous segment are rejected.

    Known limitation: if legend text shares a column with the curve AND the
    legend run length ties the curve run length, the per-column selection can
    pick the legend in that column and bridge into a separate segment. For
    such figures, use a crop that spatially separates the legend, or use the
    manual method for the affected branch.
    """
    if prov.method != "color_seg":
        raise ValueError("prov.method must be 'color_seg'")
    img = np.asarray(image_rgb)
    h, w, _ = img.shape
    raw_x, raw_y = [], []
    for x in range(w):
        idx = np.flatnonzero(color_test(img[:, x, :]))
        if idx.size < max(1, min_line_px // 2):
            continue
        # keep the longest contiguous run (the curve, not legend text)
        runs, start = [], idx[0]
        prev = idx[0]
        for i in idx[1:]:
            if i != prev + 1:
                runs.append((start, prev))
                start = i
            prev = i
        runs.append((start, prev))
        s, e = max(runs, key=lambda r: r[1] - r[0])
        if e - s + 1 < min_line_px:
            continue
        raw_x.append(x)
        raw_y.append(0.5 * (s + e))
    xs, ys = _segmentize(raw_x, raw_y, max_gap_px, min_segment_cols)
    if not xs:
        raise ValueError("color segmentation found no curve pixels")
    return DigitizedEQE(cal_x.to_data(np.array(xs)), cal_y.to_data(np.array(ys)),
                        cal_x, cal_y, prov)


def digitize_independent(
    image_rgb: np.ndarray,
    gray_curve_fn: Callable[[np.ndarray], Optional[float]],
    cal_x: AxisCalibration,
    cal_y: AxisCalibration,
    prov: DigitizationProvenance,
    max_gap_px: int = 4,
    min_segment_cols: int = 5,
) -> DigitizedEQE:
    """Method 3: independent route — grayscale/edge-based per-column trace.

    gray_curve_fn(column_vector) -> y pixel of the curve or None.
    Must use a different signal channel than method 2 (cross-check value).
    """
    if prov.method != "independent":
        raise ValueError("prov.method must be 'independent'")
    img = np.asarray(image_rgb)
    h, w, _ = img.shape
    raw_x, raw_y = [], []
    for x in range(w):
        y = gray_curve_fn(img[:, x, :])
        if y is None:
            continue
        raw_x.append(x)
        raw_y.append(y)
    xs, ys = _segmentize(raw_x, raw_y, max_gap_px, min_segment_cols)
    if not xs:
        raise ValueError("independent trace found no curve pixels")
    return DigitizedEQE(cal_x.to_data(np.array(xs)), cal_y.to_data(np.array(ys)),
                        cal_x, cal_y, prov)


def apply_transform(
    eqe: np.ndarray,
    scale: float = 1.0,
    offset: float = 0.0,
    documented_in_primary_source: bool = False,
    documentation_citation: str = "",
) -> np.ndarray:
    """Apply a vertical transform to an EQE array.

    RAISES UnsupportedRescaleError unless the transform is the identity OR a
    primary source explicitly documents it (Objective A.10). This is the
    machine-enforced version of the V1.6/V1.8 rule 'scaling NOT applied'.
    """
    is_identity = abs(scale - 1.0) < 1e-12 and abs(offset) < 1e-12
    if is_identity:
        return np.asarray(eqe, dtype=float)
    if not (documented_in_primary_source and documentation_citation.strip()):
        raise UnsupportedRescaleError(
            f"Refusing to apply vertical transform scale={scale}, "
            f"offset={offset} to EQE data: no primary-source documentation "
            f"provided. V1.8 rule (Objective A.10): no rescaling or offset "
            f"unless a primary source explicitly documents it."
        )
    return np.asarray(eqe, dtype=float) * scale + offset
