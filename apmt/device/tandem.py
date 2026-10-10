"""APMT V1.9-C — two-terminal series-constrained tandem device model.

Two solvers, one physics
------------------------
``solve_tandem_reference``  the transparent V1.9-B implementation: for every
                            bias point it inverts each subcell's implicit J-V by
                            scalar bisection (~0.8 s per solve). Kept forever as
                            the regression oracle.
``solve_tandem_fast``       the V1.9-C production path: each subcell's J(V) curve
                            is tabulated once with a vectorised Newton solve, the
                            table is inverted by interpolation, and the whole
                            tandem J-V curve is assembled with NumPy. Numerically
                            equivalent to the reference within a documented and
                            tested tolerance
                            (tests/test_v19_engine.py: the reference-vs-fast agreement contract).

Physics (identical in both)
---------------------------
A two-terminal tandem forces a common current. Parametrising on the internal
series current J:

    V_top(J)     = V_top^{-1}(J - dJ_bt(J))          (bottom->top coupling)
    V_bottom(J)  = V_bottom^{-1}(J - dJ_tb(J))       (top->bottom coupling)
    V_terminal(J) = V_top(J) + V_bottom(J) - J * Rs / 1000
    J_terminal(J) = J - V_terminal(J) / Rsh * 1000

Coupling currents (units mA/cm^2, sign: added photocurrent in the receiving
cell, so they *reduce* the current the receiving subcell must carry):

    dJ_tb(J) = beta_tb * J0_rad_top     * expm1(V_top(J)   / kT)
    dJ_bt(J) = beta_bt * f_up(Eg) * J0_rad_bottom * expm1(V_bottom(J) / kT)

``f_up`` is the *physically computed* fraction of the bottom cell's radiative
emission that lies above the top cell's bandgap; it is not a free parameter.
Both betas default to 0 (mechanisms OFF) and are registered, ablatable
parameters. The mutual dependence of the two coupling terms is resolved by a
contracted fixed-point iteration with an explicit convergence record.

Photon recycling enters through the top cell's effective radiative J0.
Concentration enters as a spectrally neutral scaling of the incident photon
currents (documented approximation: no spectral shift is applied by
concentration; ``spectrum_shift_nm`` supplies an independent, explicitly
modelled spectral shift).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from ..core.constants import K_B_EV_K
from ..core.numerics import golden_section_max
from ..optics.stack import TandemOpticsResult, solve_tandem_optics
from ..params.registry import ParamSet
from ..spectra.reference import Spectrum, reference
from .recombination import j0_budget
from .subcell import (SubcellModel, SubcellNoVocError, current_at_voltage,
                      open_circuit_voltage, voltage_at_current)


@dataclass(frozen=True)
class TandemResult:
    """Solved two-terminal tandem at a given temperature."""

    temperature_k: float
    jsc_ma_cm2: float
    voc_v: float
    ff: float
    pce_pct: float
    vmp_v: float
    jmp_ma_cm2: float
    v_top_at_mpp: float
    v_bottom_at_mpp: float
    j_top_sc: float
    j_bottom_sc: float
    current_matching_ratio: float
    coupling_converged: bool
    coupling_iterations: int
    model_form: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: (round(v, 6) if isinstance(v, float) else v)
             for k, v in self.__dict__.items() if k != "detail"}
        d["detail"] = self.detail
        return d


@dataclass(frozen=True)
class TandemDevice:
    top: SubcellModel
    bottom: SubcellModel
    rs_ohm_cm2: float
    rsh_ohm_cm2: float
    optics: Optional[TandemOpticsResult] = None
    model_form: str = "L2"
    mechanism_flags: dict = field(default_factory=dict)
    concentration: float = 1.0


# ---------------------------------------------------------------------------
# spectrum handling (cached: the reference spectrum is immutable)
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=16)
def _spectrum_for(shift_nm: float) -> Spectrum:
    sp = reference()
    return sp.shifted(float(shift_nm)) if float(shift_nm) != 0.0 else sp


def spectrum_for(ps: ParamSet) -> Spectrum:
    """Incident spectrum including the registered spectral shift."""
    return _spectrum_for(float(ps["spectrum_shift_nm"]))


@functools.lru_cache(maxsize=32)
def _optics_cached(key: tuple, model_form: str, theta_rad: float,
                   shift_nm: float) -> TandemOpticsResult:
    ps = ParamSet.from_mapping(dict(key))
    return solve_tandem_optics(ps, model_form=model_form, theta_rad=theta_rad,
                               spectrum=_spectrum_for(shift_nm))


_OPTICAL_KEYS = ("arc_thickness_nm", "parasitic_layer_thickness_nm",
                 "tco_free_carrier_k", "tco_uv_absorption_k",
                 "perovskite_thickness_nm", "perovskite_eg_ev",
                 "perovskite_urbach_mev", "perovskite_absorption_alpha_ev",
                 "perovskite_n_inf", "perovskite_oscillator_ev",
                 "silicon_thickness_um", "silicon_light_trapping",
                 "collection_efficiency_top", "collection_efficiency_bottom",
                 "collection_length_top_nm", "collection_length_bottom_nm",
                 "interface_loss_top_ma_cm2", "rear_reflectance")


def optics_for(ps: ParamSet, model_form: str = "IQE-M1", theta_rad: float = 0.0,
               use_cache: bool = True) -> TandemOpticsResult:
    """Solve (or retrieve) the tandem optics.

    The cache key is the full optical parameter tuple, so any change to an
    optical parameter invalidates it; a hit returns the *same immutable* result
    object. This is what makes the thermal fixed point and campaign sweeps that
    only move electrical/thermal parameters cheap.
    """
    if not use_cache:
        return solve_tandem_optics(ps, model_form=model_form, theta_rad=theta_rad,
                                   spectrum=spectrum_for(ps))
    key = tuple((k, float(ps[k])) for k in _OPTICAL_KEYS)
    return _optics_cached(key, model_form, float(theta_rad),
                          float(ps["spectrum_shift_nm"]))


def cache_info() -> dict:
    return {"optics_cache": _optics_cached.cache_info()._asdict(),
            "spectrum_cache": _spectrum_for.cache_info()._asdict()}


def clear_caches() -> None:
    _optics_cached.cache_clear()
    _spectrum_for.cache_clear()


# ---------------------------------------------------------------------------
# bottom -> top radiative coupling fraction (physics, not a free parameter)
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=64)
def emission_fraction_above_gap(eg_emit_ev: float, eg_absorb_ev: float,
                                temperature_k: float, n_points: int = 4000) -> float:
    """Fraction of a cell's radiative emission lying above ``eg_absorb_ev``.

    Detailed-balance emission spectrum (generalised Planck, no voltage
    factor -- the voltage dependence cancels in the ratio):

        Phi(E) dE  ∝  E^2 / (exp(E / kT) - 1) dE ,   E >= Eg_emit

    Returns the fraction of the emitted photon flux whose energy exceeds
    ``eg_absorb_ev``. For a silicon bottom cell (Eg ~1.12 eV) emitting into a
    perovskite with Eg ~1.68 eV this is exp(-dE/kT) suppressed and therefore
    tiny -- quantifying it is the point: it turns "bottom-to-top coupling might
    matter" into an answer.
    """
    kT = K_B_EV_K * float(temperature_k)
    e_hi = max(float(eg_emit_ev) + 20.0 * kT, float(eg_absorb_ev) + 5.0)
    E = np.linspace(float(eg_emit_ev), e_hi, n_points)
    with np.errstate(over="ignore"):
        occ = 1.0 / np.expm1(np.clip(E / kT, 1e-12, 700.0))
    flux = E ** 2 * occ
    total = np.trapezoid(flux, E)
    if total <= 0:
        return 0.0
    above = E > float(eg_absorb_ev)
    if not np.any(above):
        return 0.0
    Ea = np.concatenate([[float(eg_absorb_ev)], E[above]])
    fa = Ea ** 2 / np.expm1(np.clip(Ea / kT, 1e-12, 700.0))
    return float(np.trapezoid(fa, Ea) / total)


# ---------------------------------------------------------------------------
# subcell construction / thermal
# ---------------------------------------------------------------------------
def _subcell_from_params(ps: ParamSet, optics: TandemOpticsResult, temperature_k: float,
                         spectrum: Spectrum, include_srh: bool = True) -> tuple:
    """Build the two subcells, including temperature-dependent bandgaps."""
    from ..materials.perovskite import perovskite_bandgap_temperature
    from ..materials.silicon import varshni_bandgap

    eg_top = perovskite_bandgap_temperature(
        ps["perovskite_eg_ev"], temperature_k, 298.15, ps["eg_temperature_coeff_ev_k"])
    eg_bottom = varshni_bandgap(ps["silicon_eg_ev"], temperature_k)

    conc = float(ps["irradiance_suns"])
    j_top = optics.jsc_top_ma_cm2(spectrum) * conc
    j_bot = optics.jsc_bottom_ma_cm2(spectrum) * conc

    j0_top = j0_budget(eg_top, temperature_k, ps["radiative_efficiency_top"],
                       ps["ideality_top"],
                       thickness_cm=ps["perovskite_thickness_nm"] * 1e-7,
                       lifetime_s=ps["perovskite_srh_lifetime_ns"] * 1e-9,
                       doping_cm3=ps["perovskite_doping_cm3"],
                       srv_cm_s=ps["perovskite_srv_cm_s"])
    j0_bot = j0_budget(eg_bottom, temperature_k, ps["radiative_efficiency_bottom"],
                       ps["ideality_bottom"],
                       thickness_cm=ps["silicon_thickness_um"] * 1e-4,
                       lifetime_s=ps["silicon_bulk_lifetime_ms"] * 1e-3,
                       doping_cm3=ps["silicon_doping_cm3"],
                       srv_cm_s=ps["silicon_srv_cm_s"])

    if not include_srh:
        # ideal-single-diode limit: the SRH/surface channel is removed by
        # construction (a zero, not a huge, recombination current)
        j0_top = j0_budget(eg_top, temperature_k, ps["radiative_efficiency_top"],
                           ps["ideality_top"], j0_srh_override_ma_cm2=0.0)
        j0_bot = j0_budget(eg_bottom, temperature_k, ps["radiative_efficiency_bottom"],
                           ps["ideality_bottom"], j0_srh_override_ma_cm2=0.0)

    top = SubcellModel(
        name="perovskite", jph_ma_cm2=j_top, j0_budget=j0_top,
        ideality_srh=ps["ideality_top"], rs_ohm_cm2=0.0, rsh_ohm_cm2=np.inf,
        photon_recycling_gain=1.0 + ps["photon_recycling_gain_top"],
        luminescent_coupling_in=0.0, radiative_coupling_source=0.0)
    bottom = SubcellModel(
        name="silicon", jph_ma_cm2=j_bot, j0_budget=j0_bot,
        ideality_srh=ps["ideality_bottom"], rs_ohm_cm2=0.0, rsh_ohm_cm2=np.inf,
        photon_recycling_gain=1.0, luminescent_coupling_in=0.0,
        radiative_coupling_source=0.0)
    return top, bottom, eg_top, eg_bottom


def _radiative_recombination_current(model: SubcellModel, voltage_v: float,
                                     temperature_k: float) -> float:
    """Radiative recombination current density [mA/cm2] at a bias."""
    kT = K_B_EV_K * temperature_k
    j0_rad = model.j0_rad_effective()
    with np.errstate(over="ignore"):
        return float(j0_rad * (np.expm1(min(max(voltage_v / kT, -700), 700))))


def build_tandem(ps: ParamSet, model_form: str = "IQE-M1",
                 temperature_k: Optional[float] = None,
                 spectrum: Optional[Spectrum] = None,
                 optics: Optional[TandemOpticsResult] = None,
                 include_srh: bool = True, include_resistance: bool = True,
                 include_coupling: bool = True) -> TandemDevice:
    """Assemble the tandem device from a ParamSet (the digital twin).

    The three fidelity switches exist for the multi-fidelity level architecture
    (apmt.multifidelity.levels). They *switch a model term off*; they never push
    a registered parameter outside its declared range, so the registry keeps
    meaning what it says.
    """
    sp = spectrum or spectrum_for(ps)
    T = float(temperature_k if temperature_k is not None else ps["temperature_k"])
    opt = optics if optics is not None else optics_for(ps, model_form=model_form)
    top, bottom, eg_top, eg_bottom = _subcell_from_params(ps, opt, T, sp,
                                                          include_srh=include_srh)
    f_up = emission_fraction_above_gap(eg_bottom, eg_top, T)
    rs = (ps["rs_ohm_cm2"] + ps["interconnect_resistance_ohm_cm2"]
          if include_resistance else 0.0)
    rsh = ps["rsh_ohm_cm2"] if include_resistance else float("inf")
    flags = {
        "photon_recycling_gain_top": (ps["photon_recycling_gain_top"]
                                      if include_coupling else 0.0),
        "luminescent_coupling_top_to_bottom": (
            ps["luminescent_coupling_top_to_bottom"] if include_coupling else 0.0),
        "luminescent_coupling_bottom_to_top": (
            ps["luminescent_coupling_bottom_to_top"] if include_coupling else 0.0),
        "emission_fraction_above_top_gap": f_up,
        "silicon_light_trapping": ps["silicon_light_trapping"],
        "eg_top": eg_top, "eg_bottom": eg_bottom,
    }
    return TandemDevice(top=top, bottom=bottom, rs_ohm_cm2=rs, rsh_ohm_cm2=rsh,
                        optics=opt, model_form=model_form,
                        concentration=float(ps["irradiance_suns"]),
                        mechanism_flags=flags)


def junction_temperature(ps: ParamSet) -> dict:
    """Legacy V1.9-B 'simple' closure, retained for lineage and comparison."""
    from .thermal import simple_temperature
    st = simple_temperature(ps)
    return {"delta_t_k": st.delta_t_k, "r_th_effective_k_cm2_w": st.r_th_effective_k_cm2_w,
            "heat_flux_mw_cm2": st.heat_load_mw_cm2,
            "closure": st.closure_note, "category": "MODEL-ASSUMED-CLOSURE",
            "model": "simple"}


# ---------------------------------------------------------------------------
# shared curve metrics / result assembly
# ---------------------------------------------------------------------------
def _root(f, lo: float, hi: float, tol: float = 1e-12, max_iter: int = 80) -> float:
    """Bisection on a sign-changing scalar function (used on interpolants).

    Callers MUST pre-check the bracket: if f(lo) and f(hi) share a sign this
    returns the interval midpoint, which is indistinguishable from a genuine
    root at the midpoint. Never use the return value without a bracket check
    (V1.9-H audit: the Jsc conditioning diagnostic did exactly that).
    """
    f_lo, f_hi = f(lo), f(hi)
    if f_lo == 0.0:
        return lo
    if f_hi == 0.0:
        return hi
    if (f_lo > 0) == (f_hi > 0):
        return 0.5 * (lo + hi)          # NO bracket: midpoint, not a root
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if f_mid == 0.0 or (hi - lo) <= tol:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi, f_hi = mid, f_mid
    return 0.5 * (lo + hi)


def curve_metrics_by_current(J: np.ndarray, V_of_J: np.ndarray,
                             rsh_ohm_cm2: float) -> dict:
    """Metrics from a *current-parametrised* curve V(J) (fast path).

    Open-circuit voltage: root of the terminal current
    ``J_term(J) = J - V(J)/Rsh*1000`` (monotone increasing in J because V falls
    with J). Maximum power point: golden-section maximisation of
    ``V(J) * J_term(J)`` on the interval between the Voc current and the
    current-source limit, where the power is positive and unimodal.

    Short-circuit current is NOT taken from this curve: on a series tandem the
    J-V curve is nearly vertical at J = min(Jsc_subcells) (a subcell carries
    almost the same current at any bias between reverse and its Voc), so the
    current at V = 0 is ill-conditioned along that branch. The physical
    short-circuit current is the current-source limit, supplied by the caller;
    the interpolated value is returned here only as a conditioning diagnostic.
    """
    J_grid = np.asarray(J, dtype=float)
    V_grid = np.asarray(V_of_J, dtype=float)
    order = np.argsort(J_grid)
    J_grid, V_grid = J_grid[order], V_grid[order]

    def v_of_j(j: float) -> float:
        return float(np.interp(j, J_grid, V_grid))

    has_shunt = bool(np.isfinite(rsh_ohm_cm2))

    def terminal_current(j: float) -> float:
        return j - (v_of_j(j) / rsh_ohm_cm2 * 1000.0 if has_shunt else 0.0)

    j_hi = float(J_grid[-1])
    if has_shunt:
        t_lo, t_hi = terminal_current(0.0), terminal_current(j_hi)
        if t_lo >= 0.0:
            j_voc = 0.0
        elif t_hi <= 0.0:
            j_voc = j_hi
        else:
            j_voc = _root(terminal_current, 0.0, j_hi, tol=1e-13)
        voc = v_of_j(j_voc)
    else:
        j_voc = 0.0
        voc = v_of_j(0.0)

    def power(j: float) -> float:
        return terminal_current(j) * v_of_j(j)

    lo = max(0.0, j_voc)
    hi = max(j_hi, lo + 1e-9)
    jmp, pmax = golden_section_max(power, lo, hi, tol=1e-12)
    pmax = max(pmax, 0.0)

    # Conditioning diagnostic for the short-circuit definition. On a series
    # tandem the J(V) curve is nearly vertical at the current-source limit, so
    # "the current at V = 0" is only well defined to the extent that a small
    # bias change moves the current little. The quantity below is that slope:
    # mA/cm^2 of current lost per volt of forward bias just above short circuit.
    # It is reported (never used) so the reader can see why Jsc is defined as
    # min(Jsc_top, Jsc_bottom) rather than read off the curve.
    dv_probe = 0.020
    # V1.9-H repair (J-sens): the slope is only defined when V(J) actually
    # crosses the probe bias on this curve. Previously an unbracketed probe
    # silently returned the bisection midpoint, fabricating sens = j_hi/0.04
    # (385.6 at the twin point) with a physical-sounding comment. A mismatched
    # tandem never reaches V = 20 mV (the non-limiting subcell still holds
    # ~0.5 V when the limiting one hits Jsc), so the honest value is NaN plus
    # an explicit bracket flag. Matched tandems still report a finite slope.
    sens_bracketed = bool(v_of_j(0.0) >= dv_probe and v_of_j(j_hi) <= dv_probe)
    if sens_bracketed:
        j_at_dv = _root(lambda j: v_of_j(j) - dv_probe, 0.0, j_hi, tol=1e-12)
        sens = abs(j_hi - j_at_dv) / dv_probe
    else:
        sens = float("nan")
    return {"jsc_curve_ma_cm2": j_hi, "voc_v": voc, "pce_pct": pmax,
            "vmp_v": v_of_j(jmp), "jmp_ma_cm2": terminal_current(jmp),
            "voc_current_ma_cm2": j_voc,
            "jsc_bias_sensitivity_ma_cm2_per_v": sens,
            "jsc_bias_sensitivity_bracketed": sens_bracketed}


def _build_result(device: TandemDevice, temperature_k: float, metrics: dict, *,
                  converged: bool, iterations: int, solver: str, eg_top: float,
                  eg_bottom: float, j_top_sc: float, j_bot_sc: float,
                  v_top_mpp: float, v_bottom_mpp: float,
                  extra: Optional[dict] = None) -> TandemResult:
    """Assemble the result, pinning Jsc/FF to the physical current-source limit."""
    jsc = float(min(j_top_sc, j_bot_sc))
    metrics = dict(metrics)
    metrics["jsc_ma_cm2"] = jsc
    metrics["jsc_from_curve_ma_cm2"] = metrics.pop("jsc_curve_ma_cm2", float("nan"))
    voc = metrics["voc_v"]
    # V1.9-C UNIT FIX. The solver returns P_out in mW/cm^2 (V*J at the maximum
    # power point). The efficiency is that power divided by the INCIDENT power
    # density, which scales with concentration:
    #     P_in = irradiance_suns * 100 mW/cm^2  (one sun)
    #     pce_pct = P_out / P_in * 100 = P_out / irradiance_suns
    # Before this fix pce_pct was reported as P_out / 100 at EVERY irradiance,
    # i.e. it was a power density mislabelled as a percentage and it scaled
    # linearly with concentration (102.9 "per cent" at 5 suns). At exactly one sun
    # the factor is 1, so no 1-sun result -- and therefore no pinned V1.8/V1.9-B
    # number -- changes. The fill factor keeps the RAW power density, because it
    # is the ratio of P_out to Voc*Jsc in the same units.
    p_out_mw_cm2 = float(metrics["pce_pct"])
    concentration = max(float(device.concentration), 1e-12)
    metrics["p_out_mw_cm2"] = p_out_mw_cm2
    metrics["pce_pct"] = p_out_mw_cm2 / concentration
    metrics["ff"] = (p_out_mw_cm2 / (voc * jsc)) if (voc > 0 and jsc > 0) \
        else float("nan")
    detail = {
        "rs_ohm_cm2": device.rs_ohm_cm2, "rsh_ohm_cm2": device.rsh_ohm_cm2,
        "j0_top": device.top.j0_budget.to_dict(),
        "j0_bottom": device.bottom.j0_budget.to_dict(),
        "luminescent_coupling_beta": float(
            device.mechanism_flags.get("luminescent_coupling_top_to_bottom", 0.0)),
        "luminescent_coupling_beta_bottom_to_top": float(
            device.mechanism_flags.get("luminescent_coupling_bottom_to_top", 0.0)),
        "emission_fraction_bottom_above_top_gap": float(
            device.mechanism_flags.get("emission_fraction_above_top_gap", 0.0)),
        "photon_recycling_gain_top": device.top.photon_recycling_gain,
        "optics_model_form": (device.optics.model_form if device.optics else None),
        "sum_bandgap_ev": float(eg_top + eg_bottom),
        "solver": solver,
        "concentration": float(device.concentration),
        "power_density_out_mw_cm2": float(metrics.get("p_out_mw_cm2", float("nan"))),
        "pce_definition": "P_out / (irradiance_suns * 100 mW/cm2) * 100",
    }
    detail["jsc_definition"] = ("current-source limit min(Jsc_top, Jsc_bottom); "
                               "the curve endpoint is reported alongside as a "
                               "conditioning diagnostic, never used as Jsc")
    detail["jsc_curve_grid_endpoint_ma_cm2"] = float(
        metrics.get("jsc_from_curve_ma_cm2", float("nan")))
    detail["jsc_bias_sensitivity_ma_cm2_per_v"] = float(
        metrics.get("jsc_bias_sensitivity_ma_cm2_per_v", float("nan")))
    detail["jsc_bias_sensitivity_bracketed"] = bool(
        metrics.get("jsc_bias_sensitivity_bracketed", False))
    if device.optics is not None:
        detail["photon_budget_mA_cm2"] = device.optics.absorbed_photon_budget()
    if extra:
        detail.update(extra)
    return TandemResult(
        temperature_k=temperature_k, jsc_ma_cm2=metrics["jsc_ma_cm2"],
        voc_v=metrics["voc_v"], ff=metrics["ff"], pce_pct=metrics["pce_pct"],
        vmp_v=metrics["vmp_v"], jmp_ma_cm2=metrics["jmp_ma_cm2"],
        v_top_at_mpp=v_top_mpp, v_bottom_at_mpp=v_bottom_mpp,
        j_top_sc=j_top_sc, j_bottom_sc=j_bot_sc,
        current_matching_ratio=(j_bot_sc / j_top_sc if j_top_sc > 0 else float("nan")),
        coupling_converged=converged, coupling_iterations=iterations,
        model_form=device.model_form, detail=detail)


# ---------------------------------------------------------------------------
# reference solver (transparent, scalar, kept as the oracle)
# ---------------------------------------------------------------------------
def solve_tandem_reference(device: TandemDevice, temperature_k: float,
                           coupling_tol: float = 1e-6, max_iter: int = 40,
                           n_curve_points: int = 1200) -> TandemResult:
    """Series-constrained tandem with exact (bisection) subcell inversions."""
    beta = float(device.mechanism_flags.get("luminescent_coupling_top_to_bottom", 0.0))
    beta_bt = float(device.mechanism_flags.get("luminescent_coupling_bottom_to_top", 0.0))
    f_up = float(device.mechanism_flags.get("emission_fraction_above_top_gap", 0.0))
    top, bottom = device.top, device.bottom
    kT = K_B_EV_K * temperature_k

    def coupling_tb(v_top_v: float) -> float:
        if beta == 0.0:
            return 0.0
        return float(beta * top.j0_rad_effective() *
                     np.expm1(min(max(v_top_v / kT, -700.0), 700.0)))

    def coupling_bt(v_bottom_v: float) -> float:
        if beta_bt == 0.0 or f_up == 0.0:
            return 0.0
        return float(beta_bt * f_up * bottom.j0_rad_effective() *
                     np.expm1(min(max(v_bottom_v / kT, -700.0), 700.0)))

    j_top_sc = float(current_at_voltage(top, 0.0, temperature_k))
    j_bot_sc = float(current_at_voltage(bottom, 0.0, temperature_k))
    if j_top_sc <= 0 or j_bot_sc <= 0:
        raise SubcellNoVocError(
            f"tandem short-circuit current is non-positive at "
            f"{temperature_k:.1f} K (J_top {j_top_sc:.4g}, J_bottom "
            f"{j_bot_sc:.4g} mA/cm2): a subcell has no operating point here")

    J = np.linspace(0.0, min(j_top_sc, j_bot_sc), n_curve_points)
    t_shift = np.zeros_like(J)
    b_shift = np.zeros_like(J)
    Vt = np.zeros_like(J)
    Vb = np.zeros_like(J)
    converged = True
    it = 0
    needs_fp = beta > 0.0 or (beta_bt > 0.0 and f_up > 0.0)
    if needs_fp:
        converged = False
        for it in range(1, max_iter + 1):
            Vt = np.array([voltage_at_current(top, float(j - ts), temperature_k)
                           for j, ts in zip(J, t_shift)])
            Vb = np.array([voltage_at_current(bottom, float(j - bs), temperature_k)
                           for j, bs in zip(J, b_shift)])
            t_new = np.array([coupling_bt(float(v)) for v in Vb])
            b_new = np.array([coupling_tb(float(v)) for v in Vt])
            d = max(float(np.max(np.abs(t_new - t_shift))),
                    float(np.max(np.abs(b_new - b_shift))))
            t_shift, b_shift = t_new, b_new
            if d <= coupling_tol:
                converged = True
                break
    else:
        Vt = np.array([voltage_at_current(top, float(j), temperature_k) for j in J])
        Vb = np.array([voltage_at_current(bottom, float(j), temperature_k) for j in J])

    V = Vt + Vb - J * device.rs_ohm_cm2 / 1000.0
    # The same current-parametrised metric extraction as the fast solver, so that
    # a reference-vs-fast comparison isolates the subcell-inversion numerics
    # rather than two different definitions of the operating point.
    metrics = curve_metrics_by_current(J, V, device.rsh_ohm_cm2)
    jmp = metrics["jmp_ma_cm2"]
    t_at_mpp = float(np.interp(jmp, J, t_shift))
    b_at_mpp = float(np.interp(jmp, J, b_shift))
    return _build_result(
        device, temperature_k, metrics, converged=converged, iterations=it,
        solver="reference",
        eg_top=device.mechanism_flags.get("eg_top", 0.0),
        eg_bottom=device.mechanism_flags.get("eg_bottom", 0.0),
        j_top_sc=j_top_sc, j_bot_sc=j_bot_sc,
        v_top_mpp=float(voltage_at_current(top, jmp - t_at_mpp, temperature_k)),
        v_bottom_mpp=float(voltage_at_current(bottom, jmp - b_at_mpp, temperature_k)))


# ---------------------------------------------------------------------------
# fast solver (vectorised Newton + table inversion)
# ---------------------------------------------------------------------------
def current_density_vectorized(model: SubcellModel, voltage_v: np.ndarray,
                               temperature_k: float, tol: float = 1e-12,
                               max_iter: int = 60) -> tuple:
    """Vectorised implicit solve of J(V) for a subcell with Rs and/or Rsh.

    Newton on  f(J) = Jph + coupling - J0r expm1(Vj/kT) - J0s expm1(Vj/(n kT))
                      - Vj/Rsh - J ,  Vj = V + J Rs/1000 ,
    with f'(J) = -((D_rad + D_srh + 1/Rsh)(Rs/1000) + 1) < 0 always.
    V1.9-H repair (Rs-sign): Vj carries a PLUS sign (junction = terminal +
    resistive drop); the old minus sign made Rs raise the current. For Rs = 0
    the equation is linear in J, so the ideal case is reproduced exactly.
    """
    V = np.atleast_1d(np.asarray(voltage_v, dtype=float))
    kT = K_B_EV_K * temperature_k
    j0_rad = model.j0_rad_effective()
    j0_srh = model.j0_srh()
    n_id = model.ideality_srh
    jph = model.jph_ma_cm2
    coupling = model.luminescent_coupling_in * model.radiative_coupling_source
    rs = model.rs_ohm_cm2 / 1000.0
    g_sh = 1.0 / model.rsh_ohm_cm2 if np.isfinite(model.rsh_ohm_cm2) else 0.0

    J = np.full_like(V, jph)
    lo, hi = -2.0 * abs(jph) - 10.0, 2.0 * abs(jph) + 10.0
    iters = 0
    for it in range(1, max_iter + 1):
        iters = it
        vj = V + J * rs
        xr = np.clip(vj / kT, -700.0, 700.0)
        xs = np.clip(vj / (n_id * kT), -700.0, 700.0)
        with np.errstate(over="ignore"):
            d_rad = j0_rad * np.expm1(xr)
            d_srh = j0_srh * np.expm1(xs)
            d_rad_p = j0_rad * np.exp(xr) / kT
            d_srh_p = j0_srh * np.exp(xs) / (n_id * kT)
        f = jph + coupling - d_rad - d_srh - vj * g_sh - J
        step = f / (-((d_rad_p + d_srh_p + g_sh) * rs + 1.0))
        J = np.clip(J - step, lo, hi)
        if np.max(np.abs(step)) <= tol:
            break
    vj = V + J * rs
    with np.errstate(over="ignore"):
        resid = (jph + coupling
                 - j0_rad * np.expm1(np.clip(vj / kT, -700, 700))
                 - j0_srh * np.expm1(np.clip(vj / (n_id * kT), -700, 700))
                 - vj * g_sh - J)
    return J, {"iterations": iters,
               "converged_fraction": float(np.mean(np.abs(resid) <= 1e-7)),
               "max_residual_ma_cm2": float(np.max(np.abs(resid)))}


def subcell_table(model: SubcellModel, temperature_k: float, n_points: int = 3001,
                  v_pad: float = 0.25) -> tuple:
    """Tabulate V -> J for one subcell (monotone decreasing J) on a dense grid."""
    voc = open_circuit_voltage(model, temperature_k)
    V = np.linspace(-abs(v_pad), voc * 1.01 + 0.02, n_points)
    J, diag = current_density_vectorized(model, V, temperature_k)
    mono = bool(np.all(np.diff(J) <= 0.0))
    if not mono:
        J = np.minimum.accumulate(J)
    return V, J, {"monotone": mono, "voc_v": float(voc), **diag}


def solve_tandem_fast(device: TandemDevice, temperature_k: float,
                      coupling_tol: float = 1e-9, max_iter: int = 20,
                      n_curve_points: int = 1200, n_table: int = 4001) -> TandemResult:
    """Vectorised series-constrained tandem solve (production path)."""
    beta = float(device.mechanism_flags.get("luminescent_coupling_top_to_bottom", 0.0))
    beta_bt = float(device.mechanism_flags.get("luminescent_coupling_bottom_to_top", 0.0))
    f_up = float(device.mechanism_flags.get("emission_fraction_above_top_gap", 0.0))
    top, bottom = device.top, device.bottom
    kT = K_B_EV_K * temperature_k

    Vt_tab, Jt_tab, diag_t = subcell_table(top, temperature_k, n_table)
    Vb_tab, Jb_tab, diag_b = subcell_table(bottom, temperature_k, n_table)
    Jt_asc, Vt_asc = Jt_tab[::-1], Vt_tab[::-1]
    Jb_asc, Vb_asc = Jb_tab[::-1], Vb_tab[::-1]

    def j_of_v(v, V_tab, J_tab):
        return np.interp(v, V_tab, J_tab)

    def v_of_j_tied(sub, q, J_asc, V_asc, jsc):
        """Table V(J) inversion with an exact-scalar repair of flat-tie queries.

        V1.9-H repair (F1): where J(V) is numerically flat (below diode
        turn-on), table rows tie at J ~= Jsc and np.interp tie-breaking
        returns the pad endpoint (V = -v_pad) instead of V(Jsc) = 0,
        poisoning the V(J) grid endpoint by ~250 mV. Queries within
        jsc*1e-9 of Jsc (in practice the grid endpoint of the limiting
        subcell) use the exact scalar inversion instead -- a handful of
        bookkeeping evaluations, cf. test_fast_solver_is_actually_vectorised.
        """
        scalar = np.ndim(q) == 0
        qq = np.atleast_1d(np.clip(np.asarray(q, dtype=float), J_asc[0], J_asc[-1]))
        out = np.asarray(np.interp(qq, J_asc, V_asc), dtype=float)
        tie = np.abs(qq - jsc) < jsc * 1e-9
        for idx in np.nonzero(tie)[0]:
            out[idx] = voltage_at_current(sub, float(qq[idx]), temperature_k)
        return out[0] if scalar else out

    j_top_sc = float(j_of_v(0.0, Vt_tab, Jt_tab))
    j_bot_sc = float(j_of_v(0.0, Vb_tab, Jb_tab))
    if j_top_sc <= 0 or j_bot_sc <= 0:
        raise SubcellNoVocError(
            f"tandem short-circuit current is non-positive at "
            f"{temperature_k:.1f} K (J_top {j_top_sc:.4g}, J_bottom "
            f"{j_bot_sc:.4g} mA/cm2): a subcell has no operating point here")

    J = np.linspace(0.0, min(j_top_sc, j_bot_sc), n_curve_points)
    t_shift = np.zeros_like(J)
    b_shift = np.zeros_like(J)
    converged = True
    it = 0
    if beta > 0.0 or (beta_bt > 0.0 and f_up > 0.0):
        converged = False
        j0r_t, j0r_b = top.j0_rad_effective(), bottom.j0_rad_effective()
        Vt = v_of_j_tied(top, J, Jt_asc, Vt_asc, j_top_sc)
        Vb = v_of_j_tied(bottom, J, Jb_asc, Vb_asc, j_bot_sc)
        for it in range(1, max_iter + 1):
            t_new = beta_bt * f_up * j0r_b * np.expm1(np.clip(Vb / kT, -700, 700))
            b_new = beta * j0r_t * np.expm1(np.clip(Vt / kT, -700, 700))
            d = max(float(np.max(np.abs(t_new - t_shift))),
                    float(np.max(np.abs(b_new - b_shift))))
            t_shift, b_shift = t_new, b_new
            Vt = v_of_j_tied(top, J - t_shift, Jt_asc, Vt_asc, j_top_sc)
            Vb = v_of_j_tied(bottom, J - b_shift, Jb_asc, Vb_asc, j_bot_sc)
            if d <= coupling_tol:
                converged = True
                break
    Vt = v_of_j_tied(top, J - t_shift, Jt_asc, Vt_asc, j_top_sc)
    Vb = v_of_j_tied(bottom, J - b_shift, Jb_asc, Vb_asc, j_bot_sc)
    V = Vt + Vb - J * device.rs_ohm_cm2 / 1000.0

    metrics = curve_metrics_by_current(J, V, device.rsh_ohm_cm2)
    jmp = metrics["jmp_ma_cm2"]
    q_top_mpp = jmp - float(np.interp(jmp, J, t_shift))
    q_bot_mpp = jmp - float(np.interp(jmp, J, b_shift))
    return _build_result(
        device, temperature_k, metrics, converged=converged, iterations=it,
        solver="fast",
        eg_top=device.mechanism_flags.get("eg_top", 0.0),
        eg_bottom=device.mechanism_flags.get("eg_bottom", 0.0),
        j_top_sc=j_top_sc, j_bot_sc=j_bot_sc,
        v_top_mpp=float(v_of_j_tied(top, q_top_mpp, Jt_asc, Vt_asc, j_top_sc)),
        v_bottom_mpp=float(v_of_j_tied(bottom, q_bot_mpp, Jb_asc, Vb_asc, j_bot_sc)),
        extra={"subcell_table_diagnostics": {"top": diag_t, "bottom": diag_b,
                                             "n_table": n_table}})


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def evaluate_tandem(ps: ParamSet, model_form: str = "IQE-M1",
                    temperature_k: Optional[float] = None,
                    spectrum: Optional[Spectrum] = None,
                    optics: Optional[TandemOpticsResult] = None,
                    self_heating: bool = True,
                    solver: str = "auto",
                    thermal_model: str = "energy_balance") -> TandemResult:
    """Build and solve the tandem from a ParamSet.

    solver        ``auto`` (fast), ``reference`` (oracle) or ``fast``.
    thermal_model ``energy_balance`` (default, V1.9-C) or ``simple`` (V1.9-B
                  lineage closure); ``self_heating=False`` freezes the junction
                  at the ambient temperature.
    """
    from .thermal import (SUN_POWER_MW_CM2, assert_inside_electrical_envelope,
                          simple_temperature, solve_equilibrium)
    from ..core.constants import K_B_EV_K as _kT

    sp = spectrum or spectrum_for(ps)
    t_ambient = float(temperature_k if temperature_k is not None else ps["temperature_k"])
    opt = optics if optics is not None else optics_for(ps, model_form=model_form)
    solver_name = "fast" if solver == "auto" else solver
    if solver_name not in ("fast", "reference"):
        raise ValueError(f"unknown solver {solver!r}")

    def solve_at(T: float) -> TandemResult:
        dev = build_tandem(ps, model_form, T, sp, opt)
        dev = _with_bandgap_flags(dev, ps, T)
        fn = solve_tandem_fast if solver_name == "fast" else solve_tandem_reference
        return fn(dev, T)

    if not self_heating:
        res = solve_at(t_ambient)
        # FIXED-TEMPERATURE DIAGNOSTIC. The reported state must describe the solve
        # that actually happened: the junction is held AT AMBIENT, so there is no
        # conduction or radiative flux and no balance to report. (Until V1.9-C
        # this branch reported the *simple closure* junction temperature -- 328 K
        # -- while the physics had been solved at 298.15 K. The thermal
        # fixed-temperature invariant caught the inconsistency.)
        thermal = {
            "model": "fixed-temperature", "ambient_k": t_ambient,
            "junction_k": t_ambient, "delta_t_k": 0.0,
            "r_th_effective_k_cm2_w": 0.0, "emissivity": 0.0,
            "heat_load_mw_cm2": None, "conduction_loss_mw_cm2": 0.0,
            "radiative_loss_mw_cm2": 0.0, "residual_mw_cm2": 0.0,
            "d_loss_dt_mw_cm2_k": None, "d_heat_dt_mw_cm2_k": 0.0,
            "iterations": 0, "converged": True,
            "closure_note": "self_heating=False: junction held at ambient; no "
                            "thermal balance is solved (diagnostic mode)",
            "category": "MODEL-ASSUMED-CLOSURE", "diagnostics": {},
        }
    elif thermal_model == "simple":
        st = simple_temperature(ps, t_ambient)
        res = solve_at(st.junction_k)
        thermal = _thermal_as_dict(st)
    elif thermal_model == "energy_balance":
        absorbed = opt.absorbed_power_mw_cm2(sp) * float(ps["irradiance_suns"])
        extractor = ElectricalPowerExtractor(solve_at, float(ps["irradiance_suns"]),
                                             SUN_POWER_MW_CM2)
        st = solve_equilibrium(ps, absorbed, extractor, t_ambient)
        assert_inside_electrical_envelope(
            st.junction_k,
            context=f"{ps['irradiance_suns']:g} sun, R_th {ps['thermal_resistance_k_cm2_w']:g} "
                    f"K cm2/mW, {extractor.stats['envelope_extrapolations']} trial "
                    f"evaluation(s) substituted")
        res = solve_at(st.junction_k)
        thermal = _thermal_as_dict(st)
        thermal["electrical_solves"] = extractor.stats["evaluations"]
        thermal["absorbed_power_mw_cm2"] = absorbed
        thermal["electrical_envelope"] = dict(extractor.stats)
    else:
        raise ValueError(f"unknown thermal_model {thermal_model!r}")

    detail = dict(res.detail)
    detail["thermal"] = thermal
    detail["solver"] = solver_name
    out = TandemResult(**{**res.__dict__, "detail": detail})
    # Every solve carries its invariant verdict: no path can produce a result
    # whose admissibility is unknown. The guard is imported lazily (it imports
    # this module for its own diagnostics) and is cheap: it evaluates scalars and
    # the (lru-cached) optical arrays only.
    try:
        from ..validation.guard import judge_optics, judge_tandem
        bundle = judge_tandem(out, optical_bundle=judge_optics(opt))
        out.detail["invariants"] = bundle.to_dict()
        out.detail["solve_valid"] = bool(bundle.valid)
    except Exception as exc:                                   # pragma: no cover
        out.detail["invariants"] = {"status": "NOT_EVALUATED",
                                    "valid": None, "error": f"{type(exc).__name__}: {exc}"}
        out.detail["solve_valid"] = None
    return out


class ElectricalPowerExtractor:
    """T[K] -> extracted electrical power [mW/cm2] for the thermal balance.

    Wraps the electrical solve and handles the model-validity envelope: above the
    temperature at which a subcell loses its positive open-circuit voltage (its
    equilibrium recombination current exceeds its photocurrent) the electrical
    model has no operating point. The conservative substitution there is
    P_elec = 0, i.e. ALL absorbed power becomes heat -- the substitution can only
    push the solved junction temperature UP, and it is used only for trial
    temperatures above the envelope, never at the converged answer (the guard
    flags any solve whose final temperature needed it).

    ``stats`` records how many trial evaluations fell outside the envelope and the
    lowest such temperature, so the extrapolation is auditable rather than silent.
    """

    def __init__(self, solve_at, suns: float,
                 sun_power_mw_cm2: float = None):
        from .thermal import SUN_POWER_MW_CM2
        self._solve_at = solve_at
        self._suns = float(suns)
        self._sun = float(SUN_POWER_MW_CM2 if sun_power_mw_cm2 is None else sun_power_mw_cm2)
        from .thermal import ELECTRICAL_ENVELOPE_MAX_K, ELECTRICAL_ENVELOPE_MIN_K
        self.stats = {"evaluations": 0, "envelope_extrapolations": 0,
                      "lowest_extrapolated_k": None, "last_error": "",
                      "envelope_min_k": ELECTRICAL_ENVELOPE_MIN_K,
                      "envelope_max_k": ELECTRICAL_ENVELOPE_MAX_K}

    def __call__(self, temperature_k: float) -> float:
        from .thermal import ELECTRICAL_ENVELOPE_MAX_K, ELECTRICAL_ENVELOPE_MIN_K
        self.stats["evaluations"] += 1
        T = float(temperature_k)
        if T < ELECTRICAL_ENVELOPE_MIN_K or T > ELECTRICAL_ENVELOPE_MAX_K:
            # outside the electrical model's registered validity window: do not
            # evaluate the electrical model at all (it would extrapolate), use the
            # conservative P_elec = 0 substitution instead
            self.stats["envelope_extrapolations"] += 1
            low = self.stats["lowest_extrapolated_k"]
            self.stats["lowest_extrapolated_k"] = (T if low is None else min(low, T))
            self.stats["last_error"] = (f"trial temperature {T:.1f} K outside the "
                                       f"registered electrical envelope "
                                       f"[{ELECTRICAL_ENVELOPE_MIN_K}, "
                                       f"{ELECTRICAL_ENVELOPE_MAX_K}] K")
            return 0.0
        try:
            r = self._solve_at(T)
        except SubcellNoVocError as exc:
            self.stats["envelope_extrapolations"] += 1
            low = self.stats["lowest_extrapolated_k"]
            self.stats["lowest_extrapolated_k"] = (T if low is None else min(low, T))
            self.stats["last_error"] = str(exc)
            return 0.0
        return abs(r.pce_pct) * self._sun * self._suns / 100.0


def _thermal_as_dict(st, model: Optional[str] = None, note: str = "") -> dict:
    d = st.to_dict()
    if model:
        d["model"] = model
    if note:
        d["closure_note"] = note
    d["category"] = "MODEL-ASSUMED-CLOSURE"
    return d


def _with_bandgap_flags(device: TandemDevice, ps: ParamSet, temperature_k: float) -> TandemDevice:
    """Attach the temperature-dependent bandgaps to the mechanism flags so the
    solvers can report sum(Eg) for the voltage-limit invariant."""
    from ..materials.perovskite import perovskite_bandgap_temperature
    from ..materials.silicon import varshni_bandgap
    eg_top = perovskite_bandgap_temperature(
        ps["perovskite_eg_ev"], temperature_k, 298.15, ps["eg_temperature_coeff_ev_k"])
    eg_bottom = varshni_bandgap(ps["silicon_eg_ev"], temperature_k)
    flags = dict(device.mechanism_flags)
    flags["eg_top"], flags["eg_bottom"] = eg_top, eg_bottom
    return TandemDevice(top=device.top, bottom=device.bottom, rs_ohm_cm2=device.rs_ohm_cm2,
                        rsh_ohm_cm2=device.rsh_ohm_cm2, optics=device.optics,
                        model_form=device.model_form, mechanism_flags=flags,
                        concentration=device.concentration)


# Backwards-compatible alias: ``solve_tandem`` is the reference implementation.
solve_tandem = solve_tandem_reference


def _with_coupling(bottom: SubcellModel, beta: float, i_rad_top: float) -> SubcellModel:
    """Copy of the bottom subcell with a luminescent-coupling current term."""
    return SubcellModel(
        name=bottom.name, jph_ma_cm2=bottom.jph_ma_cm2, j0_budget=bottom.j0_budget,
        ideality_srh=bottom.ideality_srh, rs_ohm_cm2=bottom.rs_ohm_cm2,
        rsh_ohm_cm2=bottom.rsh_ohm_cm2,
        photon_recycling_gain=bottom.photon_recycling_gain,
        luminescent_coupling_in=beta, radiative_coupling_source=i_rad_top)
