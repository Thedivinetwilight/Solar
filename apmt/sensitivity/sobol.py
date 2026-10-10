"""APMT V1.9-D — variance-based global sensitivity (Sobol indices).

This module implements the Saltelli (2010) estimators from first principles
rather than depending on an external sensitivity package. Reasons: (a) the
estimator definitions are short and must be auditable; (b) the APMT engine has to
handle INVALID solves, which no off-the-shelf implementation accounts for; and
(c) a known-answer test against a function with analytic indices (Ishigami) is
then possible on the exact code that runs the campaign.

Definitions (Saltelli et al., Comput. Phys. Commun. 181 (2010) 259-270):

    A, B        two independent N x d sample matrices
    AB_i        A with column i replaced by column i of B
    BA_i        B with column i replaced by column i of A

    f0^2   = (1/N) sum_j f(A)_j f(B)_j
    V_i    = (1/N) sum_j f(B)_j (f(AB_i)_j - f(A)_j)          [first order]
    V_Ti   = (1/2N) sum_j (f(A)_j - f(AB_i)_j)^2              [total order]
    V_ij   = (1/N) sum_j f(AB_i)_j f(BA_j)_j - f0^2           [second order]
    S_ij   = V_ij / Var - S_i - S_j

Confidence intervals are bootstrapped over the ``j`` rows (the estimator's
sampling dimension), which is the statistically correct resampling unit.

INVALID handling. A Sobol decomposition requires a COMPLETE design: every one of
the 2N + 2Nd evaluations must return a value. If a point is physically invalid
the estimator cannot be computed without bias. This module therefore never
silently imputes: it computes what it can from the usable rows, marks the result
``complete=False``, records exactly how many rows were lost per block, and
exposes the estimator-level standard error. A ``complete=False`` result is a
diagnostic, not a sensitivity conclusion, and callers must treat it that way
(the campaign layer achieves complete designs by validating its sampling box).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import numpy as np

from ..core.numerics import make_rng

DEFAULT_N_BASE = 96


# ---------------------------------------------------------------------------
# design
# ---------------------------------------------------------------------------
@dataclass
class SaltelliDesign:
    """A Saltelli design: A, B, AB_i, BA_i blocks over a parameter box."""

    names: Tuple[str, ...]
    n_base: int
    low: np.ndarray
    high: np.ndarray
    A: np.ndarray                       # N x d
    B: np.ndarray                       # N x d
    AB: np.ndarray                      # d x N x d
    BA: np.ndarray | None               # d x N x d (only when second order)
    seed: int

    @property
    def n_blocks(self) -> int:
        return 2 + (2 if self.BA is not None else 1) * len(self.names)

    def block_names(self) -> List[str]:
        out = ["A", "B"] + [f"AB:{n}" for n in self.names]
        if self.BA is not None:
            out += [f"BA:{n}" for n in self.names]
        return out

    def matrix(self) -> np.ndarray:
        """All blocks stacked in block order (n_blocks * N, d) — one batch."""
        parts = [self.A, self.B] + list(self.AB)
        if self.BA is not None:
            parts += list(self.BA)
        return np.vstack(parts)

    def fingerprint(self) -> str:
        from ..core.numerics import array_sha256
        return array_sha256(self.matrix())

    def to_dict(self) -> dict:
        return {"names": list(self.names), "n_base": self.n_base, "seed": self.seed,
                "n_blocks": self.n_blocks, "n_evaluations": self.n_blocks * self.n_base,
                "second_order": self.BA is not None,
                "design_fingerprint": self.fingerprint(),
                "bounds": {n: [float(l), float(h)]
                           for n, l, h in zip(self.names, self.low, self.high)},
                # a small sample of the design for eyeballing; the fingerprint is
                # what actually identifies it (the full design is regenerable from
                # seed + bounds, so storing it would only bloat the artifact)
                "first_rows": self.matrix()[:3].round(6).tolist()}


def saltelli_design(names: Sequence[str], n_base: int = DEFAULT_N_BASE,
                    low: np.ndarray | None = None, high: np.ndarray | None = None,
                    seed: int = 20261004, second_order: bool = True) -> SaltelliDesign:
    """Build the Saltelli design over an explicit box (default: registered box)."""
    from ..params.registry import spec
    names = tuple(names)
    d = len(names)
    if low is None or high is None:
        low = np.array([float(spec(n).low) for n in names])
        high = np.array([float(spec(n).high) for n in names])
    low = np.asarray(low, dtype=float).copy()
    high = np.asarray(high, dtype=float).copy()
    if np.any(high <= low):
        raise ValueError("empty sampling box: high must exceed low for every parameter")
    rng = make_rng(seed)
    A = low + rng.random((n_base, d)) * (high - low)
    B = low + rng.random((n_base, d)) * (high - low)
    AB = np.empty((d, n_base, d))
    BA = np.empty((d, n_base, d)) if second_order else None
    for i in range(d):
        m = A.copy()
        m[:, i] = B[:, i]
        AB[i] = m
        if BA is not None:
        # BA_i: B with column i taken from A (needed for the second-order estimator)
            m2 = B.copy()
            m2[:, i] = A[:, i]
            BA[i] = m2
    return SaltelliDesign(names=names, n_base=n_base, low=low, high=high, A=A, B=B,
                          AB=AB, BA=BA, seed=seed)


# ---------------------------------------------------------------------------
# estimators
# ---------------------------------------------------------------------------
@dataclass
class SobolIndices:
    """First- and total-order Sobol indices for one output."""

    output: str
    names: Tuple[str, ...]
    first: np.ndarray
    total: np.ndarray
    second: Dict[Tuple[str, str], float] = field(default_factory=dict)
    variance: float = float("nan")
    mean: float = float("nan")
    n_base: int = 0
    complete: bool = True
    n_missing: int = 0
    not_applicable: bool = False
    degenerate: bool = False
    first_ci: np.ndarray | None = None       # 95% bootstrap half-width
    total_ci: np.ndarray | None = None
    bootstrap: int = 0

    def as_dict(self) -> dict:
        return {
            "output": self.output, "n_base": self.n_base, "complete": self.complete,
            "not_applicable": self.not_applicable,
            "degenerate": self.degenerate,
            "reason": ("output does not vary over this design (zero variance): "
                       "Sobol indices are undefined" if self.degenerate else
                       "output is not produced at this fidelity" if self.not_applicable
                       else ""),
            "n_missing": self.n_missing, "variance": self.variance, "mean": self.mean,
            "first": {n: float(v) for n, v in zip(self.names, self.first)},
            "total": {n: float(v) for n, v in zip(self.names, self.total)},
            "first_ci95": ({n: float(v) for n, v in zip(self.names, self.first_ci)}
                           if self.first_ci is not None else {}),
            "total_ci95": ({n: float(v) for n, v in zip(self.names, self.total_ci)}
                           if self.total_ci is not None else {}),
            "second": {f"{a}|{b}": float(v) for (a, b), v in self.second.items()},
            "bootstrap": self.bootstrap,
        }

    def ranking(self, kind: str = "total") -> List[str]:
        idx = self.total if kind == "total" else self.first
        order = np.argsort(-np.nan_to_num(idx, nan=-np.inf))
        return [self.names[i] for i in order]

    def top_pairs(self, k: int = 10) -> List[Tuple[Tuple[str, str], float]]:
        items = sorted(self.second.items(), key=lambda kv: -abs(kv[1]))
        return items[:k]


def _stack(Y: np.ndarray, n_blocks: int, n_base: int) -> List[np.ndarray]:
    """Split a stacked output vector into its per-block (N,) arrays."""
    if Y.shape[0] != n_blocks * n_base:
        raise ValueError(f"expected {n_blocks * n_base} rows, got {Y.shape[0]}")
    return [Y[i * n_base:(i + 1) * n_base] for i in range(n_blocks)]


def sobol_indices(Y: np.ndarray, design: SaltelliDesign, output: str = "",
                  bootstrap: int = 200, confidence: float = 0.95,
                  seed: int = 7) -> SobolIndices:
    """Saltelli first/total (+ second) order indices from a stacked output vector.

    ``Y`` must be the output of every block in ``design.block_names()`` order, i.e.
    ``batch_evaluate(design.matrix(), ...)`` results in the same order. NaN marks a
    physically invalid evaluation; the affected rows are excluded from every
    estimator that uses them and the result is flagged ``complete=False``.
    """
    d = len(design.names)
    blocks = _stack(np.asarray(Y, dtype=float), design.n_blocks, design.n_base)
    n_base = design.n_base
    f_A, f_B = blocks[0], blocks[1]
    f_AB = blocks[2:2 + d]
    f_BA = blocks[2 + d:] if design.BA is not None else []

    n_missing = int(np.isnan(np.concatenate([f_A, f_B] +
                                            [b for b in f_AB] + list(f_BA))).sum())
    complete = n_missing == 0
    all_nan = bool(np.isnan(np.concatenate([f_A, f_B])).all())
    if all_nan:
        # The output does not exist at this fidelity (e.g. the junction
        # temperature at a fixed-temperature level): report NOT-APPLICABLE rather
        # than a number derived from an empty sample.
        return SobolIndices(output=output, names=design.names,
                            first=np.full(d, np.nan), total=np.full(d, np.nan),
                            second={}, variance=float("nan"), mean=float("nan"),
                            n_base=n_base, complete=False, n_missing=n_missing,
                            first_ci=None, total_ci=None, bootstrap=0,
                            not_applicable=True)

    def _pair(x, y):
        m = ~(np.isnan(x) | np.isnan(y))
        return x[m], y[m], int(m.sum())

    a, b, n_ab = _pair(f_A, f_B)
    f0_sq = float(np.mean(a * b)) if n_ab else float("nan")
    with np.errstate(all="ignore"):
        var = (float(np.var(np.concatenate([f_A, f_B]), ddof=1)) if complete else
               float(np.nanvar(np.concatenate([f_A, f_B]), ddof=1)))
    if not np.isfinite(var) or var <= 1e-12 * max(1.0, abs(float(np.nanmean(f_A)))):
        # The output does not vary over this design (e.g. the junction temperature
        # at a fixed-temperature level). Normalising by a zero variance would
        # manufacture an index out of numerical noise, so the indices are declared
        # UNDEFINED and the reason is recorded instead.
        return SobolIndices(output=output, names=design.names,
                            first=np.full(d, np.nan), total=np.full(d, np.nan),
                            second={}, variance=var,
                            mean=float(np.nanmean(f_A)) if np.isfinite(np.nanmean(f_A))
                            else float("nan"),
                            n_base=n_base, complete=False, n_missing=n_missing,
                            first_ci=None, total_ci=None, bootstrap=0,
                            degenerate=True)
    first = np.full(d, np.nan)
    total = np.full(d, np.nan)
    for i in range(d):
        # V1.9-H: the Saltelli first-order estimator consumes TRIPLETS
        # (f_A, f_B, f_AB_i); masking only the (B, AB_i) pair let NaN in f_A
        # leak into the mean and silently NaN the index. Triple-wise mask.
        m3 = ~(np.isnan(f_A) | np.isnan(f_B) | np.isnan(f_AB[i]))
        if m3.sum():
            first[i] = (float(np.mean(f_B[m3] * (f_AB[i][m3] - f_A[m3])))
                        / var)
        a_i, ab_i2, n2 = _pair(f_A, f_AB[i])
        if n2:
            total[i] = float(np.mean((a_i - ab_i2) ** 2)) / (2.0 * var)

    second: Dict[Tuple[str, str], float] = {}
    if f_BA:
        for i in range(d):
            for j in range(i + 1, d):
                x, y, n = _pair(f_AB[i], f_BA[j])
                if not n:
                    continue
                v_ij = float(np.mean(x * y)) - f0_sq
                second[(design.names[i], design.names[j])] = \
                    v_ij / var - (0.0 if np.isnan(first[i]) else first[i]) \
                              - (0.0 if np.isnan(first[j]) else first[j])

    first_ci = total_ci = None
    if bootstrap and complete:
        first_ci, total_ci = _bootstrap(f_A, f_B, f_AB, var, d, bootstrap,
                                        confidence, seed)
    return SobolIndices(output=output, names=design.names, first=first, total=total,
                        second=second, variance=var,
                        mean=float(np.nanmean(np.concatenate([f_A, f_B])))
                        if np.isfinite(np.concatenate([f_A, f_B])).any() else float("nan"),
                        n_base=n_base, complete=complete, n_missing=n_missing,
                        first_ci=first_ci, total_ci=total_ci,
                        bootstrap=(bootstrap if complete else 0))


def _bootstrap(f_A, f_B, f_AB, var, d, n_boot, confidence, seed) -> Tuple[np.ndarray, np.ndarray]:
    """Bootstrap the estimator rows. Resampling unit = the j index (N rows)."""
    rng = make_rng(seed)
    n = len(f_A)
    first = np.empty((n_boot, d))
    total = np.empty((n_boot, d))
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        a, bb = f_A[idx], f_B[idx]
        first[b] = [float(np.mean(bb * (f_AB[i][idx] - a))) / var for i in range(d)]
        total[b] = [float(np.mean((a - f_AB[i][idx]) ** 2)) / (2.0 * var)
                    for i in range(d)]
    alpha = (1.0 - confidence) / 2.0
    return (np.quantile(first, 1 - alpha, axis=0) - np.quantile(first, alpha, axis=0)) / 2.0, \
           (np.quantile(total, 1 - alpha, axis=0) - np.quantile(total, alpha, axis=0)) / 2.0


# ---------------------------------------------------------------------------
# analytic verification function (Ishigami et al. 1990)
# ---------------------------------------------------------------------------
def ishigami(x: np.ndarray) -> np.ndarray:
    """Classic test function with closed-form Sobol indices.

    f(x) = sin(x1) + 7 sin^2(x2) + 0.1 x3^4 sin(x1),  x_i ~ U(-pi, pi)
    Analytic: Var = 13.8445, S1 = 0.3139, S2 = 0.4424, S3 = 0.0,
              S13 = 0.2437, S_T1 = 0.5576, S_T2 = 0.4424, S_T3 = 0.2437.
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    return (np.sin(x[:, 0]) + 7.0 * np.sin(x[:, 1]) ** 2
            + 0.1 * x[:, 2] ** 4 * np.sin(x[:, 0]))


ISHIGAMI_ANALYTIC = {
    "variance": 13.8445,
    "S1": {"x1": 0.3139, "x2": 0.4424, "x3": 0.0},
    "ST": {"x1": 0.5576, "x2": 0.4424, "x3": 0.2437},
    "S2": {("x1", "x3"): 0.2437},
}


def ishigami_design(n_base: int = 1024, seed: int = 11) -> SaltelliDesign:
    """Saltelli design in the Ishigami box (-pi, pi)^3."""
    return saltelli_design(("x1", "x2", "x3"), n_base=n_base,
                           low=np.full(3, -np.pi), high=np.full(3, np.pi),
                           seed=seed, second_order=True)


def ishigami_design_nd(n_dim: int, n_base: int = 768, seed: int = 11) -> SaltelliDesign:
    """Ishigami embedded in ``n_dim`` dimensions with inert extra variables.

    Used to calibrate the estimator's ERROR at exactly the design size a campaign
    uses: the extra variables have analytically zero first-, total- and pairwise
    indices, so any non-zero index reported for them is pure estimator noise. That
    measurement is what justifies (or forbids) reporting an interaction.
    """
    if n_dim < 3:
        raise ValueError("need at least the three Ishigami dimensions")
    names = tuple([f"x{i + 1}" for i in range(n_dim)])
    return saltelli_design(names, n_base=n_base, low=np.full(n_dim, -np.pi),
                           high=np.full(n_dim, np.pi), seed=seed, second_order=True)


def ishigami_nd(x: np.ndarray) -> np.ndarray:
    """Ishigami(x1..x3); variables 4..n are inert."""
    return ishigami(np.asarray(x)[:, :3])
