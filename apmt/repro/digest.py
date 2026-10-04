"""Physics digest — separate the SCIENCE of an artifact from its wall clock.

Several V1.9-C artifacts legitimately differ between machines: they embed
wall-clock timings (and the git commit of the run). Their *scientific* content,
however, is deterministic. This module defines the one function that decides what
"the science" of such an artifact is, so that

* the generator (``tools/v19_engine_campaign.py``),
* CI (``tools/ci_checks.py``) and
* the test suite (``tests/test_v19_batch_surrogate.py``)

all recompute the digest with exactly the same rule. A single definition is the
only way a digest can be a meaningful check.

Rule: drop the explicitly excluded top-level blocks (timing benchmarks and the
environment block, which carries the commit hash), then recursively drop every
mapping entry whose key looks like a timing (wall clock, runtime, throughput,
elapsed seconds). Everything else — every physical number, every validity flag,
every parameter point — is inside the digest.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

#: top-level blocks excluded wholesale
EXCLUDED_BLOCKS = ("benchmark", "metadata", "physics_digest")

#: key patterns that identify machine-specific timing quantities
# NOTE: deliberately NOT a generic ``_s$`` rule — ``perovskite_srv_cm_s`` and
# ``silicon_srv_cm_s`` are surface recombination velocities (cm/s), i.e. science.
_TIMING_KEYS = re.compile(
    r"(wall_clock|runtime|run_time|elapsed|solves_per_second|per_second|"
    r"duration|timestamp|_seconds$|^seconds$|solve_time)",
    re.IGNORECASE,
)


def strip_timings(obj: Any) -> Any:
    """Recursively remove timing-valued entries from a JSON-like structure."""
    if isinstance(obj, dict):
        return {k: strip_timings(v) for k, v in obj.items()
                if not _TIMING_KEYS.search(str(k))}
    if isinstance(obj, (list, tuple)):
        return [strip_timings(v) for v in obj]
    return obj


def physics_view(artifact: dict) -> dict:
    """The scientific view of an artifact: excluded blocks + timings removed."""
    body = {k: v for k, v in artifact.items() if k not in EXCLUDED_BLOCKS}
    return strip_timings(body)


def physics_digest(artifact: dict) -> str:
    """sha256 over the canonical (sorted-key) JSON of the physics view."""
    payload = json.dumps(physics_view(artifact), sort_keys=True,
                         default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def digest_block(artifact: dict) -> dict:
    """The ``physics_digest`` block an artifact stores about itself."""
    return {
        "algorithm": "sha256 over canonical json of the artifact with the "
                     "benchmark/metadata blocks and all timing-valued keys removed",
        "sha256": physics_digest(artifact),
        "excluded": [f"block:{b}" for b in EXCLUDED_BLOCKS] +
                    ["any key matching wall_clock|runtime|elapsed|"
                     "solves_per_second|seconds|duration|timestamp"],
    }
