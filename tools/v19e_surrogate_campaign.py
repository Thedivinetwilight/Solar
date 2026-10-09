#!/usr/bin/env python3
"""Run or audit the V1.9-E validated surrogate campaign.

Ordinary tests never invoke this writer.  A full run generates only new V1.9-E
artifacts; it does not edit V1.9-D or historical experimental evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apmt.surrogate.campaign import (DEFAULT_DATASET_PATH, DEFAULT_MODEL_PATH,
                                     DEFAULT_RESULTS_PATH, _audit_existing_data,
                                     run_campaign)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true",
                        help="inspect existing artifact row-level eligibility; do not run physics")
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--models", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--initial-n", type=int, default=128)
    parser.add_argument("--stage2-n", type=int, default=256)
    parser.add_argument("--adaptive-n", type=int, default=32)
    parser.add_argument("--validation-n", type=int, default=64)
    parser.add_argument("--calibration-n", type=int, default=64,
                        help="independent L4 conformal/raw-uncertainty calibration points per regime")
    parser.add_argument("--final-n", type=int, default=96)
    parser.add_argument("--interaction-n", type=int, default=768)
    parser.add_argument("--no-l5", action="store_true",
                        help="skip L5 diagnostic (not recommended; default runs L5)")
    args = parser.parse_args(argv)
    if args.audit_only:
        print(json.dumps(_audit_existing_data(), indent=2, sort_keys=True))
        return 0
    result = run_campaign(seed=args.seed, dataset_path=args.dataset,
                          results_path=args.results, model_path=args.models,
                          initial_n=args.initial_n, stage2_n=args.stage2_n,
                          adaptive_n=args.adaptive_n, validation_n=args.validation_n,
                          calibration_n=args.calibration_n, final_n=args.final_n,
                          interaction_n=args.interaction_n,
                          run_l5=not args.no_l5)
    summary = {
        "campaign_status": result["results"]["status"],
        "dataset_artifact": result["dataset_artifact"],
        "result_artifact": result["result_artifact"],
        "model_artifact": result["model_artifact"],
        "actual_points_by_regime_and_fidelity": result["results"]["actual_points_by_regime_and_fidelity"],
        "performance": result["results"]["performance"],
        "test_report": "see results JSON for per-output metrics, uncertainty, support, optima and interaction details",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
