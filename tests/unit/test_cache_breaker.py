"""P0 压缩风暴熔断 + P1 遥测内容/传输分层（2026-08-25 规格）单测.

覆盖: 风暴检测→进入 breaker / 冻结期禁压缩 / context_pressure 管控 / 逃生轮 /
退出 hysteresis / 审计事件 / history freeze_compression / 遥测行剥离 / 规则 F 协调。
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress

import pytest

from llm_loop.cache_guard.guard import PromptGuard
from llm_loop.core.cache_health import CacheHealthMonitor, strip_cache_telemetry_lines
from llm_loop.core.history import build_history_messages, is_cache_compacted_for


@pytest.fixture
def audit_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    yield path
    with suppress(OSError):
        os.unlink(path)


def _read_audit(path: str) -> list[dict]:
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _mon(**kw) -> CacheHealthMonitor:
    m = CacheHealthMonitor()
    for k, v in kw.items():
        setattr(m, f"_{k}", v)
    return m


def _storm_round(m, sid: str, chars: int = 300_000, budget: int = 300_000,
                 model: str = "deepseek/deepseek-v4-flash") -> None:
    """一轮风暴 build 通知 + 低命中回馈（窗口共信号）。chars>budget×0.9 保持超限."""
    m.note_build_result(compacted=True, anchor_moved=True, chars_total=chars,
                        budget=budget, session_id=sid, model_ref=model)
    m.record(20000, 2000, model_ref=model, session_id=sid)  # 10% 命中 → 共信号满足


# ── P0 breaker: 风暴检测与进入/退出 ──

def test_storm_detection_enters_breaker(audit_path):
    """连续 (compacted 且 anchor_moved 且 仍超压缩线) + 低命中 → 进入 breaker + 审计."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(3):
        _storm_round(m, "s1")
    assert m.breaker_active_for("s1") is True
    assert m.breaker_freeze_compression("s1") is True
    rows = _read_audit(audit_path)
    assert rows and rows[0]["event"] == "breaker_enter"
    assert rows[0]["storm_count"] == 3 and rows[0]["session_id"] == "s1"


def test_high_hit_window_does_not_trigger(audit_path):
    """结构信号满足但命中率健康（渐进折叠场景）→ 不触发 breaker."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(5):
        m.note_build_result(compacted=True, anchor_moved=True, chars_total=300_000,
                            budget=300_000, session_id="s1")
        m.record(20000, 19500, session_id="s1")  # 97.5% 命中 → 共信号不满足
    assert m.breaker_active_for("s1") is False


def test_clean_round_resets_storm_streak(audit_path):
    """干净轮（无压缩且锚点未动）清零风暴计数——不误触发."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(2):
        _storm_round(m, "s1")
    m.note_build_result(compacted=False, anchor_moved=False, chars_total=100_000,
                        budget=300_000, session_id="s1")
    for _ in range(2):
        _storm_round(m, "s1")
    assert m.breaker_active_for("s1") is False  # 中途干净轮清零 → 未达阈值


def test_head_keep_frozen_anchor_storm_still_triggers(audit_path):
    """head_keep 模式（压缩但锚点未动）→ 仍计数触发（2026-08-25 冒烟修正:

    保留窗口每轮前移同样风暴——锚点移动不是必要条件）。"""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(3):
        m.note_build_result(compacted=True, anchor_moved=False, chars_total=300_000,
                            budget=300_000, session_id="s1")
        m.record(20000, 2000, session_id="s1")  # 低命中共信号
    assert m.breaker_active_for("s1") is True
    rows = _read_audit(audit_path)
    assert rows and rows[0]["event"] == "breaker_enter"


def test_under_compression_line_does_not_count(audit_path):
    """压缩后已回落到压缩线以下（单次压缩成功）→ 不计入风暴."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(5):
        m.note_build_result(compacted=True, anchor_moved=True, chars_total=200_000,
                            budget=300_000, session_id="s1")  # 200K ≤ 270K（×0.9）
        m.record(20000, 2000, session_id="s1")
    assert m.breaker_active_for("s1") is False


def test_breaker_per_session_isolation(audit_path):
    """风暴会话触发 breaker 不影响健康会话."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3)
    for _ in range(3):
        _storm_round(m, "storm")
        m.note_build_result(compacted=False, anchor_moved=False, chars_total=50_000,
                            budget=300_000, session_id="healthy")
    assert m.breaker_active_for("storm") is True
    assert m.breaker_active_for("healthy") is False


def test_exit_hysteresis_requires_cooldown_watermark_and_stability(audit_path):
    """退出 = cooldown 轮数下限 + 水位 + 连续稳定（仅时间不够）."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3,
                           breaker_cooldown_rounds=5, breaker_exit_stable_runs=2,
                           breaker_exit_chars_ratio=0.8)
    for _ in range(3):
        _storm_round(m, "s1")
    assert m.breaker_active_for("s1") is True
    # cooldown 未满: 即使干净也不退出
    for _ in range(2):
        m.note_build_result(compacted=False, anchor_moved=False, chars_total=100_000,
                            budget=300_000, session_id="s1")
    assert m.breaker_active_for("s1") is True
    # 水位未达标（chars 200_000 > 300_000×0.8）: 不退出
    m.note_build_result(compacted=False, anchor_moved=False, chars_total=200_000,
                        budget=300_000, session_id="s1")
    assert m.breaker_active_for("s1") is True
    # cooldown 满 + 水位达标 + 连续稳定 → 退出
    for _ in range(3):
        m.note_build_result(compacted=False, anchor_moved=False, chars_total=100_000,
                            budget=300_000, session_id="s1")
    assert m.breaker_active_for("s1") is False
    events = [r["event"] for r in _read_audit(audit_path)]
    assert "breaker_exit" in events
    assert _read_audit(audit_path)[-1]["reason"] == "recovered"


def test_context_pressure_and_escape(audit_path):
    """冻结期超安全水位 → context_pressure；连续达上限 → 武装逃生轮（放行一次压缩）."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3,
                           breaker_pressure_escape_max=2, breaker_pressure_ratio=0.95)
    for _ in range(3):
        _storm_round(m, "s1")
    assert m.context_pressure_decision("s1", 290_000, 300_000) is True   # 96.7% > 95%
    assert m.context_pressure_decision("s1", 280_000, 300_000) is False  # ≤95% 放行提交
    m.note_context_pressure("s1", reason="over_safety_cap", chars_total=290_000,
                            budget=300_000)
    m.note_context_pressure("s1", reason="over_safety_cap", chars_total=290_000,
                            budget=300_000)
    assert m.breaker_freeze_compression("s1") is False  # 逃生轮: 允许一次受控压缩
    assert m.context_pressure_decision("s1", 290_000, 300_000) is False
    events = [r["event"] for r in _read_audit(audit_path)]
    assert events.count("context_pressure") == 2 and "escape_armed" in events


def test_escape_consumed_on_next_build(audit_path):
    """逃生轮在下一轮 build 消费后恢复冻结."""
    m = CacheHealthMonitor(breaker_audit_file=audit_path, breaker_trigger_runs=3,
                           breaker_pressure_escape_max=1)
    for _ in range(3):
        _storm_round(m, "s1")
    m.note_context_pressure("s1", reason="over_safety_cap", chars_total=290_000, budget=300_000)
    assert m.breaker_freeze_compression("s1") is False
    # 逃生轮 build（允许压缩发生）→ 消费逃生
    m.note_build_result(compacted=True, anchor_moved=True, chars_total=300_000,
                        budget=300_000, session_id="s1")
    assert m.breaker_freeze_compression("s1") is True
    assert m.context_pressure_decision("s1", 290_000, 300_000) is True


# ── P0: history freeze_compression ──

def _big_history(n: int = 40, chars: int = 2000) -> list:
    from llm_loop.core.message import Message, MessageSource

    msgs = []
    for i in range(n):
        msgs.append(Message(role="user", content=f"任务 {i} " + "x" * chars,
                            source=MessageSource.USER))
        msgs.append(Message(role="assistant", content=f"回答 {i} " + "y" * chars,
                            source=MessageSource.USER))
    return msgs


def test_freeze_compression_skips_archive():
    """冻结期超预算 → 正常序列化路径（不归档、无压缩标注、锚点不推进）."""
    msgs = _big_history()
    sys_p = "system prompt"
    budget = 5000  # 远小于历史 → 正常应触发压缩
    built = build_history_messages(msgs, sys_p, max_chars=budget, compact_ratio=0.9,
                                   session_id="s1")
    assert len(built) < len(msgs)  # 压缩路径只保留尾部少量消息
    assert any("上下文压缩" in str(m.get("content", "")) for m in built)
    compacted_box: list[bool] = []
    anchor_box: list[int] = []
    built2 = build_history_messages(msgs, sys_p, max_chars=budget, compact_ratio=0.9,
                                    session_id="s1", freeze_compression=True,
                                    compacted_out=compacted_box, anchor_out=anchor_box)
    assert compacted_box and compacted_box[0] is False  # 未进入归档路径
    assert anchor_box == []  # 锚点不推进
    # 冻结序列化保留全部消息（含 [上下文压缩] 标注缺失）
    assert len(built2) == len(msgs) + 1  # +1 = system


# ── P1: 遥测行剥离 ──

def test_strip_telemetry_lines():
    forge = (
        "回答正文\n\n"
        "⚡ 缓存命中率 93.6%（近 1 轮，724,096/773,371 tokens；"
        "本模型(deepseek-v4-flash)累计 1 轮 93.6% 724,096/773,371 tokens）\n\n"
        "继续"
    )
    out = strip_cache_telemetry_lines(forge)
    assert "缓存命中率" not in out
    assert "回答正文" in out and "继续" in out
    # 纯正文零改动
    plain = "普通回答"
    assert strip_cache_telemetry_lines(plain) == plain
    # 多行伪造
    multi = "a\n⚡ 缓存命中率 1%（近 1 轮，1/100 tokens）\n⚡ 缓存命中率 2%（近 2 轮，2/200 tokens）\nb"
    out2 = strip_cache_telemetry_lines(multi)
    assert "缓存命中率" not in out2 and out2 == "a\nb"
    # 无 tokens 结尾特征的行不剥离（防误伤正文）
    keep = "提到 ⚡ 缓存命中率 概念的正文"
    assert strip_cache_telemetry_lines(keep) == keep


# ── P0: cache_guard 规则 F 协调 ──

def test_guard_rule_g_provider_miss_warns_with_or_without_breaker(tmp_path):
    """无结构漂移证据的 provider 低命中始终 WARN；breaker 不应依赖旧的误 BLOCK。"""
    g = PromptGuard(audit_file=str(tmp_path / "guard2.jsonl"))
    # 制造低命中窗口（3 次 BLOCK 阈值内的低命中记录）
    for _ in range(4):
        g.record_result("sg1", tokens_in=20000, tokens_hit=2000, provider="deepseek")
    d = g.check(session_id="sg1", system_text="sys", messages=[{"role": "user", "content": "hi"}],
                breaker_active=False)
    assert d.verdict == "WARN" and d.rule == "low_hit_rate_provider"
    d2 = g.check(session_id="sg1", system_text="sys", messages=[{"role": "user", "content": "hi"}],
                 breaker_active=True)
    assert d2.verdict == "WARN" and d2.rule == "low_hit_rate_provider"


def test_guard_rule_f_downgraded_when_breaker_active(tmp_path):
    """breaker 冻结期规则 F BLOCK 降级 WARN（防双拦死锁）."""
    g = PromptGuard(audit_file=str(tmp_path / "guard.jsonl"))
    big = [{"role": "user", "content": "x" * 1000}]  # 1000 chars
    d = g.check(session_id="s1", system_text="sys", messages=big,
                history_budget=1000, breaker_active=False)
    assert d.verdict == "BLOCK" and d.rule == "submit_ratio"
    d2 = g.check(session_id="s2", system_text="sys", messages=big,
                 history_budget=1000, breaker_active=True)
    assert d2.verdict == "WARN" and d2.rule == "submit_ratio_breaker"


def test_guard_rule_f_fail_safe_when_breaker_active_missing(tmp_path):
    """任务3（§5.9）: breaker_active=None（传递丢失——如 MCP 通道未传该标志）→ 规则 F
    超限降级 WARN（submit_ratio_breaker_missing）——无法确认冻结期状态时保守放行，
    防"禁压缩 + 禁提交"双拦死锁（宁可交前置 context_pressure 管控）."""
    g = PromptGuard(audit_file=str(tmp_path / "guard3.jsonl"))
    big = [{"role": "user", "content": "x" * 1000}]  # 1000 chars > 95% × 1000
    # 未传 breaker_active（默认 None = 传递丢失）
    d = g.check(session_id="s-missing", system_text="sys", messages=big,
                history_budget=1000)
    assert d.verdict == "WARN" and d.rule == "submit_ratio_breaker_missing"
    assert "传递丢失" in d.detail and "双拦死锁" in d.detail
    # 显式 None 同语义
    d2 = g.check(session_id="s-missing2", system_text="sys", messages=big,
                 history_budget=1000, breaker_active=None)
    assert d2.verdict == "WARN" and d2.rule == "submit_ratio_breaker_missing"


def test_fold_without_provider_degrades_to_head_keep():
    """任务7（§5.7）: progressive_fold>0 但无 cache_archive_provider → 降级.

    降级后: progressive_fold 强制 0（回一次性大裁）、head_keep_chars 恢复调用者
    原值（不得错误置 0）、degrade_out 填充 degraded 事件、提交视图保留头部。
    """
    from llm_loop.core.message import Message, MessageSource

    msgs = []
    for i in range(30):
        msgs.append(Message(role="user", content=f"任务{i} " + "x" * 1000, source=MessageSource.USER))
        msgs.append(Message(role="assistant", content=f"回答{i} " + "y" * 1000, source=MessageSource.USER))
    sys_p = "system"
    budget = 20000
    archived1: list[Message] = []
    degrade_box: list[dict] = []
    out1 = build_history_messages(
        msgs, sys_p, max_chars=budget, compact_ratio=0.9, session_id="s1",
        progressive_fold=3, head_keep_chars=3000,
        archive_sink=lambda sid, m: archived1.append(m),
        degrade_out=degrade_box,
    )
    # 降级事件填充（kind="degraded"，供调用方写 metadata.cache_health）
    assert degrade_box and degrade_box[0]["kind"] == "degraded"
    assert degrade_box[0]["head_keep_chars"] == 3000, "降级必须恢复调用者原值，不得置 0"
    assert "cache_archive_provider" in degrade_box[0]["reason"]
    # 降级后 head_keep 生效：提交视图保留头部（前缀稳定），中段归档
    joined = "\n".join(str(m.get("content", "")) for m in out1)
    assert "任务0 " in joined and "回答0 " in joined, "降级后 head_keep 生效：头部保留在提交前缀"
    assert archived1, "降级后仍归档中段（一次性大裁）"


def test_fold_without_provider_head_keep_zero_uses_default():
    """任务7（§5.7.3-1）: fold>0 + 无 provider + head_keep=0 → 强制默认 2000."""
    from llm_loop.core.message import Message, MessageSource

    msgs = []
    for i in range(20):
        msgs.append(Message(role="user", content=f"任务{i} " + "x" * 1000, source=MessageSource.USER))
        msgs.append(Message(role="assistant", content=f"回答{i} " + "y" * 1000, source=MessageSource.USER))
    sys_p = "system"
    budget = 20000
    degrade_box: list[dict] = []
    build_history_messages(
        msgs, sys_p, max_chars=budget, compact_ratio=0.9, session_id="s1",
        progressive_fold=3, head_keep_chars=0,
        degrade_out=degrade_box,
    )
    assert degrade_box and degrade_box[0]["kind"] == "degraded"
    assert degrade_box[0]["head_keep_chars"] == 2000, "head_keep=0 降级应用默认 2000"


def test_provider_mid_fold_keeps_head_and_does_not_rearchive(tmp_path):
    """provider级中段折叠: 固定头部保留，已折中段后续过滤，且不同provider隔离。"""
    from llm_loop.core.message import Message, MessageSource

    msgs: list[Message] = []
    for i in range(30):
        msgs.append(
            Message(role="user", content=f"任务{i} " + "x" * 1000, source=MessageSource.USER)
        )
        msgs.append(
            Message(
                role="assistant",
                content=f"回答{i} " + "y" * 1000,
                source=MessageSource.USER,
            )
        )
    sys_p = "system"
    budget = 20_000
    archived1: list[Message] = []
    anchor1: list[int] = []
    out1 = build_history_messages(
        msgs,
        sys_p,
        max_chars=budget,
        compact_ratio=0.9,
        session_id="s1",
        progressive_fold=3,
        head_keep_chars=3_000,
        archive_sink=lambda sid, m: archived1.append(m),
        anchor_out=anchor1,
        cache_archive_provider="deepseek",
    )

    joined1 = "\n".join(str(m.get("content", "")) for m in out1)
    assert "任务0 " in joined1, "固定head必须留在压缩轮提交前缀"
    assert anchor1 == [0], "中段折叠靠provider标记去重，不应为去重而移动head锚点"
    assert archived1
    assert all(is_cache_compacted_for(m, "deepseek") for m in archived1)
    assert not is_cache_compacted_for(msgs[0], "deepseek"), "最老固定head不应被中段标记"

    first_ids = {id(m) for m in archived1}
    marked_sample = archived1[0].content
    for i in range(30, 40):
        msgs.append(
            Message(role="user", content=f"任务{i} " + "n" * 1000, source=MessageSource.USER)
        )
        msgs.append(
            Message(
                role="assistant",
                content=f"回答{i} " + "m" * 1000,
                source=MessageSource.USER,
            )
        )

    archived2: list[Message] = []
    out2 = build_history_messages(
        msgs,
        sys_p,
        max_chars=budget,
        compact_ratio=0.9,
        session_id="s1",
        progressive_fold=3,
        head_keep_chars=3_000,
        archive_sink=lambda sid, m: archived2.append(m),
        cache_archive_provider="deepseek",
    )
    assert first_ids.isdisjoint({id(m) for m in archived2}), "已折中段不得重复归档"
    joined2 = "\n".join(str(m.get("content", "")) for m in out2)
    assert "任务0 " in joined2
    assert marked_sample not in joined2, "deepseek后续提交必须过滤已折中段"

    other = build_history_messages(
        msgs,
        sys_p,
        max_chars=1_000_000,
        cache_archive_provider="minimax",
    )
    other_joined = "\n".join(str(m.get("content", "")) for m in other)
    assert marked_sample in other_joined, "provider级折叠状态不得污染另一provider"


def test_guard_g_compression_round_has_specific_warn(tmp_path):
    """压缩轮保留专用 WARN；普通 provider 低命中也只 WARN，二者归因文字不同。"""
    g = PromptGuard(audit_file=str(tmp_path / "guard3.jsonl"))
    for _ in range(4):
        g.record_result("sg2", tokens_in=20000, tokens_hit=2000, provider="deepseek")
    d = g.check(session_id="sg2", system_text="sys",
                messages=[{"role": "user", "content": "hi"}],
                compress_count_this_run=1)
    assert d.verdict == "WARN" and d.rule == "low_hit_rate_compressing"
    # 非压缩轮同命中：无结构漂移证据，仅 provider-side WARN
    d2 = g.check(session_id="sg2", system_text="sys",
                 messages=[{"role": "user", "content": "hi"}])
    assert d2.verdict == "WARN" and d2.rule == "low_hit_rate_provider"
