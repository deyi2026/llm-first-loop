"""单元测试: 演进自动执行资格判定与执行引擎（T55/T57/T69 / EXEC-01/02/03/06/07/08）.

M16 审计（FR-AUDIT-AI-01/15）: 验证/回滚移交 AI（verify_result=unverified + note 引导，
不伪装修验通过/伪回滚）；白名单空语义修正（空元组 = 不自动执行）。
"""

from __future__ import annotations

from llm_loop.introspection.evolution import EvolutionStore, EvolutionSuggestion
from llm_loop.introspection.evolution_exec import (
    AutoExecPlan,
    EvolutionExecutor,
    can_auto_exec,
    exec_level,
    in_exec_whitelist,
)


def _sug(
    content: str,
    impact_scope: str = "",
    *,
    requires_human: bool = False,
) -> EvolutionSuggestion:
    return EvolutionSuggestion(
        id="EVO-test-1",
        ts="2026-08-10T00:00:00+00:00",
        content=content,
        impact_scope=impact_scope,
        requires_human=requires_human,
    )


def test_level0_deny_only_suggestion():
    """级别 0（仅建议）→ 拒绝 + '仅建议级'（EXEC-01）."""
    ok, reason = can_auto_exec(_sug("优化超时参数", "timeout_s"), level=0)
    assert ok is False
    assert reason == "仅建议级"


def test_boundary_deny_even_level2():
    """涉边界（safety）→ 拒绝 + 边界原因（EXEC-03，级别 2 也不放行）."""
    ok, reason = can_auto_exec(_sug("调整灾难性安全策略", "safety", requires_human=True), level=2)
    assert ok is False
    assert reason == "涉边界需人工执行"


def test_boundary_deny_via_marker():
    """requires_human=False 但内容命中边界标记 → 独立重查仍拒绝（不因 accepted 放宽）."""
    ok, reason = can_auto_exec(_sug("修改数据结构 schema", "evolution.py"), level=2)
    assert ok is False
    assert reason == "涉边界需人工执行"


def test_level2_allow_non_boundary():
    """级别 2 不涉边界 → 放行（EXEC-01）."""
    ok, reason = can_auto_exec(_sug("优化超时参数", "timeout_s"), level=2)
    assert ok is True
    assert reason == ""


def test_level1_whitelist_hit():
    """级别 1 白名单命中 → 放行（EXEC-08）."""
    ok, reason = can_auto_exec(
        _sug("清理缓存", "recover_state"), level=1, whitelist=("recover_state",)
    )
    assert ok is True
    assert reason == ""


def test_level1_whitelist_miss():
    """级别 1 白名单未命中 → 拒绝 + '不在执行白名单'（EXEC-08）."""
    ok, reason = can_auto_exec(
        _sug("清理缓存", "recover_state"), level=1, whitelist=("clear_cache",)
    )
    assert ok is False
    assert reason == "不在执行白名单"


def test_level1_empty_whitelist_deny():
    """级别 1 + 空白名单 → 拒绝 + '未配置白名单'（M16 审计 FR-AUDIT-AI-15 方案 A）."""
    ok, reason = can_auto_exec(_sug("清理缓存", "recover_state"), level=1)
    assert ok is False
    assert "未配置白名单" in reason


def test_level2_ignores_whitelist():
    """级别 2 白名单不限制（不涉边界皆可，EXEC-08）."""
    ok, _ = can_auto_exec(_sug("优化超时参数", "timeout_s"), level=2, whitelist=("recover_state",))
    assert ok is True


def test_empty_whitelist_denied():
    """空元组白名单 = 无白名单授权 → 不自动执行（M16 审计 FR-AUDIT-AI-15）."""
    assert in_exec_whitelist(_sug("任意", "x"), ()) is False
    assert in_exec_whitelist(_sug("清理缓存", "recover_state"), ("recover_state",)) is True


def test_exec_level_parses_env(monkeypatch):
    """exec_level() 读取环境变量（0/1/2/非法回退 0）."""
    for raw, expected in [("0", 0), ("1", 1), ("2", 2), ("true", 1), ("", 0), ("abc", 0)]:
        monkeypatch.setenv("EVOLVE_LOCAL_EXEC", raw)
        assert exec_level() == expected


# ── AutoExecPlan（M16 审计 FR-AUDIT-AI-01）──


def test_plan_boundary():
    """AutoExecPlan: 涉边界 → allowed=False + boundary=True（DFX-SEC-05）."""
    executor = EvolutionExecutor(exec_level=2)
    plan = executor.plan(_sug("调整安全策略", "safety"))
    assert isinstance(plan, AutoExecPlan)
    assert plan.allowed is False
    assert plan.boundary is True
    assert plan.reason == "涉边界需人工执行"


def test_plan_allowed_level2():
    """AutoExecPlan: 级别 2 不涉边界 → allowed=True + boundary=False."""
    executor = EvolutionExecutor(exec_level=2)
    plan = executor.plan(_sug("优化超时参数", "timeout_s"))
    assert plan.allowed is True
    assert plan.boundary is False
    assert plan.reason == ""


# ── EvolutionExecutor 执行引擎（T69 移交语义）──


def test_maybe_auto_execute_level0_returns_none(tmp_path):
    """级别 0 → maybe_auto_execute 返回 None（accepted 保持，等待人工执行）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=0, store=store, audit_dir=tmp_path / "audit")
    outcome = executor.maybe_auto_execute(sug)
    assert outcome is None
    assert store.list(status="accepted")[0]["id"] == sug.id  # 状态保持 accepted
    log = (tmp_path / "audit" / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "仅建议级" in log


def test_maybe_auto_execute_boundary_returns_none(tmp_path):
    """涉边界 → maybe_auto_execute 返回 None + 边界原因（EXEC-03，级别 2 也不放行）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="调整安全策略", impact_scope="safety")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    outcome = executor.maybe_auto_execute(sug)
    assert outcome is None
    log = (tmp_path / "audit" / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "涉边界需人工执行" in log


def test_maybe_auto_execute_allowed_sets_executing(tmp_path):
    """级别 2 允许 → 状态 accepted→executing + verify_result=unverified + note 验证引导（不伪装修验通过）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    outcome = executor.maybe_auto_execute(sug)
    assert outcome is not None
    assert outcome.status == "executing"  # 移交后程序只推进到 executing，执行/验证交 AI
    assert outcome.executor == "ai"
    assert outcome.verify_result == "unverified"  # 程序不做硬判定（FR-AUDIT-AI-01）
    assert outcome.rollback_result == "none"
    assert "验证" in outcome.note or "architecture_status" in outcome.note  # 验证引导
    assert store.list(status="executing")[0]["id"] == sug.id
    log = (tmp_path / "audit" / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "unverified" in log


def test_complete_marks_executed(tmp_path):
    """complete(): AI 执行完成登记 → executing→executed + verify_result=ai_reported（AI 汇报）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    executor.maybe_auto_execute(sug)
    outcome = executor.complete(sug.id, note="已执行并对比架构状态，验证通过")
    assert outcome.status == "executed"
    assert outcome.executor == "ai"
    assert outcome.verify_result == "ai_reported"  # AI 自主验证后汇报
    assert store.list(status="executed")[0]["id"] == sug.id
    log = (tmp_path / "audit" / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "ai_reported" in log


def test_complete_without_note_unverified(tmp_path):
    """complete() 无 note → verify_result=unverified（如实标注，AI 未汇报验证）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    executor.maybe_auto_execute(sug)
    outcome = executor.complete(sug.id)
    assert outcome.status == "executed"
    assert outcome.verify_result == "unverified"


def test_manual_complete_marks_executed(tmp_path):
    """manual_complete: 人工执行通道 → executed + executor=human."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="调整安全策略", impact_scope="safety")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    outcome = executor.manual_complete(sug.id, "人工已完成边界调整")
    assert outcome.executor == "human"
    assert outcome.status == "executed"
    assert "人工已完成" in outcome.note
    assert store.list(status="executed")[0]["id"] == sug.id
    log = (tmp_path / "audit" / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert '"executor": "human"' in log


def test_audit_fail_open(tmp_path, monkeypatch):
    """审计落盘失败 → fail-open（不阻塞执行结果，DFX-REL-06）."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")

    from pathlib import Path

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _broken)
    try:
        executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
        outcome = executor.maybe_auto_execute(sug)
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    assert outcome is not None
    assert outcome.status == "executing"


def test_search_records_kind_evolution_exec(tmp_path):
    """T60: search_records kind=evolution_exec 命中执行审计（EXEC-06 可检索）."""
    from llm_loop.introspection.search import RecordSearcher

    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
    executor.maybe_auto_execute(sug)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    hits = searcher.search(kind="evolution_exec", query=sug.id)
    assert len(hits) >= 1
    assert hits[0]["kind"] == "evolution_exec"
    assert hits[0]["summary"] != ""
    try:
        searcher.search(kind="nope")
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass
