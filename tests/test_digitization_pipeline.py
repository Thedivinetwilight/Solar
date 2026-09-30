"""Synthetic known-answer tests for the digitization + integration pipeline.

Proves the V1.8 pipeline recovers a known Jph from a synthetic figure-like
array via all three methods, and that the integration engine matches the
hand-computed value. These are mechanics tests (the historical figure files
are MISSING-VERIFIED in this repository, so real-figure results are pending).
"""
import numpy as np
import pytest

from apmt import spectrum as S
from apmt.eqe_digitize import (
    AxisCalibration,
    DigitizationProvenance,
    digitize_color_segmentation,
    digitize_independent,
    digitize_manual,
)
from apmt.eqe_integrate import integrate_jph

SPEC = None


def _spec():
    global SPEC
    if SPEC is None:
        SPEC = S.load_astm_g173_am15g_global()
    return SPEC


def _synthetic_truth():
    """Truth EQE: 0.9 for 300-750 nm (perovskite-like), 0.0 elsewhere, plus a
    Si-like branch 0.85 for 750-1200 nm. Compose a 'figure' on a 300x400 px
    canvas: x axis 300->1250 nm (950 nm over 399 px), y axis 0->1 over 299 px."""
    wl = np.arange(300.0, 1250.0, 1.0)
    eqe = np.where((wl >= 300) & (wl <= 750), 0.90,
         np.where((wl > 750) & (wl <= 1200), 0.85, 0.0))
    return wl, eqe


CAL_X = AxisCalibration(pixel_a=(1250.0 - 300.0) / 399.0, pixel_b=300.0,
                        data_unit="nm", pixel_uncertainty=1.0,
                        calibration_evidence="synthetic axis 300/1250 nm at px 0/399")
CAL_Y = AxisCalibration(pixel_a=-(1.0 - 0.0) / 299.0, pixel_b=1.0,
                        data_unit="EQE", pixel_uncertainty=1.0,
                        calibration_evidence="synthetic axis EQE 0 at px 299, EQE 1 at px 0")


def _make_figure(wl, eqe):
    h, w = 300, 400
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, :] = 255
    for i, (wv, e) in enumerate(zip(wl, eqe)):
        if e <= 0.01:
            continue  # zero branch: nothing plotted (as in a real figure)
        x = int(round((wv - 300.0) / (1250.0 - 300.0) * 399))
        y = int(round((1.0 - e) * 299))
        img[max(0, y - 1):y + 2, x, :] = (20, 90, 200)  # blue curve, 3 px thick
    # an isolated legend blob in the empty area right of the curve end
    # (curve ends at x=377; blob starts at x=385 -> x-gap splits the segment)
    img[10:13, 385:398, :] = (20, 90, 200)
    # axis lines
    img[299, :, :] = (0, 0, 0)
    img[:, 0, :] = (0, 0, 0)
    return img


def _expected_jph(wl, eqe):
    # analytic: 0.9*Jph(100%,300-750) + 0.85*Jph(100%,750-1200)
    sp = _spec()
    j1 = 0.90 * sp.jph_100eqe(300, 750)
    j2 = 0.85 * sp.jph_100eqe(750, 1200)
    return j1 + j2


def test_manual_digitization_and_integration():
    wl, eqe = _synthetic_truth()
    img = _make_figure(wl, eqe)
    # manual: sample the figure columns. A human operator sees the legend and
    # excludes it from point selection, so sampling is restricted to the
    # curve's x-domain (x < 385; legend blob starts at 385).
    pts = []
    for x in range(0, 385, 5):
        col = np.flatnonzero((img[:, x, 2] > 120) & (img[:, x, 0] < 100))
        if col.size:
            pts.append([x, col.mean()])
    prov = DigitizationProvenance(
        source_id="SYNTH", source_url="synthetic", source_sha256="x" * 64,
        page="1", figure="S-test", crop_box_px=(0, 0, 400, 300),
        image_resolution_px_per_inch=None, method="manual",
        branch_label="synthetic two-branch",
    )
    d = digitize_manual(np.array(pts), CAL_X, CAL_Y, prov).sorted()
    res = integrate_jph(d.eqe, d.wavelength_nm, _spec(), 300, 1250)
    assert res.jph_ma_cm2 == pytest.approx(_expected_jph(wl, eqe), abs=0.35)


def test_color_segmentation_matches_manual():
    wl, eqe = _synthetic_truth()
    img = _make_figure(wl, eqe)
    prov = DigitizationProvenance(
        source_id="SYNTH", source_url="synthetic", source_sha256="x" * 64,
        page="1", figure="S-test", crop_box_px=(0, 0, 400, 300),
        image_resolution_px_per_inch=None, method="color_seg",
        branch_label="synthetic two-branch",
    )
    mask = lambda row: (row[:, 2] > 120) & (row[:, 0] < 100)
    d = digitize_color_segmentation(img, mask, CAL_X, CAL_Y, prov,
                                    min_line_px=2, max_gap_px=6).sorted()
    res = integrate_jph(d.eqe, d.wavelength_nm, _spec(), 300, 1250)
    assert res.jph_ma_cm2 == pytest.approx(_expected_jph(wl, eqe), abs=0.35)
    assert d.wavelength_nm.size > 200


def test_independent_trace_matches_manual():
    wl, eqe = _synthetic_truth()
    img = _make_figure(wl, eqe)
    prov = DigitizationProvenance(
        source_id="SYNTH", source_url="synthetic", source_sha256="x" * 64,
        page="1", figure="S-test", crop_box_px=(0, 0, 400, 300),
        image_resolution_px_per_inch=None, method="independent",
        branch_label="synthetic two-branch",
    )

    def trace(col):
        gray = col.mean(axis=1)
        dark = np.flatnonzero(gray < 200)
        if dark.size == 0:
            return None
        # exclude axis row
        dark = dark[dark < 298]
        if dark.size == 0:
            return None
        return float(dark.mean())

    d = digitize_independent(img, trace, CAL_X, CAL_Y, prov, max_gap_px=6).sorted()
    res = integrate_jph(d.eqe, d.wavelength_nm, _spec(), 300, 1250)
    assert res.jph_ma_cm2 == pytest.approx(_expected_jph(wl, eqe), abs=0.4)


def test_integration_engine_analytic():
    """100% EQE over 300-1250 must equal the spectrum's own 100%-EQE integral."""
    sp = _spec()
    wl = np.array([300.0, 1250.0])
    res = integrate_jph(np.ones(2), wl, sp, 300, 1250)
    assert res.jph_ma_cm2 == pytest.approx(sp.jph_100eqe(300, 1250), rel=1e-6)
    assert res.irradiance_in_window_w_m2 == pytest.approx(
        sp.integrated_irradiance(300, 1250), rel=1e-9)
