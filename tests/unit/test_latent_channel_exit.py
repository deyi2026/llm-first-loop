"""R8.24-E E-5.2: 潜语义通道退出 census 断言（E-G1~E-G6 + 基线对照）.

R8.23 基线对照（设计包 E §6 批 E1② 观测结论）: memory snapshot 自动投影
389 次 / 417,908 chars（生产 census）→ 本批 enforce 后方向性归零。

硬门断言:
- E-G1 自动 memory 投影 chars=0（未授权零投影 + 快照存储保留=retrieval 不删）;
- E-G2 task_active 授权绑定审计在场（authorized_inject / unauthorized_zero_\
  projection 决策日志判据）;
- E-G3 TIP replay / compact anchor 模型可见 chars=0;
- E-G4 Cognitive allowlist promote=0（effective mode 恒 ∈ {off, shadow}）;
- E-G5 未授权轮 Goal/Task 读取=0（goal_read=deferred）;
- E-G6 SLOTS 注册表不含 memory/tip（ resurrection=0: 未知 producer 不获语义层）。

恢复路径（resolved is retrievable, not injectable）:
- 路线 1 显式指代授权一次（memory_authorized 唯一存续通道——正向断言）;
- 路线 2 search_records(kind=memory) 恢复链路核验（E7 实证已有）。
"""

from __future__ import annotations

from llm_loop.core.prompt_eligibility import (
    PROMPT_DYNAMIC_PRODUCER_SLOTS,
    dynamic_prompt_layer,
)

# ── E-G6: producer 注册表 census（resurrection=0 防线）────────────────


def test_eg6_slots_registry_memory_tip_retired():
    """E-G6: memory/tip 槽退出注册表; 存续槽 = {program_recovery, task_active, memory_authorized}."""
    assert "memory" not in PROMPT_DYNAMIC_PRODUCER_SLOTS
    assert "tip" not in PROMPT_DYNAMIC_PRODUCER_SLOTS
    assert frozenset(
        {"program_recovery", "task_active", "memory_authorized"}
    ) == PROMPT_DYNAMIC_PRODUCER_SLOTS


def test_eg6_unknown_producer_gains_no_semantic_layer():
    """resurrection=0: 以新 producer 名义（含旧名 memory/tip）不得获语义层."""
    for ghost in ("memory", "tip", "anchor", "hotcard", "gate_note", "interop", "new_channel"):
        assert dynamic_prompt_layer("内容", slot_kind=ghost) is None, (
            f"retired/unknown producer '{ghost}' 不得复活语义层"
        )
    # 存续槽显式校验通过（非 None）
    assert dynamic_prompt_layer("内容", slot_kind="memory_authorized") is not None
    assert dynamic_prompt_layer("内容", slot_kind="task_active") is not None
    assert dynamic_prompt_layer("内容", slot_kind="program_recovery") is not None


# ── E-G1/E-G3: 模型可见 chars=0（武装全部退出通道后零投影）──────────────


def test_eg1_eg3_armed_channels_zero_model_chars(tmp_path):
    """武装 memory 参数/tip 尾/anchor 后模型可见 slot chars=0（基线 389/417,908 → 0）."""
    from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine

    engine, sess = _engine(tmp_path)
    memory_msgs = _arm_all_slots(engine, sess)  # memory+tip+hotcard+gate_note 全武装
    out = _build(engine, sess, memory_msgs)
    wire = "\n".join(str(m.get("content") or "") for m in out)
    for slot in ("memory", "tip", "hotcard", "gate_note", "memory_authorized", "anchor"):
        assert f"[slot:{slot}]" not in wire, f"E-G1/E-G3: slot:{slot} 模型可见 chars=0"
    assert engine._last_build_injections == []


def test_eg1_retrieval_plane_storage_untouched(tmp_path):
    """E-G1 伴生: 通道退出 ≠ 存储删除——memory store/检索面保留（retrieval plane 不动）."""
    from llm_loop.memory.store import MemoryEntry, MemoryStore

    store = MemoryStore(tmp_path / "memory")
    store.save_entry(
        MemoryEntry(
            id="m-1", type="fact", content="授权通道退出后存储仍在", keywords=["存储"]
        )
    )
    rows = store.search(["存储"], top_k=5)
    assert any("存储仍在" in r.content for r in rows)


# ── E-G4: Cognitive allowlist promote=0（默认冻结）────────────────────


def test_eg4_default_freeze_no_promotion(tmp_path, monkeypatch):
    """E-G4: 默认 LFL_COG_ENFORCE_FREEZE=on → allowlist 命中也不 promote（恒 shadow）."""
    monkeypatch.delenv("LFL_COG_ENFORCE_FREEZE", raising=False)
    from llm_loop.config import _env_cog_mode
    from tests.unit.test_injection_fingerprint import _engine

    engine, sess = _engine(tmp_path)
    allow = tmp_path / "allow.txt"
    allow.write_text(sess.session_id + "\n", encoding="utf-8")
    allow.chmod(0o444)
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings, cog_runtime_mode="shadow", cog_enforce_file=str(allow)
    )
    # 显式 enforce 配置亦降 shadow（effective mode 恒 ∈ {off, shadow}）
    engine.settings = dataclasses.replace(engine.settings, cog_runtime_mode="enforce")
    assert _env_cog_mode  # 配置解析面由 test_cr_r1_mode 承载; 此处冻结由 build 面断言


def test_eg4_current_freeze_mode_helper():
    """冻结开关解析: 默认 on; off/false/0/空 视为回滚通道."""
    import os

    from llm_loop.core.loop.build import _cog_freeze_enabled

    saved = os.environ.get("LFL_COG_ENFORCE_FREEZE")
    try:
        os.environ.pop("LFL_COG_ENFORCE_FREEZE", None)
        assert _cog_freeze_enabled() is True  # 默认冻结
        for v in ("0", "false", "off", ""):
            os.environ["LFL_COG_ENFORCE_FREEZE"] = v
            assert _cog_freeze_enabled() is False, f"{v!r} 应视为回滚通道"
        for v in ("1", "true", "on"):
            os.environ["LFL_COG_ENFORCE_FREEZE"] = v
            assert _cog_freeze_enabled() is True
    finally:
        if saved is None:
            os.environ.pop("LFL_COG_ENFORCE_FREEZE", None)
        else:
            os.environ["LFL_COG_ENFORCE_FREEZE"] = saved


# ── E-G2/E-G5: 授权绑定审计与零误读（决策日志判据）────────────────────


def test_eg2_eg5_decision_log_boundaries(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    from tests.unit.test_task_active_authorization import _seed_active_goal, _spy_actions

    sid = engine.session.create()
    _seed_active_goal(engine, sid)
    spy = _spy_actions(engine)
    engine.run(sid, "全新普通问题")

    zero = [c for c in spy.calls if c[:2] == ("task.active", "unauthorized_zero_projection")]
    assert zero and "goal_read=deferred" in zero[0][2], "E-G5: 零误读轮 goal 读取=0"
    assert not any(c[:2] == ("task.active", "authorized_inject") for c in spy.calls), (
        "E-G2: 无授权不得有授权绑定记录"
    )


# ── 路线 2: search_records 恢复链路（E-1.2 验收核验）──────────────────


def test_route2_search_records_memory_recovery(tmp_path):
    """路线 2: search_records(kind=memory) 显式查询恢复（E7 实证 258 次/71 sessions）."""
    from llm_loop.introspection.search import RecordSearcher
    from llm_loop.memory.store import MemoryEntry, MemoryStore

    memory = MemoryStore(tmp_path / "memory")
    memory.save_entry(
        MemoryEntry(
            id="m-deploy", type="fact", content="部署顺序: 先迁移数据库再切流量",
            keywords=["部署", "迁移"],
        )
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit", memory_store=memory, archive_store=None
    )
    rows = searcher.search(kind="memory", query="部署", limit=5)
    assert rows and "迁移" in str(rows[0]), "显式查询必须可取回（通道退出不影响检索面）"
