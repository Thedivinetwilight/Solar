"""Provenance category hygiene: every V1.8 number must be classifiable, and
scenario values must never be treated as measurements or confidence intervals.
"""
import pytest

from apmt.provenance import (
    ProvenanceCategory,
    ProvenanceRecord,
    SourceRef,
)
from apmt.ledger import HISTORICAL_LEDGER, ledger_category


def test_all_required_categories_exist():
    required = {"EXPERIMENTAL", "LITERATURE-DERIVED", "DIGITIZED", "MODEL-FIT",
                "MODEL-ASSUMED", "DATA_REQUIRED", "SCENARIO",
                "SOURCE-REPORTED", "HANDOFF-QUOTED"}
    have = {c.value for c in ProvenanceCategory}
    assert required <= have


def test_scenario_is_not_measurement():
    assert ProvenanceCategory.SCENARIO.value == "SCENARIO"
    # historical scenario PCEs must exist under SCENARIO-labeled notes
    for key in [("V1.6", "scenario_pce_20p18_pct"),
                ("V1.6", "scenario_pce_17p11_pct")]:
        v, u, notes = HISTORICAL_LEDGER[key]
        assert "SCENARIO" in notes and "NOT measured" in notes


def test_record_ids_stable():
    src = SourceRef("X", "test source")
    r1 = ProvenanceRecord(20.18, "mA/cm2", "Jph_silicon",
                          ProvenanceCategory.SOURCE_REPORTED, src, "Fig 4E legend")
    r2 = ProvenanceRecord(20.18, "mA/cm2", "Jph_silicon",
                          ProvenanceCategory.SOURCE_REPORTED, src, "Fig 4E legend")
    assert r1.record_id() == r2.record_id()


def test_ledger_is_handoff_quoted():
    assert ledger_category() is ProvenanceCategory.HANDOFF_QUOTED


def test_digitized_never_raw():
    """A digitized curve must be categorized DIGITIZED, never EXPERIMENTAL."""
    src = SourceRef("X", "test source")
    r = ProvenanceRecord(17.110498, "mA/cm2", "Jph_si_graphical",
                         ProvenanceCategory.DIGITIZED, src, "Fig S32")
    assert r.category is not ProvenanceCategory.EXPERIMENTAL
