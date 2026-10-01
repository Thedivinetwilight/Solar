# APMT V1.6 full report

## Validation state: **DATA-LIMITED**

## Baseline configuration hash

`e759bc7c5596043e207ac7d22ea81d30cfdecebd043810d095cb510f611ccc0b`

## Scope and preservation

V1.6 is an evidence-resolution and conventional-baseline-validation version. No APMT mechanism was added, redesigned, optimized, or executed. The copied V1.5 results remain under `v15_results_snapshot/`; V1.4 remains preserved separately.

## 1. New evidence recovered

{
  "source_reconciliation_rows": 30,
  "thesis_page_index": "all_primary_pdf_page_index.csv",
  "local_machine_readable_inventory": "local_machine_readable_inventory.csv",
  "source_count": 3,
  "official_si_status": "HTTP 403; not recovered"
}

The accepted manuscript, embedded S20-S38/Tables S1-S3, 281-page accepted thesis, repository mirror, source hashes, local machine-readable inventory, and V1.5 digitized inputs were searched. The thesis repeats the article-level 20.18/19.41/19.23 context and does not provide a new raw EQE series or unique serial-level pairing that resolves the conflict.

## 2. Source reconciliation and changelog

| evidence_item | source | locator | device_or_dataset | old_value | new_value | reason_for_change | provenance | change_status | evidence_context |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| thermal MPP | accepted manuscript + repository mirror + accepted thesis | full text search / embedded supplementary sections | context search; not a measurement row | V1.5 search coverage | {"accepted_manuscript": 0, "repository_mirror": 0, "thesis": 0} | V1.6 repeated the search across all 281 thesis pages and both 69-page article copies; no new machine-readable EQE series was recovered. | PRIMARY_AUTHOR_CONTEXT | RECONFIRMED |  |
| thickness | accepted manuscript + repository mirror + accepted thesis | full text search / embedded supplementary sections | context search; not a measurement row | V1.5 search coverage | {"accepted_manuscript": 5, "repository_mirror": 5, "thesis": 45} | V1.6 repeated the search across all 281 thesis pages and both 69-page article copies; no new machine-readable EQE series was recovered. | PRIMARY_AUTHOR_CONTEXT | RECONFIRMED | manuscript: azole such as MeO- 2PACz and 2PACz can form passivated interfaces while allowing for low transport losses due to their ultrathin thickness (<1 nm) (7). The introduction of a methyl-group substitution to the “lossless” hole- selective interface created by 2PACz (7) lead to a more optimized alignment with the perovskite valence band edge (see energetic band edge diagram in Figure S1) with a simil \|\| thesis: absorptivity 𝑎(𝐸)) of materials contain information about the position and ty |
| device architecture | accepted manuscript + repository mirror + accepted thesis | full text search / embedded supplementary sections | context search; not a measurement row | V1.5 search coverage | {"accepted_manuscript": 1, "repository_mirror": 1, "thesis": 6} | V1.6 repeated the search across all 281 thesis pages and both 69-page article copies; no new machine-readable EQE series was recovered. | PRIMARY_AUTHOR_CONTEXT | RECONFIRMED | manuscript: S. Albrecht, Numerical optical optimization of monolithic planar perovskite-silicon tandem solar cells with regular and inverted device architectures. Opt. Express. 25, A473 (2017). 31. M. Jošt, E. Köhnen, A. B. Morales-Vilches, B. Lipovšek, K. Jäger, B. Macco, A. Al-Ashouri, J. Krč, L. Korte, B. Rech, R. Schlatmann, M. Topič, B. Stannowski, S. Albrecht, Textured interfaces in monolithic perovskite/ \|\| thesis: Perovskite solar cells: state of the art Perovskite solar cells started  |
| bottom_EQE_graphical_integral | V1.5 Fig. S32 digitization | Fig. S32 / page 55 | HZB silicon curve, certified champion context | 17.110498118937528 | 17.110498118937528 | V1.6 reuses the documented branch-specific digitization; no unsupported rescaling is applied. | DIGITIZED_PRIMARY | NO_NUMERICAL_CHANGE | Independent V1.4 Fig. 4E and V1.5 Fig. S32 graphical reconstructions remain near 16.9-17.1. |
| bottom_EQE_reported_integral | accepted manuscript | main text / Fig. 4E and Fig. S32 labels | HZB silicon reported aggregate | 20.18 | 20.18 | Primary-author value retained as reported; never used to retune the plotted curve. | PRIMARY_REPORTED | NO_NUMERICAL_CHANGE | Text states 19.41 and 20.18 mA cm^-2 under AM1.5G and compares them with measured Jsc 19.23. |
| baseline_validation_state | V1.5 report | v15_results.json | conventional baseline | DATA-LIMITED | DATA-LIMITED | No blocking evidence gap was resolved in V1.6. | VALIDATION_STATE | NO_STATE_CHANGE | EQE, optical closure, external electrical loss, pairing, and identifiability remain blocking. |
| historical_APMT_result | V1.3/V1.5 record | historical comparison | model comparison | baseline 23.633%; full APMT 24.242%; +0.610 pp | unchanged | No APMT execution is permitted while the baseline gate is closed. | MODEL-OBSERVED / ASSUMPTION-DEPENDENT | PRESERVED |  |

No changed numerical value is silently substituted. V1.6 revalidates the V1.5 graphical numbers and preserves the reported primary value as a separate scenario. The complete machine-readable changelog is `results/v16_changelog.md`.

## 3. Bottom-EQE forensic hypotheses

| hypothesis | supporting_evidence | numerical_test | result | classification | provenance |
| --- | --- | --- | --- | --- | --- |
| wavelength-axis interpretation | Fig. S32 has a linear 300-1200 nm axis and bottom curve begins near 753 nm | linear mapping; ±10 and ±25 nm shifts | base=17.110498; explicit shift series recorded below | DISFAVORED | V1.6_FORENSIC_TEST |
| wavelength-axis shift closes discrepancy | The plotted wavelength ticks are visible; no alternate mapping is documented | wavelength shift -25,-10,0,+10,+25 nm | {"-25": 17.829525954883476, "-10": 17.44049352561997, "0": 17.110498118937528, "10": 16.910551799341448, "25": 16.56425135641573} | REFUTED | V1.6_FORENSIC_TEST |
| integration-limit choice | Curve reaches the 1200 nm axis edge | 300-1100, 300-1200, 300-1250 nm | {"1100": 16.571743096020683, "1200": 17.110364215971977, "1250": 17.110498118937528} | DISFAVORED | V1.6_FORENSIC_TEST |
| AM1.5G weighting choice | Article text explicitly says AM1.5G; V1.5 used ASTM G173 global tilt | global versus direct/circumsolar and direct normalized to global radiant energy | {"global": 17.110498118937528, "direct": 15.9771311602692, "direct_radiant_normalized": 17.756199127185116} | DISFAVORED | V1.6_FORENSIC_TEST |
| EQE versus 1-R interpretation | Fig. S32 labels dashed curves 1-R separately from solid EQE | integrate dashed optical proxy without calling it EQE | 1-R proxy=42.714137 versus EQE=17.110498; 1-R is not useful absorption | SUPPORTED | V1.6_FORENSIC_TEST |
| plotted branch extraction | Red solid and red dashed curves overlap; V1.6 uses separate continuity/branch masks | solid bottom branch versus V1.4 independent Fig. 4E reconstruction | Fig. S32=17.110498; Fig. 4E=16.901937; difference=0.208562 | PLAUSIBLE | V1.6_FORENSIC_TEST |
| hidden curve offset or vertical normalization | No source table or normalization note recovered | ±2% vertical scale and required factor | ±2% gives 16.768288-17.452708; 20.18 requires 1.17939290x | DISFAVORED | V1.6_FORENSIC_TEST |
| hidden additive EQE offset | No additive offset is visible or documented | constant EQE offset over 753-1200 nm | required offset ≈ 13.773 percentage points | DISFAVORED | V1.6_FORENSIC_TEST |
| graph aspect ratio / pixel geometry | Fig. S32 plot rectangle and ticks provide affine pixel mapping | axis bounds ±5 pixels | 16.963022 and 17.262052 mA cm^-2 | REFUTED | V1.6_FORENSIC_TEST |
| interpolation method | Curve points are digitized at approximately 1.15 nm spacing | linear versus nearest-neighbour interpolation | linear=17.110498; nearest=17.102947 | REFUTED | V1.6_FORENSIC_TEST |
| spectral normalization | No source normalization factor beyond ASTM G173 is stated; text reports spectral mismatch near 0.997 | multiply by reported 0.997 correction | 17.059167 mA cm^-2, not 20.18 | DISFAVORED | V1.6_FORENSIC_TEST |
| figure export/resolution effect | Digitization uncertainty metadata is 2.5 EQE percentage points | aggregate graphical interval around S32 | 16.610498 to 17.610498 mA cm^-2, no overlap with 20.18 | PLAUSIBLE | V1.6_FORENSIC_TEST |
| truncation/incomplete capture | Bottom curve begins at the perovskite/silicon crossover and ends at 1200 nm | windows 300-1100/1200/1250 | 16.571743/17.110364/17.110498 | DISFAVORED | V1.6_FORENSIC_TEST |
| 20.18 belongs to a different measurement or device | Primary text gives the number but no unique serial/device ID; thesis and repository copies repeat it | search article/thesis/repository occurrences and device genealogy | Repeated primary-author context, but no raw series or unique serial link resolving plotted curve to aggregate | UNRESOLVED | V1.6_FORENSIC_TEST |
| 20.18 is a table value rather than plotted curve integral | Embedded text/figure labels contain 20.18; no raw table with wavelength-resolved values recovered | local machine-readable inventory and S1-S3 search | No machine-readable EQE table containing the plotted HZB curve was recovered | PLAUSIBLE | V1.6_FORENSIC_TEST |
| thesis provides a clearer alternate curve | Thesis repeats article content and embedded graphics | compare thesis/article text hashes and search terms | No distinct machine-readable curve or methodological definition resolving 20.18 found | DISFAVORED | V1.6_FORENSIC_TEST |
| alternative author-hosted version contains raw data | Repository mirror is the only alternate article copy in inventory | compare article/repository text and local data inventory | No additional raw EQE series recovered; official SI remains HTTP 403 | DISFAVORED | V1.6_FORENSIC_TEST |
| different spectral condition explains 20.18 | Article states AM1.5G context; no alternate condition is documented near value | global/direct and normalization tests | global=17.110498; direct=15.977131; no tested weighting reaches 20.18 | DISFAVORED | V1.6_FORENSIC_TEST |
| source-reporting inconsistency | Independent graphical reconstructions disagree with repeated primary reported aggregate | compare 20.18, 17.110498, 16.901937 | 20.18 - S32 = 3.069502; 20.18 - Fig4E = 3.278063 | SUPPORTED | V1.6_FORENSIC_TEST |

**Final EQE decision:** `UNRESOLVED_DATA_CONFLICT`. The discrepancy is not classified as resolved same data, a resolved different dataset/device, a resolved integration definition, or a digitization artifact. `SOURCE_REPORTING_INCONSISTENCY` is supported as a description of the evidence state, but the scientific resolution remains `UNRESOLVED_DATA_CONFLICT` because the source data needed to identify the cause are absent. No graphical curve was forced to 20.18.

## 4. EQE scenario propagation

| scenario | top_Jph_mA_cm2 | bottom_Jph_mA_cm2 | current_matching_Jph_mA_cm2 | mismatch_bottom_minus_top_mA_cm2 | reported_certified_Jsc_mA_cm2 | scenario_Jsc_mA_cm2 | Jsc_minus_certified_mA_cm2 | Voc_used_V | Voc_provenance | FF_used | FF_provenance | possible_PCE_percent | PCE_provenance | APMT_interpretation | APMT_sensitivity_to_EQE_conflict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A_reported_20.18 | 19.41 | 20.18 | 19.41 | 0.7699999999999996 | 19.23 | 19.41 | 0.17999999999999972 | 1.910204081632653 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 0.8262824655906442 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 30.6361255654267 | MODEL_FIT_CANDIDATE_OUTPUT_ONLY | Baseline scenario spread only; APMT not run | NOT_COMPUTABLE_BASELINE_GATE_CLOSED; current-matching spread is propagated |
| B_graphical_S32_17.110498 | 19.41 | 17.110498118937528 | 17.110498118937528 | -2.299501881062472 | 19.23 | 17.110498118937528 | -2.1195018810624724 | 1.910204081632653 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 0.8262824655906442 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 27.0066650622755 | MODEL_FIT_CANDIDATE_OUTPUT_ONLY | Baseline scenario spread only; APMT not run | NOT_COMPUTABLE_BASELINE_GATE_CLOSED; current-matching spread is propagated |
| C_graphical_Fig4E_16.901937 | 19.41 | 16.901936581158672 | 16.901936581158672 | -2.5080634188413278 | 19.23 | 16.901936581158672 | -2.328063418841328 | 1.910204081632653 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 0.8262824655906442 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 26.677478176159504 | MODEL_FIT_CANDIDATE_OUTPUT_ONLY | Baseline scenario spread only; APMT not run | NOT_COMPUTABLE_BASELINE_GATE_CLOSED; current-matching spread is propagated |
| D_certified_measured_Jsc_19.23 | 19.41 | 19.23 | 19.23 | -0.17999999999999972 | 19.23 | 19.23 | 0.0 | 1.910204081632653 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 0.8262824655906442 | MODEL_FIT_CANDIDATE_NOT_MEASUREMENT | 30.35201930052321 | MODEL_FIT_CANDIDATE_OUTPUT_ONLY | Baseline scenario spread only; APMT not run | NOT_COMPUTABLE_BASELINE_GATE_CLOSED; current-matching spread is propagated |

The scenario PCE values use the historical candidate-fit Voc and FF only as explicitly labelled model-fit inputs. They are not measurements and do not validate the baseline. Bottom-EQE selection changes the current-matching current from 19.41 to 17.110 or 16.902 mA cm^-2, so the issue remains directly consequential for Jsc and any APMT sensitivity.

## 5. Same-device measurement genealogy

| dataset | source | locator | device_configuration | device_id | top_cell | bottom_cell | tandem | scan_direction | measurement_condition | temperature | illumination | institution | certification | data_state | numerical_completeness | confidence | pairing_certainty | baseline_usability | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| certified external JV | accepted manuscript | Fig. 4D / certification text | CERTIFIED CHAMPION | not recoverable serial | Me-4PACz + LiF | SHJ silicon | yes | Jsc->Voc and Voc->Jsc contexts | Fraunhofer-certified 1-sun equivalent | not explicitly reported on figure | calibrated solar simulator / certification | Fraunhofer ISE + author measurement context | certified | reported + digitized curve | curve and aggregate metrics | HIGH | CERTIFIED_CHAMPION_CONTEXT | YES_WITH_SCAN_SEPARATION | Do not merge with MPP row. |
| certified in-house JV | accepted manuscript | Fig. S31 | IN-HOUSE CERTIFIED-DEVICE MEASUREMENT | same champion stated by caption; serial absent | Me-4PACz + LiF | SHJ silicon | yes | Jsc->Voc and Voc->Jsc | 1-sun equivalent in-house | not explicit | simulator; exact spectrum not machine-readable | author in-house | certified device context | reported scan aggregates | two scan-direction metric sets | HIGH | IN_HOUSE_CERTIFIED_DEVICE | YES_WITH_SCAN_SEPARATION | 19.35/19.36 are not one averaged measurement. |
| HZB EQE | accepted manuscript | Fig. 4E and Fig. S32 | HZB EQE MEASUREMENT | no unique serial; caption/context says certified champion | HZB perovskite | HZB silicon | yes | not applicable | AM1.5G-labelled EQE / 1-R plot | not reported | spectral EQE measurement; raw spectrum absent | HZB / author context | champion context, serial not recoverable | reported labels + digitized curves | curve, no raw table | MEDIUM | UNKNOWN_PAIRING_WITH_STRONG_CONTEXT | PARTIAL_CONFLICT | 20.18 remains inconsistent with both graphical reconstructions. |
| Table S1 subcell Jph | accepted manuscript | Table S1 / Fig. S26 | SEPARATE CONFIGURATION / multiple cells | row IDs absent | various perovskite configurations | various silicon configurations | yes | not applicable | EQE-derived | not stated | AM1.5G context | author | not stated | reported table | 15 aggregate rows | MEDIUM | UNKNOWN_PAIRING | AGGREGATE_ONLY | Never merge into champion without row-level identity. |
| Table S2 champion JV | accepted manuscript | Table S2 | CERTIFIED CHAMPION / configuration summary | configuration row; serial absent | Me-4PACz/LiF | SHJ silicon | yes | both directions in summary | 1-sun equivalent | not stated | simulator | author / certification context | champion row | reported table | metrics only | HIGH | CONFIGURATION_LEVEL | YES_WITH_PAIRING | No wavelength-resolved data. |
| PL/EL representative tandem | accepted manuscript | Fig. 5 / Fig. S36 | REPRESENTATIVE DEVICE | not certified serial | representative perovskite | representative Si | yes | injection / reconstructed internal voltage | absolute PL/EL | 300 K in relevant figure context | electrical injection or optical excitation | author | not certified | reported spectra / pseudo-JV | summary only | MEDIUM | REPRESENTATIVE_NOT_CHAMPION | CONSTRAINT_ONLY | EL pseudo-JV is not external dark-JV. |
| thermal MPP | accepted manuscript | Fig. S35 | SEPARATE CONFIGURATION | Me-4PACz no-LiF; serial absent | Me-4PACz no LiF | Si | yes | MPP time/temperature track | thermal MPP | 25-85 C | AM1.5G calibrated simulator | author | not champion LiF configuration | digitized keypoints | PCE/time rather than full JV | MEDIUM | SEPARATE_CONFIGURATION | THERMAL_CONTEXT_ONLY | Not merged with certified LiF champion. |
| single-junction / secondary records | thesis and cited secondary literature | thesis search / references | SINGLE-JUNCTION OR SECONDARY | varies | varies | varies | not always | varies | varies | varies | varies | varies | not target-champion evidence | context only | heterogeneous | LOW_TO_MEDIUM | UNKNOWN_PAIRING | NO_MERGE | Used only to identify methods/data gaps. |

The major evidence groups are kept separate as certified champion, in-house certified-device, HZB EQE, representative device, single-junction/secondary, separate configuration, and unknown pairing.

## 6. Complete optical constraints

| quantity | source | locator | device_configuration | availability | measurement_state | closure_status | numerical_use | provenance | impact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R(lambda) | accepted manuscript | Fig. 4E / Fig. S32 dashed 1-R | HZB EQE measurement / champion context | PARTIAL | DIGITIZED_OPTICAL_PROXY | R_ONLY | diagnostic only | DIGITIZED_PRIMARY | Cannot determine useful absorption without T and A. |
| 1-R(lambda) | accepted manuscript | Fig. 4E / Fig. S32 | HZB EQE measurement / champion context | AVAILABLE_AS_PROXY | DIGITIZED | NOT_ABSORPTION | not used as EQE or A | DIGITIZED_OPTICAL_QUANTITY | Dashed optical curve is not total useful absorption. |
| T(lambda) | all recovered primary sources | manuscript, thesis, repository and local inventory | complete certified stack | MISSING | DATA_REQUIRED | DATA_REQUIRED | none | DATA_REQUIRED | Transmission beyond silicon and escape paths unknown. |
| A(lambda) | all recovered primary sources | manuscript, thesis, repository and local inventory | complete certified stack | MISSING | DATA_REQUIRED | DATA_REQUIRED | none | DATA_REQUIRED | Useful/parasitic absorption cannot be separated. |
| R+T+A closure | V1.5/V1.6 audit | no complete wavelength-resolved R,T,A set recovered | complete stack | NOT_TESTABLE | DATA_REQUIRED | COMPLETE_RTA_STATUS = DATA_REQUIRED | none | DATA_REQUIRED | No closure claim made. |
| interconnection/electrode/parasitic absorption | all recovered primary sources | supplementary sections and thesis search | certified stack | MISSING | DATA_REQUIRED | DATA_REQUIRED | none | DATA_REQUIRED | Cannot allocate optical loss ledger. |

`COMPLETE_RTA_STATUS = DATA_REQUIRED`. `1-R` is retained as an optical proxy only and is not treated as total useful absorption. No R+T+A closure is asserted without all components.

## 7. Electrical-loss constraints

| quantity | source | locator | device_configuration | technique | external_or_internal | availability | value_or_result | provenance | usable_for | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| illuminated JV | accepted manuscript | Fig. 4D and Fig. S31 | certified champion / in-house certified-device context | illuminated JV | external terminal | REPORTED + DIGITIZED | Jsc 19.23-19.36; Voc 1.91; scan PCE 29.00-29.14 | PRIMARY_REPORTED + DIGITIZED_PRIMARY | curve-level baseline with scan separation | AVAILABLE |
| MPP PCE | accepted manuscript | certification and Fig. S31 | certified champion context | MPP tracking | external terminal | REPORTED | 29.15% | PRIMARY_REPORTED | separate MPP reference only | AVAILABLE_SEPARATE_MODE |
| external dark-JV | all recovered primary sources | manuscript/thesis/repository search | certified champion | external dark-JV | external terminal | MISSING | DATA_REQUIRED | DATA_REQUIRED | J0/n/Rsh/contact loss | BLOCKING |
| EL pseudo-JV/internal voltage | accepted manuscript | Fig. S36 / EL reconstruction | representative tandem | EL-derived reconstruction | internal voltage / pseudo-JV | PARTIAL | internal-voltage relation; no external Rs | PRIMARY_REPORTED | recombination/QFLS context only | NOT_EXTERNAL_DARK_JV |
| Suns-Voc | all recovered primary sources | full text search | target champion | Suns-Voc | external open-circuit | MISSING | DATA_REQUIRED | DATA_REQUIRED | ideality/recombination separation | BLOCKING |
| Jsc-Voc | all recovered primary sources | full text search | target champion | Jsc-Voc | external terminal | MISSING | DATA_REQUIRED | DATA_REQUIRED | series/contact/recombination separation | BLOCKING |
| series resistance | all recovered primary sources | no direct extraction recovered | target champion | Rs extraction | external terminal | MISSING | DATA_REQUIRED | DATA_REQUIRED | FF loss | BLOCKING |
| shunt resistance | all recovered primary sources | no direct external dark-JV recovered | target champion | Rsh extraction | external terminal | MISSING | DATA_REQUIRED | DATA_REQUIRED | low-voltage leakage | BLOCKING |
| contact/interconnection resistance | all recovered primary sources | full text search | target champion | contact/interconnection extraction | external terminal | MISSING | DATA_REQUIRED | DATA_REQUIRED | voltage/FF loss | BLOCKING |
| current mismatch | accepted manuscript | Fig. 4E text | reported champion context | EQE/JV comparison | mixed modality | REPORTED_DIAGNOSTIC | 0.77 mA cm^-2 Si-minus-perovskite reported; graphical bottom conflict remains | PRIMARY_REPORTED + DIGITIZED_PRIMARY | diagnostic only | CONFLICTED |

EL-derived internal-voltage reconstruction is not used as external dark-JV, and no measured Rs/Rsh/contact/interconnection values are invented.

## 8. Curve-level validation

| dataset | measurement_or_curve | RMSE | normalized_RMSE | MAE | max_absolute_deviation | Jsc_deviation | Voc_deviation | Vmp_deviation | Jmp_deviation | Pmax_deviation | FF_deviation | PCE_deviation | curve_shape_residuals | status | provenance | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| certified illuminated J-V | current | 0.9170424665391248 | 0.047897325950173 |  | 3.69575095951364 |  |  |  |  |  |  |  | CURVE_FIT_AVAILABLE | PASS_IF_CONTEXTUALIZED | V1.4_REUSED_DIAGNOSTIC | Digitized red branch from Fig. 4D; uncertainty is graphical and scan-direction/certificate pairing is retained. |
| top EQE | integrated Jph |  |  |  |  | 0.5740345628052133 |  |  |  |  |  |  | DIGITIZED_CURVE_AVAILABLE | PARTIAL_WITH_DIGITIZATION_DISCREPANCY | V1.4_REUSED_DIAGNOSTIC | Digitized integral=19.984; author-version reported integral=19.41 mA cm^-2. |
| bottom EQE | integrated Jph |  |  |  |  | -3.278063418841328 |  |  |  |  |  |  | DIGITIZED_CURVE_AVAILABLE | FAIL_CURVE_INTEGRAL_DISCREPANCY | V1.4_REUSED_DIAGNOSTIC | Digitized integral=16.902; author-version reported integral=20.18 mA cm^-2. No vertical retuning was applied. |
| complete-stack R/T/A | spectral closure |  |  |  |  |  |  |  |  |  |  |  | 1-R_ONLY | DATA_REQUIRED | V1.4_REUSED_DIAGNOSTIC | Fig. 4E provides 1-reflection, not separable complete-stack R(lambda), T(lambda), A(lambda). |
| dark-JV | external curve |  |  |  |  |  |  |  |  |  |  |  | EL_RECONSTRUCTED_PSEUDO_JV_ONLY | DATA_REQUIRED | V1.4_REUSED_DIAGNOSTIC | Fig. S36 is EL-derived internal-voltage reconstruction and explicitly lacks external series resistance. |
| temperature-dependent MPP | PCE versus temperature/time |  |  |  |  |  |  |  |  |  |  |  | DIGITIZED_KEYPOINTS | PARTIAL | V1.4_REUSED_DIAGNOSTIC | Fig. S35 provides a thermal MPP track, not temperature-dependent full JV parameters. |
| Fig. S31 in-house JV scan directions | reported aggregate scan comparison |  |  |  |  | 0.01 | 0.0 |  |  |  | 0.0036 | 0.14 | scan-direction aggregate span only | PARTIAL_SCAN_SEPARATION | PRIMARY_REPORTED | Jsc 19.35 versus 19.36; PCE 29.00 versus 29.14; not averaged. |
| Fig. S32 HZB silicon EQE | integrated EQE |  |  |  |  | -3.0695018810624717 |  |  |  |  |  |  | branch digitization only | UNRESOLVED_DATA_CONFLICT | DIGITIZED_PRIMARY | Graphical curve does not reproduce reported 20.18. |
| V1.4 Fig. 4E bottom EQE | integrated EQE |  |  |  |  | -3.2780634188413273 |  |  |  |  |  |  | independent prior digitization | UNRESOLVED_DATA_CONFLICT | DIGITIZED_PRIMARY | Independent Fig. 4E reconstruction supports the conflict. |
| candidate baseline versus certified in-house JV | fit metrics versus S31 scan aggregates |  |  |  |  | -0.12019668162124475 | 0.0002040816326531747 |  |  |  | 0.0411824655906442 | 1.340482885851074 | candidate fit not validation | MODEL_FIT_NOT_VALIDATED | MODEL_FIT_TO_DIGITIZED_PRIMARY | PCE agreement/disagreement does not identify physical parameters. |

The candidate fit and scan-direction metrics are retained separately. Validation is not declared from PCE agreement.

## 9. Identifiability and fit robustness

| parameter | status | free_parameter | jacobian_rank | parameter_count | condition_number | singular_value | max_abs_local_correlation | profile_grid_span | boundary_status | interpretation | profile_robustness | multi_start_cost_spread | multi_start_parameter_spread | classification | v16_context |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| log10_J0_nonradiative_A_m2 | FIT_TO_DIGITIZED_PRIMARY_CURVE | True | 4 | 4 | 1216249.3410720828 | 32943.852017216115 | 0.9998971432355108 | 1.6000000000000014 | BOUNDARY_HIT | Curve-constrained fit; fitted value is not an experimental measurement. | NON_ROBUST_PROFILE | 5.862432317371713e-09 |  | NON_IDENTIFIABLE | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |
| n_nonradiative | FIT_TO_DIGITIZED_PRIMARY_CURVE | True | 4 | 4 | 1216249.3410720828 | 238.61851093077976 | 0.9998971432355108 | 0.1500000001145274 | BOUNDARY_HIT | Curve-constrained fit; fitted value is not an experimental measurement. | NON_ROBUST_PROFILE | 5.862432317371713e-09 |  | NON_IDENTIFIABLE | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |
| series_resistance_ohm_m2 | FIT_TO_DIGITIZED_PRIMARY_CURVE | True | 4 | 4 | 1216249.3410720828 | 0.16581497485103552 | 0.8061414397052987 | 0.0067468635761705085 | BOUNDARY_HIT | Curve-constrained fit; fitted value is not an experimental measurement. | NON_ROBUST_PROFILE | 5.862432317371713e-09 |  | NON_IDENTIFIABLE | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |
| log10_shunt_resistance_ohm_m2 | FIT_TO_DIGITIZED_PRIMARY_CURVE | True | 4 | 4 | 1216249.3410720828 | 0.027086429488362332 | 0.1658208684009369 | 1.0000000000000004 | BOUNDARY_HIT | Curve-constrained fit; fitted value is not an experimental measurement. | NON_ROBUST_PROFILE | 5.862432317371713e-09 |  | NON_IDENTIFIABLE | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |
| Jph_fixed_mA_cm2 | FIXED_PRIMARY_AUTHOR_VERSION | False | 4 | 4 | 1216249.3410720828 |  |  | 0.0 | FIXED | 19.23 mA cm^-2 author-version certified-device value. | LOCAL_PROFILE_ONLY | 5.862432317371713e-09 |  | FIXED | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |
| temperature_K | FIXED_PRIMARY_AUTHOR_VERSION | False | 4 | 4 | 1216249.3410720828 |  |  | 0.0 | FIXED | 298.15 K characterization condition. | LOCAL_PROFILE_ONLY | 5.862432317371713e-09 |  | FIXED | V1.6 repeated conventional fit; same-device/evidence constraints are fixed, not extra free parameters |

The conventional candidate retains Jacobian rank, singular values, condition number, local correlations, multi-start cost spread, profile spans, and boundary flags. Multiple model parameters remain non-identifiable or weakly identifiable.

## 10. Uncertainty decomposition

| component | quantity | lower | central | upper | status | provenance | impact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| measurement_uncertainty | reported_bottom_EQE_integral | 20.18 | 20.18 | 20.18 | PRIMARY_REPORTED_NO_ERROR_BAR | PRIMARY_REPORTED | current matching |
| digitization_uncertainty | S32_bottom_EQE_integral | 16.610498118937528 | 17.110498118937528 | 17.610498118937528 | GRAPHICAL_INTERVAL_ONLY | DIGITIZED_PRIMARY | current matching |
| source_reporting_uncertainty | bottom_EQE_integral | 16.901936581158672 | 20.18 | 20.18 | DISCRETE_CONFLICT_NOT_DISTRIBUTION | PRIMARY_REPORTED + DIGITIZED_PRIMARY | current matching/Jsc |
| dataset_pairing_uncertainty | EQE_to_certified_JV_link |  |  |  | DATA_REQUIRED | DATA_REQUIRED | all baseline outputs |
| eqe_conflict_uncertainty | scenario_Jsc | 16.901936581158672 | 18.16310867502405 | 19.41 | DISCRETE_SCENARIO_SPREAD | SCENARIO_PROPAGATION | Jsc and possible PCE |
| parameter_uncertainty | candidate baseline metrics |  |  |  | MODEL_PROFILE_NOT_EXPERIMENTAL_CI | MODEL_FIT | Voc/FF/PCE interpretation |
| model_form_uncertainty | radiative/nonradiative/conventional decomposition |  |  |  | DATA_REQUIRED | DATA_REQUIRED | Voc/FF/loss attribution |
| missing_data_uncertainty | complete R/T/A and external dark-JV |  |  |  | DATA_REQUIRED | DATA_REQUIRED | optical/electrical loss attribution |

Measurement, digitization, source-reporting, dataset-pairing, EQE-conflict, parameter, model-form, and missing-data uncertainty remain separate. The 20.18, 17.110498, and 16.901937 cases are discrete scenarios, not collapsed into an arbitrary confidence interval.

## 11. Baseline metrics

| case | Jsc_mA_cm2 | Voc_V | FF | PCE_percent | Vmp_V | Jmp_mA_cm2 | Pmax_W_m2 | status | provenance | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| certified_inhouse_Jsc_to_Voc | 19.35 | 1.91 | 0.7851 | 29.0 |  |  |  | PRIMARY_REPORTED | PRIMARY_REPORTED | Separate scan mode. |
| certified_inhouse_Voc_to_Jsc | 19.36 | 1.91 | 0.7887 | 29.14 |  |  |  | PRIMARY_REPORTED | PRIMARY_REPORTED | Separate scan mode. |
| certified_MPP |  |  |  | 29.15 |  |  |  | PRIMARY_REPORTED | PRIMARY_REPORTED | MPP is not merged with scan PCE. |
| historical_V1.4_curve_fit_candidate | 19.229803318378757 | 1.910204081632653 | 0.8262824655906442 | 30.340482885851074 | 1.6285714285714286 | 18.637014215055427 | 303.5170886451884 | MODEL_FIT_NOT_VALIDATED | MODEL_FIT_TO_DIGITIZED_PRIMARY | Boundary/correlation limited; retained unchanged as historical candidate. |
| A_reported_20.18 | 19.41 | 1.910204081632653 | 0.8262824655906442 | 30.6361255654267 |  |  |  | SCENARIO_NOT_DEVICE_MEASUREMENT | SCENARIO_PROPAGATION_WITH_MODEL_FIT_VOC_FF | Current-only propagation; no claim that PCE is measured. |
| B_graphical_S32_17.110498 | 17.110498118937528 | 1.910204081632653 | 0.8262824655906442 | 27.0066650622755 |  |  |  | SCENARIO_NOT_DEVICE_MEASUREMENT | SCENARIO_PROPAGATION_WITH_MODEL_FIT_VOC_FF | Current-only propagation; no claim that PCE is measured. |
| C_graphical_Fig4E_16.901937 | 16.901936581158672 | 1.910204081632653 | 0.8262824655906442 | 26.677478176159504 |  |  |  | SCENARIO_NOT_DEVICE_MEASUREMENT | SCENARIO_PROPAGATION_WITH_MODEL_FIT_VOC_FF | Current-only propagation; no claim that PCE is measured. |
| D_certified_measured_Jsc_19.23 | 19.23 | 1.910204081632653 | 0.8262824655906442 | 30.35201930052321 |  |  |  | SCENARIO_NOT_DEVICE_MEASUREMENT | SCENARIO_PROPAGATION_WITH_MODEL_FIT_VOC_FF | Current-only propagation; no claim that PCE is measured. |

The conventional baseline is **not VALIDATED**.

## 12. Strict validation gate

| criterion | pass | evidence | validation_state |
| --- | --- | --- | --- |
| bottom_EQE_conflict_resolved | False | 20.18 remains above independent graphical 16.902/17.110 integrals; final classification is UNRESOLVED_DATA_CONFLICT. | DATA-LIMITED |
| same_device_pairing_sufficient | False | Certified/JV/EQE context is strong but unique serial IDs and row-level pairings are unavailable. | DATA-LIMITED |
| complete_RTA_optical_closure | False | Only 1-R is available; complete R/T/A and interconnection absorption are DATA_REQUIRED. | DATA-LIMITED |
| external_electrical_loss_constraints | False | External dark-JV, Suns-Voc/Jsc-Voc, Rs/Rsh/contact/interconnection extraction remain DATA_REQUIRED. | DATA-LIMITED |
| curve_level_validation | False | Digitized JV candidate exists, but EQE conflict and fit-vs-scan metric differences remain. | DATA-LIMITED |
| identifiability_and_profile_robustness | False | Condition number ~1.2e6, boundary hits and near-unity correlations remain. | DATA-LIMITED |
| uncertainty_separation | True | Measurement, digitization, source-reporting, pairing, EQE-conflict, parameter, model-form, and missing-data rows are separate. | DATA-LIMITED |
| source_reproducibility | True | Primary PDF copies, text searches, source metadata, digitization metadata and V1.5 snapshot are retained. | DATA-LIMITED |
| historical_results_preserved | True | V1.5 outputs are copied unchanged under v15_results_snapshot; V1.4 remains outside V1.6. | DATA-LIMITED |

Final state: **DATA-LIMITED**.

## 13. APMT gate

`APMT_STATUS = BLOCKED_BY_BASELINE_VALIDATION`. No APMT comparison was run. The V1.3 result remains historical `MODEL-OBSERVED / ASSUMPTION-DEPENDENT`: baseline approximately 23.633%, full APMT approximately 24.242%, difference approximately +0.610 percentage points.

## 14. Minimum next measurements

| priority | measurement | quantity_constrained | target_uncertainty | affects | blocking | why_needed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | same-device top EQE(lambda) | perovskite spectral collection/Jph | <=1% integrated current / <=2 EQE points | Jsc, current matching, PCE, APMT interpretation | YES | Confirm the top-side current on the same serial device as bottom EQE and certified JV. |
| 1 | same-device bottom EQE(lambda) | silicon spectral collection/Jph | <=1% integrated current / <=2 EQE points | Jsc, current matching, PCE, APMT interpretation | YES | Directly resolve 20.18 versus 16.90-17.11 mA cm^-2. |
| 1 | complete-stack R(lambda) | front/rear reflection | <=0.02 absolute spectral fraction | Jsc and optical loss attribution | YES | Separate reflection from absorption/transmission. |
| 1 | complete-stack T(lambda) | useful transmission beyond silicon | <=0.02 absolute spectral fraction | Jsc and optical closure | YES | Close R/T/A without treating 1-R as absorption. |
| 1 | complete-stack A(lambda) or defensible R+T+A closure | useful versus parasitic/interconnection absorption | closure within stated measurement uncertainty | Jsc, optical loss, APMT mechanism interpretation | YES | Allocate optical loss channels. |
| 1 | external dark-JV | J0, ideality, Rsh, leakage | <=5% fit parameters | Voc, FF, recombination/loss attribution | YES | EL pseudo-JV cannot replace external dark-JV. |
| 1 | Suns-Voc or Jsc-Voc | recombination and resistive separation | <=5% | Voc and FF | YES | Constrain model-form/parameter identifiability. |
| 1 | Rs/contact/interconnection extraction | external voltage and FF loss | <=5% | FF, PCE, architecture attribution | YES | Prevent fitted Rs from absorbing multiple unknown losses. |
| 2 | absorber thickness and cross-section | geometry/absorption mapping | <=5% thickness | EQE interpretation and optical model | IMPORTANT | Check geometry and spectral assumptions. |
| 2 | temperature-resolved JV/MPP | Voc/FF/Jsc(T) and thermal boundaries | <=1 K; <=1% metrics | FF, PCE, thermal interpretation | IMPORTANT | Separate thermal effects from electrical fit artifacts. |
| 2 | absolute PL/EL with device ID | QFLS, PLQY, internal recombination | <=0.02 V / <=10% PLQY | Voc and recombination interpretation | INFORMATIVE_UNTIL_PAIRED | Link representative internal-voltage evidence to certified serial. |

## 15. Physical-fabrication decision

**A. No fabrication yet.** The recovered evidence does not justify even a controlled APMT comparison because current matching is unresolved, same-device pairing is incomplete, complete optical closure is absent, external electrical losses are unconstrained, and the conventional parameter fit is not identifiable. Exploratory fabrication may be considered only after the blocking measurements above are completed and the control/APMT pair is fabricated with matched process controls.

## Final scientific question

**Does the recovered evidence now justify physical fabrication and experimental testing of the APMT architecture?**

**NO — baseline still insufficient.** The primary evidence is stronger, but the remaining bottom-EQE conflict and missing optical/electrical constraints prevent a defensible experimental interpretation of the existing APMT mechanisms.
