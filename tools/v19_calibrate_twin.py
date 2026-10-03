#!/usr/bin/env python3
"""V1.9 explicit artifact-generation command: calibrate the digital twin.

Fits a small, explicitly named set of optical/collection parameters of the
tandem twin to the committed, digitized Fig. S32 EQE branches of the certified
champion (apmt.experiments.evidence), and writes a compact result artifact.

    python tools/v19_calibrate_twin.py            # print summary (non-mutating)
    python tools/v19_calibrate_twin.py --write    # write data/v19_calibration.json

The result is a fit to DIGITIZED figure data. It is labelled
MODEL-FIT-TO-DIGITIZED-EVIDENCE everywhere and is not experimental validation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from apmt.device.tandem import evaluate_tandem            # noqa: E402
from apmt.experiments.evidence import calibration_targets  # noqa: E402
from apmt.inference.calibration import calibrate_twin      # noqa: E402
from apmt.params.registry import ParamSet, all_specs       # noqa: E402

OUT = os.path.join(HERE, "data", "v19_calibration.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--model-form", default="IQE-M1", choices=["IQE-M1", "IQE-M2"])
    ap.add_argument("--profile", action="store_true",
                    help="include the 21-point profile-likelihood scans")
    args = ap.parse_args()

    targets = calibration_targets("hzb_M1")
    t0 = time.time()
    result = calibrate_twin(targets, model_form=args.model_form, profile=args.profile)
    wall = time.time() - t0
    fitted = result.paramset()

    summary = {
        "generated_by": "tools/v19_calibrate_twin.py",
        "category": "MODEL-FIT-TO-DIGITIZED-EVIDENCE",
        "fit_target": {
            "device": "hzb_M1 (certified champion of Al-Ashouri 2020, Fig. S32)",
            "provenance": "DIGITIZED from the committed raster "
                          "data/figures/s32_native_stitched.jpg",
            "n_points": int(targets["eqe_top"].size + targets["eqe_bottom"].size),
            "label_jph_ma_cm2": [targets["jph_top_label_ma_cm2"],
                                 targets["jph_bottom_label_ma_cm2"]],
        },
        "calibration": result.to_dict(),
        "tandem_at_fitted_parameters": evaluate_tandem(fitted,
                                                       model_form=args.model_form).to_dict(),
        "tandem_at_registry_defaults": evaluate_tandem(
            ParamSet.defaults(), model_form=args.model_form).to_dict(),
        "n_registry_parameters": len(all_specs()),
        "wall_clock_s": wall,
    }
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("calibration", "tandem_at_fitted_parameters",
                                   "tandem_at_registry_defaults")}, indent=2))
    print("fitted:", dict(zip(result.parameter_names,
                              [round(v, 4) for v in result.fitted_values])))
    print(f"rmse top {result.rmse_top*100:.3f} pp / bottom {result.rmse_bottom*100:.3f} pp")
    print(f"Jph top {result.jph_top_ma_cm2:.4f} / bottom {result.jph_bottom_ma_cm2:.4f} mA/cm2")
    print(f"kappa {result.identifiability.condition_number:.1f}  "
          f"boundary_hits {result.identifiability.boundary_hits}  "
          f"max|corr| {result.identifiability.max_parameter_correlation:.3f}  "
          f"flat {result.identifiability.flat_directions()}  ({wall:.1f} s)")
    if args.write:
        with open(OUT, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
