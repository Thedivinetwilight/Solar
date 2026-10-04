# APMT / Solar — perovskite/silicon tandem photovoltaic modelling platform

A research-grade, provenance-first modelling platform for tandem
perovskite/silicon photovoltaics. It exists to test **whether** the APMT
mechanism set (optical management, photon recycling, thermal management and
their interactions) can be shown to be physically real and experimentally
testable — not to manufacture a headline efficiency.

## Scientific status (as of V1.9-B, 2026-10-03)

| Item | Status |
| --- | --- |
| Baseline experimental gate | **CLOSED** (V1.8 evidence: G1/G4 pass, G8 fails on identifiability, G2/G3/G5/G7 deferred) |
| Gate implementation consistency | V1.9 audit: the stored `"CLOSED (DEFER)"` state was **not** what the V1.8 evaluator returns on the same evidence (`FAIL`). Both are now reported side by side by `audit_v18_gate_consistency()`. |
| APMT status | `BLOCKED_BY_BASELINE_VALIDATION` — mechanisms may only be studied as `PRE-GATE / MODEL-OBSERVED / EXPLORATORY` |
| Baseline data status | `DATA-LIMITED` (no full-stack R/T/A, no external Rs/Rsh, no serial-level device linkage) |
| Digital twin | running; registry-default tandem PCE **19.26 %** at one sun with the V1.9-C energy-balance self-heating closure (20.24 % fixed-temperature diagnostic; the legacy all-incident-power-as-heat closure gives 17.91 % and is kept for lineage), and 21.02 % for the twin calibrated to digitized EQE — the calibrated variant is a **fit to digitized figure data**, not a validated result |

## What is here

```
apmt/
  core/         units, physical constants, deterministic numerics
  params/       the parameter registry: every number has units, range, class and provenance
  spectra/      ASTM G173 AM1.5G (vendored, hashed)
  materials/    perovskite dispersion model, silicon Green-1995 optical data, thermal
  optics/       transfer-matrix solver, tandem stack assembly
  device/       detailed balance, recombination (radiative + SRH/surface), subcells, tandem solve
  inference/    calibration against digitized evidence + identifiability diagnostics
  experiments/  evidence loaders (committed figure digitizations, with provenance)
  validation/   invariant checks, extraction validity, strict gate, provenance audit
data/           committed artifacts: digitized curves, pin JSONs, vendored spectra
manifests/      reproducibility manifests (environment pins + sha256 of artifacts)
reports/        reports/APMT_MASSIVE_RND_PROGRESS_REPORT.md is the single authoritative report
tests/          unit / regression / invariant / known-answer / gate / audit tests
```

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .            # or: .venv/bin/pip install numpy scipy pvlib pillow pytest
.venv/bin/pip install -e '.[digitization]'   # only if you have the manuscript PDF
```

## Run the tests

```bash
.venv/bin/python -m pytest -q
```

The suite is **non-mutating**: no test writes into `data/`. One test is skipped
in a clean checkout — the Fig. S32 method M2 requires the 69-page accepted
manuscript PDF, which is an external source and is deliberately not committed
(`.gitignore`: `data/sources/*.pdf`). The skip message says so explicitly.

## Regenerate artifacts (explicit commands only)

```bash
python data/s32_digitize_v18.py --write    # rewrites data/s32_results.json + data/s32_curves.npz
python tools/v19_calibrate_twin.py --write # rewrites data/v19_calibration.json
python tools/ci_checks.py                  # non-mutating CI: pins, determinism, gate, provenance
```

Nothing else writes into `data/`. Tests never do.

## Non-negotiable rules encoded in the code

* **Provenance** — every numeric claim carries a category (`EXPERIMENTAL`,
  `DIGITIZED`, `LITERATURE_DERIVED`, `MODEL_ASSUMED`, `SCENARIO`,
  `HANDOFF_QUOTED`, `DATA_REQUIRED`) and a source. `DIGITIZED` is never
  reported as `EXPERIMENTAL`; `SCENARIO` spreads are never called confidence
  intervals; second-hand handoff values are never counted as verified.
* **No silent merging** — `apmt.genealogy` refuses to merge device records
  without `SERIAL_LEVEL_LINKAGE`, and a serial-level linkage must actually
  carry matching serial identifiers.
* **No silent rescaling** — EQE curves cannot be rescaled or offset without a
  documented primary source and citation (`NoUnsupportedRescalingError`).
* **Guard every solve** — V1.9-C makes invariants first-class: every solve, sweep,
  batch sample and level evaluation returns a PASS/WARN/FAIL/NOT_APPLICABLE record
  and a HARD failure makes the point INVALID rather than a warning; optimisers and
  surrogate datasets can therefore only ever see valid physics.
* **Multi-fidelity levels** — Levels 0–5 (`apmt.multifidelity.levels`) are explicit,
  documented fidelity changes with measured cross-level divergence; only L4/L5 are
  predictive (L0–L2 are MODEL-FORM-CRITICAL).
* **Fail loudly** — `apmt.validation.invariants` raises on R+T+A closure
  failure, EQE out of [0, 1], photon-budget leaks, tandem current violations,
  voltage/limit violations and detailed-balance breaches.
* **Strict gate** — thresholds are the V1.8 values and are never relaxed;
  `GateThresholds` is frozen and gate opening requires every check to PASS.
* **Determinism** — fixed seeds, `data/` hashes verified in CI; the historical
  digitization artifacts are byte-stable.

## Interpretive caveats

* The digitized Fig. S32 EQE curves integrate to 19.4301 / 20.1846 mA/cm²
  (top / bottom), which is 0.20 mA/cm² above the certified Jsc of 19.23.
  Digitization and certified-JV evidence are therefore not perfectly
  consistent; both are reported, neither is adjusted.
* The calibrated twin (24.41 %) matches a fitted model to digitized figure
  data. It must not be quoted as an experimental result, a record, or a
  breakthrough.
