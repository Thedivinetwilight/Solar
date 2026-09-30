"""Known-answer tests: the recovered spectrum reproduces historical project
constants bit-exactly. This anchors every V1.8 integration to the V1.1-V1.6
numbers (which are HANDOFF-QUOTED until the original curve files are restored).
"""
import numpy as np
import pytest

from apmt import spectrum as S
from apmt.ledger import HISTORICAL_LEDGER
from apmt.provenance import verify_known_answer

SPEC = None


def _spec():
    global SPEC
    if SPEC is None:
        SPEC = S.load_astm_g173_am15g_global()
    return SPEC


def test_spectrum_identification_irradiance():
    sp = _spec()
    irr = sp.integrated_irradiance(280.0, 4000.0)
    # project value is quoted to 6 decimals; compare at that precision
    assert round(irr, 6) == 1000.370656, irr
    verify_known_answer(irr, 1000.370656, 5.1e-7, "integrated irradiance")


def test_spectrum_identification_incident_photon_current():
    sp = _spec()
    j = sp.jph_100eqe(280.0, 5000.0)
    assert round(j, 6) == 68.982857, j
    verify_known_answer(j, 68.982857, 5.1e-7, "incident photon current 100% EQE")


def test_constants_exact_codata():
    assert S.Q_C == 1.602176634e-19
    assert S.H_J_S == 6.62607015e-34
    assert S.C_M_S == 299792458.0


def test_ledger_matches_handoff():
    # every historical value used in V1.8 docs must match the handoff quote
    assert HISTORICAL_LEDGER[("V1.5", "s32_graphical_integral")][0] == 17.110498
    assert HISTORICAL_LEDGER[("V1.6", "fig4e_reconstruction")][0] == 16.9019365812
    assert HISTORICAL_LEDGER[("V1.4", "bottom_eqe_reported")][0] == 20.18
    assert HISTORICAL_LEDGER[("V1.3", "delta_pp")][0] == 0.610


def test_window_irradiance():
    sp = _spec()
    # 300-1250 nm window irradiance sanity (V1.6 used this window)
    irr = sp.integrated_irradiance(300.0, 1250.0)
    assert 850 < irr < 870
