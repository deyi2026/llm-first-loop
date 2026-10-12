#!/usr/bin/env python3
"""Deterministic Durable Fact Equivalence qualification helper.

This is test/qualification tooling, not runtime policy. It compares two execution
snapshots after removing only an explicit fixed set of compute-only telemetry
fields. It never scores answer quality, evidence relevance, tool strategy, or
hidden reasoning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Only these fields are ignored, and only inside request.usage payloads.
# Structural/provider/model fields remain part of the behavioral comparison.
REQUEST_USAGE_COMPUTE_ONLY_FIELDS = frozenset(
    {
        "cache_hit",
        "cache_miss",
        "cache_read_tokens",
        "uncached_prompt_tokens",
        "cache_hit_rate",
        "runtime_pid",
        # Reserved for an explicitly mechanical backend observation carried in
        # request.usage in a future integration. Adding a new field here requires
        # review; fields elsewhere are never ignored by name alone.
        "actual_reused_prefix_tokens",
        "new_prefill_tokens",
        "admission",
        "eviction",
        "resident_capacity_bytes",
        "latency_ms",
    }
)

# Per-run opaque identities are normalized structurally so two independent arms
# can be compared without requiring identical UUIDs. Repeated references still
# have to preserve the same relationship graph within each arm.
OPAQUE_IDENTITY_DOMAINS = {
    # Session topology keys intentionally share one domain: parent/child/owner
    # relations must survive normalization rather than being normalized per key.
    "session_id": "session",
    "parent_id": "session",
    "child_id": "session",
    "owner_session_id": "session",
    "parent_session_id": "session",
    "child_session_id": "session",
    "run_id": "run",
    "job_id": "job",
    "execution_id": "execution",
    "tool_call_id": "tool_call",
    "artifact_ref": "artifact",
    "artifact_refs": "artifact",
    "evidence_ref": "evidence",
    "evidence_refs": "evidence",
    "generation": "generation",
}

_VOLATILE_EVENT_KEYS = frozenset({"event_id", "seq", "ts"})


class EquivalenceError(AssertionError):
    """Raised when a qualification invariant differs across two arms."""


@dataclass(frozen=True)
class QualificationResult:
    provider_payload_invariant: bool
    behavioral_delta: int
    compute_delta: bool
    off_behavior_sha256: str
    on_behavior_sha256: str
    off_payload_sha256: str
    on_payload_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_payload_invariant": self.provider_payload_invariant,
            "behavioral_delta": self.behavioral_delta,
            "compute_delta": self.compute_delta,
            "off_behavior_sha256": self.off_behavior_sha256,
            "on_behavior_sha256": self.on_behavior_sha256,
            "off_payload_sha256": self.off_payload_sha256,
            "on_payload_sha256": self.on_payload_sha256,
        }


class _IdentityNormalizer:
    def __init__(self) -> None:
        self._maps: dict[str, dict[str, str]] = {}

    def normalize(self, key: str, value: object) -> object:
        domain = OPAQUE_IDENTITY_DOMAINS.get(key)
        if domain is None or not isinstance(value, str) or not value:
            return value
        bucket = self._maps.setdefault(domain, {})
        if value not in bucket:
            bucket[value] = f"<{domain}:{len(bucket) + 1}>"
        return bucket[value]


def _plain(value: Any) -> Any:
    """Convert event-like objects/dataclasses into ordinary JSON-compatible values."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    if hasattr(value, "__dict__"):
        return {str(k): _plain(v) for k, v in vars(value).items()}
    return value


def _normalize_value(value: Any, *, key: str, ids: _IdentityNormalizer) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _normalize_value(v, key=str(k), ids=ids)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        domain = OPAQUE_IDENTITY_DOMAINS.get(key)
        if domain is not None:
            singular_key = {"artifact": "artifact_ref", "evidence": "evidence_ref"}.get(domain, key)
            return [_normalize_value(v, key=singular_key, ids=ids) for v in value]
        return [_normalize_value(v, key=key, ids=ids) for v in value]
    return ids.normalize(key, value)


def normalize_durable_events(events: Sequence[Any]) -> list[dict[str, Any]]:
    """Return the mechanically comparable durable fact stream.

    Event order is preserved. Event UUID/timestamp/absolute sequence are omitted,
    while opaque owner/resource identities are normalized by first-seen topology.
    Only the fixed request.usage compute telemetry fields are ignored.
    """
    ids = _IdentityNormalizer()
    normalized: list[dict[str, Any]] = []
    for raw in events:
        event = _plain(raw)
        if not isinstance(event, Mapping):
            raise TypeError("event must be a mapping or event-like object")
        etype = str(event.get("type") or "")
        if not etype:
            raise ValueError("event type is required")
        projected = {
            str(k): v for k, v in event.items() if str(k) not in _VOLATILE_EVENT_KEYS
        }
        payload = projected.get("payload")
        if etype == "request.usage" and isinstance(payload, Mapping):
            projected["payload"] = {
                str(k): v
                for k, v in payload.items()
                if str(k) not in REQUEST_USAGE_COMPUTE_ONLY_FIELDS
            }
        normalized.append(_normalize_value(projected, key="", ids=ids))
    return normalized


def extract_compute_telemetry(events: Sequence[Any]) -> list[dict[str, Any]]:
    """Extract allowed compute-only request.usage fields for non-gating reporting."""
    out: list[dict[str, Any]] = []
    for raw in events:
        event = _plain(raw)
        if not isinstance(event, Mapping) or str(event.get("type") or "") != "request.usage":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        row = {
            str(k): _plain(v)
            for k, v in payload.items()
            if str(k) in REQUEST_USAGE_COMPUTE_ONLY_FIELDS
        }
        out.append(row)
    return out


def _canonical_json(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def qualify(
    *,
    off_provider_payload: Any,
    on_provider_payload: Any,
    off_events: Sequence[Any],
    on_events: Sequence[Any],
) -> QualificationResult:
    """Assert payload identity and durable-fact equivalence; allow only compute deltas."""
    off_payload_hash = _sha256(off_provider_payload)
    on_payload_hash = _sha256(on_provider_payload)
    if off_payload_hash != on_payload_hash:
        raise EquivalenceError(
            "provider-visible payload invariant failed "
            f"(off={off_payload_hash[:12]} on={on_payload_hash[:12]})"
        )

    off_behavior = normalize_durable_events(off_events)
    on_behavior = normalize_durable_events(on_events)
    off_behavior_hash = _sha256(off_behavior)
    on_behavior_hash = _sha256(on_behavior)
    if off_behavior_hash != on_behavior_hash:
        raise EquivalenceError(
            "durable behavioral facts differ "
            f"(off={off_behavior_hash[:12]} on={on_behavior_hash[:12]})"
        )

    compute_delta = _canonical_json(extract_compute_telemetry(off_events)) != _canonical_json(
        extract_compute_telemetry(on_events)
    )
    return QualificationResult(
        provider_payload_invariant=True,
        behavioral_delta=0,
        compute_delta=compute_delta,
        off_behavior_sha256=off_behavior_hash,
        on_behavior_sha256=on_behavior_hash,
        off_payload_sha256=off_payload_hash,
        on_payload_sha256=on_payload_hash,
    )


def _load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"snapshot must be a JSON object: {path}")
    if "provider_payload" not in data or not isinstance(data.get("events"), list):
        raise ValueError(f"snapshot requires provider_payload + events[]: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two LFL durable-fact snapshots while allowing compute-only telemetry deltas."
    )
    parser.add_argument("off_snapshot", type=Path)
    parser.add_argument("on_snapshot", type=Path)
    args = parser.parse_args()
    off = _load_snapshot(args.off_snapshot)
    on = _load_snapshot(args.on_snapshot)
    try:
        result = qualify(
            off_provider_payload=off["provider_payload"],
            on_provider_payload=on["provider_payload"],
            off_events=off["events"],
            on_events=on["events"],
        )
    except (EquivalenceError, TypeError, ValueError) as exc:
        print(json.dumps({"qualified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"qualified": True, **result.as_dict()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
