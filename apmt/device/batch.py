"""APMT V1.9-C — batch evaluation API (N parameter sets -> N guarded results).

This is the interface V1.9-D (Sobol / LHS / surrogate training / global
optimisation) is expected to consume. It

* evaluates N parameter vectors without a Python loop per *wavelength* or per
  bias point (the electrical core is vectorised inside each solve),
* reuses the optical solution when only electrical/thermal parameters change
  (the optics cache is keyed on the optical parameter tuple),
* warm-starts the electrical solve at the previous sample's junction temperature
  in a batch (the thermal problem is a small perturbation between neighbouring
  samples; the invariant layer verifies the converged balance regardless),
* optionally evaluates in worker processes (``workers > 1``) for CPU-bound
  campaigns -- each worker is one parameter vector, so results are deterministic
  and order-preserving,
* returns :class:`apmt.validation.guard.SolveRecord` objects whose ``valid`` flag
  is False whenever a HARD physical invariant fails.

Invalid solves are returned (never silently dropped) but flagged, and
:func:`dataset` extracts only valid rows plus a full accounting of what was
rejected and why.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

import numpy as np

from ..params.registry import ParamSet, sample_bounds, spec
from ..validation.guard import SolveRecord, evaluate_guarded

_WORKER_STATE: dict = {}


def _worker_init(level: str, model_form: str, campaign_id: str) -> None:
    _WORKER_STATE.update(level=level, model_form=model_form, campaign_id=campaign_id)


def _worker_eval(row):
    i, values = row
    names = _WORKER_STATE["names"]
    ps = ParamSet.defaults().with_mapping(dict(zip(names, values)))
    rec = evaluate_guarded(ps, level=_WORKER_STATE["level"],
                           model_form=_WORKER_STATE["model_form"],
                           campaign_id=_WORKER_STATE["campaign_id"],
                           seed=_WORKER_STATE["seed"])
    return i, rec


@dataclass
class BatchSummary:
    n_requested: int
    n_valid: int
    n_invalid: int
    wall_clock_s: float
    solves_per_second: float
    failure_counts: dict
    solver: str
    level: str
    campaign_id: str
    warm_started: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def batch_evaluate(matrix: np.ndarray, names: Sequence[str], *,
                   level: str = "L4", model_form: str = "IQE-M1",
                   campaign_id: str = "", seed: Optional[int] = None,
                   base: Optional[ParamSet] = None,
                   workers: int = 1,
                   warm_start: bool = True,
                   self_heating: bool = True) -> tuple:
    """Evaluate a matrix of parameters (n_samples x n_parameters).

    Returns ``(records, summary)``. ``records[i]`` corresponds to
    ``matrix[i]``: order is preserved for both the serial and the parallel path.
    """
    names = tuple(names)
    X = np.atleast_2d(np.asarray(matrix, dtype=float))
    if X.shape[1] != len(names):
        raise ValueError(f"matrix has {X.shape[1]} columns but {len(names)} names")
    base_ps = base or ParamSet.defaults()
    lo, hi = sample_bounds(names)
    X = np.clip(X, lo, hi)                      # never evaluate outside registered ranges
    t0 = time.perf_counter()
    records: list = []

    if workers and workers > 1:
        import multiprocessing as mp
        _WORKER_STATE.update(names=names, level=level, model_form=model_form,
                             campaign_id=campaign_id, seed=seed)
        with mp.Pool(processes=int(workers), initializer=_worker_init,
                     initargs=(level, model_form, campaign_id)) as pool:
            # the initializer needs the per-task names too; send them explicitly
            for i, rec in pool.imap(_worker_eval_meta,
                                    [(i, row.tolist()) for i, row in enumerate(X)]):
                records.append((i, rec))
                pass
        records = [r for _, r in sorted(records, key=lambda kv: kv[0])]
    else:
        warm_T: Optional[float] = None
        warm_count = 0
        for i, row in enumerate(X):
            ps = base_ps.with_mapping(dict(zip(names, row)))
            if warm_start and warm_T is not None:
                rec = _evaluate_warm(ps, level, model_form, campaign_id, seed, warm_T)
                warm_count += int(rec.valid)
            else:
                rec = evaluate_guarded(ps, level=level, model_form=model_form,
                                       campaign_id=campaign_id, seed=seed)
            if rec.result is not None:
                warm_T = float(rec.result.temperature_k)
            records.append(rec)
    wall = time.perf_counter() - t0

    failure_counts: dict = {}
    for rec in records:
        for f in rec.verdict.failures:
            failure_counts[f.name] = failure_counts.get(f.name, 0) + 1
        if rec.error:
            failure_counts[f"exception:{rec.error.split(':')[0]}"] = \
                failure_counts.get(f"exception:{rec.error.split(':')[0]}", 0) + 1
    n_valid = sum(1 for r in records if r.valid)
    summary = BatchSummary(
        n_requested=len(records), n_valid=n_valid, n_invalid=len(records) - n_valid,
        wall_clock_s=wall, solves_per_second=(len(records) / wall if wall > 0 else float("nan")),
        failure_counts=failure_counts,
        solver=(records[0].solver if records else ""), level=level,
        campaign_id=campaign_id,
        warm_started=(warm_count if not (workers and workers > 1) else 0))
    return records, summary


def _worker_eval_meta(task):
    i, values = task
    names = _WORKER_STATE["names"]
    ps = ParamSet.defaults().with_mapping(dict(zip(names, values)))
    rec = evaluate_guarded(ps, level=_WORKER_STATE["level"],
                           model_form=_WORKER_STATE["model_form"],
                           campaign_id=_WORKER_STATE["campaign_id"],
                           seed=_WORKER_STATE["seed"])
    return i, rec


def _evaluate_warm(ps: ParamSet, level: str, model_form: str, campaign_id: str,
                   seed, warm_temperature_k: float):
    """Guarded evaluation with a warm-started thermal solve.

    IMPORTANT: this is a thin wrapper around the ONE solve path
    (:func:`apmt.multifidelity.levels.evaluate_with_options`). It deliberately does
    not re-implement optics, the electrical solve or the thermal loop -- an earlier
    version did, which meant a batch row evaluated through the warm path carried
    different provenance metadata from the same row evaluated serially (found by
    ``test_batch_api_and_serial_guarded_agree``). Warm starting is only a solver
    hint; the physics and the record layout are identical by construction.
    """
    from ..multifidelity.levels import evaluate_with_options, options_for
    from ..validation.guard import judge_tandem
    from ..validation.guard import SolveRecord as _SR

    opts = options_for(level)
    t0 = time.perf_counter()
    try:
        res = evaluate_with_options(opts, ps, model_form=model_form,
                                    initial_temperature_k=warm_temperature_k)
    except Exception as exc:                                       # noqa: BLE001
        from ..validation.invariants import InvariantBundle
        return _SR(None, InvariantBundle(tuple()), False, time.perf_counter() - t0,
                   level, campaign_id=campaign_id, seed=seed, solver="fast-warm",
                   error=f"{type(exc).__name__}: {exc}")
    verdict = judge_tandem(res, level=level,
                           context={"level": level, "model_form": model_form,
                                    "solver": "fast-warm"})
    res.detail["invariants"] = verdict.to_dict()
    res.detail["solve_valid"] = bool(verdict.valid)
    try:
        point = ps.to_dict()
    except Exception:                                        # pragma: no cover
        point = {}
    return _SR(res, verdict, verdict.valid, time.perf_counter() - t0, level,
               parameter_values=point, campaign_id=campaign_id, seed=seed,
               solver="fast-warm")


# ---------------------------------------------------------------------------
# surrogate-ready dataset interface
# ---------------------------------------------------------------------------
def dataset(records: Sequence[SolveRecord], names: Sequence[str],
            parameters: Optional[np.ndarray] = None) -> dict:
    """Build a surrogate-training dataset from guarded records.

    Only VALID records become rows: a physically invalid solve must never
    contaminate training data. The returned structure records the rejection
    accounting so the exclusion is auditable rather than silent.
    """
    X, y, meta = [], [], []
    rejected = []
    for i, rec in enumerate(records):
        if not rec.valid:
            rejected.append({"index": i, "reason": [f.name for f in rec.verdict.failures]
                             or [rec.error or "invalid"]})
            continue
        if parameters is not None:
            X.append(np.asarray(parameters[i], dtype=float))
        y.append([rec.result.pce_pct, rec.result.jsc_ma_cm2, rec.result.voc_v,
                  rec.result.ff, rec.result.temperature_k])
        meta.append({"level": rec.level, "solver": rec.solver,
                     "campaign_id": rec.campaign_id, "runtime_s": rec.runtime_s})
    return {
        "feature_names": list(names),
        "target_names": ["pce_pct", "jsc_ma_cm2", "voc_v", "ff", "temperature_k"],
        "X": np.asarray(X) if X else np.empty((0, len(names))),
        "y": np.asarray(y) if y else np.empty((0, 5)),
        "meta": meta,
        "n_rows": len(y),
        "n_rejected": len(rejected),
        "rejected": rejected,
        "note": "rows are VALID guarded solves only; invalid physics is never "
                "training data",
    }


def lhs_batch(n_samples: int, names: Sequence[str], seed: int = 0, **kwargs):
    """Convenience: LHS sample + guarded batch evaluation.

    The sampling seed is also recorded on every result record (reproducibility
    metadata travels with the data, not only with the sampling call).
    """
    from ..sensitivity.lhs import lhs_matrix
    X = lhs_matrix(names, n_samples, seed)
    kwargs.setdefault("seed", seed)
    return batch_evaluate(X, names, **kwargs)
