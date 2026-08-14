"""单元测试: 架构自省与 AI 修正工具（T18 / AI-serving 2.1.4）."""

from __future__ import annotations

import json

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.introspection.status import ArchitectureStatusProvider


def test_status_snapshot_eight_dimensions():
    """架构状态快照八维字段齐全、如实反映."""
    p = ArchitectureStatusProvider(config_status=lambda: {"tools": ["read_file"]})
    p.record_phase("action.tool_loop")
    p.record_action("action.tool_loop", "tool_call", "read_file data/x.txt")
    p.record_llm_round()
    snap = p.snapshot()
    for dim in (
        "current_phase",
        "action_trace",
        "tool_history",
        "message_flow",
        "memory_state",
        "context_usage",
        "exception_log",
        "architecture_config",
    ):
        assert dim in snap
    assert snap["current_phase"] == "action.tool_loop"
    assert snap["action_trace"][0]["detail"] == "read_file data/x.txt"
    assert snap["architecture_config"]["tools"] == ["read_file"]


def test_status_snapshot_dimension_crop():
    """维度裁剪 + 不可用维度如实标注."""
    p = ArchitectureStatusProvider()
    snap = p.snapshot(dimensions=["current_phase", "nonexistent_dim"])
    assert "current_phase" in snap
    assert "unavailable" in snap["nonexistent_dim"]


def test_event_report_cooldown():
    """上报冷却去重：冷却期内同类事件不重复上报."""
    r = ArchitectureStatusProvider(cooldown_s=100).reporter
    ev = ArchitectureEvent(
        event_type=ArchitectureEventType.EXCEPTION,
        fact="工具连续失败",
        reason="FileNotFoundError",
        suggestion="检查路径",
    )
    assert r.should_report(ev) is True
    assert r.should_report(ev) is False  # 冷却期内
    msg = r.build_message(ev)
    assert "[架构上报]" in msg.content
    assert "连续发生" in msg.content


def test_event_report_first_call_fresh_system(monkeypatch):
    """HARNESS-05 回归: 系统启动不足冷却窗（CI 全新 runner）时首次上报必须通过.

    根因: should_report 首次调用 last 取 0.0, 而 time.monotonic() 从系统启动起算;
    CI runner 启动可能 <60s → `now - 0 < cooldown` 误判冷却拦截首次上报
    → eval_trigger 提醒偶发不注入（本地系统启动久无法复现, CI 复现）。
    """
    import llm_loop.introspection.events as evmod

    class _FakeTime:
        t = 5.0

        @staticmethod
        def monotonic() -> float:
            return _FakeTime.t

    orig = evmod.time.monotonic
    evmod.time.monotonic = _FakeTime.monotonic
    try:
        r = ArchitectureStatusProvider(cooldown_s=60).reporter
        ev = ArchitectureEvent(
            event_type=ArchitectureEventType.DEGRADATION,
            fact="本轮 run 已完成",
            reason="r",
            suggestion="s",
        )
        assert r.should_report(ev) is True  # 系统启动 5s 首次上报必须通过
        assert r.should_report(ev) is False  # 仍处冷却
        _FakeTime.t = 70.0
        assert r.should_report(ev) is True  # 冷却过期恢复
    finally:
        evmod.time.monotonic = orig


def test_exception_log_reported():
    """异常记录落盘（exception_log）."""
    p = ArchitectureStatusProvider(audit_dir="/tmp/llm-loop-test-audit-exc")
    try:
        raise ValueError("boom")
    except ValueError as exc:
        p.record_exception("tool_execute", exc)
    assert len(p.snapshot()["exception_log"]) == 1
    assert p.snapshot()["exception_log"][0]["error_type"] == "ValueError"


def test_correction_adjust_strategy_whitelist():
    """修正工具边界校验：越界参数拒绝 + 白名单执行."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    # 越界: 关闭安全边界（不在白名单）
    r = reg.execute("adjust_strategy", {"strategy": {"safety": False}})
    assert r.status == ToolResultStatus.FAILURE
    assert "白名单" in r.content
    # 越界: 数值超范围
    r2 = reg.execute("adjust_strategy", {"strategy": {"max_iterations": 99999}})
    assert r2.status == ToolResultStatus.FAILURE
    # 合法
    r3 = reg.execute("adjust_strategy", {"strategy": {"max_iterations": 30}})
    assert r3.status == ToolResultStatus.SUCCESS
    assert ctx.strategy["max_iterations"] == 30


def test_correction_retry_uses_executor():
    """retry_tool 走注入的完整执行包裹."""
    ctx = CorrectionContext()
    calls: list[str] = []

    def fake_executor(name, args):
        calls.append(name)
        from llm_loop.core.message import ToolResult

        return ToolResult(
            status=ToolResultStatus.SUCCESS, content="ok", tool_call_id="r1", tool_name=name
        )

    ctx.retry_executor = fake_executor
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute("retry_tool", {"tool_name": "read_file", "arguments": {"path": "x"}})
    assert r.status == ToolResultStatus.SUCCESS
    assert calls == ["read_file"]


def test_correction_clear_state_removed():
    """T44: clear_state 已移除（死入口清理）→ 不在工具清单，调用返回失败."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    # 工具清单中无 clear_state
    names = [td["name"] for td in reg.tool_defs()]
    assert "clear_state" not in names
    # 调用返回失败（工具不存在）
    r = reg.execute("clear_state", {"scope": "stagnation"})
    assert r.status == ToolResultStatus.FAILURE
    # 修正工具集 + 检索/状态工具 + M12 submit_evolution/self_evaluate + M17 evolution_complete
    # + M48 model_catalog / switch_model（design §5.3 新增工具）
    # + P1-2 save_experience / refine_experience（经验库沉淀/生命周期）
    # + EVO-20260813-432813b2 主动出站飞书（send_feishu_message / create_feishu_doc / send_feishu_attachment）
    # + P2-2 recover_from_backup（fail-open 数据丢失恢复通道）
    # + P2-3 search_docs（docs/ 文档语义检索入口）
    assert set(names) == {
        "architecture_status",
        "search_archive",
        "search_records",
        # EVO-20260814: 统一事件流视图（对齐 Harness Trajectory）
        "event_stream",
        "search_docs",
        "adjust_strategy",
        "retry_tool",
        "refresh_config",
        "submit_evolution",
        "self_evaluate",
        "evolution_complete",
        "model_catalog",
        "switch_model",
        "save_experience",
        "refine_experience",
        "send_feishu_message",
        "create_feishu_doc",
        "send_feishu_attachment",
        "recover_from_backup",
        # Codex 风格 Skills 工具（2026-08-13 头条文章盘点补齐）
        "code_review",
        "grill_me",
        "stop_slop",
            "handoff_now",
            "generate_evolution_template",
            "playwright_test",
            "record_skill",
            "brainstorm_design",
            "tdd_red_green",
            "design_review",
            # B3: 插件化 Skill（skills/ 目录）
            "skill_list",
            "skill_load",
    }


def test_architecture_status_tool_snapshot_json():
    """architecture_status 工具返回状态 JSON."""
    p = ArchitectureStatusProvider(config_status=lambda: {"llm_model": "fake"})
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx, status_provider=p)
    r = reg.execute("architecture_status", {})
    assert r.status == ToolResultStatus.SUCCESS
    data = json.loads(r.content)
    assert "current_phase" in data


def test_submit_evolution_receipt_level0_same_as_before(tmp_path):
    """EVOLVE_LOCAL_EXEC=0（默认）回执与现状一致（P0 零回归，EXEC-01）."""
    from llm_loop.introspection.evolution import EvolutionStore

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store, evolve_local_exec=0, session_id="s1")
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute(
        "submit_evolution",
        {"content": "优化记忆检索", "impact_scope": "memory/", "priority": "medium"},
    )
    assert r.status == ToolResultStatus.SUCCESS
    assert "仅建议模式" in r.content  # 级别 0 保持现状回执语义
    assert "EVOLVE_LOCAL_EXEC=0" in r.content


def test_submit_evolution_receipt_by_level(tmp_path):
    """回执按权限级别如实说明（EXEC-01: 1=白名单 / 2=全面）."""
    from llm_loop.introspection.evolution import EvolutionStore

    store = EvolutionStore(tmp_path / "audit")

    ctx1 = CorrectionContext(evolution_store=store, evolve_local_exec=1)
    r1 = CorrectionToolRegistry(ctx1).execute(
        "submit_evolution", {"content": "优化超时", "impact_scope": "timeout_s"}
    )
    assert r1.status == ToolResultStatus.SUCCESS
    assert "白名单局部执行" in r1.content

    ctx2 = CorrectionContext(evolution_store=store, evolve_local_exec=2)
    r2 = CorrectionToolRegistry(ctx2).execute(
        "submit_evolution", {"content": "优化超时", "impact_scope": "timeout_s"}
    )
    assert r2.status == ToolResultStatus.SUCCESS
    assert "全面执行" in r2.content


def test_submit_evolution_receipt_boundary(tmp_path):
    """涉边界建议回执仍标注需人工（EVOLVE-03）."""
    from llm_loop.introspection.evolution import EvolutionStore

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store, evolve_local_exec=2)
    r = CorrectionToolRegistry(ctx).execute(
        "submit_evolution", {"content": "调整安全策略", "impact_scope": "safety"}
    )
    assert r.status == ToolResultStatus.SUCCESS
    assert "需人工决策" in r.content


def test_self_evaluate_tool(tmp_path):
    """T64: self_evaluate 工具返回五维指标 + 落盘回执（EVAL-01/04）."""
    from llm_loop.introspection.evaluator import SelfEvaluator

    evaluator = SelfEvaluator(status_provider=None, audit_dir=tmp_path / "audit")
    ctx = CorrectionContext(evaluator=evaluator, session_id="s1")
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute("self_evaluate", {"trigger": "manual"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "[自我评估]" in r.content
    assert "success_rate" in r.content
    assert "self_eval" in r.content
    assert "eval:" in r.content  # 提示可引用评估 ID
    # 落盘
    assert (tmp_path / "audit" / "self_eval_log.jsonl").exists()


def test_self_evaluate_not_assembled():
    """self_evaluate 未装配 → 如实失败."""
    ctx = CorrectionContext(evaluator=None)
    r = CorrectionToolRegistry(ctx).execute("self_evaluate", {})
    assert r.status == ToolResultStatus.FAILURE
    assert "未装配" in r.content


def test_self_evaluate_invalid_trigger_failure(tmp_path):
    """M19 FIX-04: 非法 trigger → FAILURE 三件套（不再静默回退 manual）."""
    from llm_loop.introspection.evaluator import SelfEvaluator

    evaluator = SelfEvaluator(status_provider=None, audit_dir=tmp_path / "audit")
    ctx = CorrectionContext(evaluator=evaluator)
    r = CorrectionToolRegistry(ctx).execute("self_evaluate", {"trigger": "weird"})
    assert r.status == ToolResultStatus.FAILURE
    assert "[参数错误]" in r.content
    assert "periodic/milestone/anomaly/manual" in r.content
    assert "'weird'" in r.content  # 收到值如实回显
    # 非法 trigger 不产生评估（不消耗 eval_id 计数）
    assert not (tmp_path / "audit" / "self_eval_log.jsonl").exists()


def test_submit_evolution_eval_id_bidirectional(tmp_path):
    """T64: submit_evolution evidence 引用 eval:<id> → eval_id 回填 + 双向溯源（EVAL-05）."""
    from llm_loop.introspection.evaluator import SelfEvaluator
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.search import RecordSearcher

    evaluator = SelfEvaluator(status_provider=None, audit_dir=tmp_path / "audit")
    report = evaluator.evaluate(session_id="s1", trigger="manual")
    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(
        evolution_store=store, evaluator=evaluator, session_id="s1", evolve_local_exec=0
    )
    reg = CorrectionToolRegistry(ctx)
    r = reg.execute(
        "submit_evolution",
        {
            "content": "基于评估优化超时参数",
            "impact_scope": "timeout_s",
            "evidence": f"eval:{report.eval_id}",
        },
    )
    assert r.status == ToolResultStatus.SUCCESS
    # eval_id 回填落盘（建议 → 评估）
    stored = store.list()[0]
    assert stored["eval_id"] == report.eval_id
    # 检索 self_eval → 返回关联建议 ID（评估 → 建议）
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    hits = searcher.search(kind="self_eval", query=report.eval_id)
    assert len(hits) == 1
    assert hits[0]["id"] == report.eval_id
    assert stored["id"] in hits[0].get("linked_suggestions", [])


def test_search_records_schema_has_self_eval():
    """M16 审计（FR-AUDIT-AI-02）: search_records schema 三处含 self_eval（AI 可达）."""
    from llm_loop.introspection.search import _VALID_KINDS

    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    td = next(t for t in reg.tool_defs() if t["name"] == "search_records")
    enum = td["parameters"]["properties"]["kind"]["enum"]
    assert "self_eval" in enum
    # schema 枚举是 _VALID_KINDS 的子集（self_eval 已同步，历史缺口 param_adjust/selfheal 不在 schema 属既有范围）

    assert set(enum) <= set(_VALID_KINDS)
    assert "self_eval" in enum and "self_eval" in _VALID_KINDS
    assert "self_eval" in td["description"]

    # 错误提示文案含 self_eval（注入检索实现使 kind 校验可达——抛 ValueError 触发错误分支）
    def _raising(**kw):
        raise ValueError("kind 'no_such_kind' 不在可选范围")

    reg._search_records_fn = _raising  # noqa: SLF001
    r = reg.execute("search_records", {"kind": "no_such_kind"})
    assert "self_eval" in r.content


def test_submit_evolution_pure_suggestion_channel():
    """M16 审计（FR-AUDIT-AI-07）: submit_evolution 纯建议通道——schema 无 kind/actions 入参."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    td = next(t for t in reg.tool_defs() if t["name"] == "submit_evolution")
    props = td["parameters"]["properties"]
    assert "kind" not in props  # 防误加回 execute_request
    assert "actions" not in props
    assert "content" in props  # 纯建议通道核心入参保留


def test_adjust_strategy_frequency_budget(tmp_path):
    """M18 AA2: PARAM-03 单轮频次预算——生产路径连续 3 次后第 4 次拦截（如实反馈）."""
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
    engine = build_engine(settings)  # type: ignore[arg-type]
    ctx = engine.correction_ctx
    # 3 次合法调整（PARAM_ADJUST_PER_ROUND=3）
    for i in (30, 40, 50):
        r = engine.corrections.execute("adjust_strategy", {"strategy": {"max_iterations": i}})
        assert r.status.value == "success"
    # 第 4 次 → 频次超限拦截
    r4 = engine.corrections.execute("adjust_strategy", {"strategy": {"max_iterations": 60}})
    assert r4.status.value == "failure"
    assert "PARAM-03" in r4.content
    assert "已达上限" in r4.content
    # 非法参数不消耗频次（校验失败先于 can_adjust）: reset 后第 1 次传非法 → 白名单错误，不消耗
    ctx.runtime.reset_round()
    r_bad = engine.corrections.execute("adjust_strategy", {"strategy": {"safety": False}})
    assert r_bad.status.value == "failure"
    assert "白名单" in r_bad.content
    # 下一轮（reset 后）恢复可调
    r_ok = engine.corrections.execute("adjust_strategy", {"strategy": {"max_iterations": 70}})
    assert r_ok.status.value == "success"


def test_memory_stats_in_status(tmp_path):
    """M18 AA10: memory_state 补真实数据——注入统计含真实 entries/recent；未注入如实标注."""
    from llm_loop.introspection.status import ArchitectureStatusProvider

    # 未注入 → 如实标注"暂不可用"
    p1 = ArchitectureStatusProvider()
    assert p1.snapshot()["memory_state"]["note"] == "memory_state 暂不可用（未注入统计）"
    # 注入 → 真实数据
    p2 = ArchitectureStatusProvider(memory_stats_fn=lambda: {"entries": 2, "recent": []})
    ms = p2.snapshot()["memory_state"]
    assert ms["entries"] == 2

    # 闭包异常 → 如实标注读取失败（fail-open）
    def _broken():
        raise OSError("boom")

    p3 = ArchitectureStatusProvider(memory_stats_fn=_broken)
    ms3 = p3.snapshot()["memory_state"]
    assert "读取失败" in ms3["note"]


def test_retry_tool_call_id_unique():
    """M18 AA14: _make_tool_call id 唯一（time_ns 后缀，协议 C3）."""
    from llm_loop.factory import _make_tool_call

    tc1 = _make_tool_call("read_file", {"path": "/a"})
    tc2 = _make_tool_call("read_file", {"path": "/a"})
    assert tc1.id != tc2.id
    assert tc1.id.startswith("retry-read_file-")
    assert tc2.id.startswith("retry-read_file-")


def test_llm_error_text_three_part():
    """M18 AA15: llm_error_text 返回三件套文本（事实/原因/建议）."""
    from llm_loop.feedback.honesty import llm_error_text

    err = RuntimeError("connection refused")
    text = llm_error_text(err)
    assert "[LLM 调用异常]" in text
    assert "事实:" in text and "原因:" in text and "建议:" in text
    assert "检查网络/Key/模型名配置后重试" in text
    assert "connection refused" in text
    # 死函数已清理
    import llm_loop.feedback.honesty as h

    assert not hasattr(h, "llm_error_message")
    assert not hasattr(h, "memory_unavailable_message")


def test_search_truncation_note(tmp_path):
    """M19 FIX-02: 检索 >6 条命中 → 回执含"仅显示前 6 条"标注（真实命中数 + limit）."""
    from llm_loop.introspection.tools_status import run_search_records

    ctx = CorrectionContext()
    hits = [{"ts": f"t{i}", "kind": "action_trace", "summary": f"s{i}"} for i in range(9)]

    def _search(**kw):
        return hits

    r = run_search_records(
        ctx, _search, {"kind": "action_trace", "query": "x", "limit": 10}, lambda: ""
    )
    assert r.status.value == "success"
    assert "[仅显示前 6 条]" in r.content
    assert "共 9 条命中" in r.content
    assert "limit=10" in r.content
    # ≤6 条无标注
    r2 = run_search_records(
        ctx, lambda **kw: hits[:5], {"kind": "action_trace", "query": "x", "limit": 10}, lambda: ""
    )
    assert "[仅显示前 6 条]" not in r2.content


def test_status_snapshot_truncation_note(tmp_path):
    """M19 FIX-03: architecture_status 超 8000 字符 → 截断标注（位于截断段后）."""
    from llm_loop.introspection.tools_status import run_status

    class _BigStatus:
        def snapshot(self, dimensions=None):
            return {"big": "x" * 9000}

    r = run_status(CorrectionContext(), _BigStatus(), {})
    assert r.status.value == "success"
    assert "[快照截断] 超出 8000 字符" in r.content
    assert r.content.rfind("[快照截断]") > 8000  # 标注在截断段之后


def test_submit_evolution_eval_id_hint(tmp_path):
    """M19 FIX-05: 引用不存在 eval_id → 回执含提示引导 + 建议仍落盘."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.tools_evolution import run_submit_evolution

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store)
    r = run_submit_evolution(
        ctx,
        lambda *a, **k: None,
        {"content": "优化超时", "impact_scope": "timeout_s", "evidence": "eval:SE-NOPE"},
        audit_dir=str(tmp_path / "audit"),
    )
    assert r.status.value == "success"
    assert "评估 ID 'SE-NOPE' 未在 self_eval_log 中找到" in r.content
    assert store.list()[0]["eval_id"] == "SE-NOPE"  # 建议仍落盘（双向溯源不阻断）


def test_architecture_status_desc_has_evolution_summary():
    """M19 FR-UX-AI-02: architecture_status 描述含 evolution_summary 可达性引导."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    td = next(t for t in reg.tool_defs() if t["name"] == "architecture_status")
    assert "evolution_summary" in td["description"]
    assert "演进待办" in td["description"]


def test_submit_evolution_scope_session_receipt(tmp_path):
    """M49: scope=session → 回执标注 executing + 登记闭环指引，不进人工审阅."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.tools_evolution import run_submit_evolution

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store)
    r = run_submit_evolution(
        ctx,
        lambda *a, **k: None,
        {"content": "本轮临时调参", "impact_scope": "运行参数", "scope": "session"},
        audit_dir=str(tmp_path / "audit"),
    )
    assert r.status.value == "success"
    assert "scope=session" in r.content
    assert "状态=executing" in r.content
    assert "evolution_complete" in r.content
    assert "pending_review" not in r.content
    assert store.list(status="pending_review") == []


def test_submit_evolution_scope_boundary_override_receipt(tmp_path):
    """M49: 涉边界指定 session → 强制 global，回执如实标注覆盖."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.tools_evolution import run_submit_evolution

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store)
    r = run_submit_evolution(
        ctx,
        lambda *a, **k: None,
        {"content": "改安全边界", "impact_scope": "安全边界", "scope": "session"},
        audit_dir=str(tmp_path / "audit"),
    )
    assert r.status.value == "success"
    assert "scope=global" in r.content
    assert "覆盖为 global" in r.content
    assert store.list(status="pending_review")[0]["scope"] == "global"


def test_submit_evolution_default_scope_global_receipt(tmp_path):
    """M49: 不传 scope → 默认 global，回执保持原人工审阅语义（向后兼容）."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.tools_evolution import run_submit_evolution

    store = EvolutionStore(tmp_path / "audit")
    ctx = CorrectionContext(evolution_store=store)
    r = run_submit_evolution(
        ctx,
        lambda *a, **k: None,
        {"content": "优化超时", "impact_scope": "timeout_s"},
        audit_dir=str(tmp_path / "audit"),
    )
    assert r.status.value == "success"
    assert "scope=global" in r.content
    assert "evolve-review" in r.content


# ── R2/A6: 程序故障计数（AI 可感知程序故障率）──


def test_program_fault_counter_and_snapshot():
    """record_program_fault 计数 + snapshot 可见（AI 可感知程序故障）."""
    from llm_loop.introspection.status import ArchitectureStatusProvider

    p = ArchitectureStatusProvider(config_status=lambda: {"llm_model": "fake"})
    p.record_program_fault("memory")
    p.record_program_fault("memory")
    p.record_program_fault("llm_call")
    snap = p.snapshot()
    assert snap["program_faults"] == {"memory": 2, "llm_call": 1}
    # 禁用时不计（enabled=False）
    p.enabled = False
    p.record_program_fault("session_persist")
    assert p.snapshot()["program_faults"] == {"memory": 2, "llm_call": 1}


def test_engine_fault_recording(tmp_path):
    """引擎 fail-open 点记录程序故障（记忆失败路径）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def chat(self, messages, tools, **kw) -> LLMResponse:
            return LLMResponse(content="回答", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="回答", tool_calls=[], provider="fake")

            return _gen()

    class _BrokenMemory:
        def search(self, *a, **k):
            raise RuntimeError("记忆故障")

        def flush(self) -> None:
            pass  # 循环末记忆统计落盘（故障隔离外）

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    from llm_loop.introspection.status import ArchitectureStatusProvider

    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),  # type: ignore[arg-type]
        memory=_BrokenMemory(),  # type: ignore[arg-type]
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
        status_provider=ArchitectureStatusProvider(config_status=lambda: {"llm_model": "fake"}),
    )
    result = engine.run_single("任务")
    assert result.final_answer  # 记忆故障不阻断
    faults = engine.status.snapshot()["program_faults"]
    assert faults.get("memory", 0) >= 1  # 记忆故障已计数
