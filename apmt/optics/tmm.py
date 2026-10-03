"""APMT V1.9 — multilayer optics: transfer-matrix solver with energy closure.

Method (documented so it can be independently checked)
------------------------------------------------------
A layer j has complex index ``n_j = n - i k``, complex Snell angle, oblique
admittance ``eta_s = n cos(theta)`` (s-pol) or ``eta_p = n / cos(theta)``
(p-pol) and propagation phase ``delta_j = 2 pi n_j cos(theta_j) d_j / lambda``.
Interface coefficients use the admittance form

    r_ab = (eta_a - eta_b)/(eta_a + eta_b),  t_ab = 2 eta_a/(eta_a + eta_b).

The internal field is obtained by a backward recursion over the interfaces
(each step solves the two Fresnel amplitude relations for the left-hand pair,
then propagates through the layer), starting from the exit medium with
(A, B) = (1, 0). Dividing the incident-medium amplitudes by A_0 gives the
standard normalisation ``|E_inc| = 1``, and ``R = |B_0/A_0|^2``.

Per-layer absorptance uses the local absorption rate

    A_j = (2 pi / lambda) * (2 n_j k_j / n_0) * integral_layer |E(z)|^2 dz

with ``|E(z)|^2 = |A|^2 e^{-2 kappa z} + |B|^2 e^{+2 kappa z}
   + 2 Re(A B* e^{-2 i k' z})``, ``kappa = 2 pi k/lambda``. A single global
factor then scales the layer absorptances so that ``sum_j A_j = 1 - R - T``,
which makes energy closure exact by construction while preserving the
physically meaningful ratios between layers. The pre-normalisation ratio

    field_profile_ratio = sum_j raw_j / (1 - R - T)

is returned as a *validation diagnostic*: it equals ~1 when the field profile
is computed correctly (checked in tests at normal incidence) and deviates when
an approximation is active (documented: at oblique incidence the absorption
profile uses transverse-field amplitudes, i.e. it neglects the longitudinal
p-polarised component).

Numerical stability: a layer with kappa*d > 45 is optically opaque (the
transmission factor is < e^-90), so both its propagation distance and its
integration length are clipped at ``45/kappa``. The physical truncation error
is below e^-90 and therefore irrelevant; this prevents ``exp(+kappa d)``
overflow for micrometre-scale absorbing layers without changing any result at
the 1e-30 level.

Incoherent thick substrates (silicon wafers): coherent interference over
hundreds of micrometres at finite source bandwidth is not physical, and the
coherent solution of the full wafer shows fringe artefacts of the same order as
the quantities of interest. :func:`solve_incoherent_substrate` therefore treats
the wafer with a Beer-Lambert absorptance and an explicit path-length
enhancement (1 = single pass, 4n^2 = ideal Lambertian limit); the coherent
front stack is still solved exactly. Closure remains exact.

Canonical units: wavelength [nm], thickness [nm], angle [rad].
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import numpy as np

OPACITY_LIMIT = 45.0   # kappa*d above which a layer is treated as opaque


class OpticsClosureError(RuntimeError):
    """Raised when R + T + sum(A) departs from unity beyond tolerance."""


@dataclass(frozen=True)
class Layer:
    """One layer of the optical stack.

    name         : identifier used in loss attribution
    thickness_nm : physical thickness
    n, k         : real refractive index and extinction coefficient (array on
                   the working grid, or scalar)
    coherent     : True -> coherent TMM layer
    pv_active    : True -> absorption here is useful photogeneration
    semi_infinite: True -> the layer is the terminating half-space (no rear
                   interface). Physically: for k>0 all light entering it is
                   absorbed; for k=0 all light entering it is transmitted.
    """

    name: str
    thickness_nm: float
    n: np.ndarray | float
    k: np.ndarray | float
    coherent: bool = True
    pv_active: bool = False
    semi_infinite: bool = False

    def __post_init__(self):
        if self.thickness_nm < 0:
            raise ValueError(f"negative thickness for layer {self.name!r}")
        if self.thickness_nm > 5.0e5:
            raise ValueError(f"thickness {self.thickness_nm} nm for {self.name!r} "
                             f"is implausible (>500 um)")
        if float(np.min(np.asarray(self.k, dtype=float))) < 0:
            raise ValueError(f"negative extinction coefficient in {self.name!r}")
        if float(np.min(np.asarray(self.n, dtype=float))) < 1.0:
            raise ValueError(f"refractive index below 1 in {self.name!r}")


@dataclass(frozen=True)
class OpticsResult:
    """Wavelength-resolved optical outcome of a stack (closure-exact)."""

    wavelength_nm: np.ndarray
    reflectance: np.ndarray
    transmittance: np.ndarray
    layer_absorption: Dict[str, np.ndarray]
    field_profile_ratio: float = 1.0
    angular: bool = False
    notes: str = ""

    @property
    def total_absorption(self) -> np.ndarray:
        if not self.layer_absorption:
            return np.zeros_like(self.reflectance)
        return np.sum(np.array(list(self.layer_absorption.values())), axis=0)

    def closure_residual(self) -> np.ndarray:
        return self.reflectance + self.transmittance + self.total_absorption - 1.0

    def max_closure_error(self) -> float:
        return float(np.max(np.abs(self.closure_residual())))

    def useful_absorption(self, names: Sequence[str]) -> np.ndarray:
        return np.sum(np.array([self.layer_absorption[n] for n in names]), axis=0)

    def parasitic_absorption(self, pv_names: Sequence[str]) -> np.ndarray:
        keep = set(pv_names)
        others = [k for k in self.layer_absorption if k not in keep]
        if not others:
            return np.zeros_like(self.reflectance)
        return np.sum(np.array([self.layer_absorption[k] for k in others]), axis=0)

    def assert_closure(self, tol: float = 1e-9) -> None:
        err = self.max_closure_error()
        if not np.isfinite(err) or err > tol:
            raise OpticsClosureError(
                f"optical energy closure violated: max|R+T+A-1| = {err:.3e} > {tol:.1e}")


def _cw(x, size: int) -> np.ndarray:
    """Broadcast to a complex array of shape (size,)."""
    return np.asarray(np.broadcast_to(np.asarray(x, dtype=float), (size,)), dtype=complex)


def _solve_polarisation(layers: Sequence[Layer], wl: np.ndarray, theta: float,
                        polarisation: str) -> tuple:
    """Vectorised backward-recursion field solution for one polarisation.

    The last layer may be flagged ``semi_infinite``; it then acts as the
    terminating half-space (no rear interface), which is the correct physical
    limit for an optically thick absorber.

    Returns (R, T, raw_absorption_by_layer, max_field_profile_ratio).
    """
    size = wl.size
    n_inc = np.ones(size, dtype=complex)

    if any(l.semi_infinite for l in layers[:-1]):
        raise ValueError("only the last layer may be flagged semi_infinite")
    semi = bool(layers[-1].semi_infinite) if layers else False
    front = list(layers[:-1]) if semi else list(layers)
    exit_layer = layers[-1] if semi else None

    med_layers = front + ([exit_layer] if exit_layer is not None else [])
    n_exit = (_cw(exit_layer.n, size) - 1j * _cw(exit_layer.k, size)) if semi \
        else np.ones(size, dtype=complex)
    n_med = [n_inc] + [_cw(l.n, size) - 1j * _cw(l.k, size) for l in med_layers]
    d_all = np.array([0.0] + [float(l.thickness_nm) for l in med_layers])

    cos_t = []
    eta = []
    for n_m in n_med:
        sin_t = (n_inc * np.sin(theta)) / n_m
        c = np.sqrt(1.0 - sin_t ** 2 + 0j)
        cos_t.append(c)
        eta.append(n_m * c if polarisation == "s" else n_m / c)
    eta0 = n_inc * np.cos(theta) if polarisation == "s" else n_inc / np.cos(theta)

    # opaque-layer clipping (numerical only: kappa*d > 45 => transmission < e^-90)
    kappa = np.vstack([np.zeros((1, size))] + [
        2.0 * np.pi * np.abs(_cw(l.k, size)) / wl for l in med_layers])
    d_eff = np.tile(d_all[:, None], (1, size))
    for m in range(1, len(n_med)):
        d_eff[m] = np.minimum(d_all[m], OPACITY_LIMIT / np.maximum(kappa[m], 1e-300))

    A_top = [None] * len(n_med)
    B_top = [None] * len(n_med)
    A_bot = [None] * len(n_med)
    B_bot = [None] * len(n_med)
    A_top[-1] = np.ones(size, dtype=complex)
    B_top[-1] = np.zeros(size, dtype=complex)
    A_bot[-1], B_bot[-1] = A_top[-1], B_top[-1]

    for m in range(len(n_med) - 1, 0, -1):
        ea, eb = eta[m - 1], eta[m]
        r_ab = (ea - eb) / (ea + eb)
        t_ab = 2.0 * ea / (ea + eb)
        r_ba = -r_ab
        t_ba = 2.0 * eb / (ea + eb)
        A_left_bot = (A_top[m] - r_ba * B_top[m]) / t_ab
        B_left_bot = r_ab * A_left_bot + t_ba * B_top[m]
        A_bot[m - 1], B_bot[m - 1] = A_left_bot, B_left_bot
        if m - 1 == 0:
            A_top[0], B_top[0] = A_left_bot, B_left_bot
        else:
            # forward wave: A(0) = A(d) * exp(+i * 2 pi n d / lambda)
            delta = 2.0 * np.pi * n_med[m - 1] * cos_t[m - 1] * d_eff[m - 1] / wl
            A_top[m - 1] = A_left_bot * np.exp(+1j * delta)
            B_top[m - 1] = B_left_bot * np.exp(-1j * delta)

    scale = A_top[0]
    if np.any(np.abs(scale) < 1e-300):
        raise OpticsClosureError("degenerate optical solution (zero incident field)")
    for arr in (A_top, B_top, A_bot, B_bot):
        for m in range(len(n_med)):
            arr[m] = arr[m] / scale

    R = np.abs(B_top[0]) ** 2
    entering_exit = (np.abs(A_top[-1]) ** 2) * (eta[-1].real / eta0.real)

    T = np.zeros(size)
    raw: Dict[str, np.ndarray] = {}
    total_raw = np.zeros(size)

    for j, layer in enumerate(front):
        m = j + 1
        total_raw = total_raw + _layer_absorption(
            raw, layer.name, n_med[m], kappa[m], wl, d_eff[m], A_top[m], B_top[m])

    if semi:
        k_exit = np.abs(np.asarray(exit_layer.k, dtype=float))
        absorbs = k_exit > 0
        raw[exit_layer.name] = np.where(absorbs, entering_exit, 0.0)
        T = np.where(absorbs, 0.0, entering_exit)
        total_raw = total_raw + raw[exit_layer.name]
    else:
        T = entering_exit

    budget = np.clip(1.0 - R - T, 0.0, None)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        ratio = np.where(budget > 1e-12,
                         total_raw / np.maximum(budget, 1e-12), 1.0)
        ratio = np.clip(ratio, 0.0, 1e6)
        scale_a = np.where(total_raw > 1e-300,
                           budget / np.maximum(total_raw, 1e-300), 0.0)
    for k in list(raw):
        raw[k] = raw[k] * scale_a
    return R, T, raw, ratio


def _layer_absorption(raw: dict, name: str, n_m: np.ndarray, kap: np.ndarray,
                      wl: np.ndarray, d: np.ndarray, A: np.ndarray,
                      B: np.ndarray) -> np.ndarray:
    """Absorption rate integral of one coherent layer (stable formulation)."""
    k_j = np.abs(n_m.imag)
    if not np.any(k_j > 0):
        raw[name] = np.zeros(wl.size)
        return np.zeros(wl.size)
    kprime = 2.0 * np.pi * n_m.real / wl
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        exp_m = np.exp(-2.0 * kap * d)
        safe_kap = np.maximum(kap, 1e-300)
        term = np.where(kap > 0, (1.0 - exp_m) / (2.0 * safe_kap), d)
        w = B * np.exp(+kap * d)                      # stable: B e^{+kappa d}
        integ = np.where(
            kprime > 1e-12,
            (1.0 - np.exp(-2.0j * kprime * d)) / (2.0j * np.maximum(kprime, 1e-300)),
            d)
        E2 = (np.abs(A) ** 2) * term + (np.abs(w) ** 2) * term \
            + 2.0 * np.real(A * np.conj(w) * integ)
    E2 = np.clip(np.real(E2), 0.0, None)
    a = (2.0 * np.pi / wl) * (2.0 * n_m.real * k_j) * E2
    a = np.clip(np.real(a), 0.0, None)
    raw[name] = a
    return a


def solve_stack(wavelength_nm: np.ndarray, layers: Sequence[Layer],
                theta_rad: float = 0.0, closure_tol: float = 1e-9) -> OpticsResult:
    """Coherent TMM solution for a coherent stack (exact R+T+A closure).

    The last layer may be flagged ``semi_infinite`` (terminating half-space,
    e.g. an optically thick absorber). Otherwise the stack is terminated by
    air, i.e. the stack behaves as a free-standing membrane.
    """
    wl = np.asarray(wavelength_nm, dtype=float)
    if np.any(wl <= 0):
        raise ValueError("wavelengths must be positive")
    if not (0.0 <= theta_rad < np.pi / 2):
        raise ValueError("incidence angle must be in [0, pi/2)")
    if len(layers) == 0:
        raise ValueError("empty optical stack")
    if not all(l.coherent for l in layers):
        raise ValueError("solve_stack requires coherent layers; use "
                         "solve_incoherent_substrate for thick substrates")

    Rs, Ts, raw_s, ratio_s = _solve_polarisation(layers, wl, theta_rad, "s")
    Rp, Tp, raw_p, ratio_p = _solve_polarisation(layers, wl, theta_rad, "p")
    R = 0.5 * (Rs + Rp)
    T = 0.5 * (Ts + Tp)
    raw = {k: 0.5 * (raw_s[k] + raw_p[k]) for k in raw_s}

    total = np.sum(np.array(list(raw.values())), axis=0)
    budget = np.clip(1.0 - R - T, 0.0, None)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        f = np.where(total > 1e-300, budget / np.maximum(total, 1e-300), 0.0)
    raw = {k: np.clip(v * f, 0.0, None) for k, v in raw.items()}

    ratio = float(np.nanmax(0.5 * (ratio_s + ratio_p)))
    notes = ""
    if theta_rad > 1e-9:
        notes = ("oblique incidence: layer absorption profiles use transverse-field "
                 "amplitudes (longitudinal p component neglected)")
    res = OpticsResult(wl, R, T, raw, field_profile_ratio=ratio,
                       angular=theta_rad > 1e-9, notes=notes)
    res.assert_closure(closure_tol)
    return res


def solve_incoherent_substrate(wavelength_nm: np.ndarray, front_layers: Sequence[Layer],
                               substrate: Layer, theta_rad: float = 0.0,
                               rear_reflectance: float = 0.0,
                               path_enhancement: float = 1.0,
                               closure_tol: float = 1e-9) -> OpticsResult:
    """Coherent front stack on an incoherent, absorbing thick substrate.

    ``path_enhancement`` is an explicit design parameter (1 = single pass,
    4 n^2 = ideal Lambertian limit).
    """
    wl = np.asarray(wavelength_nm, dtype=float)
    if substrate.coherent:
        raise ValueError("substrate must be flagged incoherent")
    if path_enhancement < 1.0:
        raise ValueError("path_enhancement must be >= 1")
    if not (0.0 <= theta_rad < np.pi / 2):
        raise ValueError("incidence angle must be in [0, pi/2)")

    terminator = Layer("__substrate_entry__", 0.0, substrate.n, substrate.k,
                       coherent=True, pv_active=False)
    front = solve_stack(wl, list(front_layers) + [terminator], theta_rad)

    entering = np.clip(front.layer_absorption["__substrate_entry__"]
                       + front.transmittance, 0.0, 1.0)
    alpha_cm1 = 4.0 * np.pi * np.asarray(substrate.k, dtype=float) / (wl * 1e-7)
    d_cm = substrate.thickness_nm * 1e-7
    a_sub = 1.0 - np.exp(-np.maximum(alpha_cm1, 0.0) * d_cm * path_enhancement)

    A_sub = entering * a_sub
    leaving = entering * (1.0 - a_sub)
    T_out = leaving * (1.0 - rear_reflectance)
    R_out = front.reflectance + leaving * rear_reflectance

    layer_abs = {k: v for k, v in front.layer_absorption.items()
                 if k != "__substrate_entry__"}
    layer_abs[substrate.name] = A_sub

    res = OpticsResult(wl, R_out, T_out, layer_abs,
                       field_profile_ratio=front.field_profile_ratio,
                       notes=front.notes)
    res.assert_closure(closure_tol)
    return res


def angular_average(wavelength_nm: np.ndarray, front_layers: Sequence[Layer],
                    substrate: Layer, angles_rad: Sequence[float],
                    weights: Optional[Sequence[float]] = None,
                    rear_reflectance: float = 0.0,
                    path_enhancement: float = 1.0) -> OpticsResult:
    """Projected-solid-angle weighted average (default weights: cos theta)."""
    angles = np.asarray(angles_rad, dtype=float)
    if np.any(angles < 0) or np.any(angles >= np.pi / 2):
        raise ValueError("angles must be in [0, pi/2)")
    w = np.cos(angles) if weights is None else np.asarray(weights, dtype=float)
    w = w / np.sum(w)
    acc: Dict[str, np.ndarray] = {}
    R = T = None
    for ang, wi in zip(angles, w):
        r = solve_incoherent_substrate(wavelength_nm, front_layers, substrate, ang,
                                       rear_reflectance, path_enhancement)
        for k, v in r.layer_absorption.items():
            acc[k] = acc.get(k, 0.0) + wi * v
        R = wi * r.reflectance if R is None else R + wi * r.reflectance
        T = wi * r.transmittance if T is None else T + wi * r.transmittance
    out = OpticsResult(np.asarray(wavelength_nm, dtype=float), R, T, acc,
                       angular=True, notes="angular average (cos-weighted)")
    out.assert_closure(1e-8)
    return out


# ---------------------------------------------------------------------------
# Analytic cross-checks (tests + model discrimination)
# ---------------------------------------------------------------------------
def fresnel_reflectance_single_interface(n: float, k: float) -> float:
    """Normal-incidence reflectance of a bare air/material interface."""
    return ((n - 1.0) ** 2 + k ** 2) / ((n + 1.0) ** 2 + k ** 2)


def beer_lambert_absorptance(alpha_cm1: np.ndarray, thickness_nm: float,
                             reflectance: float = 0.0,
                             path_enhancement: float = 1.0) -> np.ndarray:
    """Analytic single-pass absorptance with a front reflectance loss."""
    d_cm = thickness_nm * 1e-7
    return (1.0 - reflectance) * (1.0 - np.exp(-np.asarray(alpha_cm1) * d_cm
                                               * max(path_enhancement, 1e-9)))
