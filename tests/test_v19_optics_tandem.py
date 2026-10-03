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
    """Registry-default twin, model form IQE-M1 (pin of 2026-10-03)."""
    o = evaluate_tandem(ParamSet.defaults())
    assert o.pce_pct == pytest.approx(20.8508, abs=0.002)
    assert o.jsc_ma_cm2 == pytest.approx(15.7266, abs=0.002)
    assert o.voc_v == pytest.approx(1.5150, abs=0.001)
    assert o.ff == pytest.approx(0.8750, abs=0.002)
    assert o.j_top_sc == pytest.approx(15.7266, abs=0.002)
    assert o.j_bottom_sc == pytest.approx(19.8030, abs=0.002)
    assert o.coupling_converged


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
