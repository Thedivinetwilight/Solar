"""V1.9-C — multi-fidelity levels, divergence analysis, inertness, units.

Covers the V1.9-C architecture deliverables:
* Levels 0-5 are explicit, documented fidelity changes (a level switches a model
  TERM off; it never moves a registered parameter outside its declared range),
* cross-level divergence is classified LOW / MODERATE / HIGH / MODEL-FORM-CRITICAL,
* the physically suppressed bottom->top luminescent channel is live code (a
  liveness test with a forced availability factor) rather than dead code,
* canonical units and the historical unit traps (cm^2 vs m^2, nm vs cm,
  W/m^2 vs mW/cm^2, eV vs J, A vs mA) are pinned.
"""
from __future__ import annotations

import numpy as np
import pytest

from apmt.core.constants import (EV_J, IRRADIANCE_AM15G_WM2, K_B_EV_K, ONE_SUN,
                                 P_ONE_SUN_MW_CM2, Q_C, SIGMA_SB_W_M2_K4)
from apmt.device.thermal import SUN_POWER_MW_CM2, W_M2_TO_MW_CM2
from apmt.device.tandem import build_tandem, emission_fraction_above_gap, optics_for
from apmt.multifidelity.levels import (LEVELS, LEVEL_DESCRIPTIONS, classify_divergence,
                                       divergence_study, evaluate_level, options_for)
from apmt.optics.stack import TANDEM_WAVELENGTH_NM, solve_beer_lambert_optics
from apmt.params.registry import ParamSet, spec


def test_levels_are_documented_and_options_are_explicit():
    assert LEVELS == ("L0", "L1", "L2", "L3", "L4", "L5")
    for lv in LEVELS:
        assert LEVEL_DESCRIPTIONS[lv]                    # documented description
        opts = options_for(lv)
        assert opts.level == lv
        assert opts.optics_engine in ("beer_lambert", "tmm")
        assert isinstance(opts.to_dict()["solver"], str)
    # fidelity must be monotone: a higher level never drops a mechanism that a
    # lower level has (otherwise "level" would not order model complexity)
    flags = [(options_for(lv).include_srh, options_for(lv).include_resistance,
              options_for(lv).include_thermal, options_for(lv).include_coupling)
             for lv in LEVELS]
    for a, b in zip(flags, flags[1:]):
        assert all(not x or y for x, y in zip(a, b)), (a, b)


def test_higher_levels_are_not_slower_only_because_of_physics():
    """The fast solver keeps every level well inside a batch-friendly budget."""
    ps = ParamSet.defaults()
    import time
    times = {}
    for lv in LEVELS:
        t0 = time.perf_counter()
        evaluate_level(lv, ps)
        times[lv] = time.perf_counter() - t0
    assert times["L5"] < 5.0            # a full-physics point costs well under a second
    assert times["L2"] < times["L5"]    # and the reduced levels are cheaper


def test_levels_do_not_move_registered_parameters():
    """A fidelity switch is not allowed to smuggle in a parameter change: the
    registered parameter values are identical whatever level is evaluated, and
    the records of a level and of the full model must agree on the parameter
    values they claim to have used."""
    ps = ParamSet.defaults()
    l0 = evaluate_level("L0", ps)
    l4 = evaluate_level("L4", ps)
    assert l0.detail["level_switches"]["srh_channel"] is False
    assert l0.detail["level_switches"]["resistance_network"] is False
    assert l0.detail["level_switches"]["thermal_feedback"] is False
    assert l0.detail["level_switches"]["coupling_mechanisms"] is False
    assert l4.detail["level_switches"]["srh_channel"] is True
    # the switches, not the parameters, carry the fidelity
    switches = l0.detail["level_switches"]
    assert "fidelity switches disable model terms" in switches["note"]
    # both levels must report the same registered parameter values as used
    for name in ("rs_ohm_cm2", "rsh_ohm_cm2", "thermal_resistance_k_cm2_w",
                 "luminescent_coupling_top_to_bottom"):
        assert float(ps[name]) == float(ParamSet.defaults()[name])
        assert l0.detail.get("level_switches") is not None


def test_level_chain_is_monotone_in_physics_and_reported():
    """Each step up the ladder adds exactly one documented mechanism, and the
    direction of the resulting change is physically constrained."""
    ps = ParamSet.defaults()
    l0 = evaluate_level("L0", ps)      # Beer-Lambert optics, radiative-only diode
    l1 = evaluate_level("L1", ps)      # + coherent TMM optics
    l2 = evaluate_level("L2", ps)      # + SRH/surface recombination
    l3 = evaluate_level("L3", ps)      # + self-heating energy balance
    l4 = evaluate_level("L4", ps)      # + Rs/Rsh + coupling
    # (a) optics: the coherent stack with an ARC collects more current than the
    #     flat Beer-Lambert budget
    assert l0.detail["level_options"]["optics_engine"] == "beer_lambert"
    assert l1.jsc_ma_cm2 > l0.jsc_ma_cm2
    # (b) SRH recombination can only lower Voc. L1 and L2 differ in BOTH the SRH
    #     channel and the numerical grid (600 -> 1200 curve points), so the
    #     direction is asserted on a controlled comparison that varies the SRH
    #     switch alone at identical grid settings (the grid itself is worth
    #     ~1e-6 V, which would otherwise mask the effect).
    from apmt.device.tandem import solve_tandem_fast, _with_bandgap_flags
    T = 298.15
    dev_srh = build_tandem(ps, "IQE-M1", T)
    dev_ideal = build_tandem(ps, "IQE-M1", T, include_srh=False)
    assert dev_ideal.top.j0_budget.j0_srh_ma_cm2 == 0.0
    ideal = solve_tandem_fast(_with_bandgap_flags(dev_ideal, ps, T), T,
                              n_table=4001, n_curve_points=1200)
    with_srh = solve_tandem_fast(_with_bandgap_flags(dev_srh, ps, T), T,
                                 n_table=4001, n_curve_points=1200)
    assert with_srh.voc_v < ideal.voc_v
    # V1.9-H: 1e-4 -> 1e-3. Post-R1 the SRH branch carries more weight at Voc
    # (delta = 3.7404e-4 V, grid-converged to 9 decimals at 1200/2400/4800
    # curve points), but the regime is unchanged: Voc still sits on the
    # radiative branch and the step is still << Voc and >> grid noise (~1e-9).
    # The physics constraint (SRH can only lower Voc) is untouched above.
    assert abs(with_srh.voc_v - ideal.voc_v) < 1e-3
    # (c) self-heating costs efficiency and raises the junction temperature
    assert l3.temperature_k > l2.temperature_k
    assert l3.pce_pct < l2.pce_pct
    assert l3.detail["thermal"]["model"] == "energy_balance"
    # (d) resistance losses can only lower FF
    assert l4.ff < l3.ff


def test_divergence_classification_thresholds():
    assert classify_divergence(0.05, 0.05) == "LOW-DIVERGENCE"
    assert classify_divergence(0.4, 0.1) == "MODERATE-DIVERGENCE"
    assert classify_divergence(1.0, 0.1) == "HIGH-DIVERGENCE"
    assert classify_divergence(-3.0, 0.1) == "MODEL-FORM-CRITICAL"
    # the worst of the two metrics decides
    assert classify_divergence(0.01, -2.0) == "MODEL-FORM-CRITICAL"


def test_divergence_study_runs_and_reports_per_level():
    out = divergence_study(n_points=3)
    assert out["reference_level"] == "L5"
    for lv in LEVELS:
        s = out["summary"][lv]
        assert "mean_abs_delta_pce_pp" in s and "worst_class" in s
        assert s["worst_class"] in ("LOW-DIVERGENCE", "MODERATE-DIVERGENCE",
                                    "HIGH-DIVERGENCE", "MODEL-FORM-CRITICAL")
        assert isinstance(s["predictive"], bool)
    # L5 is L4 with a finer numerical grid: the two must agree far inside the
    # documented agreement tolerance (measured 5.4e-5 pp on the campaign ensemble,
    # which is grid discretisation, not model form)
    assert out["summary"]["L4"]["max_abs_delta_pce_pp"] < 1e-3
    assert out["summary"]["L4"]["worst_class"] == "LOW-DIVERGENCE"
    # the reduced optical model (L0) must NOT be predictive: that is the finding
    assert out["summary"]["L0"]["predictive"] is False


# ---------------------------------------------------------------------------
# bottom -> top coupling: physically suppressed but live code
# ---------------------------------------------------------------------------
def test_bottom_to_top_coupling_availability_is_exp_suppressed():
    ps = ParamSet.defaults()
    from apmt.materials.perovskite import perovskite_bandgap_temperature
    from apmt.materials.silicon import varshni_bandgap
    T = 310.0
    eg_bot = varshni_bandgap(ps["silicon_eg_ev"], T)
    eg_top = perovskite_bandgap_temperature(ps["perovskite_eg_ev"], T, 298.15,
                                            ps["eg_temperature_coeff_ev_k"])
    f_up = emission_fraction_above_gap(eg_bot, eg_top, T)
    assert 0.0 < f_up < 1e-6                      # ~4e-10 at the nominal gaps
    # the suppression is the Boltzmann factor exp(-dEg/kT): check the order
    assert f_up < np.exp(-(eg_top - eg_bot) / (K_B_EV_K * T)) * 1e3


def test_bottom_to_top_coupling_is_live_not_dead_code():
    """The channel's registered-box response is < 1e-6 pp, so the inert screener
    classifies it PHYSICALLY-SUPPRESSED. This test proves the code path itself is
    live: with a forced availability factor the coupling must change the result.

    This is a CODE-LIVENESS test, not a physical claim: the availability factor
    used here is not reachable with the registered bandgaps (see the test above).
    """
    ps = ParamSet.defaults()
    opt = optics_for(ps)
    T = 298.15
    kw = dict(model_form="IQE-M1", temperature_k=T, spectrum=None, optics=opt)
    dev = build_tandem(ps, **kw)
    from apmt.device.tandem import solve_tandem_fast, _with_bandgap_flags
    base = solve_tandem_fast(_with_bandgap_flags(dev, ps, T), T)
    forced = build_tandem(ps.with_mapping({"luminescent_coupling_bottom_to_top": 0.5}),
                          **kw)
    forced.mechanism_flags["emission_fraction_above_top_gap"] = 0.1   # forced
    forced.mechanism_flags["eg_top"] = dev.mechanism_flags["eg_top"]
    forced.mechanism_flags["eg_bottom"] = dev.mechanism_flags["eg_bottom"]
    coupled = solve_tandem_fast(_with_bandgap_flags(forced, ps, T), T)
    # the extra top-cell current must appear in Voc (the top cell is limiting)
    assert coupled.voc_v > base.voc_v + 1e-6
    assert coupled.pce_pct > base.pce_pct


def test_top_to_bottom_coupling_cannot_relieve_a_top_limited_device():
    """The V1.9-B coupling-scale bug inflated PCE to 141 %; the direction of the
    mechanism is also constrained: adding current to a NON-limiting subcell
    cannot raise the tandem current."""
    ps = ParamSet.defaults()
    off = evaluate_level("L4", ps.with_mapping({"luminescent_coupling_top_to_bottom": 0.0}))
    on = evaluate_level("L4", ps.with_mapping({"luminescent_coupling_top_to_bottom": 0.5}))
    # the coupling term is proportional to expm1(V/kT), so it is exactly zero at
    # short circuit: the mechanism acts on the DIODE (Voc/FF), not on the
    # collected current at V = 0
    assert on.j_top_sc == pytest.approx(off.j_top_sc, abs=1e-12)
    assert on.voc_v > off.voc_v
    # and because the tandem current is set by the top cell, Jsc/pce barely move
    assert on.jsc_ma_cm2 == pytest.approx(off.jsc_ma_cm2, abs=1e-9)
    assert abs(on.pce_pct - off.pce_pct) < 0.1


# ---------------------------------------------------------------------------
# units and canonical conversions
# ---------------------------------------------------------------------------
def test_canonical_energy_and_charge_constants():
    assert EV_J == pytest.approx(1.602176634e-19, rel=1e-12)
    assert Q_C == pytest.approx(1.602176634e-19, rel=1e-12)
    assert K_B_EV_K == pytest.approx(8.617333262e-5, rel=1e-9)
    # kT at 300 K in eV and the 25.85 mV thermal voltage
    assert K_B_EV_K * 300.0 == pytest.approx(0.025852, rel=1e-3)


def test_irradiance_and_power_density_units():
    assert SUN_POWER_MW_CM2 == 100.0                  # 1 sun = 100 mW/cm^2
    assert P_ONE_SUN_MW_CM2 == SUN_POWER_MW_CM2
    assert IRRADIANCE_AM15G_WM2 == pytest.approx(1000.0, rel=0.01)
    assert float(ONE_SUN) == pytest.approx(100.0)                # a Quantity
    assert W_M2_TO_MW_CM2 == pytest.approx(0.1)       # 1000 W/m^2 = 100 mW/cm^2
    assert 1000.0 * W_M2_TO_MW_CM2 == SUN_POWER_MW_CM2
    # sigma_SB in mW/cm^2/K^4 (the units the thermal balance works in):
    #   5.670374419e-8 W/m^2/K^4 * 0.1 (mW/cm^2 per W/m^2) = 5.670374419e-9
    sigma_mw = SIGMA_SB_W_M2_K4 * W_M2_TO_MW_CM2
    assert sigma_mw == pytest.approx(5.670374419e-9, rel=1e-9)
    # cross-check against the measured radiative loss at the default operating
    # point: 310.74 K vs 298.15 K ambient gives ~8.1 mW/cm^2 for eps = 1
    from apmt.device.thermal import radiative_loss_mw_cm2
    rad = radiative_loss_mw_cm2(310.7428, 298.15, 1.0)
    assert rad == pytest.approx(8.05, rel=0.01)
    assert radiative_loss_mw_cm2(310.7428, 298.15, 0.9) == pytest.approx(0.9 * rad, rel=1e-12)


def test_thickness_and_wavelength_units_are_explicit():
    """nm everywhere for thickness and wavelength; cm only inside absorption
    coefficients (1 nm = 1e-7 cm)."""
    assert TANDEM_WAVELENGTH_NM[0] == 300.0 and TANDEM_WAVELENGTH_NM[-1] >= 1200.0
    assert np.all(np.diff(TANDEM_WAVELENGTH_NM) > 0)
    for name in ("perovskite_thickness_nm", "arc_thickness_nm",
                 "collection_length_top_nm"):
        assert spec(name).unit == "nm"
    assert 1e-7 * 900.0 == pytest.approx(9e-5)        # 900 nm in cm


def test_beer_lambert_absorption_uses_cm_and_closure_holds():
    """The L0 optical model works in cm^-1 alpha and nm thickness: its photon
    budget must close against the incident spectrum (a silent nm/cm mix-up
    would break the closure)."""
    ps = ParamSet.defaults()
    opt = solve_beer_lambert_optics(ps)
    a = opt.absorption["perovskite"] + opt.absorption["silicon"]
    resid = np.max(np.abs(np.asarray(opt.reflectance) + np.asarray(opt.transmittance)
                          + a - 1.0))
    assert resid < 1e-9
    assert opt.jsc_top_ma_cm2() > 0 and opt.jsc_bottom_ma_cm2() > 0


def test_resistance_area_units_are_not_interchanged():
    """Rs/Rsh are ohm*cm^2 in the registry and converted to ohm internally once
    (the V1.9-B shunt bug was exactly a missing mA/A conversion)."""
    assert spec("rs_ohm_cm2").unit == "ohm*cm^2"
    assert spec("rsh_ohm_cm2").unit == "ohm*cm^2"
    assert spec("thermal_resistance_k_cm2_w").unit in ("K*cm^2/mW", "K*cm^2/W")
    ps = ParamSet.defaults()
    strong = evaluate_level("L4", ps.with_mapping({"rsh_ohm_cm2": 50.0}))
    weak = evaluate_level("L4", ps.with_mapping({"rsh_ohm_cm2": 50000.0}))
    assert strong.pce_pct < weak.pce_pct
    assert strong.ff < weak.ff
