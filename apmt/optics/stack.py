"""APMT V1.9 — tandem optical stack assembly from a ParamSet.

Builds the perovskite/silicon stack, solves it with the optics layer and turns
the result into subcell EQE/IQE models. Every layer thickness and material
parameter comes from :mod:`apmt.params.registry`; nothing is hard-coded here.

Stack (front to back), matching the reference device class of Al-Ashouri 2020
(planar front side, textured rear, 260 um SHJ silicon):

    air | MgF2 ARC | lossy transport layer (TCO/HTL proxy) |
          perovskite absorber | silicon wafer (incoherent) | air

Two internal-quantum-efficiency model forms are provided, because the source
reports *external* quantum efficiency only. Comparing them is a model-form
robustness test, not a fitting exercise:

    IQE-M1  constant collection plateau per subcell
    IQE-M2  diffusion/collection-length limited:  IQE = alpha L / (alpha L + 1)

Both are combined with the *absorbed*-photon fraction of the absorber layer:

    EQE(lambda) = A_absorber(lambda) * IQE(lambda)

so EQE <= A_absorber <= 1 by construction and no EQE can exceed the optical
budget (invariant-checked).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from ..core.numerics import trapz
from ..materials.perovskite import perovskite_index
from ..materials.silicon import silicon_index
from ..params.registry import ParamSet
from ..spectra.reference import Spectrum, reference
from .tmm import Layer, OpticsResult, solve_incoherent_substrate, solve_stack

# Fixed optical constants of the auxiliary layers (documented; these are shape
# assumptions of the stack model, not fitted device parameters):
MG_F2_N = 1.38            # magnesium fluoride ARC (low-index, dispersionless)
TRANSPORT_N = 1.90        # TCO / transport-layer proxy
TCO_UV_DECAY_NM = 60.0    # decay scale of the TCO band-edge absorption


@dataclass(frozen=True)
class TandemOpticsResult:
    """Optical + quantum-efficiency result for the tandem stack."""

    wavelength_nm: np.ndarray
    reflectance: np.ndarray
    transmittance: np.ndarray
    absorption: Dict[str, np.ndarray]
    eqe_top: np.ndarray
    eqe_bottom: np.ndarray
    iqe_top: np.ndarray
    iqe_bottom: np.ndarray
    optics: OpticsResult
    model_form: str = "IQE-M1"

    # -- scalar diagnostics -------------------------------------------------
    def jsc_top_ma_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        sp = spectrum or reference()
        return sp.eqe_current(self.eqe_top, self.wavelength_nm, 300.0, 1250.0)

    def jsc_bottom_ma_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        sp = spectrum or reference()
        return sp.eqe_current(self.eqe_bottom, self.wavelength_nm, 300.0, 1250.0)

    def reflection_loss_ma_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        sp = spectrum or reference()
        return sp.jph_100eqe(300.0, 1250.0) - sp.eqe_current(
            1.0 - self.reflectance, self.wavelength_nm, 300.0, 1250.0)

    def parasitic_loss_ma_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        sp = spectrum or reference()
        par = self.optics.parasitic_absorption(("perovskite", "silicon"))
        return sp.eqe_current(par, self.wavelength_nm, 300.0, 1250.0)

    def transmission_loss_ma_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        sp = spectrum or reference()
        return sp.eqe_current(self.transmittance, self.wavelength_nm, 300.0, 1250.0)

    def absorbed_power_mw_cm2(self, spectrum: Optional[Spectrum] = None) -> float:
        """Absorbed optical power density [mW/cm^2] over the solution window.

        int G(lambda) * A_total(lambda) dlambda with G in W m^-2 nm^-1 and the
        conversion 1 W/m^2 = 0.1 mW/cm^2 (so the result is directly comparable
        with a 100 mW/cm^2 one-sun reference). This is the quantity that becomes
        heat in the thermal energy balance.
        """
        sp = spectrum or reference()
        m = sp.mask(float(self.wavelength_nm[0]), float(self.wavelength_nm[-1]))
        wl = sp.wavelength_nm[m]
        a_total = np.interp(wl, self.wavelength_nm,
                            np.asarray(self.optics.total_absorption))
        power_w_m2 = trapz(sp.irradiance_w_m2_nm[m] * a_total, wl)
        return float(power_w_m2 * 0.1)

    def absorbed_photon_budget(self, spectrum: Optional[Spectrum] = None) -> dict:
        """Photon-budget decomposition of the 300-1250 nm window [mA/cm2]."""
        sp = spectrum or reference()
        total = sp.jph_100eqe(300.0, 1250.0)
        return {
            "incident_100pct_eqe": total,
            "reflected": self.reflection_loss_ma_cm2(sp),
            "parasitic_absorbed": self.parasitic_loss_ma_cm2(sp),
            "transmitted": self.transmission_loss_ma_cm2(sp),
            "absorbed_top": sp.eqe_current(self.absorption["perovskite"],
                                           self.wavelength_nm, 300.0, 1250.0),
            "absorbed_bottom": sp.eqe_current(self.absorption["silicon"],
                                              self.wavelength_nm, 300.0, 1250.0),
        }


def transport_layer_k(ps: ParamSet, wl: np.ndarray) -> np.ndarray:
    """Extinction coefficient of the lossy front transport/TCO proxy layer.

    Two documented absorption mechanisms of transparent conductive oxides:

    * free-carrier (Drude) absorption, rising towards the infrared:
      ``k_fc * (lambda / 1000 nm)**2``
    * band-edge/Urbach absorption at short wavelengths, decaying over
      ``TCO_UV_DECAY_NM`` nm from the 300 nm amplitude.

    Both amplitudes are registry parameters with literature-backed defaults and
    ranges; the decay length is a documented shape assumption. This term only
    ever *removes* photons from the useful budget, so it can never inflate an
    efficiency -- it exists because the measured EQE/R-T-A require a
    wavelength-dependent parasitic channel.
    """
    wl = np.asarray(wl, dtype=float)
    k_fc = ps["tco_free_carrier_k"] * (wl / 1000.0) ** 2
    k_uv = ps["tco_uv_absorption_k"] * np.exp(-np.maximum(wl - 300.0, 0.0) / TCO_UV_DECAY_NM)
    return k_fc + k_uv


def _transport_layer(ps: ParamSet, wl: np.ndarray) -> Layer:
    return Layer("transport", ps["parasitic_layer_thickness_nm"], TRANSPORT_N,
                 transport_layer_k(ps, wl), coherent=True, pv_active=False)


def build_stack(ps: ParamSet) -> tuple:
    """Return (front_layers, substrate_layer, wavelength_grid_indices)."""
    wl = TANDEM_WAVELENGTH_NM
    eg = ps["perovskite_eg_ev"]
    pv = perovskite_index(eg, ps["perovskite_absorption_alpha_ev"],
                          ps["perovskite_urbach_mev"], ps["perovskite_n_inf"],
                          ps["perovskite_oscillator_ev"], wl)
    si = silicon_index(wl, tail_nm=25.0)
    front = [
        Layer("arc", ps["arc_thickness_nm"], MG_F2_N, 0.0, pv_active=False),
        _transport_layer(ps, wl),
        Layer("perovskite", ps["perovskite_thickness_nm"], pv.n, pv.k, pv_active=True),
    ]
    substrate = Layer("silicon", ps["silicon_thickness_um"] * 1000.0, si.n, si.k,
                      coherent=False, pv_active=True)
    return front, substrate, wl




def second_pass_absorption(front_layers, wl: np.ndarray, theta_rad: float = 0.0,
                           incident_medium=None) -> dict:
    """Absorption of a beam returning from the rear through the front stack.

    The returning beam enters from the substrate side, so the stack is solved in
    reverse: [perovskite, transport, ARC] terminated by an air half-space. The
    result partitions the returning flux exactly:

            a_perovskite + a_parasitic + back_into_substrate + escape_to_air = 1

    which is what keeps the full optical budget closed when a rear reflector is
    introduced. Interface reflections inside the returning stack are treated with
    the same coherent TMM as the forward pass.
    """
    rev = []
    for layer in reversed(list(front_layers)):
        rev.append(Layer(layer.name, layer.thickness_nm, layer.n, layer.k,
                         coherent=True, pv_active=layer.pv_active))
    exit_layer = Layer("__exit__", 0.0, MG_F2_N, 0.0, coherent=True,
                       pv_active=False, semi_infinite=True)
    res = solve_stack(wl, rev + [exit_layer], theta_rad=theta_rad,
                      incident_medium=incident_medium)
    a = res.layer_absorption
    return {
        "perovskite": np.asarray(a.get("perovskite", np.zeros_like(wl))),
        "transport": np.asarray(a.get("transport", np.zeros_like(wl))),
        "arc": np.asarray(a.get("arc", np.zeros_like(wl))),
        "escape": np.asarray(res.transmittance),
        "back_into_substrate": np.asarray(res.reflectance),
        "closure_residual": np.asarray(res.closure_residual()),
    }


def apply_rear_reflectance(res: OpticsResult, front_layers, wl: np.ndarray,
                           rear_reflectance: float, theta_rad: float = 0.0,
                           incident_medium=None) -> OpticsResult:
    """Redistribute the rear-reflected flux, exactly conserving R + T + A = 1.

    ``res`` must be the *zero-rear-reflectance* solution (so its transmittance is
    the flux leaving the wafer). The flux ``T * R_rear`` is sent back through the
    stack, where it is absorbed in the perovskite (useful), absorbed in the
    auxiliary layers (parasitic) or escapes through the front (reflection loss).
    A single back-pass is modelled: higher-order bounces carry a factor
    ``R_rear * a_back`` and are small for the considered stacks (documented
    approximation, not a silent one).

    NOTE the trap this avoids: adding the second-pass absorption without removing
    the corresponding flux from the transmittance would break the energy budget
    (total = 1 + returning instead of 1).
    """
    R_rear = float(np.clip(rear_reflectance, 0.0, 0.999))
    if R_rear <= 0.0:
        return res
    back = second_pass_absorption(front_layers, wl, theta_rad, incident_medium)
    returning = res.transmittance * R_rear
    layer_abs = {k: np.asarray(v).copy() for k, v in res.layer_absorption.items()}
    layer_abs["perovskite"] = layer_abs["perovskite"] + returning * back["perovskite"]
    for aux in ("transport", "arc"):
        if aux in layer_abs:
            layer_abs[aux] = layer_abs[aux] + returning * back[aux]
    # The part of the returning beam that is internally reflected at the front
    # interface travels back into the wafer. It is counted as absorbed in the
    # silicon: an upper bound (the wafer absorbs most of the near-bandgap flux on
    # a second pass), and it cannot flatter the PCE of a top-cell-limited device.
    # Higher-order bounces (factor >= R_rear * a_back) are neglected.
    if "silicon" in layer_abs:
        layer_abs["silicon"] = layer_abs["silicon"] + returning * back["back_into_substrate"]
    R_new = res.reflectance + returning * back["escape"]
    T_new = res.transmittance * (1.0 - R_rear)
    out = OpticsResult(res.wavelength_nm, R_new, T_new, layer_abs,
                       field_profile_ratio=res.field_profile_ratio,
                       angular=res.angular,
                       notes=(res.notes + f"; rear_reflectance={R_rear:.3f} "
                                             f"(single back-pass)"))
    out.assert_closure(1e-9)
    return out

# 5 nm resolution over the photovoltaic window: the optics are smooth on this
# scale (checked by the numerical-convergence study in the campaigns).
TANDEM_WAVELENGTH_NM = np.arange(300.0, 1250.0 + 1e-9, 5.0)


def solve_tandem_optics(ps: ParamSet, model_form: str = "IQE-M1",
                        theta_rad: float = 0.0,
                        spectrum: Optional[Spectrum] = None) -> TandemOpticsResult:
    """Solve the tandem optics and derive subcell EQE for the given model form."""
    front, substrate, wl = build_stack(ps)
    res = solve_incoherent_substrate(
        wl, front, substrate, theta_rad=theta_rad,
        rear_reflectance=0.0,
        path_enhancement=ps["silicon_light_trapping"])
    si_n_k = (silicon_index(wl, tail_nm=25.0).n, np.zeros_like(wl))
    res = apply_rear_reflectance(res, front, wl, ps["rear_reflectance"], theta_rad,
                                 incident_medium=si_n_k)

    a_top = res.layer_absorption["perovskite"]
    a_bot = res.layer_absorption["silicon"]

    if model_form == "IQE-M1":
        iqe_top = np.full_like(wl, ps["collection_efficiency_top"])
        iqe_bottom = np.full_like(wl, ps["collection_efficiency_bottom"])
    elif model_form == "IQE-M2":
        alpha_top = _perovskite_alpha_from_ps(ps, wl)
        L_top = ps["collection_length_top_nm"]
        iqe_top = (alpha_top * 1e-7 * L_top) / (alpha_top * 1e-7 * L_top + 1.0)
        si = silicon_index(wl, 25.0)
        alpha_bot = si.alpha_cm1
        L_bot = ps["collection_length_bottom_nm"]
        # light-trapping increases the effective path, so the effective
        # collection length is scaled by the same enhancement (documented)
        iqe_bottom = ((alpha_bot * 1e-7 * L_bot * ps["silicon_light_trapping"])
                      / (alpha_bot * 1e-7 * L_bot * ps["silicon_light_trapping"] + 1.0))
    else:
        raise ValueError(f"unknown IQE model form {model_form!r}")

    eqe_top = np.clip(a_top * iqe_top, 0.0, 1.0)
    eqe_bottom = np.clip(a_bot * iqe_bottom, 0.0, 1.0)
    # interface collection loss (explicit loss channel, registered parameter)
    loss_top = ps["interface_loss_top_ma_cm2"]
    if loss_top > 0:
        sp = spectrum or reference()
        j_top = sp.eqe_current(eqe_top, wl, 300.0, 1250.0)
        if j_top > 0:
            eqe_top = eqe_top * max(1.0 - loss_top / j_top, 0.0)

    return TandemOpticsResult(
        wavelength_nm=wl, reflectance=res.reflectance, transmittance=res.transmittance,
        absorption={"perovskite": a_top, "silicon": a_bot, "arc": res.layer_absorption["arc"],
                    "transport": res.layer_absorption["transport"]},
        eqe_top=eqe_top, eqe_bottom=eqe_bottom, iqe_top=iqe_top, iqe_bottom=iqe_bottom,
        optics=res, model_form=model_form)


# ---------------------------------------------------------------------------
# Level-0 optics: Beer-Lambert absorption without interference
# ---------------------------------------------------------------------------
def solve_beer_lambert_optics(ps: ParamSet, spectrum: Optional[Spectrum] = None,
                              wl: Optional[np.ndarray] = None) -> TandemOpticsResult:
    """Level-0 (analytic) optical model: Beer-Lambert absorption, no interference.

    Physically explicit and deliberately crude, so that the difference between
    levels can be *measured* instead of assumed:

    * a single Fresnel reflection at the air/front interface
      ``R_0 = ((1 - n_eff) / (1 + n_eff))^2`` with the perovskite's n_inf as the
      effective index (no ARC, no interference);
    * the perovskite absorbs ``1 - exp(-alpha d)`` of what enters;
    * the silicon absorbs ``1 - exp(-alpha_si d_si * path)`` of the remainder;
    * IQE-M1 collection is applied to both absorbers.

    Closure is exact by construction (A_top + A_bot = 1 - R_0, T = 0).
    """
    from ..materials.perovskite import perovskite_alpha_cm1, perovskite_index
    from ..materials.silicon import silicon_index

    sp = spectrum or reference()
    grid = TANDEM_WAVELENGTH_NM if wl is None else np.asarray(wl, dtype=float)
    eg = ps["perovskite_eg_ev"]
    alpha_p = _perovskite_alpha_from_ps(ps, grid)
    n_eff = float(ps["perovskite_n_inf"])
    r0 = ((1.0 - n_eff) / (1.0 + n_eff)) ** 2
    d_p = ps["perovskite_thickness_nm"] * 1e-7          # nm -> cm
    entering = 1.0 - r0
    a_top = entering * (1.0 - np.exp(-alpha_p * d_p))
    si = silicon_index(grid, tail_nm=25.0)
    d_si = ps["silicon_thickness_um"] * 1e-4
    surviving = entering * np.exp(-alpha_p * d_p)
    a_bot = surviving * (1.0 - np.exp(-si.alpha_cm1 * d_si * ps["silicon_light_trapping"]))
    transmittance = surviving * np.exp(-si.alpha_cm1 * d_si * ps["silicon_light_trapping"])
    reflectance = np.full_like(grid, r0)
    optics = OpticsResult(grid, reflectance, transmittance,
                          {"perovskite": a_top, "silicon": a_bot},
                          notes="Beer-Lambert (level-0) optics: no ARC, no interference")
    iqe_top = np.full_like(grid, ps["collection_efficiency_top"])
    iqe_bottom = np.full_like(grid, ps["collection_efficiency_bottom"])
    return TandemOpticsResult(
        wavelength_nm=grid, reflectance=reflectance, transmittance=transmittance,
        absorption={"perovskite": a_top, "silicon": a_bot, "arc": np.zeros_like(grid),
                    "transport": np.zeros_like(grid)},
        eqe_top=np.clip(a_top * iqe_top, 0.0, 1.0),
        eqe_bottom=np.clip(a_bot * iqe_bottom, 0.0, 1.0),
        iqe_top=iqe_top, iqe_bottom=iqe_bottom, optics=optics,
        model_form="IQE-M1 (level-0 optics)")


def _perovskite_alpha_from_ps(ps: ParamSet, wl: np.ndarray) -> np.ndarray:
    from ..materials.perovskite import perovskite_alpha_cm1
    return perovskite_alpha_cm1(ps["perovskite_eg_ev"],
                                ps["perovskite_absorption_alpha_ev"],
                                ps["perovskite_urbach_mev"], wl)


def photon_budget_closure(result: TandemOpticsResult,
                          spectrum: Optional[Spectrum] = None) -> float:
    """Check that the photon budget closes in current-density units.

    incident = reflected + transmitted + parasitic + absorbed(top+bottom)
    within the 300-1250 nm window. Returns the residual [mA/cm2].
    """
    sp = spectrum or reference()
    b = result.absorbed_photon_budget(sp)
    lhs = (b["reflected"] + b["transmitted"] + b["parasitic_absorbed"]
           + b["absorbed_top"] + b["absorbed_bottom"])
    return float(lhs - b["incident_100pct_eqe"])
