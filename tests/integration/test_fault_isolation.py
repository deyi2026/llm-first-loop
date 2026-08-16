"""T42 故障注入集成测试: 程序故障不影响 AI 发挥（M10 容错红线）.

注入程序组件异常 → AI 仍完成回答（不抛穿、如实标注）。
"""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import ToolCall


def test_memory_failure_does_not_block(build_test_engine):
    """记忆存储异常 → run 仍返回最终回答（FR-MEM-03 扩展）."""
    engine, fake = build_test_engine([{"content": "最终回答：记忆故障不影响。"}])
    with (
        mock.patch.object(engine.memory, "search", side_effect=RuntimeError("记忆索引崩溃")),
        mock.patch.object(engine.memory, "all", side_effect=RuntimeError("记忆索引崩溃")),
    ):
        sid = engine.session.create()
        result = engine.run(sid, "查询记忆相关")
    assert result.final_answer  # 回答仍输出


def test_session_save_failure_does_not_block(build_test_engine):
    """会话保存异常 → run 不抛穿、回答仍输出、含 [程序异常] 如实标注（T39）."""
    engine, fake = build_test_engine([{"content": "这是回答内容。"}])
    sid = engine.session.create()  # 先创建（未 mock）
    with mock.patch.object(engine.session, "save", side_effect=OSError("磁盘只读")):
        result = engine.run(sid, "你好")
    assert result.final_answer
    assert "[程序异常]" in result.final_answer  # 如实标注
    assert "会话保存失败" in result.final_answer


def test_archive_failure_does_not_block(build_test_engine):
    """压缩档案异常 → 循环继续、回答正常（fail-open）."""
    engine, fake = build_test_engine([{"content": "档案故障不影响回答。"}])
    if engine.archive is not None:
        with mock.patch.object(engine.archive, "archive", side_effect=RuntimeError("档案写失败")):
            sid = engine.session.create()
            result = engine.run(
                sid,
                "内容",
            )
        assert result.final_answer
    else:
        # 无 archive 装配时直接验证正常
        sid = engine.session.create()
        result = engine.run(sid, "内容")
        assert result.final_answer


def test_tool_error_receipt_ai_continues(build_test_engine):
    """工具执行异常 → AI 收到 [状态: error] 回执后继续（DFX-REL-01 扩展）."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "/no/such"})]},
            {"content": "读取失败，我基于现有信息回答。"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "读文件")
    sess = engine.session.load(sid)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    assert tool_msgs
    assert "[状态: failure]" in tool_msgs[-1].content  # 如实状态
    assert result.final_answer


def test_declaration_light_reminder_no_block(build_test_engine):
    """T38: 声明不一致 → 轻量提醒（不重入、不阻塞回答）."""
    engine, fake = build_test_engine([{"content": "我已写入文件 output.txt"}])
    sid = engine.session.create()
    result = engine.run(sid, "写文件")
    assert result.final_answer == "我已写入文件 output.txt"  # 直接输出
    assert result.verification_note is not None  # 差异记录
    sess = engine.session.load(sid)
    assert any("[声明提醒]" in m.content for m in sess.messages)


def test_prompt_contains_ai_rules(build_test_engine):
    """T40: system prompt 含四类 AI 自主规则（诚实/参数/停滞/故障）."""
    from llm_loop.core.prompt import build_system_prompt

    prompt = build_system_prompt()
    assert "诚实自查" in prompt
    assert "参数自主规范" in prompt
    assert "停滞自主调整" in prompt
    assert "程序故障处理" in prompt


def test_prompt_system_extra_env(monkeypatch, build_test_engine):
    """T40: SYSTEM_PROMPT_EXTRA 叠加自定义规则."""
    from llm_loop.core.prompt import build_system_prompt

    monkeypatch.setenv("SYSTEM_PROMPT_EXTRA", "## 附加规则\n必须使用简体中文回答。")
    prompt = build_system_prompt()
    assert "必须使用简体中文回答" in prompt


def test_evolution_state_transition_fail_open(tmp_path, monkeypatch):
    """M16 审计（DFX-REL-06/07）: 演进状态流转失败 → fail-open（不阻塞执行结果回传）."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    from pathlib import Path

    real_open = Path.open
    monkeypatch.setattr(Path, "open", _broken)
    try:
        executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
        outcome = executor.maybe_auto_execute(sug)
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    assert outcome is not None  # 状态流转失败不阻断结果回传
    assert outcome.status == "executing"


def test_self_eval_source_read_fail_open(tmp_path, monkeypatch):
    """M16 审计（DFX-REL-06/07）: 评估数据源读取失败 → 如实标注不伪造（fail-open）."""
    from llm_loop.introspection.evaluator import SelfEvaluator

    evaluator = SelfEvaluator(status_provider=None, audit_dir=tmp_path)
    # audit 目录不可读（不存在文件 → 空数据 → 如实标注不伪造，EVO-dc3876f9 后 note 可为"无工具调用样本"）
    report = evaluator.evaluate()
    for m in report.metrics:
        assert m.value is None
        # 无数据如实标注（"样本不足"或"无工具调用样本"等 fail-open 文案）
        assert m.note  # 非空即如实标注
    assert report.summary != ""


def test_evolution_audit_write_fail_open(tmp_path, monkeypatch):
    """M16 审计（DFX-REL-06/07）: evolution_exec_log 落盘失败 → fail-open（不阻塞）."""
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    # 用只读目录模拟审计写失败：构造后移除写权限不跨平台，改用 monkeypatch Path.open
    from pathlib import Path

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        if "a" in args:  # append 模式（审计写）
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _broken)
    try:
        executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")
        outcome = executor.maybe_auto_execute(sug)
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    assert outcome is not None
    assert outcome.status == "executing"  # 审计写失败不阻塞状态推进


def test_evolution_complete_registration_fail_open(tmp_path, monkeypatch):
    """M17 FR-REVIEW-AI-01: evolution_complete 登记落盘 OSError → 如实标注不静默驻留 executing."""
    from pathlib import Path

    from llm_loop.introspection.corrections import CorrectionContext
    from llm_loop.introspection.evolution import EvolutionStore
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    ctx = CorrectionContext(evolution_store=store)

    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=tmp_path / "audit")

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        if "a" in args:  # append 模式（审计写）
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _broken)
    try:
        from llm_loop.introspection.tools_exec_complete import run_evolution_complete

        r = run_evolution_complete(
            ctx, executor, lambda *a, **k: None, {"suggestion_id": sug.id, "note": "完成"}
        )
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    # 状态推进成功（complete 内部审计落盘异常被 suppress）；工具回执如实 success
    assert r.status.value == "success"
    assert "registered=True" in r.content  # 状态推进成功；落盘异常已如实降级（不静默驻留）


def test_evolution_executing_check_fail_open(build_test_engine, monkeypatch):
    """M17 FR-REVIEW-AI-02: executing 提醒检测 store 读取失败 → 不注入不阻断（fail-open）."""
    from pathlib import Path

    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    sid = engine.session.create()
    # 预置 executing 演进
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        p = str(getattr(self, "name", ""))
        if "evolution_suggestions.jsonl" in p:  # 只拦演进存储读取（检测失败 → fail-open）
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _broken)
    try:
        result = engine.run(sid, "你好")
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    assert result.final_answer  # 检测失败不阻断回答
    sess = engine.session.load(sid)
    reminders = [
        m for m in sess.messages if m.role == "system" and "executing 演进建议" in m.content
    ]
    assert reminders == []  # 读取失败 → 不注入（fail-open）


def test_memory_stats_fail_open(build_test_engine, monkeypatch):
    """M18 AA10: memory_stats_fn 闭包异常 → memory_state.note 如实标注（fail-open 不抛穿 architecture_status）."""
    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])

    # 注入会抛异常的 memory_stats_fn
    def _broken():
        raise OSError("memory read fail")

    engine.status._memory_stats_fn = _broken
    snap = engine.status.snapshot()
    ms = snap.get("memory_state", {})
    assert "读取失败" in ms.get("note", "")
    assert "memory read fail" in ms.get("note", "")


def test_llm_error_three_part_end_to_end(build_test_engine, monkeypatch):
    """M19 T123 场景 g: LLM 异常 → 三件套反馈 + 落盘 + 不抛穿（端到端）."""
    from llm_loop.llm.errors import LLMError

    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    # FakeLLM 抛 LLMError
    monkeypatch.setattr(
        fake, "chat", lambda *a, **k: (_ for _ in ()).throw(LLMError("connection refused"))
    )
    sid = engine.session.create()
    result = engine.run(sid, "你好")
    # a) 不抛穿（正常返回 LoopResult）+ 三件套结构
    assert result.final_answer
    assert "[LLM 调用异常]" in result.final_answer
    assert (
        "事实:" in result.final_answer
        and "原因:" in result.final_answer
        and "建议:" in result.final_answer
    )
    assert "检查网络/Key/模型名配置后重试" in result.final_answer
    # b) exception_log 落盘
    log = engine.settings.audit_dir / "exception_log.jsonl"
    if log.exists():
        assert "LLMError" in log.read_text(encoding="utf-8")


def test_llm_error_type_matrix_injected(build_test_engine, monkeypatch):
    """A4: LLM 错误类型矩阵——网络/超时/HTTP 4xx/HTTP 5xx/协议 各类型注入.

    每类错误 → 引擎循环内如实三件套反馈（[LLM 调用异常] + 事实/原因/建议），
    不抛穿（正常返回 LoopResult），错误类型名如实呈现（不伪造/不吞并）。
    """
    from llm_loop.llm.errors import (
        LLMHTTPError,
        LLMNetworkError,
        LLMProtocolError,
        LLMTimeoutError,
    )

    cases = [
        (LLMNetworkError("connection refused"), "LLMNetworkError"),
        (LLMTimeoutError("timeout after 120s"), "LLMTimeoutError"),
        (LLMHTTPError("403 Forbidden", status_code=403), "LLMHTTPError"),
        (LLMHTTPError("500 Internal Server Error", status_code=500), "LLMHTTPError"),
        (LLMProtocolError("malformed response"), "LLMProtocolError"),
    ]
    for err, type_name in cases:
        engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
        monkeypatch.setattr(
            fake, "chat", lambda *a, _e=err, **k: (_ for _ in ()).throw(_e)
        )
        sid = engine.session.create()
        result = engine.run(sid, "你好")
        # 不抛穿 + 三件套 + 错误类型如实呈现
        assert result.final_answer, type_name
        assert "[LLM 调用异常]" in result.final_answer, type_name
        assert "事实:" in result.final_answer, type_name
        assert "原因:" in result.final_answer, type_name
        assert "建议:" in result.final_answer, type_name
        assert type_name in result.final_answer, type_name
        assert "检查网络/Key/模型名配置后重试" in result.final_answer, type_name
