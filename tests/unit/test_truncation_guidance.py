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


# ── EVO-20260822-b3e7105e: 本地模型预算联动收紧摘要（阈值/窗口随模型标签）──

def _set_model_label(label: str) -> None:
    """设置 current_model_label contextvar（测试用；token 由调用方保存恢复）."""
    from llm_loop.core.run_context import current_model_label

    _tok = current_model_label.set(label)
    return _tok


def test_local_model_tightens_summary_threshold():
    """local 模型标签下收紧阈值：6K 输出在 4000 阈值触发摘要（全局 15000 下不触发）."""
    from llm_loop.core.run_context import current_model_label

    reg = ToolRegistry(
        summary_threshold=15000,
        summary_local_threshold=4000,
        summary_local_head_chars=800,
        summary_local_tail_chars=800,
    )
    reg.register(_BigTool("x" * 6000))
    tok = current_model_label.set("local/qwen/qwen3.8-27b")
    try:
        r = reg.execute(_call())
    finally:
        current_model_label.reset(tok)
    assert "输出摘要" in r.content, "local 模型 6K 输出在 4000 阈值下应触发摘要分层"
    assert "search_archive" in r.content  # 信息零丢失指引保留


def test_local_model_tightens_summary_window():
    """local 模型标签下收紧首尾窗口：800 窗口内偏移 1000 的标记不可见（全局 2500 可见）."""
    from llm_loop.core.run_context import current_model_label

    reg = ToolRegistry(
        summary_threshold=15000,
        summary_local_threshold=4000,
        summary_local_head_chars=800,
        summary_local_tail_chars=800,
    )
    # 总长 ~8000，超 local 4000 阈值；MID 位于距头 1000 处——800 首窗口覆盖不到
    content = "HEAD" + "h" * 996 + "MID1000" + "m" * 6900 + "TAIL"
    reg.register(_BigTool(content))
    tok = current_model_label.set("local/qwen/qwen3.8-27b")
    try:
        r = reg.execute(_call())
    finally:
        current_model_label.reset(tok)
    assert "输出摘要" in r.content
    assert "HEAD" in r.content, "800 首窗口应覆盖距头 4 字符的 HEAD"
    assert "TAIL" in r.content
    assert "MID1000" not in r.content, "local 800 首窗口不应覆盖距头 1000 处（全局 2500 才可见）"


def test_evidence_tool_exempt_from_local_tightening():
    """证据型工具豁免本地收紧（漂移修复 2026-08-29 会话 68fed5f5 实证）.

    web_fetch 6K 输出走全局 15000 阈值全量注入——此前被本地 4000 阈值压成首尾
    1600c 摘要，DFlash 文档证据不完整导致弱模型生成漂移（答非所问输出能力清单）。
    """

    from llm_loop.core.run_context import current_model_label

    class _WebFetchTool(_BigTool):
        def __init__(self, content: str):
            super().__init__(content)
            self.name = "web_fetch"

        def execute(self, **kwargs):
            r = super().execute(**kwargs)
            r.tool_name = "web_fetch"
            return r

    reg = ToolRegistry(
        summary_threshold=15000,
        summary_local_threshold=4000,
        summary_local_head_chars=800,
        summary_local_tail_chars=800,
    )
    reg.register(_WebFetchTool("x" * 6000))
    tok = current_model_label.set("local/qwen/qwen3.8-27b")
    try:
        r = reg.execute(ToolCall(id="c1", name="web_fetch", arguments={}))
    finally:
        current_model_label.reset(tok)
    assert "输出摘要" not in r.content, "证据工具 6K < 全局 15000 阈值应全量注入（豁免本地 4000 收紧）"
    assert len(r.content) >= 6000, "6K 证据内容应完整到达（不被摘要化）"


def test_cloud_model_keeps_global_threshold():
    """云端/无标签模型维持全局配置零回归：6K 输出在 15000 阈值下不触发摘要."""
    from llm_loop.core.run_context import current_model_label

    reg = ToolRegistry(
        summary_threshold=15000,
        summary_local_threshold=4000,
    )
    reg.register(_BigTool("x" * 6000))
    tok = current_model_label.set("deepseek/deepseek-v4-flash")
    try:
        r = reg.execute(_call())
    finally:
        current_model_label.reset(tok)
    assert "输出摘要" not in r.content, "云端模型 6K 输出在全局 15000 阈值下不应被分层"
