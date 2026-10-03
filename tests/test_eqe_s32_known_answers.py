"""V1.8 cycle-2 known-answer tests: final Fig. S32 / Fig. 4E digitization.

Pins the conflict-resolution evidence (audit A.3/A.6):
1. The committed Fig. S32 digitizes to the source-reported family
   19.41 / 20.18 / 39.59 with three independent methods (no scaling).
2. data/s32_results.json is EXACTLY reproducible by a deterministic re-run
   of data/s32_digitize_v18.py (guards against silent number changes).
3. The results JSON is consistent with the saved curve points (the Jph
   values re-integrate from data/s32_curves.npz on the bit-exact spectrum).
4. The Fig. 4E re-digitization (data/eqe4e_results.json) sits in the
   reported bands (low-fidelity schematic; Si support < 20.18).
5. The conflicting historical values 16.901937 / 17.110498 remain
   immutable ledger entries (SUPERSEDED-UNREPRODUCIBLE) and are NOT
   reproduced by the current pipeline.
"""
import importlib.util
import json
import os

import numpy as np
import pytest

from apmt import spectrum as S
from apmt.eqe_integrate import integrate_jph
from apmt.ledger import HISTORICAL_LEDGER

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S32_JSON = os.path.join(HERE, "data", "s32_results.json")
S32_NPZ = os.path.join(HERE, "data", "s32_curves.npz")
S32_SCRIPT = os.path.join(HERE, "data", "s32_digitize_v18.py")
E4E_JSON = os.path.join(HERE, "data", "eqe4e_results.json")

SPEC = None
S32 = None


def _spec():
    global SPEC
    if SPEC is None:
        SPEC = S.load_astm_g173_am15g_global()
    return SPEC


def _s32():
    global S32
    if S32 is None:
        with open(S32_JSON) as f:
            S32 = json.load(f)
    return S32


@pytest.fixture(scope="module")
def s32():
    return _s32()


def test_s32_champion_labels_reproduced_by_three_methods():
    """The audit's central claim: labels 19.41/20.18/39.59 reproducible."""
    m = _s32()["methods"]
    labels = (19.41, 20.18, 39.59)
    for tag in ("hzb_M1", "hzb_M2", "hzb_M3"):
        got = (m[tag]["perovskite_jph"], m[tag]["si_jph"], m[tag]["sum_jph"])
        # every method within 0.20 mA/cm2 of the label
        assert all(abs(g - l) <= 0.20 for g, l in zip(got, labels)), (tag, got)
    # the native-pixel method (M1) reproduces to within 0.05
    m1 = m["hzb_M1"]
    assert abs(m1["perovskite_jph"] - 19.41) <= 0.05
    assert abs(m1["si_jph"] - 20.18) <= 0.05
    assert abs(m1["sum_jph"] - 39.59) <= 0.05
    # pinned final values (4 decimals, as stored)
    assert m1["perovskite_jph"] == 19.4301
    assert m1["si_jph"] == 20.1846
    assert m1["sum_jph"] == 39.6146
    assert m["hzb_M2"]["sum_jph"] == 39.7511
    assert m["hzb_M3"]["sum_jph"] == 39.4282


def test_s32_sahli_schematic_bounds():
    """Sahli drawn curves: below their measured labels (occlusion +
    schematic), within the reported -3.3% band (audit A.3)."""
    m = _s32()["methods"]["sahli_M1"]
    assert m["perovskite_jph"] == 19.6044
    assert m["si_jph"] == 19.4531
    assert m["sum_jph"] == 39.0575
    assert m["sum_jph"] <= 40.4
    assert 40.4 - m["sum_jph"] <= 1.5  # -1.34 reported


def test_s32_results_consistent_with_saved_curves():
    """Re-integrate the saved curve points on the bit-exact spectrum;
    must match the results JSON (guards against hand-edited JSON)."""
    spec = _spec()
    d = np.load(S32_NPZ, allow_pickle=True)
    m = _s32()["methods"]
    for tag in ("hzb_M1", "hzb_M2", "hzb_M3", "sahli_M1"):
        for curve, key in (("perov", "perovskite_jph"), ("si", "si_jph")):
            nm = d[f"{tag}_{curve}_nm"].astype(float)
            eqe = np.clip(d[f"{tag}_{curve}_eqe"].astype(float), 0.0, 100.0)
            jph = integrate_jph(eqe / 100.0, nm, spec, 300, 1250).jph_ma_cm2
            assert abs(jph - m[tag][key]) < 0.005, (tag, curve, jph)
        s = m[tag]["perovskite_jph"] + m[tag]["si_jph"]
        assert abs(s - m[tag]["sum_jph"]) < 1.1e-4  # independent 4-dec rounding


def _load_s32_module():
    spec = importlib.util.spec_from_file_location("s32_digitize_v18", S32_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_s32_deterministic_rerun_matches_json():
    """A deterministic re-run reproduces the stored results exactly.

    Audit item B (V1.9): the re-run is NON-MUTATING (``write=False``); the
    historical JSON/NPZ are regenerated only by the explicit command
    ``python data/s32_digitize_v18.py --write``. Methods whose source raster is
    absent are reported as SOURCE_MISSING and are NOT silently skipped: the
    test asserts that gap explicitly, and ``test_s32_m2_requires_source_pdf``
    below covers M2 whenever the manuscript PDF is present.
    """
    mod = _load_s32_module()
    out = mod.main(write=False, require_pdf=False)
    with open(S32_JSON) as f:
        stored = json.load(f)
    verified = []
    for tag in ("hzb_M1", "hzb_M2", "hzb_M3", "sahli_M1"):
        got = out["methods"][tag]
        if got.get("status") == "SOURCE_MISSING":
            assert tag == "hzb_M2"
            assert stored["methods"][tag]["perovskite_jph"] > 0  # history intact
            continue
        for k in ("perovskite_jph", "si_jph", "sum_jph",
                  "onr_jph_300_1200", "reflection_loss_proxy_300_1200"):
            assert got[k] == stored["methods"][tag][k], (tag, k)
        verified.append(tag)
    # M1/M3/sahli are raster- or coordinate-based and MUST always verify
    assert set(verified) == {"hzb_M1", "hzb_M3", "sahli_M1"}


def test_s32_m2_requires_source_pdf():
    """M2 (200-dpi PDF re-render) is verified only where the source exists.

    The 69-page manuscript PDF is an external source that is deliberately not
    committed (``.gitignore``: ``data/sources/*.pdf``). Where it is absent this
    test SKIPS with an explicit reason -- it must never report a pass it did
    not achieve.
    """
    pdf = os.path.join(HERE, "data", "sources", "al_ashouri_accepted_manuscript.pdf")
    if not os.path.exists(pdf):
        pytest.skip("data/sources/al_ashouri_accepted_manuscript.pdf absent "
                    "(external source, not committed) -> hzb_M2 200-dpi "
                    "re-render NOT VERIFIED in this checkout")
    mod = _load_s32_module()
    out = mod.main(write=False, require_pdf=True)
    with open(S32_JSON) as f:
        stored = json.load(f)
    for k in ("perovskite_jph", "si_jph", "sum_jph", "onr_jph_300_1200",
              "reflection_loss_proxy_300_1200"):
        assert out["methods"]["hzb_M2"][k] == stored["methods"]["hzb_M2"][k], k


def test_eqe4e_reconstruction_in_reported_bands():
    """Fig. 4E (low-fidelity schematic): Si visible support below 20.18;
    perovskite ~2% below its label (audit A.4)."""
    with open(E4E_JSON) as f:
        e = json.load(f)
    m = e["methods"]
    for tag in ("M1_manual_zoom_read", "M2_native_color_seg",
                "M3_900dpi_rerender_seg"):
        r = m[tag]
        assert 18.7 <= r["si_jph_visible_support"] <= 19.7
        assert r["si_hidden_leading_edge_bound"] <= 0.4
        assert r["si_jph_visible_support"] + r["si_hidden_leading_edge_bound"] <= 20.1
        assert 19.0 <= r["perovskite_jph"] <= 19.2
    # pinned headline values (4-decimal rounding of stored full precision)
    assert round(m["M2_native_color_seg"]["si_jph_visible_support"], 4) == 18.7075
    assert round(m["M1_manual_zoom_read"]["si_jph_visible_support"], 4) == 19.6306
    assert round(m["M3_900dpi_rerender_seg"]["si_jph_visible_support"], 4) == 18.7607


def test_no_rescaling_applied_and_history_immutable():
    """Spectrum fingerprint matches the bit-exact recovery; historical
    values remain exactly as handed off (silent-change guard)."""
    e = _s32()
    assert e["spectrum"]["jph100_280_5000"] == 68.9829
    with open(E4E_JSON) as f:
        d = json.load(f)
    assert d["spectrum"]["fingerprint"].startswith("59040a85")
    # the superseded historical values are unchanged in the ledger and are
    # NOT values produced by any V1.8 method
    v15 = HISTORICAL_LEDGER[("V1.5", "s32_graphical_integral")][0]
    v16 = HISTORICAL_LEDGER[("V1.6", "fig4e_reconstruction")][0]
    assert v15 == 17.110498
    assert v16 == 16.9019365812
    m = _s32()["methods"]
    for tag in ("hzb_M1", "hzb_M2", "hzb_M3"):
        assert m[tag]["si_jph"] > 19.9  # nowhere near 16.90-17.11
