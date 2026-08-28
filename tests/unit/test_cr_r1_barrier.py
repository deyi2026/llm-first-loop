"""CR-R1 任务组 3 集成单测（tasks 3.3）：Read Barrier + packet header 行为。

不变量映射：
- ② checkpoint B 后下一轮注入含 B（barrier 不一致→rebuild 生效）
- ④ 100% 决策轮 header（enforce 且 barrier 通过 → 尾部聚合条含 [当前决策]/[下一步]）
- ⑤ 零注入安静轮 decision_visible=True（无槽位仍有 header-only 单条注入）
- 宁缺勿错：goal 缺失 → 无 header（平铺照旧）；shadow 默认 → 无 header。
"""
from pathlib import Path

from llm_loop.cognitive.state import (
    CheckpointPointer,
    SemanticStateStore,
    SemanticTaskState,
    StateEnvelope,
    StateIdentity,
)
from llm_loop.introspection.goal import GoalStore
from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine


def _seed(
    engine,
    sess,
    tmp_path: Path,
    *,
    checkpoint_next: str = "执行B",
    stale_identity: bool = False,
    state_synced: bool = False,
):
    """预置 GoalStore 活跃 goal + 语义信封。

    - stale_identity=True: identity 与 goal 失配 → 触发 barrier rebuild
    - state_synced=True: 信封 state 内容与 goal 同步（一致路径下的正常态）；
      False 时 state 为陈旧内容（rebuild 用例的对照）。
    """
    sid = sess.session_id  # CR-R1.1: 与 build cognitive 路径同源（sess.session_id）
    audit = Path(engine.settings.data_dir) / "audit"  # 与 build 同源（data_dir=<tmp>/data）
    gs = GoalStore(audit)
    g = gs.create("测试目标X", session_id=sid)
    gs.checkpoint(g.id, what="完成A", next_step=checkpoint_next)
    goal = gs.get(g.id)
    cps = goal.get("checkpoints") or [{}]
    identity = StateIdentity(
        session_id=sid,
        goal_id=str(goal["id"]),
        goal_updated_at="2000-01-01T00:00:00" if stale_identity else str(goal["updated_at"]),
        checkpoint_ts=str((cps[-1] or {}).get("ts", "")),
    )
    if state_synced:
        state = SemanticTaskState(
            objective="测试目标X",
            checkpoint=CheckpointPointer(what="完成A", next=checkpoint_next),
        )
    else:
        state = SemanticTaskState(
            objective="陈旧目标（应被 rebuild 覆盖）",
            checkpoint=CheckpointPointer(what="旧步骤", next="旧next"),
        )
    env = StateEnvelope(identity=identity, state=state)
    SemanticStateStore(audit).save(sid, env)
    return goal


def _enforce(engine):
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")


def _tail(out) -> str:
    return out[-1]["content"] if out else ""


# ── 不变量④+②：barrier 一致 → header 可见（checkpoint next 投影）────────


def test_barrier_consistent_header_visible(tmp_path):
    engine, sess = _engine(tmp_path)
    _seed(engine, sess, tmp_path, state_synced=True)  # 一致信封 + 内容同步（正常态）
    _enforce(engine)
    out = _build(engine, sess, [])
    tail = _tail(out)
    assert "[当前决策] 测试目标X" in tail
    assert "[下一步] 执行B" in tail


# ── 不变量②：checkpoint B 更新 → barrier 失配 → rebuild → 注入含 B ────────


def test_barrier_mismatch_rebuilds_and_persists(tmp_path):
    engine, sess = _engine(tmp_path)
    goal = _seed(engine, sess, tmp_path, checkpoint_next="执行B", stale_identity=True)
    _enforce(engine)
    out = _build(engine, sess, [])
    tail = _tail(out)
    # 重建自 goal（陈旧目标被覆盖，objective/next 来自 goal dict）
    assert "[当前决策] 测试目标X" in tail
    assert "[下一步] 执行B" in tail
    assert "陈旧目标" not in tail
    # 回存：分片 identity 与 goal 一致（rebuild+save 生效）
    env = SemanticStateStore(Path(engine.settings.data_dir) / "audit").load(sess.session_id)
    assert isinstance(env, StateEnvelope)
    assert env.identity.matches(goal) is True


# ── 不变量⑤：零注入安静轮 decision_visible=True（header-only 单条注入）────


def test_quiet_round_header_only_visible(tmp_path):
    engine, sess = _engine(tmp_path)
    _seed(engine, sess, tmp_path, state_synced=True)  # 有效一致信封
    _enforce(engine)
    out = _build(engine, sess, [])  # 不 arm 任何槽位
    tail = _tail(out)
    assert out[-1]["role"] == "user"
    assert "[当前决策] 测试目标X" in tail  # header-only：无槽位段也有决策前导
    assert "[slot:" not in tail  # 安静轮无槽位段


# ── 宁缺勿错：goal 缺失 → 无 header（不注入不确定投影）──────────────────


def test_goal_missing_no_header(tmp_path):
    engine, sess = _engine(tmp_path)
    sid = sess.session_id  # CR-R1.1: 与 build cognitive 路径同源
    # 信封存在但 GoalStore 无该会话活跃 goal（不 seed goal）
    env = StateEnvelope(
        identity=StateIdentity(
            session_id=sid, goal_id="G-x", goal_updated_at="t", checkpoint_ts="c"
        ),
        state=SemanticTaskState(
            objective="孤儿目标", checkpoint=CheckpointPointer(what="w", next="n")
        ),
    )
    SemanticStateStore(Path(engine.settings.data_dir) / "audit").save(sid, env)
    _enforce(engine)
    _arm_all_slots(engine, sess)
    out = _build(engine, sess, [])
    tail = _tail(out)
    assert "[当前决策]" not in tail  # 宁缺勿错：无法核验一致性 → 不投影
    assert "--- [slot:" in tail or "--- [tier:" in tail  # 槽位聚合照旧（fail-open 不阻断注入）


# ── shadow 默认：无 header（不进 prompt）───────────────────────────────


def test_shadow_default_no_header(tmp_path):
    engine, sess = _engine(tmp_path)
    _seed(engine, sess, tmp_path)  # 有效一致信封
    # 不切 enforce（默认 shadow）
    _arm_all_slots(engine, sess)
    out = _build(engine, sess, [])
    tail = _tail(out)
    assert "[当前决策]" not in tail


# ── CR-R1.1（审查项4）: envelope 缺失 → 主动 rebuild（冷启动首轮建 header）──


def test_cold_start_missing_envelope_rebuilds_on_first_round(tmp_path):
    """envelope 缺失 + active goal 在场：首轮 build 即 rebuild+save，header 注入.

    审查实测旧行为：无 envelope → _sem_state=None → 前置门不进 GoalStore →
    不 rebuild 不 save → header 一直缺席（直到 compact 恰好触发 persist）。
    新逻辑："没有 envelope"不是"不可信"，GoalStore 能安全确认即重建。
    """
    engine, sess = _engine(tmp_path)
    audit = Path(engine.settings.data_dir) / "audit"
    GoalStore(audit).create("冷启动目标", session_id=sess.session_id)
    _enforce(engine)
    _arm_all_slots(engine, sess)
    out = _build(engine, sess, [])
    tail = _tail(out)
    # 首轮即注入 header（不再等 compact 触发）
    assert "[当前决策] 冷启动目标" in tail
    # envelope 已回存且身份同源（后续轮次走一致路径）
    env = SemanticStateStore(audit).load(sess.session_id)
    assert isinstance(env, StateEnvelope)
    assert env.identity.session_id == sess.session_id
    assert env.identity.goal_id  # 非 GOAL- 占位


def test_rebuild_revision_monotonic_inheritance(tmp_path):
    """CR-R1.1（审查项11）: mismatch rebuild 继承旧 revision+1，不再回退到 1."""
    engine, sess = _engine(tmp_path)
    audit = Path(engine.settings.data_dir) / "audit"
    gs = GoalStore(audit)
    goal = gs.create("演进目标", session_id=sess.session_id)
    store = SemanticStateStore(audit)
    # 预置 revision=7 的信封，identity 故意陈旧（updated_at 不一致 → mismatch）
    store.save(
        sess.session_id,
        StateEnvelope(
            identity=StateIdentity(
                session_id=sess.session_id,
                goal_id=str(goal.id),
                goal_updated_at="old-ts",
                checkpoint_ts="old-cp",
                state_revision=7,
            ),
            state=SemanticTaskState(
                objective="旧状态",
                checkpoint=CheckpointPointer(what="w", next="n"),
            ),
        ),
    )
    _enforce(engine)
    _arm_all_slots(engine, sess)
    _build(engine, sess, [])
    env = store.load(sess.session_id)
    assert isinstance(env, StateEnvelope)
    assert env.identity.state_revision == 8  # 7+1（单调），而非回退 1


# ── CR-R1.1（审查项6）: shadow 同构——telemetry 照发，投影不进 prompt ─────


def test_shadow_isomorphic_telemetry_rows_exist(tmp_path, monkeypatch):
    """shadow 完整跑 load/barrier/compile 并发 packet_compile 事件（旧行为 rows=0）.

    shadow 与 enforce 共享同一 compiler 产物（shadow 数据可预演 enforce）；
    仅投影/header 不进 prompt（平铺旧行为）。归因断言（审查项7）：
    goal_id 非空（旧写法从 _sem_state.identity 恒取空串）、revision≥1。
    """
    import json as _json

    engine, sess = _engine(tmp_path)
    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    _seed(engine, sess, tmp_path, state_synced=True)  # 一致信封（barrier 通过）
    _arm_all_slots(engine, sess)
    out = _build(engine, sess, [])
    tail = _tail(out)
    assert "[当前决策]" not in tail  # shadow: 投影不进 prompt
    tpath = Path(engine.settings.data_dir) / "audit" / "cognitive_telemetry.jsonl"
    assert tpath.exists(), "shadow 同构后应产生 telemetry（旧行为 rows=0）"
    rows = [
        _json.loads(ln)
        for ln in tpath.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert any(r.get("event") == "packet_compile" for r in rows)
    pc = next(r for r in rows if r.get("event") == "packet_compile")
    assert pc.get("goal_id"), "goal_id 归因（_env.identity 来源，旧写法恒空）"
    assert int(pc.get("state_revision") or 0) >= 1, "state_revision 归因"
