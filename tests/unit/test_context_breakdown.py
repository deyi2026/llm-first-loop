"""R1: context_usage.breakdown 组件级占用分解测试.

验证:
- 数值正确（各组件字符数/token/占比）
- 纯只读无副作用（多次调用结果一致）
- budget/ratio 计算
- 零组件时不出错
"""
from __future__ import annotations

from llm_loop.core.history import compute_breakdown
from llm_loop.core.message import Message, MessageSource


def _user(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def _tool(content: str, name: str = "read_file") -> Message:
    return Message(
        role="tool", content=content, source=MessageSource.TOOL,
        tool_call_id="c1", tool_name=name,
    )


def _assistant(content: str) -> Message:
    return Message(role="assistant", content=content, source=MessageSource.USER)


def test_breakdown_values_correct():
    """各组件字符数/token/占比正确."""
    msgs = [_user("你好"), _tool("X" * 1000), _assistant("回复")]
    bd = compute_breakdown(msgs, "SYS", None, tool_schema_chars=200, budget=10000)
    assert bd["system"]["chars"] == 3          # "SYS"
    assert bd["memory"]["chars"] == 0          # None
    assert bd["history"]["chars"] == 2 + 2     # "你好" + "回复" (非 tool)
    assert bd["tool_results"]["chars"] == 1000
    assert bd["tool_schema"]["chars"] == 200
    total = 3 + 0 + 4 + 1000 + 200
    assert bd["total"]["chars"] == total
    assert bd["total"]["est_tokens"] == total // 2
    assert bd["budget"] == 10000
    assert bd["ratio"] == round(total / 10000, 3)


def test_breakdown_with_memory_msgs():
    """memory_msgs 计入 memory 组件."""
    mem = [_user("记忆1"), _assistant("记忆2")]
    msgs = [_user("问题")]
    bd = compute_breakdown(msgs, "S", mem, budget=1000)
    assert bd["memory"]["chars"] == 3 + 3  # "记忆1" + "记忆2"


def test_breakdown_no_side_effect():
    """纯只读：多次调用结果一致，不修改入参."""
    msgs = [_user("测试"), _tool("Y" * 500)]
    original_content = msgs[1].content
    bd1 = compute_breakdown(msgs, "SYS", None, budget=10000)
    bd2 = compute_breakdown(msgs, "SYS", None, budget=10000)
    assert bd1 == bd2
    assert msgs[1].content == original_content  # 未修改入参


def test_breakdown_empty_messages():
    """空消息列表不出错."""
    bd = compute_breakdown([], "", None, budget=1000)
    assert bd["total"]["chars"] == 0
    assert bd["ratio"] == 0.0
    assert bd["system"]["chars"] == 0


def test_breakdown_zero_budget():
    """budget=0 时 ratio 为 None（不除零）."""
    bd = compute_breakdown([_user("x")], "S", None, budget=0)
    assert bd["ratio"] is None


def test_breakdown_pct_sums_to_100():
    """各组件占比之和约等于 100."""
    msgs = [_user("A" * 100), _tool("B" * 200), _assistant("C" * 50)]
    bd = compute_breakdown(msgs, "D" * 30, None, tool_schema_chars=70, budget=10000)
    pct_sum = (
        bd["system"]["pct"]
        + bd["memory"]["pct"]
        + bd["history"]["pct"]
        + bd["tool_results"]["pct"]
        + bd["tool_schema"]["pct"]
    )
    assert abs(pct_sum - 100.0) < 0.2  # 浮点容差


def test_breakdown_est_tokens_is_chars_div_2():
    """est_tokens = chars // 2（既有估算口径）."""
    msgs = [_user("X" * 101)]
    bd = compute_breakdown(msgs, "S", None, budget=1000)
    assert bd["history"]["est_tokens"] == 101 // 2


def test_breakdown_tool_schema_chars_in_loop(build_test_engine):
    """R1 修复: loop 中 _last_breakdown 的 tool_schema chars > 0（修复前恒为 0）."""
    engine, _fake = build_test_engine([{"content": "done"}])
    engine.run("test-session", "你好")
    bd = getattr(engine, "_last_breakdown", None)
    assert bd is not None
    assert bd["tool_schema"]["chars"] > 0
    assert bd["total"]["chars"] > bd["history"]["chars"] + bd["tool_results"]["chars"]


# ── 基于实际发送载荷的分解（compute_breakdown_from_dicts）──


def test_breakdown_from_dicts_measures_built_payload():
    """R1 口径修复: 分解基于构建后的协议 dict（已压缩归档历史不计入占用）.

    旧口径统计原始会话（几百万字符）→ 本地慢模型收紧预算后占用虚高数十倍,
    误导 [预算预警]/AI 压缩决策; 新口径只统计真正发送的载荷。
    """
    from llm_loop.core.history import compute_breakdown_from_dicts

    msgs = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "回答", "reasoning_content": "思考中" * 10},
        {"role": "tool", "content": "工具输出" * 50, "tool_call_id": "t1"},
    ]
    bd = compute_breakdown_from_dicts(msgs, tool_schema_chars=500, budget=12000)
    assert bd["system"]["chars"] == 3
    assert bd["history"]["chars"] == 4
    assert bd["tool_results"]["chars"] == 200
    assert bd["tool_schema"]["chars"] == 500
    assert bd["reasoning"]["chars"] == 30
    assert bd["memory"]["chars"] == 0  # 协议层记忆消息不可区分, 如实为 0
    assert bd["total"]["chars"] == 3 + 4 + 200 + 500 + 30
    assert bd["budget"] == 12000
    assert bd["ratio"] == round(bd["total"]["chars"] / 12000, 3)
    # 预算 <= 0 → ratio None（与 compute_breakdown 同语义）
    assert compute_breakdown_from_dicts(msgs, budget=0)["ratio"] is None
    # pct 总和 ≈ 100
    pct = sum(
        bd[k]["pct"] for k in ("system", "memory", "history", "tool_results", "tool_schema", "reasoning")
    )
    assert abs(pct - 100.0) < 0.2
