"""截断信号强化测试（2026-08-15 用户需求）.

- 放大字数：TOOL_SUMMARY_THRESHOLD 默认 5000 → 12000；首尾窗口 600/600 → 2500/2500。
- 截断/摘要信号带行动指引：AI 继续推理前先提炼可见要点与中部缺口（写入推理链或
  [[memory]] 记忆块），最终总结时纳入——程序只发信号，摘要由 AI 完成（RULE-AI-00）。
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.tools.registry import ToolRegistry, ToolResult, ToolResultStatus


class _BigTool:
    def __init__(self, content: str):
        self._content = content
        self.name = "big_tool"

    def execute(self, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=self._content,
            tool_call_id="c1",
            tool_name="big_tool",
        )


def _call() -> ToolCall:
    return ToolCall(id="c1", name="big_tool", arguments={})


def test_default_threshold_raised_12000():
    """默认分层阈值 12000（放大字数）：6K 输出不再分层，原样注入."""
    reg = ToolRegistry()
    assert reg.summary_threshold == 12000
    reg.register(_BigTool("x" * 6000))
    r = reg.execute(_call())
    assert "输出摘要" not in r.content, "6K 输出在 12000 默认阈值下不应被分层"


def test_summary_window_widened_2500():
    """首尾窗口 2500/2500：距头 2000 的标记仍可见（旧 600 窗口会丢）."""
    content = "HEAD" + "h" * 1996 + "MID2000" + "m" * 15000 + "TAIL"
    reg = ToolRegistry(summary_threshold=5000)
    reg.register(_BigTool(content))
    r = reg.execute(_call())
    assert "输出摘要" in r.content
    assert "MID2000" in r.content, "2500 首窗口应覆盖 2000 偏移处内容"
    assert "TAIL" in r.content
    assert "m" * 4000 not in r.content  # 中部仍省略（如实标注非全文）


def test_summary_carries_distill_guidance():
    """摘要标注带行动指引：先提炼要点再继续 + 最终总结纳入."""
    reg = ToolRegistry(summary_threshold=100)
    reg.register(_BigTool("y" * 6000))  # 超首尾窗口（2500+2500）→ 真摘要分支
    r = reg.execute(_call())
    assert "提炼" in r.content, f"摘要缺提炼指引: {r.content[:200]}"
    assert "最终总结" in r.content or "最终回答" in r.content


def test_hard_truncation_carries_distill_guidance():
    """硬上限截断标注同样带行动指引（信息零丢失声明保留）."""
    reg = ToolRegistry(summary_threshold=10_000_000, max_output_chars=2000)
    reg.register(_BigTool("z" * 5000))
    r = reg.execute(_call())
    assert "已截断" in r.content
    assert "search_archive" in r.content  # 信息零丢失指引保留
    assert "提炼" in r.content
