"""APMT V1.8 — historical numbers ledger.

Carries forward V1.3-V1.7 numbers verbatim as quoted in the authoritative
handoff (INCOMING/APMT_FULL_NEW_CHAT_HANDOFF_CONTEXT.txt,
sha256 766f573d...). Category: HANDOFF-QUOTED — the original artifacts
(v15/v16/v17 reports, digitized curve files) are NOT present in this
repository and are marked MISSING-VERIFIED; nothing here is a fresh
measurement.

The known-answer test (tests/test_ledger_unchanged.py) pins these values so
no silent historical-number changes can occur in V1.8.
"""
from __future__ import annotations

from .provenance import ProvenanceCategory

HANDOFF_SHA256 = "766f573d6c6054c47a3f7b6a7b5f76b6490f71916f3053c208b3cec9fb506c02"

# (version, quantity) -> (value, units, notes)
HISTORICAL_LEDGER = {
    # ---- V1.1 (model, incomplete data; NOT experimental claims) ----
    ("V1.1", "silicon_baseline_model_pct"): (23.402, "%", "MODEL-OBSERVED, INCONCLUSIVE"),
    ("V1.1", "tandem_model_pct"): (15.544, "%", "MODEL-OBSERVED, INCONCLUSIVE"),
    ("V1.1", "integrated_irradiance_w_m2"): (1000.370656, "W/m2", "REPRODUCED bit-exact in V1.8 (apmt.spectrum)"),
    # ---- V1.2 / V1.2.2 ----
    ("V1.2", "ref_pce_pct"): (29.15, "%", "reference/experimental, Al-Ashouri 2020"),
    ("V1.2", "ref_jsc"): (19.8, "mA/cm2", "reference/experimental"),
    ("V1.2", "ref_voc_v"): (1.92, "V", "reference/experimental"),
    ("V1.2", "ref_ff"): (0.7668, "", "reference/experimental"),
    ("V1.2.2", "calibrated_pce_pct"): (23.63256, "%", "DATA-LIMITED calibration"),
    ("V1.2.2", "calibrated_jsc"): (12.27268, "mA/cm2", "many parameters at bounds"),
    ("V1.2.2", "calibrated_voc_v"): (2.21479, "V", ""),
    ("V1.2.2", "calibrated_ff"): (0.869760, "", ""),
    ("V1.2.2", "incident_photon_current"): (68.982857, "mA/cm2", "REPRODUCED bit-exact in V1.8 (100% EQE, 280-5000 nm)"),
    # ---- V1.3 (frozen baseline; MODEL-OBSERVED / ASSUMPTION-DEPENDENT) ----
    ("V1.3", "baseline_pce_pct"): (23.633, "%", "MODEL-OBSERVED / ASSUMPTION-DEPENDENT"),
    ("V1.3", "full_apmt_pce_pct"): (24.242, "%", "MODEL-OBSERVED / ASSUMPTION-DEPENDENT"),
    ("V1.3", "delta_pp"): (0.610, "pp", "relative +2.58%; NEVER an experimental claim"),
    # ---- V1.4 (primary evidence reconstruction) ----
    ("V1.4", "certified_jv_digitized_rmse"): (0.9170, "mA/cm2", "RMSE vs digitized certified JV"),
    ("V1.4", "certified_jv_norm_rmse"): (0.047897, "", "PASS_IF_CONTEXTUALIZED"),
    ("V1.4", "top_eqe_graphical_integral"): (19.984, "mA/cm2", "DIGITIZED, Fig 4E perovskite branch"),
    ("V1.4", "bottom_eqe_graphical_integral"): (16.902, "mA/cm2", "DIGITIZED, FAIL_CURVE_INTEGRAL_DISCREPANCY"),
    ("V1.4", "bottom_eqe_reported"): (20.18, "mA/cm2", "SOURCE-REPORTED"),
    ("V1.4", "candidate_fit_pce_pct"): (30.34048, "%", "model-fit candidate, NOT a measurement"),
    # ---- V1.5 ----
    ("V1.5", "s32_graphical_integral"): (17.110498, "mA/cm2", "DIGITIZED, 300-1250 nm"),
    ("V1.5", "s32_required_scale_factor"): (1.1793929, "x", "NOT applied (unsupported)"),
    ("V1.5", "certified_inhouse_jv_j2v_jsc"): (19.35, "mA/cm2", "Fig S31, Jsc->Voc scan"),
    ("V1.5", "certified_inhouse_jv_v2j_jsc"): (19.36, "mA/cm2", "Fig S31, Voc->Jsc scan"),
    ("V1.5", "certified_inhouse_jv_j2v_pce_pct"): (29.00, "%", "Fig S31, Jsc->Voc"),
    ("V1.5", "certified_inhouse_jv_v2j_pce_pct"): (29.14, "%", "Fig S31, Voc->Jsc"),
    # ---- V1.6 (forensics) ----
    ("V1.6", "s32_integral_full_precision"): (17.1104981189, "mA/cm2", "DIGITIZED"),
    ("V1.6", "fig4e_reconstruction"): (16.9019365812, "mA/cm2", "DIGITIZED, independent route"),
    ("V1.6", "gap_s32"): (3.069502, "mA/cm2", "20.18 - 17.110498"),
    ("V1.6", "gap_fig4e"): (3.278063, "mA/cm2", "20.18 - 16.901937"),
    ("V1.6", "digitization_uncertainty_band_s32"): (16.6105, "mA/cm2", "band floor (band top ~17.6105)"),
    ("V1.6", "one_minus_r_proxy_integral"): (42.714137, "mA/cm2", "1-R is NOT absorption; never merged with EQE"),
    ("V1.6", "scenario_pce_20p18_pct"): (30.636, "%", "SCENARIO/model-fit, NOT measured"),
    ("V1.6", "scenario_pce_17p11_pct"): (27.007, "%", "SCENARIO/model-fit, NOT measured"),
    ("V1.6", "scenario_pce_16p90_pct"): (26.677, "%", "SCENARIO/model-fit, NOT measured"),
    ("V1.6", "scenario_pce_19p23_pct"): (30.352, "%", "SCENARIO/model-fit, NOT measured"),
}

STATUS_LEDGER = {
    "SOFTWARE_STATUS": "research-grade experimental-data-ready",
    "BASELINE_STATUS": "DATA-LIMITED",
    "APMT_STATUS": "BLOCKED_BY_BASELINE_VALIDATION",
    "EXPERIMENT_READINESS": "software ready; controlled APMT attribution not yet justified",
}


def ledger_category() -> ProvenanceCategory:
    return ProvenanceCategory.HANDOFF_QUOTED


def get(version: str, quantity: str):
    return HISTORICAL_LEDGER[(version, quantity)]
