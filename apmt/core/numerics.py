"""APMT V1.9 — deterministic numerics, convergence control and benchmarking.

Rules encoded here (directive §17, §36, §47):

* every stochastic computation is seeded through :func:`make_rng`, which is
  reproducible across processes for a given integer seed;
* every resolution-dependent result can be accompanied by a *convergence
  status* produced by :func:`convergence_status`;
* benchmarks record baseline vs optimised runtime and the numerical
  agreement between the two implementations (:class:`Benchmark`).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Deterministic random number generation
# ---------------------------------------------------------------------------
_DEFAULT_SEED = 20261003  # V1.9 campaign master seed (recorded in manifests)


def make_rng(seed: int | None = None) -> np.random.Generator:
    """Return a deterministic numpy Generator (PCG64).

    The same seed yields bit-identical streams regardless of process, so every
    campaign can be re-run from its manifest.
    """
    return np.random.Generator(np.random.PCG64(_DEFAULT_SEED if seed is None else int(seed)))


def seed_sequence(base_seed: int, index: int) -> int:
    """Derive a child seed deterministically (used for parallel chunks)."""
    h = hashlib.sha256(f"{base_seed}:{index}".encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**63 - 1)


# ---------------------------------------------------------------------------
# Array fingerprinting
# ---------------------------------------------------------------------------
def array_sha256(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        arr = np.ascontiguousarray(np.asarray(a, dtype=float))
        h.update(str(arr.shape).encode())
        h.update(arr.tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Integration on possibly non-uniform grids
# ---------------------------------------------------------------------------
def trapz(y: np.ndarray, x: np.ndarray) -> float:
    """Trapezoidal integral that works across numpy versions."""
    f = getattr(np, "trapezoid", None) or np.trapz
    return float(f(y, x))


def cumulative_trapz(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(y)
    dx = np.diff(x)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * dx)
    return out


def interp_clipped(x_new: np.ndarray, x: np.ndarray, y: np.ndarray,
                   left: float = 0.0, right: float = 0.0) -> np.ndarray:
    """Linear interpolation with explicit out-of-range handling."""
    return np.interp(np.asarray(x_new, dtype=float), np.asarray(x, dtype=float),
                     np.asarray(y, dtype=float), left=left, right=right)


def log_derivative(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """d(ln y)/d(ln x) on strictly positive arrays (for power-law diagnostics)."""
    lx, ly = np.log(np.asarray(x, float)), np.log(np.asarray(y, float))
    return np.gradient(ly, lx)


def stable_ratio(a: float, b: float, floor: float = 1e-300) -> float:
    return float(a) / max(abs(float(b)), floor)


def clip_unit_interval(x: np.ndarray | float):
    return np.clip(x, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Convergence control
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConvergenceReport:
    """Resolution-convergence status of one computed scalar/array quantity."""

    quantity: str
    resolutions: tuple
    values: tuple
    rel_change_last: float
    status: str          # CONVERGED | NOT-CONVERGED | UNDEFINED
    tolerance: float

    @property
    def converged(self) -> bool:
        return self.status == "CONVERGED"


def convergence_status(quantity: str, resolutions: Sequence[float],
                       values: Sequence[float], rel_tol: float = 1e-3,
                       floor: float = 1e-12) -> ConvergenceReport:
    """Compare successive refinement levels of the same computation.

    ``status == CONVERGED`` requires the last refinement step to change the
    value by less than ``rel_tol`` relative to the finest value. Undefined
    (e.g. all-NaN) inputs give ``UNDEFINED`` rather than a false positive.
    """
    vals = tuple(float(v) for v in values)
    if len(vals) < 2 or any(not np.isfinite(v) for v in vals):
        return ConvergenceReport(quantity, tuple(resolutions), vals, float("nan"),
                                 "UNDEFINED", rel_tol)
    rel = abs(vals[-1] - vals[-2]) / max(abs(vals[-1]), floor)
    status = "CONVERGED" if rel <= rel_tol else "NOT-CONVERGED"
    return ConvergenceReport(quantity, tuple(resolutions), vals, float(rel), status, rel_tol)


def convergence_study(quantity: str, resolutions: Iterable[float],
                      evaluate: Callable[[float], float],
                      rel_tol: float = 1e-3) -> ConvergenceReport:
    res = tuple(resolutions)
    vals = tuple(float(evaluate(r)) for r in res)
    return convergence_status(quantity, res, vals, rel_tol)


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------
@dataclass
class Benchmark:
    name: str
    baseline_s: float = 0.0
    optimized_s: float = 0.0
    max_abs_diff: float = 0.0
    max_rel_diff: float = 0.0
    notes: str = ""

    @property
    def speedup(self) -> float:
        return self.baseline_s / self.optimized_s if self.optimized_s > 0 else float("inf")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "baseline_s": round(self.baseline_s, 6),
            "optimized_s": round(self.optimized_s, 6),
            "speedup": round(self.speedup, 3),
            "max_abs_diff": self.max_abs_diff,
            "max_rel_diff": self.max_rel_diff,
            "numerically_equivalent": bool(self.max_rel_diff < 1e-9),
            "notes": self.notes,
        }


def timeit(fn: Callable, *args, repeat: int = 1, **kwargs) -> float:
    """Best-of-``repeat`` wall time of ``fn(*args, **kwargs)`` in seconds."""
    best = float("inf")
    for _ in range(max(1, repeat)):
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        best = min(best, time.perf_counter() - t0)
    return best


def compare_outputs(a, b) -> tuple:
    """(max abs diff, max rel diff) between two array outputs, NaN-safe."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.shape != y.shape:
        return float("inf"), float("inf")
    finite = np.isfinite(x) & np.isfinite(y)
    if not finite.any():
        return float("nan"), float("nan")
    ad = float(np.max(np.abs(x[finite] - y[finite])))
    denom = np.maximum(np.abs(y[finite]), 1e-12)
    rd = float(np.max(np.abs(x[finite] - y[finite]) / denom))
    return ad, rd


# ---------------------------------------------------------------------------
# Root finding / optimisation helpers shared by device models
# ---------------------------------------------------------------------------
def bisect(f: Callable[[float], float], lo: float, hi: float, tol: float = 1e-12,
           max_iter: int = 200) -> float:
    """Deterministic bisection on a sign-changing bracket (f(lo) < 0 < f(hi))."""
    flo, fhi = f(lo), f(hi)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if (flo > 0) == (fhi > 0):
        raise ValueError("bisect requires a sign-changing bracket")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm == 0.0 or (hi - lo) < tol:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return 0.5 * (lo + hi)


def golden_section_max(f: Callable[[float], float], lo: float, hi: float,
                       tol: float = 1e-10, max_iter: int = 300) -> tuple:
    """Deterministic 1-D maximisation; returns (x, f(x))."""
    gr = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(max_iter):
        if b - a < tol:
            break
        if fc < fd:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = f(d)
        else:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = f(c)
    x = 0.5 * (a + b)
    return x, f(x)
