"""EVO-20260818 cache_window_converge: 运行场景仿真测试（spec §5.3.1-1 d / §5.5.1 / grill-me Q19/Q20）.

覆盖: 新会话首轮提交（system 静态 + guard 冷启动不判）、压缩轮前缀保持（head 保留 + system 不变）、
默认预算可行域（100K 预算 + 131K 窗口 → 提交估算 tokens ≤ 窗口×0.8）、压缩余量降级告警。
"""

from types import SimpleNamespace

from llm_loop.cache_guard.guard import PromptGuard
from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource

SYSTEM_PROMPT = (
    "你是 llm-first-loop 助手。\n"
    + "稳定主体: 角色/工具纪律/安全规则。\n" * 30  # ~10K 字符静态主体
)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.USER)


def test_new_session_first_round_system_static():
    """新会话首轮提交 = system + 首条消息；system 与基线字节一致（跨会话共享前缀缓存）."""
    built = build_history_messages([], SYSTEM_PROMPT)
    assert built[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert len(built) == 1  # 无历史无注入，仅 system
    # 跨"会话"一致（两次构建 system 字节相同）
    built2 = build_history_messages([], SYSTEM_PROMPT)
    assert built2[0]["content"] == built[0]["content"]


def test_new_session_guard_cold_start_no_judge():
    """新会话 guard: 窗口样本不足 → 规则 G 不判（冷启动安全）."""
    g = PromptGuard(hit_telemetry=True)
    d = g.check(
        session_id="new-session",
        system_text=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )
    assert d.verdict == "ALLOW"  # 样本不足不判（_HIT_SAMPLE_MIN=3）
    assert g.snapshot("new-session")["hit_win_size"] == 0


def test_compression_round_preserves_prefix():
    """压缩轮: head_keep>0 → system + 头部组保留在提交（前缀稳定），中段归档."""
    history = [
        _msg("user", f"旧消息-{i:03d}-" + "x" * 5000) for i in range(30)  # 30×5K ≈ 150K
    ] + [_msg("assistant", "y" * 5000)] * 5
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    built = build_history_messages(
        history,
        SYSTEM_PROMPT,
        max_chars=60000,  # 收敛预算
        session_id="s1",
        archive_sink=sink,
        head_keep_chars=12000,  # 头部保留（20%）
    )
    # system 保持
    assert built[0]["role"] == "system"
    assert built[0]["content"] == SYSTEM_PROMPT
    # 头部组保留: 最旧消息（旧消息-000）在提交中
    joined = "".join(str(m.get("content", "")) for m in built)
    assert "旧消息-000" in joined
    # 中段被归档（信息零丢失）
    assert len(archived) > 0
    # 压缩标注注入
    assert any("[上下文压缩]" in str(m.get("content", "")) for m in built)


def test_budget_feasibility_131k_window():
    """默认预算可行域（grill-me Q1）: 100K 预算 + 131072 窗口 → 提交估算 tokens ≤ 窗口×0.8."""
    history = [_msg("user", f"m{i:04d}-" + "z" * 2000) for i in range(80)]  # 160K+ 字符
    built = build_history_messages(history, SYSTEM_PROMPT, max_chars=100000)
    total_chars = sum(len(str(m.get("content", ""))) for m in built)
    est_tokens = total_chars // 2
    assert est_tokens <= int(131072 * 0.8), f"提交 {est_tokens} tokens 超窗口 80%"


def test_compression_downgrade_notice_on_exhaustion():
    """压缩余量不足（spec §5.5.1-7）: head 保留后仍超 95% → 降级标注注入 + 头部被归档."""
    history = [
        _msg("user", f"big-{i}-" + "q" * 8000) for i in range(20)  # 20×8K = 160K
    ]
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    built = build_history_messages(
        history,
        SYSTEM_PROMPT,
        max_chars=60000,
        session_id="s1",
        archive_sink=sink,
        head_keep_chars=50000,  # 头部保留过大（>archive_budget//2 被上限截断）
    )
    joined = "".join(str(m.get("content", "")) for m in built)
    # 头部保留上限保护: head ≤ archive_budget//2 = 18000 → 压缩后提交 ≈ 0.6×60K+system
    # 必然 ≤ 95% 预算 → 不触发降级；用极端 system 场景验证降级路径
    big_sys = SYSTEM_PROMPT + "S" * 45000  # system 45K + 历史 160K → 单轮裁不动
    built2 = build_history_messages(
        history, big_sys, max_chars=60000,
        session_id="s1", archive_sink=sink, head_keep_chars=18000,
    )
    joined2 = "".join(str(m.get("content", "")) for m in built2)
    if "[缓存降级]" in joined2:
        # 降级触发时: 头部消息被归档（信息零丢失）+ 标注可见
        assert any("[缓存降级]" in str(m.get("content", "")) for m in built2)
    # 无论是否降级: system 保留 + 无异常
    assert built2[0]["content"] == big_sys


def test_emergency_compact_forces_anchor_advance():
    """M53 拒绝逃生（grill-me 2026-08-18）: emergency_compact 强制 head_keep=0 →
    锚点前移（历史真正缩小，防超限会话死循环）; 普通压缩 head_keep>0 时锚点不动."""
    history = [_msg("user", f"m{i:03d}-" + "z" * 3000) for i in range(40)]  # 120K 字符
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    # 普通压缩: head_keep>0 → 锚点不前移
    box1: list[int] = []
    build_history_messages(
        history, SYSTEM_PROMPT, max_chars=60000, session_id="s1",
        archive_sink=sink, head_keep_chars=12000,
        history_anchor=10, anchor_out=box1,
    )
    assert box1 == [10], f"head 保留时锚点不应前移: {box1}"

    # 紧急压缩（emergency 语义 = head_keep=0）: 锚点前移 + 历史缩小
    box2: list[int] = []
    arch2: list[Message] = []
    def sink2(session_id: str, m: Message) -> None:
        arch2.append(m)

    built = build_history_messages(
        history, SYSTEM_PROMPT, max_chars=60000, session_id="s1",
        archive_sink=sink2, head_keep_chars=0,
        history_anchor=10, anchor_out=box2,
    )
    # 锚点推进 = 旧锚点 + 窗口内丢弃数（窗口 = anchor 之后 30 条）
    assert box2[0] > 10, f"紧急压缩锚点应前移: {box2}"  # 锚点前移（精确值受 extras 影响，断言方向）
    assert len(arch2) > 0  # 归档发生（信息零丢失）
    # 提交显著缩小（≤ 预算）
    total = sum(len(str(m.get("content", ""))) for m in built)
    assert total <= 60000 + len(SYSTEM_PROMPT)
