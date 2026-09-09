"""search_archive(with_summary) legacy compatibility without false full-source claims."""

from __future__ import annotations

from dataclasses import dataclass

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.tools_status import run_search_archive


@dataclass
class _SummaryResult:
    summary: str
    source: str
    note: str = ""


class _MockArchive:
    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits

    def search(self, session_id: str, query: str, limit: int = 10, role=None, tool_name=None):
        return self._hits


class _MockSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, text: str) -> _SummaryResult:
        self.calls += 1
        return _SummaryResult(summary="MUST-NOT-BE-CALLED", source="llm")


def _hits() -> list[dict]:
    return [
        {
            "ts": "2026-08-12T00:00:00",
            "role": "tool",
            "tool_name": "read_file",
            "source": "tool",
            "summary": "文件内容索引摘要",
            "summary_source": "deterministic",
            "content_preview": "这是被压缩的原文预览，只是完整 source 的一小部分。",
        }
    ]


def _sid_fn():
    return "test-session"


def _ctx():
    class _Ctx:
        session_id = "test-session"

    return _Ctx()


def test_with_summary_is_preview_only_and_never_calls_hidden_llm():
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer()
    result = run_search_archive(
        _ctx(), archive, {"query": "关键词", "with_summary": True}, _sid_fn, summarizer
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert summarizer.calls == 0
    assert "archive_index_summary" in result.content
    assert "projection_complete=false" in result.content
    assert "full_source_semantic_summary_generated=false" in result.content
    assert "preview_only=true" in result.content
    assert "文件内容索引摘要" in result.content
    assert "MUST-NOT-BE-CALLED" not in result.content


def test_with_summary_without_summarizer_has_same_truthful_preview_contract():
    archive = _MockArchive(_hits())
    result = run_search_archive(
        _ctx(), archive, {"query": "关键词", "with_summary": True}, _sid_fn, summarizer=None
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert "projection_complete=false" in result.content
    assert "preview_only=true" in result.content


def test_without_summary_zero_regression():
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer()
    result = run_search_archive(_ctx(), archive, {"query": "关键词"}, _sid_fn, summarizer)
    assert result.status == ToolResultStatus.SUCCESS
    assert summarizer.calls == 0
    assert "文件内容索引摘要" in result.content
    assert "原文片段" in result.content


def test_without_summary_false_zero_regression():
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer()
    result = run_search_archive(
        _ctx(), archive, {"query": "关键词", "with_summary": False}, _sid_fn, summarizer
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert summarizer.calls == 0
    assert "archive_index_summary" not in result.content
