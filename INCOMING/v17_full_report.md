# APMT V1.7 full report

## 1. Executive summary

# APMT V1.7 executive summary

## SOFTWARE_STATUS

The project now has formal measurement schemas, immutable raw-data handling, ingestion reports, device genealogy/provenance graphs, reusable EQE forensics, optical/electrical constraint modules, scenario propagation, model-form metadata, identifiability artifacts, sensitivity planning, value-of-information ranking, digital-twin serialization, CLI support, synthetic mechanics tests, and reproducibility manifests.

## DATA_STATUS

The primary accepted manuscript, embedded supplements, thesis, repository mirror, local machine-readable inputs, and lawful public search results were reconciled. The official publisher SI remains `ACCESS_BLOCKED` / HTTP 403. No new target-device raw EQE series was recovered.

## BASELINE_STATUS

`DATA-LIMITED`. The reported bottom EQE remains 20.18 mA cm^-2, while independent graphical reconstructions remain 17.110498 and 16.901937 mA cm^-2. The classification remains `UNRESOLVED_DATA_CONFLICT`.

## APMT_STATUS

`BLOCKED_BY_BASELINE_VALIDATION`. No APMT efficiency output was generated.

## EXPERIMENT_READINESS

The software is ready to ingest real future measurements with explicit mappings, provenance, device IDs, checksums, uncertainty fields, and processing histories. The reference-device evidence is not yet ready for a defensible APMT claim.

## TOP_UNRESOLVED_ISSUES

1. Bottom-EQE conflict and current matching.
2. Same-device serial pairing.
3. Complete R(lambda), T(lambda), A(lambda) closure.
4. External dark-JV, Suns-Voc/Jsc-Voc, Rs/Rsh/contact/interconnection constraints.
5. Non-identifiable conventional electrical parameters.

## HIGHEST_VALUE_NEXT_MEASUREMENTS

| rank | measurement | current_uncertainty_contribution | parameters_constrained | output_metrics_affected | identifiability_improvement_potential | APMT_interpretation_impact | dependency_on_unavailable_data | information_gain_method | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | same-device bottom EQE | 2.508063 | Jph bottom, pairing | Jsc,current matching,PCE | 10.0 | YES | highest current conflict and direct gate blocker | scenario_spread_based | PRIORITIZED_NOT_EXPERIMENTALLY_PERFORMED |
| 2 | complete-stack R/T/A | nan | useful/parasitic absorption, closure | Jsc,optical loss,APMT interpretation | 9.2 | YES | exact gain unavailable; blocks optical closure | sensitivity_based_proxy; exact Fisher information unavailable | PRIORITIZED_NOT_EXPERIMENTALLY_PERFORMED |
| 3 | external dark-JV | nan | J0,ideality,Rsh | Voc,FF,recombination | 9.0 | YES | exact gain unavailable; blocks external-loss separation | sensitivity_based_proxy; exact Fisher information unavailable | PRIORITIZED_NOT_EXPERIMENTALLY_PERFORMED |
| 4 | same-device top EQE | nan | top Jph and pairing | Jsc,current matching | 8.1 | YES | pairs both EQE curves to JV | sensitivity_based_proxy; exact Fisher information unavailable | PRIORITIZED_NOT_EXPERIMENTALLY_PERFORMED |
| 5 | Rs/contact/interconnection extraction | nan | resistive loss channels | FF,PCE | 8.0 | YES | prevents fitted Rs absorbing unknowns | sensitivity_based_proxy; exact Fisher information unavailable | PRIORITIZED_NOT_EXPERIMENTALLY_PERFORMED |

## FINAL DECISION

No fabrication or controlled APMT comparison is currently justified. The minimum next evidence is a same-serial top/bottom EQE set linked to the certified JV device, complete-stack optical closure, and external electrical-loss measurements sufficient to make the conventional baseline identifiable.

**After V1.7, what is the minimum remaining evidence required before the APMT architecture can be experimentally tested in a scientifically defensible controlled comparison?**

**Same-device top and bottom EQE with machine-readable spectra and serial-level linkage to the certified JV, together with complete-stack R/T/A closure and external electrical-loss measurements, are the minimum blocking evidence. Until those data are recovered or newly measured, the APMT architecture should not be tested as a scientifically attributable comparison.**


## 2. Starting V1.6 state

`VALIDATION_STATE = DATA-LIMITED`; `APMT_STATUS = BLOCKED_BY_BASELINE_VALIDATION`; bottom EQE remained `UNRESOLVED_DATA_CONFLICT`; complete R/T/A and external electrical losses were `DATA_REQUIRED`; conventional condition number remained approximately 1.216e6.

## 3. New software architecture

V1.7 adds a formal measurement schema, immutable raw/processed separation, CSV/TSV/JSON/XLSX-ready ingestion layer, validators/parsers, device genealogy, provenance graphs, reusable EQE and forensic engines, optical/electrical model interfaces, model-form uncertainty tables, scenario propagation, sensitivity/VOI planning, digital twins, synthetic mechanics data, CLI, and reproducibility artifacts. These improvements make the simulator ready for future experimental data but do not validate the reference device.

## 4. New evidence and source reconciliation

The 281-page thesis, both 69-page article copies, embedded supplementary material, local archives, and lawful public searches were examined. External search results that were unrelated or secondary were not merged. The official SI remains access-blocked.

## 5. Device genealogy and provenance

See `v17_device_genealogy.csv`, `v17_device_genealogy.json`, and `v17_provenance_graph.json`. Unknown serial relationships remain explicit.

## 6. EQE forensic investigation

The reusable engine tested wavelength shifts, stretching, offsets, boundaries, global/direct weighting, normalization, vertical scaling, additive offsets, geometry, branch extraction, interpolation, clipping, overlay handling, truncation, measurement-condition, and dataset-identity hypotheses. The final state remains `UNRESOLVED_DATA_CONFLICT`; no curve was rescaled.

## 7. Optical analysis

`COMPLETE_RTA_STATUS = DATA_REQUIRED`. `1-R` is not treated as absorption. Complete-stack R/T/A and interconnection/parasitic absorption remain unavailable.

## 8. Electrical analysis

External dark-JV, Suns-Voc/Jsc-Voc, direct Rs/Rsh/contact/interconnection data remain `DATA_REQUIRED`. EL pseudo-JV remains internal-voltage context only.

## 9. Conventional model ensemble

Model A reuses the corrected conventional radiative/non-radiative candidate for diagnostics. Model B and Model C are implemented as explicit model-form options but remain `DATA_REQUIRED` without independent dark-JV and resistance constraints. No model is promoted because it produces a higher efficiency.

## 10. Curve validation, identifiability, and robustness

Curve metrics, residual diagnostics, Jacobian rank, singular values, condition number, local correlations, profile likelihood, multi-start spread, bounds, and parameter-combination limitations are retained. The candidate remains non-identifiable/weakly identifiable.

## 11. Sensitivity, uncertainty, and scenario propagation

The 20.18, 17.110498, 16.901937, and certified-Jsc scenarios are propagated separately. Scenario spread is not a confidence interval. Unknown optical/electrical distributions remain `DATA_REQUIRED`; no arbitrary Monte Carlo confidence interval is reported.

## 12. Value of information and experimental plan

The highest-value blocking measurement is same-device bottom EQE with serial-level linkage, followed by complete-stack R/T/A closure, external dark-JV, same-device top EQE, and resistance/contact/interconnection extraction. The ranking is a sensitivity-based proxy because exact covariance/Fisher information is unavailable.

## 13. Baseline validation gate

`DATA-LIMITED`. Major conflict, pairing, optical closure, electrical loss, and identifiability criteria remain false.

## 14. APMT gate and historical comparison

`APMT_STATUS = BLOCKED_BY_BASELINE_VALIDATION`. No APMT mechanism was run. Historical V1.3 baseline 23.633%, full APMT 24.242%, +0.610 percentage points remains `MODEL-OBSERVED / ASSUMPTION-DEPENDENT`.

## 15. Failure analysis

The software is improved; the evidence is not yet complete. Software completeness is not experimental completeness.

## 16. Reproducibility

See `v17_reproducibility_manifest.json`, `v17_dataset_hashes.csv`, `v17_environment_info.json`, `v17_dependency_versions.txt`, `v17_configuration_hash.txt`, and `v17_random_seeds.json`.

## 17. Final scientific decision

**SOFTWARE_STATUS:** research-grade experimental-data-ready infrastructure.

**DATA_STATUS:** primary/digitized evidence with unresolved EQE conflict and missing measurements.

**BASELINE_STATUS:** DATA-LIMITED.

**APMT_STATUS:** BLOCKED_BY_BASELINE_VALIDATION.

**EXPERIMENT_READINESS:** software ready; controlled APMT attribution not yet justified.

**TOP_UNRESOLVED_ISSUES:** bottom EQE/current matching, device pairing, R/T/A closure, external electrical loss, identifiability.

**HIGHEST_VALUE_NEXT_MEASUREMENTS:** same-device EQE, complete R/T/A, external dark-JV, same-device pairing, resistance extraction.

## Final scientific question

**After V1.7, what is the minimum remaining evidence required before the APMT architecture can be experimentally tested in a scientifically defensible controlled comparison?**

**Same-device machine-readable top/bottom EQE linked to the certified JV serial, complete-stack R/T/A closure, and external electrical-loss measurements are the minimum remaining blocking evidence.**
