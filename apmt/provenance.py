"""APMT V1.8 — provenance records.

Every numerical claim carries a ProvenanceRecord with an explicit category.
Categories follow the V1.2 convention (EXPERIMENTAL, LITERATURE-DERIVED,
MODEL-ASSUMED, DATA_REQUIRED) extended for V1.8:

    DIGITIZED          — extracted from a published figure by digitization
    SOURCE-REPORTED    — a number as printed/stated in a primary source
    HANDOFF-QUOTED     — quoted second-hand from the project handoff document
                         (the original artifact is not present in this repo)
    SCENARIO           — scenario-propagated model value (NOT a CI)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProvenanceCategory(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    LITERATURE_DERIVED = "LITERATURE-DERIVED"
    DIGITIZED = "DIGITIZED"
    MODEL_FIT = "MODEL-FIT"
    ASSUMED = "MODEL-ASSUMED"
    DATA_REQUIRED = "DATA_REQUIRED"
    SCENARIO = "SCENARIO"
    SOURCE_REPORTED = "SOURCE-REPORTED"
    HANDOFF_QUOTED = "HANDOFF-QUOTED"


@dataclass(frozen=True)
class SourceRef:
    """A physical source document (file, URL, or repo blob)."""
    source_id: str
    description: str
    url: Optional[str] = None
    sha256: Optional[str] = None          # of the bytes actually used
    git_blob_sha1: Optional[str] = None   # if committed to this repo
    retrieval_date: str = ""
    access_status: str = "OBTAINED"       # OBTAINED | ACCESS_BLOCKED | MISSING-VERIFIED
    lawfulness_note: str = ""


@dataclass(frozen=True)
class ProvenanceRecord:
    """One numerical (or textual) claim with full provenance.

    The record is immutable; corrections must be new records referencing the
    old one (this enforces 'never silently change historical numbers').
    """
    value: float
    units: str
    quantity: str
    category: ProvenanceCategory
    source: SourceRef
    locator: str = ""            # figure / table / page / section within source
    description: str = ""
    confidence: str = "unassessed"   # low | medium | high | unassessed
    parent_record_ids: tuple = ()
    processing_notes: str = ""

    def record_id(self) -> str:
        payload = json.dumps(
            [self.value, self.units, self.quantity, self.category.value,
             self.source.source_id, self.locator, self.description,
             self.processing_notes],
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def verify_known_answer(value: float, expected: float, tol: float, label: str) -> None:
    """Assert a reproduced value matches a historical known answer.

    Used by the reproducibility tests so that no historical number can drift
    silently through the V1.8 pipeline.
    """
    if abs(value - expected) > tol:
        raise AssertionError(
            f"Known-answer failure for {label}: reproduced {value!r} "
            f"vs historical {expected!r} (tol {tol})"
        )
