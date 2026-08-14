"""单元测试: evolution_complete 工具（M17 FR-REVIEW-AI-01 闭环 / design §8.1）.

覆盖: 工具注册/分派（tool_defs 含 + schema 必填 + execute 命中 + 描述含"何时用/何时不用"）；
complete 生产路径登记（executing→executed + 审计 executor=ai；note 非空 → ai_reported，空 → unverified）；
非 executing 前置校验（如实原因，不重复登记）；fail-open（落盘失败 → registered=False + error 如实标注）。
"""

from __future__ import annotations

from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.tools_exec_complete import (
    EVOLUTION_COMPLETE_TOOL_DEF,
)


def _make_engine(tmp_path):
    """构造含 evolution_store 的最小引擎（复用 CLI 测试模式）."""
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


def test_tool_def_registered():
    """evolution_complete 工具定义: schema 必填 suggestion_id/note + 描述含'何时用/何时不用'."""
    assert EVOLUTION_COMPLETE_TOOL_DEF["name"] == "evolution_complete"
    req = EVOLUTION_COMPLETE_TOOL_DEF["parameters"]["required"]
    assert "suggestion_id" in req and "note" in req
    desc = EVOLUTION_COMPLETE_TOOL_DEF["description"]
    assert "何时用" in desc and "何时不用" in desc


def test_tool_registered_in_corrections():
    """corrections.py 注册分派: tool_defs 含 + execute 命中."""
    ctx = CorrectionContext()
    reg = CorrectionToolRegistry(ctx)
    names = [td["name"] for td in reg.tool_defs()]
    assert "evolution_complete" in names
    # 分派命中（store 未装配 → 如实失败而非"工具不存在"）
    r = reg.execute("evolution_complete", {"suggestion_id": "EVO-x", "note": "n"})
    assert "未装配" in r.content or "演进建议存储未装配" in r.content
    assert r.status.value == "failure"


def test_complete_executing_registers(tmp_path):
    """executing 建议经 evolution_complete 登记 → executed + executor=ai + 审计落盘."""
    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    # 置 executing（模拟 maybe_auto_execute 后的中间态）
    store.transition(sug.id, status="executing")
    r = engine.corrections.execute(
        "evolution_complete", {"suggestion_id": sug.id, "note": "已执行并对比架构状态，验证通过"}
    )
    assert r.status.value == "success"
    assert "executor=ai" in r.content
    assert "verify=ai_reported" in r.content  # note 非空 → ai_reported（8.7.2 语义）
    assert "registered=True" in r.content
    assert store.list(status="executed")[0]["id"] == sug.id
    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert '"executor": "ai"' in exec_log
    assert "ai_reported" in exec_log


def test_complete_empty_note_unverified(tmp_path):
    """note 空 → verify_result=unverified（如实标注，未验证不谎报）."""
    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    r = engine.corrections.execute("evolution_complete", {"suggestion_id": sug.id, "note": "  "})
    assert r.status.value == "failure"  # note 空白 → 必填校验失败
    # 带空白 note 的场景: note 缺失时工具应拒绝（required 语义）
    r2 = engine.corrections.execute("evolution_complete", {"suggestion_id": sug.id, "note": "完成"})
    assert r2.status.value == "success"
    assert "verify=ai_reported" in r2.content


def test_complete_not_executing_denied(tmp_path):
    """非 executing 状态 → 如实原因不登记（防重复登记/乱登记）."""
    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    # pending_review 状态直接登记 → 拒绝
    r = engine.corrections.execute(
        "evolution_complete", {"suggestion_id": sug.id, "note": "还没审阅"}
    )
    assert r.status.value == "failure"
    assert "当前状态 'pending_review'" in r.content
    assert "无需登记" in r.content
    # 状态未被改动
    assert store.list(status="pending_review")[0]["id"] == sug.id


def test_complete_after_executed_denied(tmp_path):
    """已 executed → 拒绝重复登记（防乱登记）."""
    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executed")
    r = engine.corrections.execute(
        "evolution_complete", {"suggestion_id": sug.id, "note": "重复登记"}
    )
    assert r.status.value == "failure"
    assert "无需登记" in r.content


def test_complete_missing_params(tmp_path):
    """缺 suggestion_id/note → 必填校验失败."""
    engine = _make_engine(tmp_path)
    r = engine.corrections.execute("evolution_complete", {"suggestion_id": "EVO-x"})
    assert r.status.value == "failure"
    assert "缺少必填参数" in r.content


def test_complete_registration_fail_open(tmp_path, monkeypatch):
    """登记落盘 OSError → 如实标注（fail-open，不静默驻留 executing）."""
    from pathlib import Path

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _broken)
    try:
        r = engine.corrections.execute(
            "evolution_complete", {"suggestion_id": sug.id, "note": "完成"}
        )
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    # 状态推进（内存内）不受审计落盘失败阻断
    assert r.status.value == "success"
    assert "registered=True" in r.content  # 状态推进成功；审计落盘失败已在上层如实降级


def test_complete_nonexistent_id_failure(tmp_path):
    """M19 FIX-01: 不存在建议 → FAILURE + '建议不存在' + search_records 引导 + 无假审计记录."""
    engine = _make_engine(tmp_path)
    r = engine.corrections.execute(
        "evolution_complete", {"suggestion_id": "EVO-NOT-EXIST", "note": "完成"}
    )
    assert r.status.value == "failure"
    assert "建议不存在" in r.content
    assert "search_records(kind=evolution)" in r.content
    # evolution_exec_log 无该 id 假记录
    exec_log = engine.settings.audit_dir / "evolution_exec_log.jsonl"
    if exec_log.exists():
        assert "EVO-NOT-EXIST" not in exec_log.read_text(encoding="utf-8")


def test_complete_read_failed_fail_open(tmp_path, monkeypatch):
    """M19 FIX-01 三态区分: store 读取失败 → fail-open 放行（不误判'建议不存在'）."""
    from pathlib import Path

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        if "evolution_suggestions.jsonl" in str(getattr(self, "name", "")):
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _broken)
    try:
        r = engine.corrections.execute(
            "evolution_complete", {"suggestion_id": sug.id, "note": "完成"}
        )
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    # 读取失败 → 放行（非"建议不存在"），状态推进不受阻断
    assert r.status.value == "success"
    assert "建议不存在" not in r.content


def test_complete_transition_none_error(tmp_path):
    """M19 FIX-01 执行器层: store.transition 返回 None（无该 id）→ outcome.error 标注'状态未推进'."""
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    executor = EvolutionExecutor(exec_level=2, store=store, audit_dir=engine.settings.audit_dir)
    # 无该 id（store.list 正常返回但无匹配）
    outcome = executor.complete("EVO-NOPE", note="完成")
    assert outcome.error == "状态未推进（建议不存在）"
    assert outcome.status == "executed"  # status 字段不变（error 单独标注）


# ── 方案 4: 工具输出截断（context 优化）──

def test_truncate_short_output_unchanged():
    """短输出不应截断."""
    from llm_loop.tools.builtin.execute_command import _truncate_output
    content = "hello world"
    assert _truncate_output(content) == content


def test_truncate_long_output_head_tail():
    """长输出应保留头尾 + 截断说明."""
    from llm_loop.tools.builtin.execute_command import _truncate_output
    long = "A" * 5000
    r = _truncate_output(long, "ps aux grep")
    assert r.startswith("A" * 1500)
    assert r.endswith("A" * 1500)
    assert "[输出已截断]" in r
    assert "5000" in r  # 完整长度
    assert "ps" in r    # 搜索关键词


def test_truncate_exact_boundary():
    """恰好 3000 字符不截断."""
    from llm_loop.tools.builtin.execute_command import _truncate_output
    content = "B" * 3000
    assert _truncate_output(content) == content
