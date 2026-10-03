"""APMT V1.9 — baseline validation gate with explicit, machine-checkable state.

Audit item A of the V1.9 directive: the V1.8 artefact stored
``gate_state = "CLOSED (DEFER)"`` while the V1.8 evaluator logically returns
``FAIL`` on the same evidence (G8 identifiability fails). Any such mismatch
makes the gate untrustworthy. V1.9 therefore separates four things that were
previously conflated:

    evaluation_result   PASS | FAIL | INCOMPLETE     (logic over the checks)
    gate_open           bool                        (policy: only PASS opens it)
    blocking_checks     the checks that block opening, with reasons
    data_required       the checks that cannot be evaluated without new data

Every check returns a :class:`CheckResult` carrying the *evidence values* it
used, so a reviewer can re-derive the outcome. Thresholds remain the strict
V1.8 values; this module does not relax anything, and it can load the V1.8
thresholds and status file for a consistency audit.

Checks (unchanged semantics from V1.8, upgraded evidence handling):

    G1  |Jsc(J-V) - Jsc(EQE)| within tolerance
    G2  certified vs measured Jsc
    G3  J-V curve RMSE
    G4  scan-direction separation
    G5  full-stack optical closure  -- now consumes an OpticalClosureEvidence
        object (grid, coverage, alignment, units, uncertainty, missing regions)
    G6  device genealogy (linkage classes) -- serial-level evidence required
    G7  external Rs/Rsh measured (not fitted)
    G8  parameter identifiability (condition number, boundary hits)
    G9  provenance of every numeric claim -- consumes a ProvenanceAudit
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional, Sequence

from ..genealogy import Linkage, LinkageClass

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V18_GATE_JSON = os.path.join(_REPO, "v1.8_validation_gate.json")


@dataclass(frozen=True)
class GateThresholds:
    """Strict thresholds. Defaults are the V1.8 values (never edited in place)."""

    jsc_eqe_abs_tol_ma_cm2: float = 0.30
    jsc_abs_tol_ma_cm2: float = 0.20
    jv_rmse_tol_ma_cm2: float = 1.00
    scan_dir_tol_ma_cm2: float = 0.20
    rta_closure_tol: float = 0.05
    min_linkage_class: LinkageClass = LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE
    condition_number_max: float = 1.0e4
    boundary_hits_max: int = 0
    req_resistance_measured: bool = True
    version: str = "1.9-strict-v1.8-thresholds"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["min_linkage_class"] = self.min_linkage_class.name
        return d


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one gate check with the evidence that produced it."""

    check_id: str
    outcome: str                 # PASS | FAIL | DATA_REQUIRED | NOT_EVALUABLE
    message: str
    evidence: dict = field(default_factory=dict)
    required_action: str = ""

    @property
    def blocking(self) -> bool:
        """A check blocks gate opening unless it passes."""
        return self.outcome != "PASS"

    def to_dict(self) -> dict:
        return {"check_id": self.check_id, "outcome": self.outcome,
                "message": self.message, "evidence": self.evidence,
                "required_action": self.required_action}


@dataclass(frozen=True)
class GateEvaluation:
    evaluation_result: str       # PASS | FAIL | INCOMPLETE
    gate_open: bool
    checks: tuple
    flags: tuple = ()
    notes: str = ""
    thresholds: dict = field(default_factory=dict)

    @property
    def blocking_checks(self) -> tuple:
        return tuple(c for c in self.checks if c.blocking)

    @property
    def data_required(self) -> tuple:
        return tuple(c for c in self.checks if c.outcome == "DATA_REQUIRED")

    def to_dict(self) -> dict:
        return {
            "evaluation_result": self.evaluation_result,
            "gate_open": self.gate_open,
            "flags": list(self.flags),
            "notes": self.notes,
            "thresholds": self.thresholds,
            "blocking_checks": [c.to_dict() for c in self.blocking_checks],
            "data_required": [c.to_dict() for c in self.data_required],
            "checks": [c.to_dict() for c in self.checks],
            "not_evaluable": [c.to_dict() for c in self.checks
                              if c.outcome == "NOT_EVALUABLE"],
        }


# ---------------------------------------------------------------------------
# Evidence container
# ---------------------------------------------------------------------------
@dataclass
class GateEvidence:
    """All evidence inputs. ``None`` means "not provided" -> DATA_REQUIRED."""

    jsc_jv_ma_cm2: Optional[float] = None
    jsc_eqe_ma_cm2: Optional[float] = None
    jsc_certified_ma_cm2: Optional[float] = None
    jv_rmse_ma_cm2: Optional[float] = None
    jv_rmse_category: str = "HANDOFF-QUOTED"
    jsc_scan_dir1_ma_cm2: Optional[float] = None
    jsc_scan_dir2_ma_cm2: Optional[float] = None
    linkages: tuple = field(default_factory=tuple)
    resistance_measured: bool = False
    resistance_evidence: Optional[object] = None       # ResistanceEvidence
    condition_number: Optional[float] = None
    boundary_hits: int = 0
    identifiability_evidence: Optional[object] = None  # IdentifiabilityEvidence
    optical_evidence: Optional[object] = None          # OpticalClosureEvidence
    provenance_audit: Optional[object] = None          # ProvenanceAudit
    notes: str = ""

    def __post_init__(self):
        for name in ("optical_evidence", "provenance_audit", "resistance_evidence",
                     "identifiability_evidence"):
            obj = getattr(self, name)
            if obj is not None and not hasattr(obj, "to_dict"):
                raise TypeError(f"{name} must expose to_dict(); got {type(obj)!r}")


def evaluate_gate(ev: GateEvidence, th: Optional[GateThresholds] = None) -> GateEvaluation:
    """Evaluate every check and derive the gate state deterministically."""
    th = th or GateThresholds()
    checks = []

    # ---- G1 ---------------------------------------------------------------
    if ev.jsc_jv_ma_cm2 is None or ev.jsc_eqe_ma_cm2 is None:
        checks.append(CheckResult("G1", "DATA_REQUIRED",
                                  "Jsc(J-V) and Jsc(EQE) both required",
                                  {}, "provide same-device J-V and EQE integrals"))
    else:
        d = abs(ev.jsc_jv_ma_cm2 - ev.jsc_eqe_ma_cm2)
        checks.append(CheckResult(
            "G1", "PASS" if d <= th.jsc_eqe_abs_tol_ma_cm2 else "FAIL",
            f"|Jsc(J-V) - Jsc(EQE)| = {d:.3f} mA/cm2 (tol "
            f"{th.jsc_eqe_abs_tol_ma_cm2})",
            {"jsc_jv": ev.jsc_jv_ma_cm2, "jsc_eqe": ev.jsc_eqe_ma_cm2,
             "difference": d, "tolerance": th.jsc_eqe_abs_tol_ma_cm2}))

    # ---- G2 ---------------------------------------------------------------
    if ev.jsc_certified_ma_cm2 is None or ev.jsc_jv_ma_cm2 is None:
        checks.append(CheckResult("G2", "DATA_REQUIRED",
                                  "certified and measured Jsc both required", {},
                                  "obtain machine-readable certified J-V"))
    else:
        d = abs(ev.jsc_certified_ma_cm2 - ev.jsc_jv_ma_cm2)
        checks.append(CheckResult(
            "G2", "PASS" if d <= th.jsc_abs_tol_ma_cm2 else "FAIL",
            f"|certified - measured| Jsc = {d:.3f} mA/cm2 (tol "
            f"{th.jsc_abs_tol_ma_cm2})",
            {"certified": ev.jsc_certified_ma_cm2, "measured": ev.jsc_jv_ma_cm2,
             "difference": d}))

    # ---- G3 ---------------------------------------------------------------
    if ev.jv_rmse_ma_cm2 is None:
        checks.append(CheckResult("G3", "DATA_REQUIRED",
                                  "no digitized/replicated J-V comparison", {},
                                  "provide machine-readable J-V curves"))
    else:
        checks.append(CheckResult(
            "G3", "PASS" if ev.jv_rmse_ma_cm2 <= th.jv_rmse_tol_ma_cm2 else "FAIL",
            f"J-V RMSE {ev.jv_rmse_ma_cm2:.3f} mA/cm2 (tol {th.jv_rmse_tol_ma_cm2}); "
            f"provenance category {ev.jv_rmse_category}",
            {"rmse": ev.jv_rmse_ma_cm2, "category": ev.jv_rmse_category,
             "tolerance": th.jv_rmse_tol_ma_cm2}))

    # ---- G4 ---------------------------------------------------------------
    if ev.jsc_scan_dir1_ma_cm2 is None or ev.jsc_scan_dir2_ma_cm2 is None:
        checks.append(CheckResult("G4", "DATA_REQUIRED",
                                  "single scan direction only", {},
                                  "provide both scan directions"))
    else:
        d = abs(ev.jsc_scan_dir1_ma_cm2 - ev.jsc_scan_dir2_ma_cm2)
        checks.append(CheckResult(
            "G4", "PASS" if d <= th.scan_dir_tol_ma_cm2 else "FAIL",
            f"scan-direction |dJsc| = {d:.3f} mA/cm2 (tol {th.scan_dir_tol_ma_cm2})",
            {"dir1": ev.jsc_scan_dir1_ma_cm2, "dir2": ev.jsc_scan_dir2_ma_cm2,
             "difference": d}))

    # ---- G5 (optical closure, machine-checkable evidence object) ----------
    if ev.optical_evidence is None:
        checks.append(CheckResult("G5", "DATA_REQUIRED",
                                  "full-stack R/T/A evidence not provided", {},
                                  "measure complete-stack R/T/A with a "
                                  "calibrated spectrophotometer"))
    else:
        oe = ev.optical_evidence
        ok = bool(oe.is_valid_full_stack()) and \
            float(oe.max_closure_error()) <= th.rta_closure_tol
        checks.append(CheckResult(
            "G5", "PASS" if ok else "FAIL",
            (f"max|R+T+A-1| = {oe.max_closure_error():.4f} (tol {th.rta_closure_tol}); "
             f"coverage {oe.coverage_fraction(300, 1250):.2f} of 300-1250 nm; "
             f"grid aligned={oe.aligned}; units_declared={oe.units_declared}; "
             f"uncertainty_present={oe.uncertainty_present}; "
             f"missing_regions={oe.missing_regions_nm}"),
            oe.to_dict(),
            "supply complete-stack R/T/A on one aligned grid with uncertainties"))

    # ---- G6 (genealogy) ---------------------------------------------------
    if not ev.linkages:
        checks.append(CheckResult("G6", "DATA_REQUIRED",
                                  "no linkage records provided", {},
                                  "provide device genealogy records"))
    else:
        flags = []
        bad = []
        for lk in ev.linkages:
            if lk.linkage_class < th.min_linkage_class:
                bad.append(f"{lk.device_a}<->{lk.device_b}: {lk.linkage_class.name}")
            if lk.linkage_class == LinkageClass.SERIAL_LEVEL_LINKAGE and not lk.serial_available:
                bad.append(f"{lk.device_a}<->{lk.device_b}: SERIAL_LEVEL_LINKAGE "
                           f"without serial availability (forbidden)")
            if not lk.serial_available:
                flags.append(f"{lk.device_a}<->{lk.device_b}: NO_SERIAL_ID")
        checks.append(CheckResult(
            "G6", "FAIL" if bad else "PASS",
            ("linkage classes below the minimum: " + "; ".join(bad)) if bad
            else f"all {len(ev.linkages)} linkages at or above {th.min_linkage_class.name}",
            {"n_linkages": len(ev.linkages), "violations": bad, "flags": flags}))

    # ---- G7 (external resistance measurement) -----------------------------
    if not ev.resistance_measured or ev.resistance_evidence is None:
        checks.append(CheckResult(
            "G7", "DATA_REQUIRED",
            "Rs/Rsh not externally measured", {},
            "measure Rs/Rsh externally (dark J-V, Suns-Voc, Jsc-Voc)"))
    else:
        re_ = ev.resistance_evidence
        ok = bool(re_.is_external()) and re_.has_value()
        checks.append(CheckResult(
            "G7", "PASS" if ok else "FAIL",
            f"Rs/Rsh source {re_.method!r}, external={re_.is_external()}",
            re_.to_dict(),
            "the resistance must come from a measurement, not a model fit"))

    # ---- G8 (identifiability) --------------------------------------------
    if ev.identifiability_evidence is None:
        checks.append(CheckResult("G8", "DATA_REQUIRED",
                                  "no identifiability diagnostics provided", {},
                                  "provide Jacobian/condition diagnostics from a "
                                  "constrained fit"))
    else:
        ie = ev.identifiability_evidence
        kappa = float(ie.condition_number)
        hits = int(ie.boundary_hits)
        ok = kappa <= th.condition_number_max and hits <= th.boundary_hits_max
        checks.append(CheckResult(
            "G8", "PASS" if ok else "FAIL",
            (f"condition number {kappa:.3e} (max {th.condition_number_max:.1e}), "
             f"boundary hits {hits} (max {th.boundary_hits_max})"
             + (f"; largest correlation {ie.max_parameter_correlation:.3f}"
                if hasattr(ie, "max_parameter_correlation") else "")),
            ie.to_dict(),
            "add independent measurements (R/T/A, Rs/Rsh, same-device EQE) to "
            "reduce parameter correlation"))
    if ev.condition_number is not None and ev.identifiability_evidence is None:
        # legacy path: a bare number is accepted but flagged, never treated as
        # full identifiability evidence (audit item A/E principle)
        checks[-1] = CheckResult(
            "G8", "FAIL" if ev.condition_number > th.condition_number_max else
            "DATA_REQUIRED",
            f"legacy scalar condition number {ev.condition_number:.3e} provided "
            f"without identifiability evidence object",
            {"condition_number": ev.condition_number,
             "boundary_hits": ev.boundary_hits, "legacy": True},
            "supply IdentifiabilityEvidence from a real fit")

    # ---- G9 (provenance audit) -------------------------------------------
    if ev.provenance_audit is None:
        checks.append(CheckResult("G9", "DATA_REQUIRED",
                                  "no machine-checkable provenance audit provided",
                                  {}, "run apmt.validation.provenance_gate.audit"))
    else:
        pa = ev.provenance_audit
        ok = bool(pa.all_claims_verified())
        checks.append(CheckResult(
            "G9", "PASS" if ok else "FAIL",
            (f"{pa.n_verified}/{pa.n_claims} claims verified; "
             f"{len(pa.hash_mismatches)} hash mismatches, "
             f"{len(pa.missing_sources)} missing sources, "
             f"{len(pa.category_violations)} category violations"),
            pa.to_dict(),
            "fix the provenance violations listed in the audit"))

    # ---- derive state -----------------------------------------------------
    outcomes = {c.outcome for c in checks}
    if "FAIL" in outcomes:
        evaluation_result = "FAIL"
    elif outcomes == {"PASS"}:
        evaluation_result = "PASS"
    else:
        evaluation_result = "INCOMPLETE"
    gate_open = evaluation_result == "PASS"
    flags = tuple(f for c in checks for f in c.evidence.get("flags", []) if
                  c.check_id == "G6")
    return GateEvaluation(evaluation_result, gate_open, tuple(checks), flags,
                          ev.notes, th.to_dict())


def gate_state_from_v18_file() -> dict:
    """Load the stored V1.8 gate state (for inconsistency auditing)."""
    with open(V18_GATE_JSON) as f:
        return json.load(f)


def audit_v18_gate_consistency(ev: GateEvidence,
                               th: Optional[GateThresholds] = None) -> dict:
    """Compare the stored V1.8 gate status with what the evaluator returns.

    Returns a machine-checkable report; ``consistent`` is False when the stored
    state claims a different logic outcome than the evaluator produces.
    """
    stored = gate_state_from_v18_file().get("status_as_of_v1_8_cycle2_2026_10_01", {})
    stored_state = str(stored.get("gate_state", ""))
    result = evaluate_gate(ev, th)
    # V1.8 stored 'CLOSED (DEFER)', i.e. it claimed a deferred gate while the
    # evaluator returns FAIL on the same evidence (G8 non-identifiability).
    if "DEFER" in stored_state.upper():
        claimed_logic = "INCOMPLETE"
    elif "FAIL" in stored_state.upper():
        claimed_logic = "FAIL"
    elif "PASS" in stored_state.upper():
        claimed_logic = "PASS"
    else:
        claimed_logic = "UNKNOWN"
    return {
        "stored_gate_state": stored_state,
        "stored_claimed_logic": claimed_logic,
        "evaluated_result": result.evaluation_result,
        "gate_open": result.gate_open,
        "consistent": claimed_logic == result.evaluation_result,
        "blocking_checks": [c.check_id for c in result.blocking_checks],
        "data_required": [c.check_id for c in result.data_required],
    }
