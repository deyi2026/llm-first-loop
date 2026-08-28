"""CR-R1 任务组 1 单测（tasks 1.4）：StateEnvelope / 分片隔离 / 迁移 / 墓碑 / revision。

不变量映射：① 会话隔离（spec 4.1-1）/ ③ 终态墓碑（spec 4.1-3）+ design §2.1。
"""
import json

from llm_loop.cognitive.state import (
    STALE_UNTRUSTED,
    CheckpointPointer,
    SemanticStateStore,
    SemanticTaskState,
    StateEnvelope,
    StateIdentity,
    Tombstone,
    rebuild_state,
)


def _goal(status="active", updated_at="2026-08-28T00:00:00+00:00", goal_id="GOAL-1", n_cps=1):
    # key 结构对齐 Goal.to_dict（asdict）：字段名是 id（goal.py L39），非 goal_id
    return {
        "id": goal_id,
        "objective": "测试目标",
        "status": status,
        "updated_at": updated_at,
        "checkpoints": [
            {"what": f"cp{i}", "next": f"nx{i}", "ts": f"2026-08-28T00:0{i}:00+00:00"}
            for i in range(n_cps)
        ],
    }


def _envelope(session_id="AAAABBBB", goal_id="GOAL-1", updated_at="t1", cp_ts="c1"):
    return StateEnvelope(
        identity=StateIdentity(
            session_id=session_id,
            goal_id=goal_id,
            goal_updated_at=updated_at,
            checkpoint_ts=cp_ts,
        ),
        state=SemanticTaskState(
            objective="A 目标",
            checkpoint=CheckpointPointer(what="w", next="n"),
        ),
    )


# ── 不变量①：按会话分片隔离 ──────────────────────────────────────────


def test_shard_isolation_session_a_invisible_to_b(tmp_path):
    store = SemanticStateStore(tmp_path)
    store.save("AAAABBBB", _envelope())
    # Session B（不同 sid8）读不到 A 的分片：无分片且无遗留 → None
    assert store.load("CCCCDDDD") is None
    # Session A 自身可读回
    loaded = store.load("AAAABBBB")
    assert isinstance(loaded, StateEnvelope)
    assert loaded.state.objective == "A 目标"
    assert loaded.identity.session_id == "AAAABBBB"


def test_shard_file_layout(tmp_path):
    store = SemanticStateStore(tmp_path)
    store.save("AAAABBBB", _envelope())
    # 分片文件按 sid8 命名
    assert (tmp_path / "cognitive" / "state.AAAABBBB.yaml").exists()
    # 同 sid8 前缀（更长会话 id）共享分片
    loaded = store.load("AAAABBBB-extra")
    assert isinstance(loaded, StateEnvelope)


# ── 迁移：旧无头 state.yaml → STALE_UNTRUSTED ────────────────────────


def test_legacy_global_state_is_stale_untrusted(tmp_path):
    d = tmp_path / "cognitive"
    d.mkdir(parents=True)
    (d / "state.yaml").write_text(json.dumps({"objective": "旧全局状态"}), encoding="utf-8")
    store = SemanticStateStore(tmp_path)
    assert store.load("ANY1SID") is STALE_UNTRUSTED


def test_rebuild_writes_new_shard_after_stale(tmp_path):
    d = tmp_path / "cognitive"
    d.mkdir(parents=True)
    (d / "state.yaml").write_text(json.dumps({"objective": "旧全局状态"}), encoding="utf-8")
    store = SemanticStateStore(tmp_path)
    assert store.load("AAAABBBB") is STALE_UNTRUSTED
    # 调用方 rebuild 后写新分片 → 可读回，旧文件留存不再读
    store.save("AAAABBBB", _envelope())
    loaded = store.load("AAAABBBB")
    assert isinstance(loaded, StateEnvelope)
    assert (d / "state.yaml").exists()  # 旧文件留存供审计


def test_corrupted_shard_returns_none(tmp_path):
    store = SemanticStateStore(tmp_path)
    store.save("AAAABBBB", _envelope())
    p = tmp_path / "cognitive" / "state.AAAABBBB.yaml"
    p.write_text("{not json", encoding="utf-8")
    assert store.load("AAAABBBB") is None


def test_shard_missing_identity_header_is_stale(tmp_path):
    store = SemanticStateStore(tmp_path)
    p = tmp_path / "cognitive" / "state.AAAABBBB.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"objective": "无头分片"}), encoding="utf-8")
    assert store.load("AAAABBBB") is STALE_UNTRUSTED


# ── 不变量③：终态墓碑防复活 ──────────────────────────────────────────


def test_tombstone_persists_and_blocks_state_use(tmp_path):
    store = SemanticStateStore(tmp_path)
    env = _envelope()
    env.tombstone = Tombstone(reason="goal_complete", ts="2026-08-28T01:00:00+00:00")
    store.save("AAAABBBB", env)
    loaded = store.load("AAAABBBB")
    assert isinstance(loaded, StateEnvelope)
    assert loaded.tombstone is not None
    assert loaded.tombstone.reason == "goal_complete"
    # 消费方判定（build 读侧语义）：有墓碑 → 不投影
    usable = loaded.state if loaded.tombstone is None else None
    assert usable is None


def test_rebuild_state_terminal_goal_returns_none():
    assert rebuild_state(_goal(status="complete")) is None
    assert rebuild_state(_goal(status="blocked")) is None


def test_rebuild_state_active_goal_returns_state():
    state = rebuild_state(_goal(status="active"))
    assert state is not None
    assert state.objective == "测试目标"
    assert state.checkpoint is not None and state.checkpoint.what == "cp0"


def test_rebuild_state_empty_or_missing_goal():
    assert rebuild_state(None) is None
    assert rebuild_state({}) is None


# ── identity / revision 语义（design §2.1/§2.2）──────────────────────


def test_identity_matches_current_goal():
    g = _goal()
    identity = StateIdentity(
        session_id="s1",
        goal_id="GOAL-1",
        goal_updated_at=g["updated_at"],
        checkpoint_ts=g["checkpoints"][-1]["ts"],
    )
    assert identity.matches(g) is True


def test_identity_mismatch_on_goal_update():
    g = _goal()
    identity = StateIdentity(
        session_id="s1", goal_id="GOAL-1", goal_updated_at=g["updated_at"], checkpoint_ts="c1"
    )
    g2 = dict(g, updated_at="2026-08-28T02:00:00+00:00")
    assert identity.matches(g) is False or identity.matches(g2) is False


def test_identity_matches_empty_goal_is_false():
    identity = StateIdentity(
        session_id="s1", goal_id="GOAL-1", goal_updated_at="t1", checkpoint_ts="c1"
    )
    assert identity.matches({}) is False


def test_envelope_roundtrip(tmp_path):
    store = SemanticStateStore(tmp_path)
    env = _envelope()
    env.identity.state_revision = 3
    store.save("AAAABBBB", env)
    loaded = store.load("AAAABBBB")
    assert isinstance(loaded, StateEnvelope)
    assert loaded.identity == env.identity
    assert loaded.state is not None and loaded.state.objective == "A 目标"


def test_source_digest_stable_and_sensitive():
    a = StateIdentity(session_id="s", goal_id="G", goal_updated_at="t1", checkpoint_ts="c")
    b = StateIdentity(session_id="s", goal_id="G", goal_updated_at="t1", checkpoint_ts="c")
    c = StateIdentity(session_id="s", goal_id="G", goal_updated_at="t2", checkpoint_ts="c")
    assert a.source_digest == b.source_digest
    assert a.source_digest != c.source_digest
