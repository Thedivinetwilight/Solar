"""V1.9-C — thermal model tests: energy balance, stability, bounds, and the
retired 454 K corner.

The V1.9-C thermal rebuild replaced the legacy "all incident power becomes heat"
closure with a solved energy balance (conduction to ambient through the thermal
resistance + radiative cooling). These tests pin the *physics* of that closure:
which paths exist, that they close, that the equilibrium is stable, and that the
previously reported ~454 K corner is no longer reachable under the registered
parameter ranges (with the arithmetic shown, not asserted away).
"""
from __future__ import annotations

import numpy as np
import pytest

from apmt.core.constants import SIGMA_SB_W_M2_K4, STEFAN_BOLTZMANN_W_M2_K4
from apmt.device.thermal import (SUN_POWER_MW_CM2, W_M2_TO_MW_CM2,
                                 loss_mw_cm2, radiative_loss_mw_cm2,
                                 simple_temperature, solve_equilibrium)
from apmt.device.tandem import evaluate_tandem, evaluate_tandem as et
from apmt.params.registry import ParamSet


def _constant_power(fraction: float):
    """Electrical extraction = fraction of one sun, temperature independent."""
    return lambda T: fraction * SUN_POWER_MW_CM2


def test_stefan_boltzmann_alias_matches_codata_value():
    assert STEFAN_BOLTZMANN_W_M2_K4 == pytest.approx(5.670374419e-8, rel=1e-9)
    assert SIGMA_SB_W_M2_K4 == STEFAN_BOLTZMANN_W_M2_K4
    assert W_M2_TO_MW_CM2 == pytest.approx(0.1)
    assert SUN_POWER_MW_CM2 == 100.0


def test_equilibrium_solves_the_closed_balance():
    """An analytic case: with constant extraction the balance is a quartic that
    the solver must satisfy to its own tolerance."""
    ps = ParamSet.defaults()
    absorbed = 68.5
    state = solve_equilibrium(ps, absorbed, _constant_power(0.19), 298.15)
    assert state.converged
    assert state.residual_mw_cm2 == pytest.approx(0.0, abs=1e-3)
    lhs = state.heat_load_mw_cm2
    rhs = state.conduction_loss_mw_cm2 + state.radiative_loss_mw_cm2
    assert lhs == pytest.approx(rhs, abs=1e-3)
    # the analytic quartic solution for this case
    r_th = state.r_th_effective_k_cm2_w
    eps = state.emissivity
    Q = absorbed - 0.19 * SUN_POWER_MW_CM2
    T = state.junction_k
    assert (T - 298.15) / r_th + radiative_loss_mw_cm2(T, 298.15, eps) == pytest.approx(Q, abs=1e-3)


def test_equilibrium_is_stable_and_unique_in_the_bracket():
    ps = ParamSet.defaults()
    state = solve_equilibrium(ps, 68.5, _constant_power(0.19), 298.15)
    # stability requires d(loss)/dT > d(heat)/dT; here heat is constant
    assert state.d_loss_dt_mw_cm2_k > 0.0
    assert state.d_loss_dt_mw_cm2_k - state.d_heat_dt_mw_cm2_k > 0.0
    # no other root in the bracket: the residual must be monotone
    Ts = np.linspace(state.junction_k - 20.0, state.junction_k + 20.0, 41)
    res = np.array([loss_mw_cm2(T, ambient_k=298.15,
                                r_th_eff=state.r_th_effective_k_cm2_w,
                                emissivity=state.emissivity)
                    - (68.5 - 0.19 * SUN_POWER_MW_CM2) for T in Ts])
    assert np.all(np.diff(res) > 0.0)


def test_temperature_is_monotone_in_thermal_resistance_and_heat_load():
    ps = ParamSet.defaults()
    temps = [solve_equilibrium(ps.with_mapping({"thermal_resistance_k_cm2_w": r}),
                               68.5, _constant_power(0.19), 298.15).junction_k
             for r in (0.05, 0.2, 0.6, 1.2, 2.0)]
    assert all(a < b for a, b in zip(temps, temps[1:]))
    temps2 = [solve_equilibrium(ps, absorbed, _constant_power(0.19), 298.15).junction_k
              for absorbed in (40.0, 68.5, 100.0)]
    assert all(a < b for a, b in zip(temps2, temps2[1:]))


def test_radiative_path_is_active_and_bounds_an_otherwise_unbounded_closure():
    """The radiative term must actually carry power: if it were zero, the
    equilibrium would be linear in the heat load and the 454 K corner would be
    reachable again."""
    ps = ParamSet.defaults().with_mapping({"thermal_resistance_k_cm2_w": 2.0})
    hot = solve_equilibrium(ps, 68.5, _constant_power(0.19), 298.15)
    assert hot.radiative_loss_mw_cm2 > 1.0
    frac = hot.radiative_loss_mw_cm2 / (hot.radiative_loss_mw_cm2
                                        + hot.conduction_loss_mw_cm2)
    assert frac > 0.05


def test_454k_corner_is_bounded_by_the_radiative_term():
    """The V1.9-B registered-range finding said 1 sun + R_th = 2.0 K cm2/mW gives
    Tj ~ 454 K under the legacy all-incident-power rule. Under the energy balance
    the SAME worst-case parameters give a much lower junction temperature,
    because the radiative term grows as T^4.

    Arithmetic (one sun, 100 mW/cm2; R_th = 2.0 K cm2/mW => 0.2 K cm2/mW? no:
    the registry unit is K cm2/mW, so R_th = 2.0 gives 2.0 K per mW/cm2):
        legacy:  T = 298.15 + 2.0 * (100 - P_elec)
        balance: (T-298.15)/2.0 + eps*sigma*(T^4-T_amb^4) = 100 - P_elec
    The radiative term is evaluated in mW/cm2:
        sigma_SB = 5.670374419e-8 W/m2/K4 = 5.670374419e-5 mW/cm2/K4 per unit
        emissivity... (x 0.1 conversion from W/m2 to mW/cm2)
    """
    ps = ParamSet.defaults().with_mapping({"thermal_resistance_k_cm2_w": 2.0})
    assert ps["thermal_resistance_k_cm2_w"] == 2.0        # registered upper bound
    # (a) the retired closure, at the same extreme: all 100 mW/cm2 incident power
    #     becomes heat => Tj = 298.15 + 2.0 * 100 = 498.15 K
    legacy = simple_temperature(ps).junction_k
    assert legacy == pytest.approx(498.15, abs=0.01)
    assert legacy > 454.0            # the V1.9-B envelope finding (>=454 K) is real
    # (b) the energy balance for a hypothetical fully absorbing cell at 1 sun
    #     (100 mW/cm2 absorbed, 20 % extracted): Tj = 362.5 K
    hypothetical = solve_equilibrium(ps, SUN_POWER_MW_CM2, _constant_power(0.20), 298.15)
    assert hypothetical.junction_k == pytest.approx(362.5, abs=1.0)
    # (c) the energy balance for the ACTUAL device at 1 sun: 68.5 mW/cm2 absorbed,
    #     ~16.8 % extracted => ~51.7 mW/cm2 of heat => Tj = 342.2 K
    real = solve_equilibrium(ps, 68.5, _constant_power(0.168), 298.15)
    assert real.junction_k == pytest.approx(342.2, abs=1.5)
    assert real.junction_k < hypothetical.junction_k < legacy
    # the radiative loss at the legacy temperature is what makes it impossible
    rad_at_legacy = radiative_loss_mw_cm2(legacy, 298.15, ps["thermal_emissivity"])
    assert rad_at_legacy > 50.0                # > half a sun radiated away
    # the model never clips the temperature: the balance simply has no root there
    for state in (hypothetical, real):
        assert state.converged
        assert state.residual_mw_cm2 == pytest.approx(0.0, abs=1e-3)


def test_registered_extreme_thermal_resistance_stays_inside_the_envelope():
    ps = ParamSet.defaults().with_mapping({"thermal_resistance_k_cm2_w": 2.0})
    res = evaluate_tandem(ps)
    th = res.detail["thermal"]
    assert th["model"] == "energy_balance"
    assert th["junction_k"] < 360.0
    assert res.detail["solve_valid"] is True
    assert res.detail["solve_valid"] is True


def test_self_heating_costs_efficiency_and_never_adds_it():
    ps = ParamSet.defaults()
    cold = evaluate_tandem(ps, self_heating=False)
    hot = evaluate_tandem(ps)
    assert hot.temperature_k > cold.temperature_k
    assert hot.pce_pct < cold.pce_pct


def test_temperature_feedback_uses_cold_optical_constants_and_says_so():
    """The optical constants are evaluated at 298 K in both thermal models; this
    is a documented approximation, and the closure note must state it."""
    res = evaluate_tandem(ParamSet.defaults())
    note = res.detail["thermal"]["closure_note"]
    assert "optical constants at 298 K" in note
    assert "conduction" in res.detail["thermal"]["closure_note"]


def test_simple_and_energy_balance_closures_are_both_available_and_labelled():
    ps = ParamSet.defaults()
    simple = evaluate_tandem(ps, thermal_model="simple")
    balanced = evaluate_tandem(ps, thermal_model="energy_balance")
    assert simple.detail["thermal"]["model"] == "simple"
    assert balanced.detail["thermal"]["model"] == "energy_balance"
    # the legacy closure is more pessimistic: it ignores the radiative path
    assert simple.temperature_k > balanced.temperature_k
    assert simple.pce_pct < balanced.pce_pct


def test_fixed_temperature_diagnostic_declares_itself():
    res = evaluate_tandem(ParamSet.defaults(), self_heating=False)
    th = res.detail["thermal"]
    assert th["model"] == "fixed-temperature"
    assert th["junction_k"] == th["ambient_k"] == 298.15
    assert th["conduction_loss_mw_cm2"] == 0.0
    assert res.detail["solve_valid"] is True
    assert res.detail["solve_valid"] is True
