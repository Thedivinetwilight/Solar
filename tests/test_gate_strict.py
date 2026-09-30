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
    """Current known evidence for the conventional baseline:
    certified Jsc 19.23 (SOURCE-REPORTED), best digitized EQE integrals
    17.110498 / 16.901937 (DIGITIZED), reported Si Jph 20.18 (SOURCE-REPORTED),
    no full-stack R/T/A, no external Rs/Rsh, V1.4 fit condition number
    1,216,249.34 with boundary hits. The gate must NOT pass."""
    ev = GateEvidence(
        jsc_jv_ma_cm2=19.23,
        jsc_eqe_ma_cm2=17.110498,   # best digitized Si+perovskite-limited value (S32)
        jsc_certified_ma_cm2=19.23,
        jv_rmse_ma_cm2=0.9170,      # V1.4 certified JV digitization RMSE
        jsc_scan_dir1_ma_cm2=19.35,  # V1.5 Fig S31 Jsc->Voc
        jsc_scan_dir2_ma_cm2=19.36,  # V1.5 Fig S31 Voc->Jsc
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
    # G1 must flag the unresolved EQE conflict: 19.23 vs 17.11 gap 2.12 > 0.30
    assert any("G1" in f for f in res.failed)
    # G8 must flag the non-identifiable historical fit
    assert any("G8" in f for f in res.failed)


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
                          "serial match", serial_available=True),),
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
