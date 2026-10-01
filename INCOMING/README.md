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

## Primary source acquisition log (V1.8, 2026-09-30)

| source | id | access | notes |
|---|---|---|---|
| Accepted author version (main text) | AA2020-ACCEPTED-TUB | OBTAINED (text) | TU Berlin DepositOnce, DOI 10.14279/depositonce-15127, CC BY. Read in full via platform fetcher (17 chunks). Binary PDF NOT stored: sandbox TLS blocks depositonce.tu-berlin.de; git repo is the intake path for images. |
| DNB mirror (identical file) | AA2020-ACCEPTED-DNB | OBTAINED (text) | d-nb.info/1251875920/34; verified same text stream. |
| Official publisher SI | AA2020-SI-ABSENT | ACCESS_BLOCKED | V1.7 finding stands (HTTP 403). |
| PhD thesis (32.69 MB, 281 pp) | AA2020-THESIS-ABSENT | MISSING-VERIFIED | Not obtained this session; exceeds GitHub web-upload limit (25 MB) — needs git push by owner or alternative access. |

Figure images (Fig. 4E, Fig. S32) + SI text: **PENDING user commit to this repo**
(intake path: commit under uploads/ or any path; I pull via git, hash, and
proceed with the 3-method re-digitization per v1.8_eqe_digitization_audit.md §A.4).

## Cycle 2 intake (2026-10-01)

### Files now present that were MISSING-VERIFIED on 2026-09-30

| file | sha256 | lines | notes |
|---|---|---|---|
| v16_full_report.md | 2569597553fde0adf7b49a66abd6c0a5c66b7c03842ff5aa2beb629dae41f2d8 | 225 | Arrived in the repo working tree (user commit path). Supersedes its MISSING-VERIFIED entry above. Historical V1.6 report; read-only evidence. |
| v17_full_report.md | 3a5b04b0ca71f9ef45d87c4cb4989bdaccc4c1c1ad56f95ee2a931e669ef5b22 | 134 | Same. Historical V1.7 report; read-only evidence. |

Still missing (unchanged): all other files listed in the 2026-09-30
MISSING-VERIFIED block (v15 report, v16/v17 manifest/dataset/genealogy files,
V1.4–V1.6 digitized curve files + calibration metadata, thesis PDF).

### Primary source acquisition log — cycle 2 additions

| source | id | access | notes |
|---|---|---|---|
| Accepted author version **incl. full embedded SI** (69 pp; main text pp1–25 + SI pp26–69, Figs S1–S43, Tables S1–S3) | AA2020-ACCEPTED-TUB-69PP | **COMMITTED to repo 2026-10-01** (user git commit): `data/sources/al_ashouri_accepted_manuscript.pdf`, sha256 0984f7e4b351a92d9bdbae8dd3bed25faaaf4335a3da821a6d633de1b3b3b3bc | Same TU Berlin DepositOnce work (DOI 10.14279/depositonce-15127), CC BY. PDF metadata: PDFsam Basic v4.1.4 + SAMBox 2.1.16, 2022-02-14 (reassembled scan). Figure S32 raster extracted from p55 (data/figures/s32_native_stitched.jpg); Fig. 4E raster from main text. SI text (S32 caption, Tables S1–S3) read from this file — publisher SI access no longer required. |
| PhD thesis (32.69 MB, 281 pp) | AA2020-THESIS-ABSENT | still MISSING-VERIFIED (repo) | Held locally by the user; exceeds the 25 MB web-UI upload cap; user commits via git when ready. Optional cross-check only (S32 already primary-verified from the 69-pp manuscript). |
