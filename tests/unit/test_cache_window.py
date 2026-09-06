"""单元测试: 缓存窗口镜像（describe_cache_window, 2026-08-24）.

把服务端 cached_tokens 估算映射回提交载荷的消息级窗口——缓存覆盖区/新增区（miss 区）。
该映射仅供观测；generic cached_tokens 不提供精确 message boundary，不能作为硬压缩约束。
"""

from __future__ import annotations

from llm_loop.core.cache_window import describe_cache_window


def _m(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_full_hit_all_cached():
    """cached >= prompt（全命中）→ 全部消息在缓存区, 无新增."""
    msgs = [_m("system", "S" * 100), _m("user", "U" * 100), _m("assistant", "A" * 100)]
    # 显式 chars_per_token=2（ASCII 载荷旧估算口径）: 150 tokens = 300 字符 = 全载荷
    win = describe_cache_window(msgs, cached_tokens=150, prompt_tokens=150, chars_per_token=2)
    assert win.hit_ratio == 1.0
    assert len(win.new_msgs) == 0
    assert len(win.cached_msgs) == 3
    assert win.boundary_msg_index == 2
    assert win.boundary_exact is False


def test_default_ratio_calibrated():
    """默认估算已校准（2026-08-24 拷问产出）: 0.6 chars/token（≈1.67 tok/char, 实测大上下文）.

    与旧值 2 的差异是**有意校准**（旧值低估 token 3.35 倍 → 守卫失效/边界失真）——
    此测试钉住新默认, 防止误回退。
    """
    from llm_loop.core.cache_window import _CHARS_PER_TOKEN
    from llm_loop.core.loop.engine_services.routing import _CHARS_PER_TOKEN_EST as _R
    from llm_loop.core.loop.engine_services.runtime_params import (
        _CHARS_PER_TOKEN_EST as _RP,
    )

    assert _CHARS_PER_TOKEN == 0.6
    assert _R == 0.6
    assert _RP == 0.6
    # 示例: 688K tokens（08-23 实测峰值）按 0.6 → ~41 万字符边界（旧估算 137 万, 失真）
    assert int(688_808 * 0.6) == 413_284


def test_zero_hit_all_new():
    """cached=0（冷启动/断前缀）→ 全部为新增区."""
    msgs = [_m("system", "S" * 100), _m("user", "U" * 100)]
    win = describe_cache_window(msgs, cached_tokens=0, prompt_tokens=100)
    assert win.hit_ratio == 0.0
    assert len(win.cached_msgs) == 0
    assert len(win.new_msgs) == 2
    assert win.boundary_msg_index == -1
    assert win.boundary_exact is False


def test_partial_boundary_mid_message():
    """边界落在某条消息内容中间 → 该条标记 partial, 其后为新增区."""
    msgs = [_m("system", "S" * 100), _m("user", "U" * 100), _m("assistant", "A" * 100)]
    # 100+100=200 字符 ≈ 100 tokens; cached 80 tokens = 160 字符 → 边界落在 user 中间
    win = describe_cache_window(msgs, cached_tokens=80, prompt_tokens=200, chars_per_token=2)
    assert win.boundary_msg_index == 1
    assert win.cached_msgs[-1]["partial"] is True
    assert len(win.new_msgs) == 1  # assistant 为新增
    assert win.boundary_chars == 160


def test_boundary_at_message_edge():
    """边界恰好落在消息边界 → 该条整条缓存（非 partial）."""
    msgs = [_m("system", "S" * 100), _m("user", "U" * 100), _m("assistant", "A" * 100)]
    # 100 字符 = 50 tokens → 边界在 system/user 交界
    win = describe_cache_window(msgs, cached_tokens=50, prompt_tokens=200, chars_per_token=2)
    assert win.boundary_msg_index == 0
    assert win.cached_msgs[-1]["partial"] is False
    assert len(win.new_msgs) == 2


def test_empty_messages_and_invalid_inputs():
    """空载荷 / 非法 token 输入 → 空窗口不抛异常（fail-open）."""
    assert describe_cache_window([], cached_tokens=10, prompt_tokens=10).boundary_msg_index == -1
    win = describe_cache_window([_m("user", "hi")], cached_tokens="abc", prompt_tokens=None)
    assert win.cached_tokens == 0 and win.prompt_tokens == 0
    assert win.boundary_exact is False
    assert len(win.new_msgs) == 1


def test_tool_round_system_only_cached():
    """零历史工具轮典型形态: 公共前缀只有 system+工具, 配对组为新增区.

    模拟: round k 提交 [system, tools, assistant(k), tool(k)]; round k+1 提交
    [system, tools, assistant(k+1), tool(k+1)] —— 服务端前缀命中只覆盖 system+tools.
    """
    msgs = [
        _m("system", "S" * 300),
        _m("assistant", '{"tool":"read_file"}'),
        _m("tool", "[结果] 文件内容 200 字符。" + "x" * 200),
    ]
    # system 300 字符 ≈ 150 tokens 命中; 配对组 ~200 字符 ≈ 100 tokens 新增
    win = describe_cache_window(msgs, cached_tokens=150, prompt_tokens=250)
    assert win.boundary_msg_index == 0
    assert len(win.new_msgs) == 2  # 声明 + 回执均在缓存区外（每轮变化）
    assert win.summary().startswith("估算缓存覆盖至消息#0")
    assert "新增 2 条" in win.summary()


def test_answer_round_long_history_cached():
    """回答轮典型形态: 历史大多命中, 仅最新消息新增（追加不破坏命中）."""
    msgs = [_m("system", "S" * 1000)] + [
        _m(("user" if i % 2 == 0 else "assistant"), "M" * 100) for i in range(10)
    ]
    # 总 2000 字符 = 1000 tokens; cached 950 tokens = 1900 字符 → 缓存至 M8, 仅 M9 新增
    win = describe_cache_window(msgs, cached_tokens=950, prompt_tokens=1000, chars_per_token=2)
    assert win.hit_ratio == 0.95
    assert len(win.new_msgs) == 1
    assert win.new_msgs[0]["index"] == 10  # 最后一条 user 为新增
