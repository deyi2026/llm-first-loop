"""集成测试: 演进自动执行 + 自我评估闭环（T67 / EXEC-02/03/06 + EVAL-01/05/07）.

覆盖（design.md 6.4.3 关键测试桩）:
- accepted 后自动执行闭环（evolve-review accept → maybe_auto_execute → executed + 审计可检索）
- 涉边界演进人工执行（不自动执行 → manual_complete → executed + executor=human）
- 评估-改进-验证闭环（self_evaluate → submit_evolution(eval_id) → 执行 → 再评估对比）
"""

from __future__ import annotations

from llm_loop.introspection.search import RecordSearcher


def _make_engine(tmp_path):
    """构造最小引擎（隔离数据目录 + 关闭自省干扰）."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    return build_engine(settings)  # type: ignore[no-any-return]


def test_accepted_auto_execute_loop(tmp_path):
    """accepted + 级别 2 → executing → evolution_complete 工具登记 → executed（G1 闭环，生产路径）."""
    from llm_loop.cli import _cmd_evolve_review

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(
        content="清理缓存演进",
        impact_scope="recover_state",
        actions=[{"tool_name": "recover_state", "arguments": {"scope": "clear_cache"}}],
    )
    engine.correction_ctx.evolve_local_exec = 2
    assert _cmd_evolve_review(engine, sug.id, "accepted") == 0
    # M16 审计（FR-AUDIT-AI-01）: maybe_auto_execute 允许 → executing（执行/验证交 AI，不伪装终态）
    states = [e["status"] for e in store.list() if e["id"] == sug.id]
    assert states[0] == "executing"
    # verify_result=unverified + note 含验证引导（防"验证未接线"被掩盖，7.0.3 教训）
    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert '"executor": "ai"' in exec_log
    assert '"verify_result": "unverified"' in exec_log
    assert "architecture_status" in exec_log  # note 含验证引导
    # M17 G1 闭环: AI 经 evolution_complete 工具登记（生产路径，非直调 complete）
    r = engine.corrections.execute(
        "evolution_complete", {"suggestion_id": sug.id, "note": "已执行并对比架构状态，验证通过"}
    )
    assert r.status.value == "success"
    assert "executor=ai" in r.content
    assert "verify=ai_reported" in r.content
    assert store.list(status="executed")[0]["id"] == sug.id
    # 执行审计可检索（EXEC-06）
    searcher = RecordSearcher(audit_dir=engine.settings.audit_dir)
    hits = searcher.search(kind="evolution_exec", query=sug.id)
    assert len(hits) >= 1
    assert hits[0]["kind"] == "evolution_exec"


def test_boundary_accepted_human_execution(tmp_path):
    """涉边界 accepted → 不自动执行 → CLI evolve-complete → executed + executor=human（EXEC-03）."""
    from llm_loop.cli import _cmd_evolve_complete, _cmd_evolve_review

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="调整安全策略", impact_scope="safety")
    engine.correction_ctx.evolve_local_exec = 2  # 即使级别 2 边界也不放行
    assert _cmd_evolve_review(engine, sug.id, "accepted") == 0
    # 边界 → 保持 accepted（等待人工执行）
    assert store.list(status="accepted")[0]["id"] == sug.id
    # M17 G1 人工通道: CLI evolve-complete（复用 manual_complete）
    assert _cmd_evolve_complete(engine, sug.id, "人工已完成安全边界调整") == 0
    assert store.list(status="executed")[0]["id"] == sug.id
    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert '"executor": "human"' in exec_log


def test_eval_improve_verify_loop(tmp_path):
    """评估-改进-验证闭环: self_evaluate → submit_evolution(eval_id) → 执行 → 再评估对比（EVAL-05/07）."""
    from llm_loop.cli import _cmd_evolve_review
    from llm_loop.introspection.evaluator import SelfEvaluator

    engine = _make_engine(tmp_path)
    evaluator = SelfEvaluator(status_provider=None, audit_dir=engine.settings.audit_dir)
    # 1. 评估（改进前基线）
    before = evaluator.evaluate(session_id="s-eval", trigger="manual")
    assert before.eval_id.startswith("SE-")
    # 2. 基于评估提交改进建议（走 submit_evolution 工具链路: evidence 引用 eval:<id> → eval_id 回填）
    store = engine.correction_ctx.evolution_store
    r = engine.corrections.execute(
        "submit_evolution",
        {
            "content": "基于评估优化超时参数",
            "impact_scope": "timeout_s",
            "evidence": f"eval:{before.eval_id}",
        },
    )
    assert r.status.value == "success"
    sug = store.list()[-1]
    assert sug["eval_id"] == before.eval_id
    # 3. 执行改进（级别 2 自动执行）
    engine.correction_ctx.evolve_local_exec = 2
    assert _cmd_evolve_review(engine, sug["id"], "accepted") == 0
    # 4. 再评估（改进后）+ AI 侧自比基础（M18 AA5: compare 已移除，对比交 AI）
    after = evaluator.evaluate(session_id="s-eval", trigger="manual")
    assert before.eval_id != after.eval_id  # 两次评估可溯源
    am = {m.name: m for m in after.metrics}
    assert "success_rate" in am  # 指标字段可读（AI 自比 delta 基础）
    # 双向溯源: 检索 self_eval → 关联建议 ID
    searcher = RecordSearcher(audit_dir=engine.settings.audit_dir)
    hits = searcher.search(kind="self_eval", query=before.eval_id)
    assert len(hits) >= 1
    linked = hits[0].get("linked_suggestions", [])
    assert sug["id"] in linked


def test_eval_trigger_reminder_not_blocking(build_test_engine):
    """触发提醒仅提示不强制: AI 选择不评估 → 回答正常输出（EVAL-03，DFX-PERF-06）."""
    from llm_loop.introspection.evaluator import EvalTriggerDetector

    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    engine.loop_signal_detector._eval_trigger_detector = EvalTriggerDetector(interval_rounds=9999)
    sid = engine.session.create()
    result = engine.run(sid, "你好")
    # 里程碑提醒已注入但回答不受影响
    assert result.final_answer == "我是 AI 助手。"
    assert result.rounds >= 1


def test_production_wiring_no_verifier_rollback(tmp_path):
    """M16 审计（FR-AUDIT-AI-01）生产路径接线断言: EvolutionExecutor 无 verifier/rollback 参数
    （防"单测 Fake 掩盖生产未接线"复发，7.0.3 教训）."""
    import inspect

    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    sig = inspect.signature(EvolutionExecutor.__init__)
    params = list(sig.parameters)
    assert "verifier" not in params
    assert "rollback" not in params
    # 生产构造不传（CLI 路径）
    engine = _make_engine(tmp_path)
    executor = EvolutionExecutor(
        exec_level=2,
        store=engine.correction_ctx.evolution_store,
        audit_dir=engine.settings.audit_dir,
    )
    # 移交后: 无 verifier/rollback 内部引用，审计落盘保留
    assert not hasattr(executor, "_verifier")
    assert not hasattr(executor, "_rollback")
    assert executor._audit_dir is not None


def test_evolution_executing_reminder_injected(build_test_engine):
    """M17 FR-REVIEW-AI-02: executing 演进 → 循环内注入 [演进执行提醒]（含 id + 引导）."""
    from llm_loop.core.message import ToolCall

    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "/no/such"})]},
            {"content": "最终回答"},
        ]
    )
    # 预置 executing 演进（loop_signal_detector 经 evolution_store 检测）
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    sid = engine.session.create()
    result = engine.run(sid, "执行待办演进")
    assert result.final_answer  # 提醒不阻断回答
    sess = engine.session.load(sid)
    # 提醒经 [架构上报] 通道注入（DEVIATION 事件，含 executing 事实 + evolution_complete 引导）
    reminders = [
        m
        for m in sess.messages
        if m.role == "system"
        and "executing 演进建议" in m.content
        and "evolution_complete" in m.content
    ]
    assert len(reminders) >= 1
    assert sug.id in reminders[0].content
    # M19 T121 场景 e 冷却频率断言: 连续多轮不重复刷屏（60s 冷却 >> 测试时长 → ≤1 次/窗口）
    assert len(reminders) <= 1, f"提醒应经冷却去重（≤1 次/60s 窗口），实际 {len(reminders)} 次"
    assert result.rounds >= 1  # 提醒不改变循环轮数语义


def test_no_executing_no_reminder(build_test_engine):
    """M17 FR-REVIEW-AI-02: 无 executing 演进 → 不注入提醒."""
    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    sid = engine.session.create()
    result = engine.run(sid, "你好")
    assert result.final_answer
    sess = engine.session.load(sid)
    reminders = [m for m in sess.messages if m.role == "system" and "演进执行提醒" in m.content]
    assert reminders == []


def test_evolution_summary_in_architecture_status(tmp_path):
    """M17 FR-REVIEW-AI-05: architecture_status 返回 architecture_config 含 evolution_summary（executing 计数）."""
    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    r = engine.corrections.execute("architecture_status", {"dimensions": ["architecture_config"]})
    assert r.status.value == "success"
    import json

    snap = json.loads(r.content)
    es = snap.get("architecture_config", {}).get("evolution_summary", {})
    assert es.get("executing") == 1
    assert es.get("total") == 1


def test_submit_evolution_receipt_next_step(tmp_path):
    """M17 FR-REVIEW-AI-06: submit_evolution 回执含'等待 evolve-review 审阅'引导."""
    engine = _make_engine(tmp_path)
    r = engine.corrections.execute(
        "submit_evolution", {"content": "优化超时参数", "impact_scope": "timeout_s"}
    )
    assert r.status.value == "success"
    assert "evolve-review" in r.content
    assert "pending_review" in r.content
    assert "search_records(kind=evolution)" in r.content
    # 既有权限分级说明保留
    assert "仅建议模式" in r.content
