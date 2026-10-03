"""Vendor the project reference spectrum into the repository (deterministic).

The V1.1-V1.8 project spectrum was identified (apmt/spectrum.py) as the NLR
distribution of ASTM G173-03 AM1.5G global-tilt, as shipped with pvlib. Its
in-repo fingerprint is pinned in manifests/v1.8_reproducibility_manifest.json.

V1.9 vendors the *table* (public reference data, 2002 rows) so that core tests
and simulations no longer require pvlib at import time and so that the exact
spectral grid is immutable evidence rather than a library-version side effect.

Usage
-----
    python tools/vendor_spectrum.py --write     # regenerate data/spectra/*
    python tools/vendor_spectrum.py --check     # verify vendored file (no write)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_NPZ = os.path.join(REPO, "data", "spectra", "astm_g173_am15g_nlr.npz")
OUT_META = os.path.join(REPO, "data", "spectra", "astm_g173_am15g_nlr.meta.json")

# Known answers from the V1.1 / V1.2.2 project (see apmt/ledger.py)
KNOWN_IRRADIANCE = 1000.370656          # W/m2, 280-4000 nm
KNOWN_PHOTON_CURRENT = 68.982857        # mA/cm2, 100% EQE, 280-5000 nm
KNOWN_FINGERPRINT = "59040a85966f9c13ad394443bbafa5eb654df6aca58338a7a763f341b53d0eb0"

Q_C = 1.602176634e-19
H_J_S = 6.62607015e-34
C_M_S = 299792458.0


def fingerprint(wl: np.ndarray, irr: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(wl).tobytes())
    h.update(np.ascontiguousarray(irr).tobytes())
    return h.hexdigest()


def fetch() -> tuple:
    from pvlib.spectrum import get_reference_spectra
    s = get_reference_spectra()
    return np.asarray(s.index, dtype=float), np.asarray(s["global"], dtype=float)


def jph_100eqe(wl, irr, lo, hi) -> float:
    m = (wl >= lo) & (wl <= hi)
    flux = irr[m] * wl[m] * 1e-9 / (H_J_S * C_M_S)
    return 0.1 * Q_C * float(np.trapezoid(flux, wl[m]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the vendored table")
    ap.add_argument("--check", action="store_true", help="verify the vendored table only")
    args = ap.parse_args(argv)

    if args.check:
        d = np.load(OUT_NPZ)
        wl, irr = d["wavelength_nm"], d["irradiance_w_m2_nm"]
    else:
        wl, irr = fetch()

    irr_int = float(np.trapezoid(irr, wl))
    j100 = jph_100eqe(wl, irr, 280.0, 5000.0)
    fp = fingerprint(wl, irr)
    ok = (round(irr_int, 6) == KNOWN_IRRADIANCE
          and round(j100, 6) == KNOWN_PHOTON_CURRENT
          and fp == KNOWN_FINGERPRINT)
    print(f"n={wl.size} grid {wl[0]}-{wl[-1]} nm | irradiance {irr_int:.6f} W/m2 "
          f"| Jph100 {j100:.6f} mA/cm2 | fingerprint {fp[:16]}...")
    print(f"known-answer match: {ok}")
    if not ok:
        print("REFUSING to write/accept a spectrum that does not reproduce the "
              "V1.1/V1.2.2 project constants.", file=sys.stderr)
        return 2

    if args.write:
        os.makedirs(os.path.dirname(OUT_NPZ), exist_ok=True)
        np.savez_compressed(OUT_NPZ, wavelength_nm=wl, irradiance_w_m2_nm=irr)
        meta = {
            "standard": "ASTM G173-03 AM1.5G global tilt (37 deg)",
            "distribution": "NLR Excel table as shipped with pvlib-python",
            "distribution_url": "https://www.nlr.gov/grid/solar-resource/spectra-am1.5",
            "library_used_to_vendor": "pvlib 0.16.1",
            "grid": {"lo_nm": float(wl[0]), "hi_nm": float(wl[-1]),
                     "step_nm": 0.5 if wl.size == 2002 else None, "n_points": int(wl.size)},
            "known_answers": {
                "integrated_irradiance_w_m2_280_4000": irr_int,
                "incident_photon_current_ma_cm2_280_5000": j100,
            },
            "fingerprint": fp,
            "file_sha256": hashlib.sha256(open(OUT_NPZ, "rb").read()).hexdigest(),
            "provenance_category": "LITERATURE-DERIVED (public reference spectrum table)",
            "note": ("Vendored so the platform is reproducible without a specific "
                     "pvlib version. Regenerate with tools/vendor_spectrum.py "
                     "--write; the known-answer check must pass."),
        }
        with open(OUT_META, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"wrote {OUT_NPZ} and {OUT_META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
