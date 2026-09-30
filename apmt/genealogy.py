"""APMT V1.8 — device genealogy with linkage classes.

Linkage classes (per V1.8 Objective C):
    SERIAL_LEVEL_LINKAGE               — same physical device identified by serial/ID
    CERTIFIED_CHAMPION_CONTEXT_LINKAGE — article/caption states same champion device
    CONFIGURATION_LEVEL_LINKAGE        — same recipe/configuration, different (unknown) devices
    UNKNOWN_PAIRING                    — no evidence of same-device pairing

Rule (non-negotiable): devices may only be MERGED (treated as one) when
SERIAL_LEVEL_LINKAGE exists. Context- and configuration-level links are
evidence for the GATE, never grounds for merging.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


class LinkageClass(IntEnum):
    UNKNOWN_PAIRING = 0
    CONFIGURATION_LEVEL_LINKAGE = 1
    CERTIFIED_CHAMPION_CONTEXT_LINKAGE = 2
    SERIAL_LEVEL_LINKAGE = 3


class NoMergeWithoutSerialError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    description: str
    configuration: str = ""
    serial_id: Optional[str] = None      # None == NO_SERIAL_ID
    source_id: str = ""
    context_evidence: str = ""           # what article/caption states
    source_reported_values: dict = None  # values the source attaches to this device

    def __post_init__(self):
        if self.source_reported_values is None:
            object.__setattr__(self, "source_reported_values", {})


@dataclass(frozen=True)
class Linkage:
    device_a: str
    device_b: str
    linkage_class: LinkageClass
    evidence: str
    serial_available: bool = False

    def allows_merge(self) -> bool:
        return self.linkage_class == LinkageClass.SERIAL_LEVEL_LINKAGE


def classify_linkage(evidence: dict) -> LinkageClass:
    """Deterministic classification from evidence flags.

    evidence keys (bool): has_serial_match, caption_states_same_champion,
    same_configuration_name_only
    """
    if evidence.get("has_serial_match", False):
        return LinkageClass.SERIAL_LEVEL_LINKAGE
    if evidence.get("caption_states_same_champion", False):
        return LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE
    if evidence.get("same_configuration_name_only", False):
        return LinkageClass.CONFIGURATION_LEVEL_LINKAGE
    return LinkageClass.UNKNOWN_PAIRING


def assert_merge_permitted(linkage: Linkage) -> None:
    """Guard: merging two devices without serial-level linkage raises."""
    if not linkage.allows_merge():
        raise NoMergeWithoutSerialError(
            f"Refusing to merge devices {linkage.device_a!r} and {linkage.device_b!r}: "
            f"linkage is {linkage.linkage_class.name}, not SERIAL_LEVEL_LINKAGE. "
            f"Devices with matching configuration names must NOT be merged."
        )


# ---------------------------------------------------------------------------
# V1.8 genealogy of the Al-Ashouri 2020 (Science 370:1300) reference devices.
# Established 2026-09-30 from the accepted author version (TU Berlin / DNB,
# CC BY; see INCOMING/ and manifests/ for source hashes).
# ---------------------------------------------------------------------------

DEV_CERT_CHAMPION = DeviceRecord(
    device_id="AA2020-CHAMPION-LIF",
    description="Certified champion tandem, Me-4PACz + LiF, 1.68 eV, ~1.064 cm2",
    configuration="Me-4PACz+LiF",
    serial_id=None,  # NO_SERIAL_ID
    source_id="AA2020-ACCEPTED-TUB",
    context_evidence=(
        "Accepted-version main text: sent to Fraunhofer ISE CalLab for "
        "independent certification (Fig. 4D; certificate Fig. S30); "
        "certified MPP PCE 29.15%, designated area 1.064 cm2; in-house JV "
        "Fig. S31; Fig. 4E 'EQE and 1-reflection of the certified tandem "
        "cell measured in-house' with legend values perovskite 19.41 / "
        "silicon 20.18 mA/cm2."
    ),
    source_reported_values={
        "PCE_certified_MPP": 29.15,
        "PCE_scan_JtoV": 29.01,
        "Voc": 1.90,
        "FF_certified": 79.4,
        "Jsc_certified": 19.23,
        "Jph_perovskite": 19.41,
        "Jph_silicon": 20.18,
        "Jph_cumulative": 39.59,
        "Jph_mismatch": 0.77,
        "reflection_loss": 2.57,
        "area_cm2": 1.064,
    },
)

DEV_REPRESENTATIVE_EL = DeviceRecord(
    device_id="AA2020-REPRESENTATIVE-EL",
    description="Representative Me-4PACz+LiF tandem used for absolute PL/EL subcell analysis (Fig. 5)",
    configuration="Me-4PACz+LiF",
    serial_id=None,
    source_id="AA2020-ACCEPTED-TUB",
    context_evidence=(
        "Accepted-version main text, 'Subcell J-V characteristics': 'we used "
        "absolute photoluminescence measurements in each subcell of a "
        "representative tandem solar cell (Me-4PACz + LiF)'; EQE-derived "
        "Jph 18.7 (top) / 20.6 (bottom) mA/cm2; PL-implied Voc 1.18/0.72 V; "
        "PLQY 0.02% / 1.5%."
    ),
    source_reported_values={
        "Jph_perovskite_eqe": 18.7,
        "Jph_silicon_eqe": 20.6,
        "Jph_cumulative": 39.3,
        "Voc_perovskite_PL": 1.18,
        "Voc_silicon_PL": 0.72,
        "PLQY_perovskite_pct": 0.02,
        "PLQY_silicon_pct": 1.5,
        "FF_JV_EL": 87.8,
    },
)

DEV_POSTCERT_NOLIF = DeviceRecord(
    device_id="AA2020-POSTCERT-NOLIF",
    description="Post-certification champion Me-4PACz (no LiF), Fig. S33",
    configuration="Me-4PACz",
    serial_id=None,
    source_id="AA2020-ACCEPTED-TUB",
    context_evidence=(
        "Accepted-version main text: 'After the certification, we fabricated "
        "more Me-4PACz tandem solar cells without LiF interlayer (Figure S26)... "
        "The champion cell showed a higher FF of 81% and lower VOC of 1.87 V... "
        "Together with a JSC of 19.37 mA cm-2 this lead to a PCE of 29.29% and a "
        "stabilized efficiency of 29.32% (Figure S33).'"
    ),
    source_reported_values={
        "FF": 81.0,
        "Voc": 1.87,
        "Jsc": 19.37,
        "PCE": 29.29,
        "PCE_stabilized": 29.32,
    },
)

DEV_SAHLI_TEXTURED = DeviceRecord(
    device_id="AA2020-SAHLI-TEXTURED",
    description="Fully textured perovskite/silicon tandem by Sahli et al. (2018), comparison device in Fig. S32",
    configuration="Sahli 2018 fully textured",
    serial_id=None,
    source_id="AA2020-ACCEPTED-TUB",
    context_evidence=(
        "Accepted-version Fig. 4E paragraph: 'A comparison of EQEs and "
        "reflection losses between a cell of this work (planar front side) and "
        "a fully textured cell by Sahli et al. is shown in Figure S32.'"
    ),
    source_reported_values={},
)

GENEALOGY_LINKAGES = (
    Linkage(
        device_a="AA2020-CHAMPION-LIF",
        device_b="AA2020-CHAMPION-LIF",
        linkage_class=LinkageClass.CERTIFIED_CHAMPION_CONTEXT_LINKAGE,
        evidence=(
            "Certified JV (Fig. 4D) + in-house JV (Fig. S31) + EQE/1-R (Fig. 4E) "
            "all attributed by main text to the certified champion; Fig. 4E "
            "caption: 'of the certified tandem cell measured in-house'. "
            "Serial ID: absent (NO_SERIAL_ID). Strong champion-context evidence."
        ),
        serial_available=False,
    ),
    Linkage(
        device_a="AA2020-CHAMPION-LIF",
        device_b="AA2020-REPRESENTATIVE-EL",
        linkage_class=LinkageClass.CONFIGURATION_LEVEL_LINKAGE,
        evidence=(
            "Both Me-4PACz+LiF; EL device explicitly 'representative', not "
            "certified. NOT merged; different Jph pairs (19.41/20.18 vs "
            "18.7/20.6) confirm they are distinct devices."
        ),
        serial_available=False,
    ),
    Linkage(
        device_a="AA2020-CHAMPION-LIF",
        device_b="AA2020-POSTCERT-NOLIF",
        linkage_class=LinkageClass.CONFIGURATION_LEVEL_LINKAGE,
        evidence="Different configuration (LiF vs no LiF) and different device; NOT merged.",
        serial_available=False,
    ),
    Linkage(
        device_a="AA2020-CHAMPION-LIF",
        device_b="AA2020-SAHLI-TEXTURED",
        linkage_class=LinkageClass.CONFIGURATION_LEVEL_LINKAGE,
        evidence="Distinct published device (Sahli et al. 2018); comparison only.",
        serial_available=False,
    ),
)
