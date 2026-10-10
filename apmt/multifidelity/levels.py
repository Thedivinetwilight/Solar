"""APMT V1.9-C — multi-fidelity model levels (0-5) with divergence analysis.

Six levels, each differing from the previous one by a *named, implemented*
physical or numerical mechanism. Nothing is invented to fill a slot: every
switch maps to code that already exists, and every level is validated by the
same invariant engine.

    L0  analytic          Beer-Lambert optics (no ARC, no interference),
                          radiative-only recombination, no series/shunt network,
                          no thermal feedback, no coupling.
    L1  tmm-ideal         full coherent TMM + incoherent wafer optics,
                          radiative-only recombination (ideal single diode).
    L2  two-diode         + SRH/surface recombination channel (J0_srh).
    L3  thermal           + self-heating energy balance and T-dependent bandgaps.
    L4  full              + series/shunt resistance network and all luminescent
                          coupling / photon-recycling mechanisms (the default
                          configuration of evaluate_tandem).
    L5  refined           L4 with finer subcell tables and a denser bias curve
                          (solver-grid-only refinement; the wavelength grid is
                          unchanged -- V1.9-H doc fix, the old text claimed a
                          finer wavelength grid that no code path implements).

Use :func:`evaluate_level` for a single point and :func:`divergence_study` for a
level-to-level comparison over a parameter ensemble. Divergence classes are
defined against the *highest* level in the study so the classification is
relative to the best available physics, never to the cheapest.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

import numpy as np

from ..core.numerics import make_rng
from ..device.tandem import TandemResult, evaluate_tandem
from ..params.registry import ParamSet, spec

LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")

LEVEL_DESCRIPTIONS = {
    "L0": "analytic: Beer-Lambert optics, radiative-only diode, no Rs/Rsh, no "
          "thermal feedback, no coupling",
    "L1": "tmm-ideal: coherent TMM + incoherent wafer, radiative-only diode",
    "L2": "two-diode: + SRH/surface recombination channel",
    "L3": "thermal: + self-heating energy balance and T-dependent bandgaps",
    "L4": "full: + series/shunt resistance and luminescent coupling / photon "
          "recycling mechanisms",
    "L5": "refined: L4 with finer subcell tables and denser bias curve "
          "(solver-grid-only numerical cross-check; wavelength grid unchanged)",
}


@dataclass(frozen=True)
class LevelOptions:
    """Explicit fidelity switches for one level (recorded with every result)."""

    level: str
    optics_engine: str = "tmm"          # tmm | beer_lambert
    include_srh: bool = True
    include_resistance: bool = True
    include_thermal: bool = True
    include_coupling: bool = True
    # None -> the standard 5 nm grid. V1.9-H audit: currently UNWIRED (no
    # optics path reads this field); L5 refines solver grids only, see above.
    n_wavelength: Optional[int] = None
    n_table: int = 4001
    n_curve_points: int = 1200
    solver: str = "auto"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def options_for(level: str) -> LevelOptions:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    if level == "L0":
        return LevelOptions(level, optics_engine="beer_lambert", include_srh=False,
                            include_resistance=False, include_thermal=False,
                            include_coupling=False, n_table=2001,
                            n_curve_points=600)
    if level == "L1":
        return LevelOptions(level, include_srh=False, include_resistance=False,
                            include_thermal=False, include_coupling=False,
                            n_table=2001, n_curve_points=600)
    if level == "L2":
        return LevelOptions(level, include_resistance=False, include_thermal=False,
                            include_coupling=False)
    if level == "L3":
        return LevelOptions(level, include_resistance=False)
    if level == "L4":
        return LevelOptions(level)
    return LevelOptions(level, n_table=8001, n_curve_points=2400, solver="fast")


def level_switch_note(opts: LevelOptions) -> dict:
    """Record what a level switches off (it never changes a parameter value)."""
    return {"srh_channel": opts.include_srh, "resistance_network": opts.include_resistance,
            "thermal_feedback": opts.include_thermal, "coupling_mechanisms": opts.include_coupling,
            "optics_engine": opts.optics_engine,
            "note": "fidelity switches disable model terms; registered parameter "
                    "values are never moved outside their declared ranges"}


def apply_level(ps: ParamSet, opts: LevelOptions) -> ParamSet:
    """Levels do not mutate the parameter set (kept for API clarity).

    Fidelity is carried by explicit switches in :func:`evaluate_level`; the
    parameter set is passed through untouched so that every level uses the same
    physical parameters and only the *model terms* differ.
    """
    del opts
    return ps


def evaluate_level(level: str, ps: ParamSet, *, model_form: str = "IQE-M1",
                   quantify: bool = True,
                   initial_temperature_k: float | None = None) -> TandemResult:
    """Evaluate one parameter point at one fidelity level."""
    return evaluate_with_options(options_for(level), ps, model_form=model_form,
                                 quantify=quantify,
                                 initial_temperature_k=initial_temperature_k)


def evaluate_with_options(opts: LevelOptions, ps: ParamSet, *,
                          model_form: str = "IQE-M1",
                          quantify: bool = True,
                          initial_temperature_k: float | None = None) -> TandemResult:
    """Evaluate one point with an explicit :class:`LevelOptions` configuration.

    This is the entry point used by the ablation study, which needs arbitrary
    ON/OFF combinations of the four mechanisms (2^4 = 16 configurations) that do
    not correspond to any named level. The fidelity switches only ever remove or
    restore a model TERM; they never move a registered parameter value.

    ``initial_temperature_k`` is a SOLVER hint only (warm start for the thermal
    fixed point). It never changes the equations, and the returned thermal state
    is the converged equilibrium, not the hint.
    """
    from ..device.tandem import build_tandem, optics_for, solve_tandem_fast, \
        solve_tandem_reference, _with_bandgap_flags, _thermal_as_dict
    from ..device.thermal import SUN_POWER_MW_CM2, solve_equilibrium

    level = opts.level
    ps_l = apply_level(ps, opts)
    T_amb = float(ps_l["temperature_k"])
    switches = level_switch_note(opts)

    if opts.optics_engine == "beer_lambert":
        from ..optics.stack import solve_beer_lambert_optics
        opt = solve_beer_lambert_optics(ps_l)
    else:
        opt = optics_for(ps_l, model_form=model_form)

    def solve_at(T: float) -> TandemResult:
        dev = build_tandem(ps_l, model_form, T, None, opt,
                           include_srh=opts.include_srh,
                           include_resistance=opts.include_resistance,
                           include_coupling=opts.include_coupling)
        dev = _with_bandgap_flags(dev, ps_l, T)
        fn = solve_tandem_fast if opts.solver in ("auto", "fast") else solve_tandem_reference
        return fn(dev, T, n_table=opts.n_table, n_curve_points=opts.n_curve_points)

    if opts.include_thermal:
        from ..device.tandem import ElectricalPowerExtractor, spectrum_for
        # V1.9-H: pass the level's (possibly shifted) spectrum, as
        # evaluate_tandem does; the old default-spectrum call silently ignored
        # spectrum_shift_nm (identical at shift = 0).
        absorbed = (opt.absorbed_power_mw_cm2(spectrum_for(ps_l))
                    * float(ps_l["irradiance_suns"]))
        extractor = ElectricalPowerExtractor(solve_at, float(ps_l["irradiance_suns"]),
                                             SUN_POWER_MW_CM2)
        from ..device.thermal import assert_inside_electrical_envelope
        st = solve_equilibrium(ps_l, absorbed, extractor, T_amb,
                               initial_temperature_k=initial_temperature_k)
        assert_inside_electrical_envelope(
            st.junction_k,
            context=f"level {level}, {ps_l['irradiance_suns']:g} sun")
        res = solve_at(st.junction_k)
        thermal = _thermal_as_dict(st)
        thermal["absorbed_power_mw_cm2"] = absorbed
        thermal["electrical_envelope"] = dict(extractor.stats)
    else:
        res = solve_at(T_amb)
        thermal = {"model": "fixed-temperature", "ambient_k": T_amb,
                   "junction_k": T_amb, "delta_t_k": 0.0,
                   "closure_note": f"{level}: thermal feedback disabled by fidelity",
                   "category": "MODEL-ASSUMED-CLOSURE"}

    detail = dict(res.detail)
    detail["thermal"] = thermal
    detail["level"] = level
    detail["level_options"] = opts.to_dict()
    detail["level_description"] = LEVEL_DESCRIPTIONS[level]
    detail["level_switches"] = switches
    return TandemResult(**{**res.__dict__, "detail": detail})


# ---------------------------------------------------------------------------
# divergence analysis
# ---------------------------------------------------------------------------
DIVERGENCE_CLASSES = ("LOW-DIVERGENCE", "MODERATE-DIVERGENCE", "HIGH-DIVERGENCE",
                      "MODEL-FORM-CRITICAL")

# Thresholds are on |dPCE| in percentage points *relative to the highest level
# in the study*, plus a Jsc criterion (current matching is the quantity most
# sensitive to the optical model).
DIVERGENCE_THRESHOLDS_PP = (0.20, 0.60, 1.50)      # inclusive upper bounds
DIVERGENCE_THRESHOLDS_JSC = (0.20, 0.60, 1.50)


def classify_divergence(delta_pce_pp: float, delta_jsc: float) -> str:
    """Classify one level-to-level deviation (magnitudes, not signed)."""
    a, b = abs(delta_pce_pp), abs(delta_jsc)
    worst = max(a, b)
    if worst <= DIVERGENCE_THRESHOLDS_PP[0]:
        return "LOW-DIVERGENCE"
    if worst <= DIVERGENCE_THRESHOLDS_PP[1]:
        return "MODERATE-DIVERGENCE"
    if worst <= DIVERGENCE_THRESHOLDS_PP[2]:
        return "HIGH-DIVERGENCE"
    return "MODEL-FORM-CRITICAL"


def divergence_study(levels: Sequence[str] = LEVELS, n_points: int = 12,
                     seed: int = 20261004,
                     parameters: Sequence[str] = (
                         "perovskite_eg_ev", "perovskite_thickness_nm",
                         "arc_thickness_nm", "silicon_light_trapping",
                         "rsh_ohm_cm2", "thermal_resistance_k_cm2_w"),
                     reference_level: str = "L5",
                     model_form: str = "IQE-M1") -> dict:
    """Compare all levels on common parameter points and classify divergence."""
    from ..sensitivity.lhs import lhs_matrix

    base = ParamSet.defaults()
    X = lhs_matrix(parameters, n_points, seed)
    rows = []
    for i in range(n_points):
        ps = base.with_mapping({n: float(v) for n, v in zip(parameters, X[i])})
        evals = {lv: evaluate_level(lv, ps, model_form=model_form) for lv in levels}
        ref = evals[reference_level]
        row = {"point": i, "parameters": {n: float(v) for n, v in zip(parameters, X[i])},
               "levels": {}}
        for lv in levels:
            r = evals[lv]
            row["levels"][lv] = {
                "pce_pct": float(r.pce_pct), "jsc_ma_cm2": float(r.jsc_ma_cm2),
                "voc_v": float(r.voc_v), "ff": float(r.ff),
                "junction_k": float(r.detail["thermal"]["junction_k"]),
                "delta_pce_pp_vs_reference": float(r.pce_pct - ref.pce_pct),
                "delta_jsc_vs_reference": float(r.jsc_ma_cm2 - ref.jsc_ma_cm2),
                "divergence": classify_divergence(r.pce_pct - ref.pce_pct,
                                                  r.jsc_ma_cm2 - ref.jsc_ma_cm2),
            }
        rows.append(row)

    summary = {}
    for lv in levels:
        d_pce = np.array([abs(r["levels"][lv]["delta_pce_pp_vs_reference"]) for r in rows])
        d_jsc = np.array([abs(r["levels"][lv]["delta_jsc_vs_reference"]) for r in rows])
        classes = [r["levels"][lv]["divergence"] for r in rows]
        summary[lv] = {
            "mean_abs_delta_pce_pp": float(d_pce.mean()),
            "max_abs_delta_pce_pp": float(d_pce.max()),
            "mean_abs_delta_jsc": float(d_jsc.mean()),
            "max_abs_delta_jsc": float(d_jsc.max()),
            "class_counts": {c: classes.count(c) for c in DIVERGENCE_CLASSES},
            "worst_class": max(classes, key=lambda c: DIVERGENCE_CLASSES.index(c)),
            "predictive": classes.count("LOW-DIVERGENCE") == len(rows),
        }
    return {"label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
            "reference_level": reference_level,
            "levels": list(levels), "n_points": n_points, "seed": seed,
            "parameters": list(parameters),
            "thresholds_pp": list(DIVERGENCE_THRESHOLDS_PP),
            "summary": summary, "rows": rows,
            "model_form": model_form}
