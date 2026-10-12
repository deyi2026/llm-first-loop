"""单元测试: Summarizer LLM 语义摘要（T27 / FR-P1-MEM 系列）."""

from __future__ import annotations

from llm_loop.llm.client import LLMResponse
from llm_loop.memory.summarize import Summarizer


class _FakeLLMSummary:
    """摘要用 FakeLLM: 返回固定摘要或抛异常."""

    def __init__(self, content: str = "LLM 语义摘要内容", error: Exception | None = None) -> None:
        self._content = content
        self._error = error

    def chat(self, messages, tools) -> LLMResponse:
        if self._error is not None:
            raise self._error
        return LLMResponse(content=self._content, tool_calls=[], provider="fake")


def test_off_mode_uses_deterministic():
    """off 模式 → 确定性摘要（source=deterministic，与 P0 行为一致）."""
    s = Summarizer(llm_client=None, mode="off")
    r = s.summarize("读取 /tmp/notes.txt 成功，包含关键数据")
    assert r.source == "deterministic"
    assert "notes.txt" in r.summary


def test_sync_mode_llm_success():
    """sync 模式 LLM 成功 → source=llm."""
    fake = _FakeLLMSummary(content="这是 LLM 生成的语义摘要")
    s = Summarizer(llm_client=fake, mode="sync")
    r = s.summarize("内容内容")
    assert r.source == "llm"
    assert r.summary == "这是 LLM 生成的语义摘要"


def test_sync_llm_error_fallback():
    """sync LLM 失败 → 确定性兜底 + note 标注（不伪造）."""
    from llm_loop.llm.errors import LLMTimeoutError

    fake = _FakeLLMSummary(error=LLMTimeoutError("超时"))
    s = Summarizer(llm_client=fake, mode="sync")
    r = s.summarize("读取 /tmp/x.txt 成功")
    assert r.source == "deterministic"
    assert "降级" in r.note


def test_sync_llm_empty_fallback():
    """sync LLM 返回空 → 确定性兜底 + note."""
    fake = _FakeLLMSummary(content="")
    s = Summarizer(llm_client=fake, mode="sync")
    r = s.summarize("读取 /tmp/y.txt")
    assert r.source == "deterministic"
    assert "空" in r.note


def test_input_budget_truncation():
    """输入超预算 → 截断 + note（不阻塞）."""
    fake = _FakeLLMSummary()
    s = Summarizer(llm_client=fake, mode="sync", max_input_chars=50)
    r = s.summarize("A" * 500)
    assert r.note and "截断" in r.note


def test_async_mode_immediate_return():
    """async 模式主线程立即返回确定性占位 + note（DFX-PERF-04 零阻塞）."""
    fake = _FakeLLMSummary()
    s = Summarizer(llm_client=fake, mode="async")
    r = s.summarize("内容")
    assert r.source == "deterministic"  # 立即返回占位
    assert "异步" in r.note


def test_async_queue_full_fallback():
    """async 队列满 → 当前条目转确定性 + note."""
    fake = _FakeLLMSummary()
    s = Summarizer(llm_client=fake, mode="async", max_async_queue=0)
    r = s.summarize("内容")
    assert r.source == "deterministic"
    assert "队列" in r.note


def test_no_fabrication_on_failure():
    """失败必带 note 且 source != llm（禁止虚构填充）."""
    from llm_loop.llm.errors import LLMNetworkError

    fake = _FakeLLMSummary(error=LLMNetworkError("网络断开"))
    s = Summarizer(llm_client=fake, mode="sync")
    r = s.summarize("内容")
    assert r.source != "llm"
    assert r.note  # 必带 note
