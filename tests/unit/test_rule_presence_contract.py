"""rule_presence 契约与不变量回归（INV-1~INV-9 + 枚举/文案/落点/盘点器）.

覆盖 spec AC-8/AC-9/AC-10/AC-17；对齐 tasks 6.1。
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.prompt import _BASE_PROMPT, build_system_prompt
from llm_loop.introspection.registry_introspection import _SEARCH_RECORDS_TOOL_DEF
from llm_loop.introspection.tools_model import MODEL_CATALOG_TOOL_DEF
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.builtin.convergence_decide import ConvergenceDecideTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS
from tests.unit.test_err1210_recovery import _mk

_ROOT = Path(__file__).resolve().parents[2]
_LEDGER_MD = _ROOT / ".codeartsdoer" / "specs" / "rule_presence" / "rule-presence-ledger.md"
_LEDGER_AVAILABLE = _LEDGER_MD.is_file()  # 账本为内部治理文档，开源仓库不含（同 test_docs_sync specs 口径）

_BASELINE_SEARCH_RECORDS_COMPACT = 390
_SLIM_PREFIX_HASH_12 = "5aeea16c7677"  # SOUL.MD 前置逐字钉入(1117 chars, 用户指令 2026-10-09); 前值 55cd98cf0928(645, EVO-20261009-0ffcaad8); 更早 66b4523a06e7(547, EVO-20261003-8b053766)

_TOOL = ConvergenceDecideTool()
_PARAMS = _TOOL.parameters

_RULE_HEADING_RE = re.compile(r"^## .*?(RULE-AI-\d{2})", re.MULTILINE)


def _load_audit():
    name = "rule_presence_audit"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _sot_rule_refs(sot: str) -> list[str]:
    """只枚举 SoT 正式规则标题；正文引用/编号空缺说明不属于规则定义。"""
    return sorted(set(_RULE_HEADING_RE.findall(sot)), key=lambda r: int(r.split("-")[-1]))


def _tool_names(call: dict) -> list[str]:
    out: list[str] = []
    for item in call.get("tools") or []:
        if isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))
            continue
        fn = item.get("function") if isinstance(item, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            out.append(str(fn["name"]))
    return out


def _capture_tools(fake) -> None:
    original = fake.chat

    def _chat(messages, tools, **kwargs):
        result = original(messages, tools, **kwargs)
        fake.calls[-1]["tools"] = tools
        return result

    fake.chat = _chat


def _read_resp(call_id: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="read_file",
                arguments={"path": "/nonexistent/rule-presence-target"},
            )
        ],
        provider="fake",
    )


def _conclude_resp(call_id: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="convergence_decide",
                arguments={"decision": "conclude"},
            )
        ],
        provider="fake",
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ── 枚举与异常映射 ──


def test_decision_enum_accepts_conclude() -> None:
    enum = _PARAMS["properties"]["decision"]["enum"]
    assert enum == ["continue", "conclude"]


def test_continue_requires_unresolved_and_conclude_allows_empty() -> None:
    assert _PARAMS["required"] == ["decision"]
    assert _TOOL.execute(decision="continue", unresolved="").status == ToolResultStatus.FAILURE
    assert _TOOL.execute(decision="continue", unresolved="仍有事实").status == ToolResultStatus.SUCCESS
    assert _TOOL.execute(decision="conclude").status == ToolResultStatus.SUCCESS


def test_decision_enum_rejects_unknown_value() -> None:
    result = _TOOL.execute(decision="stop")
    assert result.status == ToolResultStatus.FAILURE
    assert "continue|conclude" in result.content


# ── INV-1 / INV-2 / INV-5：conclude 零状态变更与非完成裁决 ──


def test_conclude_does_not_mutate_goal_task_session_state(tmp_path) -> None:
    from llm_loop.introspection.goal import GoalStore

    GoalStore(str(tmp_path)).create("目标", session_id="s1")
    before = _snapshot(tmp_path)
    assert _TOOL.execute(decision="conclude").status == ToolResultStatus.SUCCESS
    assert _TOOL.execute(decision="continue", unresolved="u").status == ToolResultStatus.SUCCESS
    assert _snapshot(tmp_path) == before


def test_conclude_receipt_has_no_completion_verdict_words() -> None:
    content = _TOOL.execute(decision="conclude").content
    for banned in ("任务完成", "completed", "succeeded"):
        assert banned not in content
    assert "非完成裁决" in content


def test_conclude_receipt_avoids_boundary_wire_tokens() -> None:
    content = _TOOL.execute(decision="conclude").content
    assert "收敛边界" not in content
    assert "convergence.boundary" not in content


# ── INV-3 / INV-4 / INV-9：边界释放、自陈记录、非边界轮隐藏 ──


def test_repeated_calls_do_not_replace_real_tool_surface(tmp_path, monkeypatch) -> None:
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            LLMResponse(content="直接收口", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "直接收口"
    assert "read_file" in _tool_names(fake.calls[3])
    assert "convergence_decide" not in _tool_names(fake.calls[3])


def test_default_test_engine_does_not_register_convergence_meta_router(tmp_path, monkeypatch) -> None:
    engine, _fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[LLMResponse(content="done", tool_calls=[], provider="fake")],
    )
    assert "convergence_decide" not in engine.registry.names()


def test_non_boundary_round_hides_convergence_decide(tmp_path, monkeypatch) -> None:
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[LLMResponse(content="done", tool_calls=[], provider="fake")],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "任务")
    assert result.final_answer == "done"
    assert "convergence_decide" not in _tool_names(fake.calls[0])


# ── INV-6 / INV-7 / INV-8：prompt 与契约预算 ──


def test_base_prompt_bytes_unchanged() -> None:
    digest = hashlib.sha256(_BASE_PROMPT.encode("utf-8")).hexdigest()[:12]
    assert digest == _SLIM_PREFIX_HASH_12
    assert build_system_prompt("ignored-policy") == _BASE_PROMPT


def test_search_records_compact_retains_rule_ai_and_budget() -> None:
    compact = _COMPACT_TOOL_DESCRIPTIONS["search_records"]
    assert "RULE-AI" in compact
    assert len(compact) - _BASELINE_SEARCH_RECORDS_COMPACT <= 80


def test_convergence_decide_compact_description_length_bound() -> None:
    compact = ConvergenceDecideTool.compact_description
    assert len(compact) <= 160
    assert compact[:160] == compact


def test_convergence_decide_description_length_bound() -> None:
    assert len(ConvergenceDecideTool.description) <= 160


# ── G1 文案边界 / G2 落点 ──


def test_contract_text_has_no_mandate_words_and_no_rule_body() -> None:
    for text in (ConvergenceDecideTool.description, ConvergenceDecideTool.compact_description):
        for banned in ("必须", "禁止", "严禁", "必读"):
            assert banned not in text
        assert re.search(r"RULE-AI-\d\d", text) is None


def test_search_records_contract_carries_timing_semantics() -> None:
    full = _SEARCH_RECORDS_TOOL_DEF["description"]
    compact = _COMPACT_TOOL_DESCRIPTIONS["search_records"]
    assert "按需" in full and "非每轮强制" in full and "不强制检索顺序" in full
    assert "RULE-AI" in full
    assert "非每轮强制" in compact and "不强制顺序" in compact
    for text in (full, compact):
        # 2026-10-17 F 批集成：对齐 main 演进措辞的语义不变量（原分支字面断言过度耦合措辞）
        assert "≤2类" in text
        assert "每类≤5" in text
        assert "同一任务窗口" in text


def test_rule31_discovery_contract_reaches_first_provider_packet(build_test_engine) -> None:
    """Use the full test assembly, not the two-tool ERR1210 fixture."""
    engine, fake = build_test_engine(
        [LLMResponse(content="已收到任务", tool_calls=[], provider="fake")]
    )
    session_id = engine.session.create()
    engine.run(session_id, "排查多步工具调用和方法检索问题")
    assert fake.calls
    first = fake.calls[0]
    schemas = first["tools"]
    assert {"search_records", "method_manage", "save_experience", "refine_experience"}.issubset(
        _tool_names(first)
    )
    search_schema = next(
        item if item.get("name") == "search_records" else item["function"]
        for item in schemas
        if item.get("name") == "search_records"
        or item.get("function", {}).get("name") == "search_records"
    )
    assert "≤2类" in search_schema["description"]
    assert "同一任务窗口" in search_schema["description"]
    assert "每类≤5" in search_schema["description"]
    assert any(
        "学习与成长" in str(message.get("content", ""))
        for message in first["messages"]
        if isinstance(message, dict) and message.get("role") == "system"
    )


def test_rule31_bounded_discovery_reaches_full_lazy_and_first_model_tool_packet(
    tmp_path, monkeypatch
) -> None:
    """The actual FakeLLM first call must see bounded, non-coercive knowledge discovery."""
    from llm_loop.tools.registry import ToolRegistry

    class SearchRecordsStub:
        name = "search_records"
        description = _SEARCH_RECORDS_TOOL_DEF["description"]
        parameters = _SEARCH_RECORDS_TOOL_DEF["parameters"]

    expected = ("method", "experience", "lesson", "≤2类", "每类≤5", "同一任务窗口", "简单")
    registry = ToolRegistry()
    registry.register(SearchRecordsStub())
    for lazy in (False, True):
        tool = next(row for row in registry.schemas(lazy=lazy) if row["name"] == "search_records")
        assert all(part in tool["description"] for part in expected)
        assert set(("method", "experience", "lesson", "rule")) <= set(
            tool["parameters"]["properties"]["kind"]["enum"]
        )

    engine, fake = _mk(
        tmp_path, monkeypatch,
        responses=[LLMResponse(content="完成", tool_calls=[], provider="fake")],
    )
    engine.registry.register(SearchRecordsStub())
    _capture_tools(fake)
    result = engine.run(engine.session.create(), "需要排障和有界检索的多步骤任务")
    assert result.final_answer == "完成"
    assert fake.calls
    first_tools = fake.calls[0]["tools"]
    tool = next(
        (row.get("function") or row)
        for row in first_tools
        if (row.get("function") or row).get("name") == "search_records"
    )
    assert all(part in tool["description"] for part in expected)
    assert "method" in tool["parameters"]["properties"]["kind"]["enum"]


def test_rule31_bounded_discovery_reaches_full_lazy_and_first_model_tool_packet(
    tmp_path, monkeypatch
) -> None:
    """The actual FakeLLM first call must see bounded, non-coercive knowledge discovery."""
    from llm_loop.tools.registry import ToolRegistry

    class SearchRecordsStub:
        name = "search_records"
        description = _SEARCH_RECORDS_TOOL_DEF["description"]
        parameters = _SEARCH_RECORDS_TOOL_DEF["parameters"]

    expected = ("method", "experience", "lesson", "≤2类", "每类≤5", "同一任务窗口", "简单")
    registry = ToolRegistry()
    registry.register(SearchRecordsStub())
    for lazy in (False, True):
        tool = next(row for row in registry.schemas(lazy=lazy) if row["name"] == "search_records")
        assert all(part in tool["description"] for part in expected)
        assert set(("method", "experience", "lesson", "rule")) <= set(
            tool["parameters"]["properties"]["kind"]["enum"]
        )

    engine, fake = _mk(
        tmp_path, monkeypatch,
        responses=[LLMResponse(content="完成", tool_calls=[], provider="fake")],
    )
    engine.registry.register(SearchRecordsStub())
    _capture_tools(fake)
    result = engine.run(engine.session.create(), "需要排障和有界检索的多步骤任务")
    assert result.final_answer == "完成"
    assert fake.calls
    first_tools = fake.calls[0]["tools"]
    tool = next(
        (row.get("function") or row)
        for row in first_tools
        if (row.get("function") or row).get("name") == "search_records"
    )
    assert all(part in tool["description"] for part in expected)
    assert "method" in tool["parameters"]["properties"]["kind"]["enum"]


def test_model_catalog_contract_is_identity_verification_entrypoint_without_prompt_growth() -> None:
    full = MODEL_CATALOG_TOOL_DEF["description"]
    compact = _COMPACT_TOOL_DESCRIPTIONS["model_catalog"]
    for text in (full, compact):
        assert "当前模型" in text
        assert "身份" in text
    assert "路由标签" in full and "外层宿主/网页模型" in full
    assert "外层网页模型身份" in compact
    # Identity guidance belongs in the tool contract, not another universal-prompt rule copy.
    assert build_system_prompt() == _BASE_PROMPT


# ── 盘点器（只读 / 确定性 / 不可判定 / 台账覆盖） ──


def test_audit_inventory_is_read_only_and_deterministic() -> None:
    audit = _load_audit()
    watched = [_ROOT / "docs" / "ai_rules.md", _ROOT / "src" / "llm_loop" / "core" / "prompt.py"]
    before = {str(p): p.read_bytes() for p in watched}
    first = audit.inventory(generated_at="2026-09-22T00:00:00")
    second = audit.inventory(generated_at="2026-09-22T00:00:00")
    assert first == second
    assert {str(p): p.read_bytes() for p in watched} == before


def test_audit_marks_undeterminable() -> None:
    audit = _load_audit()
    report = audit.inventory(base_prompt=None, generated_at="2026-09-22T00:00:00")
    assert report.base_prompt_hash == "无法判定"
    assert report.records
    assert all(r.determinacy == "无法判定" for r in report.records)
    assert all(v == "无法判定" for v in audit.slimming_gate_status(None).values())


@pytest.mark.skipif(not _LEDGER_AVAILABLE, reason="rule-presence 账本为内部治理文档，开源仓库不含（同 test_docs_sync specs 口径）")
def test_ledger_covers_all_sot_rules() -> None:
    sot = (_ROOT / "docs" / "ai_rules.md").read_text(encoding="utf-8")
    refs = _sot_rule_refs(sot)
    assert refs
    ledger = _LEDGER_MD.read_text(encoding="utf-8")
    # Inventory header and narrative references are not formal Rule rows.
    rows = re.findall(r"^\| (RULE-AI-\d{2}) \|", ledger, re.MULTILINE)
    assert len(rows) == len(set(rows))
    missing = [ref for ref in refs if ref not in rows]
    assert missing == []
    report = _load_audit().inventory(generated_at="2026-10-15")
    inventory_header = re.search(r"^\| `records` \| (\d+)", ledger, re.MULTILINE)
    assert inventory_header is not None
    assert int(inventory_header.group(1)) == len(report.records)


def test_sot_rule_refs_ignore_body_mentions_and_gap_notes() -> None:
    refs = _sot_rule_refs(
        "\n".join(
            [
                "## 规则二十：正式规则（RULE-AI-20，示例）",
                "正文引用 RULE-AI-19 不应新增规则。",
                "**编号空缺说明（RULE-AI-21）**：该号未进入 SoT。",
                "## 规则二十二：正式规则（RULE-AI-22，示例）",
            ]
        )
    )
    assert refs == ["RULE-AI-20", "RULE-AI-22"]
