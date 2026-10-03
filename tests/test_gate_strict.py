"""Gate strictness tests: the baseline gate cannot PASS on the current
evidence, cannot be opened without evidence, and correctly classifies the
historical fit diagnostics (V1.4 condition number 1.216e6) as failing.
"""
import json

from apmt.validation_gate import (
    GateEvidence,
    GateResult,
    GateThresholds,
    evaluate_gate,
    gate_spec_json,
)
from apmt.genealogy import GENEALOGY_LINKAGES


def test_empty_evidence_defers():
    res = evaluate_gate(GateEvidence())
    assert res.status == "DEFER"
    assert res.failed == ()


def test_current_apmt_evidence_cannot_pass():
    """Current known evidence for the conventional baseline (cycle 2,
    2026-10-01): certified Jsc 19.23 (SOURCE-REPORTED, main text + Table S2),
    champion EQE integrals 19.41/20.18 (SOURCE-REPORTED and 3-method
    pixel-reproducible from the committed Fig. S32), no full-stack R/T/A, no
    external Rs/Rsh, V1.4 fit condition number 1,216,249.34 with boundary
    hits. The gate must NOT pass, but G1 no longer flags the (resolved) EQE
    conflict: |19.23 - 19.41| = 0.18 <= 0.30."""
    ev = GateEvidence(
        jsc_jv_ma_cm2=19.23,
        jsc_eqe_ma_cm2=19.41,   # V1.8 cycle-2: min(19.41, 20.18) from S32 (M1: 19.4301/20.1846)
        jsc_certified_ma_cm2=19.23,
        jv_rmse_ma_cm2=0.9170,      # V1.4 certified JV digitization RMSE (HANDOFF-QUOTED)
        jsc_scan_dir1_ma_cm2=19.23,  # Table S2 (p50): Jsc->Voc, primary-verified
        jsc_scan_dir2_ma_cm2=19.24,  # Table S2 (p50): Voc->Jsc, primary-verified
        rta_max_dev=None,           # DATA_REQUIRED
        linkages=GENEALOGY_LINKAGES,
        resistance_measured=False,  # DATA_REQUIRED
        condition_number=1216249.34,  # V1.4 candidate fit
        boundary_hits=3,
        untraced_numeric_claims=0,
    )
    res = evaluate_gate(ev)
    assert res.status in ("FAIL", "DEFER")
    assert res.status != "PASS"
    # G1 must NOT flag anything: the EQE conflict is resolved (0.18 <= 0.30)
    assert not any("G1" in f for f in res.failed)
    # G4 passes on Table S2 scan directions (|19.23-19.24| = 0.01 <= 0.20)
    assert not any("G4" in f for f in res.failed)
    # G8 must flag the non-identifiable historical fit / missing R/T/A + Rs/Rsh
    assert any("G8" in f for f in res.failed)
    # G5/G7 deferred (DATA_REQUIRED)
    assert any("G5" in d for d in res.deferred)
    assert any("G7" in d for d in res.deferred)


def test_g1_resolved_by_v1_8_s32_digitization():
    """Cycle-2 pin: with the verified champion EQE integrals (S32 3-method
    reproduction of 19.41/20.18), the EQE-vs-Jsc gap is 0.18 mA/cm2, inside
    the strict 0.30 tolerance. This documents the conflict resolution at
    gate level (audit A.6; reconciliation B.5)."""
    ev = GateEvidence(
        jsc_jv_ma_cm2=19.23,
        jsc_eqe_ma_cm2=19.41,
        rta_max_dev=None,
        resistance_measured=False,
    )
    res = evaluate_gate(ev)
    assert not any("G1" in f for f in res.failed)
    # and the superseded V1.5 value would have failed G1 (kept as a pin of
    # what the conflict WAS)
    ev_bad = GateEvidence(jsc_jv_ma_cm2=19.23, jsc_eqe_ma_cm2=17.110498)
    res_bad = evaluate_gate(ev_bad)
    assert any("G1" in f for f in res_bad.failed)


def test_synthetic_constrained_evidence_passes():
    """A synthetic fully-constrained evidence set (known-answer) must PASS,
    proving the gate is achievable and not self-contradictory."""
    from apmt.genealogy import Linkage, LinkageClass
    ev = GateEvidence(
        jsc_jv_ma_cm2=20.00,
        jsc_eqe_ma_cm2=19.95,
        jsc_certified_ma_cm2=20.01,
        jv_rmse_ma_cm2=0.40,
        jsc_scan_dir1_ma_cm2=20.00,
        jsc_scan_dir2_ma_cm2=19.99,
        rta_max_dev=0.02,
        linkages=(Linkage("D1", "D2", LinkageClass.SERIAL_LEVEL_LINKAGE,
                          "serial match", serial_available=True,
                          serial_a="SYN-1", serial_b="SYN-1"),),
        resistance_measured=True,
        condition_number=850.0,
        boundary_hits=0,
        untraced_numeric_claims=0,
    )
    res = evaluate_gate(ev)
    assert res.status == "PASS"
    assert res.failed == () and res.deferred == ()


def test_relaxation_requires_new_threshold_object():
    """Documented pattern: never edit defaults in place."""
    th = GateThresholds()
    strict = th.jsc_eqe_abs_tol_ma_cm2
    relaxed = GateThresholds(jsc_eqe_abs_tol_ma_cm2=5.0)
    assert relaxed.jsc_eqe_abs_tol_ma_cm2 != strict
    assert th.jsc_eqe_abs_tol_ma_cm2 == strict  # defaults immutable


def test_gate_spec_json_roundtrip():
    spec = gate_spec_json()
    s = json.dumps(spec)
    back = json.loads(s)
    assert back["strict"] is True
    assert back["thresholds"]["G8_condition_number_max"] == 1.0e4
