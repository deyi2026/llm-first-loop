"""EVO-20260813-4b49a822: handoff_now 生成的交接文档自动归档到当前会话 ArchiveStore.

验证: run_handoff_now 生成 handoff.md 后, 当前会话档案可经 search_archive 检索到交接内容
（修复前 handoff.md 只写普通文件, search_archive 检索不到, 新会话恢复路径断裂）。
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.tools_handoff import _archive_handoff, run_handoff_now
from llm_loop.memory.archive import ArchiveStore


def _make_ctx(session_id: str, archive: ArchiveStore) -> MagicMock:
    ctx = MagicMock()
    ctx.session_id = session_id
    ctx.archive = archive
    return ctx


def test_handoff_now_archives_to_current_session():
    """handoff_now 后, 当前会话档案可检索到交接内容. """
    from llm_loop.core.run_context import current_session_id

    with tempfile.TemporaryDirectory() as td:
        store = ArchiveStore(Path(td) / "archives")
        ctx = _make_ctx("sess-test-001", store)
        audit = MagicMock()
        token = current_session_id.set("sess-test-001")
        try:
            result = run_handoff_now(ctx, audit, {"urgency": "high"})
        finally:
            current_session_id.reset(token)

        assert result.status == ToolResultStatus.SUCCESS
        # 档案里应有 handoff 条目
        hits = store.search("sess-test-001", "Handoff", limit=5)
        assert len(hits) >= 1, "handoff 应归档到当前会话档案"
        hit = hits[0]
        assert hit.get("source") == "handoff"
        assert hit.get("tool_name") == "handoff_now"
        assert "Handoff" in hit.get("content_preview", "")


def test_handoff_missing_context_does_not_archive_to_shared_ctx_session():
    """P2: stale ctx.session_id must never authorize an archive mutation."""
    with tempfile.TemporaryDirectory() as td:
        store = ArchiveStore(Path(td) / "archives")
        ctx = _make_ctx("stale-session-B", store)

        _archive_handoff(ctx, "P2 missing-context handoff")

        assert store.search("stale-session-B", "P2 missing-context", limit=5) == []


def test_handoff_archive_fail_open():
    """归档失败 fail-open: 不影响 handoff 主流程（仍返回 SUCCESS）. """
    with tempfile.TemporaryDirectory():
        # ctx.archive 用 MagicMock, 其 archive() 抛异常
        ctx = MagicMock()
        ctx.session_id = "sess-test-002"
        ctx.archive = MagicMock()
        ctx.archive.archive.side_effect = RuntimeError("boom")
        audit = MagicMock()

        result = run_handoff_now(ctx, audit, {"urgency": "low"})
        assert result.status == ToolResultStatus.SUCCESS, "归档失败不应影响 handoff"


def test_archive_handoff_no_archive_attr():
    """ctx 无 archive 属性: 静默跳过（fail-open）. """
    ctx = MagicMock()
    del ctx.archive  # 无 archive 属性
    _archive_handoff(ctx, "doc")  # 不应抛异常


def test_explicit_handoff_creates_empty_child_and_real_task_snapshot(tmp_path, monkeypatch):
    """A model tool can actually create a fresh session when the user requests it."""
    import re

    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.run_context import current_session_id
    from llm_loop.core.session import SessionStore
    from llm_loop.introspection.goal import GoalStore
    from llm_loop.introspection.task_store import TaskStore

    monkeypatch.chdir(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    source = store.load(sid)
    source.messages.append(Message(role="user", source=MessageSource.USER, content="继续独立评测"))
    store.save(source)
    audit = tmp_path / "audit"
    goal = GoalStore(audit).create("完成完整评测", session_id=sid)
    TaskStore(audit).create(goal.id, "等待盲审结果", acceptance=["真实回执"])
    token = current_session_id.set(sid)
    try:
        result = run_handoff_now(
            MagicMock(archive=None), MagicMock(),
            {"urgency": "high", "create_new_session": True},
            session_store=store, audit_dir=audit,
        )
    finally:
        current_session_id.reset(token)

    assert result.status == ToolResultStatus.SUCCESS
    match = re.search(r"new_session_id: ([0-9a-f-]{36})", result.content)
    assert match is not None, result.content
    child = store.load(match.group(1))
    assert child.parent_id == sid
    assert child.messages == []
    assert "等待盲审结果" in child.branch_summary
    assert "上下文压力: 0%" not in result.content
    doc = next((tmp_path / "compressed_archive").glob("handoff_*/handoff.md"))
    assert "等待盲审结果" in doc.read_text(encoding="utf-8")


def test_handoff_tool_rejects_unbound_context_even_when_ctx_claims_session(tmp_path):
    """A stale shared ctx.session_id is never authorization to create a new chat."""
    from llm_loop.core.session import SessionStore

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    ctx = MagicMock()
    ctx.session_id = sid
    result = run_handoff_now(
        ctx, MagicMock(), {"create_new_session": True},
        session_store=store, audit_dir=tmp_path / "audit",
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "未创建新会话" in result.content


def test_handoff_doc_failure_does_not_hide_created_child(tmp_path, monkeypatch):
    """A backup handoff.md I/O failure must not cause duplicate-session retries."""
    import re

    from llm_loop.core.run_context import current_session_id
    from llm_loop.core.session import SessionStore

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    original_write = Path.write_text

    def deny_backup(self, *args, **kwargs):
        if self.name == "handoff.md":
            raise PermissionError("simulated archive permission error")
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", deny_backup)
    token = current_session_id.set(sid)
    try:
        report = run_handoff_now(
            MagicMock(archive=None), MagicMock(),
            {"urgency": "high", "create_new_session": True},
            session_store=store, audit_dir=tmp_path / "audit",
        )
    finally:
        current_session_id.reset(token)
    assert report.status == ToolResultStatus.SUCCESS
    assert "文档**: 写入失败" in report.content
    match = re.search(r"new_session_id: ([0-9a-f-]{36})", report.content)
    assert match is not None
    assert store.load(match.group(1)).parent_id == sid
