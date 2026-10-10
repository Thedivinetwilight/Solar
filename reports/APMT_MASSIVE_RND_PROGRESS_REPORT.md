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

# PART V1.9-D — GLOBAL SENSITIVITY FOUNDATION

**Cycle:** ten-update program, update 1 of 10 (V1.9-D … V1.9-M).
**Status:** COMPLETE. Artifact `data/v19_sensitivity.json` (398 kB, physics digest
`93f40c91cc5db29e8239dc8eb59340494afc48bf873311cd90a8f5ffd0b72ecd`), eight
independently executable and mergeable sections, 26 new tests, full suite
**168 passed / 1 skipped**.

## 32. V1.9-D — mission and implementation

**MISSION.** Turn the V1.9-C engine (fast, guarded, multi-fidelity) into a
sensitivity instrument: a rigorous variance-based global sensitivity system that
identifies which parameters actually control the device, where the model's own
validity ends, which conclusions are method-dependent, and which are not
reportable at the available sample size.

**IMPLEMENTATION.** Four new modules and one campaign driver:

| Component | File | What it does |
| --- | --- | --- |
| Saltelli design + estimators | `apmt/sensitivity/sobol.py` | A/B/AB_i/BA_i design, Saltelli first/total/second-order estimators, bootstrap CIs, INVALID/degenerate handling, Ishigami reference functions |
| Regime campaign, envelopes, cross-checks | `apmt/sensitivity/campaign.py` | per-axis validity envelopes, shared verified box, regime analysis, LHS/Spearman cross-check, interaction study, response shapes, prior diagnostic |
| Calibration + interaction study | same | Ishigami error calibration at the campaign's exact design sizes; calibrated pairwise detection floor |
| Campaign driver | `tools/v19_sensitivity_campaign.py` | eight sections (`box`, `regimes`, `crosscheck`, `l5`, `estimator`, `interactions`, `shapes`, `prior`), each flushed independently, merge-on-write, physics digest |
| Engine hardening | `apmt/validation/guard.py`, `apmt/device/batch.py` | a failed solve is now INVALID **in the verdict** as well as in the flag (§34) |

**Definition of global vs local used throughout.** GLOBAL = variance-based
(Sobol): how much of the output variance each parameter explains, including
everything that varies with it. LOCAL = one-at-a-time at an anchor. They are
different questions and, for this device, they give nearly opposite rankings (§37).

**Reproducibility.** Every section records seed, box, level, bounds, design
fingerprint, rejection ledger and environment (python/numpy/commit/registry
fingerprint); the artifact carries a physics digest that excludes all wall-clock
keys (stability across reruns and machines is pinned by tests in
`tests/test_v19_batch_surrogate.py` and `tests/test_v19_sensitivity.py`).

## 33. Estimator verification — Ishigami known-answer test and its measured limits

A variance decomposition that is not verified against a known answer is not a
measurement. The estimators are tested against the Ishigami function
(Var = 13.8445, S1 = 0.3139/0.4424/0.0, S_T = 0.5576/0.4424/0.2437, S13 = 0.2437):

| Quantity | Analytic | Measured (N = 4096, bootstrap) |
| --- | --- | --- |
| S_T(x1, x2, x3) | 0.5576 / 0.4424 / 0.2437 | 0.537 / 0.450 / 0.245 |
| S1(x1, x3) | 0.3139 / 0.0 | 0.334 / -0.007 |
| S13 | 0.2437 | 0.261 |
| Var | 13.8445 | 13.39 (5 % MC tolerance, documented) |

**The important number is the error at the campaign's own sample size.**
Measured on Ishigami at N = 96: worst-case error **0.27** on a total-order index;
at the interaction study's design (d = 4, N = 768) the pairwise noise floor is
**0.128** with a 0.030 error on the one known pair. These are not caveats bolted on
afterwards — they are computed by `estimator_validation()` and stored in the
artifact, and the campaign's headline statements are restricted to what clears them.

**Consequence adopted by this update:** a parameter is called *established* only if
its total-order index clears the calibrated worst-case error. At N = 96 that admits
**two parameters** in the nominal regime and **one** under concentration.
Everything else is reported as "small, or indistinguishable from zero at this
sample size" — never as "no effect".

## 34. The validated design space — what the model refuses to describe

Sobol indices require a COMPLETE design; an invalid point is not a missing value to
be imputed. The campaign therefore determines, and then verifies, the box it is
allowed to sample.

**Per-axis validity envelopes** (walk each axis from its default to its bound, all
others at defaults, at L4):

| Regime | Restricted axes | Reachable interval | Registered |
| --- | --- | --- | --- |
| 1 sun, 298.15 K ambient | none | all axes full | — |
| 1 sun, 338.15 K ambient | none | all axes full | — |
| **3 suns, 298.15 K** | **`thermal_resistance_k_cm2_w`** | **<= 1.15 K cm2/mW** | <= 2.0 |

**Joint constraint.** A box can be valid along every axis and still contain an
invalid corner: the single-axis envelope for the thermal resistance (1.15) is not
sufficient. With the other thirteen axes varying, the verified box is
**R_th in [0.159, 0.778] K cm2/mW** (11 % of the registered width on that axis,
0.951 of the registered box overall). Every regime is then re-probed in the shared
box: 100 % valid.

**Full registered box validity** (probe of 64 points per regime):

| Regime | Full-box validity | Failure mode |
| --- | --- | --- |
| 1 sun, 298.15 K | **1.00** (64/64) | — |
| 1 sun, 338.15 K | **1.00** (64/64) | — |
| 3 suns, 298.15 K | **0.50** (32/64) | 31 x `ModelValidityError`: junction outside the 220-400 K electrical envelope |

**Regimes the registered default device cannot reach** (recorded, not dropped):
5.0 suns / 338.15 K ambient (junction 415.3 K) and 10.0 suns / 298.15 K (junction
451.9 K). Both are inside the registered parameter ranges and outside the model's
validity envelope, so the model makes no claim there. This is the V1.9-C 454 K
finding reappearing as an operating-condition boundary rather than a
parameter-range problem.

**Engine hardening found by this work.** Before V1.9-D an out-of-envelope solve
produced `valid = False` but `verdict.status = PASS` (the invariant bundle was
empty), so a consumer reading the verdict would have accepted it. The guard now
attaches a HARD `numerical.solve_completed` failure on both dispatch paths, and
`test_invalid_solve_is_invalid_in_the_verdict_too` pins it.

## 35. Global sensitivity results (L4, three regimes)

Design: 14 architecture axes, N = 96 base samples x 2 independent replicates per
regime (mean +/- replicate spread), L4 physics, 17,280 evaluations for this part.
Only L4 carries scientific statements; §37 gives the L2 comparison.

**Nominal (1 sun, 298.15 K) — total-order S_T:**

| Rank | Parameter | S_T | S1 | Interaction budget (S_T - S1) |
| --- | --- | --- | --- | --- |
| 1 | `perovskite_eg_ev` | **0.590 +/- 0.052** | 0.409 | +0.180 |
| 2 | `perovskite_thickness_nm` | **0.532 +/- 0.058** | 0.269 | +0.263 |
| 3 | `rs_ohm_cm2` | 0.140 +/- 0.034 | -0.148 | +0.288 |
| 4 | `arc_thickness_nm` | 0.039 +/- 0.002 | 0.145 | -0.106 |
| 5 | `perovskite_urbach_mev` | 0.022 +/- 0.000 | -0.032 | +0.054 |
| 6 | `parasitic_layer_thickness_nm` | 0.018 +/- 0.004 | 0.031 | -0.013 |
| 7 | `thermal_resistance_k_cm2_w` | 0.017 +/- 0.002 | -0.014 | +0.031 |
| 8 | `silicon_light_trapping` | 0.013 +/- 0.001 | -0.010 | +0.023 |

**Concentration changes which parameter dominates (3 suns, 298.15 K):**

| Rank | Parameter | S_T | S1 | Interaction budget |
| --- | --- | --- | --- | --- |
| 1 | `rs_ohm_cm2` | **0.591 +/- 0.153** | 0.193 | +0.399 |
| 2 | `perovskite_eg_ev` | 0.251 +/- 0.019 | 0.241 | +0.010 |
| 3 | `thermal_resistance_k_cm2_w` | 0.184 +/- 0.018 | 0.135 | +0.049 |
| 4 | `perovskite_thickness_nm` | 0.114 +/- 0.019 | 0.026 | +0.088 |

The series resistance moves from 3rd (0.140) to 1st (0.591) and the bandgap falls
from 1st (0.590) to 2nd (0.251): the dominant physics changes with operating
condition. That is the I^2 R scaling of the resistive loss with the photocurrent,
and the dedicated interaction study sees the same mechanism directly (§36).

**Hot ambient (1 sun, 338.15 K):** `perovskite_eg_ev` 0.588 +/- 0.063,
`perovskite_thickness_nm` 0.425 +/- 0.047, `rs_ohm_cm2` 0.174 +/- 0.044,
`thermal_resistance_k_cm2_w` 0.041 +/- 0.005 — the nominal ordering with the thermal
resistance promoted into the top four.

**Regime comparison:** cross-regime rank correlations rho = 0.864 / 0.930 / 0.969.
Parameters whose importance is regime-dependent by the pre-declared criterion
(index range > max(0.10, 2x mean replicate spread)): **`rs_ohm_cm2`,
`perovskite_eg_ev`, `perovskite_thickness_nm`, `thermal_resistance_k_cm2_w`**.

**Per-output drivers (nominal)** show that no single parameter explains the device:
Voc is bandgap-dominated (S_T 0.932), FF is resistance-dominated (0.781), junction
temperature is thermal-resistance-dominated (0.902), the current-matching ratio is
thickness-dominated (0.582), and the heat load is dominated by parasitic absorption
(0.360). Ranking a design on PCE alone hides this structure.

**Non-monotonicity is measured, not assumed** (`response_shape`, 21-point 1-D
slices per axis, three regimes):

| Axis | Shape | Optimum | PCE range on the slice |
| --- | --- | --- | --- |
| `perovskite_eg_ev` | **INTERIOR-OPTIMUM** | 1.61 eV (nominal), 1.64 eV (concentrated/hot) | 6.4-7.4 pp |
| `perovskite_thickness_nm` | **INTERIOR-OPTIMUM** | 690 nm | 9.3-11.4 pp |
| `arc_thickness_nm` | **INTERIOR-OPTIMUM** | 77 nm | 2.9-3.6 pp |
| `rsh_ohm_cm2` | MONOTONE | at the high bound | 8.9-16.7 pp |

## 36. Interactions — what is estimable at this budget, and what is not

**First result: this campaign's raw pairwise indices are NOT reportable.** Measured
on Ishigami at the campaign's own design (N = 96, d = 3):

| Seed | S13 (truth 0.2437) | Largest spurious pair (truth 0.0) |
| --- | --- | --- |
| 0 | 0.01 | 0.240 |
| 1 | 0.36 | 0.340 |
| 2 | 0.17 | 0.087 |

Spurious pairs reach the magnitude of the real one and the real pair moves by 0.35
between designs. The artifact therefore sets `pairwise_indices_reportable = false`
and keeps the raw values "for audit only".

**Second result: the interaction BUDGET is usable and costs nothing.** S_T - S1 (the
interaction share of a parameter's effect) is far more stable than a pairwise index
and identifies the same physics: `rs_ohm_cm2` is almost entirely interaction-driven
at nominal (S_T 0.140, S1 -0.148, budget +0.288) and under concentration
(0.591 / 0.193 / +0.399).

**Third result: a dedicated interaction study at a calibratable design size.**
d = 4 dominant axes, N = 768, L4 (15,360 evaluations), detection floor calibrated at
exactly that design (0.128):

| Regime | Reportable pairs (> 0.128) | Reading |
| --- | --- | --- |
| nominal 1 sun | `perovskite_eg_ev x perovskite_thickness_nm` **+0.234** | current matching: bandgap and thickness are only jointly meaningful |
| 3 suns | `perovskite_thickness_nm x rs_ohm_cm2` **-0.209**, `perovskite_eg_ev x rs_ohm_cm2` **-0.142** | at 3x photocurrent the I^2 R loss punishes exactly the designs that absorb more |

Sub-floor pairs (e.g. `rs_ohm_cm2 x arc_thickness_nm` 0.061 at nominal) are retained
in the artifact but explicitly not interpreted.

**Ranking stability across design size.** The d = 4, N = 768 study reproduces the
d = 14, N = 96 ordering in both regimes (nominal: Eg > thickness > rs > ARC;
concentrated: rs > Eg > thickness > ARC) even though the magnitudes shift (0.590 ->
0.738 for Eg at nominal). The RANKING is robust to the sample size; the numbers are
not, and the artifact reports both.

## 37. Negative results: screening and local sensitivity both mis-rank

**L2 screening is not a substitute for L4 analysis.** Same designs, same samples,
only the fidelity differs:

| Regime | rho(L2 vs L4 ranking) | Verdict | Disagreeing parameters |
| --- | --- | --- | --- |
| nominal | 0.648 | RANKING-SHIFTED | 7 |
| concentrated | 0.367 | RANKING-SHIFTED | 7 |
| hot ambient | 0.521 | RANKING-SHIFTED | 7 |

The reason is structural, not numerical: L2 has no thermal feedback and no resistive
network, so it cannot see `thermal_resistance_k_cm2_w` or the I^2 R-driven importance
of `rs_ohm_cm2`. **Screening may reject parameters; it may not rank them.** This is
the quantitative answer to Update J's question about when low fidelity is safe, and
it is a NEGATIVE result: the cheap model is not usable for the purpose it would be
most useful for.

**Local (OAT) sensitivity anti-correlates with global sensitivity.**

| Regime | rho(local vs global ranking) | Local top-3 | Global top-3 |
| --- | --- | --- | --- |
| nominal | **-0.358** | `silicon_eg_ev`, `perovskite_eg_ev`, `thermal_resistance_k_cm2_w` | `perovskite_eg_ev`, `perovskite_thickness_nm`, `rs_ohm_cm2` |
| concentrated | **-0.565** | `silicon_eg_ev`, `thermal_resistance_k_cm2_w`, `perovskite_eg_ev` | `rs_ohm_cm2`, `perovskite_eg_ev`, `thermal_resistance_k_cm2_w` |
| hot ambient | **-0.503** | `silicon_eg_ev`, `perovskite_eg_ev`, `thermal_resistance_k_cm2_w` | `perovskite_eg_ev`, `perovskite_thickness_nm`, `rs_ohm_cm2` |

A parameter with a large local derivative at the anchor (`silicon_eg_ev`) is globally
unimportant; a parameter with a dominant global index (`perovskite_thickness_nm`) is
not locally special at 500 nm. The mechanism is visible in §35: the dominant
responses are interior optima, so a slope at one point says almost nothing about
variance over the space. The two rankings contain the SAME 14 parameters — they are
compared by ORDER, never by which parameters appear.

**Monotone/linear screens under-rank the most important parameter.** On the same
samples (nominal, replicate 1): linear model R^2 = 0.563; Spearman ranks
`perovskite_thickness_nm` (+0.483) first and `perovskite_eg_ev` (+0.326) fourth,
whereas the variance decomposition puts `perovskite_eg_ev` first (0.590 vs 0.532).
A monotone statistic cannot see an interior optimum. Therefore the LHS/Spearman
cross-check VALIDATES the simulation design (agreement that the design explores real
variation) but does NOT validate the ranking, and the artifact stores it under that
restricted claim.

**Distribution dependence is real and only partly quantified here.** A
variance-based index is defined relative to the sampling distribution. The
`rsh_ohm_cm2` axis has a 16.7 pp 1-D range at nominal yet a small index under the
campaign's uniform-linear prior, because almost all of that prior's mass sits in the
benign high-resistance region. The attempt to quantify the alternative log-uniform
prior is recorded as a **diagnostic negative result** (`prior_sensitivity` section):
the low-shunt region is partly INVALID (`electrical.range.ff`,
`electrical.range.pce_pct`, `electrical.range.jmp_ma_cm2` all fail at 50 ohm cm2 in
combination with current-matching extremes; 5/480 points rejected, and the survivors
are not a random sample of the prior), and the surviving indices at N = 96 are
noise-dominated (an FF first-order index of -1.11 is not a physical statement). The
question is deferred to V1.9-E, where priors and uncertainty belong — the registry
range is not a probability distribution and is not treated as one.

**A diagnostic honest-reporting case.** `arc_thickness_nm` shows S1 (0.145) > S_T
(0.039) at nominal, which is mathematically impossible for an exact decomposition.
It is the signature of estimator noise on a small parameter at N = 96; it is reported
as an inconsistency rather than resolved by quoting whichever of the two numbers
looks better.

## 38. Tests, benchmarks, engineering

**TESTS (26 new, all passing; full suite 168 passed / 1 skipped in 92.3 s)**

| Area | Tests |
| --- | --- |
| estimator known answers | Ishigami first/total/second-order vs analytic values; S_T >= S1; bootstrap CI covers the truth; the documented N = 96 error band |
| design | block structure (AB_i differs from A only in column i), reproducibility by seed, never leaves the box |
| INVALID handling | NaN rows -> `complete=False` with counts, never imputed; all-NaN -> NOT_APPLICABLE; zero variance -> UNDEFINED (not zero) |
| validity envelopes | reachable values inside the registered range (regression for a sign bug found in development), nominal box == registered box, concentrated box restricted and probe-verified, shared box == per-axis intersection (regression for the uniform-rescale bug) |
| engine hardening | an out-of-envelope solve is INVALID in the verdict *and* the flag, on both dispatch paths |
| campaign | regime indices + provenance, box within registered, screening labelled, rejection accounting, local/global separation, Spearman helpers |
| interactions/calibration | pairwise non-reportability at N = 96, calibrated floor, inert-variable structural zero, sub-floor pairs excluded |
| artifact | digest verifies, PRE-GATE label, L4 analysis level, unreachable regimes recorded, interaction pairs above the floor, calibration section complete, runtime absent from the physics digest |

**BENCHMARKS (2 vCPU sandbox; machine-specific)**

| Measurement | Value |
| --- | --- |
| L4 batch throughput | 32.2 solves/s (300-sample batch) |
| Sobol section per regime (5,760 L4 solves + screening + probes) | 211-291 s |
| Interaction study per regime (7,680 L4 solves) | 246-308 s |
| Response-shape section (42 axes x 21 points, 3 regimes) | 26 s |
| Cumulative campaign compute for this artifact | ~1,516 s (25 min) of L4 physics |
| Preserved V1.9-C speedups | 718x single-point, 1206x batch(3) vs the reference solver |

**ENGINEERING.** The driver runs each of the eight sections independently, flushes
after every one, and merges into the existing artifact; a crash in one section can no
longer destroy the other seven. That property was earned: during development the
driver crashed three times in the final section, and the third fix (sections writable
in isolation) is what turned a 25-minute run into a 20-second rerun. Two real bugs
were found and fixed this way — a 14-axis box handed to a 4-axis design (now
`shared_box_named`), and a stub `estimator_validation` section silently replacing the
full calibration on rewrite (the merge now prefers the existing full section).
`runtime_s` is deliberately excluded from the physics digest, and the cumulative
runtime is stored outside it.

## 39. What changed, why, limitations, next target

**What changed (V1.9-C9 -> V1.9-D).** New: `apmt/sensitivity/` (Saltelli design and
estimators, Ishigami calibration, regime campaign, validity envelopes and the shared
verified box, LHS/Spearman cross-check, interaction study, response shapes, prior
diagnostic), `tools/v19_sensitivity_campaign.py`, `tests/test_v19_sensitivity.py`,
`data/v19_sensitivity.json`. Modified: `apmt/validation/guard.py` and
`apmt/device/batch.py` (INVALID solves now carry a HARD invariant failure). No
historical artifact or number was changed and nothing was deleted.

**Why.** Update D of the program requires global sensitivity to be a verified
instrument rather than a set of numbers. The verification is what produced the
usable methodology: report interaction budgets, not pairwise indices; report
established vs indistinguishable, not small vs zero.

**KEY FINDINGS.**

1. **The dominant parameter is regime-dependent.** `rs_ohm_cm2` is 3rd at 1 sun
   (S_T 0.140) and 1st at 3 suns (0.591); `perovskite_eg_ev` goes the other way
   (0.590 -> 0.251). Ranking parameters once, at one operating point, is invalid.
2. **The bandgap and the perovskite thickness are only jointly meaningful**
   (`S_Eg x thickness` = +0.234, the single reportable pair at nominal).
3. **At 3 suns the resistive loss attacks exactly the designs that generate more**
   (negative thickness x rs and Eg x rs pairs) — the first mechanism-level
   explanation of the ranking change, not a correlation.
4. **Only two parameters are established at 1 sun at this sample size**, and one at
   3 suns. The rest are indistinguishable from zero *given the calibrated estimator
   error* — a deliberately weaker and honest claim.
5. **Screening and local sensitivity mis-rank; only L4/L5 variance-based analysis
   ranks** (§37), which is now a measured constraint for Updates E-M.
6. **The model's validity boundary is a joint constraint, not a box**: full
   registered-box validity is 1.00 / 1.00 / 0.50 at 1 / 3 / 3 suns.

**LIMITATIONS (explicit).**

* First/total-order indices at N = 96 carry up to 0.27 absolute error; only the top
  one or two parameters per regime are quantitatively meaningful, and the
  replicate spreads (e.g. 0.591 +/- 0.153 for rs at 3 suns) are reported everywhere.
* Pairwise indices from the campaign design are NOT reportable; only the dedicated
  N = 768, d = 4 study is, and only above its 0.128 floor.
* Regimes are three; the shared box is a box, so the index values apply to that box
  and not to the registered ranges.
* The `rsh_ohm_cm2` distribution dependence is demonstrated but not quantified (§37);
  the fix is a prior-based analysis, which is Update E's job.
* ISC labelling: every number in this part is **PRE-GATE / MODEL-OBSERVED /
  EXPLORATORY**. No claim here is an experimental claim.

**NEXT TARGET (V1.9-E).** Build the surrogate layer on top of this instrument:
benchmark GP / tree ensembles / neural and polynomial-sparse surfaces for
PCE/Jsc/Voc/FF/temperature, with RMSE/MAE/max-error, extrapolation detection,
uncertainty calibration and error-region detection; consume the §35 response shapes
(interior optima, interaction pairs) as structure the surrogates must reproduce;
exclude INVALID points at the dataset level (using the §34 shared box and the
verdict-level INVALID hardening); and never let a surrogate's smoothness override a
high-fidelity verification.

## 40. V1.9-E — pre-gate surrogate campaign outcome (2026-10-10)

**Status: `PRE_GATE_COMPUTATIONAL_SURROGATE_FOUNDATION`.** Every output in this
section is model-observed computational evidence, not an experiment or an opened
gate. The V1.8 experimental gate and all prior V1.9-D results remain unchanged.
The audit-only read of V1.9-D found **zero eligible row-level multivariate
training records**; its N=96 Sobol estimates, aggregate curves, and historical
interaction estimates were not used as surrogate labels. New points were solved at
L4 (IQE-M1) inside the V1.9-D shared verified box; L5 was a paired, finer-numerical
resolution check on the same physical model, not independent model-form validation.
The global models cover 14 named features and 11 outputs, for only the three
specified regimes. The other 29 registry parameters are held at their defaults.

### 40.1 Sampling, role separation, and actual row counts

The predeclared global sequence was L4 LHS stage 1 (128 points/regime), LHS stage 2
(256), then two residual-guided adaptive batches (32 each). Family choice was made
on a fresh independent-validation family; that same validation set also guided
acquisition, so it is not treated as the final test. After family choice, a separate
64-point/regime L4 family was used for prediction-spread/conformal calibration.
The untouched global final holdout was a third fresh L4 LHS family, initially
planned at 96 points/regime; invalid physics rows were excluded from metrics. None of
the final-holdout rows was used for fitting, model-family choice, calibration,
threshold setting, or adaptive acquisition. Support/OOD calibration, optimum-slice
selection/calibration/verification, and interaction-slice selection/calibration/L4
verification are separately role-labelled in the raw dataset.

| Regime | All L4 rows: valid / invalid (total) | Global 14-D L4 fit rows | Model-selection validation | Prediction calibration | Untouched final holdout | Paired L5 checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Concentrated · 3 sun · 25 °C | 1185 / 10 (1195) | 443 | 63 | 64 | 95 | 12 |
| Hot ambient · 1 sun · 65 °C | 1194 / 1 (1195) | 447 | 64 | 64 | 96 | 12 |
| Nominal · 1 sun · 25 °C | 9643 / 0 (9643) | 448 | 64 | 64 | 96 | 44 |

There are **12,101 total records: 12,090 `VALID_FOR_SURROGATE` and 11
`INVALID_PHYSICS`**. No exact/effectively repeated parameter vectors were marked;
incomplete output, outside-verified-box, and unresolved-data counts are all zero.
Structured design dependence (Saltelli blocks and one-dimensional sweeps) is not
an exact duplicate and is described separately below. The 11 invalid records were
not regressed: 10 concentrated-regime attempts (junction temperature 400.0–402.8 K
outside the registered electrical-model validity window [220, 400] K) and one hot
adaptive point failing the registered FF/PCE/Jmp range invariants. Status, error,
HARD-invariant ledger, full input vector, outputs (or null for invalid rows), role,
design family, campaign, seed, model level/form, solver options/status, runtime,
physics digest, and point/input fingerprints are retained in the gzip dataset.

The 12,090 valid rows are **not 12,090 IID observations**. They comprise 12,022 L4
and 68 L5 records. The 68 L5 records point to their L4 design partners and are
fidelity comparisons, not extra training weight. The nominal L4 count is dominated
by the dedicated N=768 Saltelli interaction design (7,680 evaluations): A/B/AB/BA
blocks are dependent by design, and are counted as one structured variance-design,
not 7,680 independent regression samples. The optimum verifications are structured
41-point one-dimensional sweeps, not multivariate training rows. The actual eligible
unique global regression-training rows are **443 concentrated / 447 hot / 448
nominal (1,338 total)**. The 14-D design-family grouped PCE CV uses four training
families and three grouped folds; pooled RMSE is 1.577 / 1.611 / 1.815 pp,
concentrated / hot / nominal. The independent-validation PCE RMSEs after the
predeclared adaptive budget were **0.734 / 1.004 / 0.710 pp**, all above the fixed
0.25 pp target; every regime stopped for that same target-not-met reason.

Scope-specific row counts are likewise explicit: each three-feature optimum slice
has 128 L4 training, 64 selection-validation, 64 calibration and 123 independent
L4 curve-verification points (41 per axis); the nominal four-feature interaction
slice has 512 L4 training, 128 selection-validation, 128 calibration and the
separate 7,680-evaluation final Saltelli design. There are 12 paired L5 global
checks per regime and 32 additional paired L5 interaction checks at nominal. The
support detector's valid in-domain calibration counts are 46 / 48 / 48 (two of the
48 concentrated attempts were physically invalid); withheld-corner calibration
and final-test counts are 24 each per regime. Boundary-validation rows are
additional and never enter global regression. These scope counts are not added to
the 1,338 global training rows.

**Leakage and spatial-separation audit.** Global model selection (63/64/64 valid
points), conformal calibration (64 each) and final testing use separate design
families; grouped CV withholds whole global training families. A post-run
nearest-training-distance audit used Euclidean coordinates normalized by each
scope's verified box. For the 14-D models, the minimum train-to-validation distance
was 0.111–0.134; calibration minima were 0.480–0.524; final-holdout minima were
0.311–0.556. In the 3-D optimum scope the corresponding minima were only 0.008–0.029
(validation), 0.015–0.039 (calibration), and 0.018–0.032 (curve verification). In
the 4-D interaction scope they were 0.0359, 0.0394, and 0.0188 (final Saltelli).
No exact duplicates occurred, and the global final holdout remained untouched, but
**no predeclared minimum-distance buffer or formal spatial-block holdout was
implemented**. Therefore these are separate-family / fresh-LHS assessments, not
proof of spatially blocked generalization—especially for the specialized low-D
slices. A future validation tranche must predeclare and enforce a distance buffer
before any spatial-generalization claim.

### 40.2 Global model selection and untouched final-holdout errors

Six families (constant baseline, ridge, degree-2 sparse polynomial, ExtraTrees,
HistGradientBoosting, and Matérn Gaussian process) were compared using the separate
selection-validation rows. The selected family shown below is selected per target
and regime. No neural model was added. Final-holdout error is prediction minus L4
truth; normalized RMSE is RMSE divided by training-target SD (or training range if
SD is zero). Median relative error omits near-zero truth values using the
output-specific floor recorded in the JSON. **PCE errors are percentage points.**
“Box-edge RMSE” is over holdout points with any of the 14 normalized coordinates
within 5% of a shared-box face; its N is shown. The JSON also retains all four
nearest-training-distance-quartile metrics and the five worst residual coordinates
per target.

**Concentrated · 3 sun · 25 °C — final holdout N=95 valid L4 points**

| Target (unit) | Selected family | RMSE | MAE | Max abs error | Bias | nRMSE | Median relative error (%) | Box-edge RMSE (n) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` (mW/cm²) | sparse_polynomial | 4.4457 | 3.5811 | 11.3878 | 0.3264 | 0.259 | 2.01 | 4.6631 (67) |
| `current_matching_ratio` (1) | extra_trees | 0.1544 | 0.1036 | 0.7282 | 0.0086 | 0.173 | 6.40 | 0.1746 (67) |
| `ff` (1) | sparse_polynomial | 0.0492 | 0.0403 | 0.1721 | -0.0026 | 0.271 | 6.51 | 0.0498 (67) |
| `heat_load_mw_cm2` (mW/cm²) | hist_gradient_boosting | 6.5443 | 5.1696 | 25.9722 | 0.3769 | 0.385 | 2.32 | 7.2300 (67) |
| `j_bottom_sc` (mA/cm²) | sparse_polynomial | 2.5608 | 2.0102 | 6.7374 | 0.0443 | 0.164 | 2.35 | 2.6569 (67) |
| `j_top_sc` (mA/cm²) | hist_gradient_boosting | 2.4593 | 1.7489 | 8.8829 | 0.1647 | 0.159 | 2.53 | 2.6572 (67) |
| `jsc_ma_cm2` (mA/cm²) | hist_gradient_boosting | 2.7755 | 2.1951 | 7.3145 | 0.2334 | 0.307 | 3.83 | 2.8112 (67) |
| `pce_pct` (%) | extra_trees | 1.1004 | 0.8067 | 3.7861 | 0.0384 | 0.258 | 6.09 | 1.2251 (67) |
| `radiative_loss_mw_cm2` (mW/cm²) | hist_gradient_boosting | 2.7813 | 2.0717 | 8.8586 | -0.0075 | 0.151 | 3.23 | 2.9255 (67) |
| `temperature_k` (K) | sparse_polynomial | 1.9475 | 1.5314 | 5.5355 | 0.0034 | 0.100 | 0.35 | 2.0417 (67) |
| `voc_v` (V) | sparse_polynomial | 0.0261 | 0.0199 | 0.0867 | -0.0027 | 0.110 | 1.27 | 0.0277 (67) |

Split-conformal 90% intervals use the disjoint 64-point calibration family; the last two columns are **measured on the untouched final holdout**, not assumed from the nominal level. Radius/width are in target units.

| Target | Calibrated q90 radius | Final empirical coverage | Mean final interval width |
| --- | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` | 8.2079 | 91.6% | 16.4159 |
| `current_matching_ratio` | 0.2512 | 94.7% | 0.5024 |
| `ff` | 0.0969 | 98.9% | 0.1938 |
| `heat_load_mw_cm2` | 9.9388 | 91.6% | 19.8777 |
| `j_bottom_sc` | 3.4633 | 84.2% | 6.9267 |
| `j_top_sc` | 3.2861 | 84.2% | 6.5723 |
| `jsc_ma_cm2` | 5.0630 | 94.7% | 10.1259 |
| `pce_pct` | 2.0048 | 90.5% | 4.0097 |
| `radiative_loss_mw_cm2` | 4.5679 | 90.5% | 9.1358 |
| `temperature_k` | 3.3718 | 91.6% | 6.7435 |
| `voc_v` | 0.0473 | 90.5% | 0.0946 |

**Hot ambient · 1 sun · 65 °C — final holdout N=96 valid L4 points**

| Target (unit) | Selected family | RMSE | MAE | Max abs error | Bias | nRMSE | Median relative error (%) | Box-edge RMSE (n) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` (mW/cm²) | hist_gradient_boosting | 1.4928 | 1.1766 | 3.5142 | -0.3200 | 0.279 | 2.07 | 1.4781 (77) |
| `current_matching_ratio` (1) | extra_trees | 0.1652 | 0.1035 | 0.8579 | -0.0024 | 0.177 | 5.99 | 0.1718 (77) |
| `ff` (1) | hist_gradient_boosting | 0.0287 | 0.0206 | 0.1027 | -0.0031 | 0.298 | 1.94 | 0.0302 (77) |
| `heat_load_mw_cm2` (mW/cm²) | hist_gradient_boosting | 1.7970 | 1.3228 | 6.0066 | -0.2896 | 0.396 | 1.84 | 1.8962 (77) |
| `j_bottom_sc` (mA/cm²) | sparse_polynomial | 0.7483 | 0.5686 | 2.5987 | 0.0490 | 0.147 | 2.34 | 0.7327 (77) |
| `j_top_sc` (mA/cm²) | hist_gradient_boosting | 0.7605 | 0.5645 | 2.8794 | -0.0706 | 0.154 | 2.91 | 0.8158 (77) |
| `jsc_ma_cm2` (mA/cm²) | extra_trees | 1.0621 | 0.8470 | 2.5379 | 0.0360 | 0.336 | 4.82 | 1.1203 (77) |
| `pce_pct` (%) | hist_gradient_boosting | 1.0866 | 0.8836 | 2.4545 | 0.1145 | 0.344 | 6.37 | 1.0979 (77) |
| `radiative_loss_mw_cm2` (mW/cm²) | sparse_polynomial | 0.5211 | 0.4163 | 1.4366 | -0.0234 | 0.096 | 2.26 | 0.5557 (77) |
| `temperature_k` (K) | sparse_polynomial | 0.5406 | 0.4377 | 1.4947 | -0.0282 | 0.092 | 0.11 | 0.5729 (77) |
| `voc_v` (V) | ridge | 0.0153 | 0.0119 | 0.0481 | -0.0008 | 0.090 | 0.83 | 0.0161 (77) |

Split-conformal 90% intervals use the disjoint 64-point calibration family; the last two columns are **measured on the untouched final holdout**, not assumed from the nominal level. Radius/width are in target units.

| Target | Calibrated q90 radius | Final empirical coverage | Mean final interval width |
| --- | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` | 2.2383 | 84.4% | 4.4767 |
| `current_matching_ratio` | 0.2009 | 91.7% | 0.4018 |
| `ff` | 0.0437 | 89.6% | 0.0873 |
| `heat_load_mw_cm2` | 2.4882 | 90.6% | 4.9765 |
| `j_bottom_sc` | 1.3106 | 93.8% | 2.6213 |
| `j_top_sc` | 1.2687 | 90.6% | 2.5375 |
| `jsc_ma_cm2` | 1.5181 | 84.4% | 3.0362 |
| `pce_pct` | 1.3085 | 76.0% | 2.6169 |
| `radiative_loss_mw_cm2` | 0.9421 | 91.7% | 1.8842 |
| `temperature_k` | 1.0014 | 91.7% | 2.0028 |
| `voc_v` | 0.0260 | 91.7% | 0.0521 |

**Nominal · 1 sun · 25 °C — final holdout N=96 valid L4 points**

| Target (unit) | Selected family | RMSE | MAE | Max abs error | Bias | nRMSE | Median relative error (%) | Box-edge RMSE (n) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` (mW/cm²) | sparse_polynomial | 1.6061 | 1.2933 | 3.7337 | -0.0545 | 0.302 | 2.49 | 1.6757 (73) |
| `current_matching_ratio` (1) | extra_trees | 0.1691 | 0.0973 | 0.8391 | -0.0083 | 0.173 | 4.64 | 0.1886 (73) |
| `ff` (1) | hist_gradient_boosting | 0.0218 | 0.0164 | 0.0756 | -0.0021 | 0.270 | 1.59 | 0.0233 (73) |
| `heat_load_mw_cm2` (mW/cm²) | hist_gradient_boosting | 1.5741 | 1.2091 | 4.8273 | 0.1079 | 0.315 | 1.94 | 1.6709 (73) |
| `j_bottom_sc` (mA/cm²) | sparse_polynomial | 0.7306 | 0.5802 | 2.1342 | 0.0855 | 0.141 | 2.33 | 0.7448 (73) |
| `j_top_sc` (mA/cm²) | hist_gradient_boosting | 0.6258 | 0.4888 | 1.4983 | 0.0260 | 0.122 | 2.55 | 0.6308 (73) |
| `jsc_ma_cm2` (mA/cm²) | extra_trees | 1.0108 | 0.8034 | 2.3549 | 0.1238 | 0.316 | 4.62 | 1.0708 (73) |
| `pce_pct` (%) | hist_gradient_boosting | 0.9919 | 0.7694 | 2.9973 | 0.0470 | 0.264 | 3.28 | 1.0561 (73) |
| `radiative_loss_mw_cm2` (mW/cm²) | sparse_polynomial | 0.5749 | 0.4210 | 2.6311 | -0.0328 | 0.135 | 2.69 | 0.6005 (73) |
| `temperature_k` (K) | sparse_polynomial | 0.8331 | 0.6158 | 3.6456 | -0.0510 | 0.128 | 0.16 | 0.8655 (73) |
| `voc_v` (V) | ridge | 0.0118 | 0.0095 | 0.0311 | -0.0022 | 0.068 | 0.57 | 0.0121 (73) |

Split-conformal 90% intervals use the disjoint 64-point calibration family; the last two columns are **measured on the untouched final holdout**, not assumed from the nominal level. Radius/width are in target units.

| Target | Calibrated q90 radius | Final empirical coverage | Mean final interval width |
| --- | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` | 2.5912 | 87.5% | 5.1823 |
| `current_matching_ratio` | 0.2370 | 90.6% | 0.4740 |
| `ff` | 0.0439 | 94.8% | 0.0878 |
| `heat_load_mw_cm2` | 2.9123 | 91.7% | 5.8246 |
| `j_bottom_sc` | 1.2609 | 89.6% | 2.5218 |
| `j_top_sc` | 1.1188 | 89.6% | 2.2377 |
| `jsc_ma_cm2` | 1.7707 | 90.6% | 3.5414 |
| `pce_pct` | 1.7427 | 91.7% | 3.4854 |
| `radiative_loss_mw_cm2` | 0.8998 | 91.7% | 1.7997 |
| `temperature_k` | 1.3928 | 93.8% | 2.7855 |
| `voc_v` | 0.0198 | 89.6% | 0.0397 |

Empirical coverage is target/regime dependent: for example, hot PCE covers only
76.0% of 96 final points under a nominal 90% interval; hot conduction loss covers
84.4%, while several other targets over-cover. Concentrated bottom/top Jsc cover
84.2%; nominal box-edge conduction covers 87.5%. This is measured marginal
prediction-residual calibration under the chosen split—not conditional coverage,
physics-model uncertainty, or an experimental confidence interval. Native model
spread exists only for selected families that return one; it is a diagnostic, not a
posterior. Measured raw-spread intervals on final holdout are:

| Regime | Target | Selected family | Raw-spread empirical coverage | Mean raw-spread interval width |
| --- | --- | --- | ---: | ---: |
| Concentrated · 3 sun · 25 °C | `current_matching_ratio` | extra_trees | 100.0% | 0.8336 |
| Concentrated · 3 sun · 25 °C | `pce_pct` | extra_trees | 100.0% | 6.3569 |
| Hot ambient · 1 sun · 65 °C | `current_matching_ratio` | extra_trees | 100.0% | 0.7899 |
| Hot ambient · 1 sun · 65 °C | `jsc_ma_cm2` | extra_trees | 99.0% | 5.2731 |
| Nominal · 1 sun · 25 °C | `current_matching_ratio` | extra_trees | 100.0% | 0.8537 |
| Nominal · 1 sun · 25 °C | `jsc_ma_cm2` | extra_trees | 99.0% | 5.0179 |

The native-spread entries are ExtraTrees between-tree spreads and remain
`MEASURED_NOT_ASSUMED_CALIBRATED`; families without native predictive variance are
`NOT_AVAILABLE`, not assigned a fabricated standard deviation. Physics-model
uncertainty is not quantified. No experimental observations or experimental
uncertainties entered this campaign.

### 40.3 Support and withheld-corner detection

The withheld region is the verified-box corner with normalized perovskite bandgap
and thickness both at least 0.90; it is excluded from global/adaptive training.
Support classification combines the hard shared-box check with calibrated nearest
neighbor distance in normalized feature space, predictive uncertainty and model
family disagreement. A 14-D convex hull was not computed. `OUT_OF_DOMAIN` means
unsupported for surrogate use; it is **not** a physics-invalidity verdict, and the
support detector is not used to certify physics validity.

| Regime | In-box final N | Withheld-corner final N | Valid in-box support-cal N | Cal FPR / recall | Final in-box false-OOD rate | Final corner recall | Final in-box uncertain rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Concentrated · 3 sun · 25 °C | 95 | 24 | 46 | 6.5% / 16.7% | 4.2% | 16.7% | 66.3% |
| Hot ambient · 1 sun · 65 °C | 96 | 24 | 48 | 6.2% / 16.7% | 8.3% | 16.7% | 71.9% |
| Nominal · 1 sun · 25 °C | 96 | 24 | 48 | 8.3% / 33.3% | 18.8% | 58.3% | 58.3% |

The predeclared in-box false-OOD calibration cap was 10%. Final corner recall is
only 16.7% in both concentrated and hot regimes; nominal improves to 58.3%, but
its final in-box false-OOD rate is **18.75%**, above the 10% cap. Across regimes,
58.3–71.9% of in-box holdout points are downgraded to `IN_DOMAIN_UNCERTAIN`, so
support is conservative but not a useful high-recall OOD detector at this budget.
These weak scores are retained; no classifier was used to infer whether a solve is
physically valid.

### 40.4 Interior-optimum slice results

Each regime has its own three-input L4 PCE slice model (the other parameters are
held at registered defaults), chosen/calibrated on the scope-specific 64/64 fresh
validation/calibration families and fitted on 128 L4 rows. Each of three axes was
then checked on a separate 41-point L4 curve. The historical V1.9-D coordinate is
shown as a reference, not used as a training label. The L4 tolerance flag compares
with the prior grid resolution; that resolution is not a statistical confidence
interval. The surrogate curve maximum itself is not a verified device design.

| Regime | Axis (unit) | V1.9-D sampled max | New L4 curve max | Surrogate curve max | Coordinate error | Curve RMSE (pp) | Curve max abs error (pp) | Surrogate − L4 at L4 peak (pp) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Concentrated · 3 sun · 25 °C | `arc_thickness_nm` (nm) | 77.0000 | 77.0000 | 93.5000 | 16.5000 | 0.4195 | 0.8979 | -0.8979 |
| Concentrated · 3 sun · 25 °C | `perovskite_eg_ev` (eV) | 1.6400 | 1.6250 | 1.6700 | 0.0450 | 0.7127 | 1.5656 | -0.9422 |
| Concentrated · 3 sun · 25 °C | `perovskite_thickness_nm` (nm) | 690.0000 | 723.7500 | 723.7500 | 0.0000 | 0.6853 | 2.0622 | -0.4134 |
| Hot ambient · 1 sun · 65 °C | `arc_thickness_nm` (nm) | 77.0000 | 82.5000 | 99.0000 | 16.5000 | 0.9104 | 1.7684 | -1.7674 |
| Hot ambient · 1 sun · 65 °C | `perovskite_eg_ev` (eV) | 1.6400 | 1.6250 | 1.6850 | 0.0600 | 1.2080 | 2.2139 | -2.0231 |
| Hot ambient · 1 sun · 65 °C | `perovskite_thickness_nm` (nm) | 690.0000 | 723.7500 | 892.5000 | 168.7500 | 0.9977 | 2.4316 | -1.5575 |
| Nominal · 1 sun · 25 °C | `arc_thickness_nm` (nm) | 77.0000 | 77.0000 | 77.0000 | 0.0000 | 1.0395 | 1.9525 | -1.9458 |
| Nominal · 1 sun · 25 °C | `perovskite_eg_ev` (eV) | 1.6100 | 1.6250 | 1.5950 | 0.0300 | 1.2005 | 1.8736 | -1.8736 |
| Nominal · 1 sun · 25 °C | `perovskite_thickness_nm` (nm) | 690.0000 | 723.7500 | 1297.5000 | 573.7500 | 1.3093 | 2.2901 | -2.2901 |

All nine new L4 curve maxima fall within the recorded V1.9-D grid-resolution
comparison tolerance. Surrogate recovery is partial: the nominal thickness peak is
predicted at **1,297.5 nm** versus the new L4 curve maximum at **723.75 nm** (573.75
nm coordinate error); the hot thickness peak is 892.5 nm (168.75 nm error). Other
slice axes are closer but not uniformly accurate—the curve residuals above remain
material. Thus the historical broad-slice optima are L4-cross-checked at their
coarse grid resolution, but the surrogate has **not** recovered the optimum set.
No peak is promoted from a surrogate curve alone.

### 40.5 Dedicated interaction verification

The nominal interaction remains the dedicated four-axis
`perovskite_eg_ev × perovskite_thickness_nm` study; V1.9-D N=96 pair estimates are
not treated as truth. The fresh Saltelli design uses N=768 base points and 7,680 L4
evaluations. The new L4 pair estimate is **+0.388876**, above the calibrated
0.127726 detection floor (sign positive); the historical reference value +0.234130
is context only. The selected ExtraTrees interaction-slice model (512 train / 128
validation / 128 calibration) estimates **+0.402690**, a +0.013814 difference from
L4 and the same sign. Its nominal 90% split-conformal interval diagnostic covers
89.1% of the 7,680 design points, with mean width 2.309 pp. Those aggregate
interval/error numbers do **not** make the full-design surrogate pair reportable:

| Support status on the 7,680-point design | Count | Share |
| --- | ---: | ---: |
| `IN_DOMAIN_VALIDATED` | 4,508 | 58.7% |
| `IN_DOMAIN_UNCERTAIN` | 2,333 | 30.4% |
| `OUT_OF_DOMAIN` | 839 | 10.9% |

Because uncertain and unsupported points remain in the Saltelli estimator, the
surrogate pair is **not reportable over the full design**, despite its close point
estimate and sign recovery. The dedicated L4 estimate is reportable above its
calibrated estimator floor; the surrogate estimate is not. No pairwise bootstrap
confidence interval is claimed.

### 40.6 L5 numerical-fidelity cross-checks

L5 was evaluated on 12 paired global calibration designs per regime plus 32 paired
nominal interaction-calibration designs (68 pairs total); every pair uses the same
parameter vector at L4/L5 and is excluded from regression training. The table gives
the measured q95 absolute L5−L4 difference over those pairs, per output. These are
numerical-resolution deltas under the same physics model, not a measure of model-form
or experimental uncertainty and not a full-space L5 validation.

| Output (unit) | Concentrated q95 | Hot q95 | Nominal q95 |
| --- | ---: | ---: | ---: |
| `conduction_loss_mw_cm2` (mW/cm²) | 4.75e-05 | 3.02e-05 | 5.25e-05 |
| `current_matching_ratio` (1) | 1.18e-08 | 7.48e-09 | 1.52e-11 |
| `ff` (1) | 8.92e-07 | 1.82e-06 | 2.85e-06 |
| `heat_load_mw_cm2` (mW/cm²) | 5.51e-05 | 3.6e-05 | 6.21e-05 |
| `j_bottom_sc` (mA/cm²) | 4.98e-07 | 1.21e-07 | 2.14e-10 |
| `j_top_sc` (mA/cm²) | 1.99e-13 | 1.17e-13 | 0 |
| `jsc_ma_cm2` (mA/cm²) | 1.37e-07 | 6.31e-08 | 6.58e-11 |
| `pce_pct` (%) | 1.84e-05 | 3.6e-05 | 6.21e-05 |
| `radiative_loss_mw_cm2` (mW/cm²) | 1.39e-05 | 1.17e-05 | 9.66e-06 |
| `temperature_k` (K) | 1.28e-05 | 1.19e-05 | 1.58e-05 |
| `voc_v` (V) | 5.18e-07 | 6.05e-07 | 6.49e-07 |

Every target at the three audited surrogate-proposed candidates also passed the
campaign's paired L5 tolerance check. Only the hot-regime candidate cleared the
conjunctive support, conformal-error, hard-invariant, L4 and L5 checks and was marked
eligible for computational optimizer follow-up. Concentrated and nominal proposals
were rejected because their PCE surrogate errors (−2.538 pp and −0.528 pp) exceeded
the calibrated intervals, despite valid L4 solves and L5 cross-checks. The hot
candidate's PCE surrogate error was −0.254 pp and stayed inside its interval. This
is a verified computational candidate for further modeling—not a global optimum,
not experimental truth, and not promotion from prediction alone.

### 40.7 Measured cost, reproducibility, and evidence files

| Measurement | Observed |
| --- | ---: |
| Campaign wall time | 993.48 s (16.56 min) |
| L4 solve runtime, mean / median / p95 | 48.37 / 44.70 / 67.55 ms |
| L5 solve runtime, median | 53.08 ms |
| Full-bundle single prediction latency / throughput | 183.91 ms / 5.44 predictions/s |
| Measured single-prediction speed ratio vs median L4 | **0.243×** (surrogate is about 4.1× slower) |
| Batch of 256 predictions | 47.97 s / 5.34 predictions/s |
| Predeclared required speed ratio | 10× — **not met** |
| L4 physics solves replaced | **0** |
| Sum of model-fitting runtimes | 6.31 s |
| Peak RSS | 1,155,108,864 bytes (~1.08 GiB) |
| Serialized joblib bundle | 52,831,723 bytes (~50.4 MiB) |

The exact campaign used seed 20261009 on clean commit `cd7cbc05a5d7f67c788f8b82e6ed867bf5672d2d`, Python 3.11.2, NumPy 2.4.6, SciPy 1.17.1 and scikit-learn 1.9.1; primary fidelity L4, cross-check L5, model form IQE-M1. Physics-source digest is `df691e7bcb02d62d27edca754710081d71dfee6c86a48be1ca703c4f8a9a32b2`; registry digest is `3e8b92be318c578acd3f338c51a2c5bbdcbea19a894942f60ce2166d71e190d7`.

| Evidence artifact | Bytes | SHA-256 / digest |
| --- | ---: | --- |
| `data/v19e_surrogate_dataset_v3.json.gz` | 7,513,529 | file `31addfc5cd245f177ad259c6278d8a03eeeead1e7ad5fd25b76ff35b1dce808d`; dataset fingerprint `c3605d06b9e3d70c481698c7a4ee0352fbb848b321d92dfe4717fe2e62f2bfcd`; physics digest `709d5875de7f039a896a7297fa70ced87ac3a33dc622bd545d80fc0238ac21fe` |
| `data/v19e_surrogate_results_v3.json` | 859,373 | file `1a0aa9c6e842c001c9b5859a852cdb7e44075900d2b43209b6cf13d0b97a7481`; physics digest `5832785fbc42f6d5f25bf17953c4812d872d0a55f7717b29e92ac21ab916fac0` |
| `data/v19e_surrogate_models_v3.joblib` | 52,831,723 | SHA-256 `0b1272b86612def8c42b17f959e2e2e30cbe46af6f6a5167cb56bc37b9a233c4` |

The dataset and results JSON are the compact immutable evidence selected for Git;
the 50.4-MiB run-specific joblib remains under the repository's generated-artifact
ignore policy and is identified by its hash above. Global model cards carry the
exact per-regime training fingerprint (concentrated
`8ce44ab7b0dfaa8b54bc388de19a6b8c8a0daea4b50e7fb5b110ff3f2d2b9843`, hot
`b32adede02e5316f754726a4e4a48b90f57ea6e2e8f3535ed6ce4f3a6f99ff99`, nominal
`4f91ead26f8117daa8bf4d64e3d4bd7c813c017992572fd1ea13884b1cdb31a0`); the three
optimum-slice fingerprints and nominal interaction fingerprint are recorded in the
same JSON alongside each model card. The dataset fingerprint is recomputable from
its valid records plus rejection ledger. A small code correction (`cd7cbc0`) makes
that fingerprint invariant to JSON mapping-key reorder; a regression test covers
the round trip. The campaign row content and its existing fingerprint are
unchanged. The raw dataset physics digest and result physics digest both recompute
successfully.

Reproduction command (defaults write the versioned v3 paths above):

```bash
.venv/bin/python tools/v19e_surrogate_campaign.py --seed 20261009
```

Synthetic analytic-surface, Ishigami, heteroscedastic-noise, invalid-region and
adaptive-sampling tests in the result file are method/software checks only; they
are not evidence about the device. The next useful work is a predeclared spatially
blocked validation design, stronger withheld-region detection, improved PCE
accuracy and a faster prediction path. Until then, V1.9-E remains pre-gate: the
accuracy and speed targets failed, OOD detection was weak, optimum recovery was
partial, and only the dedicated L4 interaction—not its full-design surrogate
estimate—is reportable.

### 40.8 Post-run repository and integrity checks

These checks validate the saved evidence and repository after the campaign; they do
not rerun or add observations to the 16.56-minute campaign. The full test suite
reported **190 passed, 1 skipped, 5 warnings**; the skip is the expected unavailable
accepted-manuscript PDF, and the warnings are scikit-learn GP convergence warnings.
`tools/ci_checks.py` passed **6/6** checks (artifact pins, digitizer determinism,
provenance, gate consistency, report/checksum consistency and tracked-data
non-mutation). `ruff check` passed on the two changed Python files, and
`git diff --check` was clean. Independent post-run checks recomputed the dataset
fingerprint and dataset/results physics digests, and matched the dataset, results
JSON and excluded model-bundle file hashes and byte sizes to the recorded values
above. The report checksum is maintained separately in `reports/.report_sha256`.

---

# PART V1.9-F — SURROGATE RELIABILITY, SPATIAL GENERALIZATION AND OPTIMIZATION READINESS

**Status: `PRE_GATE_COMPUTATIONAL_RELIABILITY_AUDIT`.** Everything in this part
is model-observed computational evidence. No experiment was run, no gate was
opened, and no headline PCE claim is made. APMT remains
**`BLOCKED_BY_BASELINE_VALIDATION`**. All V1.9-E numbers above are preserved;
this part only adds verification, reproduction, and new predeclared analyses.

**Date:** 2026-10-10 · **Repository:** github.com/Thedivinetwilight/Solar ·
**Branch:** `arena/a6cb5ca0-solar` (session branch; the referenced
`arena/01a102e7-solar` resolves to the same commit `afe4757` on the remote).

## 41. V1.9-F — reliability audit outcome

### 41.1 Repository and evidence verification (Phase 0)

| Check | Result |
| --- | --- |
| Repository identity | `Thedivinetwilight/Solar` — CONFIRMED (`git remote -v`) |
| Session branch | `arena/a6cb5ca0-solar`; remote HEAD is `main` at `9a98e9f` |
| Local HEAD at start | `afe4757cdc02b41fd9fbfab49d33503e6b37c134`, working tree clean |
| Commit `afe4757` present | YES (HEAD) |
| Commit `0257b50` ("surrogate lint cleanup") present | **NO — absent from this history.** The clone contains exactly two commits (`9a98e9f` → `afe4757`); history before `afe4757` is not present, so no lint-cleanup commit could be inspected. The V1.9-E "ruff passed on changed files" claim is UNVERIFIED here, not contradicted. |
| Generation commit `cd7cbc0` (recorded in results metadata) present | NO — same truncated history. Codebase equivalence was therefore verified by digest, not by commit (next row). |
| Physics-source digest recomputed from working tree | `df691e7b…9a32b2` — MATCHES results metadata |
| Registry digest recomputed from working tree | `3e8b92be…190d7` — MATCHES results metadata |
| V1.9-E report SHA-256 at start | `cd1cfc9e…3de0` — MATCHES the briefed value |
| `data/v19e_surrogate_dataset_v3.json.gz` | `31addfc5…808d`, 7,513,529 B — MATCHES §40.7 |
| `data/v19e_surrogate_results_v3.json` | `1a0aa9c6…7481`, 859,373 B — MATCHES §40.7 |
| Dataset fingerprint recomputed | `c3605d06…fcd` — MATCHES |
| Dataset physics digest recomputed | `709d5875…21fe` — MATCHES |
| Results physics digest recomputed | `5832785f…6fac0` — MATCHES |
| Model bundle `data/v19e_surrogate_models_v3.joblib` | absent from disk and git-ignored — policy upheld |
| Test suite (`pymupdf` installed to match the briefed env) | **190 passed, 1 skipped, 5 warnings** — MATCHES §40.8 exactly (skip = missing manuscript PDF) |
| `tools/ci_checks.py` | **6/6 PASS** |
| Ruff (v0.17.0) whole-tree count | 454 at V1.9-F start → 447 at end (7 fixed inside touched files, 0 added); all files created/modified in V1.9-F are individually `ruff`-clean (verified per file) |

Environment: Python 3.11.2, NumPy 2.4.6, SciPy 1.17.1, scikit-learn 1.9.1 —
identical to the V1.9-E campaign environment (§40.7).

### 41.2 V1.9-E baseline reproduction (Phase 1)

The exact historical campaign was rerun twice with seed `20261009`.

* **Rerun #1** (scratch paths outside the repo) completed all 12,101 rows and
  the model bundle, then crashed writing the summary: `campaign.py` calls
  `dataset_path.relative_to(ROOT)`, which fails for out-of-repo `--dataset`
  paths. This is a tooling limitation (in-repo default path unaffected);
  `campaign.py` was deliberately left untouched. Its 12,101 rows fingerprinted
  **bit-identically** (`c3605d06…fcd`) before the crash.
* **Rerun #2** (repo-relative scratch dir, removed afterwards) completed:
  906.6 s wall time, status `PRE_GATE_COMPUTATIONAL_SURROGATE_FOUNDATION`.

| Artifact | Rerun #2 | Committed | Verdict |
| --- | --- | --- | --- |
| Dataset fingerprint | `c3605d06…fcd` | `c3605d06…fcd` | BIT-IDENTICAL (12,101 rows) |
| Dataset file SHA-256 | `53dbe587…f42b` (7,514,146 B) | `31addfc5…808d` (7,513,529 B) | differ only in run metadata (git commit/branch/RSS) |
| Every science metric (selections, RMSEs, thresholds, candidates, pairs, curves, L5 tolerances, counts) | — | — | **BIT-IDENTICAL** across all compared blocks |
| Results physics digest | `c034284b…13e3` | `5832785f…6fac0` | differ: digest covers `audited_at_commit` and artifact paths/hashes, which legitimately vary by checkout |
| Single-point speedup | 0.233× | 0.243× | same verdict (`NOT_MET` vs 10×); machine timing noise |
| Bundle file SHA-256 | `56a5dae9…5523` (52,831,656 B) | `0b1272b8…233c4` (52,831,723 B) | joblib bytes not bit-stable (67 B) |
| **Bundle predictions** (final holdout, 3 regimes × 3 targets) | — | — | **BIT-IDENTICAL** (max diff 1.6e-17) |
| Campaign stderr warnings | 2 ConvergenceWarnings | not recorded in §40 | identified in §41.9 (synthetic benchmarks only) |

**BASELINE_REPRODUCED: YES.** The excluded model bundle is reproducible from
committed inputs plus documented settings: behaviorally bit-identical (only
pickle bytes differ). No committed evidence file was modified by the reruns.

### 41.3 Predeclared thresholds (Phase 11 ledger)

| Threshold | Value | Declared in |
| --- | --- | --- |
| PCE validation RMSE target | 0.25 pp | `apmt/surrogate/campaign.py:45` |
| Minimum surrogate speedup vs median L4 | 10× | `apmt/surrogate/campaign.py:47` |
| Marginal-improvement stop fraction | 0.05 | `apmt/surrogate/campaign.py:46` |
| Support in-box false-OOD cap | 0.10 | `fit_support_profile` default; campaign passes `0.10` |
| Withheld-region recall weakness gate | 0.50 | `campaign.py` negative-results rule |
| Conformal nominal coverage | 0.90 | `MODEL.conformal_coverage`; `conformal_radius(coverage=0.90)` |

No threshold was invented, relaxed, or redefined in V1.9-F. The 0.25 pp target
is retained as-is; §41.4 explains why it currently sits far below the
selection-noise floor (a finding, not a relaxation).

### 41.4 Spatial generalization audit (Phase 2)

Protocol: `apmt/surrogate/spatial.py` (`v19f-spatial-protocol/1.0`), declared
before any V1.9-F evaluation. Primary metric: Euclidean distance in
verified-box-normalized coordinates (same as V1.9-E support; limitation —
equal weight per normalized unit across wildly different physical spans — is
stated, not patched post-hoc). Buffer rule: **median leave-one-out
nearest-neighbor distance of the TRAINING design** (training geometry only, no
test peeking). Blocks: `perovskite_eg_ev` quartile slabs LOW {z0<0.25} /
HIGH {z0>0.75}. Strata with <8 points report counts only.

Refits reproduce all 198 V1.9-E family validation RMSEs and all support
thresholds **bit-for-bit** (max diff 0.0), so every probe below evaluates the
documented V1.9-E models. Final-holdout rows were never used to fit or select
anything in V1.9-F.

Buffer radii: concentrated 0.780 / hot 0.791 / nominal 0.770 (14-D
curse-of-dimensionality scale). PCE stratification (pp RMSE):

| Regime / set (grade) | Full | Interpolation (d<buf) | Separated (d≥buf) | Low slab | High slab |
| --- | ---: | ---: | ---: | ---: | ---: |
| conc / FINAL (final) | 1.100 | 1.137 (n=45) | 1.067 (n=50) | 1.149 | 1.022 |
| conc / Boundary (final) | 1.326 | 0.590 (n=9) | 1.446 (n=38) | 1.186 | 1.389 |
| conc / OOD corner (final) | 1.322 | INSUF (n=6) | 1.371 (n=18) | INSUF | 1.322 |
| hot / Final (final) | 1.087 | 1.156 (n=43) | 1.027 (n=53) | 1.129 | 1.009 |
| hot / Boundary (final) | 1.003 | 0.896 (n=16) | 1.052 (n=32) | 0.647 | 1.295 |
| hot / OOD corner (final) | 0.892 | INSUF (n=7) | 0.926 (n=17) | INSUF | 0.892 |
| nom / Final (final) | 0.992 | 0.889 (n=40) | 1.059 (n=56) | 1.187 | 0.783 |
| nom / Boundary (final) | 1.179 | 1.415 (n=13) | 1.078 (n=35) | 1.407 | 1.220 |
| nom / OOD corner (final) | 1.348 | INSUF (n=6) | 1.282 (n=18) | INSUF | 1.348 |

All-target separated-vs-full RMSE on final holdout differs by −15%…+23% with
no consistent sign — no target collapses under scattered separation.

**Diagnostic block refits** (same family, slab withheld from training, tested
on VALIDATION rows in the slab — diagnostic grade, FINAL untouched):

| Regime | Slab | Full-train on slab | Slab-withheld refit |
| --- | --- | ---: | ---: |
| conc | LOW / HIGH | 0.411 / 0.617 | **3.114 / 1.853** |
| hot | LOW / HIGH | 0.593 / 0.427 | **2.640 / 1.123** |
| nom | LOW / HIGH | 1.123 / 0.703 | **3.506 / 1.382** |

(n=13–17 per slab; direction consistent across all six blocks.)

**Interpretation (answers A–F).** (A) Grouped interpolation: reproduced
V1.9-E grouped-CV RMSEs 1.577/1.611/1.815 pp bit-identically. (B) Scattered
spatial separation at this density is benign — error is a global floor, not a
function of train distance in the observed range. (C) Boundary regions are
mildly worse (+0.0–0.2 pp). (D) Withheld corners: prediction degrades little,
but see §41.6 — the detector cannot find them. (E) Outside-box handling is
tested in §41.6 (hard-box refusal; physics never runs by default). (F)
Optimization-selected candidates: §41.8. The apparent validation→holdout
optimism (0.68–0.79 → 0.99–1.10 pp) is acquisition overfitting: adaptive
batches were placed near high-error validation points, making the selection
set locally easier — a protocol effect, not a model improvement. Genuinely
missing regions (slab withholding) degrade error 2–7×: the model interpolates
between scattered points but does not extrapolate across missing quartiles.

### 41.5 Model accuracy and error structure (Phase 3)

**Finding 1 — the V1.9-E Gaussian process is degenerate on the 14-D scope.**
`gaussian_process_matern` receives RAW physical units in every campaign path
(thickness 150–1500, rsh 50–1e6, …) while its ARD length-scale prior (init
0.25, bounds 0.025–4.0) assumes box-normalized features. The kernel matrix is
numerically the identity, the marginal likelihood is flat, the optimizer never
moves, and the family predicts the training mean everywhere: validation RMSE
is **bit-identical to `constant`** in all three regimes (3.9874/2.7955/3.4772
pp). The code comment claiming pre-normalized inputs was false for every
campaign path (corrected). Model selection in V1.9-E was therefore effectively
5-way, and GP "predictive std" on the global scope equaled the training SD
everywhere. This failure is SILENT: the full 198-fit global refit emits zero
warnings.

**Correction (not promotion).** New family `gaussian_process_matern_boxnorm`
applies the documented fixed box normalization INSIDE the estimator (bounds
are construction parameters, no fold leakage). The original family is
preserved bit-identically; `MODEL_FAMILIES` (the campaign default) is
unchanged. Seven-way PCE comparison on identical splits/seeds:

| Regime | Validation ranking (predeclared) | Holdout ranking (post-hoc diagnostic) |
| --- | --- | --- |
| conc | ET 0.679 > HGB 0.769 > poly 0.942 > **boxGP 1.003** > ridge 1.349 > const=GP 3.987 | **boxGP 0.561** > poly 0.974 > HGB 1.032 > ET 1.100 > … |
| hot | HGB 0.754 > ET 0.936 > **boxGP 1.159** > poly 1.331 > … | **boxGP 0.931** > ET 1.075 > HGB 1.087 > poly 1.161 > … |
| nom | HGB 0.7850 > ET 0.7852 > poly 1.341 > **boxGP 1.405** > … | **boxGP 0.987** > HGB 0.992 > ET 1.154 > poly 1.617 > … |

Validation selection is UNCHANGED in all regimes (ET/HGB/HGB) — the corrected
GP is functional but not selected, so it is reported, not promoted.

**Finding 2 — selection at n≈64 is underpowered (paired bootstrap, B=2000,
in results JSON).** Nominal ET−HGB dRMSE=+0.0003, 95% CI [−0.20,+0.17]
(P=0.55: a coin flip). Concentrated HGB−ET +0.090 CI [−0.05,+0.25]; hot ET−HGB
+0.182 CI [−0.14,+0.46]. Boxnorm-GP vs selected: CIs all include 0
(P=0.14/0.32/0.23). Only linear families are robustly worse. The 0.25 pp
target is ~4× below this selection-noise floor. The validation→holdout rank
flip (selected families degrade, unselected GP improves) is the textbook
winner's-curse signature.

Residual structure: worst-case holdout PCE errors 2.45–3.79 pp; signed bias
+0.04–0.11 pp globally; boundary-region errors mildly elevated (§41.4 table);
no stratum isolates the error — the ~1 pp floor is model bias at 448 sparse
14-D points, not local sparsity. No scaling/hyperparameter change beyond the
GP correction was attempted: there is no evidence a different fixed
configuration would cross 0.25 pp, and tuning against the holdout diagnostic
would invalidate it.

### 41.6 Uncertainty, OOD and support reliability (Phase 4)

**New withheld corners (216 fresh L4 solves, all VALID — OOD≠invalid):
frozen V1.9-E thresholds, no tuning on new labels.**

| Regime | Corner A (low/low) | Corner B (high/low) | Corner C (low/high) | Pooled | V1.9-E corner (ref) |
| --- | ---: | ---: | ---: | ---: | ---: |
| conc | 0.125 | 0.125 | 0.292 | **0.181** | 0.167 |
| hot | 0.292 | 0.167 | 0.125 | **0.194** | 0.167 |
| nom | 0.375 | 0.333 | 0.375 | **0.361** | 0.583 |

(n=24/corner; in-box false-OOD on final holdout 0.042/0.083/0.188;
in-box uncertain rate 0.58–0.72.) The detector fails on all three new
independent corners exactly as on the V1.9-E corner. Root cause, measured:
in 14-D at this density the distance signal is uninformative — median
train-distance is 0.80–0.89 for corner points vs 0.79–0.81 for in-box holdout
(§41.4). No threshold separates these distributions at acceptable FPR.

**Invalid-row probe (11/11 committed INVALID rows):** support says 2
VALIDATED / 7 UNCERTAIN / 2 OOD — the detector does not detect physical
invalidity (as designed) — while `verify_candidate` rejects all 11 via the L4
guard (`INVALID_PHYSICS`, none eligible). The guardrail "the OOD classifier
must not replace hard physical invariants" is empirically demonstrated:
2 invalid points pass support yet all fail physics.

**Verdict:** the support classifier is a conservative abstention mechanism
(58–72% uncertain), NOT a reliable general-purpose OOD detector. Outside-box
points still refuse before prediction acceptance (hard-box check unchanged).

### 41.7 Calibration and prediction intervals (Phase 5)

Implementation audit: `conformal_radius` uses the correct finite-sample form
k=⌈(n+1)·0.90⌉ (n=64 → k=59); calibration rows are disjoint from training and
selection; final evaluation never tunes calibration. Empirical PCE coverage
by stratum (nominal 90%):

| Regime | Final full | Final interp/sep | Boundary full | Corner full |
| --- | ---: | ---: | ---: | ---: |
| conc (r=2.00) | 0.905 | 0.867 / 0.940 | 0.872 | 0.833 |
| hot (r=1.31) | **0.760** | 0.721 / 0.792 | 0.854 | 0.833 |
| nom (r=1.74) | 0.917 | 0.950 / 0.893 | 0.896 | 0.792 |

The hot under-coverage is global (both strata), not spatial — its radius is
too small for its error distribution. Stratum coverages otherwise scatter
0.72–1.00 at small n: marginal calibration holds approximately; conditional
coverage by region is NOT established and is not claimed. Native GP/tree
spreads remain diagnostics: boxnorm-GP raw 90% Gaussian intervals cover
0.93–0.99 on holdout (widths 2.7–3.7 pp) — conservative, uncalibrated.
No interval here is an experimental confidence interval; physics-model
uncertainty remains NOT_QUANTIFIED.

### 41.8 Optimum recovery and selection bias (Phase 6)

**Why V1.9-E recovery was partial.** Slice-model refits reproduce the V1.9-E
families/RMSEs exactly. Diagnosis on the verification curves: (i) L4 peaks are
SHARP (only 2/41 points within 0.05 pp of peak — misses are real, not flat-top
noise); (ii) systematic NEGATIVE curve bias (nominal −0.68…−1.04 pp, hot
−0.58…−1.08 pp; concentrated/HGB +0.01…−0.19 pp) — tree ensembles smooth sharp
maxima by leaf averaging, and the boosting family fits peaks markedly better;
(iii) training coverage near curves is adequate (3-D dmin 0.018–0.104,
dmed 0.08–0.14) — the miss is model bias, not missing data; (iv) curve RMSEs
(0.42–1.31 pp) match validation RMSEs (0.70–1.10 pp) — recovery is exactly as
(partially) expected, no surprise.

**Controlled candidate-selection study** (identical budgets: pool 200, k=6,
4 methods, 3 seeds; 216 L4 verifications, all proposals verified, none
promoted from prediction; no new L5 solves in V1.9-F). Median best-verified
PCE across seeds:

| Regime | max-pred | disagreement-UCB | diverse-top-quartile | random baseline |
| --- | ---: | ---: | ---: | ---: |
| conc | 20.50 | 20.50 | 20.37 | 18.78 |
| hot | 18.94 | 18.59 | 18.82 | 16.98 |
| nom | 22.17 | 22.17 | 22.12 | 21.37 |

Surrogate-guided methods beat random in 7/9 regime-seeds (2 ties, 0 losses;
methods often share the same best — they overlap on the pool's top region).
Rank quality: predicted-vs-
verified Spearman is high for random pools (0.77–1.00, wide spread easy to
rank) but poor within the selected top region (diverse-top-quartile as low as
0.03; max-pred 0.60–0.94). **Separation:** (1) predicting PCE accurately —
NO (~1 pp errors); (2) ranking the top region finely — NO; (3) recovering a
high-performing verified design — PARTIALLY YES (region-finding beats random,
all gains L4-verified). No candidate is promoted; these are computational
probes, not device claims.

### 41.9 Computational cost (Phase 7)

Breakdown (V1.9-E rerun #2 + V1.9-F measurements; L4 runtimes from committed
records): L4 mean/med/p95 48.4/44.7/67.6 ms; L5 median 53.1 ms; campaign
906.6 s (rerun) vs 992.4 s (committed); global refit 34.9 s (peak RSS
0.78 GiB); V1.9-F tool 96–102 s total including 432 new L4/L5 solves.

Profiling: single-point `predict()` costs 183 ms because it issues 33
estimator calls (11 targets × selected+2 alternatives) plus an ExtraTrees
160-tree spread loop per tree model — 0.24× vs median L4. New `predict_batch`
vectorizes the estimator calls with **identical per-row numerics** (max diff
6e-14; row-equality pinned by tests): 256-point batch in 0.33 s (1.31 ms/pt),
**34× amortized throughput vs median L4**, exceeding the 10× target on the
throughput metric. Single-point latency is unchanged code and still
**NOT_MET** (0.24×) — both numbers are reported against the predeclared
target; the target was not redefined. No numerical, integrity, or
verification shortcut was taken for speed (L4 verification remains mandatory).

### 41.10 Convergence warnings (Phase 8)

Complete ledger (every warning traced to its fit):

| Source | N | Cause | Material? |
| --- | ---: | --- | --- |
| Test suite, small synthetic fits | 5 | ARD length-scale/noise bounds on toy data | No — software checks (unchanged, still 5) |
| V1.9-E campaign synthetic benchmarks | 2 | same (dim-1 scale→4.0; noise→1e-10) | No — software checks, no physics impact |
| V1.9-E campaign physics fits (all 200+) | 0 | — | Silence includes the degenerate 14-D GP (optimizer never moves) |
| V1.9-F boxnorm-GP (new family) | 5–7/regime | ARD pruning: scales→4.0 on uninformative axes | Verdict-robust (below) |

Targeted diagnostic (not a blind bound change): widening length-scale bounds
4.0→40.0 makes validation RMSE slightly WORSE in all regimes
(1.405→1.470, 1.003→1.033, 1.159→1.204) with per-point shifts ≤1.2 pp. The
bounds are therefore KEPT; the warnings mark ARD axis pruning, and the
"GP loses to trees" verdict holds under both. The material correction was the
normalization fix (§41.5), which is compared honestly and not promoted. No
warning was suppressed in production code.

### 41.11 Interaction model reliability (Phase 9)

Refit reproduces the V1.9-E interaction slice bit-identically (ExtraTrees,
support counts 4508/2333/839, L4 pair +0.388876, surrogate +0.402690).
Support-status geography on the 7,680-point Saltelli design: OOD mass
concentrates toward HIGH normalized Eg (median z0 0.60 vs 0.50 for validated
— inherited from the high-Eg/high-thickness calibration corner); other axes
are balanced. A central-box hypothesis ([0.15,0.85]^4, n=1736, 92.6%
validated share) is recorded as **HYPOTHESIS_NOT_VALIDATED**: defining the
region from the same design that estimated the pair effect would be circular,
and a Saltelli subset cannot carry the structured estimator, so the full-
design surrogate pair stays **NOT_REPORTABLE** and no sub-region claim is
made. Fresh Saltelli verification inside the box is NOT_RUN (explicit V1.9-G
candidate).

### 41.12 Reproducible research campaign (Phase 10)

`tools/v19f_reliability_campaign.py` (seed 20261010; ruff-clean) reproduces
every number in §§41.4–41.11 from committed evidence plus bounded new physics:
432 saved rows (216 withheld-corner + 216 candidate-selection, i.e. 4 methods
× 6 proposals × 3 regimes × 3 seeds) and 11 unsaved invalid-row re-verifies,
443 new L4 solves total, 0 new L5 solves. 46 cross-method duplicate solves are
ledgered and **bit-identical, max diff 0.0** — a physics-determinism spot
check.

| Evidence artifact | Bytes | SHA-256 / digest |
| --- | ---: | --- |
| `data/v19f_reliability_results.json` | 257,459 | file `56f56c0f…ef2f1`; physics digest `76fdc6da…0b24da` |
| `data/v19f_new_rows.json.gz` | 314,888 | file `ba818b78…1020` (run metadata varies); dataset fingerprint `9855e0a7…e30e65` (stable across 3 runs); physics digest `8b54dd9f…a518b` (stable) |

Role discipline: refits use TRAIN/ADAPTIVE_TRAIN (+ slice roles in scope);
FINAL rows never fit or select; frozen V1.9-E thresholds evaluate new corners.
Determinism: three tool runs share the dataset fingerprint; file SHAs vary
only in RSS/timing metadata (same known pattern as V1.9-E artifacts).

### 41.13 Success criteria verdict (Phase 11)

1. Reproducible evaluation — PASS (bit-identical rerun; 3× stable V1.9-F fingerprint).
2. Defensible spatially separated validation — PASS (predeclared protocol, buffers, blocks, counts).
3. Quantified PCE prediction errors — PASS (~1 pp floor; bias/quantiles/worst-case by stratum).
4. Measured OOD detection performance — PASS (4 corners; detector honestly FAILED: recall 0.13–0.38).
5. Honest uncertainty-calibration results — PASS (marginal ≈; hot under-covers; conditional NOT claimed).
6. Independent L4 candidate verification — PASS (216 selection + 216 corner + 11 invalid-reverify L4 solves; nothing promoted from prediction).
7. Optimum-recovery under controlled budgets — PASS (region-finding beats random; fine ranking poor).
8. Measured computational costs — PASS (breakdown; batch path 34× amortized; single still NOT_MET).
9. Investigated convergence warnings — PASS (full ledger; justified no-change on bounds).
10. Explicit interaction-support limits — PASS (geography mapped; sub-region HYPOTHESIS only).
11. Passing regression tests and CI — PASS (205 passed, 1 skipped, 5 warnings; `ci_checks.py` 6/6).
12. No weakening of the scientific validation gate — PASS (thresholds unchanged; APMT stays BLOCKED).

Performance remains insufficient for optimization-assistant duty (items 4 and
7 are honest failures of the MODEL, passes of the EVALUATION). The purpose —
determining what the surrogate can reliably do — is met.

### 41.14 Guardrails (Phase 12)

APMT remains `BLOCKED_BY_BASELINE_VALIDATION`; the baseline gate was not
reopened. No new headline APMT PCE claim is produced (candidate PCEs are
pre-gate computational probes with L4 verification, not experimental
results). L5 was used only as a paired numerical cross-check. No model
parameter is presented as a measured material property. No synthetic-data
recovery is presented as experimental validation. Model physics was not
changed (physics digest `df691e7b…9a32b2` reproduced exactly). Negative
results and unsupported regions are preserved above.

### 41.15 Tests, files, and V1.9-G readiness

Final verification: `pytest` **205 passed, 1 skipped, 5 warnings** (190
pre-existing + 15 new in `tests/test_v19f_reliability.py`; the 5 warnings are
the original suite warnings — new tests capture their own). `ci_checks.py`
**6/6**. `ruff check` clean on all created/modified files
(`apmt/surrogate/{spatial,models,engine}.py`, `tools/v19f_reliability_campaign.py`,
`tests/test_v19f_reliability.py`). `git diff --check` clean.

Files: added `apmt/surrogate/spatial.py` (predeclared protocol),
`tools/v19f_reliability_campaign.py` (10-step campaign),
`tests/test_v19f_reliability.py` (15 tests), `data/v19f_reliability_results.json`,
`data/v19f_new_rows.json.gz`; modified `apmt/surrogate/models.py`
(box-normalized GP + lint), `apmt/surrogate/engine.py` (validated batch path +
lint). No existing behavior changed (campaign defaults bit-identical).

**V1.9-G readiness: NOT READY as a 14-D global optimization assistant.**
Demonstrated: reproducible evaluation, honest error floors (~1 pp vs 0.25 pp
target), working (if coarse) slice-scope region-finding, and a 34×-throughput
batch path. Blocking: OOD detection uninformative in 14-D, selection noise
floor ~0.2–0.3 pp, slab-extrapolation failure, sharp-peak smoothing.
Recommended next experiments (all NOT_RUN): (1) fresh Saltelli verification of
the [0.15,0.85]^4 interaction box; (2) a distance-informative OOD detector
study (e.g.Axis-aware or density-based, declared before evaluation);
(3) denser or reduced-dimension training to attack the 1 pp floor;
(4) spatially-blocked acceptance gate for any future selection claim;
(5) peak-targeted slice modeling (sharp-maximum bias correction).

**Five most important discoveries.** (1) The V1.9-E GP family is degenerate
(bit-identical to `constant`) from a raw-units/kernel-scale mismatch —
silent, no warnings. (2) Family selection at n≈64 is noise (top-two P≈0.5);
the 0.25 pp target is ~4× below the selection floor. (3) Scattered separation
is benign but slab withholding degrades error 2–7× — interpolation vs
extrapolation properly separated. (4) The OOD detector fails on all four
corners because 14-D train-distances of corner vs in-box points overlap
almost completely. (5) Slice-scope region-finding beats random 8/9 times
while fine ranking collapses (Spearman as low as 0.03) — predict/rank/recover
are three different tasks with three different verdicts.

**Five highest-priority remaining limitations.** (1) PCE error floor ~1 pp
(4× target) with 2.5–3.8 pp worst cases. (2) No reliable general-purpose OOD
detector; 58–72% abstention is the only safety. (3) Hot-regime conformal
under-coverage (0.76 at nominal 0.90). (4) Sharp-peak smoothing causes
100–500 nm argmax misses on slice optima. (5) Single-point latency still
0.24× L4 (batch path only helps throughput workloads).

---

# PART V1.9-G — REDUCED-DIMENSIONAL DISCOVERY, OOD STUDY, INTERACTION SALTELLI AND SELECTION

**Status: `PRE_GATE_COMPUTATIONAL_DISCOVERY_STUDY`.** Everything in this part
is model-observed computational evidence. No experiment was run, no gate was
opened, and no headline PCE claim is made. APMT remains
**`BLOCKED_BY_BASELINE_VALIDATION`**. All V1.9-E and V1.9-F numbers above are
preserved; this part only adds verification, a predeclared discovery campaign,
and honest pass/fail verdicts against predeclared criteria.

**Date:** 2026-10-10 · **Repository:** github.com/Thedivinetwilight/Solar ·
**Branch:** `arena/a6cb5ca0-solar` (verified identical to the reported
V1.9-F branch; local HEAD = remote HEAD = `95ec5cd` at campaign start).

## 42. V1.9-G — reduced-dimensional discovery outcome

### 42.1 Verified repository state and V1.9-F baseline reconciliation

Identity gate: remote URL `github.com/Thedivinetwilight/Solar` CONFIRMED;
branch `arena/a6cb5ca0-solar`; HEAD `95ec5cdc53617ee84b3294e04a23fd5341326f48`
matches the reported final commit; commit sequence `bd6cb8a → f1311fd →
95ec5cd` verified; working tree clean; environment identical to V1.9-F
(Python 3.11.2, NumPy 2.4.6, SciPy 1.17.1, scikit-learn 1.9.1). The full
V1.9-E campaign was NOT rerun (no documented reason); the V1.9-E reference
was reproduced by exact refit (§42.5).

Every reported V1.9-F claim was re-checked against committed artifacts
before use as baseline: file hashes/sizes (4/4 match), dataset fingerprints
(`c3605d06…` via valid+ledger, `9855e0a7…` via valid_records — duplicates
live in both lists, so concatenation double-counts), physics digest
`df691e7b…` and registry digest `3e8b92be…` reproduced from the working
tree, selections (ET/HGB/HGB, 0.6789/0.7542/0.7850), the full 7-way
validation table, the nominal ET−HGB bootstrap (+0.0003, CI [−0.20,+0.17],
P=0.55), corner recalls (0.181/0.194/0.361), calibration coverages, tests
**205 passed / 1 skipped / 5 warnings**, and `ci_checks.py` **6/6** — ALL
CONFIRMED. Two transcription errata in §41 were found and are corrected
here (history preserved): (1) §41.15 "beats random 8/9 times" should read
7/9 with 2 ties and 0 losses per the §41.8 table and JSON (verified:
7 strict, 2 ties, 0 losses); (2) §41.9 "432 new L4/L5 solves" should read
432 new L4 solves (0 new L5, as §41.12 correctly states).

### 42.2 Parameter audit (Phase 3A)

All 14 surrogate axes were audited against four evidence streams: V1.9-D
Sobol total-order (max over regimes, L4, N=96×2), V1.9 OAT at the nominal
baseline (committed), the new first-hand full-box 1-D audit probe (9-pt
linear grids × 14 axes × 3 regimes plus 9-pt log grids on rsh/srh/srv;
459 L4 solves, 0 invalid), and L4 code-path inspection. Training coverage
is 100% of every verified-box range (1,338 TRAIN/ADAPTIVE_TRAIN rows).

| Axis (units, verified box) | Directly modeled in L4 | ST max / OAT / audit range | Verdict |
| --- | --- | --- | --- |
| perovskite_eg_ev (eV, 1.4–2.0) | absorption edge, J0, current match | 0.590 / 2.53 / **7.40 pp** | ACTIVE (all triggers + confirmed pair) |
| perovskite_thickness_nm (nm, 150–1500) | absorption, J0 slab | 0.532 / 5.12 / **11.21 pp** | ACTIVE (all triggers + confirmed pair) |
| perovskite_urbach_mev (meV, 5–60) | absorption tail | 0.022 / — / **1.55 pp** | ACTIVE (audit trigger) |
| perovskite_srh_lifetime_ns (ns, 10–20000) | J0 slab (propagates ≈0) | 0.000 / 0.00 / 0.02 pp | FIXED at 1000 (inert in-box) |
| silicon_eg_ev (eV, 1.1–1.16) | bottom edge, Varshni Voc | 0.004 / — / **0.91 pp** | ACTIVE (audit trigger) |
| silicon_thickness_um (µm, 60–400) | bottom absorption | 0.004 / 0.15 / 0.48 pp | FIXED at 260 (knife-edge: 0.48 vs 0.50 rule) |
| silicon_srv_cm_s (cm/s, 0.1–1000) | bottom J0 surface term | 0.006 / — / **0.62 pp** | ACTIVE log10 (audit trigger, high-end effect) |
| silicon_light_trapping (×, 1–30) | bottom path length | 0.013 / 0.10 / 0.20 pp | FIXED at 1.0 (= low bound default) |
| rear_reflectance (—, 0–0.98) | rear mirror | 0.000 / — / 0.06 pp | FIXED at 0.0 (default) |
| arc_thickness_nm (nm, 0–220) | thin-film front optics | 0.039 / 1.96 / **3.58 pp** | ACTIVE (OAT + audit; fringe structure) |
| parasitic_layer_thickness_nm (nm, 0–60) | front parasitic absorption | 0.018 / 0.08 / 0.47 pp | FIXED at 15 (knife-edge: 0.47 vs 0.50 rule) |
| rs_ohm_cm2 (Ω·cm², 0–20) | series loss | 0.591 / 0.33 / **11.95 pp** | ACTIVE (ST + audit) |
| rsh_ohm_cm2 (Ω·cm², 50–1e6) | shunt loss | 0.000 / 0.48 / **16.74 pp** | ACTIVE log10 (saturation check FAILED: 0.82 pp above 1000) |
| thermal_resistance (K·cm²/W, 0.159–0.778) | self-heating loop | 0.184 / 2.39 / **4.85 pp** | ACTIVE (all triggers) |

Classification: (A) strong — Eg, thickness, rs, arc, Rth; (B) weak-but-real
— urbach, si_eg, si_srv; (C) confirmed interaction — Eg×thickness (V1.9-D
+0.234 > 0.128 floor, nominal); (D) narrow/nonlinear — arc fringes, rsh
shunt recovery, Rth thermal edge; (E) insufficient-evidence notes —
si_thickness/parasitic sit 0.02–0.03 pp below the audit trigger (rule
sensitivity documented, threshold NOT re-tuned). No axis is declared
universally unimportant: fixed axes are fixed to stated values with stated
scope, not dropped as meaningless.

### 42.3 Operating slice and comparison design (Phases 3B–3C)

The predeclared rule (ST > 0.03 OR OAT > 0.5 OR audit > 0.5 OR confirmed
pair; rsh fixed unless > 0.5 pp above 1000 Ω·cm²) selected **9 active**
axes and 5 fixed. Models compared with equivalent data access on the slice:

1. **Reduced slice model** — 9-D (Eg, thickness, urbach, si_eg, log10 si_srv,
   arc, rs, log10 rsh, Rth), 7-family selection on slice validation.
2. **Full-dimensional reference** — the exact V1.9-E refit (ET/HGB/HGB on
   448/443/447 training rows), evaluated on identical slice test points.
3. **Simple baselines** — `constant` (slice mean) and `ridge` inside the 7-way.

Fixed values (registered defaults, all asserted inside the verified box):
srh 1000 ns, si_thickness 260 µm, light_trapping 1.0, rear_reflectance 0.0,
parasitic 15 nm. The slice supports ONLY this configuration: shunted
designs (rsh ≲ 1000), textured rears, non-default parasitics/Si thickness,
and SRH-engineered absorbers are OUT OF SLICE SCOPE by construction. Slice
training (448/region) matches the V1.9-E nominal training count
(amendment G-A2, before any slice physics); log10 scales for rsh/si_srv are
fixed box transforms (amendment G-A1, before any slice physics); the peak
budget cap was corrected 300 → 600 (amendment G-A3: the original cap was
arithmetically inconsistent with the predeclared scan design; recorded
after a loud assertion, before any peak was examined). All three
amendments are embedded in the results artifact with rationale and
no-peeking justification.

### 42.4 Spatially blocked evaluation protocol (Phase 4)

Coordinates: verified-box-normalized, with log10 applied on the two
log axes (limitation stated: equal weight per scaled unit; log axes
compress decades by design). Distance: Euclidean. Buffer rule (unchanged
from V1.9-F for comparability): median leave-one-out NN distance of the
TRAINING design — 0.493/0.498/0.498 on the 9-D slice vs 0.77–0.79 in
V1.9-F 14-D, i.e. the curse visibly relaxes. Categories reported with
counts: interpolation / separated / boundary (margin < 0.05) / Eg slabs /
withheld slice corners / interaction box / peak neighborhoods /
unsupported+invalid / operating slice. Training, selection, calibration,
and final evaluation use disjoint role sets (guarded by assertion).

### 42.5 Slice accuracy: the corrected GP wins, the full reference collapses (Phase 3C)

Slice training/validation/calibration/final per regime:
448/64/64/96 (conc, 0 invalid), 446/63/63/93 (hot, 7 invalid),
443/61/60/95 (nom, 13 invalid). **The box-normalized GP is selected in all
three regimes** (validation 0.652/0.466/0.610 vs HGB 0.954/0.982/1.285 and
ET 1.379/1.132/1.716) — with dense slice data and correct scaling, the GP
is the best family, reversing the 14-D verdict. The raw-units GP again
ties `constant` bit-for-bit (4.164/4.073/4.915), reproducing the V1.9-F
degeneracy finding on new data.

PCE accuracy on slice FINAL (pp RMSE), reduced (GP) vs full reference vs
constant:

| Regime | Reduced | Full ref | Constant | Reduced MAE / bias | G_SLICE_ERR ≤ 0.50 |
| --- | ---: | ---: | ---: | ---: | --- |
| conc | 0.513 | 1.699 | 3.594 | 0.373 / −0.021 | MISS (2.5% over) |
| hot | 0.514 | 2.970 | 3.766 | 0.364 / +0.064 | MISS (2.8% over) |
| nom | 0.605 | 4.075 | 4.981 | 0.451 / +0.119 | MISS |

**G_SLICE_BEATS_FULL: PASS in all regimes** — paired bootstrap
(full−reduced) dRMSE +1.19/+2.46/+3.47, CIs [+0.84,+1.57]/[+1.83,+3.08]/
[+2.60,+4.24], P = 1.000. **G_SLICE_ERR: FAIL in all regimes**, narrowly
(0.51/0.51/0.61). No winner's curse: the GP also leads the post-hoc final
ranking (HGB second at 0.87–1.10). Error structure: boundary strata worse
(0.56–0.72) than interpolation (0.33–0.55); hot separated (0.66) is 2× its
interpolation (0.33) — on the slice, distance predicts error, unlike 14-D.
Worst cases 1.97–2.26 pp (q90 0.76–0.98).

Why the full reference fails on the slice was isolated mechanistically:
its error concentrates in the LOW-rsh tertile (RMSE 2.36/4.61/6.65, max
errors 8–13 pp), while on rsh > 1000 it recovers to 1.24/1.68/1.61 —
near its native 14-D error. The slice's log-uniform rsh sampling probes
the shunt regime the linear-trained reference never saw; the pinned-5
corner costs only ~0.2–0.6 pp. The reduced model wins by matching the
operating distribution AND by lower dimension — both mechanisms are
real and reported. The G_SLICE_ERR miss is likewise boundary-driven: the
reduced model's own low-rsh-tertile RMSE (0.64–0.79) vs mid/high
(0.36–0.52) shows the shunt-recovery edge dominates the residual.

### 42.6 OOD detector study: a valuable negative (Phase 5)

Ensemble: knn distance (k=5) + local sparsity (k=10/radius) + model
disagreement (selected+2 alts), thresholds at the 90th dev percentile
(val rows only), OOD iff ≥2 fire. Physical-invalid and outside-box
overrides retained; the L4 guard remains binding and separate.

| Regime | New-corner recall (pooled, n=48) | In-box FPR (n≈95) | G_OOD_RECALL ≥ 0.50 | G_OOD_FPR ≤ 0.10 |
| --- | ---: | ---: | ---: | ---: |
| conc | 0.375, CI [0.25,0.52] | 0.104, CI [0.06,0.18] | FAIL | FAIL (marginal) |
| hot | 0.312, CI [0.20,0.45] | 0.129, CI [0.08,0.21] | FAIL | FAIL |
| nom | 0.250, CI [0.15,0.39] | 0.063, CI [0.03,0.13] | FAIL | PASS |

Both criteria FAIL (FPR CIs cover 0.10 in conc/hot, but point estimates
miss). Indicator autopsy: corner vs in-box MEDIANS are nearly identical
(knn 0.61–0.65 vs 0.56–0.58; sparsity 1.37–1.42 vs 1.24–1.27;
disagreement overlapping) — detections come from tails only. The 14-D
ensemble on frozen V1.9-F corners recalls 0.40/0.49/0.31 (vs frozen
single-distance 0.18/0.19/0.36) but its dev-fitted thresholds do NOT
transfer (hot test FPR 0.25 vs dev 0.10). New 14-D combos recall
0.29–0.62. Bluntly: geometry cannot separate withheld corners from
scattered training data in 9–14-D at this density, and the ensemble
abstains LESS (5–29%) than V1.9-F's detector (58–72%) while detecting no
better — as a safety device it is weaker, and V1.9-F's conservative
abstention remains the only working guardrail. The L4 guard rejected
34/34 invalid rows (11 committed + 23 new). OOD detection stays a major
open defect; no deployment may rely on these votes.

### 42.7 Fresh Saltelli central box (Phase 6)

Predeclared: 4 axes (Eg, thickness, rs, arc), normalized [0.15,0.85]^4 =
physical Eg [1.49,1.91], thickness [352.5,1297.5], rs [3,17], arc
[33,187], others at defaults (exactly the V1.9-F hypothesis box);
N=256, second order, 3 regimes, 7,680 fresh L4 solves, 0 invalid
(complete designs). Bootstrap CIs (200) + even/odd split-half stability.

Total-order (central box): conc rs 0.69 ± 0.11 / Eg 0.34 ± 0.06 /
thickness 0.06 / arc 0.02; hot Eg 0.88 ± 0.17 / thickness 0.26 / rs 0.14 /
arc 0.07; nom Eg 0.69 ± 0.15 / thickness 0.25 / rs 0.12 / arc 0.10.
Rank order matches V1.9-D full-box in conc/nom (hot is FIRST interaction
evidence for that regime). **G_SALTELLI_STABLE: 1/3** — ranks agree
across halves everywhere, but |ΔST| fails hot (0.18) and marginally nom
(0.10 vs 0.10): total magnitudes for the dominant axis are unstable, and
bootstrap CIs agree. **Second-order pairs are INCONCLUSIVE**: estimates
flip sign between halves (e.g. nom thickness×rs +1.57 even vs −1.01 odd)
with absurd magnitudes — N=256 with pseudo-random (non-quasi) base
samples is inadequate for pairs under a dominant axis (first-order sums
reach 1.46 in hot). The V1.9-D N=768 full-box Eg×thickness pair (+0.234
nominal) stands as the only converged pair evidence. Scope Expand:
central-box shares differ from full-box (nom thickness 0.25 vs 0.53) —
indices do not transfer across scopes. INTERACTION_SUBSET_SALTELLI is now
RUN with the above limitations (pairs NOT_RUN at converged N).

### 42.8 Narrow peaks: fringes are broad, two maxima resolved (Phase 7)

Predeclared anchors (center/high-Eg/low-Eg) × 41-pt arc scans + 21-pt Eg
control + prominence (> 0.05 pp over ±2 neighbors) + ≤5 refinements × 9
pts; 450 solves (≤ 600 cap). Arc response at 5.5 nm sampling is smooth
broad oscillation (ranges 0.37–3.13 pp) with NO narrow-peak pathology:
only 2 qualifying peaks (hot/nom high-Eg anchor, both at 77 nm), each
re-confirmed best on a 9-pt ±11 nm refinement grid (2.75 nm resolution;
shift 0.0 nm, Δ0.00 pp — RESOLVED, trivially by determinism at the shared
center point, honestly noted). Surrogate RMSE on scans 0.18–0.56 (smooth
1-D structure is easy). Eg control: 7.5–11.1 pp ranges; interior maximum
nom @1.73 eV; near-boundary maximum conc @1.91 eV; hot monotonic. No
global-optimality claim: these are scanned candidates and locally
resolved maxima only. Missed-peak risk below 5.5 nm scale remains
unprobed (recorded limitation).

### 42.9 Candidate selection: ranking recovers on the slice (Phase 8)

Six methods (A random, B max-pred, C disagreement-UCB β=1.0, D diverse
top-quartile, E central-box max-pred, F local refinement σ=0.02),
pool 200, k=6, 3 seeds, 3 regimes — 324 L4 verifications, all proposals
verified, none promoted from prediction. Median best-verified PCE:

| Regime | A random | B max | C UCB | D diverse | E box | F local |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| conc | 20.37/18.89/22.45 | 20.37/20.03/22.45 | 20.37/20.03/22.45 | 20.37/18.89/22.45 | 19.35/17.28/18.63 | 21.37/17.44/22.45 |
| hot | 16.94/15.13/15.38 | 19.02/18.33/19.18 | 19.02/18.33/19.18 | 19.02/18.33/19.18 | 18.30/16.67/17.49 | 19.37/18.97/19.33 |
| nom | 18.87/20.93/19.29 | 22.27/21.36/22.25 | 22.27/21.36/22.25 | 22.27/20.66/22.25 | 21.02/20.84/19.78 | 22.37/21.05/22.43 |

**G_SELECT_REPLICATION: PASS 9/9** — median-guided best ≥ random best in
every regime-seed, 0 losses, under the literal predeclared median
definition. Strict per-method accounting is less rosy: E (support-
constrained) never finds the best (by design — its picks are 48/54
VALIDATED votes vs B's 41/54 with 6 OOD flags: the support/performance
tradeoff quantified); F wins outright 4/9 but collapses once (conc seed
2: 17.44 — argmax fragility, the model's best point verified poorly).
B/C never lose (9/9 ≥ random). **Fine ranking WORKS on the slice**:
Spearman 0.37–1.00 (mostly 0.5–0.9) vs V1.9-F's 0.03–0.94 collapse;
top-2 recovery mostly 0.5–1.0. Region-finding AND ranking are supported
on the slice with mandatory verification — a genuine advance over V1.9-F.

### 42.10 Validity map: two invalid mechanisms isolated

23 unique new invalids (all preserved with reasons): 20 slice rows with
rsh 51–105 (logz < 0.08) failing `electrical.range` (FF/PCE collapse) —
the log-uniform slice sampling EXPOSED a shunt-validity boundary at
rsh ≈ 100 (nom/hot; conc unaffected) that linear sampling never reached;
plus 3 high-rs/high-Rth combo rows failing `numerical.solve_completed`
(the V1.9-E thermal-stress pattern). Slice invalid rate 20/2016 ≈ 1%.
Invalid rows never train (status-aware selector) but the boundary region
(rsh 110–1000, steep recovery) is the accuracy bottleneck for both
models (§42.5). The valid region has a complex, mechanism-dependent shape
(shunt floor + thermal corner); uniform-prior sensitivity understates
low-end effects — a methodology lesson for future campaigns.

### 42.11 Cost, scaling verification, and warnings (Phases 9–10)

Conventions identical to V1.9-F (ratios vs median L4 = 43.0 ms, n=11,217;
means 46.1 ms). Slice GP (PCE-only, single estimator): fit 1.8–2.1 s;
single-point 0.24 ms = **168–180×** (the historical 10× single-point
target is exceeded 17× on this path — scope caveat: PCE-only inference,
not an 11-target bundle, which is NOT_BUILT; projected ~16×,
UNMEASURED); batch-256 0.007 ms/pt = **5900–6400×** amortized; OOD
indicators 2.6–2.8 ms/100 queries. Full bundle path 180.9 ms = 0.237×,
reproducing V1.9-F's 0.24× exactly (convention verified). Full refit
31.8 s; campaign 590.4 s; peak RSS 0.98 GiB. L4 verification was never
sacrificed for timing.

Scaling verification (Phase 9): the V1.9-F boxnorm correction behaves
identically in current code (raw GP still ties constant on slice data);
train/select/calibrate/predict/batch/serialization paths verified —
serialization round-trip (ET + boxnorm-GP, bit-identical predictions)
pinned by test; batch-vs-single identity pinned by V1.9-F tests;
fold-independent fixed transforms only (box/log); support uses the same
scaled coordinates as the slice models. Checklist recorded in results.

Warnings ledger: suite **5** (unchanged) — pinned to two tests in
`tests/test_v19_surrogate.py` (family-comparison toy fit: 3; synthetic
benchmarks: 2), all ARD-scale→4.0 / noise→1e-10 on synthetic data;
immaterial to production (software checks; bounds are production
settings, fixtures arbitrary — no change, rationale recorded). V1.9-G
slice fits: 2–4 ConvergenceWarnings per regime marking ARD pruning of
exactly the weak axes (urbach/si_eg/si_srv/Rth → 4.0 in fitted kernels);
verdict-robust (GP wins by 0.3–1.2 pp). Campaign stderr EMPTY. No
warning suppressed in production code; no blind limit increases.

### 42.12 Evidence artifacts and determinism (Phase 11)

| Artifact | Bytes | SHA-256 / fingerprint |
| --- | ---: | --- |
| `data/v19g_discovery_results.json` | 171,562 | file `bd43dcef…a973f`; physics digest `db2bd80c…eae4f` (run-2; varies with `*_s` benchmark timings, which the shared exclusion pattern does not cover — same known pattern as V1.9-E/F) |
| `data/v19g_new_rows.json.gz` | 6,849,002 | file `95551c26…2cd956` (per-row `runtime_s` varies); dataset fingerprint `654641ca…b15d0` (BIT-STABLE across 2 runs); physics digest `0c04be2d…0ab9` (BIT-STABLE across 2 runs) |

11,217 rows: 11,052 VALID, 23 INVALID (preserved with reasons), 142
DUPLICATE (1,562 output comparisons vs priors, maxdiff 0.0 —
bit-identical; arise from overlapping selection pools across
methods/seeds). Roles V19G_*; V1.9-E/F
artifacts untouched. Round-trip assertion (fingerprint recomputed from
file layout) passes inside the tool. A second full-campaign run
reproduced the dataset fingerprint bit-identically (run-2 file SHAs
above; science content identical).

### 42.13 Success criteria verdict (Phase 12)

Historical thresholds (unchanged, reported): PCE RMSE ≤ 0.25 — NOT_MET on
slice (0.51–0.61) and reference; single-point 10× — MET on PCE-only slice
inference (168–180×), NOT_MET on bundle path (0.237×, reproduced);
withheld recall 0.50 — NOT_MET (0.25–0.38); in-box FPR 0.10 — 1/3
(nominal only); conformal coverage 0.90 — slice radii 0.83–1.25 with
post-hoc final coverage 0.927/0.914/0.958 (conc/hot/nom; marginal
calibration holds, hot under-coverage fixed — diagnostic, not
predeclared as a criterion).
New predeclared criteria: G_SLICE_BEATS_FULL 3/3 PASS; G_SLICE_ERR 0/3
(narrow miss); G_OOD_RECALL 0/3 FAIL; G_OOD_FPR 1/3; G_SELECT_REPLICATION
9/9 PASS; G_SALTELLI_STABLE 1/3 (ranks stable, magnitudes not).
Exploratory: pairs INCONCLUSIVE; peaks 2/2 resolved (broad fringes);
ranking recovered (Spearman 0.37–1.0). INSUFFICIENT_DATA: none — every
reported rate rests on n ≥ 21 and every stratum on n ≥ 8.

### 42.14 Tests, files, guardrails, readiness

Final verification: `pytest` **232 passed, 1 skipped, 5 warnings** (205
pre-existing + 27 new in `tests/test_v19g_discovery.py`, all synthetic/
deterministic, warning-clean). `ci_checks.py` **6/6**. `ruff check` clean
on all created/modified files. `git diff --check` clean.

Files added: `apmt/surrogate/discovery.py` (protocol + helpers),
`tools/v19g_discovery_campaign.py` (8-step campaign),
`tests/test_v19g_discovery.py` (27 tests),
`data/v19g_discovery_results.json`, `data/v19g_new_rows.json.gz`.
No production file modified (campaign/models/engine untouched — the G
campaign only ADDS predeclared analysis layers).

Guardrails: APMT remains `BLOCKED_BY_BASELINE_VALIDATION`; the baseline
gate was not reopened. **0 new PCE claims promoted** (all candidate PCEs
are L4-verified computational probes). L5: NOT_RUN (no new L5 solves; L5
used nowhere in V1.9-G). No synthetic recovery presented as validation.
Physics untouched (digest `df691e7b…` reproduced). No 14-D global
optimization performed (all pools slice-restricted; no optimizer run).
Negative results preserved above (OOD failure, pair inconclusiveness,
criterion misses).

**V1.9-G readiness verdict: C — REDUCED_DIMENSION_SUPPORTED_WITH_L4_VERIFICATION.**
On the defined 9-D operating slice (fixed values §42.3): GP predictions
(0.51–0.61 pp RMSE) with working fine ranking and 9/9 region-finding are
a supported discovery prior; every candidate MUST be L4-verified;
predictions outside the slice (other fixed values, rsh ≲ 100 shunt floor,
withheld corners) are UNSUPPORTED — the OOD detector cannot be relied
upon to flag them. Outcomes A (not ready) is too harsh given slice
ranking/selection evidence; B understates ranking recovery; D
(candidate-ranking-supported) overstates given OOD blindness and 2×
error target. No outcome validates APMT.

**Five most consequential discoveries.** (1) The corrected GP, dense slice
data, and log scales deliver 0.51–0.61 pp with selection on validation
confirmed on final — the 14-D GP failure was data-geometry, not method.
(2) The full reference fails on the slice (1.7–4.1 pp) almost entirely
via log-rsh distribution shift (low-tertile RMSE up to 6.7, max err 13
pp) — training-distribution match dominates dimensionality. (3) OOD
ensemble recall 0.25–0.38 with NO median indicator separation: withheld
corners are geometrically undetectable at this density — a structural
negative. (4) Log-uniform sampling exposed a shunt-validity boundary
(rsh ≈ 100, electrical collapse) invisible to linear campaigns. (5) Fine
ranking recovers on the slice (Spearman 0.37–1.0, top-2 mostly 0.5–1.0)
vs V1.9-F's 0.03 collapse — rank quality is regime/density-dependent,
not a fixed model property.

**Five most important remaining limitations.** (1) Slice RMSE 0.51–0.61
(2× the 0.25 target) with 2.0–2.3 pp worst cases at the shunt boundary.
(2) No reliable OOD detector (recall ≤ 0.38; threshold transfer fails);
abstention remains the only guardrail. (3) Saltelli pairs inconclusive at
N=256 (sign flips); only V1.9-D's full-box pair stands; hot S1 sums > 1.
(4) Slice scope is narrow by construction (5 pinned values; shunt floor;
thermal corner unmapped within slice). (5) Peak probing stops at 5.5 nm
(arc) with 2.75 nm refinement; sub-scale structure unprobed; no 11-target
slice bundle exists (PCE-only).

V1.9-H candidates (all NOT_RUN): (1) converged-N (≥768, quasi-random)
central-box Saltelli for pairs; (2) shunt-boundary-aware slice campaign
(rsh floor ≥ 110 or boundary-adapted design); (3) 5-D ARD-core
hypothesis test (Eg/thickness/arc/rs/rsh) as a FRESH predeclared
campaign; (4) non-geometric OOD signals (physics-residual or
validity-classifier study); (5) full 11-target slice bundle with
guardrails + bundle-path timing.

## 43. V1.9-H — forensic audit: gate duality, repairs, calibration regeneration, solver mining, and campaign-staleness verdicts

Mission rule in force throughout: no threshold/tolerance weakening, no silent
changes, fitted/simulated values never presented as experimental, L4
authoritative for verification (L5 refinement/cross-check only), full history
preserved. All repairs below were reproduced before fixing and are pinned by
`tests/test_v19h_physics_repairs.py`; pre-fix numbers live on in git history,
never silently updated.

### 43.1 Gate duality resolved — 9/9 thresholds identical, no change

The two gate implementations were compared programmatically field by field:
`apmt/validation_gate.py` (V1.8 evaluator) and `apmt/validation/gate.py`
(V1.9 evaluator) carry **identical values on all 9 thresholds**. The V1.9
module adds only `version = "1.9-strict-v1.8-thresholds"` (a label, not a
loosening). G9 provenance coverage is present in V1.9 via `evaluate_gate` /
`audit_v18_gate_consistency`. The vocabularies differ cosmetically (DEFER vs
INCOMPLETE/DATA_REQUIRED) at equal strictness. No threshold was touched.

`tools/ci_checks.py` (with the S32-CI repair in the CI path) is 5/6: pins,
determinism, provenance (2/37), gate (FAIL-as-expected), and
artifact-consistency PASS; only git-clean fails, on deliberate uncommitted
research work. Determinism passes **without pymupdf installed**, proving the
S32-CI repair inside the CI path rather than around it.

### 43.2 Confirmed physics repairs (all pinned by test_v19h)

| ID | File | Defect (reproduced pre-fix) | Fix | Live impact |
|----|------|-----------------------------|-----|-------------|
| R1 | `apmt/device/recombination.py` | Radiative J0 inflated 1000x by a spurious extra `* 1e3` | Removed; cross-checked vs the independent `detailed_balance._emitted_current` path (residual ~1e-4 is grid convergence, not scale) | +0.389 V Voc @328 K (OLD fit) = 2kT·ln1000 signature |
| T21 | `apmt/device/tandem.py` (`_subcell_from_params`) | SRH J0 temperature-scaled TWICE (slab evaluated at T, then rescaled to T again) | Use the slab value at T directly; standalone scaler contract pinned for fitted-298 K use | x32 inflation @320 K bottom cell removed |
| U1 | `apmt/materials/perovskite.py` | Urbach-tail branch discontinuous at the matching edge | `/e` matching factor makes the branch continuous | Edge continuity restored |
| F1 | `apmt/device/tandem.py` (`solve_tandem_fast`) | `np.interp` tie-breaking on numerically flat J(V) returned the pad endpoint (V = -v_pad) instead of V(Jsc) = 0, poisoning the V(J) grid endpoint by ~250 mV | Exact-scalar repair for queries within jsc*1e-9 of Jsc | Extreme-shunt corners only |
| J-sens | `apmt/device/tandem.py` (`curve_metrics_by_current`) | Unbracketed 20 mV probe silently returned the bisection midpoint, fabricating sens = j_hi/0.04 (385.6 at the twin point) with a physical-sounding comment | Honest NaN + explicit `jsc_bias_sensitivity_bracketed` flag; matched tandems still report finite slope | Diagnostic only (reported, never used); twin point is unbracketed (mismatched) |
| Rs-sign | `apmt/device/subcell.py`, `apmt/device/tandem.py` (vectorised twin) | Junction bias used V - J·Rs, making series resistance *raise* the current | Vj = V + J·Rs (terminal plus resistive drop) | ZERO live impact: production builds use subcell rs = 0 (Rs lives at tandem level); latent path repaired |
| F-heat | `apmt/device/thermal.py` (`solve_equilibrium`) | `f_heat * absorbed - extracted` (full extracted power subtracted from fractioned absorbed) vs documented `f_heat * (absorbed - extracted)` | Parenthesisation per documentation | Identical at default f_heat = 1.0 |
| L5-spec | `apmt/multifidelity/levels.py` (`evaluate_with_options`) | Level's (possibly shifted) spectrum not passed down | Thread the level spectrum through, as documented | Numeric only at spectrum_shift != 0 |
| L5-doc | `apmt/multifidelity/levels.py` | Description claimed more than solver-grid convergence | Corrected to solver-grids-only wording | Docs only |
| tail-doc | `apmt/materials/silicon.py`, `apmt/optics/stack.py` | Si sub-gap tail (1200 nm / 18 nm) undocumented vs registry | Documented as NOT a registered parameter | Zero numeric |
| LHS-text | `apmt/sensitivity/lhs.py` | Stale Sobol-deferral method string | Fixed; verified unpinned (occurs only in historical `data/v19_mechanism_campaign.json`, zero test refs) | Future outputs only |
| pins-write | `tools/v19_calibrate_twin.py` (`write_pins`) | **Destructive rewrite**: dropped the pins-manifest `digests` section (engine physics digest), overwrote the note, reflowed indent 1->2 | Load-modify-write preserving unknown sections; `PINNED_ARTIFACTS` completed with `data/v19_thermal_investigation.json` | Manifest diff now 2 lines (calibration sha/bytes only); `--write` byte-determinism verified (identical sha across runs); `ci_checks` pins passes (8 hashes + 1 digest) |

Deliberately NOT changed: `apmt/ledger.py`'s V1.8-era docstring references
`tests/test_ledger_unchanged.py`, which no longer exists (live pins are
`tests/test_spectrum_known_answers.py` + `tests/test_provenance.py`). A
comment fix was attempted, tripped the v1.8-manifest verified-count test
(see 43.6), and was reverted: the docstring is a historical V1.8 statement
and stays verbatim. The stale reference is recorded here instead.

### 43.3 Fast-vs-reference solver mining (V1.9-C-era, old physics — historical)

`data/v19_engine_campaign.json` (reference_level L5): L4-vs-L5 max delta-PCE
7.45e-5 pp; 12/12 LOW-DIVERGENCE with predictive = true; oracle 12/12 within
tolerance, max deviation 8.6e-6 pp. Solver grids converged — consistent with
the corrected solver-grid-only L5 description (43.2). The oracle contract
held with ~100x margin pre-fix. This is solver-*consistency* evidence mined
from a historical campaign, not a physics result; post-repair agreement is
covered implicitly by the H repair tests (43.6), and a dedicated post-repair
L4/L5 campaign remains queued behind the frozen H protocol (43.5).

### 43.4 Calibration regeneration — CAL-STALE closed (gate stays closed)

Regenerated with current (fixed) physics via `tools/v19_calibrate_twin.py`
summary then `--write` (no `--profile`, matching the committed schema):

| Quantity | Old (committed, stale physics) | New (current physics) |
|---|---|---|
| Fit RMSE (arc/perov, pp) | 4.8 / 5.2 | **3.461 / 3.851** |
| Tandem PCE fitted / defaults (pp) | 21.02 / 17.91 | **29.3524 / 24.2348** |
| Fitted Jsc / Voc / dT | — | 18.9009 mA/cm2 / 1.8279 V / 12.15 K |
| Defaults Jsc / Voc / dT | — | 15.4228 mA/cm2 / 1.8250 V / 11.33 K |

New fit: arc 120.521 / perov 1024.353 / trap 9.8177; kappa 1475.5;
boundary_hits 2 (parasitic 60.0 and coll-top 1.0 still at bounds), flat 1.
Both blocks `energy_balance`. Disentanglement at defaults (retained
`thermal_model = "simple"` option): physics fixes **+5.2255 pp**
(17.9082 -> 23.1337) then closure default **+1.1011 pp** (-> 24.2348), exact
sum; OLD-fit row: physics +6.2336 pp, closure +1.2448 pp; refit contributes
+0.854 pp.

**Gate stays closed**: boundary_hits = 2 trips G8 (`boundary_hits_max = 0`).
The fitted 29.35% PCE is a MODEL-FIT pre-gate number — no claim of any kind.
It sits below the ~40%+ tandem radiative limit: no invariant violation, just
an unconverged-at-bounds fit the gate correctly refuses.

### 43.5 Campaign-staleness verdicts — E/F/G numbers superseded, methods stand

Physics-code digest (`_physics_code_digest`, 17 files incl. all repaired
physics): F/G committed data carry `df691e7b…`; the current tree computes
`888d1d8b…`. Row-level proof: 3/3 recomputed G nominal rows differ by
+4.6757/+5.4672/+6.1612 pp (R1 signature), 1/1 F row by +6.1021 pp. **The
E/F/G campaign data are pre-R1/T21/U1.** Consequences:

- Report sections 41–42 (V1.9-F/G outcomes): NUMBERS SUPERSEDED by the
  repairs; METHODS STAND (GP normalization correction is pure math; spatial
  protocol, discovery machinery, OOD framing are physics-version-agnostic and
  pinned by pure-data tests — 15 F + 27 G, all green).
- The G tool's digest gate (`tools/v19g_discovery_campaign.py::step_verify`,
  `assert committed["metadata"]["physics_source_digest"] == code_digest`)
  correctly REFUSES to build on the stale committed E artifact in the current
  tree. That assert firing is the provenance system working, not a bug.
- GAP (recorded for regen): the F tool's `_load_committed` checks
  fingerprints (integrity) but has NO digest gate (vintage) — a re-run now
  would silently mix old-E rows with new-physics F rows (detectable via
  per-row digests, but not blocked). Add the G-style digest assert at regen.
- Chain verdict: E (committed, stale) -> F -> G all require regeneration
  under the frozen H protocol. No protocol is committed yet, so per mission
  rule (tracks run ONLY under a frozen committed protocol with amendments
  recorded) there are NO runs in this turn. Queued: E regen (thin wrapper
  over `apmt.surrogate.campaign:run_campaign`), commit, F regen, commit, G
  regen. Workflow note: G loads `COMMITTED_V19F_ROWS`, so F data must be
  committed before G runs in a clean checkout (or make the paths CLI args).
- Commit decision: F/G tools + libraries (`apmt/surrogate/discovery.py`,
  `spatial.py`) + tests + report sections are committed (durable methods).
  The 4 stale data/results files (`data/v19f_new_rows.json.gz`,
  `data/v19f_reliability_results.json`, `data/v19g_new_rows.json.gz`,
  `data/v19g_discovery_results.json`) stay UNTRACKED: known-stale generated
  artifacts, reproducible via documented tool commands, self-labeling via
  their embedded `physics_source_digest != current`.

### 43.6 Test record (this turn)

- `tests/test_v19h_physics_repairs.py` (7 classes: R1/T21/U1/F1/J-sens/
  Rs-sign/F-heat): all green — each repair reproduced pre-fix against an
  independent implementation or closed form, then pinned.
- `tests/test_v19f_reliability.py` (15) + `tests/test_v19g_discovery.py`
  (27): pure-data/synthetic, all green, no physics solves.
- Full suite: **264 passed, 1 skipped** (`hzb_M2` 200-dpi re-render NOT
  VERIFIED — external PDF absent from checkout, as designed).
- Incident: a comment-only edit to `apmt/ledger.py` dropped the v1.8-manifest
  verified count 31 -> 30, tripping
  `test_v18_manifest_hash_defect_is_recorded_not_hidden` (`n_verified > 30`;
  the two defect-recording asserts still passed). Verified via a HEAD
  worktree that the delta was exactly that one file; reverted (43.2).
  STRUCTURAL WARNING: the count now sits at 31 against a `> 30` threshold —
  the next v1.8-pinned-file edit re-trips it. That threshold must NOT be
  silently weakened; if a future physics repair must touch a pinned file,
  escalate to the operator.

### 43.7 Commit record

Branch `arena/a6cb5ca0-solar` only (no main push, no PR). Commit `5d5811f`
takes the working tree to the audited state: all 43.2 repairs + tests, the
regenerated calibration + minimal pins diff, the F/G methods (tools, libs,
tests), and this report section. Merge `d47d991` folds in the remote F/G
stack (`bd6cb8a`..`7d50249`: methods identical to the local copies,
§§41–42 byte-identical, plus the 4 committed F/G data files); conflicts
(report append point, `.report_sha256`) resolved by taking the local
superset text and regenerating the sha. A follow-up commit corrects two
pre-merge wordings in this section (43.1 CI score, 43.5 data tracking
status) with amendments recorded here, not silently. Post-merge:
`ci_checks` 6/6, full suite 264 passed + 1 skipped (carried over — the
merge adds data files only, zero code delta vs `5d5811f`).

