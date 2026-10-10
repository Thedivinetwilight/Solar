"""V1.9-A/B regression + invariant tests for the optics and tandem layers.

Every number asserted here is a *pin* of the current model under the current
registry defaults. When a physics change moves a pin, the change must be
recorded in reports/APMT_MASSIVE_RND_PROGRESS_REPORT.md and the pin updated
deliberately -- a silent move is a regression-test failure by design.
"""
import numpy as np
import pytest

from apmt.device.tandem import evaluate_tandem
from apmt.params.registry import ParamSet
from apmt.optics.stack import photon_budget_closure, solve_tandem_optics, transport_layer_k
from apmt.validation.invariants import (
    InvariantViolation,
    check_invariants,
    check_optical_closure,
    check_photon_budget,
    check_quantum_efficiency_bounds,
)


def test_optical_closure_is_exact_and_budget_closes():
    r = solve_tandem_optics(ParamSet.defaults())
    resid = np.max(np.abs(r.reflectance + r.transmittance
                          + r.optics.total_absorption - 1.0))
    assert resid < 1e-12
    assert abs(photon_budget_closure(r)) < 1e-9
    assert np.all(r.eqe_top >= 0) and np.all(r.eqe_top <= 1)
    assert np.all(r.eqe_bottom >= 0) and np.all(r.eqe_bottom <= 1)


def test_tco_absorption_shape_is_physical():
    """Free-carrier term rises towards the IR; UV term decays with wavelength."""
    ps = ParamSet.defaults()
    k = transport_layer_k(ps, np.array([300.0, 600.0, 1000.0, 1200.0]))
    assert k[0] > k[1] > 0.0          # UV absorption dominates at 300 nm
    assert k[3] > k[2]                # free-carrier term rises with lambda^2
    assert np.all(k >= 0.0)


def test_tandem_baseline_regression_pin():
    """Registry-default twin, model form IQE-M1.

    Pin history (documented moves are allowed, silent ones are not):

    * 2026-10-03 V1.9-B1  PCE 20.8508  (before the shunt unit fix)
    * 2026-10-03 V1.9-B3  PCE 20.2412  (shunt conversion bug fixed: the Rsh
      term applied no mA<->A conversion and was numerically inert; the fix
      *lowers* the efficiency, so it is not a PCE-chasing change)
    * 2026-10-04 V1.9-C   PCE 20.2417 (+0.0005 pp, the fast vectorised solver;
      agreement with the reference oracle is asserted separately in
      tests/test_v19_engine.py to 1e-4 pp). Jsc moved 15.6141 -> 15.7266
      because the reported Jsc is now the CURRENT-SOURCE LIMIT
      min(J_top_sc, J_bot_sc) instead of a linear interpolation of a
      near-vertical J(V) curve at V = 0 (the previous value was an artefact of
      that ill-conditioned intersection; the curve value is still reported as
      jsc_conditioning_gap_ma_cm2). FF moved 0.8567 -> 0.8507 for the same
      reason: the maximum-power point is now taken from the same common-current
      representation as the reference solver.
    * 2026-10-04 V1.9-C   self-heated PCE moved 17.9082 -> 19.2633 because the
      thermal closure was rebuilt from the legacy "all incident power becomes
      heat" rule to an energy balance (conduction + radiative cooling to
      ambient); dT 30.0 -> 12.6 K. This is a physics change, documented in the
      V1.9-C report section, not a tolerance relaxation.
    * 2026-10-10 V1.9-H   PCE 20.2417 -> 24.9007, Voc 1.5130 -> 1.8669
      (+0.354 V = 2 cells x kT*ln(1000), exactly the R1 signature: J0_rad was
      1000x too large). Jsc 15.7266 -> 15.4228 (U1 removed the spurious e-fold
      absorption hump at the perovskite edge; the bottom gains the transmitted
      light, 19.8030 -> 20.0932). dT 12.59 -> 11.33 K (higher P_elec leaves
      less heat). The jsc_bias_sensitivity pin (393.2) is REPLACED by NaN +
      bracketed=False (J-sens: the old value was a bisection-midpoint
      artifact, j_hi/0.04). Historical values preserved in git + report.
    """
    ps = ParamSet.defaults()
    # (a) fixed-temperature diagnostic (no self-heating)
    o = evaluate_tandem(ps, self_heating=False)
    assert o.pce_pct == pytest.approx(24.9007, abs=0.002)
    assert o.jsc_ma_cm2 == pytest.approx(15.4228, abs=0.002)
    assert o.voc_v == pytest.approx(1.8669, abs=0.001)
    assert o.ff == pytest.approx(0.8648, abs=0.002)
    assert o.j_top_sc == pytest.approx(15.4228, abs=0.002)
    assert o.j_bottom_sc == pytest.approx(20.0932, abs=0.002)
    assert o.coupling_converged
    # J-sens (V1.9-H): the old 393.2 pin was the midpoint artifact j_hi/0.04.
    # The twin is current-mismatched so V(J) never reaches the 20 mV probe;
    # the diagnostic is honestly NaN (finite-slope branch unit-tested in
    # test_v19h_physics_repairs.py). Jsc stays the current-source limit.
    assert o.detail["jsc_bias_sensitivity_bracketed"] is False
    assert np.isnan(o.detail["jsc_bias_sensitivity_ma_cm2_per_v"])
    assert o.detail["jsc_curve_grid_endpoint_ma_cm2"] == pytest.approx(15.4228, abs=0.002)
    # (b) the default configuration includes one-sun self-heating
    hot = evaluate_tandem(ps)
    th = hot.detail["thermal"]
    assert th["model"] == "energy_balance"
    assert th["delta_t_k"] == pytest.approx(11.33, abs=0.02)
    assert hot.pce_pct == pytest.approx(24.2348, abs=0.002)
    assert hot.pce_pct < o.pce_pct     # heating can only cost efficiency
    assert abs(th["residual_mw_cm2"]) < 1e-3      # the balance must close


def test_thermal_mechanism_is_wired_and_directional():
    """Mechanism C: thermal management must reduce the junction temperature and
    recover efficiency; the heat-fraction parameter must scale the rise.

    V1.9-C pin move: the numbers below are those of the energy-balance closure
    (conduction + radiative cooling), not the legacy all-incident-power rule, so
    they are smaller than the V1.9-B values (12.0 -> 5.48 K for gain 0.6,
    15.0 -> 3.68 K for heat fraction 0.5).

    V1.9-H pin move: gain-0.6 dT 5.48 -> 4.94 K (R1/T21 raise P_elec, leaving
    less heat); heat-fraction-0.5 dT 3.68 -> 5.64 K. The latter move is the
    F-heat repair signature: heat is now f*(absorbed - extracted), so f = 0.5
    gives almost exactly half the base rise (5.64 vs 11.33 K); the old form
    subtracted the full extracted power and gave 0.29x (3.68 vs 12.59 K)."""
    ps = ParamSet.defaults()
    base = evaluate_tandem(ps)
    cooled = evaluate_tandem(ps.with_mapping({"thermal_management_gain": 0.6}))
    assert cooled.detail["thermal"]["delta_t_k"] == pytest.approx(4.94, abs=0.02)
    assert cooled.pce_pct > base.pce_pct
    half_heat = evaluate_tandem(ps.with_mapping({"absorption_heat_fraction": 0.5}))
    assert half_heat.detail["thermal"]["delta_t_k"] == pytest.approx(5.64, abs=0.02)
    assert half_heat.pce_pct > base.pce_pct


def test_luminescent_coupling_is_bounded_and_directionally_honest():
    """Top->bottom coupling cannot relieve a TOP-limited tandem: the effect must
    stay small (this pins the V1.9 coupling-scale bug which produced PCE=141 %)."""
    ps = ParamSet.defaults()
    base = evaluate_tandem(ps, self_heating=False)
    coupled = evaluate_tandem(ps.with_mapping(
        {"luminescent_coupling_top_to_bottom": 0.5}), self_heating=False)
    assert abs(coupled.pce_pct - base.pce_pct) < 0.1
    assert base.current_matching_ratio > 1.0      # bottom has the surplus
    # V1.9-H: tripwire moved 25.0 -> 30.0 because the nominal moved 20.24 ->
    # 24.90 (margin was 0.1 pp); 30.0 still detects the 141 % bug class loudly
    assert coupled.pce_pct < 30.0                 # no runaway: fail loudly if it returns


def test_rsh_is_not_inert_in_the_tandem_solve():
    """Regression guard for the V1.9 shunt unit bug: a smaller shunt
    resistance must measurably lower the efficiency, otherwise the parameter
    is silently inactive and any 'unlearnable parameter' claim is false."""
    ps = ParamSet.defaults()
    strong = evaluate_tandem(ps.with_mapping({"rsh_ohm_cm2": 600.0}))
    weak = evaluate_tandem(ps.with_mapping({"rsh_ohm_cm2": 6000.0}))
    assert strong.pce_pct < weak.pce_pct - 1.0
    assert strong.ff < weak.ff


def test_tandem_model_form_sensitivity_is_reported_not_hidden():
    """IQE-M2 (diffusion-limited collection) must be *evaluated and reported*
    even though it is worse; a model-form comparison that only shows the
    flattering form would be cherry-picking."""
    ps = ParamSet.defaults()
    m1 = evaluate_tandem(ps, model_form="IQE-M1")
    m2 = evaluate_tandem(ps, model_form="IQE-M2")
    assert m1.pce_pct > m2.pce_pct
    assert m2.pce_pct > 5.0     # still a finite, plausible number
    assert m1.model_form != m2.model_form


def test_detailed_balance_known_answers():
    """Shockley-Queisser reference, independently checked values."""
    from apmt.device.detailed_balance import detailed_balance_single_junction
    r = detailed_balance_single_junction(1.34)
    assert r.jsc_ma_cm2 == pytest.approx(35.02, abs=0.05)
    assert r.voc_v == pytest.approx(1.082, abs=0.002)
    assert r.ff == pytest.approx(0.889, abs=0.003)
    assert r.pce_pct == pytest.approx(33.68, abs=0.05)
    # V1.9-H: the module docstring's known-answer claims, made real (they were
    # previously attributed to a test file that does not exist).
    from apmt.core.constants import Q_C
    from apmt.device.detailed_balance import sq_optimum
    from apmt.spectra.reference import reference
    opt = sq_optimum()
    assert 1.25 < opt.eg_ev < 1.45
    assert 32.5 < opt.pce_pct < 34.5
    assert (detailed_balance_single_junction(opt.eg_ev - 0.2).pce_pct
            < opt.pce_pct)
    assert (detailed_balance_single_junction(opt.eg_ev + 0.2).pce_pct
            < opt.pce_pct)
    sp = reference()
    assert r.jsc_ma_cm2 == pytest.approx(
        0.1 * Q_C * sp.above_gap_photon_flux(1.34), rel=1e-9)
    assert r.voc_v < 1.34
    hot = detailed_balance_single_junction(1.34, temperature_k=350.0)
    assert hot.voc_v < r.voc_v


def test_invariants_fail_loudly():
    bad = np.array([0.5, 1.2])
    with pytest.raises(InvariantViolation):
        check_invariants([check_quantum_efficiency_bounds(bad)])
    with pytest.raises(InvariantViolation):
        check_invariants([check_optical_closure(np.array([0.5]),
                                                np.array([0.5]),
                                                np.array([0.5]))])
    with pytest.raises(InvariantViolation):
        check_invariants([check_photon_budget(
            {"incident_100pct_eqe": 40.0, "reflected": 4.0, "transmitted": 6.0,
             "parasitic_absorbed": 1.0, "absorbed_top": 16.0,
             "absorbed_bottom": 12.0})])   # 39 vs 40 = 1 mA/cm2 leak
    ok = check_invariants([check_quantum_efficiency_bounds(np.array([0.0, 1.0]))])
    assert ok[0].passed


# ---------------------------------------------------------------------------
# V1.9-C campaign #1: sensitivity machinery (no physics pinned here; the
# factorial algebra is verified against a synthetic evaluator so the test is
# fast and independent of the tandem model)
# ---------------------------------------------------------------------------
def test_lhs_matrix_respects_registered_ranges_and_seed():
    from apmt.params.registry import spec
    from apmt.sensitivity.lhs import lhs_matrix
    names = ("perovskite_eg_ev", "thermal_resistance_k_cm2_w", "rsh_ohm_cm2")
    a = lhs_matrix(names, 64, seed=123)
    b = lhs_matrix(names, 64, seed=123)
    c = lhs_matrix(names, 64, seed=124)
    assert np.allclose(a, b) and not np.allclose(a, c)
    assert a.shape == (64, 3)
    for j, name in enumerate(names):
        s = spec(name)
        assert np.all(a[:, j] >= s.low) and np.all(a[:, j] <= s.high)


def test_factorial_effects_match_a_known_synthetic_response(monkeypatch):
    """Interaction algebra: for PCE = a*A + b*B + c*A*B the recovered direct
    effects must be a and b, and the 2-way interaction must be c."""
    from apmt.sensitivity import factorial as fac

    def fake(base, mechanisms, active, model_form="IQE-M1"):
        A = 1.0 if active.get("A") else 0.0
        B = 1.0 if active.get("B") else 0.0
        return {"pce_pct": 10.0 + 1.5 * A + 0.5 * B + 0.25 * A * B}

    monkeypatch.setattr(fac, "evaluate_configuration", fake)
    mechs = fac.DEFAULT_MECHANISMS[:2]
    out = fac.full_factorial(mechanisms=mechs)
    assert out["direct_effects_pp"]["A"] == pytest.approx(1.5)
    assert out["direct_effects_pp"]["B"] == pytest.approx(0.5)
    assert out["interaction_effects_pp"]["AxB"] == pytest.approx(0.25)
