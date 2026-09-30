# INCOMING — staging area (V1.8 intake)

Files re-uploaded from the previous Arena session land here FIRST, byte-for-byte verbatim.

Protocol (enforced, non-negotiable):
1. Store attachments verbatim. No reformatting, no "cleanups", no re-wording.
2. Record sha256 of each file on intake.
3. Nothing in this repo may be deleted or renamed. Only additive changes.
4. Historical artifacts (V1.1–V1.7) are evidence, not drafts — they are read-only inputs to V1.8.
5. After intake, the handoff status ledger is transcribed into the V1.8 project ledger
   and cross-checked against every file actually present here. Any discrepancy is logged,
   never silently resolved.

Intake log (file, sha256, received, notes):
- (pending) APMT_FULL_NEW_CHAT_HANDOFF_CONTEXT.txt
- (pending) APMT_V1.8_EVIDENCE_RECOVERY_MASTER_PROMPT.txt

## Intake entries (2026-09-30)

| file | sha256 | git blob (origin/main, commit ed8e7df) | size | lines | notes |
|---|---|---|---|---|---|
| APMT_FULL_NEW_CHAT_HANDOFF_CONTEXT.txt | 766f573d6c6054c47a3f7b6a7b5f76b6490f71916f3053c208b3cec9fb506c02 | f0befbc595aa3e82384f99cb4c1ad20321d7fe91 | 26375 B | 736 | Extracted verbatim from origin/main. NOTE: committed at repo ROOT, not under uploads/ as stated in chat. |
| APMT_V1.8_EVIDENCE_RECOVERY_MASTER_PROMPT.txt | 54026828bda3b79c806686ef86537624275f1ff7936e76fb35c95da7815607c4 | 189a258585ef35d3b1d3ce367eb5ad7456ebc1dd | 8217 B | 177 | Extracted verbatim from origin/main. Same path note. |

Hash stability verified across two independent extraction paths (git show to file, and git show | sha256sum).

## MISSING-VERIFIED (claimed in handoff, NOT present in this repository)
- v17_full_report.md, v16_full_report.md, v15_full_report.md
- v17_reproducibility_manifest.json, v17_dataset_hashes.csv, v17_environment_info.json,
  v17_dependency_versions.txt, v17_configuration_hash.txt, v17_random_seeds.json,
  v17_device_genealogy.csv, v17_device_genealogy.json, v17_provenance_graph.json
- results/v16_changelog.md
- all V1.4-V1.6 digitized curve files and pixel/axis calibration metadata
- accepted manuscript / SI / thesis PDFs

These will NOT be reconstructed or guessed. Historical numerical values quoted in the
handoff context are carried forward into the V1.8 ledger as HANDOFF-QUOTED (second-hand
provenance) and are flagged accordingly.
