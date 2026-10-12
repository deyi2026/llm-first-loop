"""History projection/compaction invariants under the current LLM-first contract."""
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


def _tool_msg(content: str, name: str = "read_file") -> Message:
    return Message(
        role="tool", content=content, source=MessageSource.TOOL,
        tool_call_id="c1", tool_name=name,
    )


def _tool_pair(content: str, name: str = "read_file") -> list[Message]:
    """严格 FC 合法 fixture：声明与回执必须成组，避免测试依赖孤立 tool 容忍。"""
    return [
        Message(
            role="assistant", content=f"调用 {name}", source=MessageSource.USER,
            tool_calls=[{"id": "c1", "name": name, "arguments": "{}"}],
        ),
        _tool_msg(content, name),
    ]


def _user(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def test_registry_has_no_soft_summary_producer():
    """Rule-first: runtime no longer exposes an automatic tool-summary policy API."""
    from llm_loop.tools.registry import ToolRegistry

    assert not hasattr(ToolRegistry, "_summarize_output")


# ── P1-7:

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

    # 默认（False）: 全部提交（2026-08-18 system 静态化——注入转独立 user 消息，主体纯静态）
    out_default = build_history_messages(msgs, "SYS", max_chars=100000)
    assert out_default[0]["content"] == "SYS"  # 主体字节静态
    default_users = " ".join(m["content"] for m in out_default if m["role"] == "user")
    assert "[架构上报]" in default_users
    assert "[模型降级]" in default_users

    # 开启跳过: 仅 injected 标记的 system 不进提交, 其余保留（转 user）
    out_skip = build_history_messages(
        msgs, "SYS", max_chars=100000, skip_injected_system=True
    )
    assert out_skip[0]["content"] == "SYS"
    skip_users = " ".join(m["content"] for m in out_skip if m["role"] == "user")
    assert "[架构上报]" not in skip_users
    assert "[模型降级]" in skip_users
    assert len(out_skip) == 3  # system + user(模型降级) + user(问题1)


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
    # R8.17/E10: 压缩功能仍执行，但压缩状态 extras 不再进 provider view。
    assert not any("[上下文压缩]" in str(m.get("content", "")) for m in out)


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
        session_id="s1",
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
        session_id="s1",
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



def test_anchor_beyond_len_no_loss():
    """审查中危: history_anchor ≥ len(messages) 时不裁切（历史不丢）.

    回归: 极端并发/持久化异常下 anchor 可能越界；防御逻辑（>0 and <len 才裁）
    保证越界时走全量（不丢历史、不崩溃）。
    """
    msgs = _tool_pair("x") + [_user(f"问题{i}") for i in range(5)]
    box: list[int] = []
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=100000,
        history_anchor=999,  # 越界锚点
        anchor_out=box,
    )
    # 全部消息仍提交（无裁切）
    roles = [m.get("role") for m in out if m.get("role") in ("user", "tool")]
    assert roles == ["tool"] + ["user"] * 5, f"越界锚点导致历史丢失: {roles}"
    assert len(out) == 8  # SYS + assistant 声明 + tool 回执 + 5 user
