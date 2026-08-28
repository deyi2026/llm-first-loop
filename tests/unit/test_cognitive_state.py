"""单元测试: 认知运行时 state 模块（tasks 1.8）.

覆盖:
1. SemanticTaskState / CheckpointPointer 必填非空校验（spec 6.1-1 / 5.1.3-2）
2. rebuild_state 从 GoalStore 派生 + 空 what 回退（spec 5.1.3-2）
3. _is_durable Durable Admission 门槛（spec 5.1.1-2）
4. SemanticStateStore 原子写/读、Ephemeral 不落盘（spec 5.1.1-1 / 4.2-2）
5. SemanticResetController 受控清空 + 快照回滚 + 确认门槛（spec 4.2-2 / 4.3-2）
6. promote_ephemeral v0.1 字段预留（spec 5.1.3-3）
7. ConfirmedFact 序列化 roundtrip + provenance 证据引用对齐（spec 6.1-3b）
"""

from pathlib import Path

import pytest

from llm_loop.cognitive.state import StateEnvelope, StateIdentity
from llm_loop.cognitive.state import (
    CheckpointPointer,
    ConfirmedFact,
    ConfirmedFactFreshness,
    SemanticResetController,
    SemanticStateStore,
    SemanticStateVersion,
    SemanticTaskState,
    _is_durable,
    promote_ephemeral,
    rebuild_state,
)


def _valid_evidence_ref() -> str:
    return "evidence://v1/" + ("a" * 64)


# ── 领域对象校验 ──


def test_objective_required():
    with pytest.raises(ValueError):
        SemanticTaskState(objective="")


def test_checkpoint_what_required():
    with pytest.raises(ValueError):
        CheckpointPointer(what="  ")


# ── rebuild_state 派生 ──


def test_rebuild_state_from_goal():
    goal = {
        "id": "GOAL-1",
        "status": "active",
        "objective": "深度审计项目",
        "checkpoints": [
            {"what": "完成审计框架", "evidence": "e", "path": "p", "next": "分析缓存"},
            {"what": "定位缓存瓶颈", "evidence": "e2", "path": "p2", "next": "落地修复"},
        ],
    }
    state = rebuild_state(goal)
    assert state is not None
    assert state.objective == "深度审计项目"
    assert state.checkpoint is not None
    assert state.checkpoint.what == "定位缓存瓶颈"  # 最近 checkpoint
    assert state.checkpoint.next == "落地修复"
    assert state.version is SemanticStateVersion.V0_1
    assert state.hard_constraints == []
    assert state.confirmed_facts == []


def test_rebuild_state_empty_what_fallback():
    goal = {
        "objective": "任务",
        "checkpoints": [
            {"what": "有效里程碑", "next": "N1"},
            {"what": "", "next": "N2"},  # 历史空 what → 回退
        ],
    }
    state = rebuild_state(goal)
    assert state is not None
    assert state.checkpoint.what == "有效里程碑"
    assert state.checkpoint.next == "N1"


def test_rebuild_state_none_goal():
    assert rebuild_state(None) is None
    assert rebuild_state({"objective": "", "status": "active"}) is None


# ── Durable Admission 门槛 ──


def test_is_durable_any_signal():
    assert _is_durable() is False
    assert _is_durable(survives_boundary=True) is True
    assert _is_durable(is_hard_constraint=True) is True
    assert _is_durable(is_decision_basis=True) is True
    assert _is_durable(high_recover_cost=True) is True
    assert _is_durable(stable_reusable_fact=True) is True


# ── Store 持久化（Durable 保留 / Ephemeral 丢弃）──


def test_store_roundtrip_durable_only(tmp_path: Path):
    store = SemanticStateStore(str(tmp_path))
    assert store.load("s1test00") is None  # 无文件 → None（CR-R1 新签名：按会话分片）

    state = SemanticTaskState(
        objective="任务目标",
        checkpoint=CheckpointPointer(what="里程碑", next="下一步"),
        confirmed_facts=[
            ConfirmedFact(claim="事实A", provenance=__import__(
                "llm_loop.memory.evidence", fromlist=["EvidenceRef"]
            ).EvidenceRef(_valid_evidence_ref()), freshness=ConfirmedFactFreshness.HISTORICAL)
        ],
    )
    state.ephemeral.hypotheses.append("本轮临时假设")  # Ephemeral 不应落盘

    env = StateEnvelope(
        identity=StateIdentity(
            session_id="s1test00", goal_id="g1", goal_updated_at="t1", checkpoint_ts="c1"
        ),
        state=state,
    )
    store.save("s1test00", env)
    assert store.path_for("s1test00").exists()

    loaded_env = store.load("s1test00")
    assert isinstance(loaded_env, StateEnvelope)
    loaded = loaded_env.state
    assert loaded is not None
    assert loaded.objective == "任务目标"
    assert loaded.checkpoint is not None
    assert loaded.checkpoint.what == "里程碑"
    assert loaded.checkpoint.next == "下一步"
    assert loaded.ephemeral.hypotheses == []  # Ephemeral 丢弃（spec 5.1.1-1）
    assert len(loaded.confirmed_facts) == 1
    fact = loaded.confirmed_facts[0]
    assert fact.claim == "事实A"
    assert fact.freshness is ConfirmedFactFreshness.HISTORICAL
    assert fact.provenance is not None
    assert fact.provenance.ref == _valid_evidence_ref()


def test_store_load_corrupt_returns_none(tmp_path: Path):
    store = SemanticStateStore(str(tmp_path))
    store._dir.mkdir(parents=True, exist_ok=True)
    store.path_for("s1test00").write_text("{ not valid json ]", encoding="utf-8")
    assert store.load("s1test00") is None  # 损坏 → None，由 rebuild_state 派生（fail-open）


def test_store_atomic_visible_only_new(tmp_path: Path):
    store = SemanticStateStore(str(tmp_path))
    def _env(obj: str) -> StateEnvelope:
        return StateEnvelope(
            identity=StateIdentity(
                session_id="s1test00", goal_id="g1", goal_updated_at="t1", checkpoint_ts="c1"
            ),
            state=SemanticTaskState(objective=obj),
        )

    store.save("s1test00", _env("v1"))
    loaded_env = store.load("s1test00")
    assert loaded_env is not None and loaded_env.state is not None
    assert loaded_env.state.objective == "v1"
    # 覆盖写：reader 应见最新
    store.save("s1test00", _env("v2"))
    loaded_env2 = store.load("s1test00")
    assert loaded_env2 is not None and loaded_env2.state is not None
    assert loaded_env2.state.objective == "v2"


# ── 受控重置 ──


def test_reset_keeps_pointer_clears_rest():
    ctl = SemanticResetController()
    state = SemanticTaskState(
        objective="目标",
        checkpoint=CheckpointPointer(what="里程碑"),
        hard_constraints=["硬约束A"],
    )
    state.ephemeral.hypotheses.append("待验证临时假设：模块间存在隐藏耦合需要实验确认")
    result = ctl.reset(state)
    assert result.ok is True
    assert result.metric_before > result.metric_after
    assert result.estimated_token_delta > 0
    assert result.first_miss_expected is True
    # spec 4.2-1/4.3-1: 不因 reset 丢失硬约束；Ephemeral 假设清空
    assert result.cleared is not None
    assert result.cleared.hard_constraints == ["硬约束A"]
    assert result.cleared.ephemeral.hypotheses == []


def test_reset_require_confirmation():
    ctl = SemanticResetController()
    state = SemanticTaskState(objective="目标")
    result = ctl.reset(state, require_confirmation=True)
    assert result.failed is True
    assert result.need_confirmation is True
    assert result.metric_before == result.metric_after  # enforce 语境未执行清空


# ── Ephemeral 假设晋级（v0.1 字段预留）──


def test_promote_ephemeral_identifies_durable():
    state = SemanticTaskState(objective="目标")
    state.ephemeral.hypotheses.append("假设A")
    durable = promote_ephemeral(state)
    assert durable == ["假设A"]


# ── ConfirmedFact 证据引用对齐 ──


def test_confirmed_fact_provenance_invalid_ref_eq_none():
    from llm_loop.memory.evidence import EvidenceRef

    fact = ConfirmedFact.from_dict({"claim": "c", "provenance": "not-a-ref"})
    assert fact.provenance is None
    assert isinstance(EvidenceRef(_valid_evidence_ref()), EvidenceRef)


def test_semantic_state_version_parse():
    assert SemanticStateVersion.parse("v0.2") is SemanticStateVersion.V0_2
    assert SemanticStateVersion.parse("junk") is SemanticStateVersion.V0_1