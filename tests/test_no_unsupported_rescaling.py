"""Guard tests: no unsupported EQE rescaling/offset may ever be applied.

These encode Objective A.10 ('DO NOT apply any vertical scaling or offset
unless a primary source explicitly documents it') as machine-enforced rules.
"""
import numpy as np
import pytest

from apmt.eqe_digitize import apply_transform, UnsupportedRescaleError


def test_identity_transform_ok():
    eqe = np.array([0.5, 0.6, 0.7])
    out = apply_transform(eqe)
    assert np.array_equal(out, eqe)


def test_rescale_without_documentation_refused():
    eqe = np.array([0.5, 0.6, 0.7])
    with pytest.raises(UnsupportedRescaleError):
        apply_transform(eqe, scale=1.1793929)  # the V1.6 'required' factor — refused


def test_offset_without_documentation_refused():
    eqe = np.array([0.5, 0.6, 0.7])
    with pytest.raises(UnsupportedRescaleError):
        apply_transform(eqe, offset=0.13773)   # the V1.6 'required' offset — refused


def test_scale_and_offset_without_documentation_refused():
    eqe = np.array([0.5, 0.6, 0.7])
    with pytest.raises(UnsupportedRescaleError):
        apply_transform(eqe, scale=1.1, offset=0.01,
                        documented_in_primary_source=True,
                        documentation_citation="")  # citation required


def test_documented_transform_applies():
    eqe = np.array([0.5, 0.6, 0.7])
    out = apply_transform(eqe, scale=2.0,
                          documented_in_primary_source=True,
                          documentation_citation="example source, p. 5")
    assert np.allclose(out, [1.0, 1.2, 1.4])


def test_v16_required_factor_stays_unsupported():
    """The V1.6 forensics concluded the 1.1793929x factor is unsupported;
    the pipeline must still refuse it. This test pins that conclusion."""
    eqe = np.linspace(0.2, 0.9, 100)
    with pytest.raises(UnsupportedRescaleError):
        apply_transform(eqe, scale=1.1793929,
                        documented_in_primary_source=False)
