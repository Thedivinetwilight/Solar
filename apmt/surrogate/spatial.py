"""V1.9-F predeclared spatial validation protocol.

This module declares — before any V1.9-F model evaluation — how spatial
generalization is measured.  Nothing here is tuned to surrogate errors.

1. DISTANCE METRIC (primary): Euclidean distance in verified-box-normalized
   coordinates (each axis mapped to [0, 1] by the V1.9-D shared verified box).
   This is the same metric as the V1.9-E support detector, so V1.9-F spatial
   numbers are directly comparable to V1.9-E support numbers.  Known
   limitation (stated, not fixed, here): axes with very different physical
   spans (e.g. ``rsh_ohm_cm2`` spanning 50..1e6 vs ``silicon_eg_ev``
   spanning 1.10..1.16) contribute equally per normalized unit.  A
   log-spanned sensitivity analysis is NOT added post-hoc; any future metric
   change must be declared before its evaluation campaign.

2. BUFFER RULE (adaptive, training-geometry only): the spatial buffer radius
   for a scope/regime is the MEDIAN leave-one-out nearest-neighbor distance
   of its TRAINING design in normalized coordinates.  No evaluation labels
   enter the rule.  Rationale: a holdout point farther from every training
   point than a typical training point is from its nearest training neighbor
   is spatially separated from the fit; a closer point is an interpolation
   probe.  Exact ties (distance == buffer) count as SEPARATED.

3. STRATIFICATION (no data dropped): evaluation sets are stratified into
   INTERPOLATION (d < buffer) and SEPARATED (d >= buffer) and metrics are
   reported for both strata plus the full set, with counts.  A stratum with
   fewer than 8 points is reported as INSUFFICIENT (counts only, no error
   metrics), never silently merged.

4. BLOCK RULE (axis slabs, declared here): the withheld spatial blocks are
   the ``perovskite_eg_ev`` (design axis 0) quartile slabs LOW {z0 < 0.25}
   and HIGH {z0 > 0.75}.  Axis 0 is chosen because it is the first design
   axis and the axis of the V1.9-E withheld corner and optimum/interaction
   slices — not because of any inspected surrogate error map.  Block-trained
   diagnostic models are tested ONLY on rows whose role was unused in their
   fit (VALIDATION-role rows for the diagnostic refit; FINAL_HOLDOUT rows
   for the no-refit full-model probe).  FINAL-holdout rows are never used to
   fit or select any V1.9-F model.

5. NEW WITHHELD CORNERS (V1.9-F OOD evaluation): the three Eg/thickness
   extreme corners not tested in V1.9-E, as normalized-box fractions::

       V19F_CORNER_A_LOW_LOW   z0 <= 0.10, z1 <= 0.10
       V19F_CORNER_B_HIGH_LOW  z0 >= 0.90, z1 <= 0.10
       V19F_CORNER_C_LOW_HIGH  z0 <= 0.10, z1 >= 0.90

   (V1.9-E tested z0 >= 0.90, z1 >= 0.90.)  All other axes span the full
   verified box.  The FROZEN V1.9-E support thresholds evaluate these
   corners; no V1.9-F OOD label tunes any threshold.

6. ROLE DISCIPLINE: V1.9-F reuses V1.9-E role labels.  Refits use TRAIN /
   ADAPTIVE_TRAIN only (plus OPTIMUM_TRAIN / INTERACTION_TRAIN inside their
   scopes).  No FINAL-holdout, calibration, or OOD row changes role.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SPATIAL_PROTOCOL_VERSION = "v19f-spatial-protocol/1.0"

MIN_STRATUM_POINTS = 8

# Predeclared block axis: first design axis (perovskite_eg_ev).
BLOCK_AXIS_INDEX = 0
BLOCK_LOW_MAX = 0.25
BLOCK_HIGH_MIN = 0.75

# Predeclared new-corner boxes as (axis0_min, axis0_max, axis1_min, axis1_max)
# in verified-box-normalized coordinates.
NEW_CORNER_BOXES = {
    "V19F_CORNER_A_LOW_LOW": (0.00, 0.10, 0.00, 0.10),
    "V19F_CORNER_B_HIGH_LOW": (0.90, 1.00, 0.00, 0.10),
    "V19F_CORNER_C_LOW_HIGH": (0.00, 0.10, 0.90, 1.00),
}
V19E_CORNER_BOX = (0.90, 1.00, 0.90, 1.00)

CANDIDATE_SELECTION_METHODS = (
    "max_predicted_pce",
    "uncertainty_aware_disagreement_ucb",
    "diverse_top_quartile",
    "random_pool_baseline",
)


def training_buffer_radius(X_train_normalized: np.ndarray) -> float:
    """Median leave-one-out nearest-neighbor distance of the training design.

    Uses TRAINING geometry only; evaluation labels never enter the rule.
    """
    from .domain import leave_one_out_distances

    z = np.asarray(X_train_normalized, float)
    if z.ndim != 2 or len(z) < 2:
        raise ValueError("training design must be a matrix with >= 2 rows")
    return float(np.median(leave_one_out_distances(z)))


def distance_to_training(X_eval_normalized: np.ndarray,
                         X_train_normalized: np.ndarray) -> np.ndarray:
    """Nearest-training distance for each evaluation row (normalized coords)."""
    from .domain import nearest_distances

    return nearest_distances(np.asarray(X_eval_normalized, float),
                             np.asarray(X_train_normalized, float))


def stratify_by_buffer(distances: np.ndarray, buffer: float) -> dict:
    """Split evaluation-row indices into INTERPOLATION / SEPARATED strata."""
    d = np.asarray(distances, float).reshape(-1)
    if not np.all(np.isfinite(d)):
        raise ValueError("distances must be finite")
    if not np.isfinite(buffer) or buffer < 0:
        raise ValueError("buffer must be a finite nonnegative radius")
    separated = d >= buffer  # exact ties count as separated (declared above)
    return {
        "protocol": SPATIAL_PROTOCOL_VERSION,
        "buffer": float(buffer),
        "n": len(d),
        "n_interpolation": int(np.sum(~separated)),
        "n_separated": int(np.sum(separated)),
        "interpolation_index": np.flatnonzero(~separated).tolist(),
        "separated_index": np.flatnonzero(separated).tolist(),
    }


def summarize_distances(distances: np.ndarray) -> dict:
    """Distribution summary of train-to-evaluation distances."""
    d = np.asarray(distances, float).reshape(-1)
    if len(d) == 0 or not np.all(np.isfinite(d)):
        raise ValueError("distances must be a nonempty finite vector")
    return {
        "n": len(d),
        "min": float(np.min(d)),
        "q10": float(np.quantile(d, 0.10)),
        "q25": float(np.quantile(d, 0.25)),
        "median": float(np.median(d)),
        "q75": float(np.quantile(d, 0.75)),
        "q90": float(np.quantile(d, 0.90)),
        "max": float(np.max(d)),
        "mean": float(np.mean(d)),
    }


@dataclass(frozen=True)
class BlockAssignment:
    """Which rows fall in the predeclared axis-quartile slabs."""

    low_slab_index: tuple[int, ...]
    high_slab_index: tuple[int, ...]
    interior_index: tuple[int, ...]

    def as_dict(self) -> dict:
        return {
            "protocol": SPATIAL_PROTOCOL_VERSION,
            "axis_index": BLOCK_AXIS_INDEX,
            "low_slab": f"z{BLOCK_AXIS_INDEX} < {BLOCK_LOW_MAX}",
            "high_slab": f"z{BLOCK_AXIS_INDEX} > {BLOCK_HIGH_MIN}",
            "n_low": len(self.low_slab_index),
            "n_high": len(self.high_slab_index),
            "n_interior": len(self.interior_index),
            "low_slab_index": list(self.low_slab_index),
            "high_slab_index": list(self.high_slab_index),
            "interior_index": list(self.interior_index),
        }


def assign_axis_blocks(X_normalized: np.ndarray) -> BlockAssignment:
    """Assign rows to the predeclared LOW/HIGH/interior axis slabs."""
    z = np.asarray(X_normalized, float)
    if z.ndim != 2 or z.shape[1] <= BLOCK_AXIS_INDEX:
        raise ValueError("design matrix lacks the predeclared block axis")
    axis = z[:, BLOCK_AXIS_INDEX]
    low = tuple(int(i) for i in np.flatnonzero(axis < BLOCK_LOW_MAX))
    high = tuple(int(i) for i in np.flatnonzero(axis > BLOCK_HIGH_MIN))
    interior = tuple(int(i) for i in np.flatnonzero(
        (axis >= BLOCK_LOW_MAX) & (axis <= BLOCK_HIGH_MIN)))
    return BlockAssignment(low, high, interior)


def in_normalized_box(X_normalized: np.ndarray, box: tuple[float, ...]) -> np.ndarray:
    """Mask rows inside a normalized corner box on axes 0 and 1."""
    z = np.asarray(X_normalized, float)
    a0_min, a0_max, a1_min, a1_max = (float(v) for v in box)
    return ((z[:, 0] >= a0_min) & (z[:, 0] <= a0_max)
            & (z[:, 1] >= a1_min) & (z[:, 1] <= a1_max))


def lhs_in_normalized_box(n: int, n_features: int, box: tuple[float, ...],
                          seed: int) -> np.ndarray:
    """Deterministic LHS inside a normalized corner box (axes 0-1 clamped)."""
    rng = np.random.default_rng(int(seed))
    u = np.empty((int(n), int(n_features)), float)
    for j in range(int(n_features)):
        u[:, j] = (rng.permutation(int(n)) + rng.random(int(n))) / int(n)
    a0_min, a0_max, a1_min, a1_max = (float(v) for v in box)
    u[:, 0] = a0_min + (a0_max - a0_min) * u[:, 0]
    u[:, 1] = a1_min + (a1_max - a1_min) * u[:, 1]
    return u


def denormalize(Z: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Map normalized coordinates back to physical units."""
    z = np.asarray(Z, float)
    lo = np.asarray(low, float).reshape(-1)
    hi = np.asarray(high, float).reshape(-1)
    if z.shape[1] != len(lo):
        raise ValueError("coordinate dimension does not match bounds")
    return lo + z * (hi - lo)


def assert_role_separation(fit_roles: set[str], eval_roles: set[str]) -> None:
    """Fail if any evaluation role was used to fit the evaluated model."""
    overlap = set(fit_roles) & set(eval_roles)
    if overlap:
        raise ValueError(f"role leakage: evaluation reuses fit roles {sorted(overlap)}")


def protocol_declaration() -> dict:
    """Machine-readable copy of the predeclared protocol for result files."""
    return {
        "protocol_version": SPATIAL_PROTOCOL_VERSION,
        "distance_metric": "Euclidean distance in V1.9-D shared-verified-box "
                           "normalized coordinates (same as V1.9-E support)",
        "metric_limitation": "equal weight per normalized unit across axes "
                             "with very different physical spans; no "
                             "post-hoc log variant",
        "buffer_rule": "median leave-one-out nearest-neighbor distance of "
                       "the TRAINING design; ties count as SEPARATED",
        "stratification": "INTERPOLATION (d < buffer) vs SEPARATED "
                          "(d >= buffer); strata with < 8 points report "
                          "counts only",
        "min_stratum_points": MIN_STRATUM_POINTS,
        "block_rule": {"axis_index": BLOCK_AXIS_INDEX,
                       "axis_name": "perovskite_eg_ev",
                       "low_slab": f"z0 < {BLOCK_LOW_MAX}",
                       "high_slab": f"z0 > {BLOCK_HIGH_MIN}"},
        "new_corner_boxes_normalized": {k: list(v) for k, v in NEW_CORNER_BOXES.items()},
        "v19e_corner_box_normalized": list(V19E_CORNER_BOX),
        "candidate_selection_methods": list(CANDIDATE_SELECTION_METHODS),
        "role_discipline": "refits use TRAIN/ADAPTIVE_TRAIN (scope roles "
                           "inside slices); FINAL rows never fit or select",
    }
