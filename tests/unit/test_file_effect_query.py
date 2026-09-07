from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.event_log.model import (
    EVENT_HUMAN_FILE_EDIT_OBSERVED,
    EVENT_HUMAN_FILE_EDIT_PREPARED,
    EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
    EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
    REGISTRY,
)
from llm_loop.event_log.store import EventStore
from llm_loop.workspace.file_effect_query import FileEffectQueryError, FileEffectQueryService


def _human_events(store: EventStore, sid: str, workspace: Path, op: str, path: str) -> None:
    assert store.append(
        sid,
        EVENT_HUMAN_FILE_EDIT_PREPARED,
        {
            "operation_id": op,
            "request_id": f"req-{op}",
            "request_sha256": "1" * 64,
            "origin": "authenticated_user",
            "workspace_root": str(workspace.resolve()),
            "relative_path": path,
            "before_sha256": "a" * 64,
            "before_size": 3,
            "expected_after_sha256": "b" * 64,
            "expected_after_size": 4,
            "expected_snapshot_ref": "artifact://v1/" + "c" * 32,
            "precondition_checked": True,
            "file_contract_version": 1,
        },
    )
    assert store.append(
        sid,
        EVENT_HUMAN_FILE_EDIT_OBSERVED,
        {
            "operation_id": op,
            "request_id": f"req-{op}",
            "origin": "authenticated_user",
            "workspace_root": str(workspace.resolve()),
            "relative_path": path,
            "actual_after_sha256": "b" * 64,
            "actual_size": 4,
            "matches_expected": True,
            "artifact_ref": "artifact://v1/" + "d" * 32,
            "receipt_state": "recorded",
        },
    )


def test_human_file_event_types_are_registered() -> None:
    assert REGISTRY.spec(EVENT_HUMAN_FILE_EDIT_PREPARED) is not None
    assert REGISTRY.spec(EVENT_HUMAN_FILE_EDIT_OBSERVED) is not None


def test_file_effect_query_projects_human_and_model_without_host_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "a.txt"
    target.write_text("x", encoding="utf-8")
    events = EventStore(tmp_path / "events", enabled=True)
    sid = "s1"
    _human_events(events, sid, workspace, "hop", "a.txt")
    assert events.append(
        sid,
        EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
        {
            "execution_id": "mop",
            "round": 1,
            "tool_call_id": "call-1",
            "tool_name": "edit_file",
            "effect_kind": "file_replace",
            "workspace_root": str(workspace.resolve()),
            "canonical_path": str(target.resolve()),
            "before_sha256": "e" * 64,
            "before_size": 1,
            "expected_after_sha256": "f" * 64,
            "expected_after_size": 2,
        },
    )
    assert events.append(
        sid,
        EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
        {
            "execution_id": "mop",
            "round": 1,
            "tool_call_id": "call-1",
            "tool_name": "edit_file",
            "effect_kind": "file_replace",
            "workspace_root": str(workspace.resolve()),
            "canonical_path": str(target.resolve()),
            "actual_after_sha256": "f" * 64,
            "actual_size": 2,
            "actual_mtime_ns": 1,
            "matches_expected": True,
            "artifact_ref": "artifact://v1/" + "9" * 32,
        },
    )

    service = FileEffectQueryService(events)
    page = service.query(session_id=sid, workspace_scope=str(workspace), limit=10)
    assert [r.operation_id for r in page.receipts] == ["mop", "hop"]
    assert page.receipts[0].origin == "model_tool"
    assert page.receipts[0].path == "a.txt"
    assert page.receipts[0].precondition_checked is None
    assert page.receipts[0].task_applicability == "not_evaluated"
    assert page.receipts[1].origin == "authenticated_user"
    assert page.receipts[1].precondition_checked is True
    assert all(str(workspace.resolve()) not in str(r.public_facts()) for r in page.receipts)


def test_file_effect_query_strict_exact_and_exhaustive_pagination(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    events = EventStore(tmp_path / "events", enabled=True)
    sid = "s2"
    for i in range(4):
        _human_events(events, sid, workspace, f"op{i}", f"{i}.txt")

    service = FileEffectQueryService(events)
    first = service.query(session_id=sid, workspace_scope=str(workspace), limit=2)
    assert [r.operation_id for r in first.receipts] == ["op3", "op2"]
    assert first.has_more is True
    assert first.next_query.startswith("before_seq:")
    second = service.query(
        session_id=sid, workspace_scope=str(workspace), query=first.next_query, limit=2
    )
    assert [r.operation_id for r in second.receipts] == ["op1", "op0"]
    assert second.has_more is False

    exact = service.query(
        session_id=sid, workspace_scope=str(workspace), query="operation:op1", limit=10
    )
    assert [r.operation_id for r in exact.receipts] == ["op1"]
    with pytest.raises(FileEffectQueryError):
        service.query(session_id=sid, workspace_scope=str(workspace), query="op1", limit=10)


def test_search_records_file_effect_uses_current_session_and_strict_query(tmp_path: Path) -> None:
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.introspection.tools_status import run_search_records

    workspace = tmp_path / "ws"
    workspace.mkdir()
    events = EventStore(tmp_path / "events", enabled=True)
    _human_events(events, "current", workspace, "owned-op", "a.txt")
    _human_events(events, "other", workspace, "other-op", "b.txt")
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        file_effect_query=FileEffectQueryService(events),
        workspace_scope_resolver=lambda: str(workspace),
    )

    result = run_search_records(
        None,
        searcher.search,
        {"kind": "file_effect", "query": "", "limit": 10},
        lambda: "current",
    )
    assert result.status.value == "success"
    assert "owned-op" in result.content
    assert "other-op" not in result.content
    assert "task_applicability=not_evaluated" in result.content

    invalid = run_search_records(
        None,
        searcher.search,
        {"kind": "file_effect", "query": "owned-op", "limit": 10},
        lambda: "current",
    )
    assert invalid.status.value == "failure"
    assert "[参数错误]" in invalid.content


def test_prepared_only_crash_recovery_reports_current_bytes_without_reexecution(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    source_root = str(Path(__file__).resolve().parents[2] / "src")
    child = r'''
import hashlib, os, sys
from pathlib import Path
from llm_loop.event_log.model import EVENT_HUMAN_FILE_EDIT_PREPARED
from llm_loop.event_log.store import EventStore
root = Path(sys.argv[1]); mode = sys.argv[2]
workspace = root / "ws"; workspace.mkdir(parents=True, exist_ok=True)
target = workspace / "a.txt"
before = b"before\n"; expected = b"after\n"
target.write_bytes(before)
store = EventStore(root / "events", enabled=True)
assert store.append("crash-session", EVENT_HUMAN_FILE_EDIT_PREPARED, {
    "operation_id": "crash-op", "request_id": "crash-request", "request_sha256": "1" * 64,
    "origin": "authenticated_user", "workspace_root": str(workspace.resolve()), "relative_path": "a.txt",
    "before_sha256": hashlib.sha256(before).hexdigest(), "before_size": len(before),
    "expected_after_sha256": hashlib.sha256(expected).hexdigest(), "expected_after_size": len(expected),
    "expected_snapshot_ref": "artifact://v1/" + "c" * 32,
    "precondition_checked": True, "file_contract_version": 1,
})
if mode == "expected": target.write_bytes(expected)
elif mode == "other": target.write_bytes(b"other\n")
os._exit(17)
'''
    expected_states = {
        "before": "current_matches_before",
        "expected": "current_matches_expected",
        "other": "current_diverged",
    }
    for mode, expected_state in expected_states.items():
        root = tmp_path / mode
        env = os.environ.copy()
        env["PYTHONPATH"] = source_root
        proc = subprocess.run(
            [sys.executable, "-c", child, str(root), mode],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 17
        fresh_store = EventStore(root / "events", enabled=True)
        fresh_query = FileEffectQueryService(fresh_store)
        page = fresh_query.query(
            session_id="crash-session",
            workspace_scope=str(root / "ws"),
            query="operation:crash-op",
            limit=1,
        )
        assert len(page.receipts) == 1
        receipt = page.receipts[0]
        assert receipt.effect_state == "outcome_unknown"
        assert receipt.current_state == expected_state
        assert receipt.causation_proven is False
        assert receipt.auto_reexecuted is False
        assert receipt.observed_after_sha256 is None


def test_p3_file_contract_is_reachable_in_lazy_provider_schema(fake_settings) -> None:
    from llm_loop.factory import build_engine

    engine = build_engine(fake_settings)
    lazy = {entry["name"]: entry for entry in engine.registry.schemas(lazy=True)}
    for name in ("read_file", "edit_file", "search_records"):
        assert name in lazy
        assert engine.registry.get(name) is not None

    read_props = lazy["read_file"]["parameters"]["properties"]
    edit_props = lazy["edit_file"]["parameters"]["properties"]
    search_props = lazy["search_records"]["parameters"]["properties"]
    assert "snapshot" in read_props
    assert "expected_snapshot_ref" in edit_props
    assert "file_effect" in search_props["kind"]["enum"]
