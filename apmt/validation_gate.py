"""APMT V1.8 — strict conventional-baseline validation gate (Objective E).

PASS only when independent evidence sufficiently constrains the conventional
baseline. Otherwise FAIL / DEFER. The gate is deliberately strict and is
machine-evaluated; loosening any threshold requires an explicit, recorded
justification (this file is the single source of truth for thresholds).

Checks
------
G1  EQE-integral agreement: |Jsc(J-V) - Jsc(EQE)| within tolerance
G2  Jsc agreement: certified/author Jsc vs measured within tolerance
G3  J-V curve agreement: digitized/replicated JV RMSE within tolerance
G4  Scan-direction separation: |Jsc_dir1 - Jsc_dir2| within tolerance
G5  Optical closure: |R+T+A-1| within tolerance at every wavelength (full stack)
G6  Device genealogy completeness: every device pair used has a linkage class
    >= CERTIFIED_CHAMPION_CONTEXT_LINKAGE; NO_SERIAL_ID tolerated with flag
G7  External resistance constraints: Rs/Rsh (or equivalent) measured, not fitted
G8  Parameter identifiability: fit condition number and boundary-hit policy
G9  Source/figure consistency: every numeric claim has a ProvenanceRecord
    whose source actually contains the claim (locator verified)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .genealogy import Linkage, LinkageClass


@dataclass(frozen=True)
class GateThresholds:
    # Defaults are STRICT; any relaxation must be recorded as a new threshold
    # object with justification (never edit in place).
    jsc_eqe_abs_tol_ma_cm2: float = 0.30      # G1
    jsc_abs_tol_ma_cm2: float = 0.20          # G2
    jv_rmse_tol_ma_cm2: float = 1.00          # G3 (V1.4 certified JV RMSE 0.9170 passed 'PASS_IF_CONTEXTUALIZED')
    scan_dir_tol_ma_cm2: float = 0.20         # G4
    rta_closure_tol: float = 0.05             # G5 (5% of full scale per wavelength)
    min_linkage_class: LinkageClass = LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE  # G6
    condition_number_max: float = 1.0e4       # G8 (V1.4 fit: 1.216e6 -> would FAIL)
    boundary_hits_max: int = 0                # G8: any bound-hit parameter = non-identifiable
    req_resistance_measured: bool = True      # G7


@dataclass
class GateEvidence:
    """Evidence inputs to the gate. All None/missing => gate cannot PASS."""
    jsc_jv_ma_cm2: Optional[float] = None
    jsc_eqe_ma_cm2: Optional[float] = None
    jsc_certified_ma_cm2: Optional[float] = None
    jv_rmse_ma_cm2: Optional[float] = None
    jsc_scan_dir1_ma_cm2: Optional[float] = None
    jsc_scan_dir2_ma_cm2: Optional[float] = None
    rta_max_dev: Optional[float] = None            # max |R+T+A-1| over wavelength
    linkages: tuple = field(default_factory=tuple)  # Linkage objects for all pairs used
    resistance_measured: bool = False              # Rs/Rsh from external measurement
    condition_number: Optional[float] = None
    boundary_hits: int = 0
    untraced_numeric_claims: int = 0               # G9
    notes: str = ""


@dataclass(frozen=True)
class GateResult:
    status: str                 # PASS | FAIL | DEFER
    failed: tuple
    deferred: tuple
    flags: tuple
    notes: str = ""


def evaluate_gate(ev: GateEvidence, th: GateThresholds = GateThresholds()) -> GateResult:
    failed, deferred, flags = [], [], []

    # G1
    if ev.jsc_jv_ma_cm2 is None or ev.jsc_eqe_ma_cm2 is None:
        deferred.append("G1-EQE-integral-agreement: missing Jsc(J-V) or Jsc(EQE)")
    else:
        if abs(ev.jsc_jv_ma_cm2 - ev.jsc_eqe_ma_cm2) > th.jsc_eqe_abs_tol_ma_cm2:
            failed.append(f"G1-EQE-integral-agreement: |{ev.jsc_jv_ma_cm2}-{ev.jsc_eqe_ma_cm2}| > {th.jsc_eqe_abs_tol_ma_cm2}")
    # G2
    if ev.jsc_certified_ma_cm2 is None:
        deferred.append("G2-Jsc-agreement: certified Jsc not provided")
    elif ev.jsc_jv_ma_cm2 is None:
        deferred.append("G2-Jsc-agreement: measured Jsc not provided")
    elif abs(ev.jsc_certified_ma_cm2 - ev.jsc_jv_ma_cm2) > th.jsc_abs_tol_ma_cm2:
        failed.append(f"G2-Jsc-agreement: |{ev.jsc_certified_ma_cm2}-{ev.jsc_jv_ma_cm2}| > {th.jsc_abs_tol_ma_cm2}")
    # G3
    if ev.jv_rmse_ma_cm2 is None:
        deferred.append("G3-JV-curve-agreement: no digitized/replicated JV comparison")
    elif ev.jv_rmse_ma_cm2 > th.jv_rmse_tol_ma_cm2:
        failed.append(f"G3-JV-curve-agreement: RMSE {ev.jv_rmse_ma_cm2} > {th.jv_rmse_tol_ma_cm2}")
    # G4
    if ev.jsc_scan_dir1_ma_cm2 is None or ev.jsc_scan_dir2_ma_cm2 is None:
        deferred.append("G4-scan-direction: single-direction data only")
    elif abs(ev.jsc_scan_dir1_ma_cm2 - ev.jsc_scan_dir2_ma_cm2) > th.scan_dir_tol_ma_cm2:
        failed.append(f"G4-scan-direction: |{ev.jsc_scan_dir1_ma_cm2}-{ev.jsc_scan_dir2_ma_cm2}| > {th.scan_dir_tol_ma_cm2}")
    # G5
    if ev.rta_max_dev is None:
        deferred.append("G5-R/T/A-closure: full-stack R/T/A data DATA_REQUIRED")
    elif ev.rta_max_dev > th.rta_closure_tol:
        failed.append(f"G5-R/T/A-closure: max|R+T+A-1| {ev.rta_max_dev} > {th.rta_closure_tol}")
    # G6
    if not ev.linkages:
        deferred.append("G6-genealogy: no linkage records provided")
    for lk in ev.linkages:
        if lk.linkage_class < th.min_linkage_class:
            failed.append(f"G6-genealogy: {lk.device_a}<->{lk.device_b} linkage {lk.linkage_class.name} < {th.min_linkage_class.name}")
        if not lk.serial_available:
            flags.append(f"G6-genealogy: {lk.device_a}<->{lk.device_b} NO_SERIAL_ID (context-level evidence)")
    # G7
    if th.req_resistance_measured and not ev.resistance_measured:
        deferred.append("G7-external-resistances: Rs/Rsh not externally measured (DATA_REQUIRED)")
    # G8
    if ev.condition_number is None:
        deferred.append("G8-identifiability: no fit diagnostics provided")
    else:
        if ev.condition_number > th.condition_number_max:
            failed.append(f"G8-identifiability: condition number {ev.condition_number:.3e} > {th.condition_number_max:.1e}")
        if ev.boundary_hits > th.boundary_hits_max:
            failed.append(f"G8-identifiability: {ev.boundary_hits} parameters at bounds (data insufficiency, not measurements)")
    # G9
    if ev.untraced_numeric_claims > 0:
        failed.append(f"G9-source-consistency: {ev.untraced_numeric_claims} numeric claims lack verified provenance")

    if failed:
        status = "FAIL"
    elif deferred:
        status = "DEFER"
    else:
        status = "PASS"
    return GateResult(status, tuple(failed), tuple(deferred), tuple(flags), ev.notes)


def gate_spec_json(th: GateThresholds = GateThresholds()) -> dict:
    """Machine-readable gate specification (deliverable v1.8_validation_gate.json)."""
    return {
        "gate": "APMT conventional-baseline validation gate",
        "version": "1.8",
        "policy": "PASS only when independent evidence sufficiently constrains the conventional baseline; otherwise FAIL/DEFER. No APMT efficiency claim while gate is not PASS.",
        "strict": True,
        "thresholds": {
            "G1_jsc_eqe_abs_tol_ma_cm2": th.jsc_eqe_abs_tol_ma_cm2,
            "G2_jsc_abs_tol_ma_cm2": th.jsc_abs_tol_ma_cm2,
            "G3_jv_rmse_tol_ma_cm2": th.jv_rmse_tol_ma_cm2,
            "G4_scan_dir_tol_ma_cm2": th.scan_dir_tol_ma_cm2,
            "G5_rta_closure_tol": th.rta_closure_tol,
            "G6_min_linkage_class": th.min_linkage_class.name,
            "G7_resistance_must_be_measured": th.req_resistance_measured,
            "G8_condition_number_max": th.condition_number_max,
            "G8_boundary_hits_max": th.boundary_hits_max,
            "G9_all_claims_must_have_verified_provenance": True,
        },
        "checks": [
            "G1 EQE-integral agreement |Jsc(J-V)-Jsc(EQE)|",
            "G2 Jsc agreement vs certified value",
            "G3 J-V curve agreement (RMSE)",
            "G4 scan-direction separation",
            "G5 R+T+A=1 full-stack optical closure",
            "G6 device genealogy completeness (linkage classes)",
            "G7 external resistance constraints (Rs/Rsh measured)",
            "G8 parameter identifiability (condition number, boundary hits)",
            "G9 source/figure consistency (provenance for every claim)",
        ],
        "notes": [
            "Threshold relaxations require a new GateThresholds object with recorded justification.",
            "NO_SERIAL_ID at context-level linkage is flagged, not failing, because primary sources lack serial IDs; serial-level data is DATA_REQUIRED for full closure.",
        ],
    }
