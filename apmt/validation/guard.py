"""APMT V1.9-C — the guard layer: every solve carries a machine-readable verdict.

`evaluate_guarded` is the ONLY entry point that campaign code, calibration and
surrogate-training data generation should use. It

1. runs the physics,
2. evaluates the applicable invariants (apmt.validation.invariants),
3. marks the solve INVALID if any HARD invariant fails, and
4. attaches the verdict to the result so no downstream consumer can be unaware
   of it.

Nothing here changes physics; it decides whether a physics result is admissible.
An INVALID solve is never promoted to a dataset row, never fed to an optimiser
as an objective value, and never used as surrogate training data.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from ..params.registry import ParamSet
from .invariants import (
    InvariantBundle,
    InvariantGroup,
    InvariantStatus,
    Severity,
    check_current_continuity,
    check_data_grid,
    check_numerical_finiteness,
    check_radiative_limit_consistency,
    check_ranges,
    check_recombination_channels,
    check_resistance_bounds,
    check_thermal_energy_balance,
    check_thermal_stability,
    check_temperature_envelope,
    record,
)

# Physical ranges for a two-terminal perovskite/silicon tandem. Wide on purpose:
# these are *absurdity* bounds, not performance expectations.
TANDEM_LIMITS = {
    # lower bounds are EXCLUSIVE of exact zeros: a solve reporting identically
    # zero current, fill factor or efficiency is degenerate (it cannot be told
    # apart from a failed solve) and must be INVALID, not merely reported.
    "jsc_ma_cm2": (1e-6, 60.0),
    "voc_v": (1e-6, 4.0),
    "ff": (1e-6, 1.05),
    "pce_pct": (1e-6, 60.0),
    "vmp_v": (1e-6, 4.0),
    "jmp_ma_cm2": (1e-6, 60.0),
    "j_top_sc": (1e-6, 60.0),
    "j_bottom_sc": (1e-6, 60.0),
}


@dataclass(frozen=True)
class SolveRecord:
    """One guarded evaluation: the result, its verdict, and provenance."""

    result: object
    verdict: InvariantBundle
    valid: bool
    runtime_s: float
    level: str
    parameter_values: dict = field(default_factory=dict)
    campaign_id: str = ""
    seed: Optional[int] = None
    solver: str = ""
    error: str = ""

    def metrics(self) -> dict:
        r = self.result
        if r is None:
            return {}
        return {"pce_pct": float(r.pce_pct), "jsc_ma_cm2": float(r.jsc_ma_cm2),
                "voc_v": float(r.voc_v), "ff": float(r.ff),
                "j_top_sc": float(r.j_top_sc), "j_bottom_sc": float(r.j_bottom_sc),
                "temperature_k": float(r.temperature_k)}

    def to_dict(self) -> dict:
        return {"valid": self.valid, "verdict": self.verdict.to_dict(),
                "runtime_s": self.runtime_s, "level": self.level, "solver": self.solver,
                "campaign_id": self.campaign_id, "seed": self.seed,
                "metrics": self.metrics(), "error": self.error}


def radiative_ceiling_pct(j_top_sc: float, j_bottom_sc: float,
                          j0_rad_top: float, j0_rad_bottom: float,
                          temperature_k: float, concentration: float = 1.0) -> float:
    """Upper bound on tandem PCE [%] from the model's own absorbed photon budget.

    Uses the *radiative* open-circuit voltage of each subcell at its absorbed
    current (kT ln(Jph/J0_rad + 1)). A cell that also has SRH recombination and
    a series/shunt network can only be worse, so this is a genuine ceiling for
    the model's own parameterisation and it catches runaway coupling/photon
    recycling terms (which is exactly how the V1.9-B beta-scale bug produced a
    141 % "efficiency").
    """
    kT = 8.617333262e-5 * temperature_k
    j_lim = min(j_top_sc, j_bottom_sc)
    voc_rad = 0.0
    for jph, j0 in ((j_top_sc, j0_rad_top), (j_bottom_sc, j0_rad_bottom)):
        if jph > 0 and j0 > 0:
            voc_rad += kT * float(np.log1p(jph / j0))
    # P_out [mW/cm2] = j_lim [mA/cm2] * voc_rad [V]; the efficiency is that power
    # divided by the incident power density (concentration * 100 mW/cm2 per sun)
    p_in_mw_cm2 = max(float(concentration), 1e-12) * 100.0
    return j_lim * voc_rad / p_in_mw_cm2 * 100.0


def judge_tandem(result, *, level: str = "L4", absorbed_power_mw_cm2: Optional[float] = None,
                 optical_bundle: Optional[InvariantBundle] = None,
                 context: Optional[dict] = None) -> InvariantBundle:
    """Build the full invariant verdict for a solved tandem."""
    records = []
    m = {"pce_pct": result.pce_pct, "jsc_ma_cm2": result.jsc_ma_cm2,
         "voc_v": result.voc_v, "ff": result.ff, "vmp_v": result.vmp_v,
         "jmp_ma_cm2": result.jmp_ma_cm2, "j_top_sc": result.j_top_sc,
         "j_bottom_sc": result.j_bottom_sc,
         "temperature_k": result.temperature_k}
    records += check_numerical_finiteness(m, context)
    # current limits are per-sun: at N suns the currents scale linearly with the
    # incident photon flux (the V1.9-C concentration regression test pins this)
    concentration = float(getattr(result, "detail", {}).get("concentration", 1.0) or 1.0)
    limits = dict(TANDEM_LIMITS)
    for key in ("jsc_ma_cm2", "jmp_ma_cm2", "j_top_sc", "j_bottom_sc"):
        lo, hi = limits[key]
        limits[key] = (lo, hi * max(1.0, concentration))
    records += check_ranges(m, limits, group="electrical")

    # voltage limit: the tandem Voc cannot exceed the sum of the bandgaps
    eg_sum = float(result.detail.get("sum_bandgap_ev", 4.0))
    records.append(record("electrical.voltage_limit", InvariantGroup.ELECTRICAL.value,
                          m["voc_v"] <= eg_sum + 1e-9, measured=m["voc_v"],
                          limit=eg_sum, units="V",
                          message=f"Voc {m['voc_v']:.4f} V <= sum(Eg) {eg_sum:.4f} eV"))
    records.append(record("electrical.vmp_le_voc", InvariantGroup.ELECTRICAL.value,
                          m["vmp_v"] <= m["voc_v"] + 1e-9, measured=m["vmp_v"],
                          limit=m["voc_v"], units="V", message="Vmp must not exceed Voc"))
    records.append(check_current_continuity(m["j_top_sc"], m["j_bottom_sc"],
                                            m["jsc_ma_cm2"]))
    j0t = result.detail.get("j0_top", {})
    j0b = result.detail.get("j0_bottom", {})
    for tag, j0 in (("top", j0t), ("bottom", j0b)):
        if j0:
            records += check_recombination_channels(
                j0["j0_radiative_ma_cm2"], j0["j0_srh_ma_cm2"], j0["j0_total_ma_cm2"])
    records += check_resistance_bounds(result.detail.get("rs_ohm_cm2", 0.0),
                                       result.detail.get("rsh_ohm_cm2", np.inf))
    # radiative-limit consistency (HARD)
    if j0t and j0b:
        ceiling = radiative_ceiling_pct(m["j_top_sc"], m["j_bottom_sc"],
                                        j0t["j0_radiative_ma_cm2"],
                                        j0b["j0_radiative_ma_cm2"],
                                        m["temperature_k"],
                                        concentration=concentration)
        records.append(check_radiative_limit_consistency(m["pce_pct"], ceiling))

    # thermal (HARD balance + stability; SOFT envelope)
    th = result.detail.get("thermal")
    if th and th.get("model") == "energy_balance":
        records.append(record("thermal.equilibrium_converged",
                              InvariantGroup.THERMAL.value, bool(th.get("converged")),
                              measured=th.get("iterations"), units="iterations",
                              message="the thermal equilibrium solve must converge"))
        env = th.get("electrical_envelope") or {}
        n_out = int(env.get("envelope_extrapolations", 0) or 0)
        lowest = env.get("lowest_extrapolated_k")
        env_max = float(env.get("envelope_max_k", 400.0))
        env_min = float(env.get("envelope_min_k", 220.0))
        records.append(record(
            "thermal.electrical_envelope", InvariantGroup.THERMAL.value,
            n_out == 0, measured=lowest, limit=env_max, units="K",
            severity=Severity.SOFT,
            message=(f"{n_out} trial evaluation(s) outside the electrical validity "
                     f"envelope [{env_min}, {env_max}] K" +
                     (f"; lowest such trial {lowest:.1f} K vs converged junction "
                      f"{th.get('junction_k'):.1f} K" if n_out else "") +
                     " (conservative P_elec = 0 substitution for bracketing only)")))
        # HARD: the CONVERGED operating point must lie inside the electrical
        # model's registered validity window, otherwise the reported efficiency is
        # an extrapolation and the point must not be used as data
        tj = float(th.get("junction_k", 0.0))
        records.append(record(
            "thermal.operating_point_inside_electrical_envelope",
            InvariantGroup.THERMAL.value, env_min <= tj <= env_max,
            measured=tj, limit=env_max, units="K",
            message=(f"converged junction temperature {tj:.1f} K must lie inside "
                     f"[{env_min}, {env_max}] K, the registered temperature range "
                     f"of the electrical model")))
        records.append(check_thermal_energy_balance(
            th["heat_load_mw_cm2"],
            th["conduction_loss_mw_cm2"] + th["radiative_loss_mw_cm2"]))
        records.append(check_thermal_stability(
            th["d_loss_dt_mw_cm2_k"] - th["d_heat_dt_mw_cm2_k"]))
        records.append(check_temperature_envelope(th["junction_k"], th["ambient_k"]))
    elif th:
        records.append(record("thermal.energy_balance", InvariantGroup.THERMAL.value,
                              True, applicable=False,
                              message=f"closure {th.get('model')!r} has no energy balance"))
        if th.get("model") == "fixed-temperature":
            # a fixed-temperature solve is a diagnostic; it must SAY so, and the
            # ambient/junction equality it asserts is itself checked
            records.append(record("thermal.fixed_temperature_declared",
                                  InvariantGroup.THERMAL.value,
                                  abs(float(th.get("junction_k", 0.0))
                                      - float(th.get("ambient_k", 0.0))) < 1e-9,
                                  measured=float(th.get("junction_k", 0.0)),
                                  limit=float(th.get("ambient_k", 0.0)),
                                  message="fixed-T diagnostic must hold Tj == T_amb"))
    else:
        records.append(record("thermal.energy_balance", InvariantGroup.THERMAL.value,
                              True, applicable=False, message="no thermal state reported"))

    records.append(record("numerical.solver_convergence", InvariantGroup.NUMERICAL.value,
                          bool(result.coupling_converged),
                          message="coupling/convergence flag from the solver"))
    if optical_bundle is not None:
        records = list(optical_bundle.records) + records
    if context:
        return InvariantBundle(tuple(records), dict(context))
    return InvariantBundle(tuple(records), {"level": level})


def _total_absorptance(result) -> np.ndarray:
    """Total absorptance per wavelength, for either optics-result shape.

    ``TandemOpticsResult.absorption`` is a dict of layer -> array; a generic
    TMM result exposes ``.total_absorption`` (or ``.absorption``) as an array.
    Both are reduced here so the closure invariant means the same thing
    everywhere: R + T + A = 1 over ALL layers of the stack.
    """
    for attr in ("total_absorption",):
        arr = getattr(result, attr, None)
        if arr is not None and not isinstance(arr, dict):
            return np.asarray(arr, dtype=float)
    a = result.absorption
    if isinstance(a, dict):
        return np.sum(np.stack([np.asarray(v, dtype=float) for v in a.values()]), axis=0)
    return np.asarray(a, dtype=float)


def judge_optics(result, *, require_closure: bool = True) -> InvariantBundle:
    """Optical invariants for an OpticsResult-like object."""
    records = list(check_data_grid(result.wavelength_nm))
    total_a = _total_absorptance(result)
    resid = np.asarray(result.reflectance) + np.asarray(result.transmittance) + \
        np.asarray(total_a) - 1.0
    mx = float(np.max(np.abs(resid)))
    records.append(record("optical.closure", InvariantGroup.OPTICAL.value, mx <= 1e-9,
                          measured=mx, tolerance=1e-9,
                          message=f"max|R+T+A-1| = {mx:.3e}"))
    for name, arr in (("reflectance", np.asarray(result.reflectance)),
                      ("transmittance", np.asarray(result.transmittance)),
                      ("absorptance", np.asarray(total_a))):
        a = np.asarray(arr)
        ok = bool(np.all(a >= -1e-12) and np.all(a <= 1.0 + 1e-12))
        records.append(record(f"optical.bounds.{name}", InvariantGroup.OPTICAL.value, ok,
                              measured=float(np.min(a)), limit=0.0,
                              message=f"{name} within [0, 1] (min {np.min(a):.3e}, "
                                      f"max {np.max(a):.3e})"))
    return InvariantBundle(tuple(records), {"n_points": int(np.size(result.wavelength_nm))})


_LEVEL_NAMES = ("L0", "L1", "L2", "L3", "L4", "L5")


def evaluate_guarded(ps: ParamSet, *, level: str = "L4", model_form: str = "IQE-M1",
                     campaign_id: str = "", seed: Optional[int] = None,
                     solver: str = "auto", thermal_model: str = "energy_balance",
                     optical_bundle: Optional[InvariantBundle] = None,
                     raise_on_error: bool = False) -> SolveRecord:
    """Solve the tandem and return result + verdict (never raises by default)."""
    from ..device.tandem import evaluate_tandem
    from ..validation.invariants import InvariantBundle as _B
    t0 = time.perf_counter()
    try:
        # The level is not decoration: a guarded evaluation at level "L2" must run
        # the L2 fidelity switches (no Rs/Rsh network, no thermal feedback, no
        # coupling), otherwise the recorded level would describe a model that was
        # never evaluated. Levels own their solver/thermal configuration, so the
        # explicit solver/thermal_model arguments only apply when no known level
        # is requested.
        if level in _LEVEL_NAMES:
            from ..multifidelity.levels import evaluate_level
            result = evaluate_level(level, ps, model_form=model_form)
        else:
            result = evaluate_tandem(ps, model_form=model_form, solver=solver,
                                     thermal_model=thermal_model)
    except Exception as exc:                                   # noqa: BLE001
        if raise_on_error:
            raise
        # A failed solve must be INVALID in the VERDICT as well, not only in the
        # ``valid`` flag. An empty bundle (the V1.9-C behaviour) reports status
        # PASS, so any consumer that inspected ``record.verdict.valid`` instead of
        # ``record.valid`` would have read an out-of-envelope or crashed solve as
        # a passed one. A HARD failure record makes the two agree by construction.
        from .invariants import record as _record
        bundle = _B((_record("numerical.solve_completed",
                             InvariantGroup.NUMERICAL.value, False,
                             severity=Severity.HARD,
                             message=f"{type(exc).__name__}: {exc}"),))
        return SolveRecord(None, bundle, False, time.perf_counter() - t0, level,
                           campaign_id=campaign_id, seed=seed, solver=solver,
                           error=f"{type(exc).__name__}: {exc}")
    if optical_bundle is None:
        # optical invariants (R+T+A closure, bounded R/T/A, wavelength-grid
        # integrity) must be evaluated on EVERY guarded solve, not only when the
        # caller remembers to pass them. The optics solve is lru-cached, so the
        # tandem solve has already paid for it.
        try:
            from ..device.tandem import optics_for
            optical_bundle = judge_optics(optics_for(ps, model_form=model_form))
        except Exception as exc:                               # noqa: BLE001
            optical_bundle = _B((record("optical.available", InvariantGroup.OPTICAL.value,
                                        False, severity=Severity.HARD,
                                        message=f"optics could not be evaluated: "
                                                f"{type(exc).__name__}: {exc}"),))
    verdict = judge_tandem(result, level=level, optical_bundle=optical_bundle,
                           context={"level": level, "model_form": model_form,
                                    "solver": solver, "thermal_model": thermal_model})
    rt = time.perf_counter() - t0
    valid = verdict.valid
    result.detail["invariants"] = verdict.to_dict()
    result.detail["solve_valid"] = bool(valid)
    try:
        point = ps.to_dict()
    except Exception:                                      # pragma: no cover
        point = {k: float(ps[k]) for k in ps.names()} if hasattr(ps, "names") else {}
    return SolveRecord(result, verdict, valid, rt, level, parameter_values=point,
                       campaign_id=campaign_id, seed=seed, solver=solver)
