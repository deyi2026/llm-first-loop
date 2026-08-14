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
    with tempfile.TemporaryDirectory() as td:
        store = ArchiveStore(Path(td) / "archives")
        ctx = _make_ctx("sess-test-001", store)
        audit = MagicMock()

        result = run_handoff_now(ctx, audit, {"urgency": "high"})

        assert result.status == ToolResultStatus.SUCCESS
        # 档案里应有 handoff 条目
        hits = store.search("sess-test-001", "Handoff", limit=5)
        assert len(hits) >= 1, "handoff 应归档到当前会话档案"
        hit = hits[0]
        assert hit.get("source") == "handoff"
        assert hit.get("tool_name") == "handoff_now"
        assert "Handoff" in hit.get("content_preview", "")


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
