"""V1.9 audit tests: gate evidence objects, provenance audit, genealogy hardening.

These tests pin the *audit findings* themselves, so that the defects the V1.9
directive asks about cannot silently reappear:

* A  the stored V1.8 gate state disagrees with the V1.8 evaluator on the same
     evidence (``consistent is False``);
* D  a synthetic SERIAL_LEVEL_LINKAGE label can no longer bypass the serial
     evidence requirement;
* E  G9 consumes a machine-checkable audit, not a caller-supplied counter;
* F  G5 consumes a full R/T/A evidence object (grid, coverage, units,
     uncertainty, missing regions), not a scalar.
"""
import numpy as np
import pytest

from apmt.genealogy import GENEALOGY_LINKAGES, InvalidLinkageError, Linkage, LinkageClass
from apmt.validation.gate import (
    GateEvidence,
    GateThresholds,
    audit_v18_gate_consistency,
    evaluate_gate,
)
from apmt.validation.identifiability import IdentifiabilityEvidence, ResistanceEvidence
from apmt.validation.optical_evidence import (
    OpticalClosureEvidence,
    synthetic_evidence,
)
from apmt.validation.provenance_gate import (
    Claim,
    audit_claims,
    audit_manifest_integrity,
    ledger_claims,
)

V18_EVIDENCE = dict(
    jsc_jv_ma_cm2=19.23, jsc_eqe_ma_cm2=19.41, jsc_certified_ma_cm2=19.23,
    jv_rmse_ma_cm2=0.9170, jsc_scan_dir1_ma_cm2=19.23,
    jsc_scan_dir2_ma_cm2=19.24, linkages=GENEALOGY_LINKAGES,
    resistance_measured=False, condition_number=1216249.34, boundary_hits=3,
)


def test_audit_a_stored_v18_state_is_inconsistent_with_its_evaluator():
    rep = audit_v18_gate_consistency(GateEvidence(**V18_EVIDENCE))
    assert rep["stored_gate_state"].upper().startswith("CLOSED")
    assert rep["evaluated_result"] == "FAIL"
    assert rep["consistent"] is False
    # the blocking set is exactly the four unresolved blockers + the migrated G9
    assert set(rep["blocking_checks"]) <= {"G5", "G6", "G7", "G8", "G9"}


def test_audit_e_g9_is_not_satisfied_by_a_caller_counter():
    ev = GateEvidence(**V18_EVIDENCE)
    res = evaluate_gate(ev)
    g9 = [c for c in res.checks if c.check_id == "G9"][0]
    assert g9.outcome == "DATA_REQUIRED"     # no audit object -> not evaluable
    assert res.gate_open is False


def test_audit_f_g5_requires_full_stack_evidence_not_a_scalar():
    good = synthetic_evidence(noise=0.0)
    assert good.is_valid_full_stack()
    ev = dict(V18_EVIDENCE)
    ev["optical_evidence"] = good
    res = evaluate_gate(GateEvidence(**ev))
    g5 = [c for c in res.checks if c.check_id == "G5"][0]
    assert g5.outcome == "PASS"

    gapped = synthetic_evidence(missing_window=(500.0, 900.0))
    assert not gapped.is_valid_full_stack()
    ev["optical_evidence"] = gapped
    res = evaluate_gate(GateEvidence(**ev))
    g5 = [c for c in res.checks if c.check_id == "G5"][0]
    assert g5.outcome == "FAIL"
    assert g5.evidence["missing_regions_nm"]        # gap is reported explicitly


def test_optical_evidence_rejects_undeclared_units_and_percent_scale():
    wl = np.linspace(300.0, 1250.0, 200)
    r = np.full_like(wl, 0.2); t = np.full_like(wl, 0.1); a = 1.0 - r - t
    percent = OpticalClosureEvidence(wl, r * 100, t * 100, a * 100, units="percent")
    assert not percent.units_declared
    assert not percent.is_valid_full_stack()


def test_audit_d_serial_linkage_requires_actual_serials():
    with pytest.raises(InvalidLinkageError):
        Linkage("A", "B", LinkageClass.SERIAL_LEVEL_LINKAGE, "claimed", False)
    with pytest.raises(InvalidLinkageError):
        Linkage("A", "B", LinkageClass.SERIAL_LEVEL_LINKAGE, "claimed", True,
                serial_a="S1", serial_b="S2")
    with pytest.raises(InvalidLinkageError):
        Linkage("A", "B", LinkageClass.SERIAL_LEVEL_LINKAGE, "claimed", True)
    ok = Linkage("A", "B", LinkageClass.SERIAL_LEVEL_LINKAGE, "vendor ledger",
                 True, serial_a="S-1", serial_b="S-1")
    assert ok.verified_serial_identity() and ok.allows_merge()
    # a lower-class linkage can never allow a merge
    assert not Linkage("A", "C", LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE,
                       "same batch").allows_merge()


def test_identifiability_evidence_reports_flat_directions():
    ie = IdentifiabilityEvidence(
        condition_number=1.216e6, boundary_hits=3, n_parameters=3, n_data_points=100,
        singular_values=(1.0, 1e-5, 1e-8), parameter_names=("a", "b", "c"),
        correlation_matrix=np.array([[1.0, 0.99, 0.1],
                                     [0.99, 1.0, 0.2],
                                     [0.1, 0.2, 1.0]]))
    d = ie.to_dict()
    assert d["flat_directions"] == 2   # 1e-5 and 1e-8 are both < 1e-3 * s_max
    assert d["max_parameter_correlation"] == pytest.approx(0.99)
    assert d["unidentifiable_pairs"][0]["pair"] == ("a", "b")


def test_resistance_evidence_distinguishes_measured_from_fitted():
    fitted = ResistanceEvidence(method="model_fit", rs_ohm_cm2=1.5)
    assert not fitted.is_external() and fitted.has_value()
    measured = ResistanceEvidence(method="dark_jv_fit_to_measured_curves",
                                  rs_ohm_cm2=1.4, rsh_ohm_cm2=3200.0,
                                  uncertainty_rs_ohm_cm2=0.1)
    assert measured.is_external()
    ev = dict(V18_EVIDENCE); ev["resistance_measured"] = True
    ev["resistance_evidence"] = measured
    res = evaluate_gate(GateEvidence(**ev))
    g7 = [c for c in res.checks if c.check_id == "G7"][0]
    assert g7.outcome == "PASS"


def test_provenance_audit_detects_each_violation_class():
    from apmt.provenance import ProvenanceCategory, SourceRef
    src = SourceRef(source_id="X", description="x", sha256="", access_status="OBTAINED")
    claims = [
        Claim("no_locator", 1.0, "1", ProvenanceCategory.LITERATURE_DERIVED, src, "  "),
        Claim("measured_from_scenario", 1.0, "1", ProvenanceCategory.SCENARIO, src, "fig 1",
              kind="measurement"),
        Claim("measured_from_handoff", 1.0, "1", ProvenanceCategory.HANDOFF_QUOTED, src,
              "ledger", kind="measurement"),
    ]
    rep = audit_claims(claims)
    assert rep.n_claims == 3 and rep.n_verified == 0
    assert not rep.all_claims_verified()
    assert len(rep.missing_locators) == 1
    assert len(rep.category_violations) == 2


def test_ledger_claims_are_honestly_unverifiable():
    """Handoff-quoted historical values must NOT count as verified evidence."""
    rep = audit_claims(ledger_claims())
    assert rep.n_claims > 10
    assert rep.n_verified < rep.n_claims
    assert not rep.all_claims_verified()


def test_v18_manifest_hash_defect_is_recorded_not_hidden():
    rep = audit_manifest_integrity("manifests/v1.8_reproducibility_manifest.json")
    statuses = {f["path"]: f["status"] for f in rep["findings"]}
    assert statuses.get("v1.8_full_report.md") == "V1.8-MANIFEST-DEFECT"
    assert statuses.get("data/sources/al_ashouri_accepted_manuscript.pdf") == \
        "MISSING-FROM-REPOSITORY"
    assert rep["n_verified"] > 30


def test_gate_thresholds_are_frozen_at_v18_values():
    th = GateThresholds()
    assert (th.jsc_eqe_abs_tol_ma_cm2, th.jsc_abs_tol_ma_cm2) == (0.30, 0.20)
    assert (th.jv_rmse_tol_ma_cm2, th.scan_dir_tol_ma_cm2) == (1.00, 0.20)
    assert th.condition_number_max == 1.0e4 and th.boundary_hits_max == 0
    assert th.rta_closure_tol == 0.05
