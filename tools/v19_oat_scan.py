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


def scan(params=DEFAULT_PARAMS, factors=FACTORS) -> dict:
    base = ParamSet.defaults()
    t0 = time.time()
    o0 = evaluate_tandem(base)
    rows = {}
    for name in params:
        s = spec(name)
        v0 = base[name]
        points = []
        for f in factors:
            v = v0 * f
            if not s.in_bounds(v) or v == v0:
                continue
            o = evaluate_tandem(base.with_mapping({name: v}))
            points.append({"value": v, "delta_pct_of_default": round(100 * (f - 1), 2),
                           "pce_pct": round(o.pce_pct, 4),
                           "delta_pce_pp": round(o.pce_pct - o0.pce_pct, 4),
                           "jsc": round(o.jsc_ma_cm2, 4), "voc": round(o.voc_v, 4),
                           "ff": round(o.ff, 4)})
        span = max((abs(p["delta_pce_pp"]) for p in points), default=0.0)
        rows[name] = {
            "default": v0, "unit": s.unit, "range": [s.low, s.high],
            "range_class": s.range_class.value, "category": s.category.value,
            "max_abs_delta_pce_pp": round(span, 4),
            "inert": span < 1e-6,
            "points": points,
        }
    return {
        "category": "OAT-SCREENING (local, one-factor-at-a-time; NOT global sensitivity)",
        "baseline_pce_pct": round(o0.pce_pct, 4),
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
