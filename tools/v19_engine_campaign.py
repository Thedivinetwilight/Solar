#!/usr/bin/env python3
"""V1.9-C engine campaign: levels, coupling, limits, convergence, inertness, benchmarks.

    python tools/v19_engine_campaign.py --write            # full campaign
    python tools/v19_engine_campaign.py --sections benchmark,divergence

Writes ONE compact artifact: data/v19_engine_campaign.json (plus
data/v19_thermal_investigation.json from tools/v19_thermal_investigation.py).
Every section is PRE-GATE / MODEL-OBSERVED / EXPLORATORY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from apmt.device.batch import batch_evaluate, dataset                # noqa: E402
from apmt.device.tandem import (clear_caches, emission_fraction_above_gap,   # noqa: E402
                                evaluate_tandem)
from apmt.multifidelity.levels import (LEVELS, divergence_study, evaluate_level,  # noqa: E402
                                       options_for)
from apmt.params.registry import ParamSet, all_specs                 # noqa: E402
from apmt.sensitivity.lhs import lhs_matrix                          # noqa: E402
from apmt.validation.guard import evaluate_guarded                   # noqa: E402

OUT = os.path.join(HERE, "data", "v19_engine_campaign.json")

DEFAULT_MATRIX_PARAMS = ("perovskite_eg_ev", "perovskite_thickness_nm",
                         "arc_thickness_nm", "silicon_light_trapping",
                         "rsh_ohm_cm2", "thermal_resistance_k_cm2_w")


def _serialisable(obj):
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialisable(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
def section_benchmark(n_small: int = 3) -> dict:
    """Reference vs fast solver: wall clock, throughput, memory, accuracy."""
    import tracemalloc
    ps = ParamSet.defaults()
    clear_caches()
    names = ("perovskite_eg_ev", "perovskite_thickness_nm", "arc_thickness_nm",
             "silicon_light_trapping")
    X = lhs_matrix(names, n_small, seed=11)
    base = ParamSet.defaults()

    def run(solver: str, thermal: str) -> dict:
        tracemalloc.start()
        t0 = time.perf_counter()
        out = []
        for row in X:
            p = base.with_mapping({k: float(v) for k, v in zip(names, row)})
            out.append(evaluate_tandem(p, solver=solver, thermal_model=thermal))
        wall = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"wall_clock_s": wall, "solves_per_second": n_small / wall,
                "peak_python_alloc_mb": peak / 1e6,
                "results": [(r.pce_pct, r.jsc_ma_cm2, r.voc_v, r.ff) for r in out]}

    ref = run("reference", "energy_balance")
    fast = run("fast", "energy_balance")
    # single-solve timings (cold cache, one optical solve each)
    def single(solver: str) -> float:
        clear_caches()
        t0 = time.perf_counter()
        evaluate_tandem(ps, solver=solver, thermal_model="energy_balance")
        return time.perf_counter() - t0
    ref_single, fast_single = single("reference"), single("fast")

    dev = {"pce": 0.0, "jsc": 0.0, "voc": 0.0, "ff": 0.0}
    keys = ("pce", "jsc", "voc", "ff")
    for a, b in zip(ref["results"], fast["results"]):
        for k, x, y in zip(keys, a, b):
            dev[k] = max(dev[k], abs(x - y))
    # batch API throughput (fast path only: the reference is too slow to batch)
    Xb = lhs_matrix(DEFAULT_MATRIX_PARAMS, 24, seed=12)
    recs, summ = batch_evaluate(Xb, DEFAULT_MATRIX_PARAMS, level="L4",
                                campaign_id="benchmark")
    ds = dataset(recs, DEFAULT_MATRIX_PARAMS, Xb)
    return {
        "reference": {k: v for k, v in ref.items() if k != "results"},
        "fast": {k: v for k, v in fast.items() if k != "results"},
        "single_solve_s": {"reference": ref_single, "fast": fast_single},
        "speedup_single": ref_single / fast_single,
        "speedup_batch": ref["wall_clock_s"] / fast["wall_clock_s"],
        "batch_api": {"n": summ.n_requested, "valid": summ.n_valid,
                      "wall_clock_s": summ.wall_clock_s,
                      "solves_per_second": summ.solves_per_second,
                      "warm_started": summ.warm_started,
                      "dataset_rows": ds["n_rows"]},
        "max_abs_deviation": dev,
        "tolerances": {"pce_pp": 1e-3, "jsc_ma_cm2": 1e-3, "voc_v": 1e-4, "ff": 1e-4},
        "within_tolerance": bool(dev["pce"] < 1e-3 and dev["jsc"] < 1e-3
                                 and dev["voc"] < 1e-4 and dev["ff"] < 1e-4),
        "reference_note": "reference = scalar bisection per bias point (V1.9-B, "
                          "kept as the regression oracle)",
        "configuration": {"n_small": n_small, "curve_points_reference": 1200,
                          "thermal_model": "energy_balance",
                          "note": "wall-clock timings are machine-specific (2 vCPU "
                                  "sandbox); the speedup ratio is the reproducible "
                                  "quantity, and the deviations are the physics check"},
    }


def section_oracle_agreement(n_points: int = 12, seed: int = 11) -> dict:
    """Item 6: reference-vs-fast agreement over a RANDOM-VALID ensemble.

    Deterministic (no wall clock inside the section): the same 12 LHS points,
    the same seeds, the same reference curve grid and the same fast solver on
    every machine. This is the pinned replacement for the ad-hoc 12-point
    measurement quoted in the report.
    """
    names = ("perovskite_eg_ev", "perovskite_thickness_nm", "arc_thickness_nm",
             "silicon_light_trapping")
    X = lhs_matrix(names, n_points, seed=seed)
    base = ParamSet.defaults()
    dev = {"pce": 0.0, "jsc": 0.0, "voc": 0.0, "ff": 0.0}
    keys = ("pce", "jsc", "voc", "ff")
    rows = []
    n_agree = 0
    for i, row in enumerate(X):
        p = base.with_mapping({k: float(v) for k, v in zip(names, row)})
        r = evaluate_tandem(p, solver="reference", thermal_model="energy_balance")
        f = evaluate_tandem(p, solver="fast", thermal_model="energy_balance")
        a, b = (r.pce_pct, r.jsc_ma_cm2, r.voc_v, r.ff), (f.pce_pct, f.jsc_ma_cm2, f.voc_v, f.ff)
        d = {k: abs(x - y) for k, x, y in zip(keys, a, b)}
        ok = (d["pce"] < 1e-3 and d["jsc"] < 1e-3 and d["voc"] < 1e-4 and d["ff"] < 1e-4)
        n_agree += int(ok)
        for k in keys:
            dev[k] = max(dev[k], d[k])
        rows.append({"i": i, "parameter_point": {k: float(v) for k, v in zip(names, row)},
                     "reference": a, "fast": b, "abs_deviation": d, "within_tolerance": ok})
        print(f"[oracle] {i+1}/{n_points} ok={ok}", flush=True)
    return {
        "n_points": n_points, "seed": seed, "parameters": list(names),
        "thermal_model": "energy_balance",
        "max_abs_deviation": dev,
        "n_within_tolerance": n_agree,
        "tolerances": {"pce_pp": 1e-3, "jsc_ma_cm2": 1e-3, "voc_v": 1e-4, "ff": 1e-4},
        "rows": rows,
    }


def section_divergence(n_points: int = 12) -> dict:
    return divergence_study(n_points=n_points)


def section_coupling() -> dict:
    """Top<->bottom luminescent coupling: availability factor and ablation."""
    ps = ParamSet.defaults()
    base = evaluate_level("L4", ps)
    rows = []
    # physical availability of the bottom -> top channel
    from apmt.materials.silicon import varshni_bandgap
    from apmt.materials.perovskite import perovskite_bandgap_temperature
    T = base.temperature_k
    eg_bot = varshni_bandgap(ps["silicon_eg_ev"], T)
    eg_top = perovskite_bandgap_temperature(ps["perovskite_eg_ev"], T, 298.15,
                                           ps["eg_temperature_coeff_ev_k"])
    f_up = emission_fraction_above_gap(eg_bot, eg_top, T)
    for beta_tb in (0.0, 0.05, 0.2, 0.5):
        for beta_bt in (0.0, 0.5):
            p = ps.with_mapping({"luminescent_coupling_top_to_bottom": beta_tb,
                                 "luminescent_coupling_bottom_to_top": beta_bt})
            r = evaluate_level("L4", p)
            rows.append({"beta_tb": beta_tb, "beta_bt": beta_bt,
                         "pce_pct": r.pce_pct, "jsc": r.jsc_ma_cm2,
                         "voc_v": r.voc_v, "ff": r.ff,
                         "j_top_sc": r.j_top_sc, "j_bottom_sc": r.j_bottom_sc,
                         "delta_pce_vs_off_pp": r.pce_pct - base.pce_pct})
    return {
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
        "availability": {
            "bottom_to_top_emission_fraction": f_up,
            "eg_bottom_ev": eg_bot, "eg_top_ev": eg_top, "temperature_k": T,
            "interpretation": "fraction of the silicon cell's radiative emission "
                              "lying above the perovskite bandgap; the channel is "
                              "activated by luminescent_coupling_bottom_to_top "
                              "multiplied by this factor",
        },
        "sweep": rows,
        "conclusion": "TOP-LIMITED DEVICE: adding current to the bottom cell (or "
                      "re-absorbing its emission in the top cell) cannot relieve "
                      "min(Jsc) when the top cell is the limiting one.",
    }


def section_limits() -> dict:
    """Physical limiting cases; qualitative expectations are asserted in tests."""
    ps = ParamSet.defaults()
    cases = {}

    def add(name, mapping=None, expectation="", **kwargs):
        p = ps.with_mapping(mapping) if mapping else ps
        r = evaluate_level(kwargs.pop("level", "L4"), p)
        rec = {"expectation": expectation, "pce_pct": r.pce_pct, "jsc": r.jsc_ma_cm2,
               "voc_v": r.voc_v, "ff": r.ff,
               "junction_k": r.detail["thermal"]["junction_k"]}
        rec.update(kwargs)
        cases[name] = rec

    add("perfect_arc_rear", {"rear_reflectance": 0.98, "arc_thickness_nm": 140.0},
        "rear reflector + tuned ARC must increase bottom-cell Jsc")
    add("weak_top_absorption", {"perovskite_absorption_alpha_ev": 1.0e4},
        "the registered lower absorption limit must reduce the top-cell current")
    add("thin_top_cell", {"perovskite_thickness_nm": 150.0},
        "a thin top cell trades top-cell current for bottom-cell current")
    add("strong_parasitic", {"tco_uv_absorption_k": 2.0, "tco_free_carrier_k": 0.2},
        "parasitic absorption must remove photons from the useful budget")
    cases["zero_recombination"] = {
        "expectation": "switching the SRH/surface channel off (include_srh=False, "
                       "the L1 ideal-single-diode limit) must raise Voc",
        "srh_disabled_pce": evaluate_level("L1", ps).pce_pct,
        "srh_disabled_voc_v": evaluate_level("L1", ps).voc_v,
        "srh_enabled_pce": evaluate_level("L3", ps).pce_pct,
        "srh_enabled_voc_v": evaluate_level("L3", ps).voc_v}
    add("tiny_shunt", {"rsh_ohm_cm2": 50.0}, "a 50 ohm cm2 shunt must destroy FF")
    add("no_thermal_resistance", {"thermal_resistance_k_cm2_w": 0.05},
        "near-zero thermal resistance must approach the fixed-T efficiency")
    add("extreme_thermal_resistance", {"thermal_resistance_k_cm2_w": 2.0},
        "the 454 K corner: reported, not clipped")
    add("ideal_rear_trapping", {"silicon_light_trapping": 30.0},
        "the full light-trapping limit must not exceed detailed balance")
    return {"label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY", "cases": cases}


def section_convergence() -> dict:
    """Solver-resolution convergence: does the answer move with resolution?"""
    from apmt.device.tandem import build_tandem, solve_tandem_fast, optics_for, _with_bandgap_flags
    from apmt.optics.stack import TANDEM_WAVELENGTH_NM
    ps = ParamSet.defaults()
    table = []
    dev = build_tandem(ps, "IQE-M1", 298.15)
    for n_table, n_curve in ((1001, 200), (2001, 400), (4001, 1200), (8001, 2400), (16001, 4800)):
        t0 = time.perf_counter()
        r = solve_tandem_fast(dev, 298.15, n_table=n_table, n_curve_points=n_curve)
        table.append({"n_table": n_table, "n_curve_points": n_curve,
                      "pce_pct": r.pce_pct, "jsc": r.jsc_ma_cm2, "voc_v": r.voc_v,
                      "ff": r.ff, "wall_clock_s": time.perf_counter() - t0})
    ref = table[-1]
    for row in table:
        row["delta_pce_vs_finest_pp"] = row["pce_pct"] - ref["pce_pct"]
        row["delta_voc_vs_finest_mv"] = (row["voc_v"] - ref["voc_v"]) * 1000

    # wavelength-grid convergence of the optics
    wl_table = []
    from apmt.optics.stack import solve_tandem_optics
    for step in (20.0, 10.0, 5.0, 2.5):
        grid = np.arange(300.0, 1250.0 + 1e-9, step)
        orig = TANDEM_WAVELENGTH_NM
        import apmt.optics.stack as st
        st.TANDEM_WAVELENGTH_NM = grid
        try:
            r = solve_tandem_optics(ps)
            wl_table.append({"step_nm": step, "n_points": int(grid.size),
                             "jsc_top": r.jsc_top_ma_cm2(),
                             "jsc_bottom": r.jsc_bottom_ma_cm2(),
                             "closure": r.optics.max_closure_error()})
        finally:
            st.TANDEM_WAVELENGTH_NM = orig
    for row in wl_table:
        row["delta_jsc_top_vs_finest"] = row["jsc_top"] - wl_table[-1]["jsc_top"]
        row["delta_jsc_bottom_vs_finest"] = row["jsc_bottom"] - wl_table[-1]["jsc_bottom"]
    return {
        "subcell_table_and_curve": table,
        "wavelength_grid": wl_table,
        "standard_grid_nm": 5.0,
        "note": "the production settings (n_table 4001, 1200 curve points, 5 nm) "
                "are validated against the finest settings listed here",
    }


MODEL_FORM_INACTIVE = {
    # Under model_form="IQE-M1" the collection efficiency is a single constant per
    # subcell, so the collection-length parameters play no role. The IQE-M2 model
    # form exists precisely to make them active; a dedicated test proves that they
    # are not dead code (tools/v19_engine_campaign.py cannot see this because it
    # runs IQE-M1 everywhere).
    "collection_length_top_nm", "collection_length_bottom_nm",
    # Doping and the SRH lifetimes enter the J0 budget only through the slab SRH
    # model, which is bypassed when the twin uses the calibrated J0_SRH override
    # (IQE-M1 default). tests/test_v19_invariants.py asserts their activity in the
    # slab route.
    "perovskite_doping_cm3", "silicon_doping_cm3",
    "perovskite_srh_lifetime_ns", "perovskite_srv_cm_s",
    "silicon_bulk_lifetime_ms", "silicon_srv_cm_s",
}


def _expected_inert(level: str, model_form: str) -> set:
    """Parameters that cannot have any effect by construction at this level."""
    opts = options_for(level)
    s: set = set()
    if not opts.include_srh:
        s |= {"perovskite_srh_lifetime_ns", "perovskite_srv_cm_s",
              "silicon_bulk_lifetime_ms", "silicon_srv_cm_s",
              "perovskite_doping_cm3", "silicon_doping_cm3",
              "ideality_top", "ideality_bottom"}
    if not opts.include_resistance:
        s |= {"rs_ohm_cm2", "rsh_ohm_cm2", "interconnect_resistance_ohm_cm2"}
    if not opts.include_coupling:
        s |= {"luminescent_coupling_top_to_bottom",
              "luminescent_coupling_bottom_to_top",
              "photon_recycling_gain_top"}
    if not opts.include_thermal:
        # a fixed-temperature solve cannot respond to any thermal parameter
        s |= {"thermal_resistance_k_cm2_w", "thermal_management_gain",
              "absorption_heat_fraction", "thermal_emissivity",
              "eg_temperature_coeff_ev_k"}
    if opts.optics_engine == "beer_lambert":
        # L0 is a per-layer Beer-Lambert absorption budget: no coherent optics,
        # no rear reflection, no parasitic-layer extinction coefficients, no
        # TCO free-carrier absorption.
        s |= {"arc_thickness_nm", "parasitic_layer_thickness_nm",
              "tco_free_carrier_k", "tco_uv_absorption_k", "rear_reflectance",
              "perovskite_oscillator_ev", "interface_loss_top_ma_cm2",
              "perovskite_urbach_mev"}
    if model_form == "IQE-M1":
        s |= MODEL_FORM_INACTIVE
    return s


def _suppression_probe(name: str, level: str, ps: ParamSet, base_pce: float) -> dict:
    """For a parameter that is inert at the nominal point, test whether the
    *physics* suppresses it or whether it is dead code.

    The probe moves the parameter to its registered maximum AND moves the
    parameter that controls the mechanism's availability to the corner of its
    registered range where the mechanism is strongest. If the response is still
    below the inertness threshold, the mechanism is physically suppressed inside
    the registered parameter box -- and a separate unit test then asserts the
    code path itself is live by forcing the availability factor.
    """
    spec_ = next(s for s in all_specs() if s.name == name)
    probe = {name: float(spec_.high)}
    availability = None
    if name == "luminescent_coupling_bottom_to_top":
        # the availability of the channel is controlled by the bandgap pair, so
        # the corner probe must move BOTH the coupling strength and the gap, and
        # compare the corner WITH and WITHOUT the coupling (otherwise the bandgap
        # shift alone dominates the delta and the probe proves nothing).
        eg_spec = next(s for s in all_specs() if s.name == "perovskite_eg_ev")
        probe = {"perovskite_eg_ev": float(eg_spec.low),
                 name: float(spec_.high)}
        off = dict(probe, **{name: 0.0})
        r_off = evaluate_level(level, ps.with_mapping(off))
        r_on = evaluate_level(level, ps.with_mapping(probe))
        T = r_on.temperature_k
        from apmt.device.tandem import emission_fraction_above_gap
        from apmt.materials.silicon import varshni_bandgap
        from apmt.materials.perovskite import perovskite_bandgap_temperature
        eg_bot = varshni_bandgap(float(ps["silicon_eg_ev"]), T)
        eg_top = perovskite_bandgap_temperature(probe["perovskite_eg_ev"], T, 298.15,
                                               float(ps["eg_temperature_coeff_ev_k"]))
        availability = emission_fraction_above_gap(eg_bot, eg_top, T)
        delta = abs(r_on.pce_pct - r_off.pce_pct)
    else:
        r_on, r_off, delta = evaluate_level(level, ps.with_mapping(probe)), None, None
        delta = abs(r_on.pce_pct - base_pce)
    return {"probe": probe, "delta_pce_pp": delta,
            "availability_factor": availability,
            "pce_pct": r_on.pce_pct, "voc_v": r_on.voc_v,
            "pce_off_pct": (r_off.pce_pct if r_off is not None else base_pce),
            "classification": ("PHYSICALLY-SUPPRESSED" if delta < 1e-6
                               else "LIVE-AT-RANGE-CORNER")}


def section_inert(levels=("L0", "L1", "L2", "L3", "L4", "L5"),
                  model_form: str = "IQE-M1") -> dict:
    """Inert-parameter screening across every model level (screening 2.0).

    For each level every registered parameter is perturbed (both directions where
    the parameter is non-zero and in-range, otherwise against its registered
    bounds). A parameter whose PCE response is below 1e-6 pp is INERT. Inertness
    is a defect unless the level's fidelity switches or the active model form
    make the parameter structurally inactive -- those are reported as
    ``expected_inert``.
    """
    ps = ParamSet.defaults()
    out = {}
    screenable = [s.name for s in all_specs()
                  if s.name not in ("temperature_k", "irradiance_suns")]
    for lv in levels:
        base = evaluate_level(lv, ps)
        expected = _expected_inert(lv, model_form)
        rows = {}
        for name in screenable:
            spec_ = next(s for s in all_specs() if s.name == name)
            vals = []
            if float(ps[name]) != 0.0:
                for f in (0.8, 1.2):
                    v = float(ps[name]) * f
                    if spec_.in_bounds(v):
                        vals.append(v)
            if not vals:
                for f in (0.25, 1.0):
                    v = f * spec_.high
                    if spec_.in_bounds(v) and v != float(ps[name]):
                        vals.append(v)
            deltas = []
            for v in vals:
                r = evaluate_level(lv, ps.with_mapping({name: float(v)}))
                deltas.append(abs(r.pce_pct - base.pce_pct))
            span = max(deltas) if deltas else 0.0
            rows[name] = {"max_abs_delta_pce_pp": span, "inert": bool(span < 1e-6),
                          "expected_inert_here": name in expected,
                          "n_points": len(vals)}
        suspicious = [n for n, r in rows.items() if r["inert"] and not r["expected_inert_here"]]
        unexpected, suppressed = [], []
        for n in suspicious:
            probe = _suppression_probe(n, lv, ps, base.pce_pct)
            rows[n]["falsification_probe"] = probe
            if probe["classification"] == "PHYSICALLY-SUPPRESSED":
                suppressed.append(n)
            else:
                unexpected.append(n)
            rows[n]["expected_inert_here"] = False
        active = [n for n, r in rows.items() if not r["inert"]]
        out[lv] = {"baseline_pce_pct": base.pce_pct, "model_form": model_form,
                   "n_screened": len(rows),
                   "n_active": len(active),
                   "n_inert": sum(1 for r in rows.values() if r["inert"]),
                   "n_inert_explained": sum(1 for r in rows.values()
                                            if r["inert"] and r["expected_inert_here"]),
                   "inert_by_switch_or_model_form": sorted(
                       n for n, r in rows.items() if r["inert"] and r["expected_inert_here"]),
                   "inert_physically_suppressed": sorted(suppressed),
                   "unexpected_inert": sorted(unexpected),
                   "defect": bool(unexpected),
                   "active_parameters": sorted(active),
                   "parameters": rows}
    return out


def section_batch_levels(n_samples: int = 16) -> dict:
    """Throughput per level through the batch API (V1.9-D readiness)."""
    X = lhs_matrix(DEFAULT_MATRIX_PARAMS, n_samples, seed=21)
    out = {}
    for lv in LEVELS:
        recs, summ = batch_evaluate(X, DEFAULT_MATRIX_PARAMS, level=lv,
                                    campaign_id=f"throughput-{lv.lower()}")
        out[lv] = {"n": summ.n_requested, "valid": summ.n_valid,
                   "wall_clock_s": summ.wall_clock_s,
                   "solves_per_second": summ.solves_per_second,
                   "failures": summ.failure_counts}
    return out


def section_ablation(n_points: int = 5, seed: int = 31) -> dict:
    """Automatic ablation of every APMT mechanism (ON/OFF + combinations).

    Mechanisms are switched through the SAME fidelity switches the levels use, so
    the ablation measures the mechanism and nothing else. A 2^k factorial over the
    four switches gives the interaction terms; the ensemble repeats it over an LHS
    sample so a single lucky parameter point cannot drive the conclusion.
    """
    import itertools
    from apmt.multifidelity.levels import options_for
    names = ("perovskite_eg_ev", "perovskite_thickness_nm", "thermal_resistance_k_cm2_w",
             "silicon_light_trapping")
    X = lhs_matrix(names, n_points, seed=seed)
    base = ParamSet.defaults()
    switches = (("srh", "include_srh"), ("resistance", "include_resistance"),
                ("thermal", "include_thermal"), ("coupling", "include_coupling"))
    rows = []
    for row in X:
        ps = base.with_mapping({k: float(v) for k, v in zip(names, row)})
        cases = {}
        for combo in itertools.product([False, True], repeat=len(switches)):
            r = _evaluate_with_switches(ps, combo, switches)
            cases["".join("1" if c else "0" for c in combo)] = {
                "pce_pct": r.pce_pct, "jsc": r.jsc_ma_cm2, "voc_v": r.voc_v,
                "ff": r.ff, "junction_k": r.detail["thermal"]["junction_k"],
                "j_top_sc": r.j_top_sc, "j_bottom_sc": r.j_bottom_sc}
        full = cases["1111"]
        main = {}
        for i, (label, _) in enumerate(switches):
            off = list("1111")
            off[i] = "0"
            key = "".join(off)
            main[label] = {"delta_pce_off_vs_full_pp": full["pce_pct"] - cases[key]["pce_pct"],
                           "delta_voc_v": full["voc_v"] - cases[key]["voc_v"],
                           "delta_jsc": full["jsc"] - cases[key]["jsc"],
                           "delta_ff": full["ff"] - cases[key]["ff"],
                           "delta_temperature_k": full["junction_k"] - cases[key]["junction_k"]}
        # interactions: second-order residual beyond the two main effects
        inter = {}
        for i, j in itertools.combinations(range(len(switches)), 2):
            k_both = list("1111"); k_both[i] = "0"; k_both[j] = "0"
            k_i = list("1111"); k_i[i] = "0"
            k_j = list("1111"); k_j[j] = "0"
            inter[f"{switches[i][0]}x{switches[j][0]}"] = {
                "interaction_pp": (full["pce_pct"] - cases["".join(k_i)]["pce_pct"]
                                   - cases["".join(k_j)]["pce_pct"]
                                   + cases["".join(k_both)]["pce_pct"])}
        rows.append({"point": {k: float(v) for k, v in zip(names, row)},
                     "full": full, "main_effects": main, "interactions": inter,
                     "cases": cases})
    agg = {}
    for label, _ in switches:
        vals = [r["main_effects"][label]["delta_pce_off_vs_full_pp"] for r in rows]
        agg[label] = {"mean_delta_pce_pp": float(np.mean(vals)),
                      "min": float(np.min(vals)), "max": float(np.max(vals)),
                      "sign_consistent": bool(np.all(np.array(vals) > 0)
                                              or np.all(np.array(vals) < 0))}
    inter_agg = {}
    for name_ in rows[0]["interactions"]:
        vals = [r["interactions"][name_]["interaction_pp"] for r in rows]
        inter_agg[name_] = {"mean_pp": float(np.mean(vals)),
                            "max_abs_pp": float(np.max(np.abs(vals)))}
    return {"label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
            "n_points": n_points, "seed": seed,
            "mechanisms": [s_[0] for s_ in switches],
            "aggregate_main_effects": agg, "aggregate_interactions": inter_agg,
            "rows": rows,
            "note": "each mechanism is switched off by removing the model TERM "
                    "(fidelity switch), never by moving a registered parameter; "
                    "interactions are second-order factorial residuals and are NOT "
                    "causal claims"}


def _evaluate_with_switches(ps, combo, switches):
    """Evaluate with an explicit on/off combination of the four model terms."""
    import dataclasses

    from apmt.multifidelity import levels as lv
    opts = lv.options_for("L4")            # full physics grid/solver settings
    overrides = {name: bool(value) for (_, name), value in zip(switches, combo)}
    opts = dataclasses.replace(opts, **overrides)
    return lv.evaluate_with_options(opts, ps)


SECTIONS = {
    "benchmark": section_benchmark,
    "ablation": section_ablation,
    "divergence": section_divergence,
    "coupling": section_coupling,
    "limits": section_limits,
    "convergence": section_convergence,
    "inert": section_inert,
    "batch_levels": section_batch_levels,
    "oracle_agreement": section_oracle_agreement,
}


def _environment_metadata() -> dict:
    """Reproducibility metadata (V1.9-C requirement 21)."""
    import hashlib
    import platform
    import subprocess

    def _cmd(*args):
        try:
            return subprocess.run(args, capture_output=True, text=True, cwd=HERE,
                                  timeout=10).stdout.strip()
        except Exception:                                        # pragma: no cover
            return ""

    from apmt.params.registry import ParamSet, all_specs
    from apmt.core.numerics import array_sha256
    base = ParamSet.defaults()
    vec = np.array([float(base[s_.name]) for s_ in all_specs()])
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "git_commit": _cmd("git", "rev-parse", "HEAD"),
        "git_dirty": bool(_cmd("git", "status", "--porcelain")),
        "registry_defaults_fingerprint": array_sha256(vec),
        "registry_size": len(all_specs()),
        "topology": "monolithic two-terminal tandem (current-matched), "
                    "perovskite top / silicon bottom",
        "units": {"wavelength_nm": "nm", "thickness_nm": "nm",
                  "temperature_k": "K", "irradiance": "suns (1 sun = 100 mW/cm2)",
                  "power_density": "mW/cm2", "current_density": "mA/cm2",
                  "resistance_area": "ohm*cm2 (thermal: K*cm2/mW)"},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sections", default=",".join(SECTIONS))
    args = ap.parse_args()

    wanted = [s.strip() for s in args.sections.split(",") if s.strip()]
    out = {"label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
           "generated_by": "tools/v19_engine_campaign.py",
           "metadata": _environment_metadata(),
           "n_registry_parameters": len(all_specs())}
    if os.path.exists(OUT):
        # merge: a section run in isolation must not delete sections measured in
        # an earlier, expensive run (the reference-solver benchmark takes minutes)
        try:
            with open(OUT) as f:
                previous = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:      # pragma: no cover
            print(f"WARNING: existing {OUT} unreadable ({exc}); starting fresh")
            previous = {}
        out.update({k: v for k, v in previous.items()
                    if k not in ("label", "generated_by", "n_registry_parameters")
                    and k not in wanted})
    t_start = time.perf_counter()
    for name in wanted:
        if name not in SECTIONS:
            raise SystemExit(f"unknown section {name!r}; available: {list(SECTIONS)}")
        t0 = time.perf_counter()
        out[name] = SECTIONS[name]()
        print(f"[{name}] {time.perf_counter() - t0:.1f} s")
    print(f"total {time.perf_counter() - t_start:.1f} s")

    if args.write:
        # atomic write: a crash mid-serialisation must never leave a truncated
        # artifact behind (this happened once and cost a benchmark re-run)
        # the wall clock is metadata, not physics: keep it out of the physics
        # sections so the artifact stays byte-reproducible where it matters
        if "benchmark" not in wanted and "benchmark" in out:
            out["benchmark"] = dict(out["benchmark"])
        # PHYSICS DIGEST: sha256 over the scientific content of the artifact --
        # every physical number, validity flag and parameter point, with the
        # timing-bearing benchmark/environment blocks and all wall-clock-valued
        # keys removed. Wall-clock values are machine-specific, so they must not
        # enter a pinned digest (see apmt/repro/digest.py for the single rule
        # shared by this generator, tools/ci_checks.py and the test suite).
        from apmt.repro.digest import digest_block
        out["physics_digest"] = digest_block(out)
        payload = json.dumps(_serialisable(out), indent=2, sort_keys=True,
                             allow_nan=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            f.write(payload)
        os.replace(tmp, OUT)
        print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
