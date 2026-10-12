"""EVO-20260917-abdb3247 P0: 注入观测 ledger——零行为变化 + fail-open + 开关."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.tools.registry import (
    ToolResult,
    ToolResultStatus,
    tool_result_to_message,
)


@pytest.fixture(autouse=True)
def _reset_ledger_binding(monkeypatch):
    """顺序隔离：factory 构建路径会把 injection_ledger._LEDGER_PATH 钉到运行时
    audit 目录，该全局在 _resolved_path() 中遮蔽 INJECTION_LEDGER_PATH env 覆盖
    （全量套件顺序依赖根因）。逐例重置回 None，恢复 env 优先语义。"""
    from llm_loop.knowledge import injection_ledger

    monkeypatch.setattr(injection_ledger, "_LEDGER_PATH", None)


def _fail_result() -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content="[状态: failure] boom",
        tool_call_id="c1",
        tool_name="demo_tool",
    )


def _rows(tmp: Path) -> list[dict]:
    p = tmp / "injection_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_receipt_pointer_row_written_and_content_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("INJECTION_LEDGER_PATH", str(tmp_path / "injection_ledger.jsonl"))
    monkeypatch.delenv("KNOWLEDGE_INJECTION_LEDGER", raising=False)

    # 运行线 R8.24-C：引导模式经参数注入（不再读 LFL_TOOL_GUIDANCE env）
    with_ledger = tool_result_to_message(_fail_result(), tool_guidance_mode="on")
    rows = _rows(tmp_path)
    assert any(
        r.get("kind") == "receipt_pointer" and r.get("source") == "failure_guidance" for r in rows
    )

    # 开关关闭：正文逐字节一致，且不再新增行
    monkeypatch.setenv("KNOWLEDGE_INJECTION_LEDGER", "0")
    without = tool_result_to_message(_fail_result(), tool_guidance_mode="on")
    assert str(without.content) == str(with_ledger.content)
    assert len(_rows(tmp_path)) == 1


def test_guidance_off_mode_zero_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("INJECTION_LEDGER_PATH", str(tmp_path / "injection_ledger.jsonl"))
    msg = tool_result_to_message(_fail_result(), tool_guidance_mode="off")
    assert "RULE-AI-02/07" not in str(msg.content)
    assert _rows(tmp_path) == []


def test_ledger_io_error_fail_open(tmp_path, monkeypatch):
    # 路径指向目录 → 写失败 → 不冒泡、正文正常
    monkeypatch.setenv("INJECTION_LEDGER_PATH", str(tmp_path))
    msg = tool_result_to_message(_fail_result(), tool_guidance_mode="on")
    assert "RULE-AI-02/07" in str(msg.content)


def test_hydration_refs_and_session_id_fields(tmp_path, monkeypatch):
    """P1: hydration 行登记 refs（正文提取）与 session_id（run_context 缺省时为空串）."""
    from llm_loop.tools.registry import _observe_knowledge_hydration

    monkeypatch.setenv("INJECTION_LEDGER_PATH", str(tmp_path / "injection_ledger.jsonl"))
    call = SimpleNamespace(name="search_records", arguments={"kind": "experience", "query": "venv"})
    result = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        tool_name="search_records",
        content="命中卡片: experience:EXP-1 experience:EXP-1 method:m-2 无关文本",
    )
    _observe_knowledge_hydration(call, result)
    rows = [json.loads(line) for line in (tmp_path / "injection_ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "hydration"
    assert row["refs"] == ["experience:EXP-1", "method:m-2"]  # 去重 + 只取 ref 字面
    assert "session_id" in row  # 无 run_context 时为 ""（fail-open 归属缺失，归因跳过）


def test_hydration_rows(tmp_path, monkeypatch):
    from llm_loop.tools.registry import _observe_knowledge_hydration

    monkeypatch.setenv("INJECTION_LEDGER_PATH", str(tmp_path / "injection_ledger.jsonl"))
    call = SimpleNamespace(name="search_records", arguments={"kind": "rule", "query": "evidence discipline"})
    result = SimpleNamespace(status=SimpleNamespace(value="success"), tool_name="search_records")
    _observe_knowledge_hydration(call, result)

    call2 = SimpleNamespace(name="skill_load", arguments={"name": "notebook-session"})
    result2 = SimpleNamespace(status=SimpleNamespace(value="success"), tool_name="skill_load")
    _observe_knowledge_hydration(call2, result2)

    # 非成功状态不登记
    result3 = SimpleNamespace(status=SimpleNamespace(value="failure"), tool_name="search_records")
    _observe_knowledge_hydration(call, result3)

    rows = _rows(tmp_path)
    pairs = [(r.get("tool"), r.get("record_kind") or r.get("skill")) for r in rows]
    assert ("search_records", "rule") in pairs
    assert ("skill_load", "notebook-session") in pairs
    assert len(rows) == 2
