"""执行句柄注册表单元测试（design.md §2.2.2.4）."""

from __future__ import annotations

from pathlib import Path

from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import ExecutionHandle, HandleStatus, RemoteStatus
from llm_loop.event_log.store import EventStore


def _make_handle(hid: str = "h1") -> ExecutionHandle:
    return ExecutionHandle(
        handle_id=hid,
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
        remote_status=RemoteStatus.RUNNING,
    )


def _make_store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events", enabled=True)


def test_register_and_get(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    h = _make_handle()
    reg.register(h, session_id="s1", trace_id="t1")
    assert reg.get("h1") is not None
    assert reg.get("h1").handle_id == "h1"


def test_is_full(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=2)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    reg.register(_make_handle("h2"), session_id="s1", trace_id="t2")
    assert reg.is_full() is True


def test_not_full(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    assert reg.is_full() is False


def test_list_in_flight(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    reg.register(_make_handle("h2"), session_id="s1", trace_id="t2")
    in_flight = reg.list_in_flight()
    assert len(in_flight) == 2


def test_update_status(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    reg.update_status("h1", HandleStatus.SUCCEEDED, RemoteStatus.SUCCEEDED)
    h = reg.get("h1")
    assert h.status == HandleStatus.SUCCEEDED


def test_release(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    reg.update_status("h1", HandleStatus.SUCCEEDED)
    reg.release("h1")
    assert len(reg.list_in_flight()) == 0


def test_get_nonexistent(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    assert reg.get("nonexistent") is None


def test_in_flight_count(tmp_path: Path):
    store = _make_store(tmp_path)
    reg = HandleRegistry(store, max_concurrent=10)
    reg.register(_make_handle("h1"), session_id="s1", trace_id="t1")
    reg.register(_make_handle("h2"), session_id="s1", trace_id="t2")
    assert reg.in_flight_count() == 2
