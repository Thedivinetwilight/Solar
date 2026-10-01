"""V1.8 — Fig. S32 champion EQE digitization (independent methods).

Source: data/figures/s32_native_stitched.jpg (613x471, native 144 dpi, stitched
byte-exact from the 8 JPEG strips xref 1059-1064,1071-1072 of the accepted
manuscript PDF, page 55 / printed page 54, Fig. S32).

Figure content (caption read verbatim):
  HZB Perovskite 19.41  (dark red solid, champion in-house)
  HZB Si 20.18          (dark red solid)
  Sahli Perovskite 20.1 (yellow solid, ref. 62)
  Sahli Si 20.3         (yellow solid)
  + dashed 1-R lines (dark red, yellow).

Calibration (LSQ of tick-label centers, pixel-verified):
  X: col = -109.0 + 0.5845*nm   (400@125.0, 600@241.5, 800@358.5,
                                 1000@475.5, 1200@592.5; max resid 0.2 px)
  Y: row = 414.4 - 4.0229*EQE_pct (100@11.0 ... 0@413.0; max resid 2.1 px)
  frames: bottom axis row 414, left axis col 67 (->301 nm),
          right frame col 592 (->1200 nm), top frame row 11.

Curve geometry (verified per-column, native px rows / EQE%):
  HZB perovskite: 17.5%@306 -> peak 92.7%@542 -> 80.4%@681 -> 55.2%@730.5 ->
    merged with Si 732.2-735.7 (~47%, row 225) -> 27.7%@740.8 -> 0 by ~785.
  HZB Si: 0.5%@496 -> 1.3%@542 -> 13%@681 -> 17.5%@715 -> 39%@730.5 ->
    (merge) -> 67%@740.8 -> 93%@770 -> plateau 93-97% 780-1050 -> 0 by ~1196.
  Sahli pair: perovskite visible 376-515, 528-657, 720-792 (peak 93.4%@545);
    hidden under the dark-red line in 515-528 and 657-720 (occlusion flagged,
    not assigned). Yellow Si plateau 780-1030 at 97.5-98.5% (~1% above the
    dark-red plateau); yellow NIR tail higher than dark-red (59.3%@1103 vs
    49.8%; ends ~1151-1158). Yellow crossing at 743.0 nm.

Methods:
  M1: per-column color-mask cluster extraction on the native raster.
  M2: independent 200 dpi re-render of the same PDF rect + the same pipeline.
  M3: manual point set read off the 4x grid zoom (human-independent).

Extraction rules (structural; both colors compute their OWN 1-R reference —
the yellow 1-R sits 2-3% above the dark-red one, so a shared reference
fails):
  * 1-R reference: per-color envelope from unambiguous dash columns, built
    with `_local_curve` (rolling median + linear interpolation — NON-
    parametric; a degree-6 polynomial oscillated on M2's 355-400 nm dashes)
    or an 88th-percentile window envelope in the steep NIR descent.
  * Left of the crossing: perovskite = topmost cluster after 1-R exclusion
    (4 px tolerance), Si tail = bottommost.
  * Crossing window (|nm-cross|<=2.5 nm): mean of the SOLID clusters only
    (1-R excluded) assigned to both branches.
  * Plateau (crossing..1055 nm): perovskite tail = bottommost cluster
    (row>250, >15 px below the Si); Si = second-from-top when the top two
    clusters are <=6% apart (1-R dash present) or the topmost is within 4 px
    of the envelope, else topmost (1-R in a dash gap). The Si peak 845-880
    (96-97%) nearly touches the 1-R — the separation rule disambiguates.
  * NIR tail (>=1055 nm): nothing exists below the Si, so Si = bottommost
    cluster; an isolated sub-axis noise row (len>=3, gap>15 px, row>350;
    present in the 200 dpi render) is skipped, and a monotone-decreasing
    guard (seeded from the plateau; cand within [last-20, last+5]) rejects
    1-R dashes in columns where the Si has dropped below the mask.
  * smooth(): two-pass rolling median (w=4) + drop points deviating >8% from
    the local median (200-dpi JPEG spikes).
"""
import json
import os
import sys
import numpy as np
from PIL import Image
import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMG = "data/figures/s32_native_stitched.jpg"
PDF = "data/sources/al_ashouri_accepted_manuscript.pdf"

def col2nm(c):  return (c + 109.0) / 0.5845
def nm2col(nm): return -109.0 + 0.5845 * nm
def row2eqe(r): return (414.4 - r) / 4.0229
def eqe2row(e): return 414.4 - 4.0229 * e   # e in percent

C0, C1 = 70, 590
R_TOP, R_BOT = 12, 413
GAP = 3.0
SI_ONSET = 490.0
CROSS = {"hzb": 733.5, "sahli": 743.0}

def make_masks(img):
    R, G, B = img[..., 0], img[..., 1], img[..., 2]
    darkred = ((R >= 90) & (R <= 200) & (R - B >= 45) & (R - G >= 35) & (G <= 110))
    yellow = ((R >= 180) & (R <= 240) & (G >= 155) & (G <= 220) & (B >= 95) &
              (B <= 170) & (R - B >= 45) & (R - G <= 60))
    for m in (darkred, yellow):
        m[:, :68] = False
        m[:, 593:] = False
        m[:13, :] = False
        m[414:, :] = False
        m[196:237, 118:316] = False    # 'Sahli Perovskite / HZB Perovskite' text
        m[196:237, 363:497] = False    # 'Sahli Si / HZB Si' text
    return darkred, yellow

def clusters(rows, gap=GAP):
    if len(rows) == 0:
        return []
    out, start, prev = [], 0, rows[0]
    for i in range(1, len(rows)):
        r = rows[i]
        if r - prev > gap:
            out.append(float(np.mean(rows[start:i])))
            start = i
        prev = r
    out.append(float(np.mean(rows[start:])))
    return out

def col_clusters(m, sc):
    cc = {}
    for rc in range(int(sc * C0), int(sc * C1) + 1):
        rows = np.flatnonzero(m[int(sc * R_TOP):int(sc * R_BOT) + 1, rc]) + int(sc * R_TOP)
        if not len(rows):
            continue
        cn = rc / sc
        cc[int(round(cn))] = [r / sc for r in clusters(rows, gap=GAP * sc)]
    return cc

ONR_TOL = 4.0   # px: "1-R present" tolerance for structural extraction

def _local_curve(pts, w=6):
    """Rolling-median + linear interpolation (NO polynomial: a cubic over a
    400+ nm range oscillates (Runge) and can miss a local 1-R level by
    2-3%, which breaks the 4 px exclusion tolerance)."""
    pts = sorted(pts)
    n = np.array([p[0] for p in pts]); e = np.array([p[1] for p in pts])
    em = np.array([np.median(e[max(0, i - w):i + w + 1]) for i in range(len(e))])
    def f(nm):
        return float(np.interp(nm, n, em))
    resid = em - e
    return f, float(np.sqrt(np.mean(resid ** 2)))


def _percentile_envelope(cc, lo, hi, win=25.0, pct=88.0):
    """Upper-envelope reference from the topmost clusters in [lo, hi]: the
    1-R dashed line is always the topmost curve and exists in ~60% of
    columns, so a high local percentile sits on the 1-R while dash-gap
    points of the (always-lower) solid curves are suppressed."""
    items = sorted((col2nm(c), row2eqe(min(cl)))
                   for c, cl in cc.items() if cl and lo <= col2nm(c) <= hi)
    n = np.array([x for x, _ in items]); e = np.array([y for _, y in items])
    env = np.array([np.percentile(e[np.abs(n - n[i]) <= win], pct)
                    for i in range(len(n))])
    env = np.array([np.median(env[max(0, i - 4):i + 5]) for i in range(len(env))])
    def f(nm):
        return float(np.interp(nm, n, env))
    resid = e - env
    on_env = np.abs(resid) <= 1.5
    rms = float(np.sqrt(np.mean(resid[on_env] ** 2))) if on_env.sum() else float("nan")
    return f, rms


def onr_band_a(cc):
    """1-R reference, 305-735 nm: isolated topmost clusters (row<30 for
    350-735 where the perovskite peak reaches row ~32; row<150 for
    305-350 where the perovskite rise is <45%). The 1-R is isolated
    (>=5 px above the perovskite) in every dash column -> clean points."""
    pts = []
    for c, cl in cc.items():
        nm = col2nm(c)
        if not (305.0 <= nm < 735.0):
            continue
        cl = sorted(cl)
        top = cl[0]
        if nm < 350.0:
            if top > 150.0 or (len(cl) > 1 and cl[1] - top < 10):
                continue
        else:
            if top > 30.0 or (len(cl) > 1 and cl[1] - top < 5):
                continue
        pts.append((nm, row2eqe(top)))
    return _local_curve(pts)


def onr_reference(cc):
    """Piecewise 1-R reference: band A (305-735, isolated-topmost cubic),
    gap (735-1055) and band B (1055-1230) as 88th-percentile envelopes
    (cubic) of the topmost clusters - robust to the dash gaps where the
    topmost is the Si instead."""
    fit_a, rms_a = onr_band_a(cc)
    fit_g, rms_g = _percentile_envelope(cc, 735.0, 1055.0)
    fit_b, rms_b = _percentile_envelope(cc, 1055.0, 1260.0)
    def ref(nm):
        if nm < 735.0:
            return float(fit_a(nm))
        if nm <= 1055.0:
            return float(fit_g(nm))
        return float(fit_b(nm))
    rms = float(np.sqrt((rms_a ** 2 + rms_g ** 2 + rms_b ** 2) / 3))
    return ref, rms


def extract_rules(cc, onr, cross, tag, perov_min_eqe=0.0):
    """Structural extraction (no proximity-only decisions).

    Geometry (pixel-verified per column):
    * the 1-R dashed line is always the topmost curve;
    * left of the crossing: [1-R, perovskite, Si tail];
    * crossing zone: perov and Si merge into one value;
    * gap/plateau (cross..1055): [1-R, Si plateau, perov tail]; the Si peak
      (96-97% at 845-880) nearly touches the 1-R, so the two are told apart
      by SEPARATION (<=6% -> 1-R on top, Si next down) plus proximity to the
      local 1-R envelope as a secondary trigger;
    * NIR tail (>1055): [1-R, descending Si]; the 1-R stays >=8% above the
      Si, so it is identified by proximity to its envelope.

    perov_min_eqe: below this, a topmost (nm<cross) cluster is not the
    perovskite (yellow pair: the perovskite can be hidden under the dark-red
    line, leaving only the low Si tail)."""
    per, si, onr_c = {}, {}, {}
    for c, cl in cc.items():
        nm = col2nm(c)
        tgt = eqe2row(float(onr(nm)))
        near = [r for r in cl if abs(r - tgt) <= ONR_TOL]
        if near and c not in onr_c:
            onr_c[c] = (nm, row2eqe(min(near)))
        cl_s = sorted(cl)
        if abs(nm - cross) <= 2.5:
            # merged crossing zone: average of the SOLID curves only
            solid = [r for r in cl_s if abs(r - tgt) > ONR_TOL]
            v = row2eqe(np.mean(solid if solid else cl_s))
            per[c] = (nm, v)
            si[c] = (nm, v)
            continue
        if nm < cross:
            # [1-R, perovskite, Si tail]
            cands = [r for r in cl_s if abs(r - tgt) > ONR_TOL]
            if not cands:
                continue
            if len(cands) >= 2 and abs(cands[0] - tgt) < 7.0 and cands[1] < 350.0:
                per_r = cands[1]            # 1-R slipped past exclusion
            else:
                per_r = cands[0]
            top_eqe = row2eqe(per_r)
            if top_eqe >= perov_min_eqe:
                per[c] = (nm, top_eqe)
            if nm >= SI_ONSET and len(cands) > 1:
                si[c] = (nm, row2eqe(max(cands)))
            elif nm >= SI_ONSET:
                si[c] = (nm, 0.0)
        elif nm < 1055.0:
            # gap/plateau: perov tail = bottommost (row>250, far from the Si)
            if len(cl_s) >= 2 and cl_s[-1] > 250.0 and (cl_s[-1] - cl_s[-2]) > 15.0:
                per[c] = (nm, row2eqe(cl_s[-1]))
                cl_s = cl_s[:-1]
            if not cl_s:
                continue
            if len(cl_s) >= 2:
                sep = row2eqe(cl_s[1]) - row2eqe(cl_s[0])
                if sep <= 6.0 or abs(cl_s[0] - tgt) <= ONR_TOL:
                    si[c] = (nm, row2eqe(cl_s[1]))   # 1-R on top, Si next
                else:
                    si[c] = (nm, row2eqe(cl_s[0]))   # 1-R in a dash gap
            else:
                si[c] = (nm, row2eqe(cl_s[0]))
        # NIR tail (nm>=1055) handled in a monotone second pass below
    # NIR second pass: nothing exists below the Si there (perovskite = 0),
    # so Si = bottommost cluster - except an isolated sub-axis noise row
    # (present in the 200 dpi re-render). A monotone-decreasing guard
    # (seeded from the plateau) rejects 1-R dashes in columns where the Si
    # has dropped below the mask and one-off noise rows.
    pre_pts = sorted((v[0], v[1]) for v in si.values())
    last_si = pre_pts[-1][1] if pre_pts else None
    for c, cl2 in sorted(cc.items(), key=lambda kv: col2nm(kv[0])):
        nm2 = col2nm(c)
        if nm2 < 1055.0:
            continue
        if not cl2:
            continue
        r_sorted = sorted(cl2)
        if (len(r_sorted) >= 3 and r_sorted[-1] > 350.0
                and (r_sorted[-1] - r_sorted[-2]) > 15.0):
            cand_r = r_sorted[-2]        # skip isolated sub-axis noise row
        else:
            cand_r = r_sorted[-1]
        cand = row2eqe(cand_r)
        if last_si is not None and (cand > last_si + 5.0 or cand < last_si - 20.0):
            continue
        si[c] = (nm2, cand)
        last_si = cand if last_si is None else min(cand, last_si)
    return per, si, onr_c


def smooth(p, w=4):
    ks = sorted(p)
    nm = np.array([p[k][0] for k in ks])
    e = np.array([p[k][1] for k in ks])
    es = np.array([np.median(e[max(0, i - w):i + w + 1]) for i in range(len(e))])
    # drop isolated spikes (JPEG artifacts in the 200 dpi re-render):
    # points deviating >8% from the local median are re-extracted from
    # nothing in particular - just remove them; integrate_jph bridges gaps.
    keep = np.abs(e - es) <= 8.0
    if keep.sum() < 5:
        keep = np.ones(len(e), bool)
    nm, es = nm[keep], es[keep]
    es = np.array([np.median(es[max(0, i - w):i + w + 1]) for i in range(len(es))])
    return nm, np.clip(es, 0.0, 100.0)

# ---- M3 manual point sets (read off s32_grid4x.png; coarse, ±1-2%) ----------
M3_PEROV = [
    (305, 17), (320, 27), (340, 42), (360, 55), (380, 67), (400, 76),
    (420, 81), (440, 84), (460, 86.5), (480, 88), (500, 89.8), (520, 91.4),
    (542, 92.7), (560, 92), (580, 90.6), (600, 88.7), (620, 86.5),
    (640, 84.6), (660, 82.5), (680, 80.4), (700, 79), (715, 76.5),
    (723.7, 68), (730.5, 55.2), (733.5, 47), (737.4, 35.5), (740.8, 27.7),
    (745.9, 16.8), (749.4, 11.3), (754.5, 5.9), (759.6, 3.0), (765, 1.7),
    (770, 1.0), (775, 0.8), (782, 0.3), (788, 0),
]
# M3 manual points, cross-checked against the per-column pixel dump. Two
# regions of the initial grid read were corrected: the 880-1020 plateau
# (the curve gently descends 95.5 -> 91.8, it does not stay at ~95) and the
# 1050-1196 tail (smooth ~2.7%/5nm descent to 0.7% at 1196, not a cutoff at
# 1172). Everything else is the original hand read of s32_grid4x.png.
M3_SI = [
    (490, 0.4), (510, 0.7), (530, 1.0), (542, 1.3), (560, 1.8), (580, 2.9),
    (600, 4.6), (620, 6.9), (640, 9.2), (660, 11.5), (680, 13.0), (700, 14.3),
    (710, 16), (715, 17.5), (720, 21), (725, 27), (730.5, 39.0),
    (733.5, 47), (735.7, 47), (737.4, 58.1), (739.1, 62.5), (740.8, 67.0),
    (742.5, 70.7), (745.9, 77.5), (749.4, 82.9), (754.5, 88.3), (759.6, 91.2),
    (764.8, 92.3), (770, 92.8), (780, 93.1), (790, 92.9), (800, 93.1),
    (810, 93.9), (820, 94.8), (830, 95.6), (840, 96.4), (850, 96.8),
    (860, 97.0), (870, 96.8), (880, 95.5), (890, 94.9), (900, 94.4),
    (910, 93.4), (920, 92.9), (930, 92.4), (940, 92.3), (950, 92.1),
    (960, 92.1), (970, 91.9), (980, 91.8), (990, 91.8), (1000, 91.8),
    (1010, 91.0), (1020, 89.3), (1030, 87.2), (1040, 82.4), (1050, 78.5),
    (1060, 72.9), (1070, 67.5), (1080, 62.5), (1090, 56.5), (1100, 50.0),
    (1110, 44.0), (1120, 37.0), (1130, 31.0), (1140, 24.0), (1150, 18.0),
    (1160, 13.0), (1170, 7.3), (1180, 2.7), (1190, 1.1), (1196, 0.5),
]
M3_ONR = [
    (305, 84), (315, 88), (330, 93), (350, 95.5), (380, 96.2), (420, 96.4),
    (460, 96.2), (500, 96.2), (540, 96.4), (580, 96.3), (620, 96.1),
    (660, 96.1), (700, 96.2), (740, 96.5), (780, 96.8), (820, 97.2),
    (860, 97.6), (900, 97.2), (940, 96.8), (980, 96.4), (1020, 95.2),
    (1050, 92.5), (1070, 89), (1090, 84.5), (1110, 79.5), (1130, 74.5),
    (1150, 70.5), (1170, 67.5), (1190, 65.5), (1210, 64.5),
]

def main():
    from apmt.spectrum import load_astm_g173_am15g_global
    from apmt.eqe_integrate import integrate_jph
    spec = load_astm_g173_am15g_global()

    def integ(n, e, lo=280, hi=5000):
        if e is None or len(n) < 3:
            return None
        return integrate_jph(e / 100.0, n, spec, lo, hi).jph_ma_cm2

    def run(mask, sc, tag, perov_min_eqe=0.0, ref=None, rms=None):
        cc = col_clusters(mask, sc)
        if ref is None:
            ref, rms = onr_reference(cc)
        per, si, onr_c = extract_rules(cc, ref, CROSS[tag], tag, perov_min_eqe)
        pn, pe = smooth(per)
        sn, se = smooth(si)
        on, oe = smooth(onr_c, w=3)
        # 1-R integral from the piecewise reference (300-1200, axis window)
        nm_g = np.arange(300.0, 1200.5, 1.0)
        eqe_g = np.clip(np.array([ref(x) for x in nm_g]), 0.0, 100.0)
        io = integ(nm_g, eqe_g, 300, 1200)
        ip, isi = integ(pn, pe), integ(sn, se)
        print(f"{tag}: 1-R rms {rms:.2f}% | "
              f"perov {len(pn)} pts {pn[0]:.0f}-{pn[-1]:.0f} nm max {pe.max():.1f}% "
              f"-> Jph {ip:.4f} | si {len(sn)} pts {sn[0]:.0f}-{sn[-1]:.0f} nm "
              f"max {se.max():.1f}% -> Jph {isi:.4f} | sum {ip + isi:.4f}")
        print(f"   1-R ref curve: Jph(300-1200) {io:.4f}, "
              f"reflection-loss proxy {spec.jph_100eqe(300, 1200) - io:.4f} "
              f"({len(on)} pixel-trace pts)")
        return dict(nm_perov=pn, eqe_perov=pe, nm_si=sn, eqe_si=se,
                    nm_onr=on, eqe_onr=oe, onr_rms_pct=rms,
                    n_perov=len(pn), n_si=len(sn), n_onr=len(on),
                    iph=ip, ishp=isi, ionr=io)

    img = np.asarray(Image.open(IMG).convert("RGB")).astype(int)
    dr, yl = make_masks(img)
    results = {}
    # Each color gets its OWN 1-R reference: the yellow (Sahli) 1-R dashed
    # line sits ~2-3% ABOVE the dark-red (HZB) one (textured front = reduced
    # reflection = higher 1-R), so a shared reference would mis-exclude the
    # yellow solid curves.
    r = run(dr, 1.0, "hzb");                 results["hzb_M1"] = r
    r = run(yl, 1.0, "sahli", 45.0);         results["sahli_M1"] = r

    # M2: 200 dpi re-render (same PDF rect), HZB color
    page = pymupdf.open(PDF)[54]
    rect = pymupdf.Rect(144.4, 388.5, 451.0, 623.0)
    S = 200 / 72.0
    sc = S / 2.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(S, S), clip=rect,
                          colorspace=pymupdf.csRGB)
    big = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
    R, G, B = big[..., 0], big[..., 1], big[..., 2]
    dr2 = ((R >= 90) & (R <= 200) & (R - B >= 45) & (R - G >= 35) & (G <= 110))
    dr2[:, :int(sc * 68)] = False
    dr2[:, int(sc * 593):] = False
    dr2[:int(sc * 13), :] = False
    dr2[int(sc * 414):, :] = False
    dr2[int(sc * 196):int(sc * 237), int(sc * 118):int(sc * 316)] = False
    dr2[int(sc * 196):int(sc * 237), int(sc * 363):int(sc * 497)] = False
    r = run(dr2, sc, "hzb");      results["hzb_M2"] = r

    # M3 manual
    a3p = np.array([x for x, _ in M3_PEROV]); e3p = np.array([y for _, y in M3_PEROV])
    a3s = np.array([x for x, _ in M3_SI]);     e3s = np.array([y for _, y in M3_SI])
    a3o = np.array([x for x, _ in M3_ONR]);    e3o = np.array([y for _, y in M3_ONR])
    ip3, isi3 = integ(a3p, e3p), integ(a3s, e3s)
    print(f"hzb_M3: perov Jph {ip3:.4f} | si Jph {isi3:.4f} | sum {ip3 + isi3:.4f}")
    results["hzb_M3"] = dict(nm_perov=a3p, eqe_perov=e3p, nm_si=a3s, eqe_si=e3s,
                             nm_onr=a3o, eqe_onr=e3o, onr_rms_pct=None,
                             n_perov=len(a3p), n_si=len(a3s), n_onr=len(a3o),
                             iph=ip3, ishp=isi3)

    out = {
        "figure": "Fig. S32 (p55 of accepted manuscript, printed p54)",
        "source_raster": "data/figures/s32_native_stitched.jpg (613x471 @144 dpi, 8 native JPEG strips)",
        "calibration": {"x": "col = -109.0 + 0.5845*nm (max resid 0.2 px = 0.34 nm)",
                        "y": "row = 414.4 - 4.0229*EQE% (max resid 2.1 px = 0.52%)"},
        "crossing_nm": CROSS,
        "labels": {"hzb_perovskite": 19.41, "hzb_si": 20.18,
                   "sahli_perovskite": 20.1, "sahli_si": 20.3,
                   "sahli_cumulative": 40.4, "hzb_cumulative": 39.59},
        "spectrum": {"jph100_280_5000": round(spec.jph_100eqe(280, 5000), 4)},
    }
    for tag in ("hzb_M1", "hzb_M2", "hzb_M3", "sahli_M1"):
        r = results[tag]
        d = {
            "perovskite_jph": round(r["iph"], 4),
            "si_jph": round(r["ishp"], 4),
            "sum_jph": round(r["iph"] + r["ishp"], 4),
            "perov_range_nm": [round(float(r["nm_perov"][0]), 1), round(float(r["nm_perov"][-1]), 1)],
            "si_range_nm": [round(float(r["nm_si"][0]), 1), round(float(r["nm_si"][-1]), 1)],
            "perov_max_pct": round(float(r["eqe_perov"].max()), 2),
            "si_max_pct": round(float(r["eqe_si"].max()), 2),
            "n_perov_pts": r["n_perov"],
            "n_si_pts": r["n_si"],
            "n_onr_pts": r["n_onr"],
            "onr_fit_rms_pct": (round(r["onr_rms_pct"], 2) if r["onr_rms_pct"] is not None else None),
        }
        if "ionr" in r:
            io = r["ionr"]                      # piecewise 1-R reference, 300-1200
        else:
            io = integ(r["nm_onr"], r["eqe_onr"], 300, 1200)
        d["onr_jph_300_1200"] = round(io, 4)
        d["reflection_loss_proxy_300_1200"] = round(spec.jph_100eqe(300, 1200) - io, 4)
        out.setdefault("methods", {})[tag] = d
    print(json.dumps(out, indent=2))
    with open("data/s32_results.json", "w") as f:
        json.dump(out, f, indent=2)
    np.savez("data/s32_curves.npz",
             **{f"{k}_{s}": v for k, r in results.items() for s, v in
                [("perov_nm", r["nm_perov"]), ("perov_eqe", r["eqe_perov"]),
                 ("si_nm", r["nm_si"]), ("si_eqe", r["eqe_si"]),
                 ("onr_nm", r["nm_onr"]), ("onr_eqe", r["eqe_onr"])]})
    return out

if __name__ == "__main__":
    main()
