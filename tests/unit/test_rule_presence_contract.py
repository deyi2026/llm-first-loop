"""rule_presence 契约与不变量回归（INV-1~INV-9 + 枚举/文案/落点/盘点器）.

覆盖 spec AC-8/AC-9/AC-10/AC-17；对齐 tasks 6.1。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.prompt import _BASE_PROMPT, build_system_prompt
from llm_loop.introspection.registry_introspection import _SEARCH_RECORDS_TOOL_DEF
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.builtin.convergence_decide import ConvergenceDecideTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS
from llm_loop.core.message import ToolCall
from tests.unit.test_err1210_recovery import _mk

_ROOT = Path(__file__).resolve().parents[2]
_LEDGER_MD = _ROOT / ".codeartsdoer" / "specs" / "rule_presence" / "rule-presence-ledger.md"

_BASELINE_SEARCH_RECORDS_COMPACT = 390
_SLIM_PREFIX_HASH_12 = "8934d96c3f25"

_TOOL = ConvergenceDecideTool()
_PARAMS = _TOOL.parameters


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


def test_conclude_releases_boundary_and_reopens_normal_tool_surface(tmp_path, monkeypatch) -> None:
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _conclude_resp("decision-conclude"),
            LLMResponse(content="收口后的回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    result = engine.run(sid, "真实任务")
    assert result.final_answer == "收口后的回答"
    assert _tool_names(fake.calls[3]) == ["convergence_decide"]
    assert "read_file" in _tool_names(fake.calls[4])
    assert "convergence_decide" not in _tool_names(fake.calls[4])


def test_conclude_records_declaration_only_in_action_trace(tmp_path, monkeypatch) -> None:
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[
            _read_resp("c1"),
            _read_resp("c2"),
            _read_resp("c3"),
            _conclude_resp("decision-conclude"),
            LLMResponse(content="收口后的回答", tool_calls=[], provider="fake"),
        ],
    )
    _capture_tools(fake)
    sid = engine.session.create()
    engine.run(sid, "真实任务")
    trace = json.dumps(engine.status.snapshot().get("action_trace", []), ensure_ascii=False)
    assert "conclude" in trace
    for banned in ("completed", "succeeded", "任务完成"):
        assert banned not in trace


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


def test_ledger_covers_all_sot_rules() -> None:
    sot = (_ROOT / "docs" / "ai_rules.md").read_text(encoding="utf-8")
    refs = sorted(set(re.findall(r"RULE-AI-\d{2}", sot)), key=lambda r: int(r.split("-")[-1]))
    assert refs
    ledger = _LEDGER_MD.read_text(encoding="utf-8")
    missing = [ref for ref in refs if ref not in ledger]
    assert missing == []