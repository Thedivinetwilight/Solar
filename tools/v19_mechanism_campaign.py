#!/usr/bin/env python3
"""V1.9 campaign #1: mechanism factorial + dose-response + LHS screen.

    python tools/v19_mechanism_campaign.py            # dry run (prints)
    python tools/v19_mechanism_campaign.py --write    # writes data/v19_mechanism_campaign.json

Everything produced here is PRE-GATE / MODEL-OBSERVED / EXPLORATORY. No result
from this campaign may be reported as an experimental finding, and none of it can
open the baseline gate (G5/G6/G7 evidence is still missing).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from apmt.sensitivity.factorial import DEFAULT_MECHANISMS, dose_response, full_factorial  # noqa: E402
from apmt.sensitivity.lhs import screen                                                # noqa: E402

OUT = os.path.join(HERE, "data", "v19_mechanism_campaign.json")
DOSE_VALUES = {
    "A": [1.0, 2.0, 3.0, 4.0, 5.0],                                  # light trapping
    "B": [0.0, 1.0, 2.0, 5.0, 10.0, 20.0],                           # recycling gain
    "C": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],                             # thermal gain
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--skip-lhs", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    out = {"label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
           "generated_by": "tools/v19_mechanism_campaign.py"}

    out["factorial"] = full_factorial()
    print("2^3 factorial (%d solves):" % out["factorial"]["n_solves"])
    print("  baseline %.4f pp  best %.4f pp"
          % (out["factorial"]["baseline_pce_pct"], out["factorial"]["best_pce_pct"]))
    print("  direct effects (pp):",
          {k: round(v, 4) for k, v in out["factorial"]["direct_effects_pp"].items()})
    print("  2-way interactions (pp):",
          {k: round(v, 4) for k, v in out["factorial"]["interaction_effects_pp"].items()})
    print("  3-way interaction (pp): %.4f"
          % out["factorial"]["three_way_interaction_pp"])

    dose_parameter = {"A": "silicon_light_trapping",
                      "B": "photon_recycling_gain_top",
                      "C": "thermal_management_gain"}
    doses = {name: dose_response(param, DOSE_VALUES[name])
             for name, param in dose_parameter.items()}
    out["dose_response"] = doses
    for name, rows in doses.items():
        print("  dose %s: %s" % (name, "  ".join(
            "%.3g->%.3f" % (r["value"], r["pce_pct"]) for r in rows)))

    if not args.skip_lhs:
        def prog(i, n):
            print("  LHS %d/%d" % (i, n))
        out["lhs"] = screen(n_samples=args.samples, progress=prog)
        print("LHS screen (%d solves): mean %.4f sd %.4f  R^2 %.3f"
              % (out["lhs"]["n_solves"], out["lhs"]["pce_mean"],
                 out["lhs"]["pce_std"], out["lhs"]["surrogate_r2"]))
        for n, v in sorted(out["lhs"]["src"].items(), key=lambda kv: -abs(kv[1])):
            lo, hi = out["lhs"]["src_ci95"][n]
            print("   %-32s SRC %+7.3f  [%+.3f, %+.3f]  rho %+.3f"
                  % (n, v, lo, hi, out["lhs"]["spearman_rho"][n]))

    wall = round(time.time() - t0, 1)
    print("total %.1f s" % wall)
    # wall-clock timing is printed only: pinned artifacts must be deterministic
    if args.write:
        with open(OUT, "w") as f:
            json.dump(out, f, indent=2, sort_keys=True)
        print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
