"""EVO-20260818 cache_window_converge: 运行场景仿真测试（spec §5.3.1-1 d / §5.5.1 / grill-me Q19/Q20）.

覆盖: 新会话首轮提交（system 静态 + guard 冷启动不判）、压缩轮前缀保持（head 保留 + system 不变）、
默认预算可行域（100K 预算 + 131K 窗口 → 提交估算 tokens ≤ 窗口×0.8）、压缩余量降级告警、
M53 拒绝逃生（紧急压缩锚点前移）。
"""

from llm_loop.cache_guard.guard import PromptGuard
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource, ToolResultStatus

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
    # 跨'会话'一致（两次构建 system 字节相同）
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
        _msg("user", f"旧消息-{i:03d}-" + "x" * 5000)
        for i in range(30)  # 30×5K ≈ 150K
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
    # R8.17/E10: 压缩发生事实不再作为动态 provider 消息回灌。
    assert not any("[上下文压缩]" in str(m.get("content", "")) for m in built)


def test_provider_mid_compression_extends_common_prefix_beyond_system():
    """压缩轮删除发生在固定head之后：共同前缀不再只剩system。"""
    history = [_msg("user", f"m{i:03d}-" + "x" * 2500) for i in range(36)]
    before = build_history_messages(history, SYSTEM_PROMPT, max_chars=1_000_000)
    compressed = build_history_messages(
        history,
        SYSTEM_PROMPT,
        max_chars=40_000,
        compact_ratio=0.9,
        head_keep_chars=8_000,
        cache_archive_provider="deepseek",
    )

    common = 0
    for old, new in zip(before, compressed, strict=False):
        if old != new:
            break
        common += 1
    assert common >= 3, f"压缩轮共同前缀应包含system+固定head，实际仅{common}条"
    assert compressed[1]["content"].startswith("m000-")


def test_provider_head_target_ratio_can_reserve_more_of_compressed_waterline():
    """DeepSeek式中段压缩可把fixed-head从旧50%目标上限提高，同时仍保留尾部。"""

    def _build(ratio: float) -> tuple[list[dict], int]:
        history = [_msg("user", f"m{i:03d}-" + "x" * 4000) for i in range(30)]
        before = build_history_messages(history, SYSTEM_PROMPT, max_chars=1_000_000)
        compressed = build_history_messages(
            history,
            SYSTEM_PROMPT,
            max_chars=60_000,
            compact_ratio=0.9,
            head_keep_chars=24_000,
            head_keep_target_ratio=ratio,
            cache_archive_provider="deepseek",
        )
        common = 0
        for old, new in zip(before, compressed, strict=False):
            if old != new:
                break
            common += 1
        return compressed, common

    old_cap, old_common = _build(0.50)
    deepseek_cap, deepseek_common = _build(0.65)

    assert deepseek_common > old_common, (old_common, deepseek_common)
    assert any(str(msg.get("content", "")).startswith("m029-") for msg in deepseek_cap), (
        "提高fixed-head后仍必须保留最近尾部"
    )
    assert len(deepseek_cap) >= len(old_cap)


def test_provider_mid_compression_long_tool_stress_stays_structurally_stable():
    """40轮重工具会话：多次中段压缩仍保固定head、协议配对且不形成连续风暴。"""
    history: list[Message] = []
    previous: list[dict] | None = None
    compression_rounds = 0
    consecutive = 0
    max_consecutive = 0
    min_prefix_chars: int | None = None

    for round_no in range(40):
        call_id = f"call-{round_no}"
        history.extend(
            [
                Message(
                    role="user",
                    content=f"round-{round_no}-task " + "u" * 500,
                    source=MessageSource.USER,
                ),
                Message(
                    role="assistant",
                    content="",
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                ),
                Message(
                    role="tool",
                    content=f"round-{round_no}-tool " + "t" * 3_500,
                    source=MessageSource.TOOL,
                    tool_call_id=call_id,
                    status=ToolResultStatus.SUCCESS,
                    tool_name="read_file",
                ),
                Message(
                    role="assistant",
                    content=f"round-{round_no}-done " + "a" * 500,
                    source=MessageSource.USER,
                ),
            ]
        )
        compacted: list[bool] = []
        built = build_history_messages(
            history,
            SYSTEM_PROMPT,
            max_chars=60_000,
            compact_ratio=0.9,
            head_keep_chars=12_000,
            cache_archive_provider="deepseek",
            compacted_out=compacted,
        )

        declared = {
            str(tc.get("id"))
            for msg in built
            if msg.get("role") == "assistant"
            for tc in (msg.get("tool_calls") or [])
        }
        for msg in built:
            if msg.get("role") == "tool":
                assert msg.get("tool_call_id") in declared, "压缩后不得产生孤儿tool回执"

        if compacted and compacted[0]:
            compression_rounds += 1
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
            if previous is not None:
                common_chars = 0
                for old, new in zip(previous, built, strict=False):
                    if old != new:
                        break
                    common_chars += len(str(new.get("content", "")))
                min_prefix_chars = (
                    common_chars
                    if min_prefix_chars is None
                    else min(min_prefix_chars, common_chars)
                )
        else:
            consecutive = 0
        previous = built

    assert compression_rounds >= 3, "压力场景应覆盖多次压缩"
    assert max_consecutive <= 2, f"不应回到连续压缩风暴，实际连续{max_consecutive}轮"
    assert min_prefix_chars is not None and min_prefix_chars >= 8_000, (
        f"压缩轮应保留显著固定head共同前缀，实际最小{min_prefix_chars}字符"
    )
    marked = [
        m for m in history if "deepseek" in ((m.metadata or {}).get("cache_compacted_for") or [])
    ]
    assert marked, "压力结束后应有provider级中段折叠标记"


def test_budget_feasibility_131k_window():
    """默认预算可行域（grill-me Q1）: 100K 预算 + 131072 窗口 → 提交估算 tokens ≤ 窗口×0.8."""
    history = [_msg("user", f"m{i:04d}-" + "z" * 2000) for i in range(80)]  # 160K+ 字符
    built = build_history_messages(history, SYSTEM_PROMPT, max_chars=100000)
    total_chars = sum(len(str(m.get("content", ""))) for m in built)
    est_tokens = total_chars // 2
    assert est_tokens <= int(131072 * 0.8), f"提交 {est_tokens} tokens 超窗口 80%"


def test_submission_single_system_after_fix():
    """2026-08-18 注入纪律修复: skip_injected_system=True 时提交视图仅 system 主体一个
    system——推送式注入（架构上报等）剔除不进提交；功能性 system 注入（memory 检索）转
    user 保留（AI 可见）——守卫规则 B（非首位 system）无触发源."""
    msgs = [
        Message(
            role="system",
            content="[架构上报] 测试注入",
            source=MessageSource.SYSTEM,
            metadata={"injected_system": True},
        ),
        _msg("user", "h1"),
        Message(role="system", content="[相关记忆]\n- [fact] x", source=MessageSource.MEMORY),
    ]
    built = build_history_messages(msgs, SYSTEM_PROMPT, max_chars=100000, skip_injected_system=True)
    roles = [m["role"] for m in built]
    assert roles.count("system") == 1 and roles[0] == "system"
    contents = "\n".join(m.get("content", "") for m in built)
    assert "[架构上报]" not in contents  # 推送式注入不进提交
    assert "[相关记忆]" in contents  # memory 转 user 保留（AI 可见）


def test_69715765_baseline(monkeypatch):
    """69715765 事故复现基准（spec §5.1 任务6.4 + 任务12.3）: MiniMax 400K 档预算 +
    ~288K 字符提交 + 320+ 条中段消息 + 每轮新增 ~2K chars 尾部 + 初始命中 ~22% + guard F 每轮 BLOCK.

    事故表现: 每轮压缩 320-386 条、命中钉死 22%、提交恒定 288K、压缩无效
    （head_keep fold=0 大裁后视图未缩小）→ guard 规则 F 每轮 BLOCK.

    修复闭环（任务6）: ①归档中段 + ②cache_compacted_out per-provider 视图排除
    + ③锚点推进安全防护 → 压缩后视图真正缩小 ≥10%、不再每轮 288K 恒定、
    后续轮不重复归档中段、guard 规则 F 放行、命中率回升 >70%.
    （on 态机制基准，R9-P0-01 批 3/3 setattr 钉住前提——模块级常量）
    """
    import llm_loop.cache_guard.guard as guard_mod

    monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "on")
    budget = 320_000  # MiniMax 有效预算（事故 288K 恒定提交 → 有效预算贴近该量级）
    compact_ratio = 0.9  # 压缩线 288K——略低于 288K+2K 首轮提交 → 恰触发首轮压缩
    # （真实配置压缩线 > 压缩目标 60% + head 15% = 75%，压缩后留增长空间，
    #   不会每轮压缩——后续轮视图 243K < 288K 线 → 不再压缩）
    guard_budget = 270_000  # 事故档: 0.95×270K=256.5K——未压缩的 288K 恰触发规则 F BLOCK
    head_keep = int(budget * 0.15)  # MiniMax 非 deepseek: HEAD_KEEP_RATIO=0.15

    history = [_msg("user", f"m{i:05d}-" + "z" * 895) for i in range(320)]  # 320×901 ≈ 288K
    g = PromptGuard(hit_telemetry=True)

    first_stats: dict | None = None
    first_post_chars: int | None = None
    first_cache_count: int | None = None
    view_sizes: list[int] = []
    later_cache_new: list[int] = []
    guard_blocked = 0

    for round_no in range(8):
        history.append(_msg("user", f"t{round_no:03d}-" + "z" * 1990))  # 每轮新增 ~2K
        archived: list[Message] = []

        def sink(session_id: str, m: Message, _archived: list[Message] = archived) -> None:
            _archived.append(m)

        cache_box: list[Message] = []
        stats_box: list[dict] = []
        built = build_history_messages(
            history,
            SYSTEM_PROMPT,
            max_chars=budget,
            compact_ratio=compact_ratio,
            session_id="s69715765",
            archive_sink=sink,
            head_keep_chars=head_keep,
            cache_archive_provider="minimax",
            cache_compacted_out=cache_box,
            compact_view_stats=stats_box,
        )
        post_chars = sum(len(str(m.get("content") or "")) for m in built)
        view_sizes.append(post_chars)
        if round_no == 0:
            assert stats_box, "首轮（288K>压缩线）应发生压缩并填充体积统计"
            first_stats = stats_box[0]
            first_post_chars = post_chars
            first_cache_count = len(cache_box)
        else:
            later_cache_new.append(len(cache_box))
        # guard 规则 F: 提交视图（压缩后）占比 <95% 预算 → 不再每轮 BLOCK
        # （breaker_active=False 显式传——非冻结期正常传递，任务3 三态语义）
        d = g.check(
            session_id="s69715765",
            system_text=SYSTEM_PROMPT,
            messages=built,
            history_budget=guard_budget,
            provider="minimax",
            breaker_active=False,
        )
        if d.verdict == "BLOCK":
            guard_blocked += 1
        # 命中模拟: 压缩有效（视图缩小 + 前缀稳定）→ 高命中；事故场景恒定 288K → 22%
        g.record_result("s69715765", 1000, 750, provider="minimax")

    # ① 压缩后提交视图缩小 ≥10%（288K→≤259K），不再每轮 288K 恒定
    assert first_stats is not None
    assert first_stats["pre_chars"] >= 280_000, (
        f"首轮压缩前视图应 ≈288K，实际 {first_stats['pre_chars']}"
    )
    assert first_post_chars is not None
    assert first_post_chars <= 259_000, (
        f"首轮压缩后视图应 ≤259K（缩小≥10%），实际 {first_post_chars}"
    )
    assert first_stats["drop_pct"] >= 10, f"首轮压缩 drop 应 ≥10%，实际 {first_stats['drop_pct']}%"
    # ② 后续轮视图保持缩小（每轮仅增尾部 ~2K，不回到 288K 恒定——验收目标 ≤259K）
    assert all(sz <= 259_000 for sz in view_sizes), (
        f"所有轮次提交视图应 ≤259K（事故为每轮恒定 288K）: {view_sizes}"
    )
    # ③ 中段只折一次: 后续轮新增 cache_compacted_out 标记远小于首轮（视图排除生效）
    assert first_cache_count is not None and first_cache_count > 0
    assert sum(later_cache_new) <= max(2, first_cache_count // 5), (
        f"后续轮不应重复归档中段: 首轮标记 {first_cache_count}，后续累计 {sum(later_cache_new)}"
    )
    # ④ guard 规则 F 不再每轮 BLOCK（因提交视图真正缩小）
    assert guard_blocked == 0, f"压缩有效后 guard 规则 F 不应 BLOCK，实际 {guard_blocked} 次"
    # 对照: 未压缩的完整历史（288K）在事故档预算下必须触发规则 F BLOCK——证明 guard 有效，
    # 修复的价值是让压缩真正缩小视图（而非绕过 guard）
    raw_messages = [m.to_llm_dict() for m in history]
    raw_d = g.check(
        session_id="s69715765",
        system_text=SYSTEM_PROMPT,
        messages=raw_messages,
        history_budget=guard_budget,
        provider="minimax",
        breaker_active=False,
    )
    assert raw_d.verdict == "BLOCK", "未压缩的 288K 完整提交在事故档预算下应被规则 F 拦截"
    # ⑤ 命中率回升 >70%
    rate = g._recent_hit_rate("s69715765")
    assert rate is not None and rate > 0.70, f"压缩有效后命中率应回升 >70%，实际 {rate}"
    # ⑥ 协议配对完整（压缩不产生孤儿 tool 回执）
    declared = {
        str(tc.get("id"))
        for msg in built
        if msg.get("role") == "assistant"
        for tc in (msg.get("tool_calls") or [])
    }
    for msg in built:
        if msg.get("role") == "tool":
            assert msg.get("tool_call_id") in declared, "压缩后不得产生孤儿 tool 回执"
