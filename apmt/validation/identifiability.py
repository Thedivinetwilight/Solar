"""APMT V1.9 — evidence objects for gate checks G7 (resistance) and G8 (identifiability).

Audit item A requires the gate to consume *evidence* rather than bare scalars,
and audit item E requires that a number the caller chooses cannot silently
satisfy a check. Both objects below carry the full provenance of the numbers
they contain and are the only accepted inputs for G7/G8.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

EXTERNAL_METHODS = {
    "dark_jv_fit_to_measured_curves",
    "suns_voc",
    "jsc_voc",
    "four_point_probe",
    "tlm_contact_resistance",
    "impedance_spectroscopy",
    "electroluminescence_series_resistance",
}


@dataclass(frozen=True)
class ResistanceEvidence:
    """External Rs/Rsh evidence for gate G7."""

    method: str
    rs_ohm_cm2: Optional[float] = None
    rsh_ohm_cm2: Optional[float] = None
    uncertainty_rs_ohm_cm2: Optional[float] = None
    uncertainty_rsh_ohm_cm2: Optional[float] = None
    instrument: str = ""
    source_id: str = ""
    device_id: str = ""
    notes: str = ""

    def is_external(self) -> bool:
        """A model-fit parameter is not a measurement (gate G7 policy)."""
        return self.method in EXTERNAL_METHODS

    def has_value(self) -> bool:
        return self.rs_ohm_cm2 is not None or self.rsh_ohm_cm2 is not None

    def to_dict(self) -> dict:
        return {
            "method": self.method, "is_external": self.is_external(),
            "rs_ohm_cm2": self.rs_ohm_cm2, "rsh_ohm_cm2": self.rsh_ohm_cm2,
            "uncertainty_rs_ohm_cm2": self.uncertainty_rs_ohm_cm2,
            "uncertainty_rsh_ohm_cm2": self.uncertainty_rsh_ohm_cm2,
            "instrument": self.instrument, "source_id": self.source_id,
            "device_id": self.device_id, "notes": self.notes,
        }


@dataclass(frozen=True)
class IdentifiabilityEvidence:
    """Identifiability diagnostics of a fit, for gate G8."""

    condition_number: float
    boundary_hits: int
    n_parameters: int
    n_data_points: int
    singular_values: tuple = ()
    parameter_names: tuple = ()
    correlation_matrix: Optional[np.ndarray] = None
    profile_likelihood: dict = field(default_factory=dict)
    objective_value: float = float("nan")
    residual_rmse: float = float("nan")
    category: str = "MODEL-FIT (fitted to DIGITIZED evidence)"
    notes: str = ""

    @property
    def max_parameter_correlation(self) -> float:
        if self.correlation_matrix is None:
            return float("nan")
        c = np.asarray(self.correlation_matrix, dtype=float)
        if c.size <= 1:
            return 0.0
        off = c - np.diag(np.diag(c))
        return float(np.max(np.abs(off)))

    def unidentifiable_parameters(self, corr_threshold: float = 0.95) -> list:
        """Parameter pairs whose correlation exceeds the threshold."""
        if self.correlation_matrix is None:
            return []
        c = np.asarray(self.correlation_matrix, dtype=float)
        names = self.parameter_names or tuple(f"p{i}" for i in range(c.shape[0]))
        out = []
        for i in range(c.shape[0]):
            for j in range(i + 1, c.shape[0]):
                if abs(c[i, j]) >= corr_threshold:
                    out.append({"pair": (names[i], names[j]),
                                "correlation": float(c[i, j])})
        return out

    def flat_directions(self, rel_threshold: float = 1e-3) -> int:
        """Number of singular values below ``rel_threshold`` * the largest one."""
        if not self.singular_values:
            return 0
        s = np.asarray(self.singular_values, dtype=float)
        return int(np.sum(s < rel_threshold * s[0]))

    def to_dict(self) -> dict:
        return {
            "condition_number": float(self.condition_number),
            "boundary_hits": int(self.boundary_hits),
            "n_parameters": int(self.n_parameters),
            "n_data_points": int(self.n_data_points),
            "degrees_of_freedom": int(self.n_data_points - self.n_parameters),
            "singular_values": [float(v) for v in self.singular_values],
            "flat_directions": self.flat_directions(),
            "parameter_names": list(self.parameter_names),
            "max_parameter_correlation": self.max_parameter_correlation,
            "unidentifiable_pairs": self.unidentifiable_parameters(),
            "objective_value": float(self.objective_value),
            "residual_rmse": float(self.residual_rmse),
            "category": self.category,
            "notes": self.notes,
        }
