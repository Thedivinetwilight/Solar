"""APMT V1.9 — evidence ingestion for the digitized primary-source curves.

This module is the *only* place where digitized figure data enter the platform.
Every curve carries its provenance category (DIGITIZED), the committed raster it
came from, its integration value, the source-reported label it is compared
against, and an explicit validity classification produced by
:mod:`apmt.validation.extraction_validity`.

Nothing here converts a digitized curve into an "EXPERIMENTAL" record, and no
value is silently scaled: the V1.8 rule (no vertical rescaling without a
primary-source citation) is enforced upstream by apmt.eqe_digitize.apply_transform.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from ..provenance import ProvenanceCategory, SourceRef

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S32_NPZ = os.path.join(_REPO, "data", "s32_curves.npz")
S32_JSON = os.path.join(_REPO, "data", "s32_results.json")
E4E_NPZ = os.path.join(_REPO, "data", "eqe4e_curves.npz")
E4E_JSON = os.path.join(_REPO, "data", "eqe4e_results.json")


def detect_curve_scale(values: np.ndarray) -> tuple:
    """Detect whether stored curve values are fractions (0-1) or percent (0-100).

    V1.9 audit finding: ``data/s32_curves.npz`` stores EQE in percent while
    ``data/eqe4e_curves.npz`` stores the *same kind of quantity* as fractions
    (both are DIGITIZED evidence from the same V1.8 cycle). The committed files
    are historical evidence and are NOT modified here; instead the reader
    detects the scale, normalises to percent and *records* the decision so the
    inconsistency cannot propagate silently.

    Returns (scale_factor_to_percent, detected_unit_string).
    """
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return 1.0, "empty"
    finite = v[np.isfinite(v)]
    if finite.size == 0:
        return 1.0, "non-finite"
    hi = float(np.max(np.abs(finite)))
    if hi <= 1.5:
        return 100.0, "fraction (0-1) [normalised to percent]"
    return 1.0, "percent (0-100)"


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class CurveEvidence:
    """One digitized spectral curve with provenance."""

    name: str
    wavelength_nm: np.ndarray
    values_pct: np.ndarray
    category: ProvenanceCategory
    source: SourceRef
    reported_label_value: Optional[float] = None     # mA/cm2 from the figure legend
    integrated_value: Optional[float] = None         # mA/cm2 from the platform
    valid: bool = True
    invalid_reason: str = ""
    notes: str = ""

    def as_fraction(self) -> np.ndarray:
        return np.clip(self.values_pct / 100.0, 0.0, 1.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "category": self.category.value,
            "source_id": self.source.source_id, "source_sha256": self.source.sha256,
            "n_points": int(self.wavelength_nm.size),
            "wavelength_range_nm": [float(self.wavelength_nm.min()),
                                    float(self.wavelength_nm.max())],
            "reported_label_ma_cm2": self.reported_label_value,
            "integrated_ma_cm2": self.integrated_value,
            "valid": self.valid, "invalid_reason": self.invalid_reason,
            "notes": self.notes,
        }


def _s32_source() -> SourceRef:
    meta = {}
    if os.path.exists(S32_JSON):
        with open(S32_JSON) as f:
            meta = json.load(f)
    return SourceRef(
        source_id="AA2020-ACCEPTED-TUB-69PP:FigS32",
        description="Figure S32 of the accepted manuscript (perovskite/silicon EQE "
                    "and 1-R of the certified champion and of Sahli et al.)",
        sha256=file_sha256(S32_NPZ) if os.path.exists(S32_NPZ) else None,
        retrieval_date="2026-10-01",
        access_status="OBTAINED",
        lawfulness_note="CC BY accepted author version committed to this repository",
    )


def load_s32_curves(method: str = "hzb_M1") -> Dict[str, CurveEvidence]:
    """Load the Fig. S32 branch curves for one digitization method.

    Returns {'perovskite': CurveEvidence, 'silicon': CurveEvidence,
             'one_minus_r': CurveEvidence (validity classified)}.
    """
    if not os.path.exists(S32_NPZ):
        raise FileNotFoundError(f"missing {S32_NPZ}: the digitized evidence is not "
                                f"present; refusing to synthesise it")
    d = np.load(S32_NPZ, allow_pickle=True)
    with open(S32_JSON) as f:
        results = json.load(f)
    m = results["methods"].get(method)
    if m is None:
        raise KeyError(f"method {method!r} not present in s32_results.json")
    src = _s32_source()
    out = {}
    for curve, label_key in (("perov", "perovskite"), ("si", "silicon")):
        nm = d[f"{method}_{curve}_nm"].astype(float)
        eqe = np.clip(d[f"{method}_{curve}_eqe"].astype(float), 0.0, 100.0)
        short = "perovskite" if label_key == "perovskite" else "si"
        prefix = "hzb" if method.startswith("hzb") else "sahli"
        reported = results["labels"].get(f"{prefix}_{short}")
        out[label_key] = CurveEvidence(
            name=f"{method}:{label_key}", wavelength_nm=nm, values_pct=eqe,
            category=ProvenanceCategory.DIGITIZED, source=src,
            reported_label_value=float(reported) if reported is not None else None,
            integrated_value=float(m["perovskite_jph" if label_key == "perovskite"
                                      else "si_jph"]),
            notes="pixel-traced from the committed raster; 3-method reproduction "
                  "documented in v1.8_eqe_digitization_audit.md")
    if f"{method}_onr_nm" in d:
        nm = d[f"{method}_onr_nm"].astype(float)
        raw = d[f"{method}_onr_eqe"].astype(float)
        scale, unit = detect_curve_scale(raw)
        onr = raw * scale
        from ..validation.extraction_validity import classify_one_minus_r
        v = classify_one_minus_r(nm, onr, expect_plateau_pct=95.0)
        out["one_minus_r"] = CurveEvidence(
            name=f"{method}:1-R", wavelength_nm=nm, values_pct=onr,
            category=ProvenanceCategory.DIGITIZED, source=src,
            reported_label_value=results["labels"].get("one_r"),
            integrated_value=float(m.get("onr_jph_300_1200", np.nan)),
            valid=v.valid, invalid_reason=v.reason,
            notes=("1-R is NOT absorption and is NEVER merged with EQE "
                   "(invariant enforced by tests). Stored units: " + unit))
    return out


def load_eqe4e_curves() -> Dict[str, CurveEvidence]:
    """Load the Fig. 4E digitized branches (low-fidelity schematic source)."""
    if not os.path.exists(E4E_NPZ):
        raise FileNotFoundError(f"missing {E4E_NPZ}")
    d = np.load(E4E_NPZ, allow_pickle=True)
    with open(E4E_JSON) as f:
        results = json.load(f)
    src = SourceRef(
        source_id="AA2020-ACCEPTED-TUB-69PP:Fig4E",
        description="Figure 4E of the accepted manuscript (in-house EQE and 1-R "
                    "of the certified champion)",
        sha256=file_sha256(E4E_NPZ),
        retrieval_date="2026-10-01", access_status="OBTAINED",
        lawfulness_note="CC BY accepted author version committed to this repository")
    out = {}
    for method_key, tag in (("M1_manual_zoom_read", "M1"),
                            ("M2_native_color_seg", "M2"),
                            ("M3_900dpi_rerender_seg", "M3")):
        for curve, key in (("perov", "perovskite"), ("si", "silicon")):
            k_nm, k_eqe = f"{method_key}_{curve}_nm", f"{method_key}_{curve}_eqe"
            if k_nm not in d:
                continue
            nm = d[k_nm].astype(float)
            raw_eqe = d[k_eqe].astype(float)
            scale, unit = detect_curve_scale(raw_eqe)
            eqe = np.clip(raw_eqe * scale, 0.0, 100.0)
            res = results["methods"][method_key]
            integrated = (res.get("perovskite_jph") if key == "perovskite"
                          else res.get("si_jph_visible_support"))
            label = results["labels"].get(key)
            out[f"{tag}_{key}"] = CurveEvidence(
                name=f"Fig4E-{tag}:{key}", wavelength_nm=nm, values_pct=eqe,
                category=ProvenanceCategory.DIGITIZED, source=src,
                reported_label_value=float(label) if label else None,
                integrated_value=float(integrated) if integrated is not None else None,
                notes=("Fig. 4E is a low-fidelity schematic panel; the hidden "
                       "leading edge of the Si branch is bounded in the audit. "
                       "Stored units: " + unit))
        if f"{method_key}_onr_nm" in d:
            nm = d[f"{method_key}_onr_nm"].astype(float)
            raw_onr = d[f"{method_key}_onr_eqe"].astype(float)
            scale_onr, unit_onr = detect_curve_scale(raw_onr)
            onr = raw_onr * scale_onr
            from ..validation.extraction_validity import classify_one_minus_r
            v = classify_one_minus_r(nm, onr, expect_plateau_pct=95.0)
            out[f"{tag}_one_minus_r"] = CurveEvidence(
                name=f"Fig4E-{tag}:1-R", wavelength_nm=nm, values_pct=onr,
                category=ProvenanceCategory.DIGITIZED, source=src,
                reported_label_value=results["labels"].get("one_r"),
                integrated_value=float(results.get("reflection_check", {})
                                       .get(method_key, np.nan)),
                valid=v.valid, invalid_reason=v.reason,
                notes=("stored units: " + unit_onr + "; " + v.detail))
    return out


def calibration_targets(method: str = "hzb_M1") -> dict:
    """Digitized EQE targets used by the digital-twin calibration.

    Returns a dict with the target curves (as fractions), the wavelength grid,
    the source-reported Jph labels, and the pixel-uncertainty bands recorded in
    the V1.8 sensitivity file when available.
    """
    c = load_s32_curves(method)
    return {
        "method": method,
        "wavelength_top_nm": c["perovskite"].wavelength_nm,
        "eqe_top": c["perovskite"].as_fraction(),
        "wavelength_bottom_nm": c["silicon"].wavelength_nm,
        "eqe_bottom": c["silicon"].as_fraction(),
        "jph_top_label_ma_cm2": c["perovskite"].reported_label_value,
        "jph_bottom_label_ma_cm2": c["silicon"].reported_label_value,
        "jph_top_digitized_ma_cm2": c["perovskite"].integrated_value,
        "jph_bottom_digitized_ma_cm2": c["silicon"].integrated_value,
        "category": ProvenanceCategory.DIGITIZED.value,
        "notes": "TARGETS ARE DIGITIZED FIGURE DATA, NOT RAW MEASUREMENTS",
    }
