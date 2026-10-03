"""Command-line entry points for the APMT/Solar platform.

Deliberately thin: every command calls the same library functions the tests and
the CI checks use, so there is exactly one implementation of each procedure.
None of these commands writes into ``data/`` unless ``--write`` is passed.
"""
from __future__ import annotations

import argparse
import json
import sys


def cmd_twin(args) -> int:
    from .device.tandem import evaluate_tandem, junction_temperature
    from .params.registry import ParamSet
    ps = ParamSet.defaults()
    if args.set:
        overrides = {}
        for item in args.set:
            name, _, value = item.partition("=")
            overrides[name.strip()] = float(value)
        ps = ps.with_mapping(overrides)
    res = evaluate_tandem(ps, model_form=args.model_form,
                          self_heating=not args.no_self_heating)
    print(json.dumps(res.to_dict(), indent=2))
    print("thermal closure:", json.dumps(junction_temperature(ps), indent=2))
    return 0


def cmd_calibrate(args) -> int:
    from .experiments.evidence import calibration_targets
    from .inference.calibration import calibrate_twin
    r = calibrate_twin(calibration_targets("hzb_M1"), model_form=args.model_form,
                       profile=args.profile)
    print(json.dumps(r.to_dict(), indent=2))
    print("NOTE: MODEL-FIT-TO-DIGITIZED-EVIDENCE -- not experimental validation.")
    return 0


def cmd_gate(args) -> int:
    from .genealogy import GENEALOGY_LINKAGES
    from .validation.gate import GateEvidence, audit_v18_gate_consistency
    rep = audit_v18_gate_consistency(GateEvidence(
        jsc_jv_ma_cm2=19.23, jsc_eqe_ma_cm2=19.41, jsc_certified_ma_cm2=19.23,
        jv_rmse_ma_cm2=0.9170, jsc_scan_dir1_ma_cm2=19.23,
        jsc_scan_dir2_ma_cm2=19.24, linkages=GENEALOGY_LINKAGES,
        condition_number=1216249.34, boundary_hits=3))
    print(json.dumps(rep, indent=2))
    return 0 if rep["evaluated_result"] != "PASS" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="apmt")
    sub = ap.add_subparsers(dest="command", required=True)

    t = sub.add_parser("twin", help="evaluate the tandem digital twin")
    t.add_argument("--model-form", default="IQE-M1", choices=["IQE-M1", "IQE-M2"])
    t.add_argument("--no-self-heating", action="store_true")
    t.add_argument("--set", nargs="*", help="parameter overrides, e.g. rsh_ohm_cm2=800")
    t.set_defaults(func=cmd_twin)

    c = sub.add_parser("calibrate", help="fit the twin to digitized EQE evidence")
    c.add_argument("--model-form", default="IQE-M1", choices=["IQE-M1", "IQE-M2"])
    c.add_argument("--profile", action="store_true")
    c.set_defaults(func=cmd_calibrate)

    g = sub.add_parser("gate", help="evaluate the strict baseline gate")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
