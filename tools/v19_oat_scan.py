#!/usr/bin/env python3
"""V1.9 one-at-a-time (OAT) sensitivity scan -- first-order screening only.

This is deliberately *not* the global sensitivity campaign (that is V1.9-C/D
work: LHS / Sobol / interaction search). Its purpose here is a cheap, honest
screen that (a) quantifies which registry parameters the model actually
responds to and (b) exposes structurally inert parameters, i.e. parameters that
the model claims to use but that have no effect on any output. The shunt
unit-conversion bug of V1.9-B was found exactly this way (dPCE/dRsh == 0).

Usage:
    python tools/v19_oat_scan.py                 # print a table
    python tools/v19_oat_scan.py --write         # also write data/v19_oat_sensitivity.json

Every point is a full tandem solve with the *registered* parameter ranges; no
range is invented here. Points outside a parameter's registered range are
skipped (never clipped silently).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from apmt.device.tandem import evaluate_tandem          # noqa: E402
from apmt.params.registry import ParamSet, spec         # noqa: E402

DEFAULT_PARAMS = [
    "perovskite_eg_ev", "perovskite_thickness_nm", "arc_thickness_nm",
    "parasitic_layer_thickness_nm", "tco_free_carrier_k", "tco_uv_absorption_k",
    "silicon_light_trapping", "silicon_thickness_um", "perovskite_srh_lifetime_ns",
    "perovskite_srv_cm_s", "perovskite_doping_cm3", "silicon_doping_cm3",
    "rs_ohm_cm2", "rsh_ohm_cm2", "thermal_resistance_k_cm2_w",
    "radiative_efficiency_top", "radiative_efficiency_bottom",
    "luminescent_coupling_top_to_bottom", "photon_recycling_gain_top",
    "thermal_management_gain", "absorption_heat_fraction",
    "collection_efficiency_top", "collection_efficiency_bottom",
]
FACTORS = (0.5, 0.8, 0.9, 1.1, 1.2, 2.0)


def _grid_for(s, v0: float) -> tuple:
    """Test values for one parameter: multiplicative factors, plus (for
    switch-like parameters with a zero default, where multiplication can never
    leave zero) range-anchored values. Returns (values, mode)."""
    vals = sorted({round(v0 * f, 10) for f in FACTORS
                   if s.in_bounds(v0 * f) and v0 * f != v0})
    if v0 == 0.0:                       # switch / off-by-default mechanism
        frac = [f for f in (0.05, 0.25, 0.5, 1.0) if s.in_bounds(f * s.high)]
        vals = sorted({round(f * s.high, 10) for f in frac})
        return vals, "range-anchored (default is 0: multiplicative scan is degenerate)"
    return vals, "multiplicative"


def scan(params=DEFAULT_PARAMS, factors=FACTORS) -> dict:
    base = ParamSet.defaults()
    t0 = time.time()
    o0 = evaluate_tandem(base)
    rows = {}
    for name in params:
        s = spec(name)
        v0 = float(base[name])
        vals, mode = _grid_for(s, v0)
        points = []
        for v in vals:
            o = evaluate_tandem(base.with_mapping({name: v}))
            points.append({"value": float(v), "delta_pct_of_default": round(100 * (v / v0 - 1), 2)
                           if v0 else None,
                           "pce_pct": round(float(o.pce_pct), 4),
                           "delta_pce_pp": round(float(o.pce_pct - o0.pce_pct), 4),
                           "jsc": round(float(o.jsc_ma_cm2), 4),
                           "voc": round(float(o.voc_v), 4),
                           "ff": round(float(o.ff), 4),
                           "delta_junction_t_k": round(
                               float(o.detail["thermal"]["delta_t_k"]
                                     - o0.detail["thermal"]["delta_t_k"]), 4)})
        span = max((abs(p["delta_pce_pp"]) for p in points), default=0.0)
        rows[name] = {
            "default": v0, "unit": s.unit, "range": [s.low, s.high],
            "range_class": s.range_class.value, "category": s.category.value,
            "scan_mode": mode,
            "max_abs_delta_pce_pp": round(float(span), 4),
            "inert": bool(span < 1e-6),
            "inert_note": ("no effect on any reported quantity over the scanned "
                           "range: parameter is structurally inactive"
                           if span < 1e-6 else ""),
            "points": points,
        }
    return {
        "category": "OAT-SCREENING (local, one-factor-at-a-time; NOT global sensitivity)",
        "baseline_pce_pct": round(float(o0.pce_pct), 4),
        "baseline": o0.to_dict(),
        "params": rows,
        "wall_clock_s": round(time.time() - t0, 2),
        "n_solves": sum(len(r["points"]) for r in rows.values()) + 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    out = scan()
    print(f"baseline PCE {out['baseline_pce_pct']} % "
          f"({out['n_solves']} solves, {out['wall_clock_s']} s)")
    print(f"{'parameter':<32}{'max |dPCE| pp':>14}  inert")
    for name, r in sorted(out["params"].items(),
                          key=lambda kv: -kv[1]["max_abs_delta_pce_pp"]):
        print(f"{name:<32}{r['max_abs_delta_pce_pp']:>14.4f}  "
              f"{'YES (structurally inactive)' if r['inert'] else ''}")
    if args.write:
        path = os.path.join(HERE, "data", "v19_oat_sensitivity.json")
        with open(path, "w") as f:
            json.dump(out, f, indent=2, sort_keys=True)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
