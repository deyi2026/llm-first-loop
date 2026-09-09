"""同 session whole-run 跨进程 lease：防 Web/飞书长 run last-writer-wins."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from llm_loop.core.loop.runner import SessionBusyError
from llm_loop.core.session import SessionStore


def test_run_lease_cross_process_is_nonblocking_and_reacquirable(tmp_path: Path):
    """进程 A 持 lease 时 B 立即失败；A 释放后 B 可重新取得。"""
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    sid = "shared-session"
    worker = r"""
import sys, time
from pathlib import Path
from llm_loop.core.session import SessionStore
root, sid, ready, release = sys.argv[1:]
store = SessionStore(root)
with store.run_lease(sid) as acquired:
    if not acquired:
        raise SystemExit(2)
    Path(ready).write_text("ready")
    while not Path(release).exists():
        time.sleep(0.01)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    proc = subprocess.Popen(
        [sys.executable, "-c", worker, str(tmp_path), sid, str(ready), str(release)],
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "子进程未取得 run lease"

        store = SessionStore(tmp_path)
        started = time.monotonic()
        with store.run_lease(sid) as acquired:
            assert acquired is False
        assert time.monotonic() - started < 0.5, "冲突 lease 必须非阻塞快速返回"

        release.write_text("go")
        assert proc.wait(timeout=5) == 0
        with store.run_lease(sid) as acquired:
            assert acquired is True
    finally:
        if proc.poll() is None:
            proc.kill()


def test_engine_maps_cross_process_lease_conflict_to_session_busy(build_test_engine):
    engine, _ = build_test_engine([{"content": "should-not-run"}])
    sid = engine.session.create()
    other = SessionStore(engine.session._dir)  # noqa: SLF001 — 模拟另一个进程同目录

    with other.run_lease(sid) as acquired:
        assert acquired is True
        with pytest.raises(SessionBusyError, match="另一进程"):
            engine.run(sid, "hello")

    # busy 失败必须清理进程内 _sync_active；释放外部 lease 后同 engine 可再次执行。
    result = engine.run(sid, "hello again")
    assert result.final_answer == "should-not-run"
    assert sid not in engine._run_sessions, "正常run结束后不得永久保留完整Session对象"  # noqa: SLF001


def test_generator_close_releases_run_lease(build_test_engine):
    from llm_loop.llm.client import LLMResponse, StreamDelta

    engine, fake = build_test_engine([])
    sid = engine.session.create()
    other = SessionStore(engine.session._dir)  # noqa: SLF001

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = slow_stream
    stream = engine.run_stream(sid, "hello")
    try:
        first = next(stream)
        assert first.text == "A"
        with other.run_lease(sid) as acquired:
            assert acquired is False, "生成器存续期应持有整轮 lease"
    finally:
        stream.close()

    with other.run_lease(sid) as acquired:
        assert acquired is True, "GeneratorExit/finally 必须释放整轮 lease"
    assert sid not in engine._run_sessions, "GeneratorExit后也必须释放in-memory Session绑定"  # noqa: SLF001


def test_management_mutations_reject_active_run(tmp_path):
    """长 run 持 lease 时，所有 run 外写必须快速失败，不能制造最终 save 覆盖。"""
    import time

    import pytest

    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionMutationBusyError, SessionStore

    owner = SessionStore(tmp_path)
    other = SessionStore(tmp_path)
    sid = owner.create()
    snapshot = other.load(sid)
    snapshot.title = "external-save"

    with owner.run_lease(sid) as acquired:
        assert acquired is True
        started = time.monotonic()
        operations = [
            lambda: other.save(snapshot),
            lambda: other.rename(sid, "renamed"),
            lambda: other.set_pinned(sid, True),
            lambda: other.set_channel(sid, "feishu:group:test"),
            lambda: other.archive(sid),
            lambda: other.append(
                sid, Message(role="user", content="late", source=MessageSource.USER)
            ),
            lambda: other.trim_session(sid, keep_recent=1),
            lambda: other.fork(sid),
            lambda: other.delete(sid),
        ]
        for operation in operations:
            with pytest.raises(SessionMutationBusyError):
                operation()
        assert time.monotonic() - started < 1.0
        assert owner.exists(sid) is True
        current = owner.load(sid)
        assert current.title != "renamed"
        assert current.pinned is False
        assert current.status == "active"
        assert current.channel == "web"
        assert all(m.content != "late" for m in current.messages)

    assert other.rename(sid, "after-run") is True
    assert other.load(sid).title == "after-run"
    assert other.delete(sid) is True
    assert other.exists(sid) is False


def test_active_engine_stream_blocks_delete_until_close(build_test_engine):
    """真实 run 生命周期中 delete 被拒；stream 关闭释放 lease 后删除成功且不会复活。"""
    import pytest

    from llm_loop.core.session import SessionMutationBusyError, SessionStore
    from llm_loop.llm.client import LLMResponse, StreamDelta

    engine, fake = build_test_engine([])

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = slow_stream
    sid = engine.session.create()
    stream = engine.run_stream(sid, "hello")
    assert next(stream).text == "A"

    other = SessionStore(engine.session._dir)  # noqa: SLF001 — 独立 store 模拟另一进程
    with pytest.raises(SessionMutationBusyError):
        other.delete(sid)
    assert other.exists(sid) is True

    stream.close()
    assert other.delete(sid) is True
    assert other.exists(sid) is False


def test_workspace_switch_rejected_while_sync_stream_is_active(build_test_engine, tmp_path):
    """活跃run期间不得切SessionStore workspace根，否则旧run最终save会写入新分区。"""
    from llm_loop.llm.client import LLMResponse, StreamDelta

    engine, fake = build_test_engine([])
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    engine.set_workspace(str(workspace_a), "ws-a")
    sid = engine.session.create()
    root_a = engine.session.root

    def slow_stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = slow_stream
    stream = engine.run_stream(sid, "hello")
    try:
        assert next(stream).text == "A"
        with pytest.raises(RuntimeError, match="运行|workspace|工作区"):
            engine.set_workspace(str(workspace_b), "ws-b")
        assert engine.session.root == root_a
        list(stream)
    finally:
        stream.close()

    stored = engine.session.load(sid)
    assert any(m.role == "assistant" and "AB" in m.content for m in stored.messages)
    assert not (engine.settings.sessions_dir / "ws-b" / f"{sid}.json").exists()


def test_run_owned_session_binds_save_authority_without_serializing_token(tmp_path: Path):
    """Public run-owned facade owns save rights only for the context lifetime."""
    from llm_loop.core.message import Message, MessageSource

    owner = SessionStore(tmp_path)
    other = SessionStore(tmp_path)
    sid = owner.create()

    with owner.run_owned_session(sid) as active:
        assert active is not None
        active.messages.append(Message(role="user", content="durable", source=MessageSource.USER))
        owner.save(active)

        with other.run_lease(sid) as acquired:
            assert acquired is False

        snapshot = active.to_dict()
        serialized = repr(snapshot)
        assert "run_save_token" not in serialized
        assert "opaque" not in serialized.lower()

    assert owner.load(sid).messages[-1].content == "durable"
    with other.run_lease(sid) as acquired:
        assert acquired is True
