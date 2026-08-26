"""缓存命中纪律门禁（EVO-20260816-3eb50cf4，Cache-First）.

用户定调: LLM 请求 token 前缀缓存命中是 agent/大模型项目优先考虑项。
本测试把 docs/development_methodology.md 五章"缓存命中纪律"的关键约束固化为
自动化防回归:

- system_prompt 静态（两次调用字节级一致，无时间/随机动态内容）
- tools schema 顺序稳定（两次生成 JSON 一致，防运行时裁剪漂移）
- 前缀稳定（有/无动态注入轮，system_prompt 主体字节级保持命中）
- system_prompt 主体不被截断（Cache-First 核心: 静态段是前缀缓存锚）

2026-08-16 现场: 修复前 system_prompt=6693 字符 > max_sys_merge_chars=4000，
_append_or_merge 把 system_prompt 主体砍到 200 字符——任何 memory/inbox 注入轮
前缀缓存全毁（本文件 4 号测试即该事故的回归护栏）。
"""

import json
import re

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt
from llm_loop.tools.registry import ToolRegistry


def _fake_msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.SYSTEM)


def test_system_prompt_static():
    """1. system_prompt 静态: 两次调用字节级一致 + 无时间/随机动态模式."""
    sp1 = build_system_prompt()
    sp2 = build_system_prompt()
    assert sp1 == sp2, "system_prompt 两次调用必须字节级一致（含时间戳/计数器即破坏前缀）"
    # 无动态模式: 时间戳、uuid、随机（静态规则文本的历史日期如"2026-08-20 R5 事故复盘"
    # 是固定文本允许——测试防的是动态时间注入破坏前缀，sp1==sp2 已证字节级静态）
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", sp1), "system_prompt 不得含 ISO/日期时间戳"
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", sp1), "system_prompt 不得含 uuid"
    assert not re.search(r"random|uuid|time\.", sp1, re.I), "system_prompt 不得引用动态源"


def test_tools_schema_stable():
    """2. tools schema 顺序稳定: 多次生成 JSON 一致（防运行时裁剪/重排/动态内容漂移）.

    注: 生产全量工具集由 factory.build_engine 装配（重依赖），此处注册代表性真实
    工具验证 schemas() 生成逻辑确定性——注册表内容装配期固定，风险在生成逻辑。
    """
    from llm_loop.tools.builtin.edit_file import EditFileTool
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    from llm_loop.tools.builtin.read_file import ReadFileTool

    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(EditFileTool())
    reg.register(ExecuteCommandTool(timeout_s=30))
    assert len(reg.schemas()) >= 3, "注册的真实工具应全部可见（门禁前提）"
    snapshots = [json.dumps(reg.schemas(), ensure_ascii=False, sort_keys=True) for _ in range(3)]
    assert len(set(snapshots)) == 1, (
        "tools schema 多次生成必须一致（运行时裁剪/重排/动态内容会破坏前缀）"
    )


def _build_with_system_injects(sp: str, sys_msgs: list[Message]) -> str:
    """辅助: 经 build_history_messages 合并 system 消息后的 out[0].content."""
    out = build_history_messages(sys_msgs, sp, max_chars=200000)
    assert out and out[0]["role"] == "system"
    return out[0]["content"]


def test_system_prompt_not_truncated_by_dynamic_injects():
    """3. (核心回归) system_prompt 主体永不截断——动态注入只追加尾部.

    修复前 (2026-08-16): system_prompt=6693 > max_sys_merge_chars=4000,
    任何 memory/inbox 合并触发截断分支, 主体被砍到 200 字符 → 前缀缓存全毁.
    修复后: 静态主体完整保留, 只对动态追加段设上限.
    """
    sp = build_system_prompt()
    # 2026-08-20 P2: L0 稳定核心 < max_sys_merge_chars(4000) → 动态合并截断分支结构性不触发
    assert len(sp) < 4000, f"L0 应小于合并上限 4000（现 {len(sp)}）——截断风险结构性消除"
    out = build_history_messages(
        [_fake_msg("system", "MEM-1: 记忆片段"),
         _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核")],
        sp, max_chars=200000,
    )
    # 2026-08-18 对齐 DSH: system 主体纯静态（注入不进主体——转独立 user 消息）
    assert out[0]["role"] == "system"
    assert out[0]["content"] == sp, "system 主体字节级静态（跨会话一致——首轮命中稳定段）"
    # 注入转 user——内容仍在（AI 可见）
    users = [m for m in out if m["role"] == "user"]
    assert any("MEM-1" in m["content"] for m in users), "memory 注入转 user 保留"
    assert any("20260816-006" in m["content"] for m in users), "协调注入转 user 保留"


def test_prefix_stable_with_and_without_inbox():
    """4. 前缀稳定: 无注入轮 content 是有注入轮 content 的严格前缀（追加式合并语义）."""
    sp = build_system_prompt()
    base_sys = [_fake_msg("system", "MEM-1: 记忆片段")]
    no_inbox = _build_with_system_injects(sp, base_sys)
    with_inbox = _build_with_system_injects(sp, base_sys + [
        _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核")
    ])
    # 2026-08-18 对齐 DSH: system 主体跨会话字节一致（注入不进主体——转 user）
    assert no_inbox == with_inbox == sp, "system 主体静态（有无注入轮完全一致——跨会话命中稳定段）"


def test_system_inject_no_merge_no_truncation():
    """5. (2026-08-18 对齐 DSH) 注入转 user——无合并无截断——主体静态不受注入量影响."""
    sp = build_system_prompt()
    # 大量 system 帧（原超限场景）——现在转 user 独立——主体不受影响
    heavy = [_fake_msg("system", f"STATE-{i}: " + "x" * 500) for i in range(30)]
    out = build_history_messages(heavy, sp, max_chars=200000)
    assert out[0]["role"] == "system"
    assert out[0]["content"] == sp, "主体字节静态（不受注入量影响）"
    users = [m for m in out if m["role"] == "user"]
    assert len(users) == 30, "30 个注入帧全部转 user 保留（信息零丢失）"
    assert any("STATE-29" in m["content"] for m in users)


def test_head_keep_fold0_three_action_compaction():
    """任务6.1: head_keep 一次性大裁（fold=0）三动作协作（69715765 事故根因回归）——
    ① 归档中段 + ② cache_compacted_out 视图排除（尾部保留组绝不参与）+ ③ 体积验证：
    压缩后视图真正缩小，且再次 build 同一批不重复归档中段."""
    history = [_fake_msg("user", f"m{i:03d}-" + "x" * 900) for i in range(320)]
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    cache_box: list[Message] = []
    stats_box: list[dict] = []
    built = build_history_messages(
        history,
        "S" * 500,
        max_chars=320000,
        compact_ratio=0.9,
        session_id="s-tri",
        archive_sink=sink,
        head_keep_chars=48000,
        cache_archive_provider="minimax",
        cache_compacted_out=cache_box,
        compact_view_stats=stats_box,
    )
    # ① 归档中段发生（信息零丢失）
    assert archived, "压缩应归档中段"
    # ② 视图排除：归档中段全部被 per-provider 标记（cache_compacted_out 事件链同步）
    assert len(cache_box) == len(archived), "视图排除应标记全部归档中段"
    # 视图排除严格限定中段：最新尾部消息（m319）必须在提交视图（不被排除）
    post = "\n".join(str(m.get("content", "")) for m in built)
    assert "m319" in post, "最新尾部消息必须在提交视图（视图排除不越界到尾部保留组）"
    # ③ 体积验证（6.2）：压缩后视图真正缩小 ≥10%
    assert stats_box and stats_box[0]["drop_pct"] >= 10, f"首轮压缩 drop 应 ≥10%，实际 {stats_box}"
    # 再次 build 同一批：视图排除使已标记中段不进入构建 → 不重复归档（事故修复核心）
    archived2: list[Message] = []

    def sink2(session_id: str, m: Message) -> None:
        archived2.append(m)

    cache_box2: list[Message] = []
    build_history_messages(
        history,
        "S" * 500,
        max_chars=320000,
        compact_ratio=0.9,
        session_id="s-tri",
        archive_sink=sink2,
        head_keep_chars=48000,
        cache_archive_provider="minimax",
        cache_compacted_out=cache_box2,
    )
    assert len(archived2) <= max(2, len(archived) // 5), (
        f"再次 build 不应重复归档中段: 首次 {len(archived)}，再次 {len(archived2)}"
    )


def test_compact_view_stats_warns_when_view_not_shrinking(caplog):
    """任务6.2: 压缩发生但视图几乎没缩小（drop<5%）→ 体积验证 WARN
    （压缩风暴前兆——head 保留 + 归档目标使 post≈pre 时归因可见）."""
    history = [_fake_msg("user", f"m{i:03d}-" + "x" * 850) for i in range(262)]
    stats_box: list[dict] = []
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    with caplog.at_level("WARNING", logger="llm_loop.core.history"):
        build_history_messages(
            history,
            "S" * 500,
            max_chars=320000,
            compact_ratio=0.7,
            session_id="s-tiny",
            archive_sink=sink,
            head_keep_chars=60000,
            cache_archive_provider="minimax",
            compact_view_stats=stats_box,
        )
    assert stats_box, "压缩应填充体积统计"
    assert stats_box[0]["drop_pct"] < 5, f"构造的微降场景 drop 应 <5%，实际 {stats_box[0]}"
    assert any("head_keep 大裁后视图未缩小" in r.message for r in caplog.records), (
        "drop<5% 时应发出 WARN「head_keep 大裁后视图未缩小」"
    )


def test_head_keep_empty_head_groups_degrades_to_full_archive():
    """任务6.3: head_keep 预算过小（首组即超）→ head 保留组为空 → 自动降级
    head_keep=0 全量归档（锚点前移式，前缀重建一轮）——归档仍发生、信息零丢失."""
    history = [_fake_msg("user", "H" * 5000) for _ in range(60)]  # 每条 5K——首组就超 head
    box: list[int] = []
    archived: list[Message] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    build_history_messages(
        history,
        "S" * 500,
        max_chars=100000,
        session_id="s-empty",
        archive_sink=sink,
        head_keep_chars=10,  # 极小 head 预算 → 首组（5K）即超 → head 组为空
        history_anchor=0,
        anchor_out=box,
    )
    assert len(archived) > 0, "head 保留组为空时应全量归档（信息零丢失）"
    assert box and box[0] > 0, "降级 head_keep=0 语义 → 锚点前移（历史真正缩小）"


# ── 任务7（2026-08-25 §5.7）: progressive_fold 缺失 archive_provider 降级防护 ──

def _make_pairs(n: int, body: str = "x" * 1000) -> list[Message]:
    msgs: list[Message] = []
    for i in range(n):
        msgs.append(_fake_msg("user", f"任务{i} " + body))
        msgs.append(_fake_msg("assistant", f"回答{i} " + body))
    return msgs


def test_fold_missing_provider_degrades_with_head_keep_restored():
    """任务7.1: fold>0 + 无 provider + head_keep>0 → 降级.

    验证: 降级事件填充（kind=degraded）、head_keep 恢复调用者原值（不得置 0）、
    提交视图保留头部 3000 chars、中段归档仍发生（一次性大裁）。"""
    msgs = _make_pairs(30)
    archived: list[Message] = []
    degrade_box: list[dict] = []

    def sink(session_id: str, m: Message) -> None:
        archived.append(m)

    out = build_history_messages(
        msgs,
        "system",
        max_chars=20000,
        compact_ratio=0.9,
        session_id="s-deg",
        progressive_fold=3,
        head_keep_chars=3000,
        archive_sink=sink,
        degrade_out=degrade_box,
    )
    assert degrade_box and degrade_box[0]["kind"] == "degraded", "降级事件应填充"
    assert degrade_box[0]["head_keep_chars"] == 3000, "降级必须恢复调用者原值 3000"
    assert "cache_archive_provider" in degrade_box[0]["reason"]
    joined = "\n".join(str(m.get("content", "")) for m in out)
    assert "任务0 " in joined, "降级后 head_keep 生效：头部保留在提交前缀"
    assert archived, "降级后中段归档仍发生（信息零丢失）"


def test_fold_missing_provider_head_keep_zero_uses_default(monkeypatch):
    """任务7.1（§5.7.3-1）: fold>0 + 无 provider + head_keep=0 → 强制默认 2000."""
    import llm_loop.core.history as hist

    monkeypatch.setattr(hist, "_DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE", 2000)
    msgs = _make_pairs(20)
    degrade_box: list[dict] = []
    out = build_history_messages(
        msgs,
        "system",
        max_chars=20000,
        compact_ratio=0.9,
        session_id="s-deg0",
        progressive_fold=3,
        head_keep_chars=0,
        degrade_out=degrade_box,
    )
    assert degrade_box and degrade_box[0]["kind"] == "degraded"
    assert degrade_box[0]["head_keep_chars"] == 2000, "head_keep=0 降级应用默认 2000"
    joined = "\n".join(str(m.get("content", "")) for m in out)
    assert "任务0 " in joined, "默认 head_keep 生效：前缀仍稳定"
