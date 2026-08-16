"""PollingSynchronizer 单元测试（design.md §2.2.2.5）.

使用 mock client 测试状态映射/终态回调/状态未知标注/轮询间隔下限行为。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from llm_loop.codearts.client import ClientError, RetryableError
from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.credential import EnvCredentialProvider
from llm_loop.codearts.handle import HandleRegistry
from llm_loop.codearts.models import (
    ExecutionHandle,
    HandleStatus,
    RemoteStatus,
)
from llm_loop.codearts.sync import PollingSynchronizer
from llm_loop.event_log.store import EventStore


def _make_config(**overrides) -> CodeArtsSettings:
    defaults = dict(
        enabled=True,
        endpoint="https://codearts.example.com",
        region="cn-north-4",
        ak="AK123",
        sk="SK456",
        poll_interval_s=5,
        max_retries=1,
    )
    defaults.update(overrides)
    return CodeArtsSettings(**defaults)


def _make_handle() -> ExecutionHandle:
    return ExecutionHandle(
        handle_id="h1",
        session_id="s1",
        trace_id="t1",
        created_at="2026-01-01T00:00:00Z",
        status=HandleStatus.RUNNING,
    )


def _make_sync(tmp_path: Path, config=None, client=None) -> PollingSynchronizer:
    config = config or _make_config()
    event_store = EventStore(tmp_path / "events", enabled=False)
    handle_registry = HandleRegistry(event_store, max_concurrent=config.max_concurrent)
    cred_provider = EnvCredentialProvider(config)
    mock_client = client or MagicMock()
    return PollingSynchronizer(
        client=mock_client,
        credential_provider=cred_provider,
        handle_registry=handle_registry,
        event_store=event_store,
        config=config,
    )


def test_start_terminal_succeeded_calls_callback(tmp_path: Path):
    sync = _make_sync(tmp_path)
    sync._client.query_status.return_value = RemoteStatus.SUCCEEDED
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()
    result_status: list[HandleStatus] = []

    def on_terminal(status: HandleStatus) -> None:
        result_status.append(status)
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    assert callback_called.wait(timeout=10)
    assert result_status[0] == HandleStatus.SUCCEEDED
    sync.stop(handle.handle_id)


def test_start_terminal_failed_calls_callback(tmp_path: Path):
    sync = _make_sync(tmp_path)
    sync._client.query_status.return_value = RemoteStatus.FAILED
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()
    result_status: list[HandleStatus] = []

    def on_terminal(status: HandleStatus) -> None:
        result_status.append(status)
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    assert callback_called.wait(timeout=10)
    assert result_status[0] == HandleStatus.FAILED
    sync.stop(handle.handle_id)


def test_start_terminal_cancelled(tmp_path: Path):
    sync = _make_sync(tmp_path)
    sync._client.query_status.return_value = RemoteStatus.CANCELLED
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()
    result_status: list[HandleStatus] = []

    def on_terminal(status: HandleStatus) -> None:
        result_status.append(status)
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    assert callback_called.wait(timeout=10)
    assert result_status[0] == HandleStatus.CANCELLED


def test_start_persistent_error_marks_unknown(tmp_path: Path):
    config = _make_config(max_retries=0, poll_interval_s=0)
    sync = _make_sync(tmp_path, config=config)
    sync._client.query_status.side_effect = ClientError("permanent failure")
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()
    result_status: list[HandleStatus] = []

    def on_terminal(status: HandleStatus) -> None:
        result_status.append(status)
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    assert callback_called.wait(timeout=10)
    assert result_status[0] == HandleStatus.UNKNOWN
    updated = sync._handle_registry.get("h1")
    assert updated is not None
    assert updated.status == HandleStatus.UNKNOWN


def test_start_retryable_error_then_unknown(tmp_path: Path):
    config = _make_config(max_retries=0, poll_interval_s=0)
    sync = _make_sync(tmp_path, config=config)
    sync._client.query_status.side_effect = RetryableError("transient")
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()

    def on_terminal(status: HandleStatus) -> None:
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    assert callback_called.wait(timeout=10)
    assert sync._handle_registry.get("h1").status == HandleStatus.UNKNOWN


def test_stop_terminates_polling(tmp_path: Path):
    sync = _make_sync(tmp_path)
    sync._client.query_status.return_value = RemoteStatus.RUNNING
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    sync.start(handle, on_terminal=lambda s: None)
    time.sleep(0.1)
    sync.stop(handle.handle_id)
    with sync._lock:
        assert handle.handle_id not in sync._stop_flags


def test_status_mapping_running(tmp_path: Path):
    sync = _make_sync(tmp_path)
    sync._client.query_status.return_value = RemoteStatus.RUNNING
    handle = _make_handle()
    sync._handle_registry.register(handle, session_id="s1", trace_id="t1")

    callback_called = threading.Event()

    def on_terminal(status: HandleStatus) -> None:
        callback_called.set()

    sync.start(handle, on_terminal=on_terminal)
    time.sleep(0.2)
    sync.stop(handle.handle_id)
    updated = sync._handle_registry.get("h1")
    assert updated is not None
    assert updated.status == HandleStatus.RUNNING
    assert not callback_called.is_set()


def test_poll_interval_enforced_minimum_5s(tmp_path: Path):
    config = _make_config(poll_interval_s=1)
    _make_sync(tmp_path, config=config)
    assert max(5, config.poll_interval_s) == 5
