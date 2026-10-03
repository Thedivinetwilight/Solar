"""APMT V1.9 — recombination models and the J0 budget.

Two physically distinct contributions to the dark saturation current are
computed *separately* and never merged (directive §5: radiative and
nonradiative recombination must be separable):

radiative  J0_rad
    From detailed balance:  J0_rad = (1/ERE) * q * Phi_emit(V=0, Eg, T)
    where the external radiative efficiency ERE = fraction of radiative
    recombination that escapes the device. ERE = 1 gives the radiative limit;
    the perovskite representative device (PLQY 0.02%, Fig. 5 of the source)
    sets ERE = 2e-4 for that device class. ERE is a registered parameter with
    EXPLORATORY range classification, because the champion's ERE is not
    published.

nonradiative  J0_SRH
    From Shockley-Read-Hall recombination in a slab of thickness W with
    effective lifetime tau and doping N:
        J0_SRH = q n_i(T)^2 [ W/(tau N) + S_eff/N ]
    with the temperature scaling
        n_i(T)^2 ~ T^3 exp(-Eg(T)/kT).

Ideality: the SRH term carries its own ideality factor n_id (registered), the
radiative term is unity-ideality by construction. This gives the two-diode
form used by the subcell model:

    J(V) = Jph - J0_rad (exp(V/kT) - 1) - J0_SRH (exp(V/(n_id kT)) - 1)

All quantities are in mA/cm2 (current density) and V.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.constants import K_B_EV_K, Q_C
from ..materials.silicon import intrinsic_carrier_density_cm3


@dataclass(frozen=True)
class J0Budget:
    """Dark saturation current split, with the inputs that created it."""

    j0_radiative_ma_cm2: float
    j0_srh_ma_cm2: float
    j0_total_ma_cm2: float
    ere: float
    ideality_srh: float
    temperature_k: float
    detail: dict

    def to_dict(self) -> dict:
        return {
            "j0_radiative_ma_cm2": self.j0_radiative_ma_cm2,
            "j0_srh_ma_cm2": self.j0_srh_ma_cm2,
            "j0_total_ma_cm2": self.j0_total_ma_cm2,
            "radiative_fraction": (self.j0_radiative_ma_cm2 / self.j0_total_ma_cm2
                                   if self.j0_total_ma_cm2 > 0 else float("nan")),
            "ere": self.ere,
            "ideality_srh": self.ideality_srh,
            "temperature_k": self.temperature_k,
            "detail": self.detail,
        }


def radiative_j0_ma_cm2(eg_ev: float, temperature_k: float,
                        emissive_solid_angle_fraction: float = 1.0,
                        n_points: int = 3000, e_max_ev: float = 4.5) -> float:
    """Radiative saturation current density [mA/cm2] from generalized Planck.

    J0_rad = q * Phi_emit(V = 0) with emission into one hemisphere, times the
    fraction of the hemisphere the cell can actually emit into (1.0 for a bare
    cell; a fraction < 1 models external confinement, which lowers J0_rad).
    """
    from .detailed_balance import blackbody_photon_flux_hemisphere
    from ..core.numerics import trapz
    e_lo = max(eg_ev, 1e-3)
    E = np.linspace(e_lo, max(e_max_ev, e_lo + 1.0), n_points)
    flux = blackbody_photon_flux_hemisphere(E, temperature_k, 0.0)
    ph = trapz(flux, E) * emissive_solid_angle_fraction
    return 0.1 * Q_C * ph * 1e3   # A/m2 -> mA/cm2  (0.1 * Q_C already is mA/cm2)


def j0_from_ere(eg_ev: float, temperature_k: float, ere: float) -> float:
    """Radiative J0 corrected for a finite external radiative efficiency.

    ERE < 1 means most radiative recombination remains internal, so the
    *effective* radiative loss channel is larger by 1/ERE. ERE = 1 returns the
    radiative limit.
    """
    if not (0.0 < ere <= 1.0):
        raise ValueError("ERE must be in (0, 1]")
    return radiative_j0_ma_cm2(eg_ev, temperature_k) / ere


def j0_srh_slab_ma_cm2(temperature_k: float, eg_ev: float, thickness_cm: float,
                       lifetime_s: float, doping_cm3: float,
                       surface_recombination_cm_s: float,
                       ref_temperature_k: float = 298.15,
                       ref_eg_ev: float | None = None) -> float:
    """SRH+surface saturation current density [mA/cm2] of a semiconductor slab."""
    if thickness_cm <= 0 or lifetime_s <= 0 or doping_cm3 <= 0:
        raise ValueError("thickness, lifetime and doping must be positive")
    ni2 = intrinsic_carrier_density_cm3(temperature_k, eg_ev) ** 2
    j0_a_cm2 = Q_C * ni2 * (thickness_cm / (lifetime_s * doping_cm3)
                            + surface_recombination_cm_s / doping_cm3)
    return j0_a_cm2 * 1e3     # A/cm2 -> mA/cm2


def j0_srh_temperature_scaled(j0_ref_ma_cm2: float, temperature_k: float,
                              reference_temperature_k: float, eg_ev_at_t: float,
                              eg_ev_at_ref: float, ideality: float,
                              temperature_exponent: float = 3.0) -> float:
    """Scale a reference-temperature SRH J0 with temperature.

    J0(T) = J0(T_ref) (T/T_ref)^gamma exp( -(Eg(T))/(n k T)
                                          + (Eg(T_ref))/(n k T_ref) )
    """
    kT = K_B_EV_K * temperature_k
    kTr = K_B_EV_K * reference_temperature_k
    exponent = (-eg_ev_at_t / (ideality * kT) + eg_ev_at_ref / (ideality * kTr))
    if exponent > 300:
        raise ValueError("SRH temperature scaling overflow: check Eg/ideality units")
    return float(j0_ref_ma_cm2 * (temperature_k / reference_temperature_k) ** temperature_exponent
                 * np.exp(exponent))


def j0_budget(eg_ev: float, temperature_k: float, ere: float, ideality_srh: float,
              thickness_cm: float | None = None, lifetime_s: float | None = None,
              doping_cm3: float = 1.0e16, srv_cm_s: float = 10.0,
              j0_srh_override_ma_cm2: float | None = None) -> J0Budget:
    """Assemble the two-term J0 budget for one subcell.

    If ``j0_srh_override_ma_cm2`` is given it is used directly (e.g. a value
    fitted to measured subcell V_oc); otherwise the slab model is used. The
    provenance of the chosen route is recorded in ``detail``.
    """
    j0_rad = j0_from_ere(eg_ev, temperature_k, ere)
    if j0_srh_override_ma_cm2 is not None:
        j0_srh = float(j0_srh_override_ma_cm2)
        route = "override (fitted/source-constrained value)"
    else:
        if thickness_cm is None or lifetime_s is None:
            raise ValueError("provide thickness/lifetime or an explicit J0_SRH override")
        j0_srh = j0_srh_slab_ma_cm2(temperature_k, eg_ev, thickness_cm, lifetime_s,
                                    doping_cm3, srv_cm_s)
        route = "slab SRH+surface model"
    return J0Budget(j0_rad, j0_srh, j0_rad + j0_srh, ere, ideality_srh, temperature_k,
                    {"srh_route": route, "doping_cm3": doping_cm3,
                     "srv_cm_s": srv_cm_s, "thickness_cm": thickness_cm,
                     "lifetime_s": lifetime_s})
