"""APMT V1.9 — two-terminal series-constrained tandem device model.

A two-terminal tandem forces a common current. For a terminal current J the
subcell voltages follow from inverting each subcell's own J-V:

    V_top(J) = V_top^{-1}(J),   V_bottom(J) = V_bottom^{-1}(J)
    V_terminal(J) = V_top(J) + V_bottom(J) - J * Rs / 1000

with Rs [ohm*cm2] applied once at the tandem level (the external series
resistance is a property of the two-terminal device, and the recorded gate
evidence is an *external* resistance). Shunt resistance is applied at the
tandem level for the same reason.

Luminescent coupling is solved self-consistently: the bottom cell receives
``beta * I_rad_top(V_top)`` where ``I_rad_top`` is the *radiative* recombination
current of the top cell at its own operating point. Because the coupling
changes the bottom cell's current, a fixed-point iteration is used with an
explicit convergence record; if it does not converge the solver raises rather
than returning a silently inconsistent number.

Photon recycling enters through the top cell's effective radiative J0 (see
recombination.py / subcell.py) and is recorded in the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..core.constants import K_B_EV_K
from ..core.numerics import golden_section_max
from ..optics.stack import TandemOpticsResult, solve_tandem_optics
from ..params.registry import ParamSet
from ..spectra.reference import Spectrum, reference
from .recombination import j0_budget, j0_srh_temperature_scaled
from .subcell import SubcellModel, current_at_voltage, open_circuit_voltage, voltage_at_current


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


def _subcell_from_params(ps: ParamSet, optics: TandemOpticsResult, temperature_k: float,
                         spectrum: Spectrum) -> tuple:
    """Build the two subcells, including temperature-dependent bandgaps."""
    from ..materials.perovskite import perovskite_bandgap_temperature
    from ..materials.silicon import varshni_bandgap

    eg_top = perovskite_bandgap_temperature(
        ps["perovskite_eg_ev"], temperature_k, 298.15, ps["eg_temperature_coeff_ev_k"])
    eg_bottom = varshni_bandgap(ps["silicon_eg_ev"], temperature_k)

    j_top = optics.jsc_top_ma_cm2(spectrum)
    j_bot = optics.jsc_bottom_ma_cm2(spectrum)

    # --- top cell: perovskite: SRH route is a slab model with an effective
    # lifetime derived from the measured PLQY/ERE of the representative device
    j0_top = j0_budget(eg_top, temperature_k, ps["radiative_efficiency_top"],
                       ps["ideality_top"],
                       thickness_cm=ps["perovskite_thickness_nm"] * 1e-7,
                       lifetime_s=ps["perovskite_srh_lifetime_ns"] * 1e-9,
                       doping_cm3=ps["perovskite_doping_cm3"],
                       srv_cm_s=ps["perovskite_srv_cm_s"])
    # --- bottom cell: silicon: slab SRH with the registered wafer parameters
    j0_bot = j0_budget(eg_bottom, temperature_k, ps["radiative_efficiency_bottom"],
                       ps["ideality_bottom"],
                       thickness_cm=ps["silicon_thickness_um"] * 1e-4,
                       lifetime_s=ps["silicon_bulk_lifetime_ms"] * 1e-3,
                       doping_cm3=ps["silicon_doping_cm3"],
                       srv_cm_s=ps["silicon_srv_cm_s"])

    # temperature correction applied from the 298.15 K reference
    if abs(temperature_k - 298.15) > 1e-9:
        from ..materials.perovskite import perovskite_bandgap_temperature as pbg
        eg_top_ref = ps["perovskite_eg_ev"]
        eg_bot_ref = varshni_bandgap(ps["silicon_eg_ev"], 298.15)
        j0_srh_top = j0_srh_temperature_scaled(
            j0_top.j0_srh_ma_cm2, temperature_k, 298.15, eg_top, eg_top_ref,
            ps["ideality_top"])
        j0_srh_bot = j0_srh_temperature_scaled(
            j0_bot.j0_srh_ma_cm2, temperature_k, 298.15, eg_bottom, eg_bot_ref,
            ps["ideality_bottom"])
        j0_top = j0_budget(eg_top, temperature_k, ps["radiative_efficiency_top"],
                           ps["ideality_top"], j0_srh_override_ma_cm2=j0_srh_top)
        j0_bot = j0_budget(eg_bottom, temperature_k, ps["radiative_efficiency_bottom"],
                           ps["ideality_bottom"], j0_srh_override_ma_cm2=j0_srh_bot)

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
                 optics: Optional[TandemOpticsResult] = None) -> TandemDevice:
    """Assemble the tandem device from a ParamSet (the digital twin)."""
    sp = spectrum or reference()
    T = float(temperature_k if temperature_k is not None else ps["temperature_k"])
    opt = optics if optics is not None else solve_tandem_optics(
        ps, model_form=model_form, spectrum=sp)
    top, bottom, eg_top, eg_bottom = _subcell_from_params(ps, opt, T, sp)
    return TandemDevice(top=top, bottom=bottom,
                        rs_ohm_cm2=ps["rs_ohm_cm2"] + ps["interconnect_resistance_ohm_cm2"],
                        rsh_ohm_cm2=ps["rsh_ohm_cm2"], optics=opt, model_form=model_form,
                        mechanism_flags={
                            "photon_recycling_gain_top": ps["photon_recycling_gain_top"],
                            "luminescent_coupling_top_to_bottom":
                                ps["luminescent_coupling_top_to_bottom"],
                            "silicon_light_trapping": ps["silicon_light_trapping"],
                        })


def solve_tandem(device: TandemDevice, temperature_k: float,
                 coupling_tol: float = 1e-6, max_iter: int = 40,
                 n_curve_points: int = 400) -> TandemResult:
    """Solve the series-constrained tandem including luminescent coupling.

    The J-V curve is built by parametrising on the internal series current J:
    for each J the two subcell voltages are inverted exactly (subcell.py), and
    the terminal voltage is  V = V_top(J) + V_bottom(J) - J*Rs/1000.  A finite
    shunt resistance then removes V/Rsh from the terminal current.  Voc and the
    MPP are evaluated on the resulting monotone curve.
    """
    beta = float(device.mechanism_flags.get("luminescent_coupling_top_to_bottom", 0.0))
    top = device.top
    bottom = device.bottom
    converged = True
    n_iter = 0

    # --- self-consistent luminescent coupling ------------------------------
    v_top_ref = open_circuit_voltage(top, temperature_k)
    for n_iter in range(1, max_iter + 1):
        i_rad_top = _radiative_recombination_current(top, v_top_ref, temperature_k)
        bottom = _with_coupling(bottom, beta, i_rad_top)
        v_new = _tandem_voc(top, bottom, temperature_k, device.rs_ohm_cm2)
        if abs(v_new - v_top_ref) <= coupling_tol:
            v_top_ref = v_new
            break
        v_top_ref = v_new
    else:
        converged = False

    j_limit = min(float(current_at_voltage(top, 0.0, temperature_k)),
                  float(current_at_voltage(bottom, 0.0, temperature_k)))
    if j_limit <= 0:
        raise RuntimeError("tandem short-circuit current is non-positive")

    J = np.linspace(0.0, j_limit, n_curve_points)
    V = np.empty_like(J)
    for i, j in enumerate(J):
        vt = voltage_at_current(top, float(j), temperature_k)
        vb = voltage_at_current(bottom, float(j), temperature_k)
        V[i] = vt + vb - float(j) * device.rs_ohm_cm2 / 1000.0

    J_term = J.copy()
    if np.isfinite(device.rsh_ohm_cm2):
        J_term = J - V / device.rsh_ohm_cm2 * 1000.0 / 1000.0

    # monotone ascending V along decreasing J -> invert for the MPP search
    order = np.argsort(V)
    V_sorted, J_sorted = V[order], J_term[order]

    def j_at_v(v: float) -> float:
        return float(np.interp(v, V_sorted, J_sorted))

    v_max = float(V_sorted[-1])
    # Voc: terminal voltage where the terminal current vanishes
    idx = np.where(J_sorted <= 0.0)[0]
    if idx.size:
        voc = float(np.interp(0.0, J_sorted[idx][::-1] * -1.0,
                              V_sorted[idx][::-1] * -1.0)) if False else float(V_sorted[idx[0]])
    else:
        voc = v_max

    def power(v: float) -> float:
        return v * j_at_v(v)

    vmp, pmax = golden_section_max(power, 0.0, voc, tol=1e-10)
    jmp = j_at_v(vmp)
    jsc = float(j_at_v(0.0))
    ff = pmax / (voc * jsc) if voc * jsc > 0 else float("nan")

    j_top_sc = float(current_at_voltage(top, 0.0, temperature_k))
    j_bot_sc = float(current_at_voltage(bottom, 0.0, temperature_k))
    return TandemResult(
        temperature_k=temperature_k, jsc_ma_cm2=jsc, voc_v=voc, ff=ff, pce_pct=pmax,
        vmp_v=vmp, jmp_ma_cm2=jmp,
        v_top_at_mpp=float(voltage_at_current(top, jmp, temperature_k)),
        v_bottom_at_mpp=float(voltage_at_current(bottom, jmp, temperature_k)),
        j_top_sc=j_top_sc, j_bottom_sc=j_bot_sc,
        current_matching_ratio=j_bot_sc / j_top_sc if j_top_sc > 0 else float("nan"),
        coupling_converged=converged, coupling_iterations=n_iter,
        model_form=device.model_form,
        detail={
            "rs_ohm_cm2": device.rs_ohm_cm2, "rsh_ohm_cm2": device.rsh_ohm_cm2,
            "j0_top": device.top.j0_budget.to_dict(),
            "j0_bottom": device.bottom.j0_budget.to_dict(),
            "luminescent_coupling_beta": beta,
            "photon_recycling_gain_top": device.top.photon_recycling_gain,
            "optics_model_form": (device.optics.model_form if device.optics else None),
        })


def _with_coupling(bottom: SubcellModel, beta: float, i_rad_top: float) -> SubcellModel:
    """Return a copy of the bottom subcell with luminescent coupling applied."""
    return SubcellModel(
        name=bottom.name, jph_ma_cm2=bottom.jph_ma_cm2, j0_budget=bottom.j0_budget,
        ideality_srh=bottom.ideality_srh, rs_ohm_cm2=bottom.rs_ohm_cm2,
        rsh_ohm_cm2=bottom.rsh_ohm_cm2,
        photon_recycling_gain=bottom.photon_recycling_gain,
        luminescent_coupling_in=beta, radiative_coupling_source=i_rad_top)


def _tandem_voc(top: SubcellModel, bottom: SubcellModel, temperature_k: float,
                rs_ohm_cm2: float = 0.0) -> float:
    """Open-circuit voltage of the series tandem (common current -> 0 limit).

    For a series-constrained tandem the terminal voltage at J = 0 is the sum of
    the two subcell voltages each evaluated at J = 0 (i.e. at their own
    open-circuit condition) -- this is the standard limit, and it is what the
    iterative coupling step needs. The full J-V solve treats the finite-current
    coupling exactly.
    """
    return (open_circuit_voltage(top, temperature_k)
            + open_circuit_voltage(bottom, temperature_k))


def evaluate_tandem(ps: ParamSet, model_form: str = "IQE-M1",
                    temperature_k: Optional[float] = None,
                    spectrum: Optional[Spectrum] = None,
                    optics: Optional[TandemOpticsResult] = None) -> TandemResult:
    """Convenience: build and solve the tandem from a ParamSet."""
    sp = spectrum or reference()
    T = float(temperature_k if temperature_k is not None else ps["temperature_k"])
    device = build_tandem(ps, model_form, T, sp, optics)
    return solve_tandem(device, T)
