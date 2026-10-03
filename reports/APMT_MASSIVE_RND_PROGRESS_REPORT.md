# APMT / SOLAR — MASSIVE R&D PROGRESS REPORT

**Cycle:** V1.9-A → V1.9-B (engineering hardening → model architecture)
**Date:** 2026-10-03
**Branch:** `arena/01a102e7-solar` · **Repository:** github.com/Thedivinetwilight/Solar
**Commits this cycle:** `abece5f` (V1.9-A1) → `ffe54e0` (V1.9-B1) → `b35cf66` (V1.9-B2) → `7cafe30` (V1.9-B3) → `f77979c` (V1.9-A2) → `4f88ec4` (V1.9-B1 continued: twin physics)
**Base (V1.8 endpoint, untouched):** `b846e2e2f1380f253f876e1ef9606b731dd1ca3d`

This is the single authoritative report for the cycle. Everything below is
derived from the repository state at the commits listed above; every number is
reproducible with the commands quoted in §13.

---

## 1. Inspected state (what was actually in the repository)

The V1.8 endpoint was inspected directly rather than trusted from hand-off text.
Verified facts, with the checks that established them:

| Claim | Verified? | Evidence |
| --- | --- | --- |
| V1.8 endpoint commit | YES | `git log`; `b846e2e…` |
| S32 champion labels 19.41 / 20.18 / 39.59 | YES | three independent digitization methods re-run non-mutatingly; 19.4301 / 20.1846 / 39.6146 |
| EQE conflict resolved (20.18 vs 16.90/17.11) | YES | superseded values remain immutable ledger entries; current pipeline does not reproduce them |
| Provenance/genealogy infrastructure | YES | `apmt/provenance.py`, `apmt/genealogy.py`; 4 linkages; no serial-level evidence |
| Strict gate, thresholds frozen | YES | `apmt/validation_gate.py` + `v1.8_validation_gate.json` |
| "41/41 tests passing" (manifest claim) | NO at V1.8 tip | V1.8 tip was **40 passed / 1 failed** because `data/sources/al_ashouri_accepted_manuscript.pdf` is absent. Resolved this cycle (§7, audit B): **61 passed / 1 explicit skip** |
| Manuscript PDF committed at `data/sources/…pdf` | **NO — the claim is false** | `git log --all -- 'data/sources/*'` is empty, `git ls-files` has no `sources/` entry, and `.gitignore` excludes `data/sources/*.pdf`. The file is an external, on-disk-only source; only its sha256 is recorded |
| `manifests/v1.8_reproducibility_manifest.json` is a valid integrity reference | **PARTLY** | `v1.8_full_report.md` is listed with sha256 `1e244b92…`; the committed blob hashes to `afe74262…`. The file was **not** modified by V1.9 (verified with `git show HEAD:<path>`), so the defect is in the manifest, not the history |
| Stored gate state "CLOSED (DEFER)" | **INCONSISTENT** | the V1.9 evaluator returns `FAIL` on the same evidence (G8 identifiability); `audit_v18_gate_consistency()` returns `consistent: false` |

## 2. Files added / changed / removed

**Added (V1.9-A1, commit `abece5f`)**
`apmt/core/{constants,units,numerics}.py`, `apmt/params/registry.py`,
`apmt/spectra/reference.py`, `apmt/materials/{silicon,perovskite}.py`,
`apmt/optics/tmm.py`, `apmt/device/detailed_balance.py`,
`tools/vendor_spectrum.py`, `tools/vendor_silicon_optics.py`,
vendored data `data/spectra/astm_g173_am15g_nlr.npz` (+meta),
`data/materials/silicon_green_keevers_1995.npz` (+meta).

**Added (V1.9-B1/B2/B3, commits `ffe54e0`, `b35cf66`, `7cafe30`, `4f88ec4`)**
`apmt/device/{recombination,subcell,tandem}.py`, `apmt/optics/stack.py`,
`apmt/experiments/evidence.py`, `apmt/inference/calibration.py`,
`apmt/validation/{extraction_validity,identifiability,optical_evidence,provenance_gate,invariants}.py`,
`apmt/validation/gate.py`, `apmt/cli.py`,
`tests/test_v19_optics_tandem.py`, `tests/test_v19_validation_evidence.py`,
`data/v19_calibration.json`, `data/v19_oat_sensitivity.json`,
`manifests/v1.9_artifact_pins.json`,
`tools/{ci_checks.py,v19_calibrate_twin.py,v19_oat_scan.py}`,
`.github/workflows/ci.yml`, `pyproject.toml`, `README.md` (rewritten).

**Changed** `apmt/genealogy.py` (linkage hardening, audit D),
`apmt/params/registry.py` (34 → 40 parameters),
`apmt/optics/stack.py` (wavelength-dependent TCO absorption),
`apmt/device/tandem.py` (rewritten solve; three bug fixes),
`data/s32_digitize_v18.py` (non-mutating default; audit B),
`tests/{test_eqe_s32_known_answers,test_gate_strict,test_no_device_merging}.py`,
`.gitignore` (deduplicated).

**Removed** nothing. No historical artifact was deleted, rewritten or renamed,
and no published historical number was changed.

## 3. Architecture and scientific changes

### 3.1 Layer map (19 layers, no monoliths)

| Layer | Module | Status this cycle |
| --- | --- | --- |
| units / dimensional safety | `apmt/core/units.py` | implemented; errors on mismatched dimensions |
| constants | `apmt/core/constants.py` | implemented |
| numerics (deterministic) | `apmt/core/numerics.py` | trapezoid integration, golden-section MPP, bisection, seeded RNG, array hashing |
| parameter registry | `apmt/params/registry.py` | **40 parameters**, each with unit, range, range-class, provenance category, description, source, uncertainty |
| spectra | `apmt/spectra/reference.py` | vendored ASTM G173 AM1.5G, hash-pinned |
| materials | `apmt/materials/{perovskite,silicon}.py` | Tauc/Urbach perovskite dispersion; Varshni Eg(T); Green–Keevers silicon n,k |
| optical physics | `apmt/optics/tmm.py`, `optics/stack.py` | coherent front stack + incoherent substrate; tandem stack |
| EQE / IQE | `apmt/optics/stack.py` (IQE-M1/M2) | two model forms, explicitly compared |
| recombination | `apmt/device/recombination.py` | radiative (generalised Planck) + SRH/surface slab model, T-scaled |
| tandem current | `apmt/device/tandem.py` | series-current solve with exact subcell inversion |
| thermal | `apmt/device/tandem.py::junction_temperature` | **new this cycle** (mechanism C wiring) |
| loss / interface | absorbed-photon budget, interface loss parameter | implemented |
| device / system | `apmt/device/tandem.py` | two-terminal series constriction, Rs, Rsh |
| optimization | `apmt/inference/calibration.py` (least squares) | implemented; global optimizers planned V1.9-D |
| sensitivity | `tools/v19_oat_scan.py` | OAT screening implemented; Sobol/LHS planned V1.9-C |
| uncertainty | identifiability diagnostics | SVD/correlation/profile likelihood implemented; UQ engine planned V1.9-E |
| inference / identifiability | `apmt/validation/identifiability.py` | implemented |
| experimental data | `apmt/experiments/evidence.py` | S32 + Fig. 4E ingestion with provenance |
| provenance | `apmt/provenance.py`, `apmt/validation/provenance_gate.py` | machine-checkable audit |
| validation gates | `apmt/validation/gate.py` | V1.9 evaluator (audit A) |
| reproducibility | manifests + `tools/ci_checks.py` | pins, determinism, provenance, gate, artifact consistency |
| reporting | this file | single authoritative report |

### 3.2 New physics this cycle (with justification)

**(i) Wavelength-dependent TCO / transport-layer absorption** (`optics/stack.py`)

    k_TCO(λ) = k_fc · (λ / 1000 nm)²  +  k_uv · exp(−(λ − 300 nm) / 60 nm)

Free-carrier (Drude-like) absorption rising towards the infrared, plus a
short-wavelength band-edge term. Justification: the front TCO of the champion
stack is a documented component, TCO free-carrier absorption is well documented
in the literature (10–20 nm ITO, k ≈ 0.01–0.06 at 1000 nm), and the *measured*
EQE/R-T-A shape cannot be reproduced without a wavelength-dependent parasitic
channel — the previous flat `k = 0.05` proxy produced 10.8 pp RMSE and a
0.995 parameter correlation (see §6.3). The term can only remove photons; it
never increases efficiency. Two new registered parameters
(`tco_free_carrier_k` = 0.02 [0, 0.20], `tco_uv_absorption_k` = 0.60 [0, 2.0]),
both labelled `LITERATURE_DERIVED / LITERATURE_SUPPORTED`; the 60 nm decay
length is a documented shape assumption.

**(ii) Junction temperature / self-heating — mechanism C wiring**

    T_junction = T_ambient + R_th,eff · G · f_heat
    R_th,eff = thermal_resistance_k_cm2_w · (1 − thermal_management_gain)
    G = irradiance_suns · 100 mW/cm² ,  f_heat = absorption_heat_fraction

Closure is deliberately **conservative**: all incident power is treated as heat
(the ≈20 % electrically extracted and ≈5 % reflected fractions are neglected),
over-estimating ΔT by roughly 25 %. At the registered default
(0.3 K·cm²/mW, one sun) ΔT = 30 K, i.e. T_j = 328.15 K. A refined energy-balance
closure is V1.9-C work. Before this change the registered thermal parameters had
**no effect whatsoever** on any output — a vacuous mechanism, which is exactly
what the directive forbids.

**(iii) Exact luminescent-coupling treatment** (`device/tandem.py`)

    I_rad,top(J) = j0_rad,top · expm1(V_top(J) / kT) ;  ΔJ_bottom = β · I_rad,top(J)

Because V_top(J) does not depend on the bottom cell, the coupling is closed-form
per bias point — no outer fixed-point iteration, no circularity. β = 0
reproduces the pre-change baseline bit-for-bit (verified).

### 3.3 Bugs found and fixed this cycle

| # | Bug | How it was found | Effect of the fix |
| --- | --- | --- | --- |
| B1 | **Shunt unit conversion was a no-op**: `J − V/Rsh · 1000/1000` — Rsh was numerically inert | OAT sensitivity scan showed dPCE/dRsh ≡ 0 exactly | PCE 20.8508 → **20.2412 %** (a *decrease*; Rsh now physically active) |
| B2 | **Luminescent coupling scale error**: the top-cell radiative current was evaluated at the *tandem* Voc (sum of both subcells), so exp(V/kT) exploded | β-sweep produced PCE = 141.9 % at β = 0.3 | β > 0 now bounded: β = 0.5 changes PCE by +0.013 pp; β = 0 unchanged |
| B3 | **Thermal layer unwired**: thermal resistance / management / heat-fraction parameters did nothing | OAT scan: all three inert | self-heating wired; −2.33 pp at one sun (honest, physically correct) |
| B4 | Dead `if False` ternary in the Voc interpolation | code read-through | removed |
| B5 | OAT tool reported zero-default *switch* parameters as inert (multiplicative scan can never leave 0) and crashed on numpy `bool_` JSON serialization | tool run | range-anchored scanning + explicit casts; genuine inert set now meaningful |

Two further loader defects from the V1.9-A groundwork were fixed within the same
cycle (wrong relative import of `classify_one_minus_r`; npz keys built from the
method tag instead of the method key) — both were caught by executing the code,
not by inspection.

## 4. Equations, parameters and provenance

### 4.1 Registry summary (40 parameters)

| Group | Parameters (default) |
| --- | --- |
| illumination / ambient | `temperature_k` 298.15, `irradiance_suns` 1.0, `spectrum_shift_nm` 0.0 |
| perovskite absorber | `perovskite_eg_ev` 1.68, `perovskite_thickness_nm` 500, `perovskite_urbach_mev` 20, `perovskite_absorption_alpha_ev` 5e4 cm⁻¹, `perovskite_n_inf` 2.35, `perovskite_oscillator_ev` |
| silicon | `silicon_thickness_um` 260, `silicon_eg_ev` (Varshni: 1.170 eV, α 4.73e-4, β 636 K), `silicon_light_trapping` 1.0 [1, 30], `silicon_srv_cm_s`, `silicon_bulk_lifetime_ms`, `silicon_doping_cm3` 1e16 |
| recombination | `radiative_efficiency_top` 0.02, `radiative_efficiency_bottom` 1e-4, `ideality_top` 1.45, `ideality_bottom` 1.05, `perovskite_srh_lifetime_ns` 1000, `perovskite_doping_cm3` 1e17, `perovskite_srv_cm_s` 1000 |
| mechanism B | `luminescent_coupling_top_to_bottom` 0.0 [0, 0.5], `photon_recycling_gain_top` 0.0 [0, 20] |
| optics (mechanism A) | `arc_thickness_nm` 100 [0, 220], `parasitic_layer_thickness_nm` 15 [0, 60], `tco_free_carrier_k` 0.02 [0, 0.20], `tco_uv_absorption_k` 0.60 [0, 2.0], `collection_efficiency_top/bottom` 0.98 [0.6, 1] |
| thermal (mechanism C) | `thermal_resistance_k_cm2_w` 0.3 [0.05, 2.0], `thermal_management_gain` 0.0 [0, 1], `absorption_heat_fraction` 1.0 [0, 1], `eg_temperature_coeff_ev_k` |
| series resistance | `rs_ohm_cm2` 1.5, `rsh_ohm_cm2` 3000, `interconnect_resistance_ohm_cm2`, `interface_loss_top_ma_cm2` |

Every parameter carries a provenance category (`EXPERIMENTALLY_CONSTRAINED`,
`LITERATURE_DERIVED`, `MODEL_ASSUMED`, `SCENARIO`, `DIGITIZED`,
`HANDOFF_QUOTED`, `DATA_REQUIRED`) and a range class
(`LITERATURE_SUPPORTED`, `EXPERIMENTALLY_CONSTRAINED`, `MODEL_ASSUMED`,
`EXPLORATORY`). A parameter that is not registered cannot be used: `spec(name)`
raises with an explicit message (this caught a stale `ere_bottom` reference in
the first OAT run).

## 5. Simulations run this cycle

| Simulation | Command | Result |
| --- | --- | --- |
| Optics closure / photon budget | `solve_tandem_optics` | max|R+T+A−1| = 2.2e-16; budget residual 7.1e-15 mA/cm² |
| Photon budget decomposition | 300–1250 nm | incident 48.6881 = R 4.6458 + parasitic 0.4178 + T 7.5637 + top 15.9993 + bottom 20.0615 mA/cm² |
| Detailed-balance reference | `detailed_balance_single_junction(1.34)` | Jsc 35.02, Voc 1.082, FF 0.889, **PCE 33.68 %** |
| Tandem twin, registry defaults | `apmt.cli twin` | PCE 17.91 % (T_j 328.15 K) / 20.24 % fixed-T |
| Tandem twin, IQE-M2 form | `evaluate_tandem(..., "IQE-M2")` | evaluated and reported (§6.4) |
| Twin calibration (IQE-M1) | `tools/v19_calibrate_twin.py --write` | 0.7 s; §6.3 |
| Twin calibration (IQE-M2) | `--model-form IQE-M2` | §6.4 |
| OAT screening | `tools/v19_oat_scan.py --write` | 114 solves, 123 s; §6.5 |

**Benchmarks (2 vCPU sandbox):** optics solve 11 ms (IQE-M1) / 2 ms (IQE-M2);
full tandem solve ≈ 1.12 s (dominated by the per-bias subcell inversions);
calibration fit 0.7 s; OAT scan 1.08 s per solve; test suite 12.6 s.

## 6. Analysis and results

### 6.1 Digital twin, registry defaults

| Configuration | PCE % | Jsc | Voc | FF | J_top | J_bottom | mismatch |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fixed-T diagnostic (298.15 K) | 20.2412 | 15.6141 | 1.5131 | 0.8567 | 15.7266 | 19.8030 | 1.259 |
| default (self-heating, T_j 328.15 K) | **17.9082** | 15.6415 | 1.3665 | 0.8378 | 15.7266 | 19.8030 | 1.259 |

The champion-class stack is **top-cell limited** by a factor 1.259: the
perovskite absorbs fewer photons than the silicon can use. Any mechanism that
only *adds* current to the bottom cell therefore cannot help (§6.6).

### 6.2 Loss decomposition (300–1250 nm, registry defaults)

Reflection 4.646 mA/cm² (9.5 % of the incident photon current), parasitic
0.418, transmission 7.564, top-cell absorption 15.999, bottom 20.062;
incident 48.688 mA/cm². The transmission loss is the single largest recoverable
photon pool, and it is *recoverable* only by thickening/re-texturing the
perovskite or by an intermediate reflector — i.e. mechanism A territory.

### 6.3 Calibration to digitized evidence (IQE-M1)

Fit target: the committed, digitized Fig. S32 EQE of the certified champion
(`hzb_M1`: 352 + 413 points). Result (`data/v19_calibration.json`):

| Quantity | Value |
| --- | --- |
| fitted `arc_thickness_nm` | 115.85 (range 0–220) |
| fitted `parasitic_layer_thickness_nm` | **60.0 — at the upper bound** |
| fitted `perovskite_thickness_nm` | 837.69 (range 150–1500) |
| fitted `collection_efficiency_top` | **1.000 — at the upper bound** |
| fitted `collection_efficiency_bottom` | 0.962 |
| fitted `silicon_light_trapping` | 10.23 (range 1–30) |
| RMSE top / bottom | 4.82 pp / 5.16 pp |
| max abs residual top / bottom | 0.192 / 0.180 |
| Jph top / bottom | 18.6250 / 20.6434 mA/cm² (targets 19.4301 / 20.1846) |
| condition number κ | **1300.8** (gate limit 1e4) |
| boundary hits | **2** (gate limit 0) |
| largest parameter correlation | 0.298 |
| flat directions (σ < 1e-3 σ_max) | 1 |
| tandem PCE at fitted parameters | 21.0199 % (T_j 328.15 K) |

Interpretation: with the TCO absorption channel included, the earlier
identifiability catastrophe (κ = 6074 with max|corr| = 0.995 on a 6-parameter
fit using a flat TCO proxy) becomes a well-conditioned fit. **The historical
G8 blocker was therefore partly a model-deficiency artefact, not only a data
deficiency.** But two parameters sit on their bounds, so G8 still fails on the
boundary-hit criterion, and the correct response is *new external
measurements* (DATA_REQUIRED), **not** widening the bounds or relaxing the gate.
Note also that this fit is to DIGITIZED figure data: even a perfect fit could
not open an experimental gate.

### 6.4 Model-form comparison (IQE-M1 vs IQE-M2)

| Form | RMSE top | RMSE bottom | κ | boundary hits | flat | Jph top | Jph bottom | PCE@fit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IQE-M1 (constant collection) | **4.82 pp** | 5.16 pp | 1300.8 | 2 | 1 | 18.6250 | 20.6434 | 21.02 % |
| IQE-M2 (αL/(αL+1) collection) | 18.00 pp | 6.25 pp | ∞ | 0 | 2 | 14.2920 | 20.2353 | 18.45 % |

IQE-M2 cannot reproduce the top-cell EQE plateau at all (max residual 0.46) and
its Jacobian is singular. On this evidence the constant-collection form is the
better *description of the measured data*, and the diffusion-limited form is
retained only as a divergence check. No promotion is claimed: both are
MODEL-COMPUTED and neither is experimentally validated.

### 6.5 Sensitivity and structurally inert parameters (OAT screen)

Post-fix OAT ranking (max |ΔPCE| over each parameter's registered range,
114 solves, 123 s), largest first:

`perovskite_thickness_nm` 5.12 pp · `collection_efficiency_top` 3.53 ·
`perovskite_eg_ev` 2.53 · `thermal_resistance_k_cm2_w` 2.39 ·
`thermal_management_gain` 2.33 · `arc_thickness_nm` 1.96 ·
`photon_recycling_gain_top` 1.25 · `absorption_heat_fraction` 1.17 ·
`collection_efficiency_bottom` 0.81 · `rsh_ohm_cm2` 0.48 · `rs_ohm_cm2` 0.33 ·
`radiative_efficiency_top/bottom` 0.285/0.285 · `silicon_thickness_um` 0.15 ·
`tco_uv_absorption_k` 0.13 · `silicon_light_trapping` 0.098 ·
`parasitic_layer_thickness_nm` 0.079 · `tco_free_carrier_k` 0.033 ·
`luminescent_coupling_top_to_bottom` 0.018.

**Structurally inert (< 1e-4 pp) in this configuration:**
`perovskite_srh_lifetime_ns`, `perovskite_srv_cm_s`, `perovskite_doping_cm3`
(near-inert: `silicon_doping_cm3` 0.0009 pp). The top-cell dark current is
dominated by the ERE-parameterised radiative term (j0_rad 2.368e-18 vs
j0_SRH 5.857e-20 mA/cm², radiative fraction 0.976), so the SRH route parameters
are **unlearnable from tandem efficiency data** in this configuration. This is a
genuine identifiability result and an input to the VOI engine (§11).

### 6.6 Mechanism directions (honest negatives)

* **Top→bottom luminescent coupling is ineffective in this device.** The tandem
  is top-limited (ratio 1.259) and coupling pumps current into the *already
  surplus* bottom cell: β = 0.5 changes PCE by **+0.013 pp**. The lever that
  would matter — bottom→top coupling (silicon emission re-absorbed by the
  perovskite) — is **not implemented**; the model must not be used to claim a
  coupling benefit before it is.
* **Photon recycling is a real lever (1.25 pp over its range)**, but its effect
  is entirely in the top-cell Voc and it is parameterised as a radiative-lifetime
  enhancement factor; it is MODEL-OBSERVED only, and it must not be double
  counted with `radiative_efficiency_top` (which already embeds recycling).
* **Thermal management is the largest single APMT lever in this twin (2.39 pp)**
  — purely because the default thermal closure is pessimistic (30 K rise, all
  incident power as heat). That is a *modelling* statement, not a discovery:
  measured thermal data are DATA_REQUIRED.
* **Optical management (thickness, ARC, collection) dominates everything**, up
  to 5.12 pp, and the calibrated stack wants ≈838 nm of perovskite — thicker
  than the 500 nm registered default, which is a *fit to digitized data*, not
  evidence that the real device is thicker.

### 6.7 Data-consistency finding (negative result)

The digitized Fig. S32 EQE of the champion integrates to 19.4301 (top) +
20.1846 (bottom) mA/cm², whereas the certified short-circuit current density for
the same device is 19.23 mA/cm² — the digitized top-cell integral exceeds the
certified value by **0.20 mA/cm² (1.05 %)**. Both numbers are reported, neither
is adjusted, and no rescaling is permitted without a documented primary source
(`NoUnsupportedRescalingError`). Any APMT gain smaller than ≈1 % in Jsc is
therefore below the present evidence-quality floor.

### 6.8 Full-stack R/T/A and the 1−R traces (audit C)

The three S32 one-minus-R traces classify as: `hzb_M1` **LOW_SUPPORT**,
`hzb_M2` **INVALID_EXTRACTION**, `hzb_M3` **INVALID_EXTRACTION**; the
Fig. 4E traces: M2 **USABLE** (247 points, median 97.4 %), M1 INVALID (23 pts),
M3 INVALID (5 pts, 1190–1199 nm, median 4.1 %). The implausible 900-dpi Fig. 4E
1−R trace is therefore confirmed as an invalid extraction *and* the platform no
longer depends on it: no mechanism or gate check consumes it.

## 7. Validation, gate and audit results

### 7.1 Strict gate (V1.9 evaluator, current evidence)

    evaluation_result = FAIL
    gate_open         = False
    blocking_checks   = [G5, G6, G7, G8, G9]
    data_required     = [G5, G7, G9]

* G1 PASS (|19.23 − 19.41| = 0.18 ≤ 0.30), G4 PASS (scan directions 0.01 ≤ 0.20), G3 PASS (RMSE 0.917 ≤ 1.00)
* G5, G7, G9 DATA_REQUIRED — no full-stack R/T/A with uncertainties, no external Rs/Rsh, no machine-checkable provenance audit supplied
* G6 FAIL on the serial-evidence requirement (NO_SERIAL_ID for all linkages)
* G8 FAIL (boundary hits 2 > 0; the condition number is now 1300.8 ≤ 1e4)
* V1.8 stored state "CLOSED (DEFER)" vs V1.9 evaluation **FAIL** → `consistent: false`. Thresholds were **not** changed; only the implementation was made faithful. A new test (`test_current_apmt_evidence_cannot_pass`) pins this.

### 7.2 Audit items A–I

| Item | Status | Where |
| --- | --- | --- |
| A — gate output separates result/state/blockers/DATA_REQUIRED | **DONE** | `apmt/validation/gate.py`; `audit_v18_gate_consistency` |
| B — non-mutating tests + explicit artifact-generation commands | **DONE** | `data/s32_digitize_v18.py` (`main(write=False, require_pdf=True)`), `tools/v19_calibrate_twin.py --write`; PDF-dependent M2 test skips with an explicit reason |
| C — classify the implausible Fig. 4E 1−R without depending on it | **DONE** | `apmt/validation/extraction_validity.py`; §6.8 |
| D — merge protection requires serial-level evidence | **DONE** | `apmt/genealogy.py`: SERIAL_LEVEL_LINKAGE now requires matching serial identifiers; 3 invalid constructions rejected |
| E — G9 must not rely on a caller-supplied counter | **DONE** | `apmt/validation/provenance_gate.py`: 37 ledger claims audited, **2/37 verified**; a bare counter now yields DATA_REQUIRED, never PASS |
| F — G5 must verify grids/coverage/units/uncertainty/closure | **DONE** | `apmt/validation/optical_evidence.py`; a gapped 500–900 nm spectrum now FAILS G5 explicitly |
| G — serious README | **DONE** | `README.md` (status table, rules, caveats) |
| H — `pyproject.toml` with compatible versions | **DONE** | `pyproject.toml` (numpy ≥2,<3; scipy ≥1.11,<2; pvlib ≥0.10,<1; pillow ≥10) |
| I — non-mutating CI | **DONE** | `.github/workflows/ci.yml` + `tools/ci_checks.py` (6 checks; 4/6 pass locally, the two remaining are "report exists" and "git clean", both satisfied by this commit) |

### 7.3 Invariant checks that now fail loudly

`apmt/validation/invariants.py` raises `InvariantViolation` on: R+T+A closure
(>1e-6), EQE/IQE out of bounds, EQE > absorber absorptance, photon-budget leak
(>1e-6 mA/cm²), tandem current above min(subcell)+coupling, Voc above ΣEg or
Vmp > Voc, PCE above the radiative ceiling, negative loss channels,
non-monotone absorptance with thickness, Voc increasing with temperature, and
undefined convergence status. Six of these are directly exercised by tests.

## 8. Reproducibility

* Environment pins: numpy 2.4.6, scipy 1.17.1, pvlib 0.16.1, pytest 9.1.1, PyMuPDF 1.28.2 (recorded in `manifests/v1.8_reproducibility_manifest.json` and re-declared with bounds in `pyproject.toml`).
* Artifact pins (`manifests/v1.9_artifact_pins.json`, 6 files) are verified in CI; `tools/ci_checks.py` re-runs the digitization deterministically and compares against the committed JSON.
* Determinism: the Fig. S32 pipeline reproduces `s32_results.json` for all
  raster/coordinate methods; `data/s32_results.json` md5
  `aaebd692f9daeb60d203a8873c32fae2` and `data/s32_curves.npz` md5
  `39321b876f925a0f2b7e6246be9b459a` are unchanged from V1.8.
* Historical ledger: 37 hand-off-quoted claims audited; **2 verified**, 35
  unverifiable-by-construction (the original artifacts are absent). Scenario
  values (30.636 / 27.007 / 26.677 / 30.352 %) remain classified SCENARIO and
  are never presented as measurements or as confidence intervals.
* V1.8 manifest defect disclosed: `v1.8_full_report.md` hash mismatch
  (§1); the file was not modified by this cycle, and the manifest was not
  rewritten.

## 9. Negative results (explicit)

1. Top→bottom luminescent coupling cannot relieve this device's current limitation (≤ 0.02 pp).
2. Top-cell SRH lifetime, doping and surface recombination are unlearnable from tandem efficiency data in this configuration.
3. The IQE-M2 (diffusion-limited) model form fails on the top subcell (18 pp RMSE, singular Jacobian).
4. The calibrated fit is boundary-limited on two parameters → identifiability is not yet resolved, only improved.
5. Digitized top-cell EQE exceeds the certified Jsc by 1.05 % — the evidence floor for any claimed gain.
6. The manuscript PDF and several historical artifacts are absent; 35/37 historical claims cannot be verified in this repository.
7. No experimental APMT claim is currently possible: the gate is CLOSED and the baseline is DATA-LIMITED.

## 10. Insights

* The historically reported identifiability failure (κ = 1.216e6) was partly a
  *model deficiency*: adding the documented wavelength-dependent TCO absorption
  reduces κ by ~3–4 orders of magnitude and collapses the 0.995 ARC↔TCO
  correlation. Model form and identifiability cannot be assessed separately.
* The largest *recoverable* photon pool is transmission into the silicon from an
  optically thin top cell (7.56 mA/cm²) — this, not coupling, is where mechanism
  A has room.
* A single OAT screen found two genuine physics bugs (inert shunt, runaway
  coupling). Cheap screening of "parameters that do nothing" is a high-value
  bug detector and should run in CI.
* An honest thermal closure changes the headline twin number by −2.33 pp. Any
  efficiency statement about this stack must state its temperature assumption.

## 11. Uncertainty, VOI and open model questions

* Parameter uncertainty: only identifiability structure is quantified so far
  (SVD, correlation, profile likelihood). Full covariance/Fisher/bootstrap and
  the measurement-vs-model-vs-numerical decomposition are V1.9-E work.
* Highest-value missing measurements, in order: (1) full-stack R/T/A with
  uncertainties (unlocks G5 and constrains the optical block), (2) external
  Rs/Rsh from dark J–V/Suns-Voc (unlocks G7 and breaks the Rsh↔FF degeneracy),
  (3) temperature-resolved J–V (constrains the thermal closure, currently the
  largest single lever), (4) same-device EQE with a certified Jsc anchor
  (resolves the 1.05 % integral conflict).
* No confidence interval in this report is derived from scenario spread.

## 12. Computational cost

| Task | Time | Notes |
| --- | --- | --- |
| optics solve (300–1250 nm, 5 nm, 191 points) | 11 ms / 2 ms | IQE-M1 / IQE-M2 |
| tandem solve | 1.12 s | 400 bias points × 2 subcell inversions |
| calibration (6 parameters, 765 residuals) | 0.7 s | least squares + finite-difference Jacobian |
| OAT scan (114 solves) | 123 s | trivially parallelizable; planned |
| test suite | 12.6 s | 61 passed, 1 skip |

No artifact explosion: 6 pinned artifacts totalling ≈50 kB; no per-run output
directories, no near-duplicate files.

## 13. Reproduction commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q                       # 61 passed, 1 skip (PDF absent)
.venv/bin/python tools/ci_checks.py                 # pins/determinism/provenance/gate/report
.venv/bin/python -m apmt.cli twin                   # registry-default twin (self-heating)
.venv/bin/python -m apmt.cli twin --no-self-heating  # fixed-T diagnostic
.venv/bin/python -m apmt.cli gate                   # strict gate + V1.8 consistency audit
.venv/bin/python tools/v19_calibrate_twin.py --write # data/v19_calibration.json + pins
.venv/bin/python tools/v19_oat_scan.py --write       # data/v19_oat_sensitivity.json
python data/s32_digitize_v18.py --write              # historical digitization artifacts
```

## 14. Remaining blockers

1. **Evidence (blocking the gate):** no full-stack R/T/A; no external Rs/Rsh; no
   serial-level device linkage. The gate cannot open on modelling work by
   construction, and must not.
2. **Identifiability:** 2/6 fitted parameters sit on bounds; needs external
   constraints.
3. **Missing sources:** manuscript PDF absent (M2 unverifiable); 35/37 historical
   claims unverifiable; `v1.8_full_report.md` manifest hash defect.
4. **Model form:** IQE-M1 is preferred but is a constant-collection
   parameterisation; the top-cell transport physics (surface recombination
   velocity, real absorption coefficient) is not yet constrained by data.
5. **Not yet implemented:** global optimization, sampling, Sobol/LHS, surrogate
   models, UQ engine, VOI engine, synthetic experiment lab, discovery engine,
   multi-fidelity Levels 0–5, bottom→top luminescent coupling, refined thermal
   energy balance, and the autonomous campaign loop. These are V1.9-C…F.

## 15. Next recommended direction

1. **V1.9-C (simulation engine):** wire `validation/invariants.py` into every
   solve; refined thermal energy balance; bottom→top coupling; Level 0–5
   multi-fidelity ladder with divergence cross-checks; vectorize the tandem
   solve (target ≥10× for campaign work) with recorded memory/agreement.
2. **V1.9-D (optimization/discovery):** LHS + Sobol + interaction search over
   mechanisms A/B/C (baseline/A/B/C/AB/AC/BC/ABC), local + multi-start global
   optimization, surrogate-assisted search with speedup *and* approximation
   error reported, Pareto fronts with full provenance per candidate.
3. **V1.9-E (uncertainty/VOI):** covariance, Fisher, bootstrap, profile
   likelihood, posterior sampling, decomposition of measurement vs parameter vs
   model uncertainty; VOI engine ranking the four measurements in §11.
4. **V1.9-F (experimental readiness):** synthetic experiment lab as a permanent
   regression suite; injection/recovery tests (EQE, R/T/A, dark J–V, Suns-Voc,
   Rs/Rsh, PL, T-resolved), failure-mode catalogue, experiment-design engine.
5. **Report/claim discipline:** no APMT result may be reported above
   MODEL-OBSERVED until G5, G6, G7 and G8 actually pass on measured evidence.

## 16. Honesty statement

No threshold was relaxed, no historical number was edited, no measurement was
silently fitted, no uncertainty was re-labelled as a confidence interval, and no
result in this report is called a breakthrough, proven, or experimentally
validated. Every efficiency figure above is a MODEL-COMPUTED value under stated
assumptions; the only experimentally anchored numbers are the digitized Fig. S32
integrals and the source-reported certified values, each labelled DIGITIZED or
HANDOFF-QUOTED respectively.
