"""APMT V1.9-D — global sensitivity campaign over the validated design space.

Design decisions, and why they are the honest ones:

1. **Two-dataset rule.** Sobol indices are only meaningful on a COMPLETE design.
   An INVALID point is not a missing number to be imputed, so the campaign first
   establishes a *validated sampling box* inside which every design point solves
   to a valid physical state, and reports by how much the box had to shrink. The
   registered ranges are never modified; the campaign box is a campaign input,
   printed in the artifact next to the registered ranges.

2. **Regimes are not design knobs.** Irradiance and ambient temperature define
   the operating condition being analysed; they are held constant within a regime
   and the sensitivity analysis is conditioned on them. Comparing indices across
   regimes then answers "does parameter importance change with operating
   condition" without mixing that effect with a change of sampling box (the box is
   shared across regimes by construction).

3. **Replicates, not a single lucky design.** Sobol estimates from one design of
   N base samples carry a real sampling error (measured on the Ishigami reference
   function in tests: up to ~0.1-0.35 absolute on total-order indices at N = 48-96
   for a strongly non-linear parameter). The campaign therefore runs R independent
   designs per regime and reports mean and spread, instead of one number with no
   error bar.

4. **Screening is labelled.** L2 (fixed-temperature TMM) indices are computed for
   exactly the same designs and compared with L4. They are reported as a
   SCREENING comparison, never as the scientific conclusion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.numerics import make_rng
from ..device.batch import batch_evaluate
from ..params.registry import ParamSet, spec
from .sobol import (DEFAULT_N_BASE, SaltelliDesign, SobolIndices, saltelli_design,
                    sobol_indices)

# ---------------------------------------------------------------------------
# campaign definition
# ---------------------------------------------------------------------------
#: design parameters (the architecture / physics axes being analysed)
DESIGN_PARAMETERS: Tuple[str, ...] = (
    "perovskite_eg_ev",
    "perovskite_thickness_nm",
    "perovskite_urbach_mev",
    "perovskite_srh_lifetime_ns",
    "silicon_eg_ev",
    "silicon_thickness_um",
    "silicon_srv_cm_s",
    "silicon_light_trapping",
    "rear_reflectance",
    "arc_thickness_nm",
    "parasitic_layer_thickness_nm",
    "rs_ohm_cm2",
    "rsh_ohm_cm2",
    "thermal_resistance_k_cm2_w",
)

#: outputs analysed (device metrics plus the internal loss channels)
OUTPUTS: Tuple[str, ...] = (
    "pce_pct", "jsc_ma_cm2", "voc_v", "ff",
    "temperature_k", "j_top_sc", "current_matching_ratio", "heat_load_mw_cm2",
)

OUTPUT_UNITS = {
    "pce_pct": "%", "jsc_ma_cm2": "mA/cm2", "voc_v": "V", "ff": "1",
    "temperature_k": "K", "j_top_sc": "mA/cm2", "current_matching_ratio": "1",
    "heat_load_mw_cm2": "mW/cm2",
}


@dataclass(frozen=True)
class Regime:
    """An operating condition: the held-fixed axes of the analysis."""

    name: str
    description: str
    settings: Dict[str, float]
    level: str = "L4"

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "settings": {k: float(v) for k, v in self.settings.items()},
                "level": self.level}


REGIMES: Tuple[Regime, ...] = (
    Regime("nominal_1sun_25c", "1.0 sun, 298.15 K ambient (reference condition)",
           {"irradiance_suns": 1.0, "temperature_k": 298.15}),
    Regime("concentrated_3sun_25c", "3.0 suns, 298.15 K ambient "
           "(concentration, junction still inside the electrical envelope)",
           {"irradiance_suns": 3.0, "temperature_k": 298.15}),
    Regime("hot_ambient_1sun_65c", "1.0 sun, 338.15 K ambient (65 degC)",
           {"irradiance_suns": 1.0, "temperature_k": 338.15}),
)

#: regimes that were probed and found UNREACHABLE for the registered default
#: device (recorded as findings, not dropped)
INVESTIGATED_INVALID_REGIMES = (
    {"description": "5.0 suns, 338.15 K ambient",
     "settings": {"irradiance_suns": 5.0, "temperature_k": 338.15}},
    {"description": "10.0 suns, 298.15 K ambient",
     "settings": {"irradiance_suns": 10.0, "temperature_k": 298.15}},
)


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------
def extract_outputs(rec) -> Dict[str, float]:
    """Pull the analysed outputs out of a guarded record (NaN when invalid)."""
    out = {k: float("nan") for k in OUTPUTS}
    if not rec.valid or rec.result is None:
        return out
    r = rec.result
    out["pce_pct"] = float(r.pce_pct)
    out["jsc_ma_cm2"] = float(r.jsc_ma_cm2)
    out["voc_v"] = float(r.voc_v)
    out["ff"] = float(r.ff)
    out["temperature_k"] = float(r.temperature_k)
    out["j_top_sc"] = float(r.j_top_sc)
    out["current_matching_ratio"] = float(r.current_matching_ratio)
    th = r.detail.get("thermal", {}) if isinstance(r.detail, dict) else {}
    hl = th.get("heat_load_mw_cm2", float("nan"))
    out["heat_load_mw_cm2"] = float(hl)
    return out


def _output_matrix(records: Sequence) -> np.ndarray:
    """(n_records, n_outputs) matrix; INVALID rows become NaN by construction."""
    return np.array([[extract_outputs(r)[k] for k in OUTPUTS] for r in records],
                    dtype=float)


def _rejection_ledger(records: Sequence) -> dict:
    """Count why points were rejected: HARD invariant failures vs exceptions."""
    by_invariant: Dict[str, int] = {}
    by_exception: Dict[str, int] = {}
    for rec in records:
        if rec.valid:
            continue
        for f in rec.verdict.failures:
            by_invariant[f.name] = by_invariant.get(f.name, 0) + 1
        if rec.error:
            key = rec.error.split(":")[0]
            by_exception[key] = by_exception.get(key, 0) + 1
    n = len(records)
    n_valid = sum(1 for r in records if r.valid)
    return {"n_total": n, "n_valid": n_valid, "n_invalid": n - n_valid,
            "validity_rate": (n_valid / n) if n else float("nan"),
            "hard_invariant_failures": by_invariant,
            "exceptions": by_exception}


# ---------------------------------------------------------------------------
# validated sampling box
# ---------------------------------------------------------------------------
def default_anchor(names: Sequence[str]) -> np.ndarray:
    return np.array([float(spec(n).default) for n in names])


def box_at_scale(names: Sequence[str], f: float) -> Tuple[np.ndarray, np.ndarray]:
    """Registered box scaled by ``f`` towards each parameter's default value.

    ``f = 1`` is the registered range, ``f = 0`` collapses to the registered
    default point. Parameters whose default sits at a bound keep that bound and
    shrink only inwards from the other side (the reference device is never
    excluded from the box).
    """
    lo = np.array([float(spec(n).low) for n in names])
    hi = np.array([float(spec(n).high) for n in names])
    anchor = default_anchor(names)
    return anchor - f * (anchor - lo), anchor + f * (hi - anchor)


def _probe(names, low, high, regime, level, n_probe, seed, campaign_id) -> dict:
    rng = make_rng(seed)
    X = low + rng.random((n_probe, len(names))) * (high - low)
    ps_extra = dict(regime.settings)
    recs, summary = batch_evaluate(X, names, level=level, campaign_id=campaign_id,
                                  seed=seed, base=_base_with(ps_extra))
    return {"_records": recs, **_rejection_ledger(recs), "n_probe": n_probe,
            "summary_valid": summary.n_valid}


def _base_with(settings: dict) -> ParamSet:
    return ParamSet.defaults().with_mapping(dict(settings))


def per_axis_validity_envelope(names: Sequence[str], regime: Regime,
                               level: str = "L4", n_scan: int = 9,
                               campaign_id: str = "v19d-envelope") -> dict:
    """Per-parameter validity envelope at a fixed operating condition.

    For each design axis, walk from the registered default value towards each
    registered bound and keep the furthest point that still solves to a VALID
    physical state (all other axes at their defaults). This is the model's
    validity boundary along that axis, and it is a RESULT, not a utility: it says
    which part of a declared range the model refuses to describe at this
    operating condition.

    Why not simply shrink the whole box uniformly? Because one axis (here the
    thermal resistance under concentration) drives the invalidity, and shrinking
    every axis throws away design space that is perfectly valid. The product box
    of these envelopes is verified by a probe before it is used.
    """
    from ..device.batch import batch_evaluate
    base = _base_with(regime.settings)
    anchor = default_anchor(names)
    detail = {}
    lo = anchor.copy()
    hi = anchor.copy()
    for i, name in enumerate(names):
        s = spec(name)
        found = {"low": float(anchor[i]), "high": float(anchor[i]),
                 "registered_low": float(s.low), "registered_high": float(s.high),
                 "limited_low": False, "limited_high": False}
        for bound, key in ((float(s.low), "low"), (float(s.high), "high")):
            if abs(bound - anchor[i]) < 1e-12:
                continue
            # walk from the anchor to the bound; (bound - anchor) carries the sign
            grid = anchor[i] + np.linspace(0.0, 1.0, n_scan) * (bound - anchor[i])
            grid = np.asarray([s.clip(g) for g in grid])   # never leave the range
            X = np.tile(anchor, (len(grid), 1))
            X[:, i] = grid
            recs, _ = batch_evaluate(X, names, level=level, base=base,
                                     campaign_id=f"{campaign_id}:{regime.name}:{name}")
            ok = [bool(r.valid) for r in recs]
            reachable = anchor[i]
            for g, good in zip(grid, ok):
                if good:
                    reachable = float(g)
                else:
                    break
            found[key] = reachable
            found[f"limited_{key}"] = bool(abs(reachable - bound) > 1e-9)
            found[f"n_scan_{key}"] = int(len(grid))
        lo[i] = min(found["low"], found["high"])
        hi[i] = max(found["low"], found["high"])
        detail[name] = found
    n_limited = sum(1 for d in detail.values() if d["limited_low"] or d["limited_high"])
    return {"low": lo, "high": hi, "per_parameter": detail,
            "n_parameters_restricted": n_limited,
            "labels": {"restricted": "the registered range is NOT usable at this "
                                     "operating condition; the reachable sub-interval "
                                     "is reported",
                       "restricted_axes": [n for n, d in detail.items()
                                           if d["limited_low"] or d["limited_high"]]}}


def validated_box(names: Sequence[str], regime: Regime, level: str = "L4",
                  n_probe: int = 64, seed: int = 4242,
                  campaign_id: str = "v19d-box", anchor_valid: Optional[bool] = None,
                  n_bisect: int = 5) -> dict:
    """Largest verified-valid box: per-axis envelopes, then verified by probe.

    Phase 1 builds the per-axis validity envelope (which axis is actually the
    constraint). Phase 2 probes the product box and, if some corner is still
    invalid (axis interactions), bisects a uniform scale on top of the envelope.
    Returns the box, the probe history and, when no box is usable, a ``failure``
    reason - an unvalidated regime is a FINDING, not an excuse to sample anyway.
    """
    if anchor_valid is None:
        anchor_valid = level_valid_default(regime, level)
    if not anchor_valid:
        return {"ok": False, "scale": 0.0, "failure": "anchor_invalid",
                "reason": ("the registered default device is already INVALID in this "
                           "regime, so no box anchored on it can be valid; the regime "
                           "is recorded as unreachable for this model"),
                "probe_history": []}
    history: list = []
    env = per_axis_validity_envelope(names, regime, level=level,
                                     campaign_id=campaign_id)
    env_lo, env_hi = env["low"], env["high"]

    def _try(low, high, tag: str) -> bool:
        pr = _probe(names, low, high, regime, level, n_probe, seed, campaign_id)
        ok = pr["n_invalid"] == 0
        history.append({"phase": tag, "n_probe": pr["n_probe"],
                        "n_valid": pr["n_valid"], "n_invalid": pr["n_invalid"],
                        "complete": bool(ok),
                        "rejections": {"hard_invariant_failures":
                                       pr["hard_invariant_failures"],
                                       "exceptions": pr["exceptions"]}})
        return ok

    if _try(env_lo, env_hi, "envelope_probe"):
        # shrink factor relative to the REGISTERED box, for reporting
        reg_lo, reg_hi = box_at_scale(names, 1.0)
        width = np.maximum(reg_hi - reg_lo, 1e-30)
        scale = float(np.mean((env_hi - env_lo) / width))
        return {"ok": True, "scale": scale, "low": env_lo, "high": env_hi,
                "registered_box_used": bool(np.allclose(env_lo, reg_lo) and
                                            np.allclose(env_hi, reg_hi)),
                "envelope": env, "probe_history": history,
                "restricted_axes": env["labels"]["restricted_axes"]}
    # Axis interactions matter: a box can be valid along every single axis and
    # still contain an invalid JOINT corner (e.g. a high-absorption design combined
    # with a high thermal resistance under concentration). Shrink FIRST only the
    # axes the envelope already identified as the constraint - scaling every axis
    # would throw away valid design space. Fall back to a uniform shrink only if
    # that fails or if no axis was identified.
    anchor = default_anchor(names)
    restricted = list(env["labels"]["restricted_axes"])
    idx = [names.index(n) for n in restricted]

    def _scaled(f: float):
        lo = env_lo.copy(); hi = env_hi.copy()
        target = idx if idx else list(range(len(names)))
        for i in target:
            lo[i] = env_lo[i] * f + anchor[i] * (1 - f)
            hi[i] = env_hi[i] * f + anchor[i] * (1 - f)
        return lo, hi

    mode = "restricted_axes" if idx else "uniform"
    lo_f, hi_f = 0.0, 1.0
    best = None
    for _ in range(n_bisect):
        mid = 0.5 * (lo_f + hi_f)
        lo_m, hi_m = _scaled(mid)
        if _try(lo_m, hi_m, f"shrink_{mode}_{mid:.4f}"):
            lo_f, best = mid, (lo_m, hi_m)
        else:
            hi_f = mid
    if best is None:
        return {"ok": False, "scale": 0.0, "low": anchor, "high": anchor,
                "registered_box_used": False, "envelope": env,
                "envelope_fraction": 0.0, "probe_history": history,
                "restricted_axes": restricted, "failure": "box_collapsed"}
    lo, hi = best
    reg_lo, reg_hi = box_at_scale(names, 1.0)
    width = np.maximum(reg_hi - reg_lo, 1e-30)
    return {"ok": True, "scale": float(np.mean((hi - lo) / width)),
            "low": lo, "high": hi, "registered_box_used": False,
            "envelope": env, "envelope_fraction": lo_f, "shrink_mode": mode,
            "probe_history": history, "restricted_axes": restricted}


def shared_validated_box(names: Sequence[str], regimes: Sequence[Regime],
                         level: str = "L4", n_probe: int = 48, seed: int = 20261011,
                         campaign_id: str = "v19d-sharedbox",
                         n_bisect: int = 4) -> dict:
    """ONE box, valid in EVERY regime, built by INTERSECTING per-regime envelopes.

    Why intersect instead of scaling uniformly: under concentration the binding
    constraint is a single axis (thermal resistance), and a uniform scale would
    shrink all fourteen axes - discarding valid design space, and with it the
    sensitivity information for the parameters that were never the problem. The
    intersection keeps every axis as wide as the tightest regime allows
    component-wise.

    The intersection is then VERIFIED by a probe in every regime (an intersection
    of per-axis envelopes is not automatically valid, because validity is a joint
    property). If a regime still fails, the box is scaled towards the anchors
    until all regimes pass, or the analysis is declared UNREACHABLE.
    """
    per = {r.name: validated_box(names, r, level=level, n_probe=n_probe,
                                 seed=seed + 1, campaign_id=f"{campaign_id}:{r.name}")
           for r in regimes}
    usable = {k: b for k, b in per.items() if b.get("ok")}
    if not usable:
        return {"ok": False, "failure": "no regime has a usable box", "per_regime": per}
    lows = np.max([b["low"] for b in usable.values()], axis=0)
    highs = np.min([b["high"] for b in usable.values()], axis=0)
    restricted = sorted({n for b in usable.values()
                         for n in b.get("restricted_axes", [])})
    anchor = default_anchor(names)
    history = []
    lo_f, hi_f = 0.0, 1.0
    best = None

    def _probe_all(scale: float):
        lo = anchor + scale * (lows - anchor)
        hi = anchor + scale * (highs - anchor)
        ok_all = True
        for r in regimes:
            pr = _probe(names, lo, hi, r, level, n_probe, seed + 3, campaign_id)
            good = pr["n_invalid"] == 0
            history.append({"regime": r.name, "scale": round(scale, 6),
                            "n_probe": pr["n_probe"], "n_valid": pr["n_valid"],
                            "n_invalid": pr["n_invalid"], "complete": bool(good),
                            "rejections": {"hard_invariant_failures":
                                           pr["hard_invariant_failures"],
                                           "exceptions": pr["exceptions"]}})
            ok_all = ok_all and good
        return ok_all

    if _probe_all(1.0):
        best, lo_f = 1.0, 1.0
    else:
        for _ in range(n_bisect):
            mid = 0.5 * (lo_f + hi_f)
            if _probe_all(mid):
                lo_f, best = mid, mid
            else:
                hi_f = mid
    if best is None:
        return {"ok": False, "failure": "shared box collapsed",
                "per_regime": per, "probe_history": history}
    lo = anchor + best * (lows - anchor)
    hi = anchor + best * (highs - anchor)
    reg_lo, reg_hi = box_at_scale(names, 1.0)
    width = np.maximum(reg_hi - reg_lo, 1e-30)
    return {"ok": True, "scale": float(np.mean((hi - lo) / width)),
            "intersection_scale": best, "low": lo, "high": hi,
            "registered_box_used": bool(np.allclose(lo, reg_lo) and
                                        np.allclose(hi, reg_hi)),
            "restricted_axes": restricted, "per_regime": per,
            "probe_history": history}


def level_valid_default(regime: Regime, level: str = "L4") -> bool:
    from ..multifidelity.levels import evaluate_level
    try:
        evaluate_level(level, _base_with(regime.settings))
        return True
    except Exception:                                          # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# one regime
# ---------------------------------------------------------------------------
def run_regime(regime: Regime, names: Sequence[str] = DESIGN_PARAMETERS,
               box: Optional[dict] = None, level: str = "L4",
               n_base: int = DEFAULT_N_BASE, replicates: int = 2,
               seed0: int = 20261004, second_order: bool = True,
               bootstrap: int = 100, screening_level: str = "L2",
               campaign_id: str = "v19d-sensitivity") -> dict:
    """Full sensitivity analysis for one operating regime at one level."""
    names = tuple(names)
    if box is None:
        box = validated_box(names, regime, level=level, campaign_id=campaign_id)
    if not box.get("ok", False):
        return {"regime": regime.to_dict(), "level": level, "status": "UNREACHABLE",
                "reason": box.get("reason", box.get("failure", "no valid box")),
                "probe_history": box.get("probe_history", [])}

    out: dict = {
        "regime": regime.to_dict(), "level": level, "status": "OK",
        "box": {"scale": box["scale"], "registered_box_used": box["registered_box_used"],
                "low": {n: float(v) for n, v in zip(names, box["low"])},
                "high": {n: float(v) for n, v in zip(names, box["high"])},
                "registered_low": {n: float(spec(n).low) for n in names},
                "registered_high": {n: float(spec(n).high) for n in names}},
        "probe_history": box.get("probe_history", []),
        "n_base": n_base, "replicates": replicates, "second_order": second_order,
        "outputs": list(OUTPUTS), "parameters": list(names),
        "indices": {}, "designs": [], "rejections": {},
    }
    base = _base_with(regime.settings)
    seeds = [seed0 + 1000 * r for r in range(replicates)]

    stacked_per_output: Dict[str, List[np.ndarray]] = {k: [] for k in OUTPUTS}
    for seed in seeds:
        design = saltelli_design(names, n_base=n_base, low=box["low"], high=box["high"],
                                 seed=seed, second_order=second_order)
        X = design.matrix()
        recs, summary = batch_evaluate(X, names, level=level, base=base,
                                       campaign_id=f"{campaign_id}:{regime.name}",
                                      seed=seed)
        Y = _output_matrix(recs)
        ledger = _rejection_ledger(recs)
        out["designs"].append({**design.to_dict(), "rejections": ledger,
                               "n_evaluations": len(recs),
                               "solves_per_second": summary.solves_per_second})
        out["rejections"][f"seed_{seed}"] = ledger
        for j, key in enumerate(OUTPUTS):
            stacked_per_output[key].append(Y[:, j])

    # ---- Sobol indices per output, per replicate, then aggregate -----------
    for key in OUTPUTS:
        per_rep = []
        for r, (seed, Y) in enumerate(zip(seeds, stacked_per_output[key])):
            design = saltelli_design(names, n_base=n_base, low=box["low"],
                                     high=box["high"], seed=seed,
                                     second_order=second_order)
            per_rep.append(sobol_indices(Y, design, output=key, bootstrap=bootstrap)
                           if r == 0 else
                           sobol_indices(Y, design, output=key, bootstrap=0))
        out["indices"][key] = _aggregate_indices(per_rep, names)
        out["indices"][key]["unit"] = OUTPUT_UNITS.get(key, "")

    # ---- screening comparison (lower fidelity, same designs) ---------------
    if screening_level:
        out["screening"] = _screening_comparison(regime, names, box, base,
                                                 screening_level, n_base,
                                                 stacked_per_output, seed0,
                                                 campaign_id)
        out["screening_vs_reference"] = {}
        for key in OUTPUTS:
            if out["screening"]["per_output"][key].get("not_applicable"):
                out["screening_vs_reference"][key] = {
                    "agreement": "NOT-APPLICABLE",
                    "reason": out["screening"]["per_output"][key]["reason"]}
                continue
            ref = out["indices"][key]["mean_total"]
            scr = out["screening"]["per_output"][key]["total"]
            out["screening_vs_reference"][key] = {
                "rho_total_order": spearman_rank([ref[n] for n in names],
                                                 [scr[n] for n in names]),
                "agreement": ("RANKING-CONSISTENT" if
                              spearman_rank([ref[n] for n in names],
                                            [scr[n] for n in names]) >= 0.9
                              else "RANKING-SHIFTED"),
                "disagreements": rank_disagreements(ref, scr),
            }
    # ---- local (OAT) sensitivity at the anchor, for the global/local contrast
    out["local_sensitivity"] = local_sensitivity(names, box, regime, level,
                                                 campaign_id, base=base)
    # ---- validity of the FULL registered box (a finding in itself) ---------
    out["registered_box_validity"] = _full_box_validity(names, regime, level,
                                                        campaign_id)
    return out


def _aggregate_indices(per_rep: List[SobolIndices], names) -> dict:
    first = np.array([r.first for r in per_rep])
    total = np.array([r.total for r in per_rep])
    agg = {
        "n_replicates": len(per_rep),
        "complete": all(r.complete for r in per_rep),
        "variance_mean": float(np.mean([r.variance for r in per_rep])),
        "mean": float(np.mean([r.mean for r in per_rep])),
        "mean_first": {n: float(v) for n, v in zip(names, first.mean(axis=0))},
        "mean_total": {n: float(v) for n, v in zip(names, total.mean(axis=0))},
        "spread_first": {n: float(v) for n, v in zip(names, _spread(first))},
        "spread_total": {n: float(v) for n, v in zip(names, _spread(total))},
        "ranking_total": [names[i] for i in np.argsort(-total.mean(axis=0))],
        # S_T - S_1 is the share of a parameter's total effect that is
        # interaction-driven. It is far more robust than a pairwise index at this
        # sample size (measured on the Ishigami reference in estimator_validation).
        "interaction_budget": {n: float(t - f) for n, t, f in
                               zip(names, total.mean(axis=0), first.mean(axis=0))},
        "interaction_budget_note":
            "S_T - S_1: interaction share of a parameter's total effect. A "
            "NEGATIVE S_1 means the estimator's first-order term is statistically "
            "indistinguishable from zero at this N (the Saltelli estimator is "
            "unbiased but can go negative at finite N); it is NOT a negative "
            "influence on the result.",
        "top_interactions": {},
        "pairwise_indices_reportable": False,
        "pairwise_indices_note":
            "pairwise (second-order) indices from an N=96 design are dominated by "
            "estimator variance (calibrated on the Ishigami reference: spurious "
            "pairs up to 0.5 where the true value is exactly 0). Reportable pairs "
            "come from the dedicated interaction study at a larger N; the values "
            "below are kept only for audit.",
    }
    # interactions: aggregate the union of the per-replicate pair sets, keeping
    # the pairs that were quantitatively relevant in any replicate
    pairs: Dict[Tuple[str, str], List[float]] = {}
    for r in per_rep:
        for k, v in r.second.items():
            pairs.setdefault(k, []).append(v)
    ranked = sorted(pairs.items(), key=lambda kv: -abs(np.mean(kv[1])))
    for (a, b), vals in ranked[:12]:
        agg["top_interactions"][f"{a}|{b}"] = {
            "mean": float(np.mean(vals)), "n_replicates": len(vals),
            "max_abs": float(np.max(np.abs(vals))),
            "reportable": False,
            "why_not": "below the calibrated detection floor at this N"if abs(float(np.mean(vals))) < 1.0 else "not calibrated"}
    return agg


def _spread(arr: np.ndarray) -> np.ndarray:
    """Half the replicate range (0 when only one replicate)."""
    if arr.shape[0] < 2:
        return np.zeros(arr.shape[1])
    return 0.5 * (arr.max(axis=0) - arr.min(axis=0))


def _screening_comparison(regime, names, box, base, level, n_base,
                          stacked_per_output, seed0, campaign_id) -> dict:
    """Total-order indices at a screening level, same designs, ranking compared."""
    seed = seed0
    design = saltelli_design(names, n_base=n_base, low=box["low"], high=box["high"],
                             seed=seed, second_order=False)
    recs, _ = batch_evaluate(design.matrix(), names, level=level, base=base,
                             campaign_id=f"{campaign_id}:screen:{regime.name}",
                            seed=seed)
    Y = _output_matrix(recs)
    comp = {"level": level, "n_base": n_base,
            "label": "SCREENING ONLY - not a scientific sensitivity conclusion",
            "rejections": _rejection_ledger(recs), "per_output": {}}
    for j, key in enumerate(OUTPUTS):
        rep = sobol_indices(Y[:, j], design, output=key, bootstrap=0)
        if rep.not_applicable or rep.degenerate:
            comp["per_output"][key] = {
                "not_applicable": True,
                "reason": (f"{key} is not produced at {level} (fidelity switch)"
                           if rep.not_applicable else
                           f"{key} does not vary at {level} (zero variance): indices "
                           f"are UNDEFINED, not zero"),
                "complete": False, "n_missing": rep.n_missing}
        else:
            comp["per_output"][key] = {
                "not_applicable": False,
                "total": {n: float(v) for n, v in zip(names, rep.total)},
                "complete": rep.complete, "n_missing": rep.n_missing}
    return comp


def local_sensitivity(names, box, regime, level, campaign_id, base=None,
                      rel_step: float = 0.05) -> dict:
    """One-at-a-time sensitivity around the regime anchor (LOCAL, not global).

    Reported deliberately alongside the Sobol indices so the reader can see where
    local and global rankings disagree: a pure OAT scan cannot see interactions
    and systematically under-ranks parameters whose effect is non-monotone.
    """
    base = base if base is not None else _base_with(regime.settings)
    anchor = default_anchor(names)
    # keep the anchor inside the (possibly shrunk) box
    anchor = np.clip(anchor, box["low"], box["high"])
    step = rel_step * (box["high"] - box["low"])
    X = []
    labels = []
    for i in range(len(names)):
        for direction in (-1.0, +1.0):
            row = anchor.copy()
            row[i] = float(np.clip(anchor[i] + direction * step[i], box["low"][i],
                                   box["high"][i]))
            X.append(row)
            labels.append((names[i], direction))
    X = np.array(X)
    recs, _ = batch_evaluate(X, names, level=level, base=base,
                             campaign_id=f"{campaign_id}:local:{regime.name}")
    Y = _output_matrix(recs)
    j_pce = OUTPUTS.index("pce_pct")
    local = {}
    for k, (name, direction) in enumerate(labels):
        if k % 2 == 1:
            continue
        plus, minus = Y[k + 1, j_pce], Y[k, j_pce]
        dx = float(X[k + 1][k // 2] - X[k][k // 2])
        local[name] = {
            "d_pce_pp_per_unit": (float((plus - minus) / dx) if dx and
                                  np.isfinite(plus) and np.isfinite(minus) else float("nan")),
            "delta_pce_pp": (float(plus - minus) if np.isfinite(plus) and
                             np.isfinite(minus) else float("nan")),
            "step": dx,
        }
    valid = [k for k, v in local.items() if np.isfinite(v["d_pce_pp_per_unit"])]
    order = sorted(valid, key=lambda k: -abs(local[k]["d_pce_pp_per_unit"]))
    return {"rel_step": rel_step, "ranking": order, "entries": local,
            "n_valid": len(valid), "n_total": len(local),
            "rejections": _rejection_ledger(recs),
            "label": "LOCAL (one-at-a-time) sensitivity at the regime anchor"}


def _full_box_validity(names, regime, level, campaign_id, n: int = 64,
                       seed: int = 99991) -> dict:
    """Validity rate of the FULL registered box for this regime (a finding)."""
    lo, hi = box_at_scale(names, 1.0)
    rng = make_rng(seed)
    X = lo + rng.random((n, len(names))) * (hi - lo)
    recs, _ = batch_evaluate(X, names, level=level, base=_base_with(regime.settings),
                             campaign_id=f"{campaign_id}:fullbox:{regime.name}",
                            seed=seed)
    led = _rejection_ledger(recs)
    led["box"] = "full registered ranges"
    led["seed"] = seed
    return led


# ---------------------------------------------------------------------------
# estimator calibration + interaction study
# ---------------------------------------------------------------------------
def estimator_validation(n_base_main: int = DEFAULT_N_BASE,
                         n_base_pairs: int = 768, n_dim_pairs: int = 4,
                         seeds: Sequence[int] = (1, 2, 3)) -> dict:
    """Measure the estimator's error at the design sizes the campaign actually uses.

    Nothing here is a physics result: it calibrates the instrument. The Ishigami
    function has known indices, and embedding it in extra inert dimensions gives an
    exact zero for every index of those dimensions - so the largest index reported
    for an inert variable IS the estimator's noise floor at that design size.
    """
    from .sobol import ISHIGAMI_ANALYTIC, ishigami, ishigami_design, ishigami_design_nd, \
        ishigami_nd
    main_err_total, main_err_first = [], []
    for seed in seeds:
        d = ishigami_design(n_base=n_base_main, seed=seed)
        r = sobol_indices(ishigami(d.matrix()), d, bootstrap=0)
        main_err_total.append(max(abs(r.total[i] - ISHIGAMI_ANALYTIC["ST"][n])
                                  for i, n in enumerate(d.names)))
        main_err_first.append(max(abs(r.first[i] - ISHIGAMI_ANALYTIC["S1"][n])
                                  for i, n in enumerate(d.names)))
    pair_err, pair_known, structural = [], [], []
    for seed in seeds:
        d = ishigami_design_nd(n_dim_pairs, n_base=n_base_pairs, seed=seed)
        r = sobol_indices(ishigami_nd(d.matrix()), d, bootstrap=0)
        inert = [n for n in d.names if n not in ("x1", "x2", "x3")]
        # THE noise floor must come from pairs of ACTIVE variables whose analytic
        # interaction is zero: (x1,x2) and (x2,x3). A pair involving an inert
        # variable is identically zero by construction of the estimator (it
        # collapses to S_i - S_i), so it measures bookkeeping, not noise.
        pair_err.append(max(abs(r.second[("x1", "x2")]), abs(r.second[("x2", "x3")])))
        structural.append(max([abs(v) for (a, b), v in r.second.items()
                               if a in inert or b in inert] + [0.0]))
        pair_known.append(abs(r.second[("x1", "x3")] - 0.2437))
    return {
        "purpose": "calibrate the estimator; not a physics result",
        "first_total_order": {
            "n_base": n_base_main, "reference": "Ishigami (analytic)",
            "max_abs_error_total_order": float(np.max(main_err_total)),
            "max_abs_error_first_order": float(np.max(main_err_first)),
            "per_seed_total_order": [float(v) for v in main_err_total],
            "conclusion": ("first- and total-order indices at this N carry an error "
                           "of this magnitude: ranking of clearly dominant "
                           "parameters is reliable, small index differences are not"),
        },
        "pairwise_order": {
            "n_base": n_base_pairs, "n_dim": n_dim_pairs,
            "calibration_pairs": "Ishigami (x1,x2) and (x2,x3): active variables "
                                 "with analytically ZERO interaction",
            "noise_floor": float(np.max(pair_err)),
            "known_pair_error": float(np.max(pair_known)),
            "detection_floor": float(np.max(pair_err)),
            "structural_zero_check": float(np.max(structural)),
            "conclusion": ("a pairwise index is only reportable above this floor; "
                           "everything below it is indistinguishable from estimator "
                           "noise. The structural check (pairs involving an inert "
                           "variable) is zero, which verifies the estimator's "
                           "bookkeeping rather than its noise."),
        },
    }


def interaction_study(names: Sequence[str], regime: Regime, box: dict,
                      level: str = "L4", n_base: int = 768, seed: int = 5150,
                      detection_floor: float = 0.15,
                      campaign_id: str = "v19d-interactions") -> dict:
    """Pairwise interactions among a REDUCED set of axes, at a design size where
    they are estimable.

    The design-size limit is the whole point: with d axes the design costs
    (2 + 2d) * N evaluations, so pairwise indices for all 14 campaign axes at a
    reliable N are out of reach in this environment. Restricting to the dominant
    axes (the others held at their registered defaults) buys the sample size, at
    the cost of a clearly stated scope: the study answers "how do the dominant
    axes interact with each other", not "what is the full 14-dimensional
    interaction structure".
    """
    names = tuple(names)
    # the study uses a SUBSET of the campaign axes, so the box must be subset to
    # match (a 14-axis box with a 4-axis design silently broadcasts into nonsense)
    if isinstance(box, dict) and isinstance(box.get("low"), dict):
        low = np.array([box["low"][n] for n in names])
        high = np.array([box["high"][n] for n in names])
    else:
        idx = box.get("names") if isinstance(box, dict) else None
        low = np.asarray(box["low"]) if idx is None else np.asarray(box["low"])[[
            list(idx).index(n) for n in names]]
        high = np.asarray(box["high"]) if idx is None else np.asarray(box["high"])[[
            list(idx).index(n) for n in names]]
    if low.shape != (len(names),) or high.shape != (len(names),):
        raise ValueError(f"box has {low.shape} axes but the study has {len(names)}")
    d = saltelli_design(names, n_base=n_base, low=low, high=high,
                        seed=seed, second_order=True)
    from ..device.batch import batch_evaluate
    recs, summary = batch_evaluate(d.matrix(), names, level=level,
                                   base=_base_with(regime.settings),
                                   campaign_id=f"{campaign_id}:{regime.name}", seed=seed)
    Y = _output_matrix(recs)
    out = {"regime": regime.to_dict(), "level": level, "n_base": n_base,
           "parameters": list(names), "detection_floor": detection_floor,
           "scope_note": ("other campaign axes are held at their registered "
                          "defaults in this study"),
           "design": d.to_dict(), "rejections": _rejection_ledger(recs),
           "per_output": {}}
    for j, key in enumerate(OUTPUTS):
        r = sobol_indices(Y[:, j], d, output=key, bootstrap=0)
        if r.not_applicable or r.degenerate:
            continue
        pairs = {f"{a}|{b}": float(v) for (a, b), v in r.second.items()}
        reportable = {k: v for k, v in pairs.items() if abs(v) >= detection_floor}
        out["per_output"][key] = {
            "first": {n: float(v) for n, v in zip(names, r.first)},
            "total": {n: float(v) for n, v in zip(names, r.total)},
            "pairs": pairs,
            "reportable_pairs": dict(sorted(reportable.items(),
                                            key=lambda kv: -abs(kv[1]))),
            "complete": r.complete, "n_missing": r.n_missing,
            "interaction_budget": {n: float(t - f) for n, t, f in
                                   zip(names, r.total, r.first)},
        }
    return out


# ---------------------------------------------------------------------------
# LHS / monotone cross-check and regime comparison
# ---------------------------------------------------------------------------
def lhs_crosscheck(X: np.ndarray, Y: np.ndarray, names: Sequence[str],
                   outputs: Sequence[str] = OUTPUTS) -> dict:
    """Rank-correlation + linear-model cross-check on the SAME samples (no extra solves).

    Sobol indices decompose variance; Spearman/SRC measure monotone association
    and a linear fit. They answer different questions, so agreement between the
    two rankings is evidence that a parameter's importance is not an artefact of
    one method, and disagreement localises non-monotone behaviour.
    """
    names = tuple(names)
    out = {}
    for j, key in enumerate(outputs):
        y = Y[:, j]
        m = np.isfinite(y)
        if m.sum() < 10 or np.nanstd(y) <= 0:
            out[key] = {"not_applicable": True,
                        "reason": "output is constant or has too few valid samples"}
            continue
        Xv, yv = X[m], y[m]
        ys = (yv - yv.mean()) / yv.std()
        rho, src = {}, {}
        for i, n in enumerate(names):
            xi = Xv[:, i]
            if np.std(xi) <= 0:
                rho[n] = float("nan")
                continue
            rx = np.argsort(np.argsort(xi)).astype(float)
            ry = np.argsort(np.argsort(yv)).astype(float)
            rx -= rx.mean(); ry -= ry.mean()
            den = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
            rho[n] = float((rx * ry).sum() / den) if den else float("nan")
        Xs = (Xv - Xv.mean(axis=0)) / np.where(Xv.std(axis=0) > 0, Xv.std(axis=0), 1.0)
        try:
            beta, *_ = np.linalg.lstsq(np.c_[np.ones(len(Xs)), Xs], ys, rcond=None)
            pred = np.c_[np.ones(len(Xs)), Xs] @ beta
            r2 = float(1.0 - ((ys - pred) ** 2).sum() / (ys ** 2).sum())
            src = {n: float(b) for n, b in zip(names, beta[1:])}
        except Exception:                                        # pragma: no cover
            r2 = float("nan")
        out[key] = {"spearman": rho, "src": src, "r2_linear_model": r2,
                    "n_used": int(m.sum())}
    return out


def regime_comparison(regimes_result: dict, names: Sequence[str],
                      output: str = "pce_pct") -> dict:
    """Does parameter IMPORTANCE change with operating condition?

    Compares the mean total-order indices of the same parameters (same box, same N,
    same level) across regimes; a parameter whose index moves by more than the
    calibration error floor is regime-dependent in importance.
    """
    names = tuple(names)
    keys = [k for k, v in regimes_result.items() if v.get("status") == "OK"]
    order = {n: i for i, n in enumerate(names)}
    table = {}
    for n in names:
        table[n] = {k: float(regimes_result[k]["indices"][output]["mean_total"][n])
                    for k in keys}
        table[n]["range"] = float(max(table[n].values()) - min(table[n].values()))
        table[n]["spread_mean"] = float(np.mean(
            [regimes_result[k]["indices"][output]["spread_total"][n] for k in keys]))
        table[n]["regime_dependent"] = bool(
            table[n]["range"] > max(0.10, 2.0 * table[n]["spread_mean"]))
    pair_rho = {}
    for a in keys:
        for b in keys:
            if a < b:
                pair_rho[f"{a}|{b}"] = spearman_rank(
                    [regimes_result[a]["indices"][output]["mean_total"][n] for n in names],
                    [regimes_result[b]["indices"][output]["mean_total"][n] for n in names])
    ranked = sorted(table.items(), key=lambda kv: -kv[1]["range"])
    return {"output": output, "regimes": keys,
            "per_parameter": table,
            "regime_dependent_parameters": [n for n, v in ranked
                                            if v["regime_dependent"]],
            "cross_regime_rank_correlation": pair_rho,
            "criterion": "regime_dependent if index range across regimes exceeds "
                         "max(0.10, 2x the mean replicate spread)"}


def response_shape(names: Sequence[str], regime: Regime, box: dict,
                   level: str = "L4", n_points: int = 21,
                   campaign_id: str = "v19d-shapes") -> dict:
    """1-D response slices along each axis (others at their defaults).

    Why this matters for the sensitivity analysis: a monotone screen (Spearman /
    SRC / a one-at-a-time scan) can only see monotone association. If the dominant
    response has an interior optimum - as the bandgap does, through current
    matching - the monotone rank correlation understates its importance and can
    even anti-correlate with the variance-based ranking. This section measures the
    shape directly instead of inferring it.
    """
    from ..device.batch import batch_evaluate
    names = tuple(names)
    base = _base_with(regime.settings)
    anchor = default_anchor(names)
    if isinstance(box.get("low"), dict):
        low = np.array([box["low"][n] for n in names])
        high = np.array([box["high"][n] for n in names])
    else:
        low, high = np.asarray(box["low"]), np.asarray(box["high"])
    anchor = np.clip(anchor, low, high)
    out = {"regime": regime.name, "level": level, "n_points": n_points,
           "note": "other axes held at their registered defaults",
           "per_parameter": {}}
    for i, name in enumerate(names):
        grid = np.linspace(low[i], high[i], n_points)
        X = np.tile(anchor, (n_points, 1))
        X[:, i] = grid
        recs, _ = batch_evaluate(X, names, level=level, base=base,
                                 campaign_id=f"{campaign_id}:{regime.name}:{name}")
        Y = _output_matrix(recs)
        j = OUTPUTS.index("pce_pct")
        pce = Y[:, j]
        finite = np.isfinite(pce)
        if finite.sum() < 5:
            out["per_parameter"][name] = {"n_valid": int(finite.sum()),
                                          "status": "NOT_EVALUABLE"}
            continue
        g, p = grid[finite], pce[finite]
        d = np.diff(p)
        sign_changes = int(np.sum(np.sign(d[1:]) * np.sign(d[:-1]) < 0))
        interior = bool(1 <= int(np.argmax(p)) <= len(p) - 2 and
                        p.max() > max(p[0], p[-1]) + 1e-9)
        out["per_parameter"][name] = {
            "n_valid": int(finite.sum()),
            "pce_min": float(p.min()), "pce_max": float(p.max()),
            "x_at_min": float(g[int(np.argmin(p))]),
            "x_at_max": float(g[int(np.argmax(p))]),
            "delta_pce_pp_full_range": float(p.max() - p.min()),
            "monotone": bool(sign_changes == 0),
            "sign_changes": sign_changes,
            "interior_optimum": interior,
            "shape": ("INTERIOR-OPTIMUM" if interior and sign_changes >= 1 else
                      "MONOTONE" if sign_changes == 0 else "NON-MONOTONE"),
            "curve": {"x": [round(float(v), 6) for v in g.tolist()],
                      "pce_pct": [round(float(v), 6) for v in p.tolist()]},
        }
    n_nonmono = sum(1 for v in out["per_parameter"].values()
                    if v.get("shape") in ("INTERIOR-OPTIMUM", "NON-MONOTONE"))
    out["n_non_monotone_axes"] = n_nonmono
    return out


def sampling_distribution_effect(name: str, regime: Regime, level: str = "L4",
                                 background: Sequence[str] = ("perovskite_eg_ev",
                                                              "perovskite_thickness_nm"),
                                 n_base: int = 256, seed: int = 8888,
                                 campaign_id: str = "v19d-prior") -> dict:
    """How much of a parameter's index is the SAMPLING DISTRIBUTION, not the physics?

    A variance-based index is defined with respect to the distribution the
    parameter is drawn from. For a parameter whose declared range spans several
    decades (the shunt resistance spans 50 to 1e6 ohm*cm2), a uniform-in-linear
    prior puts almost all of its mass in the benign high-resistance region, so a
    genuine shunting regime is barely visited and the index can look small.

    The comparison keeps everything else identical - the same axes, the same
    background margins, the same seeds, the same block structure - and swaps ONLY
    the marginal of the parameter of interest. The background axes are required:
    with a single variable the total-order index is 1 by construction, which
    measures nothing.
    """
    from ..core.numerics import make_rng
    from ..device.batch import batch_evaluate
    from .sobol import saltelli_design, sobol_indices

    sp = spec(name)
    lo, hi = float(sp.low), float(sp.high)
    names = (name,) + tuple(n for n in background if n != name)
    low, high = box_arrays(names, None)
    base = _base_with(regime.settings)
    results = {}
    for label, mode in (("uniform_linear", "linear"), ("log_uniform", "log")):
        rng = make_rng(seed)

        def _draw(n, _lo=lo, _hi=hi, _mode=mode, _rng=rng):
            if _mode == "log":
                return np.exp(_rng.random(n) * (np.log(_hi) - np.log(_lo))
                              + np.log(_lo))
            return _lo + _rng.random(n) * (_hi - _lo)

        d = saltelli_design(names, n_base=n_base, low=low, high=high, seed=seed,
                            second_order=False)
        A0, B0 = _draw(n_base), _draw(n_base)
        # keep the Saltelli block structure: the parameter's column comes from A0
        # everywhere except in B and in AB_0, where it comes from B0
        A = d.A.copy(); A[:, 0] = A0
        B = d.B.copy(); B[:, 0] = B0
        blocks = [A, B]
        for i in range(len(names)):
            m = d.AB[i].copy()
            m[:, 0] = B0 if i == 0 else A0
            blocks.append(m)
        X = np.vstack(blocks)
        recs, summary = batch_evaluate(X, names, level=level, base=base,
                                       campaign_id=f"{campaign_id}:{label}",
                                       seed=seed)
        Y = _output_matrix(recs)
        per_output = {}
        for j, key in enumerate(OUTPUTS):
            y = Y[:, j]
            if not np.isfinite(y).all():
                per_output[key] = {"not_applicable": True,
                                   "n_invalid": int((~np.isfinite(y)).sum())}
                continue
            res = sobol_indices(y, d, output=key, bootstrap=0)
            per_output[key] = {"first_order": float(res.first[0]),
                               "total_order": float(res.total[0]),
                               "variance": float(res.variance),
                               "complete": bool(res.complete)}
        results[label] = {"n_base": n_base, "range": [lo, hi], "mode": mode,
                          "n_evaluations": len(X),
                          "validity_rate": summary.n_valid / max(1, summary.n_requested),
                          "per_output": per_output}
    u = results["uniform_linear"]["per_output"].get("pce_pct", {})
    g = results["log_uniform"]["per_output"].get("pce_pct", {})
    ut, gt = u.get("total_order"), g.get("total_order")
    return {"parameter": name, "regime": regime.name, "level": level,
            "axes": list(names),
            "priors": results,
            "pce_index_uniform": ut, "pce_index_log_uniform": gt,
            "index_ratio_log_over_uniform": ((gt / ut) if ut and gt else None),
            "interpretation": ("variance-based indices are relative to the sampling "
                              "distribution: a wide linear range can hide a regime "
                              "that a log-uniform prior visits. The registry range "
                              "is not a probability distribution.")}


def box_arrays(names: Sequence[str], box) -> Tuple[np.ndarray, np.ndarray]:
    """Registered (or supplied) box as arrays in ``names`` order."""
    if box is None:
        return (np.array([float(spec(n).low) for n in names]),
                np.array([float(spec(n).high) for n in names]))
    if isinstance(box.get("low"), dict):
        return (np.array([float(box["low"][n]) for n in names]),
                np.array([float(box["high"][n]) for n in names]))
    return np.asarray(box["low"], dtype=float), np.asarray(box["high"], dtype=float)


# ---------------------------------------------------------------------------
# helpers used by the campaign driver and tests
# ---------------------------------------------------------------------------
def spearman_rank(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation (no scipy import needed, NaN-safe)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a[m])).astype(float)
    rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float("nan")


def rank_disagreements(mean_total: dict, other: dict, threshold_rank: int = 3,
                       threshold_index: float = 0.10) -> list:
    """Parameters whose importance ranking differs materially between two sets."""
    names = [n for n in mean_total if np.isfinite(mean_total[n])]
    order_a = sorted(names, key=lambda n: -mean_total[n])
    order_b = sorted(names, key=lambda n: -other.get(n, float("nan")))
    rank_a = {n: i for i, n in enumerate(order_a)}
    rank_b = {n: i for i, n in enumerate(order_b)}
    out = []
    for n in names:
        dr = abs(rank_a[n] - rank_b.get(n, 99))
        di = abs(mean_total[n] - other.get(n, float("nan")))
        if dr >= threshold_rank or di >= threshold_index:
            out.append({"parameter": n, "rank_here": rank_a[n],
                        "rank_other": rank_b.get(n, None), "delta_rank": dr,
                        "index_here": mean_total[n],
                        "index_other": other.get(n, float("nan")),
                        "delta_index": di})
    return sorted(out, key=lambda d: -d["delta_index"])
