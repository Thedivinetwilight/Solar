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


def _worker_init(level: str, model_form: str, campaign_id: str,
                 names: tuple, seed, base_dict: Optional[dict]) -> None:
    # V1.9-H: ALL worker state travels via initargs. An earlier revision set
    # names/seed in the parent process, so workers>1 only worked under fork
    # (spawn children raised KeyError). base_dict (None = registry defaults)
    # is passed too: the worker previously ignored `base`, silently diverging
    # from the serial path whenever a non-default base was given.
    _WORKER_STATE.update(level=level, model_form=model_form,
                         campaign_id=campaign_id, names=tuple(names), seed=seed,
                         base_dict=dict(base_dict) if base_dict else None)


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
                   self_heating: bool = True,
                   mp_context: Optional[str] = None) -> tuple:
    """Evaluate a matrix of parameters (n_samples x n_parameters).

    Returns ``(records, summary)``. ``records[i]`` corresponds to
    ``matrix[i]``: order is preserved for both the serial and the parallel path.
    ``mp_context`` selects the multiprocessing start method (None = platform
    default; "spawn" is supported and regression-tested).
    """
    names = tuple(names)
    X = np.atleast_2d(np.asarray(matrix, dtype=float))
    if X.shape[1] != len(names):
        raise ValueError(f"matrix has {X.shape[1]} columns but {len(names)} names")
    base_ps = base or ParamSet.defaults()
    lo, hi = sample_bounds(names)
    n_clipped = int(((X < lo) | (X > hi)).sum())
    if n_clipped:
        import warnings
        # V1.9-H: the clip itself is correct (never evaluate outside the
        # registered ranges; records carry the clipped values), but it was
        # silent. Callers that spray outside the box are told, once per call.
        warnings.warn(f"batch_evaluate clipped {n_clipped} out-of-range "
                      f"entries to the registered bounds", UserWarning,
                      stacklevel=2)
    X = np.clip(X, lo, hi)
    t0 = time.perf_counter()
    records: list = []

    if workers and workers > 1:
        import multiprocessing as mp
        ctx = mp.get_context(mp_context)
        with ctx.Pool(processes=int(workers), initializer=_worker_init,
                      initargs=(level, model_form, campaign_id, names, seed,
                                base_ps.to_dict())) as pool:
            for i, rec in pool.imap(_worker_eval_meta,
                                    [(i, row.tolist()) for i, row in enumerate(X)]):
                records.append((i, rec))
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
    base_dict = _WORKER_STATE["base_dict"]
    start = (ParamSet.defaults().with_mapping(base_dict) if base_dict
             else ParamSet.defaults())
    ps = start.with_mapping(dict(zip(names, values)))
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
        # a failed solve must be INVALID in the VERDICT too, not only in the flag
        # (an empty bundle would report status PASS) -- same contract as
        # apmt.validation.guard.evaluate_guarded
        from ..validation.invariants import (InvariantBundle, InvariantGroup, Severity,
                                             record as _record)
        bundle = InvariantBundle((_record("numerical.solve_completed",
                                          InvariantGroup.NUMERICAL.value, False,
                                          severity=Severity.HARD,
                                          message=f"{type(exc).__name__}: {exc}"),))
        return _SR(None, bundle, False, time.perf_counter() - t0,
                   level, campaign_id=campaign_id, seed=seed, solver="fast-warm",
                   error=f"{type(exc).__name__}: {exc}")
    # V1.9-H: the warm path judged WITHOUT the optical bundle, so warm
    # records carried fewer invariant records than the same row evaluated
    # cold/serially. Mirror evaluate_guarded: optics are lru-cached, the solve
    # has already paid for them.
    from ..device.tandem import optics_for
    from ..validation.guard import judge_optics
    from ..validation.invariants import InvariantBundle as _B
    from ..validation.invariants import record as _record2
    try:
        optical_bundle = judge_optics(optics_for(ps, model_form=model_form))
    except Exception as exc:                                   # noqa: BLE001
        from ..validation.invariants import InvariantGroup as _G, Severity as _S
        optical_bundle = _B((_record2(
            "optical.available", _G.OPTICAL.value, False, severity=_S.HARD,
            message=f"optics could not be evaluated: "
                    f"{type(exc).__name__}: {exc}"),))
    verdict = judge_tandem(res, level=level, optical_bundle=optical_bundle,
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
