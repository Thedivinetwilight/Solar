"""APMT V1.8 — Fig. 4E (accepted manuscript, embedded 840x961 JPEG) digitization.

Source: data/sources/al_ashouri_accepted_manuscript.pdf
        sha256 0984f7e4b351a92d9bdbae8dd3bed25faaaf4335a3da821a6d633de1b3b3b3bc
        (69 pp; Fig. 4 = p12; embedded figure image xref 431, 840x961 px,
         DCTDecode, placed at Rect(87.36, 92.4, 507.36, 573.36) pt
         -> exactly 2 px/pt = 144 dpi effective)
Extracted: data/figures/fig4_native_embedded_jpeg (byte-exact extract_image)

AXIS CALIBRATION (panel E; native px, origin top-left)
  X (wavelength): least squares on tick-label centres
     400->527.0, 600->596.0, 800->661.0, 1000->736.0 (1200 label merged,
     excluded from fit):  col = 630 + 0.346*(nm-700); max residual 3.6 px
     (=10.4 nm). Sanity: 300 nm -> col 492.2 (y-axis line at col 489.5-490);
     1200 nm -> col 803.0 (right frame at col 806).
  Y (EQE %): least squares on tick-label centres
     100->409.5, 80->456.0, 60->510.0, 40->554.0, 20->601.0, 0->650.5:
     row = 650.52 - 2.4070*EQE; max residual 1.63 pct. Sanity: 0% -> 650.5
     (axis line rows 651-652). Top frame (row ~425.5) = ~93.4%; the 100%
     tick label sits above the frame (axis range ~ -0.4..93.4%).

GEOMETRY (verified pixel-wise; drawing = yellow perovskite fill + tan Si fill
+ black edge outlines + light-gray dashed 1-R)
  * Perovskite curve = top of yellow fill, cols 491-641 (300-732 nm),
    17.7% -> peak 91.6% (541 nm) -> 61.7% (732 nm); then the black edge
    continues in the white gap: ~55% (735 nm), ~52% (737.6 nm), crossing the
    Si edge at ~740 nm (~55%); beyond the crossover the perovskite edge is
    hidden under the Si fill. Tail 740-749 nm bounded by straight line to 0.
  * Si curve = black sigmoid edge in the white gap, cols 640-651
    (717 nm, 32%) -> (752 nm, 91%), then top of tan fill cols 652-799
    (91.6% plateau 755-1025 nm; smooth fall; 0 at ~1190 nm). Si below ~717 nm
    (32% -> 0 at ~685 nm) is not drawn (hidden under perovskite fill);
    bounded by straight line from (717, 32%) to (685, 0).
  * 1-R = light-gray dashed line; text '1-R: 2.57' (cols 760-810, rows
    412-448), right frame (cols>=803), top frame excluded; gaps interpolated.

COLOUR MASKS (mode colours sampled in-fill)
  perovskite fill (250,211,134): R 244-254, G 198-222, B 122-146
  Si fill (230,204,167):         R 222-240, G 196-214, B 156-178
"""
from __future__ import annotations
import json
import numpy as np
from PIL import Image

import sys
sys.path.insert(0, ".")
from apmt.spectrum import load_astm_g173_am15g_global
from apmt.eqe_integrate import (integrate_jph, shift_sensitivity,
                                window_sensitivity, pixel_uncertainty_band)

JPG = "data/figures/fig4_native_embedded_jpeg"
C0, C1 = 491, 806
R0, R1 = 426, 651

# Si sigmoid edge (black outline in the white gap), extracted pixel-wise:
# (col, row) -> center of dark cluster
SI_SIGMOID = [(640, 573), (641, 560), (642, 541), (643, 521), (644, 502),
              (645, 487), (646, 474), (647, 458), (648, 446), (649, 441),
              (650, 437), (651, 432)]
# perovskite edge in the white gap, extracted pixel-wise
PEROV_GAP = [(643, 518), (643, 525.5), (641, 502)]   # (735,~55%), (737.6,~52%), (731.8, 61.7%)


def col2nm(c): return 700.0 + (c - 630.0) / 0.346
def row2eqe(r): return (650.52 - r) / 2.4070


def masks(img):
    R, G, B = img[..., 0], img[..., 1], img[..., 2]
    yellow = (R >= 244) & (R <= 254) & (G >= 198) & (G <= 222) & (B >= 122) & (B <= 146)
    tan = (R >= 222) & (R <= 240) & (G >= 196) & (G <= 214) & (B >= 156) & (B <= 178)
    return yellow, tan


def top_edge(mask, c0=C0, c1=C1, r0=R0, r1=R1):
    out = np.full(c1 - c0, np.nan)
    for i, c in enumerate(range(c0, c1)):
        v = np.flatnonzero(mask[r0:r1, c])
        if len(v):
            out[i] = r0 + v[0]
    return out


def onegr_mask(img):
    """Light-gray dashed 1-R line mask.
    Window: rows 405-422 (above the top frame; the dashed line runs 94-97.5%
    there) + rows 428-650 (below the top frame band 423-427). Excludes right
    frame (cols>=803) and the '1-R: 2.57' text box (cols 760-811, rows 412-448).
    """
    R, G, B = img[..., 0], img[..., 1], img[..., 2]
    gray = img.mean(axis=2)
    sat = img.max(axis=2) - img.min(axis=2)
    m = ((np.abs(R - G) <= 4) & (np.abs(G - B) <= 4) & (np.abs(R - B) <= 6)
         & (gray >= 175) & (gray <= 248) & (sat <= 12))
    m[:, 803:] = False                 # right frame
    m[412:448, 760:812] = False        # '1-R: 2.57' text
    m[:405, :] = False
    m[423:428, :] = False              # top frame band
    m[651:, :] = False
    return m


def extract_onegr(img):
    """Per-column topmost gray pixel; robust outlier rejection (dashed line is
    smooth; dash gaps -> interpolate); returns (nm, eqe_fraction)."""
    m = onegr_mask(img)
    pts = []
    for c in range(C0, C1):
        v = np.flatnonzero(m[405:651, c])
        if len(v):
            pts.append((c, 405 + v[0]))
    pts = np.array(sorted(pts))
    if not len(pts):
        return np.array([]), np.array([])
    eqe = row2eqe(pts[:, 1]) / 100.0
    # robust cleaner: median over +/-6 cols, drop points >7 pct from median
    med = []
    for i in range(len(pts)):
        lo = max(0, i - 6); hi = min(len(pts), i + 7)
        med.append(np.median(eqe[lo:hi]))
    med = np.array(med)
    keep = np.abs(eqe - med) <= 0.07
    pts, eqe = pts[keep], eqe[keep]
    o_nm = col2nm(pts[:, 0])
    o_eqe = np.clip(eqe, 0, 1)
    return o_nm, o_eqe


def method2_native():
    """Color segmentation on the byte-exact embedded JPEG."""
    img = np.asarray(Image.open(JPG).convert("RGB")).astype(int)
    yellow, tan = masks(img)
    cols = np.arange(C0, C1)
    ty, tt = top_edge(yellow), top_edge(tan)

    # ---- perovskite: yellow top (300-732) + gap edge + tail to 0 at 749 ----
    p = [(col2nm(c), row2eqe(r) / 100.0) for c, r in zip(cols, ty)
         if not np.isnan(r) and c <= 641]
    for c, r in [(643, 518), (643, 525.5)]:
        p.append((col2nm(c), row2eqe(r) / 100.0))
    p.append((749.0, 0.0))
    p = sorted(p)
    # de-duplicate at same nm (keep max)
    dd = {}
    for nm_, e in p:
        dd[round(nm_, 1)] = max(dd.get(round(nm_, 1), 0.0), e)
    p = sorted(dd.items())
    p_nm, p_eqe = np.array([a for a, _ in p]), np.array([b for _, b in p])
    p_eqe = np.clip(p_eqe, 0, 1)

    # ---- Si: sigmoid + tan top (755-1190) + hidden leading edge bound ----
    s = [(col2nm(c), row2eqe(r) / 100.0) for c, r in SI_SIGMOID]
    s += [(col2nm(c), row2eqe(r) / 100.0) for c, r in zip(cols, tt)
          if not np.isnan(r) and c >= 652]
    s.append((1190.0, 0.0))
    s = sorted(s)
    dd = {}
    for nm_, e in s:
        dd[round(nm_, 1)] = max(dd.get(round(nm_, 1), 0.0), e)
    s = sorted(dd.items())
    s_nm, s_eqe = np.array([a for a, _ in s]), np.array([b for _, b in s])
    s_eqe = np.clip(s_eqe, 0, 1)

    # ---- 1-R ----
    o_nm, o_eqe = extract_onegr(img)
    return p_nm, p_eqe, s_nm, s_eqe, o_nm, o_eqe


def manual_points():
    """Method 1: analyst read from 8-10x NEAREST zooms (grid 5-10 native px).
    Independent of the color masks: coordinates read by eye on
    perovk_region_zoom10 / crossover2_zoom10 / panelE_zoom6 / crossover_zoom8.
    """
    perov = [(300, 0.10), (325, 0.25), (350, 0.41), (375, 0.66), (400, 0.78),
             (425, 0.82), (450, 0.85), (475, 0.87), (500, 0.90), (525, 0.91),
             (550, 0.91), (575, 0.90), (600, 0.87), (625, 0.83), (650, 0.81),
             (675, 0.79), (700, 0.77), (715, 0.70), (725, 0.66), (732, 0.62),
             (736, 0.55), (740, 0.52), (745, 0.25), (749, 0.0)]
    si = [(685, 0.0), (700, 0.13), (710, 0.22), (717, 0.32), (723, 0.46),
          (729, 0.58), (735, 0.67), (741, 0.80), (746, 0.87), (752, 0.91),
          (770, 0.92), (800, 0.925), (850, 0.933), (900, 0.93), (950, 0.915),
          (1000, 0.91), (1025, 0.88), (1045, 0.81), (1065, 0.71), (1085, 0.62),
          (1105, 0.48), (1125, 0.37), (1145, 0.25), (1165, 0.13), (1180, 0.05),
          (1190, 0.0)]
    onegr = [(300, 0.965), (350, 0.975), (400, 0.980), (450, 0.980),
             (500, 0.978), (550, 0.978), (600, 0.976), (650, 0.975),
             (700, 0.976), (750, 0.975), (800, 0.972), (850, 0.968),
             (900, 0.965), (950, 0.955), (1000, 0.940), (1050, 0.87),
             (1080, 0.78), (1100, 0.71), (1120, 0.62), (1140, 0.55),
             (1160, 0.47), (1180, 0.38), (1200, 0.31)]
    return (np.array([a for a, _ in perov]), np.array([b for _, b in perov]),
            np.array([a for a, _ in si]), np.array([b for _, b in si]),
            np.array([a for a, _ in onegr]), np.array([b for _, b in onegr]))


def method3_rerender():
    """Method 3: independent rasterization — MuPDF render of p12 at 900 dpi
    (different pipeline than raw-JPEG extraction), same analytic calibration
    via the PDF placement rectangle (exact): render_px = (rect0 + native*0.5)*12.5.
    Axis sanity check in the render: x-axis row ~5227, y-axis col ~4151."""
    import pymupdf
    d = pymupdf.open("data/sources/al_ashouri_accepted_manuscript.pdf")
    page = d[11]
    pix = page.get_pixmap(dpi=900)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    img = img.astype(int)
    S = 12.5
    def xc(c): return (87.36 + 0.5 * c) * S
    def yr(r): return (92.40 + 0.5 * r) * S
    x0, x1 = int(xc(C0)), int(xc(C1))
    y0, y1 = int(yr(R0)), int(yr(R1))
    sub = img[y0:y1, x0:x1]
    R, G, B = sub[..., 0], sub[..., 1], sub[..., 2]
    yellow = (R >= 242) & (R <= 255) & (G >= 195) & (G <= 224) & (B >= 118) & (B <= 150)
    tan = (R >= 220) & (R <= 242) & (G >= 193) & (G <= 216) & (B >= 152) & (B <= 180)

    # perovskite: iterate native cols at 0.5 px step; top of yellow in render
    p = []
    for cn in np.arange(491, 641.5, 0.5):
        rc = int(round(xc(cn) - xc(C0)))
        v = np.flatnonzero(yellow[:, min(rc, sub.shape[1] - 1)])
        if len(v):
            rn = R0 + v[0] / (S / 2)
            p.append((col2nm(cn), row2eqe(rn) / 100.0))
    p += [(735.0, 0.55), (737.5, 0.52), (749.0, 0.0)]
    dd = {}
    for nm_, e in sorted(p):
        dd[round(nm_, 1)] = max(dd.get(round(nm_, 1), 0.0), e)
    p = sorted(dd.items())

    s = []
    for cn in np.arange(652, C1, 0.5):
        rc = int(round(xc(cn) - xc(C0)))
        v = np.flatnonzero(tan[:, min(rc, sub.shape[1] - 1)])
        if len(v):
            rn = R0 + v[0] / (S / 2)
            s.append((col2nm(cn), row2eqe(rn) / 100.0))
    s += [(col2nm(c), row2eqe(r) / 100.0) for c, r in SI_SIGMOID]
    s.append((1190.0, 0.0))
    dd = {}
    for nm_, e in sorted(s):
        dd[round(nm_, 1)] = max(dd.get(round(nm_, 1), 0.0), e)
    s = sorted(dd.items())

    # 1-R in render: native rows 405-422 + 428-650 (skip top frame band 423-427),
    # exclude right frame + '1-R: 2.57' text box; per native-col topmost gray.
    gray = sub.mean(axis=2)
    sat = sub.max(axis=2) - sub.min(axis=2)
    m = ((np.abs(R - G) <= 5) & (np.abs(G - B) <= 5) & (np.abs(R - B) <= 7)
         & (gray >= 175) & (gray <= 250) & (sat <= 14))
    m[:, int(xc(803) - xc(C0)):] = False
    tx0, tx1 = int(xc(760) - xc(C0)), int(xc(811) - xc(C0))
    # native row -> render row: rr = (yr(r) - yr(R0)) ; yr(r)=(92.4+0.5r)*12.5
    def rr(r): return int(round((92.4 + 0.5 * r - (92.4 + 0.5 * R0)) * S))
    m[max(0, rr(412)):rr(448), max(0, tx0):tx1] = False   # text box
    m[:rr(405), :] = False                                  # above window
    m[rr(423):rr(428), :] = False                           # top frame band
    m[rr(651):, :] = False
    o = []
    for cn in np.arange(C0, C1, 0.5):
        rc = int(round(xc(cn) - xc(C0)))
        v = np.flatnonzero(m[:, min(rc, sub.shape[1] - 1)])
        if len(v):
            rn = R0 + v[0] / (S / 2)
            o.append((col2nm(cn), row2eqe(rn) / 100.0))
    o = sorted(o)
    # robust cleaner (same as native): median +/-6, drop >7 pct
    if len(o):
        oe = np.array([e for _, e in o])
        keep = []
        for i in range(len(o)):
            lo = max(0, i - 6); hi = min(len(o), i + 7)
            keep.append(abs(oe[i] - np.median(oe[lo:hi])) <= 0.07)
        o = [a for a, k in zip(o, keep) if k]

    return (np.array([a for a, _ in p]), np.array([b for _, b in p]),
            np.array([a for a, _ in s]), np.array([b for _, b in s]),
            np.array([a for a, _ in o]), np.array([b for _, b in o]))


def integrate(spec, nm, eqe, lo=300.0, hi=1250.0):
    return integrate_jph(eqe, nm, spec, lo, hi).jph_ma_cm2


def main():
    spec = load_astm_g173_am15g_global()
    out = {"spectrum": {"fingerprint": spec.data_fingerprint(),
                        "irradiance_300_1250": spec.integrated_irradiance(300, 1250),
                        "jph100_300_1250": spec.jph_100eqe(300, 1250)}}
    methods = {
        "M2_native_color_seg": method2_native(),
        "M1_manual_zoom_read": manual_points(),
        "M3_900dpi_rerender_seg": method3_rerender(),
    }
    out["methods"] = {}
    for name, (pn, pe, sn, se, on, oe) in methods.items():
        m = {}
        m["perovskite_jph"] = integrate(spec, pn, pe)
        m["si_jph_visible_support"] = integrate(spec, sn, se)
        # hidden Si leading edge 685-717 (0->32% straight line): upper bound
        hid = np.array([685.0, 717.0])
        hid_e = np.array([0.0, 0.32])
        m["si_hidden_leading_edge_bound"] = integrate(spec, hid, hid_e, 685, 717)
        m["perovskite_points"] = len(pn)
        m["si_points"] = len(sn)
        m["onr_points"] = len(on)
        if len(on):
            og = (spec.wavelength_nm >= 300) & (spec.wavelength_nm <= 1200)
            oeg = np.interp(spec.wavelength_nm[og], on, oe, left=np.nan, right=np.nan)
            m["onr_mean_pct_300_1200"] = float(np.nanmean(oeg) * 100)
            m["onr_jph_proxy"] = integrate(spec, on, oe)
        # sensitivity on Si
        m["si_shifts"] = {str(k): round(v, 4) for k, v in
                          shift_sensitivity(se, sn, spec, (-25, -10, -5, 0, 5, 10, 25)).items()}
        m["si_windows"] = {k: round(v, 4) for k, v in
                           window_sensitivity(se, sn, spec,
                                              ((300, 1100), (300, 1150), (300, 1200),
                                               (300, 1250), (685, 1250), (717, 1250),
                                               (755, 1200))).items()}
        lo_, hi_ = pixel_uncertainty_band(se, sn, spec, dl_nm=11.6, deqe=0.0042)
        m["si_pixel_band"] = [round(lo_, 4), round(hi_, 4)]
        lo_, hi_ = pixel_uncertainty_band(pe, pn, spec, dl_nm=11.6, deqe=0.0042)
        m["perov_pixel_band"] = [round(lo_, 4), round(hi_, 4)]
        out["methods"][name] = m

    # labels
    out["labels"] = {"perovskite": 19.41, "silicon": 20.18, "sum": 39.59, "one_r": 2.57}
    # historical (HANDOFF-QUOTED)
    out["historical"] = {"fig4e_V1.6_si": 16.9019365812, "s32_V1.4_si": 17.110498}

    # --- reflection-loss check: if dashed = (1-R)(lambda), then
    #     R_loss = jph100(window) - integral(1-R curve)  should be ~2.57 ---
    j100 = spec.jph_100eqe(300, 1200)
    out["reflection_check"] = {"jph100_300_1200": round(j100, 4)}
    for name, (pn, pe, sn, se, on, oe) in methods.items():
        if len(on):
            out["reflection_check"][name] = round(j100 - integrate(spec, on, oe, 300, 1200), 4)

    # --- forensic decomposition: V1.6 16.901937 reproduced by support
    #     truncation of the SAME drawn Si curve ---
    sn, se = methods["M2_native_color_seg"][2], methods["M2_native_color_seg"][3]
    out["v16_reproduction"] = {
        "full_visible_300_1250": round(integrate(spec, sn, se), 6),
        "plateau_755_to_1100": round(integrate(spec, sn, se, 755, 1100), 6),
        "plateau_763_to_1100": round(integrate(spec, sn, se, 763, 1100), 6),
        "handoff_V1.6": 16.9019365812,
        "note": ("V1.6 value equals the integral of the same drawn Si curve "
                 "starting at the flat plateau (~755 nm; sigmoid rise in the "
                 "crossover omitted) and truncated at ~1100 nm (NIR tail "
                 "omitted): 16.9228 vs 16.9019, d = 0.021 (0.12%)."),
    }

    print(json.dumps(out, indent=2))
    with open("data/eqe4e_results.json", "w") as f:
        json.dump(out, f, indent=2)
    arrays = {}
    for k, v in methods.items():
        arrays[f"{k}_perov_nm"] = v[0]
        arrays[f"{k}_perov_eqe"] = v[1]
        arrays[f"{k}_si_nm"] = v[2]
        arrays[f"{k}_si_eqe"] = v[3]
        arrays[f"{k}_onr_nm"] = v[4]
        arrays[f"{k}_onr_eqe"] = v[5]
    np.savez("data/eqe4e_curves.npz", **arrays)


if __name__ == "__main__":
    main()
