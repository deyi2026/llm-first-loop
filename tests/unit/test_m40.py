"""M40 上下文管理优化测试（config 默认值断言 + 截断行为测试，零真实冒烟）.

用例：5 处预算放大默认值断言 + 3 处截断行为测试（大输入不丢关键信息）。
"""

from __future__ import annotations

from llm_loop.config import Settings, load_settings
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.tools.registry import ToolRegistry


def test_config_history_max_chars_1m():
    """history_max_chars 放大到 1M（对齐 1M 上下文窗口）."""
    assert Settings.history_max_chars == 1_000_000


def test_config_tool_output_chars_100k():
    assert Settings.tool_max_output_chars == 100_000


def test_config_summary_input_chars_100k():
    assert Settings.summary_max_input_chars == 100_000


def test_config_extract_input_chars_100k():
    assert Settings.extract_max_input_chars == 100_000


def test_env_override_preserved(monkeypatch):
    """env 覆盖机制延续（放大默认值后 env 仍可覆盖）."""
    monkeypatch.setenv("HISTORY_MAX_CHARS", "123456")
    monkeypatch.setenv("TOOL_MAX_OUTPUT_CHARS", "654321")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    s = load_settings()
    assert s.history_max_chars == 123456
    assert s.tool_max_output_chars == 654321


def test_history_compression_pair_atomic_2m():
    """2M 大输入历史压缩：assistant(tool_calls) 与其 tool 响应配对原子（协议不断裂）."""
    msgs: list[Message] = []
    for k in range(400):  # 构造大量配对组（大字符触发压缩）
        calls = [{"id": f"c{k}_0", "name": "web_fetch", "arguments": "{}"}]
        msgs.append(Message(role="assistant", content=f"调用 {k}", source=MessageSource.USER, tool_calls=calls))
        msgs.append(Message(role="tool", content="x" * 2000, source=MessageSource.TOOL, tool_call_id=f"c{k}_0"))
    msgs.append(Message(role="user", content="最新问题", source=MessageSource.USER))
    out = build_history_messages(msgs, system_prompt="SYS", max_chars=500_000)

    i = 0
    n = len(out)
    while i < n:
        d = out[i]
        if d["role"] == "assistant" and d.get("tool_calls"):
            n_calls = len(d["tool_calls"])
            j = i + 1
            while j < n and out[j]["role"] == "tool":
                j += 1
            assert (j - (i + 1)) == n_calls, f"配对断裂: assistant({n_calls}) 后 tool {j-i-1}"
            i = j
        else:
            i += 1


def test_tool_oversize_archived_not_lost():
    """300K 工具输出：分层摘要注入 + 完整结果另存（EVO-20260811-22a7d3e1 更新验收）.

    演进后行为: 超 summary_threshold(默认5000) 先注入首/尾摘要（远小于硬上限），
    完整结果仍另存至压缩档案可检索找回（信息零丢失不变）。
    """
    registry = ToolRegistry(max_output_chars=100_000)

    class _BigTool:
        name = "big_tool"

        def execute(self, **kwargs):
            from llm_loop.tools.registry import ToolResult, ToolResultStatus

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="k" * 300_000,
                tool_call_id="big_1",
                tool_name="big_tool",
            )

    registry.register(_BigTool())
    from llm_loop.core.message import ToolCall

    call = ToolCall(id="big_1", name="big_tool", arguments={})
    result = registry.execute(call)
    assert len(result.content) <= 100_000 + 200  # 注入内容远小于硬上限（分层摘要）
    assert "[输出摘要]" in result.content  # 分层注入（EVO-20260811-22a7d3e1）
    assert "search_archive 检索找回" in result.content  # 完整结果可检索找回指引


def test_history_within_800k_budget_no_compression():
    """800K 预算内（< 1M）：不触发压缩（全量保留）."""
    msgs = [_m("user", "x" * 300_000), _m("assistant", "y" * 300_000), _m("user", "z" * 100_000)]
    out = build_history_messages(msgs, system_prompt="SYS", max_chars=1_000_000)
    assert len(out) == 4  # system + 3 条全量保留
    assert not any("[上下文压缩]" in str(m.get("content", "")) for m in out)


def _m(role: str, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.USER)
