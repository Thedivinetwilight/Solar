"""Versioned, validity-aware data contract for surrogate campaigns.

Raw historical campaign artifacts are never rewritten.  This module only builds
new derived records and deliberately separates usable outputs from the rejection
ledger.  An invalid physics solve has no numeric output payload in the ledger.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

DATA_CONTRACT_VERSION = "apmt-surrogate-data/1.0"
VALID_FOR_SURROGATE = "VALID_FOR_SURROGATE"
INVALID_PHYSICS = "INVALID_PHYSICS"
OUTSIDE_VERIFIED_DOMAIN = "OUTSIDE_VERIFIED_DOMAIN"
INCOMPLETE_OUTPUT = "INCOMPLETE_OUTPUT"
DUPLICATE_OR_DEPENDENT = "DUPLICATE_OR_DEPENDENT"
UNRESOLVED_DATA = "UNRESOLVED_DATA"
STATUSES = (VALID_FOR_SURROGATE, INVALID_PHYSICS, OUTSIDE_VERIFIED_DOMAIN,
            INCOMPLETE_OUTPUT, DUPLICATE_OR_DEPENDENT, UNRESOLVED_DATA)

CORE_OUTPUTS = ("pce_pct", "jsc_ma_cm2", "voc_v", "ff", "temperature_k")
OUTPUT_UNITS = {
    "pce_pct": "%", "jsc_ma_cm2": "mA/cm2", "voc_v": "V", "ff": "1",
    "temperature_k": "K", "j_top_sc": "mA/cm2", "j_bottom_sc": "mA/cm2",
    "current_matching_ratio": "1", "heat_load_mw_cm2": "mW/cm2",
    "conduction_loss_mw_cm2": "mW/cm2", "radiative_loss_mw_cm2": "mW/cm2",
}
OUTPUT_NAMES = tuple(OUTPUT_UNITS)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str).encode("utf-8")


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _json_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if np.isfinite(out) else None


def design_fingerprint(parameters: Mapping[str, float], feature_names: Sequence[str]) -> str:
    """Identity of a parameter vector, independent of regime and fidelity."""
    vector = [(str(n), float(parameters[n]).hex()) for n in feature_names]
    return _sha({"features": vector})


def physics_configuration_digest(*, model_code_digest: str, registry_digest: str,
                                 level: str, model_form: str, regime: Mapping[str, Any],
                                 solver_options: Mapping[str, Any]) -> str:
    """Fingerprint the deterministic model/configuration used to label outputs."""
    return _sha({"contract": DATA_CONTRACT_VERSION,
                 "model_code_digest": model_code_digest,
                 "registry_digest": registry_digest,
                 "level": str(level), "model_form": str(model_form),
                 "regime": dict(regime), "solver_options": dict(solver_options)})


def _extract_outputs(result: Any) -> dict[str, float | None]:
    detail = getattr(result, "detail", {}) or {}
    thermal = detail.get("thermal", {}) if isinstance(detail, dict) else {}
    out = {
        "pce_pct": getattr(result, "pce_pct", None),
        "jsc_ma_cm2": getattr(result, "jsc_ma_cm2", None),
        "voc_v": getattr(result, "voc_v", None),
        "ff": getattr(result, "ff", None),
        "temperature_k": getattr(result, "temperature_k", None),
        "j_top_sc": getattr(result, "j_top_sc", None),
        "j_bottom_sc": getattr(result, "j_bottom_sc", None),
        "current_matching_ratio": getattr(result, "current_matching_ratio", None),
        "heat_load_mw_cm2": thermal.get("heat_load_mw_cm2"),
        "conduction_loss_mw_cm2": thermal.get("conduction_loss_mw_cm2"),
        "radiative_loss_mw_cm2": thermal.get("radiative_loss_mw_cm2"),
    }
    return {name: _json_float(value) for name, value in out.items()}


def _hard_invariants(verdict: Any) -> list[dict]:
    records = getattr(verdict, "records", ()) or ()
    rows = []
    for item in records:
        severity = getattr(getattr(item, "severity", None), "value",
                           getattr(item, "severity", None))
        if severity != "HARD":
            continue
        status = getattr(getattr(item, "status", None), "value",
                         getattr(item, "status", None))
        rows.append({
            "name": str(getattr(item, "name", "")),
            "group": str(getattr(item, "group", "")),
            "status": str(status),
            "severity": "HARD",
            "measured": _json_float(getattr(item, "measured", None)),
            "limit": _json_float(getattr(item, "limit", None)),
            "tolerance": _json_float(getattr(item, "tolerance", None)),
            "units": str(getattr(item, "units", "")),
        })
    return rows


def make_sample_record(*, solve_record: Any, feature_names: Sequence[str],
                       regime: Mapping[str, Any], role: str, design_family: str,
                       seed: int, model_form: str, physics_digest: str,
                       verified_low: Mapping[str, float],
                       verified_high: Mapping[str, float],
                       solver_options: Mapping[str, Any] | None = None,
                       paired_design_id: str = "") -> dict:
    """Convert a guarded L4/L5 result into one contract-v1 record.

    ``INVALID_PHYSICS`` and ``INCOMPLETE_OUTPUT`` rows never carry regressand
    labels.  Points outside the verified box may retain diagnostic outputs, but
    their status prevents regression training and prediction acceptance.
    """
    feature_names = tuple(feature_names)
    params = dict(getattr(solve_record, "parameter_values", {}) or {})
    params = {str(k): _json_float(v) for k, v in params.items()}
    regime_dict = {str(k): (float(v) if isinstance(v, (int, float, np.number)) else v)
                   for k, v in dict(regime).items()}
    level = str(getattr(solve_record, "level", ""))
    verdict = getattr(solve_record, "verdict", None)
    hard = _hard_invariants(verdict)
    hard_failures = [r["name"] for r in hard if r["status"] == "FAIL"]
    valid_flag = bool(getattr(solve_record, "valid", False))
    has_features = all(n in params and params[n] is not None for n in feature_names)
    inside = has_features and all(
        float(verified_low[n]) - 1e-12 <= float(params[n]) <= float(verified_high[n]) + 1e-12
        for n in feature_names)
    result = getattr(solve_record, "result", None)
    outputs = _extract_outputs(result) if result is not None else {k: None for k in OUTPUT_NAMES}
    missing_core = [n for n in CORE_OUTPUTS if outputs.get(n) is None]
    unresolved = (not has_features or len(params) == 0 or not regime_dict or not level
                  or not str(getattr(solve_record, "campaign_id", "")))

    if unresolved:
        status = UNRESOLVED_DATA
    elif not valid_flag or hard_failures:
        status = INVALID_PHYSICS
    elif missing_core:
        status = INCOMPLETE_OUTPUT
    elif not inside:
        status = OUTSIDE_VERIFIED_DOMAIN
    else:
        status = VALID_FOR_SURROGATE

    # Invalid physics outputs are not retained as numbers.  Incomplete records
    # retain only their finite partial diagnostic values and cannot train any
    # target because their status is not VALID_FOR_SURROGATE.
    if status == INVALID_PHYSICS:
        outputs_payload = None
    else:
        outputs_payload = outputs

    sample = {
        "contract_version": DATA_CONTRACT_VERSION,
        "sample_id": "",
        "input_fingerprint": "",
        "design_point_fingerprint": "",
        "physics_digest": str(physics_digest),
        "feature_names": list(feature_names),
        "parameters": params,
        "operating_regime": regime_dict,
        "model_level": level,
        "model_form": str(model_form),
        "solver_options": dict(solver_options or {}),
        "solve_valid": bool(valid_flag),
        "hard_invariants": hard,
        "hard_invariant_failures": hard_failures,
        "campaign_id": str(getattr(solve_record, "campaign_id", "")),
        "design_family": str(design_family),
        "paired_design_id": str(paired_design_id),
        "random_seed": int(seed),
        "role": str(role),
        "status": status,
        "status_reason": ("; ".join(hard_failures) if hard_failures else
                          ("missing required outputs: " + ", ".join(missing_core)
                           if missing_core else
                           "point lies outside the shared verified box" if not inside
                           else "")),
        "outputs": outputs_payload,
        "output_units": OUTPUT_UNITS,
        "runtime_s": float(getattr(solve_record, "runtime_s", 0.0) or 0.0),
        "solver": str(getattr(solve_record, "solver", "")),
        "solver_termination_status": _termination_status(result, valid_flag),
        "error": str(getattr(solve_record, "error", "") or ""),
    }
    if has_features:
        sample["design_point_fingerprint"] = design_fingerprint(params, feature_names)
        sample["input_fingerprint"] = _sha({
            "design_point_fingerprint": sample["design_point_fingerprint"],
            "operating_regime": regime_dict, "model_level": level,
            "model_form": model_form, "physics_digest": physics_digest,
            "solver_options": dict(solver_options or {}),
        })
        sample["sample_id"] = sample["input_fingerprint"][:24]
    else:
        sample["sample_id"] = _sha({"role": role, "campaign": getattr(solve_record, "campaign_id", ""),
                                    "seed": seed, "params": params})[:24]
    return sample


def _termination_status(result: Any, valid: bool) -> str:
    if result is None:
        return "SOLVE_FAILED"
    detail = getattr(result, "detail", {}) or {}
    thermal = detail.get("thermal", {}) if isinstance(detail, dict) else {}
    if not bool(getattr(result, "coupling_converged", True)):
        return "COUPLING_NOT_CONVERGED"
    if thermal.get("model") == "energy_balance" and not bool(thermal.get("converged", False)):
        return "THERMAL_NOT_CONVERGED"
    return "CONVERGED_VALID" if valid else "COMPLETED_INVALID"


def mark_duplicates(samples: Sequence[dict], *, tolerance: float = 1e-10) -> list[dict]:
    """Mark exact/effectively repeated inputs within regime, fidelity and model.

    The first unique sample retains its status; a later dependent record becomes
    ``DUPLICATE_OR_DEPENDENT`` and never receives a second regression weight.
    Cross-level L4/L5 pairs intentionally remain distinct and are linked by their
    ``design_point_fingerprint``/``paired_design_id``.
    """
    out = [dict(s) for s in samples]
    seen: dict[str, dict] = {}
    for row in out:
        if row.get("status") not in (VALID_FOR_SURROGATE, OUTSIDE_VERIFIED_DOMAIN):
            continue
        params = row.get("parameters") or {}
        # Quantize every stored parameter by a very small fraction of its registry
        # span: exact repeats and effectively identical float representations share
        # a key, while scientifically distinct parameter changes remain separate.
        try:
            from ..params.registry import spec
            quantized = []
            for name in sorted(params):
                value = params[name]
                if value is None:
                    quantized.append((name, None))
                    continue
                s = spec(name)
                span = max(float(s.high) - float(s.low), abs(float(s.default)), 1.0)
                quantized.append((name, round((float(value) - float(s.low)) / span / tolerance)))
        except Exception:  # noqa: BLE001 - preserve the raw-key fallback on any registry error
            quantized = sorted((str(k), str(v)) for k, v in params.items())
        base_key = _sha({"parameter_vector": quantized,
                         "operating_regime": row.get("operating_regime"),
                         "model_level": row.get("model_level"),
                         "model_form": row.get("model_form"),
                         "physics_digest": row.get("physics_digest")})
        prior = seen.get(base_key)
        if prior is not None:
            row["status_before_deduplication"] = row["status"]
            row["status"] = DUPLICATE_OR_DEPENDENT
            row["status_reason"] = f"duplicate/effectively dependent on {prior['sample_id']}"
            row["duplicate_of"] = prior["sample_id"]
            # Keep valid outputs as auditable raw solve evidence, but consumers
            # must use the status-aware training selector below.
        else:
            seen[base_key] = row
    return out


def training_rows(samples: Sequence[dict], *, regime_name: str,
                  level: str = "L4", allowed_roles: Iterable[str] = ("TRAIN", "ADAPTIVE_TRAIN")) -> list[dict]:
    """Select unique, valid, in-domain rows for regression; never imputes."""
    roles = set(allowed_roles)
    selected = []
    seen = set()
    for row in samples:
        if (row.get("status") != VALID_FOR_SURROGATE
                or row.get("model_level") != level
                or row.get("role") not in roles
                or row.get("operating_regime", {}).get("name") != regime_name
                or row.get("outputs") is None):
            continue
        key = row.get("input_fingerprint")
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected


def dataset_fingerprint(samples: Sequence[dict], *, roles: Iterable[str] | None = None,
                        regime_name: str | None = None, level: str | None = None) -> str:
    role_set = None if roles is None else set(roles)
    rows = []
    for s in samples:
        if role_set is not None and s.get("role") not in role_set:
            continue
        if regime_name is not None and s.get("operating_regime", {}).get("name") != regime_name:
            continue
        if level is not None and s.get("model_level") != level:
            continue
        # Runtime and process-local solver metadata are intentionally excluded;
        # all coordinates, labels, statuses, invariant outcomes and provenance
        # remain part of the reproducible science fingerprint.
        rows.append({k: s.get(k) for k in (
            "input_fingerprint", "design_point_fingerprint", "physics_digest",
            "feature_names", "parameters", "operating_regime", "model_level", "model_form",
            "solver_options", "solver", "solver_termination_status", "solve_valid",
            "hard_invariants", "hard_invariant_failures", "campaign_id", "design_family",
            "paired_design_id", "random_seed", "role", "status",
            "status_before_deduplication", "status_reason", "duplicate_of", "outputs", "error")})
    def _row_order(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
        regime = row.get("operating_regime")
        if isinstance(regime, Mapping):
            # A regime's name is its stable primary identity.  Never sort by
            # ``str(dict)``: JSON serialization may reorder mapping keys, which
            # changes row order and therefore the fingerprint after a round-trip.
            regime_name = str(regime.get("name", ""))
            regime_canonical = _canonical(regime).decode("utf-8")
        else:
            regime_name = ""
            regime_canonical = _canonical(regime).decode("utf-8")
        return (regime_name, regime_canonical, str(row.get("model_level")),
                str(row.get("role")), str(row.get("input_fingerprint")))

    rows.sort(key=_row_order)
    return _sha({"contract_version": DATA_CONTRACT_VERSION, "records": rows})


def summarize_samples(samples: Sequence[dict]) -> dict:
    counts = Counter(s.get("status", UNRESOLVED_DATA) for s in samples)
    by_regime_level: dict[str, dict[str, dict[str, int]]] = {}
    for row in samples:
        regime = str(row.get("operating_regime", {}).get("name", "UNKNOWN"))
        level = str(row.get("model_level", "UNKNOWN"))
        bucket = by_regime_level.setdefault(regime, {}).setdefault(level, Counter())
        bucket[row.get("status", UNRESOLVED_DATA)] += 1
    return {
        "n_records": len(samples),
        "status_counts": {k: int(counts.get(k, 0)) for k in STATUSES},
        "by_regime_level": {
            r: {lv: {k: int(c.get(k, 0)) for k in STATUSES} for lv, c in lv_map.items()}
            for r, lv_map in by_regime_level.items()},
        "eligible_unique_training_rows": sum(
            1 for s in samples if s.get("status") == VALID_FOR_SURROGATE
            and s.get("role") in ("TRAIN", "ADAPTIVE_TRAIN")
            and s.get("model_level") == "L4"),
    }


def save_dataset(path: str | os.PathLike[str], samples: Sequence[dict], *,
                 metadata: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> dict:
    """Write an atomic, deterministic gzip JSON dataset; never mutate raw inputs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    deduped = mark_duplicates(samples)
    unknown_statuses = sorted({str(s.get("status")) for s in deduped
                               if s.get("status") not in STATUSES})
    if unknown_statuses:
        raise ValueError(f"dataset contains unknown sample statuses: {unknown_statuses}")
    invalid_with_outputs = [s.get("sample_id", "") for s in deduped
                            if s.get("status") == INVALID_PHYSICS
                            and s.get("outputs") is not None]
    if invalid_with_outputs:
        raise ValueError("INVALID_PHYSICS rows must not retain numeric outputs: "
                         + ", ".join(invalid_with_outputs[:5]))
    valid_records = [s for s in deduped if s.get("status") == VALID_FOR_SURROGATE]
    rejected = [s for s in deduped if s.get("status") != VALID_FOR_SURROGATE]
    body = {
        "contract_version": DATA_CONTRACT_VERSION,
        "label": "PRE-GATE / MODEL-OBSERVED / EXPLORATORY; L4/L5 simulations are not experimental data",
        "feature_schema": {"names": list(next((s["feature_names"] for s in deduped
                                                   if s.get("feature_names")), [])),
                           "units": dict(metadata.get("feature_units", {}))},
        "output_schema": {n: {"unit": u, "role": "regression target"}
                          for n, u in OUTPUT_UNITS.items()},
        "metadata": dict(metadata),
        "summary": summarize_samples(deduped),
        "dataset_fingerprint": dataset_fingerprint(deduped),
        "valid_records": valid_records,
        "rejection_ledger": rejected,
        "extra": dict(extra or {}),
    }
    from ..repro.digest import digest_block
    body["physics_digest"] = digest_block(body)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False, default=str).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with open(tmp_name, "wb") as raw_file, gzip.GzipFile(
                fileobj=raw_file, mode="wb", mtime=0, compresslevel=6) as gz:
            gz.write(raw)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return {"path": str(target), "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "dataset_fingerprint": body["dataset_fingerprint"],
            "physics_digest": body["physics_digest"]["sha256"],
            "summary": body["summary"]}


def load_dataset(path: str | os.PathLike[str]) -> dict:
    """Load and validate a data-contract artifact without promoting rejected rows."""
    p = Path(path)
    with gzip.open(p, "rt", encoding="utf-8") as f:
        body = json.load(f)
    if not isinstance(body, dict):
        raise TypeError("dataset root must be an object")
    if body.get("contract_version") != DATA_CONTRACT_VERSION:
        raise ValueError(f"unsupported surrogate data contract {body.get('contract_version')!r}")
    valid_records = body.get("valid_records")
    rejection_ledger = body.get("rejection_ledger")
    if not isinstance(valid_records, list) or not isinstance(rejection_ledger, list):
        raise TypeError("dataset must contain valid_records and rejection_ledger lists")
    if any(not isinstance(row, dict) for row in valid_records + rejection_ledger):
        raise ValueError("dataset record partitions may contain only objects")
    if any(row.get("status") != VALID_FOR_SURROGATE for row in valid_records):
        raise ValueError("valid_records may contain only VALID_FOR_SURROGATE rows")
    if any(row.get("status") not in STATUSES or row.get("status") == VALID_FOR_SURROGATE
           for row in rejection_ledger):
        raise ValueError("rejection_ledger must contain only recognized rejected statuses")
    if any(row.get("status") == INVALID_PHYSICS and row.get("outputs") is not None
           for row in rejection_ledger):
        raise ValueError("INVALID_PHYSICS rows must not retain numeric outputs")
    records = valid_records + rejection_ledger
    summary = body.get("summary")
    record_count = summary.get("n_records") if isinstance(summary, dict) else None
    if (isinstance(record_count, bool) or not isinstance(record_count, int)
            or record_count != len(records)):
        raise ValueError("dataset record partitions do not match the stored record count")
    fingerprint = dataset_fingerprint(records)
    if fingerprint != body.get("dataset_fingerprint"):
        raise ValueError("dataset fingerprint does not match its valid/rejected records")
    from ..repro.digest import physics_digest
    digest_block = body.get("physics_digest")
    stored_digest = digest_block.get("sha256") if isinstance(digest_block, dict) else None
    if not stored_digest or physics_digest(body) != stored_digest:
        raise ValueError("dataset physics digest is missing or invalid")
    return body
