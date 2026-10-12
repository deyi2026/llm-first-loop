"""P2-A Rule-first integration: repetition is observable, never a generic tool blocker."""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.message import ToolCall


def _tc(i: int, path: Path) -> ToolCall:
    return ToolCall(id=f"c{i}", name="read_file", arguments={"path": str(path)})


def _read_audit(engine) -> list[dict]:
    audit_dir = engine.status._audit_dir  # noqa: SLF001 -- test reads assembled audit surface
    path = Path(audit_dir) / "action_trace.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_five_identical_read_calls_all_execute(build_test_engine, tmp_path):
    probe = tmp_path / "repeat-observation-probe.txt"
    probe.write_text("repeat probe\n", encoding="utf-8")
    engine, _fake = build_test_engine(
        [
            {"content": "", "tool_calls": [_tc(i, probe)]}
            for i in range(1, 6)
        ]
        + [{"content": "done", "tool_calls": []}]
    )
    sid = engine.session.create()
    result = engine.run(sid, "连续读取同一文件五次，然后结束")

    msgs = engine.session.load(sid).messages
    by_id = {m.tool_call_id: m for m in msgs if m.role == "tool" and m.tool_call_id}
    assert set(by_id) == {"c1", "c2", "c3", "c4", "c5"}
    assert all("[同参熔断]" not in m.content for m in by_id.values())
    assert all(getattr(m.status, "value", "") != "blocked" for m in by_id.values())
    assert result.final_answer == "done"

    rows = _read_audit(engine)
    repeat = [r for r in rows if r.get("phase") == "tool.repeat_observed"]
    assert len(repeat) == 1
    assert repeat[0].get("action_type") == "observed"
    assert "exact_call_count=3" in repeat[0].get("detail", "")
    assert not [r for r in rows if str(r.get("phase", "")).startswith("duplicate.")]
    assert not [r for r in rows if r.get("phase") == "stagnation.break"]
    assert not [r for r in rows if str(r.get("phase", "")).startswith("no_progress.")]


def test_repeated_calls_preserve_declaration_receipt_pairing(build_test_engine, tmp_path):
    probe = tmp_path / "pairing-probe.txt"
    probe.write_text("pairing probe\n", encoding="utf-8")
    engine, _fake = build_test_engine(
        [
            {"content": "", "tool_calls": [_tc(i, probe)]}
            for i in range(1, 5)
        ]
        + [{"content": "done", "tool_calls": []}]
    )
    sid = engine.session.create()
    engine.run(sid, "重复调用配对测试")
    msgs = engine.session.load(sid).messages
    declared = {
        tc["id"] for m in msgs if m.role == "assistant" for tc in (m.tool_calls or [])
    }
    answered = {m.tool_call_id for m in msgs if m.role == "tool" and m.tool_call_id}
    assert declared == answered
