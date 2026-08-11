"""R2: search_archive(with_summary) AI 按需语义摘要测试.

验证:
- with_summary=true 时返回 LLM 摘要 + source
- 摘要失败时如实标注 [摘要失败] + 原文片段（不静默降级）
- summarizer 未装配时标注 [摘要不可用]
- with_summary 未传时行为不变（零回归）
"""
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
    """mock archive: search 返回固定 hits."""

    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits

    def search(self, session_id: str, query: str, limit: int = 10, role=None, tool_name=None):
        return self._hits


class _MockSummarizer:
    """mock summarizer: summarize 返回固定结果或抛异常."""

    def __init__(self, result: _SummaryResult | None = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    def summarize(self, text: str) -> _SummaryResult:
        if self._exc is not None:
            raise self._exc
        return self._result or _SummaryResult(summary="默认摘要", source="llm")


def _hits() -> list[dict]:
    return [
        {
            "ts": "2026-08-12T00:00:00",
            "role": "tool",
            "tool_name": "read_file",
            "source": "tool",
            "summary": "文件内容摘要",
            "content_preview": "这是被压缩的原文内容，包含关键信息。",
        }
    ]


def _sid_fn():
    return "test-session"


def _ctx():
    class _Ctx:
        session_id = "test-session"
    return _Ctx()


def test_with_summary_success():
    """with_summary=true 时返回 LLM 摘要 + source=llm."""
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer(_SummaryResult(summary="这是 LLM 生成的语义摘要", source="llm"))
    result = run_search_archive(_ctx(), archive, {"query": "关键词", "with_summary": True}, _sid_fn, summarizer)
    assert result.status == ToolResultStatus.SUCCESS
    assert "摘要(source=llm)" in result.content
    assert "这是 LLM 生成的语义摘要" in result.content
    assert "原文片段" in result.content


def test_with_summary_failure_honest():
    """摘要失败时如实标注 [摘要失败] + 原文片段（不静默降级）."""
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer(exc=RuntimeError("LLM 摘要服务不可用"))
    result = run_search_archive(_ctx(), archive, {"query": "关键词", "with_summary": True}, _sid_fn, summarizer)
    assert result.status == ToolResultStatus.SUCCESS
    assert "[摘要失败" in result.content
    assert "LLM 摘要服务不可用" in result.content
    assert "原文片段" in result.content  # 回退原文片段


def test_with_summary_no_summarizer_unavailable():
    """summarizer 未装配时标注 [摘要不可用] + 原文片段."""
    archive = _MockArchive(_hits())
    result = run_search_archive(_ctx(), archive, {"query": "关键词", "with_summary": True}, _sid_fn, summarizer=None)
    assert result.status == ToolResultStatus.SUCCESS
    assert "[摘要不可用]" in result.content
    assert "原文片段" in result.content


def test_without_summary_zero_regression():
    """with_summary 未传时行为与现状完全一致（零回归）."""
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer()
    result = run_search_archive(_ctx(), archive, {"query": "关键词"}, _sid_fn, summarizer)
    assert result.status == ToolResultStatus.SUCCESS
    assert "摘要(source" not in result.content  # 既有格式无摘要标注
    assert "文件内容摘要" in result.content  # 既有 summary 字段
    assert "原文片段" in result.content  # 既有原文片段


def test_without_summary_false_zero_regression():
    """with_summary=false 时行为与现状完全一致."""
    archive = _MockArchive(_hits())
    summarizer = _MockSummarizer()
    result = run_search_archive(_ctx(), archive, {"query": "关键词", "with_summary": False}, _sid_fn, summarizer)
    assert result.status == ToolResultStatus.SUCCESS
    assert "摘要(source" not in result.content
