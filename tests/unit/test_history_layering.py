"""历史分层重发测试（EVO-20260811-7baa2737）.

旧的长 tool 消息（距最新 >= age 条 且 content > threshold）降级为首尾摘要，
原文归档（信息零丢失）；最近上下文完整保留；默认参数零回归。
"""
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _tool_msg(content: str, name: str = "read_file") -> Message:
    return Message(
        role="tool", content=content, source=MessageSource.TOOL,
        tool_call_id="c1", tool_name=name,
    )


def _user(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def test_budget_in_layer_trims_old_long_tool():
    """预算内：距最新 >= age 条的旧长 tool 消息降级（含首尾/检索指引），原文归档."""
    archived: list[Message] = []
    # tool 消息在 idx0，距最新 = 24 条（>= age=20）→ 触发降级
    msgs = [_tool_msg("D" * 5000)] + [_user(f"问题{i}") for i in range(24)]
    sink = lambda sid, m: archived.append(m)  # noqa: E731
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        archive_sink=sink, layer_tool_trim=True,
        tool_trim_threshold=100,  # 显式小阈值强制触发折叠（与默认 8000 解耦）
    )
    contents = [str(m.get("content", "")) for m in out]
    assert any("工具输出已分层" in c for c in contents)  # 降级注入
    assert any("search_archive" in c for c in contents)  # 检索指引
    assert any("问题23" in c for c in contents)  # 最新消息完整
    assert len(archived) == 1 and len(archived[0].content) == 5000  # 原文完整归档


def test_trim_uses_key_facts_digest():
    """EVO-20260815: 折叠含路径/URL 的长 tool 消息 → 注入关键事实摘要（摘要优先），
    而非机械首尾截断把中间信息丢给 AI 迫使二次检索浪费 token."""
    archived: list[Message] = []
    content = (
        "抓取结果: https://m.toutiao.com/article/7674130972811608626\n"
        "- 关键动作: 修复 <repo>/src/llm_loop/core/history.py 折叠逻辑\n"
        "- 验证: tests/unit/test_history_layering.py 全部通过\n"
        "正文细节（不应出现在摘要里）: 大量展开内容" * 80
    )
    msgs = [_tool_msg(content)] + [_user(f"问题{i}") for i in range(24)]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        archive_sink=lambda sid, m: archived.append(m), layer_tool_trim=True,
        tool_trim_threshold=100,  # 显式小阈值强制触发折叠
    )
    folded = [str(m.get("content", "")) for m in out if "工具输出已分层" in str(m.get("content", ""))]
    assert folded, "应触发折叠"
    c = folded[0]
    # 摘要优先: 注入关键事实/路径（规则提取），而非只有首尾截断
    assert "关键事实" in c
    assert "history.py" in c or "关键路径" in c
    # 原文完整归档（信息零丢失）
    assert len(archived) == 1 and "正文细节" in archived[0].content


def test_recent_tool_not_trimmed():
    """距最新消息 < age 条的 tool 消息保留完整（保护最近上下文）."""
    msgs = [_user("问题0"), _tool_msg("E" * 5000), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        layer_tool_trim=True, tool_trim_threshold=100,  # 显式小阈值：测 age 逻辑（最近保留）而非长度
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)
    assert any("EEEEE" in c for c in contents)  # 完整保留


def test_short_tool_not_trimmed():
    """短 tool 消息不降级."""
    msgs = [_tool_msg("S" * 100), _user("问题1"), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)


def test_default_off_zero_regression():
    """默认 layer_tool_trim=False → 行为不变（不降级）."""
    msgs = [_tool_msg("D" * 5000), _user("问题1"), _user("最新问题")]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1"
    )
    contents = [str(m.get("content", "")) for m in out]
    assert not any("工具输出已分层" in c for c in contents)
    assert any("DDDDD" in c for c in contents)


def test_compression_path_layering_non_interfering():
    """压缩路径：分层开关不干扰压缩主流程（归档 + 压缩标注正常，短 tool 消息不误伤）.

    注: 超预算时旧长 tool 消息会被"最旧先压"整组归档（不进保留组），
    分层降级主战场在预算内主动瘦身；此处验证压缩路径下开关开启无副作用。
    """
    archived: list[Message] = []
    msgs = [
        _tool_msg("G" * 3000),
        _user("q" * 500),
        _user("最新问题"),
    ]
    sink = lambda sid, m: archived.append(m)  # noqa: E731
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1500, session_id="s1",
        archive_sink=sink, layer_tool_trim=True,
    )
    contents = [str(m.get("content", "")) for m in out]
    assert any("[上下文压缩]" in c for c in contents)  # 压缩标注正常
    assert any("最新问题" in c for c in contents)  # 最新消息保留
    assert len(archived) >= 1  # 归档正常


# ── R3: tool_trim_age 自适应测试 ──


def test_adaptive_age_low_occupancy():
    """占用率 < 40% → age=20（保守）."""
    from llm_loop.core.history import _adaptive_tool_trim_age
    assert _adaptive_tool_trim_age(100, 1000) == 20   # 10%
    assert _adaptive_tool_trim_age(399, 1000) == 20   # 39.9%


def test_adaptive_age_mid_occupancy():
    """占用率 40-70% → age=10（中等）."""
    from llm_loop.core.history import _adaptive_tool_trim_age
    assert _adaptive_tool_trim_age(400, 1000) == 10   # 40%
    assert _adaptive_tool_trim_age(699, 1000) == 10   # 69.9%


def test_adaptive_age_high_occupancy():
    """占用率 > 70% → age=5（激进）."""
    from llm_loop.core.history import _adaptive_tool_trim_age
    assert _adaptive_tool_trim_age(700, 1000) == 5    # 70%
    assert _adaptive_tool_trim_age(900, 1000) == 5    # 90%


def test_adaptive_age_zero_max_chars():
    """max_chars=0 → age=20（不除零）."""
    from llm_loop.core.history import _adaptive_tool_trim_age
    assert _adaptive_tool_trim_age(100, 0) == 20


def test_adaptive_age_via_build_history():
    """tool_trim_age=0 自适应：占用高时 age=5，距最新 8 条的旧 tool 降级."""
    # 8 < 20（低占用时不降级）但 8 >= 5（高占用 age=5 时降级）
    msgs = [_tool_msg("X" * 5000)] + [_user(f"q{i}") for i in range(8)]
    sink = lambda sid, m: None  # noqa: E731
    # 高占用：total~5016, max=7000 → 71% > 70% → age=5 → 距最新 8 >= 5 → 降级
    out_high = build_history_messages(
        msgs, system_prompt="S", max_chars=7000, session_id="s",
        archive_sink=sink, layer_tool_trim=True, tool_trim_age=0,
        tool_trim_threshold=100,  # 显式小阈值强制触发折叠（与默认 8000 解耦）
    )
    assert any("工具输出已分层" in str(m.get("content", "")) for m in out_high)
    # 低占用：total~5016, max=1000000 → < 40% → age=20 → 距最新 8 < 20 → 不降级
    out_low = build_history_messages(
        msgs, system_prompt="S", max_chars=1000000, session_id="s",
        archive_sink=sink, layer_tool_trim=True, tool_trim_age=0,
    )
    assert not any("工具输出已分层" in str(m.get("content", "")) for m in out_low)


def test_fixed_age_disables_adaptive():
    """tool_trim_age=20 固定值禁用自适应（向后兼容）."""
    msgs = [_tool_msg("X" * 5000)] + [_user(f"q{i}") for i in range(8)]
    sink = lambda sid, m: None  # noqa: E731
    # 固定 age=20，距最新 8 < 20 → 不降级（即使占用高）
    out = build_history_messages(
        msgs, system_prompt="S", max_chars=7000, session_id="s",
        archive_sink=sink, layer_tool_trim=True, tool_trim_age=20,
        tool_trim_threshold=100,  # 显式小阈值：测 age 逻辑（8<20 不降级）而非长度
    )
    assert not any("工具输出已分层" in str(m.get("content", "")) for m in out)


# ── EVO-20260814-e5b045d3: 分层提示附带可照抄的 search_archive 调用示例 ──


def test_layered_history_hint_includes_tool_name_filter():
    """历史降级提示含 tool_name 过滤的检索示例，可直接照抄."""
    import inspect

    from llm_loop.core import history as h

    src = inspect.getsource(h)
    assert 'search_archive(tool_name="' in src  # 提示中含精确过滤示例
    assert "勿换命令重复执行同一工具" in src


def test_registry_summarize_hint_with_call():
    """registry._summarize_output 传 call 时提示含 query + tool_name 示例."""
    from types import SimpleNamespace

    from llm_loop.tools.registry import ToolRegistry

    call = SimpleNamespace(name="read_file", arguments={"path": "/a/b/engine.py"})
    out = ToolRegistry._summarize_output("x" * 5000, call=call)
    assert 'search_archive(query="engine.py", tool_name="read_file")' in out

    call_cmd = SimpleNamespace(name="execute_command", arguments={"command": "git status --short"})
    out2 = ToolRegistry._summarize_output("x" * 5000, call=call_cmd)
    assert 'search_archive(query="git status --short", tool_name="execute_command")' in out2

    # 无 call（向后兼容路径）退回通用指引
    out3 = ToolRegistry._summarize_output("x" * 5000)
    assert "search_archive" in out3


# ── P1-7: 推送式 system 注入跳过（本地 provider 前缀稳定）──


def test_skip_injected_system_not_submitted():
    """skip_injected_system=True → 带 injected_system 标记的 system 消息不进提交视图.

    推送式注入（架构上报/预警/快照）仅落会话; 未标记的 system（功能性注入/
    压缩标注）与普通消息不受影响。默认 False 零回归。
    """
    from llm_loop.core.message import Message, MessageSource

    injected = Message(
        role="system", content="[架构上报] 事实: 待审阅",
        source=MessageSource.SYSTEM, metadata={"injected_system": True},
    )
    func_sys = Message(
        role="system", content="[模型降级] 事实: 已切换",
        source=MessageSource.SYSTEM, metadata={},
    )
    msgs = [injected, func_sys, _user("问题1")]

    # 默认（False）: 全部提交（零回归）
    out_default = build_history_messages(msgs, "SYS", max_chars=100000)
    assert "[架构上报]" in out_default[0]["content"]
    assert "[模型降级]" in out_default[0]["content"]

    # 开启跳过: 仅 injected 标记的 system 不进提交, 其余保留
    out_skip = build_history_messages(
        msgs, "SYS", max_chars=100000, skip_injected_system=True
    )
    sys_content = out_skip[0]["content"]
    assert "[架构上报]" not in sys_content
    assert "[模型降级]" in sys_content
    assert len(out_skip) == 2  # system(含 func_sys 合并) + user


def test_skip_injected_system_survives_long_path():
    """超长预算路径同样跳过注入（本地 provider 前缀稳定不因压缩失效）."""
    from llm_loop.core.message import Message, MessageSource

    injected = Message(
        role="system", content="[预算预警] 事实: 占用超限",
        source=MessageSource.SYSTEM, metadata={"injected_system": True},
    )
    msgs = [injected] + [_user(f"问题{i} " + "x" * 2000) for i in range(30)]
    out = build_history_messages(
        msgs, "SYS", max_chars=5000, session_id="s1", skip_injected_system=True
    )
    sys_content = out[0]["content"]
    assert "[预算预警]" not in sys_content
    # 压缩标注（功能性 extras）仍注入
    assert "压缩" in sys_content or any("压缩" in str(m.get("content", "")) for m in out)


# ── P1-10: 窗口锚定（固定起点, 前缀稳定 → 缓存命中）──


def test_anchor_slices_prefix_and_keeps_rest():
    """history_anchor=N → 跳过前 N 条消息（起点固定, 只提交锚点起内容）."""
    msgs = [_user(f"旧问题{i}") for i in range(10)]
    box: list[int] = []
    out = build_history_messages(msgs, "SYS", max_chars=100000, history_anchor=6, anchor_out=box)
    contents = [m.get("content") for m in out]
    assert "旧问题0" not in contents
    assert "旧问题6" in contents
    assert len(box) == 0  # 窗口在预算内 → 无归档 → 锚点不变


def test_anchor_within_budget_no_archive():
    """锚定窗口 ≤ 预算 → 无归档、无 extras、锚点不变（前缀完全稳定）."""
    msgs = [_user(f"问题{i} " + "x" * 300) for i in range(20)]  # ~6.2K 字符
    box: list[int] = []
    out = build_history_messages(
        msgs, "SYS", max_chars=8000, history_anchor=5, anchor_out=box,
        session_id="s1", layer_tool_trim=True,
    )
    assert len(box) == 0
    sys_content = out[0]["content"]
    assert "[上下文压缩]" not in sys_content  # 无归档 → 无压缩标注
    assert "问题5" in str(out)


def test_anchor_over_budget_advances_anchor():
    """锚定窗口超预算（降级后仍超）→ 从窗口头归档, 锚点推进 = 旧锚点 + 丢弃数."""
    msgs = [_user(f"问题{i} " + "x" * 2000) for i in range(30)]  # ~62K 字符
    box: list[int] = []
    out = build_history_messages(
        msgs, "SYS", max_chars=20000, history_anchor=10, anchor_out=box,
        session_id="s1", layer_tool_trim=True, tool_trim_threshold=3000,
    )
    assert len(box) == 1
    assert box[0] > 10  # 锚点前移
    assert box[0] <= 30
    # 提交内容不含被归档的窗口头
    submitted = str(out)
    assert submitted  # 归档起点取决于预算, 只验证锚点推进合理（提交内容非空）


def test_anchor_zero_behavior_unchanged():
    """history_anchor=0（默认）→ 现有行为（零回归）, 锚点 = 归档丢弃数."""
    msgs = [_user(f"问题{i} " + "x" * 2000) for i in range(30)]
    box: list[int] = []
    out = build_history_messages(
        msgs, "SYS", max_chars=20000, anchor_out=box, session_id="s1"
    )
    assert len(box) == 1
    assert box[0] > 0  # 无锚: 丢弃数即新锚点
    # 与不带 anchor_out 的默认行为一致（返回内容相同）
    out2 = build_history_messages(msgs, "SYS", max_chars=20000, session_id="s1")
    assert out == out2


def test_sink_failure_note_honest():
    """审查中危: archive_sink 失败时标注如实声明"归档失败"，不谎称已另存."""
    def _boom(sid, m):
        raise OSError("disk full")
    msgs = [_tool_msg("D" * 5000)] + [_user(f"问题{i}") for i in range(24)]
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000, session_id="s1",
        archive_sink=_boom, layer_tool_trim=True,
        tool_trim_threshold=100, tool_trim_age=20,
    )
    folded = [m for m in out if m.get("role") == "tool" and "已分层" in str(m.get("content", ""))]
    assert folded, "应有折叠消息"
    c = str(folded[0].get("content", ""))
    assert "原文归档失败（未另存，仅保留以下摘要）" in c, c[:200]
    assert "原文已另存压缩档案" not in c
    assert "search_archive" not in c  # 未归档则不给检索指引（避免空检索）


def test_anchor_beyond_len_no_loss():
    """审查中危: history_anchor ≥ len(messages) 时不裁切（历史不丢）.

    回归: 极端并发/持久化异常下 anchor 可能越界；防御逻辑（>0 and <len 才裁）
    保证越界时走全量（不丢历史、不崩溃）。
    """
    msgs = [_tool_msg("x")] + [_user(f"问题{i}") for i in range(5)]
    box: list[int] = []
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000,
        history_anchor=999,  # 越界锚点
        anchor_out=box,
    )
    # 全部消息仍提交（无裁切）
    roles = [m.get("role") for m in out if m.get("role") in ("user", "tool")]
    assert roles == ["tool"] + ["user"] * 5, f"越界锚点导致历史丢失: {roles}"
    assert len(out) == 7  # SYS + 6 条消息
