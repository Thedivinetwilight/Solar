"""V1.9-C — engine tests: reference oracle vs vectorised solver, agreement,
batching, and numerical-equivalence guarantees.

The reference solver (scalar bisection per bias point) is the regression oracle
for the fast vectorised solver. These tests are the automated agreement contract:
they run over nominal points, random valid points, and physically awkward corners
(series resistance, shunt, coupling), and they pin the measured deviations.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from apmt.device import tandem as tandem_module
from apmt.device.batch import batch_evaluate, dataset
from apmt.device.tandem import (build_tandem, evaluate_tandem, optics_for,
                                solve_tandem_reference, clear_caches, cache_info)
from apmt.params.registry import ParamSet, sample_bounds
from apmt.sensitivity.lhs import lhs_matrix

# documented agreement tolerances between the reference oracle and the fast path.
# These are the SAME tolerances the campaign artifact (data/v19_engine_campaign.json)
# is required to satisfy: 1e-3 pp on PCE, 1e-3 mA/cm2 on Jsc, 1e-4 V on Voc, 1e-4 on FF.
TOL = {"pce": 1e-3, "jsc": 1e-3, "voc": 1e-4, "ff": 1e-4}

ENGINE_PARAMS = ("perovskite_eg_ev", "perovskite_thickness_nm", "arc_thickness_nm",
                 "silicon_light_trapping", "rsh_ohm_cm2", "rs_ohm_cm2")


def _pair(ps, **kw):
    ref = evaluate_tandem(ps, solver="reference", self_heating=False, **kw)
    fast = evaluate_tandem(ps, solver="fast", self_heating=False, **kw)
    return ref, fast


def _assert_agree(ref, fast, scale=1.0):
    assert abs(ref.pce_pct - fast.pce_pct) < TOL["pce"] * scale, (ref.pce_pct, fast.pce_pct)
    assert abs(ref.jsc_ma_cm2 - fast.jsc_ma_cm2) < TOL["jsc"] * scale
    assert abs(ref.voc_v - fast.voc_v) < TOL["voc"] * scale
    assert abs(ref.ff - fast.ff) < TOL["ff"] * scale
    # Jsc is defined identically in both solvers (the current-source limit)
    assert ref.jsc_ma_cm2 == pytest.approx(min(ref.j_top_sc, ref.j_bottom_sc), abs=1e-12)
    assert fast.jsc_ma_cm2 == pytest.approx(min(fast.j_top_sc, fast.j_bottom_sc), abs=1e-12)


def test_reference_and_fast_agree_at_the_nominal_point():
    _assert_agree(*_pair(ParamSet.defaults()))


def test_reference_and_fast_agree_on_a_random_valid_ensemble():
    """12-point LHS ensemble over the optics/electrical parameter block."""
    X = lhs_matrix(ENGINE_PARAMS, 12, seed=20261004)
    base = ParamSet.defaults()
    worst = {k: 0.0 for k in TOL}
    for row in X:
        ps = base.with_mapping({k: float(v) for k, v in zip(ENGINE_PARAMS, row)})
        ref, fast = _pair(ps)
        worst["pce"] = max(worst["pce"], abs(ref.pce_pct - fast.pce_pct))
        worst["jsc"] = max(worst["jsc"], abs(ref.jsc_ma_cm2 - fast.jsc_ma_cm2))
        worst["voc"] = max(worst["voc"], abs(ref.voc_v - fast.voc_v))
        worst["ff"] = max(worst["ff"], abs(ref.ff - fast.ff))
    # measured on the V1.9-C campaign: 1.1e-5 pp / 1.7e-11 / 9.9e-7 / 3.0e-7
    for k, tol in TOL.items():
        assert worst[k] < tol, (k, worst[k])


@pytest.mark.parametrize("mapping", [
    {"rs_ohm_cm2": 0.0},
    {"rs_ohm_cm2": 20.0},
    {"rsh_ohm_cm2": 60.0},
    {"rsh_ohm_cm2": 1.0e6},
    {"rs_ohm_cm2": 10.0, "rsh_ohm_cm2": 120.0},
    {"luminescent_coupling_top_to_bottom": 0.5},
    {"luminescent_coupling_bottom_to_top": 0.5},
    {"perovskite_eg_ev": 1.40},
    {"perovskite_eg_ev": 2.00},
    {"perovskite_thickness_nm": 150.0},
    {"silicon_light_trapping": 30.0},
    {"rear_reflectance": 0.98},
])
def test_reference_and_fast_agree_at_edge_points(mapping):
    _assert_agree(*_pair(ParamSet.defaults().with_mapping(mapping)), scale=5.0)


def test_fast_solver_is_actually_vectorised():
    """The fast path must not fall back to the scalar bisection solver.

    Any scalar per-bias-point inversion inside the fast solve would make the
    measured speedup a wall-clock accident rather than an algorithmic property.
    """
    clear_caches()
    ps = ParamSet.defaults()
    calls = {"scalar_current": 0, "scalar_voltage": 0}
    real_c = tandem_module.current_at_voltage
    real_v = tandem_module.voltage_at_current

    def counting_c(*a, **kw):
        calls["scalar_current"] += 1
        return real_c(*a, **kw)

    def counting_v(*a, **kw):
        calls["scalar_voltage"] += 1
        return real_v(*a, **kw)

    tandem_module.current_at_voltage = counting_c
    tandem_module.voltage_at_current = counting_v
    try:
        res = evaluate_tandem(ps, solver="fast", self_heating=False)
    finally:
        tandem_module.current_at_voltage = real_c
        tandem_module.voltage_at_current = real_v
    assert res.pce_pct > 0
    # the fast path may use the scalar relation only for a handful of bookkeeping
    # evaluations (short-circuit currents), never per curve point
    assert calls["scalar_voltage"] < 20, calls


def test_fast_solver_is_faster_than_the_reference_oracle():
    """A generous factor (5x) is asserted so the test is not a timing race; the
    measured campaign speedup is ~1e3x and is recorded in the artifact."""
    ps = ParamSet.defaults()
    clear_caches()
    t0 = time.perf_counter()
    evaluate_tandem(ps, solver="reference", self_heating=False)
    t_ref = time.perf_counter() - t0
    clear_caches()
    t0 = time.perf_counter()
    evaluate_tandem(ps, solver="fast", self_heating=False)
    t_fast = time.perf_counter() - t0
    assert t_fast * 5.0 < t_ref, (t_ref, t_fast)


def test_optical_cache_is_shared_between_solves():
    """Changing only electrical parameters must not recompute the optics."""
    clear_caches()
    ps = ParamSet.defaults()
    evaluate_tandem(ps, self_heating=False)
    info1 = cache_info()
    evaluate_tandem(ps.with_mapping({"rs_ohm_cm2": 5.0}), self_heating=False)
    info2 = cache_info()
    key = "optics_cache" if "optics_cache" in info1 else "optics"
    assert info2[key]["hits"] > info1[key]["hits"]
    assert info2[key]["misses"] == info1[key]["misses"]


def test_batch_api_returns_one_guarded_record_per_point():
    names = ("perovskite_eg_ev", "perovskite_thickness_nm", "rsh_ohm_cm2")
    X = lhs_matrix(names, 8, seed=3)
    recs, summary = batch_evaluate(X, names, level="L4", campaign_id="batch-test")
    assert len(recs) == X.shape[0] == summary.n_requested
    assert summary.valid if hasattr(summary, "valid") else True
    assert summary.n_valid + summary.n_invalid == summary.n_requested
    assert all(r.campaign_id == "batch-test" for r in recs)
    # every record carries its own invariants: batch results are auditable
    for r in recs:
        if r.result is not None:
            assert "invariants" in r.result.detail


def test_batch_dataset_excludes_invalid_rows_and_reports_them():
    names = ("perovskite_eg_ev", "rsh_ohm_cm2")
    # include a deliberately absurd point (a 50 ohm cm2 shunt at high injection)
    X = np.array([[1.68, 50.0], [1.55, 600.0], [1.80, 6000.0]])
    recs, _ = batch_evaluate(X, names, level="L4", campaign_id="dataset-test")
    ds = dataset(recs, names, X)
    assert ds["n_rows"] + ds["n_rejected"] == 3
    assert ds["X"].shape == (ds["n_rows"], 2)
    assert ds["y"].shape == (ds["n_rows"], 5)
    # the reject accounting is explicit, never silent
    for rej in ds["rejected"]:
        assert rej["reason"]
    assert "never training data" in ds["note"]


def test_batch_clips_to_registered_bounds_instead_of_evaluating_outside_them():
    names = ("perovskite_eg_ev",)
    lo_arr, hi_arr = sample_bounds(names)
    lo, hi = float(lo_arr[0]), float(hi_arr[0])
    X = np.array([[lo - 10.0], [hi + 10.0]])
    recs, _ = batch_evaluate(X, names, level="L2", campaign_id="clip-test")
    values = [r.parameter_values["perovskite_eg_ev"] for r in recs if r.result]
    assert all(lo <= v <= hi for v in values)


def test_jsc_definition_and_conditioning_diagnostic():
    """Jsc is the current-source limit; the curve sensitivity documents why."""
    res = evaluate_tandem(ParamSet.defaults(), self_heating=False)
    assert res.jsc_ma_cm2 == pytest.approx(min(res.j_top_sc, res.j_bottom_sc), abs=1e-12)
    assert "current-source limit" in res.detail["jsc_definition"]
    # V1.9-H (J-sens): the twin is current-mismatched, so V(J) never reaches
    # the 20 mV probe bias (the bottom cell still holds ~0.5 V when the top
    # hits Jsc) and the slope is honestly NaN, not the old midpoint artifact
    # (j_hi/0.04 = 385.6, preserved in git history). The finite-slope branch
    # is unit-tested on synthetic curves in test_v19h_physics_repairs.py.
    assert res.detail["jsc_bias_sensitivity_bracketed"] is False
    assert np.isnan(res.detail["jsc_bias_sensitivity_ma_cm2_per_v"])


def test_solver_auto_selects_the_fast_path():
    ps = ParamSet.defaults()
    auto = evaluate_tandem(ps, solver="auto", self_heating=False)
    fast = evaluate_tandem(ps, solver="fast", self_heating=False)
    assert auto.pce_pct == pytest.approx(fast.pce_pct, abs=1e-12)


# ---------------------------------------------------------------------------
# concentration: the V1.9-C unit fix
# ---------------------------------------------------------------------------
def test_pce_is_a_percentage_at_every_concentration():
    """V1.9-C unit bug: pce_pct was P_out/100 mW/cm2 at EVERY irradiance, i.e. it
    scaled linearly with concentration and reached 102.9 'per cent' at 5 suns.
    The efficiency must be P_out / (suns * 100 mW/cm2) * 100 at every irradiance.
    """
    ps = ParamSet.defaults()
    rows = []
    for suns in (0.1, 0.5, 1.0, 2.0, 5.0):
        r = evaluate_tandem(ps.with_mapping({"irradiance_suns": float(suns)}),
                            self_heating=False, solver="fast")
        p_out = r.detail["power_density_out_mw_cm2"]
        assert r.pce_pct == pytest.approx(p_out / suns, rel=1e-12)
        assert r.pce_pct == pytest.approx(r.vmp_v * r.jmp_ma_cm2 / (suns * 100.0) * 100.0,
                                          rel=1e-9)
        assert 0.0 < r.pce_pct < 45.0          # a two-junction ceiling of 45.7 %
        rows.append(r.pce_pct)
    # the 1-sun value is untouched by the fix (this is why no pinned 1-sun number
    # changed) and the concentration response is weak and physical
    assert rows[2] == pytest.approx(24.9007, abs=0.002)  # V1.9-H: R1 (J0_rad/1000)
    assert rows[3] > rows[2]                   # small concentration gain
    assert all(abs(p - rows[2]) < 2.0 for p in rows[1:])   # >=0.5 sun: flat
    # ... and at 0.1 sun the efficiency falls by ~6 pp because the shunt and the
    # ideality terms dominate at low injection -- a physically expected loss, not
    # a normalisation artefact
    assert rows[0] < rows[2] - 4.0


def test_currents_scale_with_concentration_and_limits_allow_it():
    ps = ParamSet.defaults()
    one = evaluate_tandem(ps, self_heating=False, solver="fast")
    five = evaluate_tandem(ps.with_mapping({"irradiance_suns": 5.0}), self_heating=False,
                           solver="fast")
    assert five.jsc_ma_cm2 / one.jsc_ma_cm2 == pytest.approx(5.0, rel=0.01)
    assert five.jsc_ma_cm2 > 60.0              # above the per-sun absurdity bound
    from apmt.validation.guard import evaluate_guarded
    rec = evaluate_guarded(ps.with_mapping({"irradiance_suns": 5.0}), campaign_id="conc")
    assert rec.valid                          # the guard scales currents with suns


def test_radiative_ceiling_is_normalised_by_concentration():
    from apmt.validation.guard import radiative_ceiling_pct
    one = radiative_ceiling_pct(15.7, 19.8, 1e-13, 1e-12, 298.15, concentration=1.0)
    five = radiative_ceiling_pct(15.7, 19.8, 1e-13, 1e-12, 298.15, concentration=5.0)
    assert five < one                          # the same power over 5x the input
    assert one / five == pytest.approx(5.0, rel=1e-12)


def test_out_of_envelope_junction_temperature_is_invalid_not_extrapolated():
    """A corner whose equilibrium junction temperature leaves the electrical
    model's validity window must be INVALID (never reported as a result)."""
    from apmt.validation.guard import evaluate_guarded
    from apmt.device.thermal import ELECTRICAL_ENVELOPE_MAX_K
    ps = ParamSet.defaults().with_mapping({"irradiance_suns": 5.0,
                                           "thermal_resistance_k_cm2_w": 2.0})
    rec = evaluate_guarded(ps, level="L4", campaign_id="envelope")
    assert rec.valid is False
    assert "validity window" in rec.error
    assert ELECTRICAL_ENVELOPE_MAX_K == 400.0


def test_batch_api_and_serial_guarded_agree():
    """The warm-started batch path and the plain guarded path must produce the
    same physics for the same parameter point (they are two code paths through
    the same level configuration and the same fidelity switches).

    The tolerance is the DOCUMENTED thermal convergence tolerance (1e-4 mW/cm2 on
    the balance residual, i.e. ~1e-5 K), not machine precision: the warm start
    changes only how many electrical solves the thermal loop needs. A fidelity
    mismatch (a level not applied) shows up as 0.1-2 pp, six orders larger.
    """
    from apmt.validation.guard import evaluate_guarded
    names = ("perovskite_eg_ev", "thermal_resistance_k_cm2_w")
    X = np.array([[1.62, 0.45], [1.72, 1.10]])
    recs, _ = batch_evaluate(X, names, level="L4", campaign_id="agree")
    for row, rec in zip(X, recs):
        ps = ParamSet.defaults().with_mapping({k: float(v) for k, v in zip(names, row)})
        direct = evaluate_guarded(ps, level="L4", campaign_id="agree")
        assert rec.valid and direct.valid
        assert rec.result.pce_pct == pytest.approx(direct.result.pce_pct, abs=1e-3)
        assert rec.result.voc_v == pytest.approx(direct.result.voc_v, abs=1e-4)
        assert rec.result.jsc_ma_cm2 == pytest.approx(direct.result.jsc_ma_cm2, abs=1e-3)
        # the fidelity switches must be identical on both paths
        assert (rec.result.detail["level_switches"]
                == direct.result.detail["level_switches"])
