"""单元测试: 架构演进建议（T52 / FR-AUTO-EVOLVE + T56 七态扩展）."""

from __future__ import annotations

import json

from llm_loop.introspection.evolution import EvolutionStore


def test_submit_evolution(tmp_path):
    """submit_evolution 落盘 + id 回执 + 默认状态."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(
        content="建议合并冗余工具",
        evidence="search_records 显示重复",
        impact_scope="tools/registry.py",
    )
    assert s.id.startswith("EVO-")
    assert s.status == "pending_review"
    assert s.requires_human is False
    # 落盘可检索
    assert store.search("冗余")[0]["id"] == s.id


def test_boundary_requires_human(tmp_path):
    """涉安全边界 → requires_human=True（EVOLVE-03）."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="调整灾难性安全策略", impact_scope="safety")
    assert s.requires_human is True
    s2 = store.submit(content="优化记忆检索", impact_scope="memory/")
    assert s2.requires_human is False


def test_review_state_machine(tmp_path):
    """审阅状态机（EVOLVE-05）: pending→accepted/rejected."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="建议 A", impact_scope="x")
    # 审阅 accepted
    target = store.review(s.id, "accepted")
    assert target is not None and target["status"] == "accepted"
    # 非法 decision
    try:
        store.review(s.id, "invalid")
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass
    # 审阅不存在的建议
    assert store.review("no-such", "accepted") is None


def test_executed_via_transition(tmp_path):
    """M16 审计（FR-AUDIT-AI-09）: mark_executed 已移除，executed 语义统一走 transition."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="建议 B", impact_scope="y")
    store.review(s.id, "accepted")
    target = store.transition(s.id, status="executed", executed_at="t")
    assert target is not None and target["status"] == "executed"
    assert target["executed_at"] == "t"


def test_list_filter(tmp_path):
    """list 按状态过滤."""
    store = EvolutionStore(tmp_path / "audit")
    store.submit(content="建议 1", impact_scope="a")
    s2 = store.submit(content="建议 2", impact_scope="b")
    store.review(s2.id, "accepted")
    pending = store.list(status="pending_review")
    accepted = store.list(status="accepted")
    assert len(pending) == 1
    assert len(accepted) == 1


def test_submit_actions_and_eval_id(tmp_path):
    """T56: submit 透传 actions/eval_id."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(
        content="清理缓存",
        impact_scope="recover_state",
        actions=[{"tool_name": "recover_state", "arguments": {"scope": "clear_cache"}}],
        eval_id="EVAL-20260810-1",
    )
    assert s.actions == [{"tool_name": "recover_state", "arguments": {"scope": "clear_cache"}}]
    assert s.eval_id == "EVAL-20260810-1"
    loaded = store.list()[0]
    assert loaded["actions"] == s.actions
    assert loaded["eval_id"] == "EVAL-20260810-1"


def test_seven_state_transition(tmp_path):
    """T56/M17: 状态流转 executed 路径（pending→accepted→executing→executed）+ 时间戳.

    M17 FR-REVIEW-AI-04: verifying 中间态已收敛移除（生产无 verifying 流转）.
    """
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="优化超时参数", impact_scope="timeout_s")
    # 人工审阅 accepted
    store.review(s.id, "accepted")
    assert store.list(status="accepted")[0]["id"] == s.id
    # 自动执行路径中间态（T57 使用 transition）
    store.transition(s.id, status="executing")
    assert store.list(status="executing")[0]["id"] == s.id
    store.transition(s.id, status="executed", executed_at="2026-08-10T01:00:00+00:00")
    done = store.list(status="executed")[0]
    assert done["executed_at"] == "2026-08-10T01:00:00+00:00"
    # 流转完整记录可检索
    assert done["status"] == "executed"


def test_seven_state_failed_path(tmp_path):
    """T56/M17: 状态流转失败路径（executing→rolled_back / failed）."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(s.id, "accepted")
    store.transition(s.id, status="executing")
    store.transition(s.id, status="rolled_back", rolled_back_at="2026-08-10T02:00:00+00:00")
    rb = store.list(status="rolled_back")[0]
    assert rb["rolled_back_at"] == "2026-08-10T02:00:00+00:00"
    # failed 路径
    s2 = store.submit(content="优化记忆", impact_scope="memory/")
    store.review(s2.id, "accepted")
    store.transition(s2.id, status="executing")
    store.transition(s2.id, status="failed")
    assert len(store.list(status="failed")) == 1


def test_legacy_verifying_status_preserved(tmp_path):
    """M17 FR-REVIEW-AI-04: 旧记录 status=verifying 经 list() 如实保留展示（兼容断言，不回退）."""
    import json

    store = EvolutionStore(tmp_path / "audit")
    legacy = {
        "id": "EVO-LEGACY-VERIFY",
        "ts": "2026-08-01T00:00:00+00:00",
        "content": "旧格式含 verifying 中间态",
        "impact_scope": "y",
        "status": "verifying",
        "requires_human": False,
    }
    with (tmp_path / "audit" / "evolution_suggestions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
    entries = store.list()
    legacy_entry = [e for e in entries if e["id"] == "EVO-LEGACY-VERIFY"][0]
    assert legacy_entry["status"] == "verifying"  # 如实保留展示（不转换不回退）


def test_legacy_record_defaults(tmp_path):
    """T56: 旧记录缺省字段补默认（零破坏版本兼容）."""
    store = EvolutionStore(tmp_path / "audit")
    store.submit(content="旧建议", impact_scope="x")
    # 手工写入一条缺省字段的旧格式记录
    legacy = {
        "id": "EVO-LEGACY-1",
        "ts": "2026-08-01T00:00:00+00:00",
        "content": "旧格式",
        "impact_scope": "y",
        "status": "pending_review",
        "requires_human": False,
    }
    with (tmp_path / "audit" / "evolution_suggestions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
    entries = store.list()
    legacy_entry = [e for e in entries if e["id"] == "EVO-LEGACY-1"][0]
    assert legacy_entry["actions"] == []
    assert legacy_entry["eval_id"] == ""
    assert legacy_entry["executed_at"] == ""
    assert legacy_entry["verified_at"] == ""
    assert legacy_entry["rolled_back_at"] == ""


def test_review_accept_returns_pending_execution(tmp_path):
    """T56: review accept 返回待执行建议（供 T57 自动执行触发）."""
    store = EvolutionStore(tmp_path / "audit")
    s = store.submit(content="优化超时参数", impact_scope="timeout_s")
    target = store.review(s.id, "accepted")
    assert target is not None
    assert target["id"] == s.id
    assert target["status"] == "accepted"
    assert target["requires_human"] is False


# ── M49: 双层演进作用域（EVO-20260812-dc911d93 落地）──

def test_scope_defaults_global(tmp_path):
    """不传 scope → global + pending_review（保守默认，向后兼容）."""
    store = EvolutionStore(tmp_path)
    sug = store.submit(content="持久架构变更", impact_scope="loop")
    assert sug.scope == "global"
    assert sug.status == "pending_review"


def test_scope_session_goes_executing(tmp_path):
    """scope=session 直达 executing，不进人工审阅队列."""
    store = EvolutionStore(tmp_path)
    sug = store.submit(content="本轮临时调大 history_budget", impact_scope="运行参数", scope="session")
    assert sug.scope == "session"
    assert sug.status == "executing"
    assert store.list(status="pending_review") == []
    assert len(store.list(status="executing")) == 1


def test_scope_invalid_falls_back_global(tmp_path):
    store = EvolutionStore(tmp_path)
    sug = store.submit(content="x", scope="bogus")
    assert sug.scope == "global"


def test_boundary_forces_global(tmp_path):
    """涉边界内容指定 session 被强制覆盖为 global（安全优先）."""
    store = EvolutionStore(tmp_path)
    sug = store.submit(
        content="修改安全边界",
        impact_scope="安全边界/协议硬约束",
        scope="session",
    )
    assert sug.scope == "global"
    assert sug.status == "pending_review"
    assert sug.requires_human is True


def test_old_records_default_scope_global(tmp_path):
    """旧记录（无 scope 字段）读取时补默认 global，零破坏兼容."""
    import json as _json
    store = EvolutionStore(tmp_path)
    old = {"id": "EVO-old-1", "ts": "2026-01-01T00:00:00", "content": "旧建议",
           "status": "pending_review", "priority": "medium"}
    with store._path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(old, ensure_ascii=False) + "\n")
    items = store.list()
    assert items[0]["scope"] == "global"
