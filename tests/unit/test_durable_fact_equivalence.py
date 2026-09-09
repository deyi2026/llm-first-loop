from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.qualify_durable_fact_equivalence import (
    EquivalenceError,
    normalize_durable_events,
    qualify,
)


def _payload() -> dict:
    return {
        "model": "ornith-test",
        "messages": [{"role": "user", "content": "inspect exact state"}],
        "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
    }


def _events(*, suffix: str, cache_hit: int, runtime_pid: int) -> list[dict]:
    sid = f"session-{suffix}"
    execution_id = f"execution-{suffix}"
    artifact_ref = f"artifact://v1/{suffix * 32}"[:46]
    return [
        {
            "event_id": f"event-created-{suffix}",
            "session_id": sid,
            "seq": 1,
            "ts": f"2026-09-07T00:00:0{suffix}Z",
            "type": "session.created",
            "payload": {},
        },
        {
            "event_id": f"event-tool-{suffix}",
            "session_id": sid,
            "seq": 2,
            "ts": f"2026-09-07T00:00:1{suffix}Z",
            "type": "tool.execution.finished",
            "payload": {
                "execution_id": execution_id,
                "tool_call_id": f"call-{suffix}",
                "tool_name": "edit_file",
                "status": "success",
                "result_sha256": "a" * 64,
                "artifact_ref": artifact_ref,
                "effect_sha256": "b" * 64,
            },
        },
        {
            "event_id": f"event-usage-{suffix}",
            "session_id": sid,
            "seq": 3,
            "ts": f"2026-09-07T00:00:2{suffix}Z",
            "type": "request.usage",
            "payload": {
                "round": 1,
                "model": "ornith-test",
                "tokens_in": 1000,
                "tokens_out": 20,
                "cache_hit": cache_hit,
                "cache_miss": 1000 - cache_hit,
                "cache_read_tokens": cache_hit,
                "uncached_prompt_tokens": 1000 - cache_hit,
                "cache_hit_rate": cache_hit / 1000,
                "runtime_pid": runtime_pid,
                "stable_prefix_fp": "stable-prefix",
                "prefix_changed": False,
                "prefix_change_reason": "",
                "cache_prefix_epoch": 0,
                "compaction_epoch": 0,
                "context_window": 4096,
                "output_reserve_tokens": 512,
                "context_headroom_tokens": 2584,
                "context_used_ratio": 1512 / 4096,
                "usage_available": True,
            },
        },
        {
            "event_id": f"event-end-{suffix}",
            "session_id": sid,
            "seq": 4,
            "ts": f"2026-09-07T00:00:3{suffix}Z",
            "type": "run.end",
            "payload": {"reason": "completed", "rounds": 1},
        },
    ]


def test_compute_only_cache_and_runtime_deltas_are_allowed() -> None:
    result = qualify(
        off_provider_payload=_payload(),
        on_provider_payload=_payload(),
        off_events=_events(suffix="a", cache_hit=0, runtime_pid=101),
        on_events=_events(suffix="b", cache_hit=900, runtime_pid=202),
    )

    assert result.provider_payload_invariant is True
    assert result.behavioral_delta == 0
    assert result.compute_delta is True
    assert result.off_behavior_sha256 == result.on_behavior_sha256


def test_opaque_ids_are_structurally_normalized_not_byte_compared() -> None:
    off = normalize_durable_events(_events(suffix="a", cache_hit=0, runtime_pid=101))
    on = normalize_durable_events(_events(suffix="b", cache_hit=0, runtime_pid=101))
    assert off == on
    assert off[1]["payload"]["execution_id"] == "<execution:1>"
    assert off[1]["payload"]["artifact_ref"] == "<artifact:1>"


def test_provider_visible_payload_must_be_exact() -> None:
    on_payload = _payload()
    on_payload["messages"] = [
        {"role": "system", "content": "cache_tag=goal"},
        *on_payload["messages"],
    ]
    with pytest.raises(EquivalenceError, match="provider-visible payload invariant"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=on_payload,
            off_events=_events(suffix="a", cache_hit=0, runtime_pid=101),
            on_events=_events(suffix="b", cache_hit=900, runtime_pid=202),
        )


@pytest.mark.parametrize(
    ("event_index", "payload_key", "value"),
    [
        (1, "result_sha256", "f" * 64),
        (1, "effect_sha256", "e" * 64),
        (3, "reason", "llm_error"),
    ],
)
def test_durable_protocol_fact_changes_fail(
    event_index: int, payload_key: str, value: object
) -> None:
    off = _events(suffix="a", cache_hit=0, runtime_pid=101)
    on = _events(suffix="b", cache_hit=900, runtime_pid=202)
    on[event_index]["payload"][payload_key] = value
    with pytest.raises(EquivalenceError, match="durable behavioral facts differ"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=_payload(),
            off_events=off,
            on_events=on,
        )


def test_request_usage_model_and_prefix_facts_are_not_compute_ignored() -> None:
    off = _events(suffix="a", cache_hit=0, runtime_pid=101)
    on = _events(suffix="b", cache_hit=900, runtime_pid=202)
    on[2]["payload"]["model"] = "different-model"
    with pytest.raises(EquivalenceError, match="durable behavioral facts differ"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=_payload(),
            off_events=off,
            on_events=on,
        )

    on = _events(suffix="b", cache_hit=900, runtime_pid=202)
    on[2]["payload"]["stable_prefix_fp"] = "different-prefix"
    with pytest.raises(EquivalenceError, match="durable behavioral facts differ"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=_payload(),
            off_events=off,
            on_events=on,
        )


def test_semantic_fields_are_never_ignored_by_name() -> None:
    off = _events(suffix="a", cache_hit=0, runtime_pid=101)
    on = _events(suffix="b", cache_hit=900, runtime_pid=202)
    off.insert(
        3,
        {
            "event_id": "off-semantic",
            "session_id": "session-a",
            "seq": 4,
            "ts": "2026-09-07T00:00:30Z",
            "type": "qualification.fixture",
            "payload": {"goal": "A", "completion": False, "retry": False, "cache_tag": "x"},
        },
    )
    on.insert(
        3,
        {
            "event_id": "on-semantic",
            "session_id": "session-b",
            "seq": 4,
            "ts": "2026-09-07T00:00:31Z",
            "type": "qualification.fixture",
            "payload": {"goal": "B", "completion": True, "retry": True, "cache_tag": "y"},
        },
    )
    with pytest.raises(EquivalenceError, match="durable behavioral facts differ"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=_payload(),
            off_events=off,
            on_events=on,
        )


def test_cli_reports_hashes_without_dumping_payload_content(tmp_path: Path) -> None:
    off = {
        "provider_payload": _payload(),
        "events": _events(suffix="a", cache_hit=0, runtime_pid=101),
    }
    on = {
        "provider_payload": _payload(),
        "events": _events(suffix="b", cache_hit=900, runtime_pid=202),
    }
    off_path = tmp_path / "off.json"
    on_path = tmp_path / "on.json"
    off_path.write_text(json.dumps(off), encoding="utf-8")
    on_path.write_text(json.dumps(on), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/qualify_durable_fact_equivalence.py",
            str(off_path),
            str(on_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["qualified"] is True
    assert report["behavioral_delta"] == 0
    assert report["compute_delta"] is True
    assert "inspect exact state" not in proc.stdout


def test_session_topology_relation_is_preserved_across_parent_child_keys() -> None:
    off = _events(suffix="a", cache_hit=0, runtime_pid=101)
    on = _events(suffix="b", cache_hit=900, runtime_pid=202)
    off.insert(
        1,
        {
            "event_id": "off-link",
            "session_id": "session-a",
            "seq": 2,
            "ts": "2026-09-07T00:00:05Z",
            "type": "subagent.linked",
            "payload": {"parent_id": "session-a", "child_id": "child-a", "generation": "gen-a"},
        },
    )
    on.insert(
        1,
        {
            "event_id": "on-link",
            "session_id": "session-b",
            "seq": 2,
            "ts": "2026-09-07T00:00:06Z",
            "type": "subagent.linked",
            "payload": {
                "parent_id": "different-parent-b",
                "child_id": "child-b",
                "generation": "gen-b",
            },
        },
    )
    with pytest.raises(EquivalenceError, match="durable behavioral facts differ"):
        qualify(
            off_provider_payload=_payload(),
            on_provider_payload=_payload(),
            off_events=off,
            on_events=on,
        )


def test_real_event_objects_are_accepted_and_volatile_event_identity_is_ignored(
    tmp_path: Path,
) -> None:
    from llm_loop.event_log.store import EventStore

    left = EventStore(tmp_path / "left", enabled=True)
    right = EventStore(tmp_path / "right", enabled=True)
    left.append("session-left", "session.created", {})
    right.append("session-right", "session.created", {})
    left.append(
        "session-left",
        "run.end",
        {"reason": "completed", "rounds": 1},
    )
    right.append(
        "session-right",
        "run.end",
        {"reason": "completed", "rounds": 1},
    )

    result = qualify(
        off_provider_payload=_payload(),
        on_provider_payload=_payload(),
        off_events=left.read("session-left"),
        on_events=right.read("session-right"),
    )
    assert result.behavioral_delta == 0
