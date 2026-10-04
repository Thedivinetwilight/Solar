"""V1.9-C — invariant layer and admissibility guard tests.

The invariant framework is a *physics gate on the model itself*: every solve must
carry a machine-readable PASS/WARN/FAIL/NOT_APPLICABLE record per physical
invariant, and a HARD failure must mark the solve INVALID. These tests check both
directions: a well-behaved solve passes, and a deliberately corrupted solve FAILS
(otherwise the framework would be decoration).
"""
from __future__ import annotations

import numpy as np
import pytest

from apmt.device.tandem import evaluate_tandem
from apmt.params.registry import ParamSet
from apmt.validation import invariants as inv
from apmt.validation.guard import (TANDEM_LIMITS, evaluate_guarded, judge_optics,
                                   judge_tandem, radiative_ceiling_pct)


# ---------------------------------------------------------------------------
# record / bundle plumbing
# ---------------------------------------------------------------------------
def test_statuses_and_severity_are_first_class():
    assert {s.value for s in inv.InvariantStatus} == {"PASS", "WARN", "FAIL",
                                                      "NOT_APPLICABLE"}
    assert {s.value for s in inv.Severity} == {"HARD", "SOFT"}
    assert inv.InvariantGroup.OPTICAL.value == "optical"


def test_fail_record_and_bundle_validity():
    ok = inv.record("optical.closure", "optical", True, message="R+T+A=1")
    bad = inv.record("optical.closure", "optical", False, message="R+T+A=1.2")
    soft = inv.record("thermal.envelope", "thermal", False, severity=inv.Severity.SOFT,
                      message="implausible rise")
    assert ok.status is inv.InvariantStatus.PASS and ok.severity is inv.Severity.HARD

    bundle = inv.InvariantBundle((ok,))
    assert bundle.valid and bundle.hard_failures == ()

    bundle = inv.InvariantBundle((ok, bad))
    assert not bundle.valid
    assert [r.name for r in bundle.hard_failures] == ["optical.closure"]
    assert "optical.closure" in bundle.invalid_reason

    # a SOFT non-conformance must NOT invalidate the solve (reported, not fatal)
    bundle = inv.InvariantBundle((ok, soft))
    assert bundle.valid
    assert [r.name for r in bundle.soft_failures] == ["thermal.envelope"]
    assert bundle.counts()["WARN"] == 1


def test_not_applicable_is_not_a_failure():
    na = inv.record("thermal.energy_balance", "thermal", True, applicable=False,
                    message="fixed-T solve has no energy balance")
    bundle = inv.InvariantBundle((na,))
    assert bundle.valid and bundle.counts()["NOT_APPLICABLE"] == 1
    assert na.status is inv.InvariantStatus.NOT_APPLICABLE
    assert na.to_dict()["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# individual checks: PASS on good data, FAIL on corrupted data
# ---------------------------------------------------------------------------
def test_numerical_finiteness_check_catches_nan_and_inf():
    good = inv.check_numerical_finiteness({"pce": 20.2, "jsc": 15.7})
    assert all(r.status is inv.InvariantStatus.PASS for r in good)
    for bad in (float("nan"), float("inf"), float("-inf")):
        recs = inv.check_numerical_finiteness({"pce": bad})
        assert all(r.status is inv.InvariantStatus.FAIL for r in recs)
        assert all(r.severity is inv.Severity.HARD for r in recs)


def test_optical_closure_check_is_hard():
    wl = np.linspace(300.0, 1200.0, 25)
    r = np.full_like(wl, 0.45)
    t = np.full_like(wl, 0.15)
    a = np.full_like(wl, 0.40)
    assert inv.check_optical_closure(r, t, a).status is inv.InvariantStatus.PASS
    # a leak of 0.05 in the budget must FAIL, and the legacy V1.9-B report shape
    # must expose the same PASS/FAIL status through the unified registry API
    assert inv.check_optical_closure(r, t + 0.05, a).status is inv.InvariantStatus.FAIL
    legacy = inv.CHECKS["optical.closure"](r, t, a)
    assert legacy.status is inv.InvariantStatus.PASS and legacy.passed
    assert legacy.to_record().status is inv.InvariantStatus.PASS


def test_range_check_rejects_out_of_bounds_and_negative_power():
    limits = {"ff": (0.0, 1.0), "voc_v": (0.0, 3.0)}
    recs = inv.check_ranges({"ff": 0.85, "voc_v": 1.5}, limits)
    assert all(r.status is inv.InvariantStatus.PASS for r in recs)
    recs = inv.check_ranges({"ff": 1.4, "voc_v": 1.5}, limits)
    assert any(r.status is inv.InvariantStatus.FAIL for r in recs)
    recs = inv.check_ranges({"absorbed_mw_cm2": -1.0}, {"absorbed_mw_cm2": (0.0, None)})
    assert recs[0].status is inv.InvariantStatus.FAIL
    # a missing quantity is NOT_APPLICABLE, never a silent PASS
    recs = inv.check_ranges({"ff": 0.85}, {"ff": (0.0, 1.0), "voc_v": (0.0, 3.0)})
    assert any(r.status is inv.InvariantStatus.NOT_APPLICABLE for r in recs)


def test_data_grid_check_detects_non_monotone_duplicates_and_gaps():
    wl = np.linspace(300.0, 1200.0, 30)
    assert all(r.status is inv.InvariantStatus.PASS for r in inv.check_data_grid(wl))
    bad = wl.copy()
    bad[5], bad[6] = bad[6], bad[5]
    assert any(r.name == "data.wavelength_monotone"
               and r.status is inv.InvariantStatus.FAIL for r in inv.check_data_grid(bad))
    dup = wl.copy()
    dup[7] = dup[6]
    assert any(r.name == "data.wavelength_duplicates"
               and r.status is inv.InvariantStatus.FAIL for r in inv.check_data_grid(dup))
    # too-coarse grids are rejected: 5 nm resolution is the documented minimum
    assert any(r.name == "data.min_points" and r.status is inv.InvariantStatus.FAIL
               for r in inv.check_data_grid(wl[:10]))


def test_radiative_limit_check_and_ceiling():
    assert inv.check_radiative_limit_consistency(20.0, 33.7).status is inv.InvariantStatus.PASS
    assert inv.check_radiative_limit_consistency(60.0, 33.7).status is inv.InvariantStatus.FAIL
    # ceiling from the model's own absorbed-photon budget: Jlim * sum(Voc_rad)
    ceiling = radiative_ceiling_pct(15.7, 19.8, 1e-13, 1e-12, 298.15)
    assert 20.0 < ceiling < 60.0
    # a tighter J0 gives a higher ceiling: the bound tracks the parameterisation
    assert radiative_ceiling_pct(15.7, 19.8, 1e-14, 1e-13, 298.15) > ceiling
    # A subcell with a non-positive radiative J0 is EXCLUDED from the ceiling sum
    # (a conservative, tighter bound). Such a point is independently INVALID under
    # check_recombination_channels (detailed balance requires J0_rad > 0), so the
    # conservative ceiling can never reject a physically admissible solve.
    assert radiative_ceiling_pct(15.7, 19.8, 0.0, 1e-12, 298.15) < ceiling
    recs = inv.check_recombination_channels(0.0, 1e-12, 1e-12)
    assert recs[0].status is inv.InvariantStatus.FAIL


def test_thermal_check_family():
    assert inv.check_thermal_energy_balance(49.2328, 49.2328).status is inv.InvariantStatus.PASS
    assert inv.check_thermal_energy_balance(49.2328, 49.9).status is inv.InvariantStatus.FAIL
    assert inv.check_thermal_stability(3.0).status is inv.InvariantStatus.PASS
    assert inv.check_thermal_stability(-0.5).status is inv.InvariantStatus.FAIL
    assert inv.check_temperature_envelope(310.0, 298.15).status is inv.InvariantStatus.PASS
    assert inv.check_temperature_envelope(1200.0, 298.15).status is inv.InvariantStatus.WARN


def test_resistance_and_recombination_checks():
    recs = inv.check_resistance_bounds(2.0, 1.0e6)
    assert all(r.status is inv.InvariantStatus.PASS for r in recs)
    recs = inv.check_resistance_bounds(-1.0, 1.0e6)
    assert any(r.status is inv.InvariantStatus.FAIL for r in recs)
    recs = inv.check_resistance_bounds(2.0, float("inf"))
    assert all(r.status is inv.InvariantStatus.PASS for r in recs)

    recs = inv.check_recombination_channels(1e-13, 1e-12, 1.1e-12)
    assert all(r.status is inv.InvariantStatus.PASS for r in recs)
    recs = inv.check_recombination_channels(1e-13, -1e-12, 1e-11)
    assert any(r.status is inv.InvariantStatus.FAIL for r in recs)
    recs = inv.check_recombination_channels(1e-13, 1e-12, 9e-12)   # sum mismatch
    assert any(r.name == "electrical.j0_channel_sum"
               and r.status is inv.InvariantStatus.FAIL for r in recs)


def test_shunt_and_current_continuity_and_radiometric_checks():
    assert inv.check_shunt_consistency(15.0, 15.7, 600.0).status \
        is inv.InvariantStatus.PASS          # a finite shunt lowers Jsc
    assert inv.check_shunt_consistency(16.0, 15.7, 600.0).status \
        is inv.InvariantStatus.WARN          # a shunt may never raise Jsc (SOFT)
    assert inv.check_shunt_consistency(15.0, 15.7, float("inf")).status \
        is inv.InvariantStatus.NOT_APPLICABLE
    assert inv.check_current_continuity(15.7, 19.8, 15.7).status is inv.InvariantStatus.PASS
    assert inv.check_current_continuity(15.7, 19.8, 16.9).status is inv.InvariantStatus.FAIL
    assert inv.check_radiometric_consistency(100.0, 100.0).status is inv.InvariantStatus.PASS
    assert inv.check_radiometric_consistency(120.0, 100.0).status is inv.InvariantStatus.FAIL


def test_checks_registry_is_discoverable_and_callable():
    assert len(inv.CHECKS) >= 20
    for name, fn in inv.CHECKS.items():
        assert callable(fn), name
    for required in ("optical.closure", "electrical.current_continuity",
                     "thermal.energy_balance", "numerical.finiteness",
                     "data.wavelength_grid"):
        assert required in inv.CHECKS


# ---------------------------------------------------------------------------
# guard: the admissibility layer
# ---------------------------------------------------------------------------
def test_guarded_default_solve_is_valid_and_carries_invariants():
    rec = evaluate_guarded(ParamSet.defaults())
    assert rec.valid and rec.verdict.valid and rec.result is not None
    assert rec.result.detail["solve_valid"] is True
    d = rec.result.detail["invariants"]
    assert d["valid"] is True and d["counts"]["FAIL"] == 0
    names = {r["name"] for r in d["records"]}
    assert any(n.startswith("optical") for n in names)
    assert any(n.startswith("electrical") for n in names)
    assert any(n.startswith("thermal") for n in names)
    assert any(n.startswith("numerical") for n in names)
    # every invariant is machine-readable: status + severity on every record
    for r in d["records"]:
        assert r["status"] in ("PASS", "WARN", "FAIL", "NOT_APPLICABLE")
        assert r["severity"] in ("HARD", "SOFT")


def test_guard_rejects_a_corrupted_high_efficiency_result():
    """The V1.9-B coupling-scale bug produced a 141.93 % 'efficiency'; the guard
    must reject any such result outright (HARD radiative-limit failure)."""
    res = evaluate_tandem(ParamSet.defaults(), self_heating=False)
    corrupt = res.__class__(**{**res.__dict__, "pce_pct": 141.93})
    verdict = judge_tandem(corrupt)
    assert not verdict.valid
    assert any("radiative_limit" in f.name or "pce_pct" in f.name
               for f in verdict.hard_failures)


def test_guard_rejects_degenerate_scalars():
    res = evaluate_tandem(ParamSet.defaults(), self_heating=False)
    for broken in ({"jsc_ma_cm2": 0.0}, {"voc_v": -0.1}, {"ff": 1.2},
                   {"pce_pct": float("nan")}, {"jsc_ma_cm2": 1e6},
                   {"vmp_v": 2.0}, {"pce_pct": 0.0}, {"ff": 0.0}):
        corrupt = res.__class__(**{**res.__dict__, **broken})
        assert not judge_tandem(corrupt).valid, broken


def test_guard_optics_returns_a_bundle():
    from apmt.device.tandem import optics_for
    opt = optics_for(ParamSet.defaults())
    bundle = judge_optics(opt)
    assert bundle.valid
    assert all(r.status is not inv.InvariantStatus.FAIL for r in bundle.records)
    assert any(r.name == "optical.closure" for r in bundle.records)


def test_guard_records_parameter_point_level_and_campaign():
    ps = ParamSet.defaults().with_mapping({"perovskite_eg_ev": 1.55})
    rec = evaluate_guarded(ps, level="L4", campaign_id="unit-test", seed=7)
    assert rec.campaign_id == "unit-test" and rec.seed == 7 and rec.level == "L4"
    assert rec.valid
    assert rec.parameter_values["perovskite_eg_ev"] == pytest.approx(1.55)
    assert rec.to_dict()["valid"] is True


def test_guard_reports_errors_instead_of_dying(monkeypatch):
    """A solver that raises must yield an INVALID record carrying the error text,
    not propagate the exception: a campaign must survive pathological samples.

    BOTH dispatch paths are exercised, because they are different code: a KNOWN
    level goes through the multi-fidelity engine (``evaluate_level``, which applies
    the level's fidelity switches and its own solver/thermal configuration), while
    an unknown level falls back to the plain tandem entry point. A regression in
    either path must not be able to kill a campaign.
    """
    import apmt.device.tandem as tandem_module
    import apmt.multifidelity.levels as levels_module

    def boom(*a, **k):
        raise RuntimeError("synthetic solver failure")

    monkeypatch.setattr(levels_module, "evaluate_level", boom)
    monkeypatch.setattr(tandem_module, "evaluate_tandem", boom)

    rec = evaluate_guarded(ParamSet.defaults(), level="L4", campaign_id="hostile")
    assert rec.valid is False
    assert "synthetic solver failure" in rec.error
    assert rec.result is None

    rec2 = evaluate_guarded(ParamSet.defaults(), level="no-such-level",
                            campaign_id="hostile")
    assert rec2.valid is False and "synthetic solver failure" in rec2.error
    assert rec2.result is None


def test_guard_separates_points_in_an_audit():
    ps = ParamSet.defaults()
    points = [ps.with_mapping({"rsh_ohm_cm2": v}) for v in (60.0, 600.0, 6000.0)]
    records = [evaluate_guarded(p, level="L4", campaign_id="audit") for p in points]
    assert len(records) == 3 and all(r.valid for r in records)
    pces = [r.result.pce_pct for r in records]
    assert pces[0] < pces[1] < pces[2]


def test_tandem_limits_are_documented_absurdity_bounds():
    assert TANDEM_LIMITS["pce_pct"][1] <= 100.0
    assert TANDEM_LIMITS["pce_pct"][0] > 0.0     # exact zeros are degenerate
    assert TANDEM_LIMITS["ff"][1] <= 1.05
    assert TANDEM_LIMITS["jsc_ma_cm2"][1] <= 60.0
    assert set(TANDEM_LIMITS) >= {"pce_pct", "jsc_ma_cm2", "voc_v", "ff"}
