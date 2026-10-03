"""APMT V1.9 — absorber/material optical models (layer 3 of the architecture).

Two material models are provided:

* :mod:`silicon`   — tabulated literature n,k (Green & Keevers 1995), so the
  bottom-cell optics are *evidence-linked* rather than invented;
* :mod:`perovskite` — parameterized dispersion (Wemple-DiDomenico index +
  Tauc interband absorption + Urbach tail), whose shape parameters are
  registered in :mod:`apmt.params.registry` and whose outputs are
  cross-checked against the digitized EQE evidence in the discovery campaigns.

Both return complex refractive index arrays on a requested wavelength grid.
"""
