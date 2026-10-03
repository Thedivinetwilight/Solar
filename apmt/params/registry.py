"""APMT V1.9 — parameter registry: the single source of truth for every number.

Directive §4/§7: "Everything must be parameterized. No magic numbers hidden
inside scripts." And §7: "Every parameter range needs classification:
literature-supported | experimentally constrained | model-assumed | exploratory."

This module provides

* :class:`ParamSpec` — one named, unit-qualified parameter with a default,
  a physically admissible interval, a provenance category, a range
  classification and a source note;
* :class:`ParamSet` — an immutable bundle of parameter values that all model
  layers consume, convertible to/from vectors for sampling and optimisation.

Any model module that needs a numeric constant must obtain it from a
ParamSet; :func:`validate_paramset` fails if a value leaves its admissible
interval, and :meth:`ParamSet.from_vector` fails on unregistered names.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np

from ..provenance import ProvenanceCategory


class RangeClass(str, Enum):
    """How well the admissible interval itself is supported by evidence."""

    LITERATURE_SUPPORTED = "LITERATURE-SUPPORTED"
    EXPERIMENTALLY_CONSTRAINED = "EXPERIMENTALLY-CONSTRAINED"
    MODEL_ASSUMED = "MODEL-ASSUMED"
    EXPLORATORY = "EXPLORATORY"
    DATA_REQUIRED = "DATA_REQUIRED"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    unit: str
    default: float
    low: float
    high: float
    category: ProvenanceCategory
    range_class: RangeClass
    description: str
    source: str = ""
    uncertainty: float = 0.0        # 1-sigma, 0 => unassessed
    fixed: bool = False             # structural/fixed quantity, never a fit variable

    def clip(self, x: float) -> float:
        return float(min(max(float(x), self.low), self.high))

    def in_bounds(self, x: float, tol: float = 0.0) -> bool:
        return self.low - tol <= float(x) <= self.high + tol


def _p(*args, **kwargs) -> ParamSpec:
    return ParamSpec(*args, **kwargs)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_SPECS: Tuple[ParamSpec, ...] = (
    # ---- spectral / illumination -------------------------------------------
    _p("temperature_k", "K", 298.15, 220.0, 400.0,
       ProvenanceCategory.EXPERIMENTALLY_CONSTRAINED, RangeClass.EXPERIMENTALLY_CONSTRAINED,
       "Cell temperature of the tandem stack",
       "standard reporting condition 25 degC; range covers -50 to +127 degC "
       "cell temperature used in IEC 61215 thermal cycling",
       uncertainty=0.5),
    _p("irradiance_suns", "suns", 1.0, 0.01, 100.0,
       ProvenanceCategory.EXPERIMENTALLY_CONSTRAINED, RangeClass.EXPERIMENTALLY_CONSTRAINED,
       "Broadband concentration factor relative to AM1.5G one sun",
       "one-sun AM1.5G default; upper bound = 100x typical CPV concentration",
       uncertainty=0.02),
    _p("spectrum_shift_nm", "nm", 0.0, -40.0, 40.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Rigid wavelength-axis shift applied to the reference spectrum (spectral "
       "mismatch proxy for LEDs / field spectra)",
       "exploratory; not a measured spectral mismatch"),

    # ---- perovskite top cell ----------------------------------------------
    _p("perovskite_eg_ev", "eV", 1.68, 1.40, 2.00,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Perovskite absorber bandgap at 298.15 K",
       "Al-Ashouri 2020 certified champion uses a 1.68 eV triple-cation "
       "perovskite (main text); 1.40-2.00 eV spans the tandem-relevant "
       "single-junction perovskite range",
       uncertainty=0.01),
    _p("perovskite_thickness_nm", "nm", 500.0, 150.0, 1500.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Perovskite absorber thickness",
       "V1.2.2 calibration hit the 1000 nm upper bound -> the interval here is "
       "explicitly an exploratory design interval, NOT a measurement",
       uncertainty=0.0),
    _p("perovskite_urbach_mev", "meV", 20.0, 5.0, 60.0,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Urbach tail energy of the perovskite absorber",
       "reported Urbach energies for triple-cation perovskites are 12-25 meV; "
       "interval widened to 5-60 meV to bound the sub-gap absorption effect",
       uncertainty=5.0),
    _p("perovskite_absorption_alpha_ev", "1/cm", 5.0e4, 1.0e4, 1.2e5,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Above-gap absorption strength: alpha(E) = alpha_Eg * sqrt((E-Eg)/1 eV) "
       "for E > Eg",
       "MAPbI3-type absorption coefficients reach 1e5 cm^-1 above the gap; the "
       "exact prefactor is a dispersion-model shape parameter",
       uncertainty=1.0e4),
    _p("perovskite_n_inf", "1", 2.35, 2.0, 2.8,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "High-frequency refractive-index scale of the perovskite (Wemple-"
       "DiDomenico single-oscillator form)",
       "perovskite films show n = 2.3-2.6 in the near-IR",
       uncertainty=0.1),
    _p("perovskite_oscillator_ev", "eV", 1.60, 0.8, 3.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.MODEL_ASSUMED,
       "Wemple-DiDomenico oscillator energy offset above Eg",
       "shape parameter of the dispersion model; not separately measured"),

    # ---- silicon bottom cell ----------------------------------------------
    _p("silicon_thickness_um", "um", 260.0, 60.0, 400.0,
       ProvenanceCategory.EXPERIMENTALLY_CONSTRAINED, RangeClass.EXPERIMENTALLY_CONSTRAINED,
       "Silicon wafer thickness",
       "Al-Ashouri 2020 champion: 260 um n-type FZ SHJ silicon (main text)",
       uncertainty=10.0),
    _p("silicon_eg_ev", "eV", 1.121, 1.10, 1.16,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Silicon bandgap at 0 K (Varshni extrapolation basis)",
       "Si Eg(0) = 1.170 eV with Varshni alpha=4.73e-4 eV/K, beta=636 K gives "
       "1.121 eV at 298 K",
       uncertainty=0.003),
    _p("silicon_light_trapping", "1", 1.0, 1.0, 30.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Effective optical path-length enhancement factor of the silicon "
       "(1 = single pass, 4n^2 ~ 50 = ideal Lambertian)",
       "exploratory optical-management parameter; the planar-front champion is "
       "not a fully textured device",
       uncertainty=0.0),
    _p("silicon_srv_cm_s", "cm/s", 10.0, 0.1, 1000.0,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Effective surface recombination velocity of the silicon bottom cell",
       "SHJ passivation reaches < 10 cm/s; poor contacts exceed 100 cm/s",
       uncertainty=5.0),
    _p("silicon_bulk_lifetime_ms", "ms", 5.0, 0.05, 100.0,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Effective bulk lifetime of the silicon absorber",
       "FZ n-type Si used in the champion has ms-scale lifetimes",
       uncertainty=2.0),

    # ---- recombination / electrical ---------------------------------------
    _p("radiative_efficiency_top", "1", 0.02, 1e-4, 1.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "External radiative efficiency (ERE) of the perovskite top cell",
       "representative device PLQY 0.02% (Al-Ashouri Fig. 5) is the low end; "
       "photon-recycling-assisted cells reach > 1%",
       uncertainty=0.005),
    _p("radiative_efficiency_bottom", "1", 1.0e-4, 1e-6, 1.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "External radiative efficiency (ERE) of the silicon bottom cell",
       "representative device PLQY 1.5% for Si at low injection; effective ERE "
       "under one-sun tandem operation is much lower",
       uncertainty=5e-5),
    _p("ideality_top", "1", 1.45, 1.0, 2.5,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.MODEL_ASSUMED,
       "Diode ideality factor of the perovskite subcell",
       "perovskite SRH recombination commonly gives n = 1.3-1.8"),
    _p("ideality_bottom", "1", 1.05, 1.0, 2.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.MODEL_ASSUMED,
       "Diode ideality factor of the silicon subcell",
       "well-passivated SHJ Si is close to unity"),
    _p("rs_ohm_cm2", "ohm*cm^2", 1.5, 0.0, 20.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "External series resistance of the two-terminal tandem",
       "DATA_REQUIRED for the champion device (gate G7): no external Rs "
       "measurement exists, so this is an explicitly exploratory interval",
       uncertainty=0.5),
    _p("rsh_ohm_cm2", "ohm*cm^2", 3000.0, 50.0, 1e6,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Shunt resistance of the two-terminal tandem",
       "DATA_REQUIRED (gate G7)"),
    _p("luminescent_coupling_top_to_bottom", "1", 0.0, 0.0, 0.5,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Fraction of top-cell radiative recombination photons that reach and "
       "are collected by the silicon bottom cell (luminescent coupling)",
       "mechanism B (photon recycling / optical coupling) parameter"),
    _p("photon_recycling_gain_top", "1", 0.0, 0.0, 20.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Effective radiative-lifetime enhancement of the top cell due to "
       "photon recycling (multiplicative on the radiative lifetime)",
       "mechanism B parameter; ideal planar recycling can exceed 10x, realistic "
       "textured stacks are much lower"),
    _p("arc_thickness_nm", "nm", 100.0, 0.0, 220.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Single-layer MgF2 anti-reflection coating thickness (n = 1.38). "
       "Mechanism A (optical management) design variable.",
       "the champion stack uses a LiF/MgF2 front coating; the exact thickness "
       "is NOT available in the primary source -> exploratory design variable, "
       "not a measurement"),
    _p("parasitic_layer_thickness_nm", "nm", 15.0, 0.0, 60.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Equivalent thickness of the lossy front transport/TCO layer "
       "(fixed n = 1.9, k = 0.05); mechanism A loss channel",
       "parasitic absorption is required by the optical budget but its exact "
       "magnitude is DATA_REQUIRED"),
    _p("collection_efficiency_top", "1", 0.98, 0.6, 1.0,
       ProvenanceCategory.MODEL_FIT, RangeClass.MODEL_ASSUMED,
       "Collection efficiency (IQE plateau) of the perovskite top cell",
       "IQE-model M1 parameter; the source reports EQE only, so the IQE split "
       "is a model assumption"),
    _p("collection_efficiency_bottom", "1", 0.98, 0.6, 1.0,
       ProvenanceCategory.MODEL_FIT, RangeClass.MODEL_ASSUMED,
       "Collection efficiency (IQE plateau) of the silicon bottom cell",
       "IQE-model M1 parameter"),
    _p("collection_length_top_nm", "nm", 900.0, 100.0, 5000.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Effective collection length of the perovskite (IQE model M2: "
       "IQE = alpha*L/(alpha*L + 1))",
       "IQE-model M2 parameter used for the model-form robustness test"),
    _p("collection_length_bottom_nm", "nm", 400000.0, 2000.0, 2.0e6,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Effective collection length of the silicon bottom cell (IQE model M2)",
       "the effective diffusion length of the SHJ silicon exceeds the wafer "
       "thickness, so the NIR EQE drop is dominated by absorption depth and "
       "rear optics"),

    # ---- thermal -----------------------------------------------------------
    _p("eg_temperature_coeff_ev_k", "eV/K", -3.0e-4, -6.0e-4, -1.0e-4,
       ProvenanceCategory.LITERATURE_DERIVED, RangeClass.LITERATURE_SUPPORTED,
       "Linear temperature coefficient of the perovskite bandgap",
       "reported dEg/dT for triple-cation perovskites is -0.25 to -0.45 meV/K",
       uncertainty=1.0e-4),
    _p("thermal_resistance_k_cm2_w", "K*cm^2/mW", 8.0, 1.0, 40.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Areal thermal resistance from the junction to the mount",
       "mechanism C (thermal management) parameter"),
    _p("thermal_management_gain", "1", 0.0, 0.0, 1.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Fractional reduction of the junction-to-mount thermal resistance "
       "attributed to the thermal-management element (mechanism C)",
       "mechanism C parameter"),
    _p("absorption_heat_fraction", "1", 1.0, 0.0, 1.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.MODEL_ASSUMED,
       "Fraction of absorbed (non-electrical) power that becomes heat rather "
       "than being re-emitted (energy balance coupling)",
       "conservative default 1.0 = all sub-bandgap/non-collected power is heat"),

    # ---- interfaces --------------------------------------------------------
    _p("interface_loss_top_ma_cm2", "mA/cm^2", 0.0, 0.0, 2.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Current-density loss at the perovskite/transport-layer interface "
       "(collection loss)",
       "interface recombination proxy"),
    _p("interconnect_resistance_ohm_cm2", "ohm*cm^2", 0.0, 0.0, 5.0,
       ProvenanceCategory.MODEL_ASSUMED, RangeClass.EXPLORATORY,
       "Recombination/interconnection resistance between subcells (adds to Rs)",),
)

REGISTRY: Mapping[str, ParamSpec] = MappingProxyType({s.name: s for s in _SPECS})

# Sanity: the registry itself must be internally consistent.
for _s in _SPECS:
    assert _s.low <= _s.default <= _s.high, f"default outside bounds for {_s.name}"
assert len(REGISTRY) == len(_SPECS), "duplicate parameter names in registry"


def spec(name: str) -> ParamSpec:
    if name not in REGISTRY:
        raise KeyError(
            f"parameter {name!r} is not registered; add it to apmt.params.registry "
            f"with an explicit provenance category and range classification"
        )
    return REGISTRY[name]


def all_specs() -> Tuple[ParamSpec, ...]:
    return _SPECS


def spec_table() -> list:
    """Flat table of the registry (used by reports and CI checks)."""
    return [
        {
            "name": s.name, "unit": s.unit, "default": s.default,
            "low": s.low, "high": s.high,
            "category": s.category.value, "range_class": s.range_class.value,
            "uncertainty": s.uncertainty, "fixed": s.fixed,
            "source": s.source, "description": s.description,
        }
        for s in _SPECS
    ]


@dataclass(frozen=True)
class ParamSet:
    """Immutable parameter bundle consumed by every model layer."""

    values: Mapping[str, float]

    # -- construction -------------------------------------------------------
    @staticmethod
    def defaults(**overrides: float) -> "ParamSet":
        base = {s.name: s.default for s in _SPECS}
        base.update(overrides)
        return ParamSet(MappingProxyType(base)).validated()

    @staticmethod
    def from_mapping(m: Mapping[str, float]) -> "ParamSet":
        base = {s.name: s.default for s in _SPECS}
        for k, v in m.items():
            spec(k)
            base[k] = float(v)
        return ParamSet(MappingProxyType(base)).validated()

    # -- access -------------------------------------------------------------
    def __getitem__(self, name: str) -> float:
        return float(self.values[name])

    def get(self, name: str, default: float | None = None) -> float:
        return float(self.values.get(name, default)) if default is not None else float(self.values[name])

    def names(self) -> Tuple[str, ...]:
        return tuple(self.values.keys())

    def validated(self) -> "ParamSet":
        validate_paramset(self)
        return self

    def with_updates(self, **updates: float) -> "ParamSet":
        return self.with_mapping(updates)

    def with_mapping(self, updates: Mapping[str, float]) -> "ParamSet":
        base = dict(self.values)
        for k, v in updates.items():
            spec(k)
            base[k] = float(v)
        return ParamSet(MappingProxyType(base)).validated()

    # -- vector interface (sampling / optimisation) -------------------------
    def to_vector(self, names: Sequence[str] | None = None) -> np.ndarray:
        names = tuple(names) if names is not None else self.names()
        return np.array([self.values[n] for n in names], dtype=float)

    @staticmethod
    def from_vector(names: Sequence[str], x: Sequence[float],
                    base: "ParamSet | None" = None) -> "ParamSet":
        base = base or ParamSet.defaults()
        updates = {n: float(v) for n, v in zip(names, x)}
        return base.with_mapping(updates)

    def to_dict(self) -> Dict[str, float]:
        return {k: float(v) for k, v in self.values.items()}


def validate_paramset(ps: ParamSet) -> None:
    """Fail loudly if any value leaves its admissible interval."""
    bad = []
    for name, value in ps.values.items():
        s = spec(name)
        if not np.isfinite(value):
            bad.append(f"{name}={value!r} not finite")
        elif not s.in_bounds(value, tol=1e-12):
            bad.append(f"{name}={value!r} outside [{s.low}, {s.high}] ({s.unit})")
    if bad:
        raise ValueError("invalid ParamSet: " + "; ".join(bad))


def vector_names() -> Tuple[str, ...]:
    return tuple(s.name for s in _SPECS)


def sample_bounds(names: Iterable[str]) -> Tuple[np.ndarray, np.ndarray]:
    names = tuple(names)
    lo = np.array([spec(n).low for n in names], dtype=float)
    hi = np.array([spec(n).high for n in names], dtype=float)
    return lo, hi
