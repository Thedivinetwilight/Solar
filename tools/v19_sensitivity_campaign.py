#!/usr/bin/env python3
"""APMT V1.9-D — global sensitivity campaign (Sobol + screening cross-check).

Runs the variance-based global sensitivity analysis over the validated design
space for each operating regime, at the high-fidelity level (L4) with a labelled
lower-fidelity screening comparison (L2), and writes ONE compact artifact:

    data/v19_sensitivity.json

Cost is dominated by L4 evaluations: 2 + 2d blocks x N base samples x replicates
x regimes. The design is regenerable from (seed, bounds, names), so the artifact
stores the design FINGERPRINT rather than the sample matrix (item 22: no artifact
explosion, no per-point files).

Usage
-----
    python tools/v19_sensitivity_campaign.py --write
    python tools/v19_sensitivity_campaign.py --write --regimes nominal_1sun_25c
    python tools/v19_sensitivity_campaign.py --write --n-base 32 --replicates 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from apmt.sensitivity.campaign import (DESIGN_PARAMETERS, INVESTIGATED_INVALID_REGIMES,
                                       OUTPUTS, REGIMES, _rejection_ledger,
                                       estimator_validation, interaction_study,
                                       level_valid_default, lhs_crosscheck,
                                       regime_comparison, response_shape,
                                       run_regime, sampling_distribution_effect,
                                       shared_validated_box, spearman_rank,
                                       validated_box)
from apmt.sensitivity.sobol import DEFAULT_N_BASE

OUT = os.path.join(HERE, "data", "v19_sensitivity.json")
GENERATED_BY = "tools/v19_sensitivity_campaign.py"

#: the axes used for the (more expensive) pairwise interaction study: the dominant
#: axes of the campaign, chosen AFTER the main analysis, from its own ranking
INTERACTION_AXES = ("perovskite_eg_ev", "perovskite_thickness_nm", "rs_ohm_cm2",
                    "arc_thickness_nm")
INTERACTION_LEVEL = "L4"
LABEL = "PRE-GATE / MODEL-OBSERVED / EXPLORATORY"
L5_CHECKS = ("pce_pct", "jsc_ma_cm2", "voc_v", "ff", "temperature_k")


def _environment_metadata() -> dict:
    import subprocess

    def _cmd(*args) -> str:
        try:
            return subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except Exception:                                       # pragma: no cover
            return ""

    from apmt.core.numerics import array_sha256
    from apmt.params.registry import ParamSet, all_specs
    base = ParamSet.defaults()
    vec = np.array([float(base[s.name]) for s in all_specs()])
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "git_commit": _cmd("git", "rev-parse", "HEAD"),
        "git_dirty": bool(_cmd("git", "status", "--porcelain")),
        "registry_defaults_fingerprint": array_sha256(vec),
        "registry_size": len(all_specs()),
        "units": {"pce_pct": "%", "jsc_ma_cm2": "mA/cm2", "voc_v": "V", "ff": "1",
                  "temperature_k": "K", "heat_load_mw_cm2": "mW/cm2"},
        "topology": "monolithic two-terminal tandem (current-matched), "
                    "perovskite top / silicon bottom",
    }


def _l5_verification(names, regime, box, n_base: int, seed: int) -> dict:
    """Does the L4 ranking survive at the highest fidelity (L5)? (Update J seed)"""
    from apmt.device.batch import batch_evaluate
    from apmt.params.registry import ParamSet
    from apmt.sensitivity.campaign import _output_matrix
    from apmt.sensitivity.sobol import saltelli_design, sobol_indices
    design = saltelli_design(names, n_base=n_base, low=box["low"], high=box["high"],
                             seed=seed, second_order=False)
    base = ParamSet.defaults().with_mapping(dict(regime.settings))
    recs, summ = batch_evaluate(design.matrix(), names, level="L5", base=base,
                                campaign_id=f"v19d-l5:{regime.name}", seed=seed)
    Y = _output_matrix(recs)
    out = {"level": "L5", "n_base": n_base, "rejections": _rejection_ledger(recs),
           "per_output": {}}
    for j, key in enumerate(OUTPUTS):
        if key not in L5_CHECKS:
            continue
        rep = sobol_indices(Y[:, j], design, output=key, bootstrap=0)
        out["per_output"][key] = {"total": {n: float(v) for n, v in zip(names, rep.total)},
                                  "complete": rep.complete}
    return out


def _crosscheck_regime(regime, res, box, level, campaign_id="v19d-lhscross") -> dict:
    """LHS / monotone cross-check on the design's own random blocks (no extra cost:
    the A blocks of the Sobol designs ARE Latin-hypercube-style random samples)."""
    from apmt.device.batch import batch_evaluate
    from apmt.params.registry import ParamSet
    from apmt.sensitivity.campaign import _output_matrix, lhs_crosscheck
    names = tuple(res["parameters"])
    base = ParamSet.defaults().with_mapping(dict(regime.settings))
    per_replicate = []
    for entry in res["designs"]:
        bounds = entry["bounds"]
        low = np.array([bounds[n][0] for n in names])
        high = np.array([bounds[n][1] for n in names])
        from apmt.sensitivity.sobol import saltelli_design
        design = saltelli_design(names, n_base=entry["n_base"], low=low, high=high,
                                 seed=entry["seed"], second_order=False)
        X = design.A                     # the random (LHS-like) sample block
        recs, _ = batch_evaluate(X, names, level=level, base=base,
                                 campaign_id=f"{campaign_id}:{regime.name}",
                                seed=entry["seed"])
        per_replicate.append(lhs_crosscheck(X, _output_matrix(recs), names))
    return {"regime": regime.name, "level": level,
            "n_replicates": len(per_replicate),
            "note": ("cross-check on the A blocks of the Sobol designs: Spearman "
                     "rank correlation and standardised regression coefficients "
                     "answer a monotone/linear question, Sobol indices a variance "
                     "one; agreement means importance is not method-dependent"),
            "per_replicate": per_replicate}


#: independently executable, independently mergeable sections. An expensive
#: measurement must never be lost because a later section crashed.
SECTIONS = ("box", "regimes", "crosscheck", "l5", "estimator", "interactions",
            "shapes", "prior")

#: which top-level artifact keys each section owns (used by merge-on-write)
SECTION_KEYS = {
    "box": ("shared_box", "unreachable_regimes"),
    "regimes": ("regimes", "regime_comparison", "campaign", "design_parameters",
                "outputs", "levels"),
    "crosscheck": ("lhs_crosscheck",),
    "l5": ("l5_verification",),
    "estimator": ("estimator_validation",),
    "interactions": ("interaction_study",),
    "shapes": ("response_shape",),
    "prior": ("prior_sensitivity",),
}


def _flush(art: dict, sections, generated_by: str, runtime_s: float) -> dict:
    """Merge the produced sections into data/v19_sensitivity.json and rewrite it."""
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                previous = json.load(f)
            for key, value in previous.items():
                art.setdefault(key, value)
        except Exception as exc:                                # pragma: no cover
            print(f"WARNING: could not merge existing artifact ({exc})")
    art.setdefault("label", LABEL)
    art.setdefault("generated_by", generated_by)
    art["sections_present"] = sorted(set(art.get("sections_present", [])) |
                                     set(sections))
    # cumulative over the section runs that produced this artifact (a full
    # single-process run contributes its total once; incremental section runs add
    # up). Wall clock is machine-specific and never enters the physics digest.
    art["runtime_s_cumulative"] = round(
        float(art.get("runtime_s_cumulative", 0.0)) + runtime_s, 3)
    art.pop("runtime_s", None)
    art["metadata"] = _environment_metadata()
    art = _round_floats(art)
    from apmt.repro.digest import digest_block
    art["physics_digest"] = digest_block({k: v for k, v in art.items()
                                          if k != "physics_digest"})
    payload = json.dumps(art, indent=1, sort_keys=True, default=str)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        f.write(payload)
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({len(payload)} B) digest "
          f"{art['physics_digest']['sha256'][:16]}... sections {art['sections_present']}",
          flush=True)
    return art


def run(n_base: int = DEFAULT_N_BASE, replicates: int = 2, level: str = "L4",
        screening_level: str = "L2", regime_names=None, l5_n_base: int = 48,
        seed0: int = 20261004, probe: int = 160, interaction_n_base: int = 768,
        interaction_regimes=None, sections=SECTIONS) -> dict:
    from apmt.multifidelity.levels import evaluate_level
    sections = tuple(sections)
    regimes = [r for r in REGIMES
               if regime_names is None or r.name in set(regime_names)]
    started = time.time()
    names = DESIGN_PARAMETERS
    artifact: dict = {"label": LABEL, "generated_by": GENERATED_BY,
                      "campaign": "V1.9-D global sensitivity foundation",
                      "design_parameters": list(names), "outputs": list(OUTPUTS),
                      "levels": {"analysis": level, "screening": screening_level,
                                 "verification": "L5"}}

    # ---- unreachable regimes (recorded, not dropped) ------------------------
    unreachable = []
    for entry in INVESTIGATED_INVALID_REGIMES:
        from apmt.sensitivity.campaign import Regime
        reg = Regime(name="probe", description=entry["description"],
                     settings=dict(entry["settings"]))
        if not level_valid_default(reg, level):
            unreachable.append({**entry, "level": level,
                                "why": "registered default device is INVALID in this "
                                       "regime (junction temperature leaves the "
                                       "electrical validity envelope)"})
    artifact["unreachable_regimes"] = unreachable

    # ---- shared validated box ----------------------------------------------
    shared_box = None
    if "box" in sections or not os.path.exists(OUT):
        shared_box = shared_validated_box(names, regimes, level=level, n_probe=probe,
                                          seed=seed0 + 11,
                                          campaign_id="v19d-sharedbox")
        if not shared_box.get("ok"):
            raise SystemExit(f"no shared valid box: {shared_box.get('failure')}")
        artifact["shared_box"] = {
            "scale": shared_box["scale"],
            "intersection_scale": shared_box.get("intersection_scale"),
            "low": {n: float(v) for n, v in zip(names, shared_box["low"])},
            "high": {n: float(v) for n, v in zip(names, shared_box["high"])},
            "registered_used": bool(shared_box.get("registered_box_used")),
            "restricted_axes": shared_box.get("restricted_axes", []),
            "per_regime_probes": shared_box.get("per_regime", {}),
            "probe_history": shared_box.get("probe_history", []),
            "note": "one box shared by all regimes so that index differences are "
                    "regime effects, not box effects; built as the per-axis "
                    "INTERSECTION of the per-regime validated boxes and verified "
                    "by probe in every regime"}
        _flush(artifact, ("box",), GENERATED_BY, time.time() - started)
    if shared_box is None:
        with open(OUT) as f:
            prev = json.load(f)
        shared_box = {"low": {n: prev["shared_box"]["low"][n] for n in names},
                      "high": {n: prev["shared_box"]["high"][n] for n in names}}
    # normalised named form, used by sections that analyse a SUBSET of the axes
    if isinstance(shared_box["low"], dict):
        shared_box_named = {"low": {n: float(shared_box["low"][n]) for n in names},
                            "high": {n: float(shared_box["high"][n]) for n in names}}
    else:
        shared_box_named = {"low": {n: float(v) for n, v in zip(names, shared_box["low"])},
                            "high": {n: float(v) for n, v in zip(names, shared_box["high"])}}

    results = {}
    if "regimes" in sections:
        cross_checks = {}
        for reg in regimes:
            t0 = time.time()
            res = run_regime(reg, names=names, box=shared_box_named, level=level,
                             n_base=n_base, replicates=replicates, seed0=seed0,
                             second_order=True, bootstrap=100,
                             screening_level=screening_level,
                             campaign_id="v19d-sensitivity")
            results[reg.name] = res
            artifact["regimes"] = results
            print(f"[sensitivity] {reg.name}: {time.time() - t0:.1f} s "
                  f"status={res.get('status')}", flush=True)
            # MEASURED DATA IS FLUSHED FIRST: a failure while computing a derived
            # view must never cost the expensive evaluations that are already done
            _flush(artifact, ("regimes",), GENERATED_BY, time.time() - started)
            try:
                artifact["regime_comparison"] = regime_comparison(results, names)
                if "crosscheck" in sections and res.get("status") == "OK":
                    cross_checks[reg.name] = _crosscheck_regime(reg, res, shared_box,
                                                                level)
                    artifact["lhs_crosscheck"] = cross_checks
                _flush(artifact, ("regimes", "crosscheck"), GENERATED_BY,
                       time.time() - started)
            except Exception as exc:                            # noqa: BLE001
                print(f"WARNING: derived sections failed ({type(exc).__name__}: "
                      f"{exc}); measured sections are already written", flush=True)
    else:
        with open(OUT) as f:
            prev = json.load(f)
        results = prev.get("regimes", {})

    if "estimator" in sections:
        artifact["estimator_validation"] = estimator_validation(
            n_base_main=n_base, n_base_pairs=interaction_n_base,
            n_dim_pairs=len(INTERACTION_AXES))
        _flush(artifact, ("estimator",), GENERATED_BY, time.time() - started)

    if "l5" in sections and results:
        ref_regime = regimes[0]
        if results.get(ref_regime.name, {}).get("status") == "OK":
            t0 = time.time()
            l5 = _l5_verification(names, ref_regime, shared_box_named, l5_n_base,
                                  seed0 + 3)
            l4_rank = results[ref_regime.name]["indices"]["pce_pct"]["mean_total"]
            l5_rank = l5["per_output"]["pce_pct"]["total"]
            l5["vs_l4_pce_pct"] = {
                "spearman_rank_correlation": spearman_rank(
                    [l4_rank[n] for n in names], [l5_rank[n] for n in names]),
                "l4_total": {n: float(l4_rank[n]) for n in names},
                "l5_total": {n: float(v) for n, v in l5_rank.items()}}
            artifact["l5_verification"] = l5
            print(f"[l5-verify] {time.time() - t0:.1f} s", flush=True)
            _flush(artifact, ("l5",), GENERATED_BY, time.time() - started)

    if "interactions" in sections:
        existing = {}
        if os.path.exists(OUT):
            try:
                with open(OUT) as f:
                    existing = json.load(f).get("estimator_validation", {}) or {}
            except Exception:                                   # pragma: no cover
                existing = {}
        floor = (artifact.get("estimator_validation", {}) or {}).get(
            "pairwise_order", {}).get("detection_floor")
        if floor is None:
            floor = existing.get("pairwise_order", {}).get("detection_floor")
        if floor is None:
            # no calibration available: compute the FULL one (a stub must never
            # overwrite, or stand in for, a real calibration section)
            artifact["estimator_validation"] = estimator_validation(
                n_base_main=n_base, n_base_pairs=interaction_n_base,
                n_dim_pairs=len(INTERACTION_AXES))
            floor = artifact["estimator_validation"]["pairwise_order"][
                "detection_floor"]
        else:
            # reuse the calibration already in the file, and make sure the file
            # keeps the FULL section (not a stub) on rewrite
            if existing and "first_total_order" not in (
                    artifact.get("estimator_validation") or {}):
                artifact["estimator_validation"] = existing
        interactions = {}
        for reg in regimes:
            if interaction_regimes and reg.name not in set(interaction_regimes):
                continue
            t0 = time.time()
            interactions[reg.name] = interaction_study(
                INTERACTION_AXES, reg, shared_box_named, level=INTERACTION_LEVEL,
                n_base=interaction_n_base, detection_floor=floor,
                campaign_id="v19d-interactions")
            print(f"[interactions] {reg.name}: {time.time() - t0:.1f} s", flush=True)
            artifact["interaction_study"] = {
                "axes": list(INTERACTION_AXES), "level": INTERACTION_LEVEL,
                "n_base": interaction_n_base, "detection_floor": floor,
                "why_reduced": ("pairwise indices need a much larger N than "
                                "first/total order; the campaign concentrates its "
                                "budget on the dominant axes rather than reporting "
                                "noise for 14"),
                "results": interactions}
            _flush(artifact, ("interactions",), GENERATED_BY, time.time() - started)

    if "shapes" in sections:
        t0 = time.time()
        artifact["response_shape"] = {
            r.name: response_shape(names, r, shared_box_named, level=level,
                                   campaign_id="v19d-shapes")
            for r in regimes}
        print(f"[shapes] {time.time() - t0:.1f} s", flush=True)
        _flush(artifact, ("shapes",), GENERATED_BY, time.time() - started)

    if "prior" in sections:
        t0 = time.time()
        attempt = sampling_distribution_effect("rsh_ohm_cm2", regimes[0],
                                               level=level, n_base=n_base,
                                               campaign_id="v19d-prior")
        attempt["status"] = "DIAGNOSTIC / NEGATIVE RESULT"
        attempt["why_not_reportable"] = (
            "the log-uniform prior reaches the low-shunt region where the model's "
            "own extraction invariants fail (electrical.range.ff / pce_pct / "
            "jmp_ma_cm2), and the remaining complete-design indices at this N are "
            "estimator-noise dominated (an FF first-order index of -1.11 is not a "
            "physical statement). The distribution dependence is therefore reported "
            "from the response-shape evidence and deferred to V1.9-E, where the "
            "prior/uncertainty machinery belongs.")
        artifact["prior_sensitivity"] = attempt
        print(f"[prior] {time.time() - t0:.1f} s", flush=True)
        _flush(artifact, ("prior",), GENERATED_BY, time.time() - started)

    _flush(artifact, sections, GENERATED_BY, time.time() - started)
    return artifact


def _round_floats(obj, ndigits: int = 6):
    """Round floats for storage. The 7th decimal of a Sobol index is far below its
    sampling error (measured in the tests), so nothing scientific is lost, and the
    artifact stays compact."""
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits) if np.isfinite(obj) else None
    return obj


def augment(path: str = OUT) -> int:
    """Add the cheap derived sections (LHS cross-check, regime comparison) to an
    existing artifact without re-paying for the Sobol designs.

    The Sobol designs ARE the expensive part (17k L4 evaluations); the cross-check
    only needs the A blocks, which are regenerable from the seeds and bounds
    recorded in the artifact. This is the artifact-merge discipline: expensive
    measurements are never recomputed to add a derived view.
    """
    from apmt.sensitivity.campaign import Regime as _Regime
    with open(path) as f:
        art = json.load(f)
    names = art["design_parameters"]
    cross, cmp_input = {}, {}
    for reg_name, res in art["regimes"].items():
        if res.get("status") != "OK":
            continue
        regime = _Regime(reg_name, res["regime"]["description"],
                         res["regime"]["settings"], level=res["level"])
        box = {"low": np.array([res["box"]["low"][n] for n in names]),
               "high": np.array([res["box"]["high"][n] for n in names])}
        t0 = time.time()
        cross[reg_name] = _crosscheck_regime(regime, res, box, res["level"])
        cmp_input[reg_name] = res
        print(f"[crosscheck] {reg_name}: {time.time() - t0:.1f} s", flush=True)
    art["lhs_crosscheck"] = cross
    art.setdefault("regime_comparison", None)
    from apmt.sensitivity.campaign import regime_comparison as _rc
    art["regime_comparison"] = _rc(cmp_input, names, output="pce_pct")
    art = _round_floats(art)
    from apmt.repro.digest import digest_block
    art["physics_digest"] = digest_block({k: v for k, v in art.items()
                                          if k != "physics_digest"})
    payload = json.dumps(art, indent=1, sort_keys=True, default=str)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(payload)
    os.replace(tmp, path)
    print(f"augmented {path} ({len(payload)} B) "
          f"digest {art['physics_digest']['sha256'][:16]}...")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default=",".join(SECTIONS),
                    help="comma-separated subset of " + ",".join(SECTIONS))
    ap.add_argument("--augment", action="store_true",
                    help="add the derived cross-check/comparison sections to the "
                         "existing artifact without recomputing the Sobol designs")
    ap.add_argument("--n-base", type=int, default=DEFAULT_N_BASE)
    ap.add_argument("--replicates", type=int, default=2)
    ap.add_argument("--level", default="L4")
    ap.add_argument("--screening-level", default="L2")
    ap.add_argument("--l5-n-base", type=int, default=48)
    ap.add_argument("--probe", type=int, default=160)
    ap.add_argument("--interaction-n-base", type=int, default=768)
    ap.add_argument("--interaction-regimes",
                    default="nominal_1sun_25c,concentrated_3sun_25c")
    ap.add_argument("--regimes", default=None,
                    help="comma-separated regime names (default: all)")
    args = ap.parse_args()
    if args.augment:
        return augment(OUT)
    sections = tuple(x for x in args.sections.split(",") if x)
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise SystemExit(f"unknown sections: {sorted(unknown)}")
    regime_names = args.regimes.split(",") if args.regimes else None
    out = run(n_base=args.n_base, replicates=args.replicates, level=args.level,
              screening_level=args.screening_level, regime_names=regime_names,
              l5_n_base=args.l5_n_base, probe=args.probe,
              interaction_n_base=args.interaction_n_base,
              interaction_regimes=(args.interaction_regimes.split(",")
                                   if args.interaction_regimes else None),
              sections=sections)
    n_evals = sum(d["n_evaluations"] for r in out.get("regimes", {}).values()
                  for d in r.get("designs", []))
    print(f"design evaluations in this artifact: {n_evals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
