# APMT / SOLAR — MASSIVE R&D PROGRESS REPORT

**Cycle:** V1.9-A → V1.9-B (engineering hardening → model architecture) → **V1.9-C
(physics engine hardening: invariants, vectorization, thermal rebuild, bottom→top
coupling, multi-fidelity levels)**
**Date:** 2026-10-03
**Branch:** `arena/01a102e7-solar` · **Repository:** github.com/Thedivinetwilight/Solar
**Commits this cycle:** `abece5f` (V1.9-A1) → `ffe54e0` (V1.9-B1) → `b35cf66` (V1.9-B2) → `7cafe30` (V1.9-B3) → `f77979c` (V1.9-A2) → `4f88ec4` (V1.9-B1: twin physics) → `c4bf52d` (V1.9-B4: self-heating, coupling, OAT, CLI) → `f2dea0a` (V1.9-B5: this report) → `a9091bd` (V1.9-B6: report refresh) → **V1.9-C1: mechanism campaign #1** (§6.9). Branch pushed to `origin/arena/01a102e7-solar`.
**Base (V1.8 endpoint, untouched):** `b846e2e2f1380f253f876e1ef9606b731dd1ca3d`
**V1.9-C part:** Part V1.9-C below (starts at §17). It preserves every V1.9-B
number in place and marks superseded values explicitly where a model form was
replaced.

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
| Mechanism campaign #1 | `tools/v19_mechanism_campaign.py --write` | 2³ factorial + dose-response + 96-sample LHS; 124 s; §6.9 |

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

### 6.9 Mechanism campaign #1 — factorial, dose-response, LHS screen

`data/v19_mechanism_campaign.json` (label: **PRE-GATE / MODEL-OBSERVED /
EXPLORATORY**). Mechanisms are modelled as registered-parameter toggles:
A optical management (`collection_efficiency_top/bottom`, `silicon_light_trapping`),
B photon recycling (`photon_recycling_gain_top`), C thermal management
(`thermal_management_gain`).

**2³ factorial (8 solves, baseline 17.9082 pp):**

| Effect | Value (pp) |
| --- | --- |
| A direct | +0.555 |
| B direct | +0.737 |
| C direct | +1.401 |
| A×B interaction | +0.016 |
| A×C interaction | +0.022 |
| B×C interaction | −0.041 |
| A×B×C interaction | −0.002 |
| all three ON | **+2.688** (20.5965 pp) |

The mechanisms are **essentially additive in this model**: the largest
interaction is 3 % of the largest direct effect. This is labelled
**MODEL-FORM-FRAGILE**: the additivity is a property of the current
parameterisation (the three mechanisms act on separable model terms), not an
empirical finding. Coupled pathways that would break additivity — photon
recycling feeding the luminescent-coupling channel, thermal shift of the
absorption edge feeding the optical block — are not yet implemented, so an
"APMT synergy" claim would be unsupported *and an "APMT has no synergy" claim
would be equally unsupported*.

**Dose–response (30 solves):**

| Mechanism | Sweep | PCE range (pp) | Shape |
| --- | --- | --- | --- |
| A light trapping | 1 → 5 | 17.908 → 18.092 | saturating |
| B recycling gain | 0 → 20 | 17.908 → 19.159 | sub-linear, saturating |
| C thermal gain | 0 → 1 | 17.908 → 20.241 | linear in the gain |

**LHS screen (96 solves, 124 s):** PCE mean 15.23, sd 5.57, min/max within the
sampled envelope. Linear surrogate R² = **0.576** — i.e. a linear model explains
only 58 % of the variation over the *full registered ranges*, which are wide
(e.g. E_g 1.1–2.1 eV). Standardised regression coefficients (bootstrap 95 % CI):

| Parameter | SRC | 95 % CI | Spearman ρ |
| --- | --- | --- | --- |
| `thermal_resistance_k_cm2_w` | −0.518 | [−0.678, −0.366] | −0.482 |
| `thermal_management_gain` | +0.506 | [+0.350, +0.653] | +0.513 |
| `perovskite_eg_ev` | +0.138 | [+0.004, +0.278] | +0.013 |
| `perovskite_thickness_nm` | +0.131 | [−0.019, +0.257] | +0.214 |
| `silicon_light_trapping` | −0.128 | [−0.267, +0.064] | −0.125 |
| `arc_thickness_nm` | +0.059 | [−0.086, +0.173] | +0.148 |
| `rsh_ohm_cm2` | +0.025 | [−0.122, +0.159] | +0.053 |
| `photon_recycling_gain_top` | +0.017 | [−0.145, +0.166] | +0.000 |
| `radiative_efficiency_top` | +0.010 | [−0.130, +0.151] | +0.032 |

Only the thermal axis is a *robust* first-order driver in this screen. Two
honesty notes:

* the near-zero marginal SRC of photon recycling **contradicts** its clear
  positive effect in the factorial (+0.737 pp) and dose-response (+1.25 pp). A
  targeted check (6 LHS points, gain 0 → 20) gives +0.06 … +0.40 pp at every
  non-degenerate point, so the marginal signal is real but small compared with
  the variance injected by the thermal and bandgap axes. **LHS rank screening
  over wide ranges cannot detect weak-but-real effects** — that is a limitation
  of the screen, not evidence of no effect, and it is reported rather than
  quietly dropped.
* `perovskite_eg_ev` has SRC +0.138 but ρ = +0.013: the true response is
  strongly non-monotone (it has an interior optimum), so the linear surrogate is
  misleading for that parameter.

**Registered-range audit finding.** The LHS envelope contains corners where the
twin returns PCE ≈ 1 % at a junction temperature of ≈454 K
(`thermal_resistance_k_cm2_w` × `irradiance_suns` extremes). A 200 K rise is not
physically realisable for a glass-mounted cell, so the registered upper bound
2.0 K·cm²/mW (classified EXPLORATORY) is **too wide to be physically meaningful
at one sun**. The range is not silently narrowed here (that would be a silent
change to a registered assumption); it is flagged for re-justification in
V1.9-C, together with an explicit envelope flag on out-of-envelope samples.

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
| I — non-mutating CI | **DONE** | `.github/workflows/ci.yml` + `tools/ci_checks.py` (6/6 checks pass after the report commit) |

### 7.3 Invariant checks that now fail loudly

`apmt/validation/invariants.py` raises `InvariantViolation` on: R+T+A closure
(>1e-6), EQE/IQE out of bounds, EQE > absorber absorptance, photon-budget leak
(>1e-6 mA/cm²), tandem current above min(subcell)+coupling, Voc above ΣEg or
Vmp > Voc, PCE above the radiative ceiling, negative loss channels,
non-monotone absorptance with thickness, Voc increasing with temperature, and
undefined convergence status. Six of these are directly exercised by tests.

## 8. Reproducibility

* Environment pins: numpy 2.4.6, scipy 1.17.1, pvlib 0.16.1, pytest 9.1.1, PyMuPDF 1.28.2 (recorded in `manifests/v1.8_reproducibility_manifest.json` and re-declared with bounds in `pyproject.toml`).
* Pinned artifacts are **byte-deterministic**: wall-clock timings are printed to
  the console but never written into a pinned file (a V1.9 implementation fix —
  the first calibration artifact changed hash on every run). Verified by running
  each generator twice and comparing sha256.
* Artifact pins (`manifests/v1.9_artifact_pins.json`, 7 files) are verified in CI; `tools/ci_checks.py` re-runs the digitization deterministically and compares against the committed JSON.
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

### 11b. V1.9-C supersession notes (V1.9-B numbers preserved above)

* The **self-heated** twin efficiency in V1.9-B (17.9082 %, ΔT 30.0 K, all
  incident power as heat, PCE 20.2412 % fixed-T) is **superseded for the default
  model** by the V1.9-C energy-balance closure: **19.2633 %**, ΔT 12.59 K,
  PCE 20.2417 % fixed-T. The V1.9-B value remains reproducible
  (`evaluate_tandem(ps, thermal_model="simple")` → 17.9085 %) and is kept for
  lineage, not as a current model result. The README twin row was updated to show
  both closures.
* The V1.9-B registered-range finding (Tj ≈ 454 K) is **resolved**, not deleted:
  the corner is reproducible under the legacy closure (R_th ≈ 1.556 K cm²/mW →
  453.75 K, PCE 1.97 %) and is unreachable under the energy balance (337.6 K,
  17.17 %) because the missing radiative pathway carries ~51 % of the heat load.
  See §23.
* The calibrated twin (21.0199 % fixed-T / 23.8146 % with the thermal gain) is
  unchanged by V1.9-C: the calibration path uses the same physics and its
  artifact hash (`data/v19_calibration.json` sha256 `6da5a9e3…`) still matches its
  pin, verified by `tools/ci_checks.py`.

## 12. Computational cost

| Task | Time | Notes |
| --- | --- | --- |
| optics solve (300–1250 nm, 5 nm, 191 points) | 11 ms / 2 ms | IQE-M1 / IQE-M2 |
| tandem solve | 1.12 s | 400 bias points × 2 subcell inversions |
| calibration (6 parameters, 765 residuals) | 0.7 s | least squares + finite-difference Jacobian |
| OAT scan (114 solves) | 123 s | trivially parallelizable; planned |
| mechanism campaign #1 (8 + 30 + 96 solves) | 124 s | 1.08 s per solve |
| test suite | 12.6 s | 61 passed, 1 skip (V1.9-B) |
| fast tandem solve (V1.9-C) | 61 ms | vectorised Newton + table inversion, cold cache |
| fast tandem solve (V1.9-C, warm cache) | 4–40 ms | per level (L2 → L5) |
| self-heated solve (V1.9-C) | ≤ 0.05 s | 4–6 electrical solves in the thermal loop |
| reference oracle solve (V1.9-C) | 32.4 s | preserved V1.9-B scalar bisection |
| engine campaign (all sections) | 1,696 s | dominated by the 3-point reference benchmark |
| test suite (V1.9-C) | 81 s | 142 passed, 1 skip (reference-oracle comparisons) |

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
5. **Registered-range audit:** `thermal_resistance_k_cm2_w` upper bound implies
   a 200 K rise at one sun; the LHS envelope therefore contains unphysical
   corners. Re-justify the bound (or add an explicit physical-envelope guard)
   in V1.9-C.
6. ~~**Not yet implemented:** … multi-fidelity Levels 0–5, bottom→top luminescent
   coupling, refined thermal energy balance …~~ **V1.9-C delivered** the refined
   thermal energy balance (§23), bottom→top coupling (§24), Levels 0–5 with
   divergence analysis (§25), the invariant/guard framework (§19), the vectorised
   solver + batch API (§21/§28), inert screening 2.0 (§26), ablation, limit and
   convergence tests (§27). Still not implemented (V1.9-D…F): global optimization,
   Sobol variance decomposition, surrogate models, UQ/VOI engines, the synthetic
   experiment lab, the discovery engine and the autonomous campaign loop.

## 15. Next recommended direction

1. **V1.9-C (simulation engine):** wire `validation/invariants.py` into every
   solve; refined thermal energy balance; bottom→top coupling; Level 0–5
   multi-fidelity ladder with divergence cross-checks; vectorize the tandem
   solve (target ≥10× for campaign work) with recorded memory/agreement.
2. **V1.9-D (optimization/discovery):** Sobol variance decomposition (with a
   surrogate whose approximation error is reported) + interaction search over
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

---

# PART V1.9-C — PHYSICS ENGINE HARDENING, INVARIANT ENFORCEMENT, VECTORIZATION, THERMAL REBUILD, BOTTOM→TOP COUPLING, MULTI-FIDELITY LEVELS

**Cycle:** V1.9-C · **Date:** 2026-10-04 · **Branch:** `arena/01a102e7-solar`
**Commits:** see §31 (V1.9-C commit map). **Base:** `f47aede` (V1.9-C1, unchanged) ← `b846e2e2…` (V1.8 endpoint, untouched).
**Status of everything in this part: PRE-GATE / MODEL-OBSERVED / EXPLORATORY.**
No experimental claim is made anywhere in V1.9-C. The baseline gate remains
**CLOSED** and was not touched (§7.1 is still the current gate state).

## 17. What V1.9-C changed, and why

V1.9-C is an *engine* cycle: the physics model forms were not rewritten to chase
efficiency — they were made auditable, faster, and harder to fool. Five
deliverables:

1. **Invariants became first-class** with a machine-readable verdict on every
   solve, and a **guard** that makes any HARD violation INVALID (not a warning).
2. **The tandem solve was vectorised** against a preserved scalar **reference
   oracle**, with quantified agreement.
3. **The thermal closure was rebuilt** as a solved energy balance (conduction +
   radiative cooling), and the V1.9-B ≈454 K corner was investigated to a
   conclusion.
4. **Bottom→top coupling was implemented and measured** — and found to be
   physically absent at these bandgaps; the non-existence is demonstrated with
   numbers rather than asserted.
5. **Multi-fidelity Levels 0–5** with cross-level divergence classification,
   inert-parameter screening 2.0, ablation, limit tests and convergence tests.

Three defects were found *by the new machinery itself* (all fixed, all with
regression tests): the concentration PCE unit bug (§20), the fixed-temperature
thermal reporting inconsistency (§19), and the electrical validity-envelope
failure at extreme corners (§23). Two dead-parameter defects were found by
screening 2.0 and fixed by wiring the parameters to the physics that they claim
to model, not by declaring them inert (§26).

## 18. Engine audit (item 1) — input → physics → result trace

The audit walked every documented path rather than the intended one.

**Full trace of one evaluation** (`evaluate_tandem(ps, solver="fast", thermal_model="energy_balance")`):

| Stage | Code | Inputs | Outputs | Cost |
| --- | --- | --- | --- | --- |
| spectrum | `apmt/spectra/reference.py` | ASTM G173 npz, `spectrum_shift_nm` | `Spectrum` (191 pts, 300–1250 nm) | 0 (cached) |
| optics | `apmt/optics/stack.py` + `tmm.py` | ARC/parasitic/TCO layers, thicknesses, `rear_reflectance` | R/T/A per layer, EQE, Jsc_subcell, absorbed power | 11 ms (lru-cached) |
| subcell model | `apmt/device/subcell.py`, `recombination.py` | Eg, thickness, lifetime/SRV or calibrated J0 override, Rs/Rsh | J(V) with two-diode + shunt | — |
| tandem solve | `apmt/device/tandem.py::solve_tandem_fast` | two subcell tables, coupling flags | Voc, MPP, Jsc (current-source limit), FF, PCE | 4.2 ms |
| thermal | `apmt/device/thermal.py::solve_equilibrium` | absorbed power, T→P_elec callback, R_th, ε | Tj, balance residual, stability derivative | 6–7 electrical solves |
| invariants | `apmt/validation/guard.py` | result + optics + parameter point | `InvariantBundle` (PASS/WARN/FAIL/NA) | < 1 ms |

**Bottleneck found by profiling (cProfile, V1.9-B engine):** 67,462 scalar
`current_density` calls and 1,607 `bisect` calls per self-heated solve — the
scalar bisection per bias point was the whole cost. That profile motivated the
vectorised Newton solver (§21) and the reference/oracle split (§22).

**Paths audited and their state after V1.9-C:**

| Path | Invariants wired? | Guarded? | Notes |
| --- | --- | --- | --- |
| forward solve (`evaluate_tandem`) | YES (`detail["invariants"]`, `detail["solve_valid"]`) | via `evaluate_guarded` | every solve now carries a verdict |
| sweeps / limit tests | YES | YES | corners outside the validity window return INVALID |
| calibration | YES | YES | residuals use guarded solves; an INVALID solve cannot enter the objective |
| LHS / batches | YES | YES (`device/batch.py`) | invalid rows are excluded from datasets and counted |
| stages 0–5 (`multifidelity/levels.py`) | YES | YES | switches are real: a guarded L2 solve runs L2 physics |
| synthetic data generation | YES | YES (`dataset()`) | "no invalid physics in training data" is enforced, not documented |

**Audit finding (a real one):** before this cycle `evaluate_guarded(level="L2")`
recorded `L2` in its metadata but evaluated **full-physics L4**, because the
guard called `evaluate_tandem` directly. Any campaign that trusted the recorded
level was therefore mislabelled. Fixed: the guard now dispatches through
`evaluate_level`/`evaluate_with_options`, and
`tests/test_v19_engine.py::test_batch_api_and_serial_guarded_agree` pins the
equality of the batch and serial paths *including their switch dictionaries*.

## 19. Invariant enforcement (items 2–3)

**Design.** `apmt/validation/invariants.py` now carries a first-class layer
alongside the V1.9-B checks (both retained, one registry):
`InvariantStatus` (PASS/WARN/FAIL/NOT_APPLICABLE), `Severity` (HARD/SOFT),
`InvariantRecord`, `InvariantBundle` (`.valid` ⇔ no HARD FAIL), and a `CHECKS`
registry of 23 named checks. The V1.9-B `InvariantReport` shape gained
`.status`/`.to_record()` so both generations are consumable uniformly.

**Families and examples** (all machine-readable, all in the verdict):

| Group | Checks | Severity policy |
| --- | --- | --- |
| optical | R+T+A closure over all stack layers, bounded R/T/A, wavelength grid integrity (finite/positive/monotone/duplicate-free/min-points), photon budget, radiometric power conservation | HARD |
| electrical | current continuity (`Jsc ≤ min(Jsc_subcells)`), range/absurdity bounds, strictly-positive radiative J0, J0 channel sum, Rs ≥ 0 / Rsh > 0, shunt direction, Voc ≤ ΣEg, Vmp ≤ Voc, radiative-limit consistency | HARD (shunt direction SOFT) |
| thermal | energy balance (abs 1e-3 mW/cm² or rel 1e-6), stability `d(loss)/dT > d(heat)/dT`, equilibrium convergence, electrical-validity envelope, temperature envelope, fixed-T declaration consistency | balance/stability/convergence/envelope HARD; temperature envelope SOFT |
| numerical | finiteness (NaN/Inf), solver convergence flag, monotonicity, non-negativity | HARD |
| data | units/range/dimension checks on grids and curve arrays | HARD |

**Guard.** `apmt/validation/guard.py` builds the verdict, attaches it to the
result (`detail["invariants"]`, `detail["solve_valid"]`) and returns a
`SolveRecord` carrying the parameter point, level, solver, campaign id, seed,
runtime and error text. `evaluate_guarded` never raises: a solver exception
becomes an INVALID record with the error preserved.

**Proof that the guard is not decoration** (each case has a test):
a 141.93 % "efficiency" (the V1.9-B coupling-scale pathology) → HARD
`electrical.radiative_limit` FAIL; Jsc = 0, FF = 0, Vmp > Voc, NaN PCE, and
Jsc = 1e6 mA/cm² → INVALID; j0_RAD = 0 → INVALID (a zero radiative channel would
silently disable the radiative ceiling); thermal residual above tolerance →
INVALID.

**Defect caught by the invariants:** the fixed-temperature diagnostic reported
the *simple-closure* junction temperature (328.15 K) while the physics had been
solved at 298.15 K. The new `thermal.fixed_temperature_declared` check failed
immediately; the reporting is now consistent (`Tj = T_amb`, no balance claimed).

## 20. Unit & dimension audit (item 4)

Canonical internal units, checked by
`tests/test_v19_multifidelity.py::test_*_units`: wavelength and thickness **nm**
(cm only inside absorption coefficients, 1 nm = 1e-7 cm), temperature **K**,
irradiance **suns** (1 sun = 100 mW/cm²), power density **mW/cm²**, current
density **mA/cm²**, resistance-area **Ω·cm²** (thermal **K·cm²/mW**), energy
**eV** internally with `EV_J = 1.602176634e-19` and `K_B_EV_K = 8.617333262e-5`,
σ_SB = 5.670374419e-8 W/m²/K⁴ (= 5.670374419e-9 mW/cm²/K⁴, cross-checked against
2π⁵k⁴/15h³c² to 3.3e-11 and against the measured radiative loss).

**BUG FOUND AND FIXED — the concentration PCE unit error.** `pce_pct` was
computed as `P_out / 100 mW cm⁻²` at *every* irradiance, i.e. it was a power
density mislabelled as a percentage, scaling linearly with concentration:

| suns | `pce_pct` before | `Jsc` (mA/cm²) | correct PCE after fix |
| --- | --- | --- | --- |
| 0.1 | 1.4156 | 1.573 | 14.156 % |
| 1.0 | 20.2417 | 15.727 | 20.242 % (bit-identical) |
| 2.0 | 41.4665 | 31.453 | 20.733 % |
| 5.0 | **102.9093** | 78.633 | 20.582 % |

The correct definition is `PCE = P_out / (suns · 100 mW/cm²) · 100`, which is
`P_out / suns`. **At exactly one sun the correction is the identity**, so no
pinned V1.8/V1.9-B number changes; verified bit-for-bit
(`20.24165864` before and after). **Blast radius checked and reported:** no
V1.9-B artifact sampled `irradiance_suns` (0 occurrences in
`v19_oat_sensitivity.json`, `v19_mechanism_campaign.json`,
`v19_calibration.json`), so the historical results are unaffected; the bug only
became reachable when the new thermal sweep varied irradiance. Downstream
consequences also fixed: the guard's current limits and radiative ceiling are now
concentration-aware (`Jsc` at 5 suns legitimately exceeds the per-sun absurdity
bound), and the thermal extractor's `P_elec = PCE·suns·100/100` now yields the
correct mW/cm².

**Regression tests added:** `test_pce_is_a_percentage_at_every_concentration`,
`test_currents_scale_with_concentration_and_limits_allow_it`,
`test_radiative_ceiling_is_normalised_by_concentration`.

## 21. Vectorisation and performance (items 5, 20, 27)

**What changed.** (a) `subcell_table`: one vectorised Newton solve for the whole
V-grid instead of a per-point bisection; (b) `solve_tandem_fast`: the series
constraint is solved on a shared current grid with table inversion
(`np.interp`), and the luminescent-coupling fixed point is vectorised;
(c) optics are `lru_cache`d and shared across solves that only change electrical
or thermal parameters; (d) `ElectricalPowerExtractor` memoises the thermal loop's
trial evaluations; (e) the thermal Newton step uses the analytic loss derivative
(one electrical solve per iteration); (f) `apmt/device/batch.py` provides an
N→N batch API with warm-started thermal solves and optional worker processes.

**Measured (see `data/v19_engine_campaign.json` §benchmark; 2 vCPU sandbox):**

| Quantity | Reference oracle | Fast solver | Factor |
| --- | --- | --- | --- |
| single self-heated solve | 32.72 s | 0.04558 s | **718×** |
| batch of 3 (energy balance) | 603.3 s | 0.5001 s | **1206×** |
| peak Python allocation | 1.40 MB | 0.57 MB | 0.41× |
| batch API (24-point LHS, L4) | — | 1.16 s = 20.8 solves/s | warm-started 23/24 |

**Against the item-5/27 target.** The baseline that defines the 10× target is the
measured V1.9-A campaign cost of **1.08 s per solve** (recorded in §12). The final
fast solver does one self-heated solve in **45.6 ms → 23.7×** versus that
baseline (718× versus the preserved oracle, which is a different, slower
reference), and the 24-point batch API sustains **20.8 solves/s** (≥ 260× the
baseline throughput). Both clear the target. The numbers are machine-specific; the
reproducible quantity is the **ratio** and the agreement (§22). No blind
parallelism is used: the batch API runs serially by default and only offers
`workers>1` for campaigns.

**Honest limit:** the speedup is not free of physics — the fast path differs from
the oracle only by discretisation (§22), but it depends on the tabulated
monotone subcell J(V) inversion, which is exactly the part the oracle does not
assume. `tests/test_v19_engine.py::test_fast_solver_is_actually_vectorised`
asserts the fast path does not fall back to scalar bisection (< 20 scalar
inversions per solve, measured 4).

## 22. Reference oracle and the agreement contract (item 6)

The V1.9-B scalar solver is preserved unchanged as `solve_tandem_reference` and
is the regression oracle. Both solvers extract their metrics through the *same*
function (`curve_metrics_by_current`), so a comparison isolates numerics rather
than two definitions of the operating point.

| Ensemble | max ΔPCE (pp) | ΔJsc (mA/cm²) | ΔVoc (V) | ΔFF | Tolerance |
| --- | --- | --- | --- | --- | --- |
| nominal point | 8.9e-06 | 7.6e-11 | 5.9e-07 | 2.3e-07 | PCE 1e-3, Jsc 1e-3, Voc 1e-4, FF 1e-4 |
| 3-point LHS (benchmark) | 8.88e-06 | 7.64e-11 | 5.86e-07 | 2.26e-07 | same |
| **12-point LHS (pinned `oracle_agreement` section)** | **8.61e-06** | **9.85e-11** | **8.16e-07** | **2.67e-07** | same; 12/12 within tolerance |
| edge cases (Rs, Rsh, coupling, bandgaps, trapping, rear mirror) | < 1e-4 (×5 tolerance) | — | — | — | parametrised in `tests/test_v19_engine.py` |

**Jsc definition (documented change).** Jsc is reported as the physical
current-source limit `min(Jsc_top, Jsc_bottom)`. The old value was read off the
J(V) curve at V = 0, which is ill-conditioned on a series tandem: the new
diagnostic `jsc_bias_sensitivity_ma_cm2_per_v = 393.2 mA cm⁻² V⁻¹` means a
20 mV bias error would move that intersection by ≈7.9 mA/cm². The curve endpoint
is still reported (`jsc_curve_grid_endpoint_ma_cm2`) so the change is auditable;
PCE did not move (+0.0005 pp), FF moved 0.8567 → 0.8507 because it is now taken
from the same common-current representation.

**Discretisation floor (honest number).** Solver-vs-solver agreement (1e-11
mA/cm²) is *three orders below* the grid discretisation floor: at the production
5 nm wavelength grid vs 2.5 nm, ΔJsc_top = 2.41e-02 mA/cm² (0.153 %) and
ΔJsc_bottom = −2.27e-02 mA/cm². Any comparison of *models* (levels, mechanisms,
couplings) at the 1e-3 mA/cm² level must therefore be read as "below the
discretisation floor", not as a physical difference.

## 23. Thermal rebuild and the 454 K investigation (item 7)

**What changed.** The V1.9-B closure ("all incident power becomes heat", no
radiative path) is retained as `simple_temperature` for lineage, and a solved
energy balance is now the default:

    Q(Tj) = f_heat · P_absorbed − P_elec(Tj)          (heat load)
    L(Tj) = (Tj − T_amb)/R_th,eff + ε·σ·(Tj⁴ − T_amb⁴)  (loss)
    equilibrium: L(Tj) = Q(Tj),  stable ⇔ dL/dT > dQ/dT

Units: mW/cm², K, σ in mW/cm²/K⁴, `f_heat = absorption_heat_fraction` (default
1.0, conservative: photon escape above the gap is *not* credited as cooling).
Solved by a safeguarded Newton with an analytic loss derivative and a
bisection bracket (tolerance 1e-4 mW/cm²); initial guess from the simple closure.

**Default operating point (1 sun, T_amb 298.15 K):**

| Quantity | Value |
| --- | --- |
| absorbed optical power | 68.4961 mW/cm² |
| extracted power (PCE 19.2633 %) | 19.2633 mW/cm² |
| heat load Q | 49.2328 mW/cm² |
| conduction | 41.9759 mW/cm² (85.3 %) |
| radiative | 7.2569 mW/cm² (14.7 %) |
| junction temperature | **310.7428 K** (ΔT 12.5928 K) |
| balance residual | 6.0e-05 mW/cm² (tolerance 1e-4; invariant bound 1e-3) |
| stability margin dL/dT − dQ/dT | 3.76 mW cm⁻² K⁻¹ (dQ/dT = 0.182) |
| PCE (self-heated, energy balance) | 19.2633 % |

For comparison, the legacy closure at the same parameters gives ΔT = 30.0 K and
PCE 17.9082 % — i.e. the V1.9-B self-heated number was **pessimistic by ≈1.36 pp
of efficiency** because two thirds of the extracted power was being conducted as
if it were heat and no radiative cooling existed.

**Stability and uniqueness** (`data/v19_thermal_investigation.json`): over the
irradiance × R_th grid (0.1/1/5 suns × 0.05/0.3/2.0 K cm²/mW), dQ/dT =
0.017–0.863 mW cm⁻² K⁻¹, dL/dT = 1.07–20.6 mW cm⁻² K⁻¹, margin +1.05 to +20.5
mW cm⁻² K⁻¹, residuals monotone in every case. The heat load *rises* with
temperature (P_elec falls), and the loss term rises faster — that is what makes
the equilibrium unique.

**The 454 K corner — conclusion with arithmetic.** The V1.9-B finding is
reproduced exactly and explained:

| R_th (K cm²/mW) | legacy closure Tj | legacy PCE | energy balance Tj | energy balance PCE | radiative share |
| --- | --- | --- | --- | --- | --- |
| 0.30 (default) | 328.15 K | 17.9085 % | 310.74 K | 19.2633 % | 14.7 % |
| 1.00 | 398.15 K | 9.7543 % | 329.21 K | 17.8261 % | 38.7 % |
| 1.556 | **453.75 K** | 1.9685 % | 337.60 K | 17.1699 % | 50.6 % |
| 2.00 (registered max) | 498.15 K (no subcell Voc at 498.1 K) | — | **342.21 K** | 16.8084 % | 57.4 % |

Verdict: the 454 K corner was **reachable under the legacy closure, was not a
numerical artefact, and is no longer reachable** — the missing pathway was
radiative cooling, which carries 51 % of the heat load at the same R_th and 57 %
at the registered maximum. At 498 K an emissive front surface radiates
≈339 mW/cm² against a 100 mW/cm² heat load, so the temperature simply cannot
exist in a closed balance. The registered range is **kept** (per the standing
rule that a registered assumption is not silently narrowed); the upper bound is
now bounded by physics rather than by a missing term, and it is flagged
EXPLORATORY in the artifact.

**Validity envelope (new, and it matters).** The electrical parameterisation
(Varshni bandgaps, n_i, SRH slab, calibrated J0) is registered for
`temperature_k ∈ [220, 400] K`. The thermal solve must evaluate trial
temperatures outside that window to bracket the root; it substitutes the
conservative `P_elec = 0` there (auditable: `electrical_envelope` in the thermal
record) and **refuses to report** a converged junction temperature outside the
window (`ModelValidityError` → INVALID solve). Consequences: 3 of the 24
sweep corners (5 suns at the higher R_th values) are INVALID, and the legacy
2.0 K cm²/mW point at 498 K — which V1.9-B's report-space claim relied on — could
not be reported at all by a guarded model today. This is the honest outcome: a
number outside the model's validity is worse than no number.

**Heat-ledger transparency.** The model does not separate thermalisation,
non-radiative recombination and luminescent escape: all of the absorbed-minus-
extracted power is treated as heat, so the junction temperature is an **upper
bound** for a given R_th. Removing any passive cooling path would raise the
temperature and was not done; the assumption is conservative in the safe
direction.

## 24. Bottom→top coupling (item 8)

**Definition and units.** `luminescent_coupling_bottom_to_top` (β_bt, 0–0.5) is
the fraction of the bottom cell's *radiative* recombination current that is
re-absorbed by the top cell. The physical availability of the channel is
`f_up = ∫_{E ≥ Eg_top} φ_bb(E; T) dE`, computed by `emission_fraction_above_gap`
(Boltzmann/Planck integral, dimensionless), and the current transferred is
`β_bt · f_up · J0_rad,bottom · expm1(V_bottom / kT)`, exactly zero at short
circuit. Sign convention: positive means current *added to the top cell*.
Limiting behaviour: f_up → 0 as Eg_top − Eg_bottom grows; the term is zero for
β_bt = 0 and vanishes at V = 0.

**Measured availability:** f_up = 3.9e-10 at the nominal gaps (ΔEg = 0.603 eV),
which is the expected `exp(−ΔEg/kT)` suppression.

**Impact (defaults, L4):** at the registered maximum β_bt = 0.5 the response is
**+4.7e-08 pp** even at the most favourable bandgap corner of the registered box
(Eg_top = 1.40 eV, f_up = 1.0e-5) — eight orders below the discretisation floor.

**Ablation (item 17, 5-point LHS × 2⁴ configurations):**

| Mechanism switched OFF | mean ΔPCE (pp) | range (pp) | sign-consistent |
| --- | --- | --- | --- |
| thermal feedback | **−2.1997** | −3.2722 … −0.8316 | YES |
| Rs/Rsh network | **−0.8051** | −0.9992 … −0.5646 | YES |
| SRH/surface channel | −0.0025 | −0.0075 … −0.0001 | YES |
| luminescent coupling (both directions) | **0.0000** | 0.0000 … 0.0000 | n/a (exactly zero) |

Interactions (second-order factorial residuals, no causal claim):
thermal × resistance **+0.1153 pp mean (max 0.1968)** — a genuine second-order
term: self-heating lowers the extracted power, which changes the resistive loss.
All other pairs ≤ 7.5e-03 pp.

**Conclusion (a valid answer is "it does not exist here").** The channel is
implemented, differential-tested against the oracle, bounded, sign-correct and
provably *live code* (a forced availability of 0.1 changes Voc by > 1e-6 V in
`test_bottom_to_top_coupling_is_live_not_dead_code`). It is **physically absent**
at these bandgaps: a 1.12 eV silicon cell cannot emit above a 1.68 eV perovskite
gap with any appreciable probability, and adding current to a *non-limiting*
subcell cannot help a TOP-LIMITED tandem anyway. Both mechanisms are therefore
reported as structurally present, physically inert, and quantified — not as
"no effect".

## 25. Multi-fidelity Levels 0–5 (items 9–10)

Each level is an explicit, documented **fidelity change (a model term removed or
restored)** — never a parameter change: `apply_level` returns the parameter set
untouched and the switches are recorded in `detail["level_switches"]`.

| Level | Optics | SRH | Rs/Rsh | Thermal | Coupling | Grid | PCE % | Jsc | Voc | FF | Tj (K) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L0 | Beer-Lambert | — | — | fixed | — | 2001/600 | 19.881 | 14.816 | 1.5114 | 0.8878 | 298.15 |
| L1 | TMM | — | — | fixed | — | 2001/600 | 21.208 | 15.727 | 1.5152 | 0.8900 | 298.15 |
| L2 | TMM | ✓ | — | fixed | — | 4001/1200 | 21.208 | 15.727 | 1.5153 | 0.8900 | 298.15 |
| L3 | TMM | ✓ | — | balance | — | 4001/1200 | 20.190 | 15.727 | 1.4550 | 0.8824 | 310.51 |
| L4 | TMM | ✓ | ✓ | balance | ✓ | 4001/1200 | 19.263 | 15.727 | 1.4516 | 0.8438 | 310.74 |
| L5 | TMM | ✓ | ✓ | balance | ✓ | 8001/2400 | 19.263 | 15.727 | 1.4516 | 0.8438 | 310.74 |

**Divergence classification** (12-point LHS ensemble in Eg / thickness / ARC /
trapping / Rsh / R_th, reference L5):

| Level | mean \|ΔPCE\| (pp) | max \|ΔPCE\| (pp) | worst class | predictive? |
| --- | --- | --- | --- | --- |
| L0 | 2.127 | 4.257 | MODEL-FORM-CRITICAL | **NO** |
| L1 | 2.360 | 4.283 | MODEL-FORM-CRITICAL | **NO** |
| L2 | 2.360 | 4.283 | MODEL-FORM-CRITICAL | **NO** |
| L3 | 0.297 | 0.429 | MODERATE-DIVERGENCE | NO |
| L4 | 1.6e-05 | 7.5e-05 | LOW-DIVERGENCE | YES |
| L5 | reference | — | — | YES |

**Reading for V1.9-D.** Only **L4/L5** may be trusted for optimisation: L0–L2
diverge by up to 4.3 pp (temperature-free electrical models *overestimate* this
device by ≈2 pp), and L3 by 0.43 pp. Any campaign that mixes levels would be
optimising model form, not physics. Runtime per level makes the trade-off
explicit: L0–L2 ≈ 4–6 ms, L3 ≈ 40 ms, L4 ≈ 48 ms, L5 ≈ 54 ms per point
(single-thread, warm cache).

## 26. Inert-parameter screening 2.0 (item 11)

Every one of the 41 screenable registered parameters is perturbed in both
directions (or against its registered bounds when the default is zero) at *every*
level; a PCE response below 1e-6 pp is INERT. Inertness is classified three ways:
explained by a fidelity switch or by the active model form, physically suppressed
(with a falsification probe), or a **defect**.

| Level | active | inert | switch/model-form explained | physically suppressed | **unexpected (defect)** |
| --- | --- | --- | --- | --- | --- |
| L0 | 14 | 27 | 27 | 0 | **0** |
| L1 | 21 | 20 | 20 | 0 | **0** |
| L2 | 25 | 16 | 16 | 0 | **0** |
| L3 | 32 | 9 | 8 | 1 | **0** |
| L4 | 35 | 6 | 5 | 1 | **0** |
| L5 | 35 | 6 | 5 | 1 | **0** |

**Two defects found and fixed** (found by the screener in the first run — this is
the point of the tool):

1. `absorption_heat_fraction` was **structurally dead** after the thermal rebuild:
   the energy balance ignored it. Fixed by wiring it into the heat load
   (f_heat·P_absorbed). Verified response: f_heat 0.5 / 0.8 / 1.0 →
   Tj 301.83 / 307.19 / 310.74 K, PCE 19.956 / 19.539 / 19.263 %.
2. `luminescent_coupling_bottom_to_top` is inert at the nominal point. It is not
   dead code; it is **physically suppressed**, and the screener now proves it with
   a falsification probe: at the best corner of the registered box (Eg_top =
   1.40 eV, β = 0.5) the on/off difference is 4.7e-08 pp with an availability of
   1.0e-05, while an explicit code-liveness test with a forced availability
   changes Voc. A declared-active-but-inert parameter with an *unexplained*
   cause remains a defect and is reported as one.

Honest screen limitation (carried from V1.9-B and re-confirmed): a ±20 % local
perturbation cannot see weak-but-real effects that only appear far from the
default point, nor non-monotone optima. The screener therefore reports the probe
point it used, and near-zero responses are never written as "no effect".

## 27. Limit tests, convergence tests, ablation (items 12, 13, 17)

**Physical limit tests** (1 sun unless stated): tiny shunt (Rsh 50 Ω cm²) →
PCE 3.090 % / FF 0.250; strong parasitic absorption (k_TCO ×20) → 18.638 %;
weak top absorption (α at the registered lower bound) → 6.787 % / Jsc 5.759;
thin top cell (150 nm) → 9.532 % / Jsc 7.887; no thermal resistance (0.05) →
20.059 % / Tj 300.51 K (approaches the fixed-T value 20.242 %); extreme
registered R_th (2.0) → 16.808 % / Tj 342.21 K; ideal rear trapping (30×) →
19.429 %; tuned ARC + rear mirror (R = 0.98) → Tj 310.59 K with Jsc unchanged
(top-limited); SRH disabled (the ideal single-diode limit, L1) → Voc 1.5152 V vs
1.4550 V with SRH (L3). Every direction matches the physical expectation, and no
limit case is rejected by the guard.

**Convergence tests:** the subcell table / curve grid (PCE stable to 1.1e-05 pp
from 4001 table points and 1200 curve points — the production setting on the
finest 16001/4800 reference); the wavelength grid (closure 2.2e-16 at every
resolution ≥ 5 nm; ΔJsc_top = 2.4e-02 mA/cm² between 5 nm and 2.5 nm — the
documented discretisation floor, §22); thermal tolerance (residual 6e-05 vs 1e-04
specified); thermal iteration count (≤ 11, ≤ 43 electrical evaluations with
memoisation; 6–7 typical).

**Ablation** is in §24 (it shares the mechanism table). Its structure answers
item 28 for every mechanism with WHAT CHANGED / WHY / PHYSICS / PROVING TEST /
LIMIT / WHAT RESULT CHANGED / HOW MUCH / ROBUST / MODEL-DEPENDENT — see the
per-mechanism blocks in §24 and §23.

## 28. Batch API, surrogate readiness, reproducibility (items 18, 19, 21, 22, 23)

**Batch API** (`apmt/device/batch.py`): `batch_evaluate(matrix, names, level=…)`
→ N guarded `SolveRecord`s (order-preserving, optionally multi-process),
`BatchSummary` (wall clock, solves/s, failure counts by invariant name, warm-start
count), `dataset()` (VALID rows only, with an explicit rejection ledger), and
`lhs_batch()` convenience. Measured throughput: L0 181.5, L1 158.0, L2 231.1,
L3 23.6, L4 22.2, L5 18.5 guarded solves/s on 2 vCPU. Invalid solves are
returned and flagged, never dropped silently; `dataset()` refuses to train on
them and records why.

**Reproducibility metadata:** every campaign artifact embeds python/numpy,
platform, git commit + dirty flag, a fingerprint of the 43 registry defaults
(`efccfb25…`), the registry size, the topology and the unit table. Pinned
artifacts stay byte-deterministic (timings printed, never written), verified by
double-run sha256 equality (`data/v19_thermal_investigation.json`
`043a9bea…` twice). The engine-campaign artifact additionally carries a
**physics digest** (one shared rule in `apmt/repro/digest.py`: sha256 over the
artifact with the benchmark and environment blocks removed and every
timing-valued key stripped recursively — so it is stable across machines and
across reruns) so that its physics is verifiable even though wall-clock values
are machine-specific. Timing-independence is itself tested: the suite injects a
fake `wall_clock_s` and asserts the digest does not move, then perturbs a PCE and
asserts it does (`tests/test_v19_batch_surrogate.py`).

**Pinned vs non-byte-deterministic artifacts (explicit rule).** Only artifacts
that reproduce byte-for-byte are sha256-pinned in
`manifests/v1.9_artifact_pins.json`: the seven V1.9-B artifacts plus
`data/v19_thermal_investigation.json`. The engine-campaign artifact is *not*
byte-reproducible (it contains wall clocks and the git commit of the run) and is
therefore pinned by its **physics digest**
`278636bce59415d6e17f905f4d50c8801a08f02733ac627f583c0248201bc108` in the
`digests` block of the same manifest; `tools/ci_checks.py` recomputes the digest
from the committed file on every CI run, and `tests/test_v19_batch_surrogate.py`
re-derives it independently. Regenerating the artifact at a different commit
therefore changes bytes but not the digest, which is the quantity that has to
stay invariant. The `oracle_agreement` section (12-point LHS, reference vs fast)
is deterministic and is inside the digest.

**Artifact discipline:** four compact JSON artifacts for the whole cycle
(≤ 340 kB total), no per-point files, no new directories, no compressed dumps of
per-sample data. Tests are non-mutating: computation, serialization and CLI are
separate functions, and every generator writes only its own single artifact on
explicit `--write`.

## 29. Calibration hardening (item 14) — status

Carried from V1.9-B and unchanged in V1.9-C, with the new guard now enforced on
its residuals: fitting uses only the documented EQE targets (never forbidden
measurements); scenario values are never fitted or presented as measurements;
residuals and weighting are explicit (`weight_bottom`), the Jacobian SVD,
condition number (1300.8), correlation matrix, boundary hits (2) and profile
likelihood are reported; DATA-FIT QUALITY (RMSE 4.824 / 5.161 pp) is reported
**separately** from PARAMETER IDENTIFIABILITY (κ, boundary hits, profile widths);
fitted parameters are never described as measured material properties. Not yet
done and explicitly listed as remaining work: multi-start/multi-seed diagnostics
(V1.9-E) and the covariance/Fisher decomposition.

**New synthetic known-truth check for the thermal block** (software verification
only, no measurement): synthetic (irradiance, P_elec, Tj) data generated from a
known truth (R_th = 0.45 K cm²/mW, ε = 0.85) are recovered to 1.3e-06 (R_th) and
8.3e-06 (ε) without noise, and to 8.5e-04 / 3.2e-03 with 0.2 K noise; the Jacobian
condition number is 108.6 across the irradiance range, while a **single
irradiance** leaves R_th and ε untestable (the conduction term scales with the
heat load, the radiative term with T⁴ — a physically meaningful identifiability
statement that the report states rather than hides).

## 30. V1.9-C negative results, blockers and acceptance

**Negative results (explicit).**

1. Bottom→top luminescent coupling is physically absent at these bandgaps
   (≤ 4.7e-08 pp at the best registered corner; f_up = 3.9e-10 nominal).
2. Luminescent coupling in *either* direction changes nothing in a top-limited
   tandem (§24).
3. The reduced levels L0–L2 are **not predictive** of the full model (up to
   4.3 pp) and must not be used for optimisation claims.
4. The 5-sun × high-R_th corners of the registered parameter box are **outside
   the model's validity** and are INVALID — the box is wider than the physics.
5. The V1.9-B self-heated efficiency (17.9082 %) is **superseded** for the
   energy-balance closure (19.2633 %); the legacy value remains reproducible and
   is kept for lineage, not as a current model result.
6. The concentration PCE bug (§20) shows that a unit error can survive a large
   test suite when only one operating point is exercised — the regression tests
   added here are the direct remedy.

**Blockers (unchanged, and not engineering-fixable):** no full-stack R/T/A, no
external Rs/Rsh, no serial-level device linkage, manuscript PDF absent (35/37
historical claims unverifiable). The gate stays CLOSED; APMT remains
BLOCKED_BY_BASELINE_VALIDATION. Nothing in V1.9-C changes the gate definition or
any threshold.

**Acceptance checklist (item 26):**

| Criterion | Status | Evidence |
| --- | --- | --- |
| deep engine audit recorded | DONE | §18 |
| invariant engine first-class | DONE | §19, 23 checks in one registry |
| HARD failures block (INVALID) | DONE | §19 + guard tests |
| units audited, conversions explicit | DONE | §20 (+ a bug found and fixed) |
| reference solver preserved | DONE | §22 `solve_tandem_reference` |
| optimised solver ≥10× | DONE | §21: 718× single, 1206× batch (final code) |
| agreement quantified | DONE | §22 (1e-11 … 1e-05) |
| thermal audited, balance enforced, 454 K investigated | DONE | §23 (verdict: missing radiative path) |
| bottom→top coupling implemented or shown unjustified | DONE | §24 (implemented; physically absent, quantified) |
| Levels 0–5 | DONE | §25 |
| cross-level divergence analysis | DONE | §25 (LOW/MODERATE/MODEL-FORM-CRITICAL) |
| inert screening expanded to all levels | DONE | §26 (2 defects found and fixed) |
| physical-limit tests | DONE | §27 |
| convergence tests | DONE | §27 (+ discretisation floor) |
| calibration hardened | PARTIAL (carried V1.9-B + guard; multi-start deferred to V1.9-E) | §29 |
| synthetic tests expanded | DONE (thermal known-truth recovery) | §29 |
| ablation expanded | DONE | §24 |
| batch API / V1.9-D interface | DONE | §28 |
| reproducibility metadata + deterministic artifacts | DONE | §28 |
| test side-effect audit | DONE | §28 (non-mutating suite, verified by `ci_checks` git-clean) |
| full regression suite passes | DONE | 142 passed / 1 skip, 81 s |
| item 28 mechanism ledger | DONE | §23, §24, §26 |

## 31. V1.9-C commit map and verification

V1.9-C commits (all on `arena/01a102e7-solar`, all pushed):

| Commit | Contents |
| --- | --- |
| `V1.9-C2` = `53dfa41` | invariant layer + guard + tests (`apmt/validation/{invariants,guard}.py`, `tests/test_v19_invariants.py`) |
| `V1.9-C3` = `53f555c` | vectorised solver + preserved reference oracle + batch API (`apmt/device/{tandem,subcell,batch}.py`, `apmt/core/constants.py`, `tests/test_v19_engine.py`) |
| `V1.9-C4` = `659691c` | thermal energy-balance rebuild + validity envelope + 454 K investigation (`apmt/device/thermal.py`, `tests/test_v19_thermal.py`, `tools/v19_thermal_investigation.py`, `data/v19_thermal_investigation.json`) |
| `V1.9-C5` = `de4bd26` | bottom->top coupling, rear-reflection optics, Levels 0-5, concentration unit fix (`apmt/multifidelity/levels.py`, `apmt/optics/*`, `apmt/materials/silicon.py`, `apmt/params/registry.py`, tests) |
| `V1.9-C6` = `a5aee30` | engine campaign + physics digest (`tools/v19_engine_campaign.py`, `apmt/repro/digest.py`, `data/v19_engine_campaign.json`, `tests/test_v19_batch_surrogate.py`) |
| `V1.9-C7` = `84dab7b` | pins, CI digest verification, README twin row, master report PART V1.9-C |
| `V1.9-C8` = `813d8b0` | report commit-hash record + regenerated `reports/.report_sha256` |
| `V1.9-C9` = `(this commit)` | report correction: L4 divergence row set to the committed artifact value (1.6e-05 / 7.5e-05 pp), hash regenerated |

*(Full hashes are listed in the table; `V1.9-C8` is the self-referencing record
commit, so its own hash can only appear in `git log` and in the cycle's final
chat block. The V1.9-A/V1.9-B/V1.9-C1 commits below `V1.9-C2` are untouched.)*

**Verification performed at the end of the cycle:**

| Check | Result |
| --- | --- |
| full test suite | **142 passed, 1 skipped** in 81 s (the skip is the explicit "manuscript PDF absent" M2 re-render check) |
| `tools/ci_checks.py` | **6/6 PASS** (8 artifact sha256 pins + 1 physics digest, determinism re-run, provenance audit, gate evaluator, report consistency, git-clean) |
| report sha256 | `11f317e2…` as committed in `V1.9-C7`; the sha256 of the file as committed in `V1.9-C8` is recorded in `reports/.report_sha256` |
| working tree | clean after `V1.9-C8` (`git status --porcelain` empty) |
| remote | verified with `git ls-remote origin` against the local commit hash |
| test side effects | the suite does not modify `data/` or `manifests/` (the CI git-clean check proves it on every run) |

**V1.9-D readiness.** Ready, with the interfaces in place:
`batch_evaluate`/`dataset` (N→N, guarded, surrogate-ready), level selection with
divergence classes, and a documented agreement/discretisation floor so that no
search can mistake grid noise for physics. Required before trust: use **L4/L5
only**, never optimise a level below L4, treat any objective value from an
INVALID solve as absent (not as a penalty), and carry the campaign id, seed,
level and parameter point with every candidate.
