"""APMT V1.9 — mechanism factorial design and interaction analysis.

The APMT mechanism set is modelled as three physical toggles whose "ON" levels
are explicit, registered parameters:

    A  optical management     -> collection_efficiency_top/bottom and light trapping
    B  photon recycling       -> photon_recycling_gain_top (+ luminescent coupling)
    C  thermal management     -> thermal_management_gain (reduces junction heating)

The exploration is a 2^3 factorial in (A, B, C) plus a dose-response scan for
each mechanism. For each configuration the *direct* effect and the *interaction*
effects are computed on the standard definitions:

    E_A  = PCE(A+B-C-) - PCE(A-B-C-)                       (direct effect of A)
    E_AB = [PCE(A+B+) - PCE(A+B-)] - [PCE(A-B+) - PCE(A-B-)]  (2-way interaction)

Every result is labelled PRE-GATE / MODEL-OBSERVED / EXPLORATORY: it is a
statement about *this model configuration*, never about the real device, and it
is only meaningful once the experimental gate opens (which it has not).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Callable, Dict, Optional, Sequence

import numpy as np

from ..device.tandem import evaluate_tandem
from ..params.registry import ParamSet


@dataclass(frozen=True)
class Mechanism:
    """One mechanism: its name and the parameter mapping for ON/OFF."""

    name: str
    label: str
    on: Dict[str, float]
    off: Dict[str, float]
    rationale: str = ""

    def apply(self, base: ParamSet, active: bool) -> ParamSet:
        return base.with_mapping(self.on if active else self.off)


DEFAULT_MECHANISMS = (
    Mechanism(
        "A", "optical management",
        on={"collection_efficiency_top": 1.0, "collection_efficiency_bottom": 1.0,
            "silicon_light_trapping": 4.0},
        off={"collection_efficiency_top": 0.98, "collection_efficiency_bottom": 0.98,
             "silicon_light_trapping": 1.0},
        rationale=("front/rear optical management: perfect carrier collection from "
                   "absorbed photons and a textured rear (path enhancement 4). "
                   "Exploratory design intent, not a measured device state."),
    ),
    Mechanism(
        "B", "photon recycling",
        on={"photon_recycling_gain_top": 5.0},
        off={"photon_recycling_gain_top": 0.0},
        rationale=("top-cell radiative-lifetime enhancement by re-absorption of "
                   "emitted photons (5x, mid-range of the registered 0-20 scale)."),
    ),
    Mechanism(
        "C", "thermal management",
        on={"thermal_management_gain": 0.6},
        off={"thermal_management_gain": 0.0},
        rationale=("60 % reduction of the junction-to-mount areal thermal "
                   "resistance relative to the registered 0.3 K cm^2 / mW default."),
    ),
)


def evaluate_configuration(base: ParamSet, mechanisms: Sequence[Mechanism],
                           active: Dict[str, bool], model_form: str = "IQE-M1") -> dict:
    """Evaluate the tandem with the given mechanism combination active."""
    ps = base
    for m in mechanisms:
        ps = m.apply(ps, bool(active.get(m.name, False)))
    res = evaluate_tandem(ps, model_form=model_form)
    overrides = {k: float(ps[k]) for m in mechanisms for k in m.on}
    return {"pce_pct": float(res.pce_pct), "jsc": float(res.jsc_ma_cm2),
            "voc": float(res.voc_v), "ff": float(res.ff),
            "mismatch_ratio": float(res.current_matching_ratio),
            "junction_t_k": float(res.detail["thermal"]["junction_k"]),
            "mechanism_parameter_values": overrides, "active": dict(active)}


def full_factorial(base: Optional[ParamSet] = None,
                   mechanisms: Sequence[Mechanism] = DEFAULT_MECHANISMS,
                   model_form: str = "IQE-M1") -> dict:
    """2^n factorial across the mechanisms + direct and interaction effects."""
    base = base or ParamSet.defaults()
    names = [m.name for m in mechanisms]
    cells = {}
    for bits in product([False, True], repeat=len(names)):
        active = dict(zip(names, bits))
        key = "".join(n if a else "-" for n, a in active.items())
        cells[key] = evaluate_configuration(base, mechanisms, active, model_form)

    baseline = cells["-" * len(names)]["pce_pct"]

    def pce(key: str) -> float:
        return cells[key]["pce_pct"]

    def flip(key: str, name: str) -> str:
        """Toggle one mechanism bit in a configuration key."""
        i = names.index(name)
        chars = list(key)
        chars[i] = "-" if chars[i] == name else name
        return "".join(chars)

    direct = {}
    for n in names:
        on = flip("-" * len(names), n)
        direct[n] = pce(on) - baseline

    interactions = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            k00 = "-" * len(names)
            k10 = flip(k00, a)
            k01 = flip(k00, b)
            k11 = flip(flip(k00, a), b)
            interactions[f"{a}x{b}"] = (pce(k11) - pce(k10)) - (pce(k01) - pce(k00))
    triple = None
    if len(names) == 3:
        a, b, c = names
        k000 = "-" * 3
        k100, k010, k001 = flip(k000, a), flip(k000, b), flip(k000, c)
        k110 = flip(flip(k000, a), b)
        k101 = flip(flip(k000, a), c)
        k011 = flip(flip(k000, b), c)
        k111 = flip(k101, b)
        triple = (((pce(k111) - pce(k011)) - (pce(k101) - pce(k001)))
                  - ((pce(k110) - pce(k010)) - (pce(k100) - pce(k000))))

    return {
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY",
        "design": "2^%d factorial over mechanism toggles" % len(names),
        "model_form": model_form,
        "mechanisms": {m.name: {"label": m.label, "on": m.on, "off": m.off,
                                "rationale": m.rationale} for m in mechanisms},
        "cells": cells,
        "baseline_pce_pct": baseline,
        "best_pce_pct": max(c["pce_pct"] for c in cells.values()),
        "direct_effects_pp": direct,
        "interaction_effects_pp": interactions,
        "three_way_interaction_pp": triple,
        "n_solves": len(cells),
    }


def dose_response(parameter: str, values: Sequence[float],
                  base: Optional[ParamSet] = None,
                  model_form: str = "IQE-M1") -> list:
    """Dose-response of the model to one mechanism parameter."""
    base = base or ParamSet.defaults()
    key = parameter
    vals = list(values)
    out = []
    for v in vals:
        ps = base.with_mapping({key: float(v)})
        r = evaluate_tandem(ps, model_form=model_form)
        out.append({"parameter": key, "value": float(v), "pce_pct": r.pce_pct,
                    "voc": r.voc_v, "jsc": r.jsc_ma_cm2, "ff": r.ff,
                    "junction_t_k": r.detail["thermal"]["junction_k"]})
    return out
