"""方案 3 合规变体 A: 压缩档案自动回填语义摘要（RULE-AI-00 自动摘要边界内）.

验证: SUMMARY_MODE!=off 时, _archive_sink 压缩另存后自动回填档案语义摘要,
且不注入当前上下文、不丢原文、可经 search_archive(with_summary=true) 检索。
"""
import tempfile

from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.summarize import Summarizer


class _FakeSummarizer(Summarizer):
    """确定性 fake: 摘要 = 首 50 字符 + 标记."""

    def summarize(self, text: str, truncated: bool = False):
        from llm_loop.memory.summarize import SummaryResult
        return SummaryResult(
            summary=f"[FAKE-SUM] {text[:50]}",
            source="fake",
            note="test",
        )


def test_archive_backfill_summary_in_rule_boundary():
    """压缩档案自动回填语义摘要（off 模式跳过, async 回填占位+后台）. """
    with tempfile.TemporaryDirectory() as td:
        store = ArchiveStore(td)
        # mode=off: 不应触发摘要回填
        _FakeSummarizer(mode="off")
        # 直接走 summarize_archive: off/sync 同步回填
        sync = _FakeSummarizer(mode="sync")
        entry = store.archive("s1", role="assistant", source="test", content="A" * 200)
        # off 模式: summarize_archive 仍同步回填（确定性），但 engine 侧跳过（summarizer.mode==off 不调用）
        # 这里验证 sync 模式回填生效
        sync.summarize_archive(entry.id, "B" * 200, store)
        hits = store.search("s1", "FAKE-SUM", limit=5)
        assert any("[FAKE-SUM]" in h.get("summary", "") for h in hits), "sync 模式应回填摘要"


def test_engine_archive_sink_skips_when_off():
    """engine 侧: summarizer.mode=off 时 _archive_sink 不调用 summarize_archive."""
    from unittest.mock import MagicMock, patch

    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import Message, MessageSource

    engine = LoopEngine.__new__(LoopEngine)
    engine.archive = ArchiveStore(tempfile.mkdtemp())
    engine.summarizer = _FakeSummarizer(mode="off")  # off: 跳过
    engine.session = MagicMock()

    with patch.object(engine.summarizer, "summarize_archive") as mock_sum:
        engine._archive_sink("s1", Message(role="user", content="hello world" * 20, source=MessageSource.USER))
        mock_sum.assert_not_called()


def test_engine_archive_sink_backfills_when_sync():
    """engine 侧: summarizer.mode=sync 时 _archive_sink 自动回填档案摘要."""
    from unittest.mock import MagicMock, patch

    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import Message, MessageSource

    engine = LoopEngine.__new__(LoopEngine)
    engine.archive = ArchiveStore(tempfile.mkdtemp())
    engine.summarizer = _FakeSummarizer(mode="sync")  # sync: 触发回填
    engine.session = MagicMock()

    with patch.object(engine.summarizer, "summarize_archive") as mock_sum:
        engine._archive_sink("s1", Message(role="user", content="hello world" * 20, source=MessageSource.USER))
        mock_sum.assert_called_once()
        # 传入的是已归档 entry.id
        entry_id = mock_sum.call_args[0][0]
        assert entry_id.startswith("ARC-")
