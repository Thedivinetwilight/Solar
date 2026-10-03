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
from .tmm import Layer, OpticsResult, solve_incoherent_substrate

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
