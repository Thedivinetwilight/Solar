"""V1.9-C — batch / surrogate-readiness tests (items 18, 19, 21, 22).

The batch API is the interface V1.9-D consumes: N parameter sets in, N guarded
records out, with the parameter point, level, campaign id, seed and invariant
status attached to every row, and a hard guarantee that an invalid solve never
reaches a dataset. These tests pin those guarantees.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from apmt.device.batch import BatchSummary, batch_evaluate, dataset, lhs_batch
from apmt.params.registry import ParamSet

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPAIGN = os.path.join(HERE, "data", "v19_engine_campaign.json")


def test_lhs_batch_returns_records_and_a_summary():
    recs, summary = lhs_batch(4, ("perovskite_eg_ev", "arc_thickness_nm"),
                              level="L2", campaign_id="lhs-test", seed=17)
    assert isinstance(summary, BatchSummary)
    assert summary.n_requested == 4 and len(recs) == 4
    assert summary.n_valid + summary.n_invalid == 4
    assert summary.solves_per_second > 0
    assert summary.level == "L2" and summary.campaign_id == "lhs-test"
    assert all(r.seed == 17 for r in recs)


def test_records_carry_everything_a_surrogate_row_needs():
    names = ("perovskite_eg_ev",)
    X = np.array([[1.5], [1.7]])
    recs, _ = batch_evaluate(X, names, level="L4", campaign_id="meta-test", seed=3)
    for rec in recs:
        assert rec.level == "L4" and rec.campaign_id == "meta-test" and rec.seed == 3
        assert rec.runtime_s > 0 and rec.solver
        assert rec.parameter_values["perovskite_eg_ev"] in (1.5, 1.7)
        assert rec.result is not None
        assert "invariants" in rec.result.detail
        assert "status" in rec.result.detail["invariants"]


def test_invalid_solves_are_excluded_and_accounted_in_the_dataset():
    """A point outside the validity window must be reported, not silently used."""
    names = ("irradiance_suns", "thermal_resistance_k_cm2_w")
    X = np.array([[1.0, 0.3],      # fine
                  [5.0, 2.0],      # converged junction above the validity window
                  [1.0, 1.0]])     # fine
    recs, summary = batch_evaluate(X, names, level="L4", campaign_id="validity")
    assert summary.n_invalid >= 1
    ds = dataset(recs, names, X)
    assert ds["n_rows"] + ds["n_rejected"] == 3
    assert ds["n_rejected"] >= 1
    for rej in ds["rejected"]:
        assert rej["reason"]
    # the invalid row must not appear in the training matrix
    assert ds["X"].shape[0] == ds["n_rows"]


def test_dataset_targets_are_the_documented_five_columns():
    names = ("perovskite_eg_ev", "perovskite_thickness_nm")
    X = np.array([[1.6, 500.0]])
    recs, _ = batch_evaluate(X, names, level="L2", campaign_id="cols")
    ds = dataset(recs, names, X)
    assert ds["target_names"] == ["pce_pct", "jsc_ma_cm2", "voc_v", "ff",
                                  "temperature_k"]
    assert ds["y"].shape == (1, 5) and ds["X"].shape == (1, 2)
    assert ds["feature_names"] == list(names)


def test_batch_order_is_preserved():
    names = ("perovskite_eg_ev",)
    X = np.array([[1.40], [1.55], [1.70], [1.85], [2.00]])
    recs, _ = batch_evaluate(X, names, level="L2", campaign_id="order")
    got = [r.parameter_values["perovskite_eg_ev"] for r in recs]
    assert got == [1.40, 1.55, 1.70, 1.85, 2.00]
    # the bandgap response is non-monotone (interior optimum), so an order bug
    # would be visible even without inspecting the ids
    pces = [r.result.pce_pct for r in recs]
    # V1.9-H: current-matching optimum moved 1.70 -> ~1.60 eV (U1 lowers top
    # current at fixed Eg; R1 reshapes Voc(Eg)), so on this coarse grid the max
    # sits at 1.55 eV (index 1). Still interior, so the order tripwire (an order
    # bug would surface the max at an endpoint) keeps working.
    assert max(pces) == pces[1]


def test_campaign_artifact_is_reproducible_and_carries_metadata():
    """The committed campaign artifact must be verifiable and self-describing.

    The full file is not byte-deterministic (it contains machine-specific wall
    clock), so the artifact carries a PHYSICS DIGEST over the sections that are.
    """
    if not os.path.exists(CAMPAIGN):                       # pragma: no cover
        pytest.skip("campaign artifact not generated in this checkout")
    from apmt.repro.digest import physics_digest, strip_timings
    with open(CAMPAIGN) as f:
        art = json.load(f)
    assert "physics_digest" in art
    assert physics_digest(art) == art["physics_digest"]["sha256"]
    # the digest must not depend on wall clock: inject a fake timing and check
    import copy
    noisy = copy.deepcopy(art)
    noisy["batch_levels"]["L4"]["wall_clock_s"] = 12345.678
    noisy["convergence"]["subcell_table_and_curve"][0]["wall_clock_s"] = 1.0
    assert physics_digest(noisy) == art["physics_digest"]["sha256"]
    # ... and it MUST depend on the science
    changed = copy.deepcopy(art)
    cases = changed["limits"]["cases"]
    key = "no_thermal_resistance"
    assert key in cases, sorted(cases)
    cases[key]["pce_pct"] = 20.0
    assert physics_digest(changed) != art["physics_digest"]["sha256"]
    meta = art["metadata"]
    for key in ("python", "numpy", "git_commit", "registry_defaults_fingerprint",
                "units", "topology"):
        assert key in meta
    assert art["n_registry_parameters"] == 43
    assert art["label"].startswith("PRE-GATE")


def test_reference_first_row_of_the_batch_is_not_warm_started():
    """Warm-starting must never be used without a previous solve: the first row
    has to be an independent, cold evaluation."""
    names = ("rsh_ohm_cm2",)
    X = np.array([[600.0], [600.0]])
    recs, _ = batch_evaluate(X, names, level="L4", campaign_id="warm", seed=5)
    assert recs[0].solver != "fast-warm"
    assert recs[1].solver == "fast-warm"
    # and the warm-started result agrees with the cold one (same physics)
    assert recs[0].result.pce_pct == pytest.approx(recs[1].result.pce_pct, abs=1e-3)


def test_batch_workers_run_under_spawn_and_match_serial():
    """V1.9-H: workers>1 must work under the spawn start method (macOS/Windows
    default), not just fork. Pre-fix the children raised KeyError('names')."""
    names = ("perovskite_eg_ev", "rsh_ohm_cm2")
    X = np.array([[1.60, 3000.0], [1.70, 2500.0]])
    recs_p, _ = batch_evaluate(X, names, level="L2", campaign_id="spawn",
                               workers=2, mp_context="spawn", warm_start=False)
    recs_s, _ = batch_evaluate(X, names, level="L2", campaign_id="serial",
                               warm_start=False)
    assert [r.parameter_values["perovskite_eg_ev"] for r in recs_p] == [1.60, 1.70]
    for rp, rs in zip(recs_p, recs_s):
        assert rp.valid == rs.valid
        if rp.valid:
            assert rp.result.pce_pct == pytest.approx(rs.result.pce_pct, rel=1e-9)


def test_batch_workers_honor_a_non_default_base():
    """V1.9-H: the worker path ignored `base` (always rebuilt from registry
    defaults), silently diverging from the serial path."""
    base = ParamSet.defaults().with_mapping({"rsh_ohm_cm2": 600.0})
    names = ("perovskite_eg_ev",)
    X = np.array([[1.60], [1.70]])
    recs_p, _ = batch_evaluate(X, names, level="L2", campaign_id="base",
                               base=base, workers=2, warm_start=False)
    recs_s, _ = batch_evaluate(X, names, level="L2", campaign_id="base-s",
                               base=base, warm_start=False)
    for rp, rs in zip(recs_p, recs_s):
        assert rp.parameter_values["rsh_ohm_cm2"] == pytest.approx(600.0)
        assert rp.result.pce_pct == pytest.approx(rs.result.pce_pct, rel=1e-9)


def test_batch_warm_and_cold_carry_the_same_verdict_records():
    """V1.9-H: the warm path judged WITHOUT the optical bundle, so warm
    records carried fewer invariant records than the same row cold."""
    names = ("rsh_ohm_cm2",)
    X = np.array([[600.0], [600.0]])
    recs, _ = batch_evaluate(X, names, level="L4", campaign_id="verdict", seed=5)
    assert recs[1].solver == "fast-warm"
    cold = [r.name for r in recs[0].verdict.records]
    warm = [r.name for r in recs[1].verdict.records]
    assert warm == cold
    assert any(n.startswith("optical.") for n in warm)


def test_batch_clip_warns_but_stays_self_consistent():
    """V1.9-H: out-of-range entries are still clipped (never evaluated
    outside the registered ranges), but the caller is now told."""
    names = ("perovskite_eg_ev",)
    from apmt.params.registry import sample_bounds
    lo_v = float(sample_bounds(names)[0][0])
    hi_v = float(sample_bounds(names)[1][0])
    X = np.array([[lo_v - 10.0], [hi_v + 10.0]])
    with pytest.warns(UserWarning, match="clipped"):
        recs, _ = batch_evaluate(X, names, level="L2", campaign_id="clip-warn")
    got = [r.parameter_values["perovskite_eg_ev"] for r in recs]
    assert got == [lo_v, hi_v]
