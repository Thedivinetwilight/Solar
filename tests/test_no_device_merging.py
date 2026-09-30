"""Guard tests: devices may never be merged without serial-level linkage.

Encodes V1.8 Objective C and the non-negotiable 'never merge devices merely
because configuration names match' / 'never infer serial pairing without a
source'.
"""
import pytest

from apmt.genealogy import (
    Linkage,
    LinkageClass,
    NoMergeWithoutSerialError,
    assert_merge_permitted,
    classify_linkage,
    GENEALOGY_LINKAGES,
)


def test_classification_serial_wins():
    assert classify_linkage({"has_serial_match": True,
                             "caption_states_same_champion": True}) == LinkageClass.SERIAL_LEVEL_LINKAGE


def test_classification_context():
    assert classify_linkage({"caption_states_same_champion": True}) == \
        LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE


def test_classification_configuration_only():
    assert classify_linkage({"same_configuration_name_only": True}) == \
        LinkageClass.CONFIGURATION_LEVEL_LINKAGE


def test_classification_none():
    assert classify_linkage({}) == LinkageClass.UNKNOWN_PAIRING


def test_context_level_linkage_cannot_merge():
    lk = Linkage("A", "B", LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE,
                 "caption says same champion", serial_available=False)
    with pytest.raises(NoMergeWithoutSerialError):
        assert_merge_permitted(lk)


def test_configuration_level_linkage_cannot_merge():
    lk = Linkage("A", "B", LinkageClass.CONFIGURATION_LEVEL_LINKAGE,
                 "same configuration name", serial_available=False)
    with pytest.raises(NoMergeWithoutSerialError):
        assert_merge_permitted(lk)


def test_serial_level_linkage_may_merge():
    lk = Linkage("A", "B", LinkageClass.SERIAL_LEVEL_LINKAGE,
                 "serial match in source", serial_available=True)
    assert_merge_permitted(lk)  # no exception


def test_champion_genealogy_has_no_serials():
    """V1.8 finding: champion-context pairing is strong but NO_SERIAL_ID.
    Every linkage in the V1.8 genealogy must therefore forbid merging."""
    assert GENEALOGY_LINKAGES, "genealogy must not be empty"
    for lk in GENEALOGY_LINKAGES:
        assert not lk.serial_available
        if lk.linkage_class != LinkageClass.SERIAL_LEVEL_LINKAGE:
            with pytest.raises(NoMergeWithoutSerialError):
                assert_merge_permitted(lk)


def test_representative_vs_champion_not_mergible():
    """The EL 'representative' cell (Jph 18.7/20.6) must never be treated as
    the certified champion (Jph 19.41/20.18) without a serial."""
    relevant = [lk for lk in GENEALOGY_LINKAGES
                if {lk.device_a, lk.device_b} == {"AA2020-CHAMPION-LIF", "AA2020-REPRESENTATIVE-EL"}]
    assert relevant, "champion<->representative linkage must exist"
    for lk in relevant:
        assert lk.linkage_class == LinkageClass.CONFIGURATION_LEVEL_LINKAGE
        with pytest.raises(NoMergeWithoutSerialError):
            assert_merge_permitted(lk)
