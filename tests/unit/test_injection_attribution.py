"""EVO-20260917-abdb3247 P1: A 级归因——窗口/跨 session/锚点前/skill 调用形/旧格式兼容."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "attribute_injection_usage.py"
_spec = importlib.util.spec_from_file_location("attribute_injection_usage", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _write_session(dirs: Path, sid: str, messages: list[dict]) -> None:
    d = dirs / "part"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({"session_id": sid, "messages": messages}), encoding="utf-8")


def _msg(role: str, ts: float, content: str = "", tool_calls: list[dict] | None = None) -> dict:
    m: dict = {"role": role, "content": content, "ts": ts}
    if tool_calls:
        m["tool_calls"] = [
            {"function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
            for name, args in tool_calls
        ]
    return m


def _rows(*items: dict) -> list[dict]:
    return [dict(r) for r in items]


def test_attribution_window_and_isolation(tmp_path):
    sid1, sid2 = "s-1111", "s-2222"
    _write_session(
        tmp_path,
        sid1,
        [
            _msg("user", 99.0, "任务"),
            _msg("assistant", 99.5, "水合前就引用了 experience:EXP-PRE", tool_calls=[("search_records", {"kind": "experience", "query": "pre"})]),
            _msg("tool", 100.0, "命中卡片: experience:EXP-1 | method:m-1"),
            _msg("assistant", 110.0, "以 experience:EXP-1 核对", tool_calls=[("read_evidence", {"evidence_ref": "evidence://v1/x"})]),
            _msg("assistant", 120.0, "结论：method:m-1 验证通过"),
        ],
    )
    _write_session(
        tmp_path,
        sid2,
        [
            _msg("tool", 101.0, "另一会话的回执，锚点后无 assistant 消息: experience:EXP-1"),
        ],
    )
    rows = _rows(
        {"kind": "hydration", "tool": "search_records", "status": "success", "ts": 100.2, "session_id": sid1,
         "refs": ["experience:EXP-1", "method:m-1"], "record_kind": "experience", "query": "q"},
        {"kind": "hydration", "tool": "search_records", "status": "success", "ts": 100.8, "session_id": sid2,
         "refs": ["experience:EXP-1"], "record_kind": "experience", "query": "q2"},
        {"kind": "hydration", "tool": "search_records", "status": "success", "ts": 99.3, "session_id": sid1,
         "refs": ["experience:EXP-PRE"], "record_kind": "experience", "query": "pre"},
    )
    report = mod.build_report(rows, tmp_path)
    per = report["per_ref"]
    # EXP-1：sid1 窗口内命中一次；sid2 无后续 → attributed=1 / hydrations=2
    assert per["experience:EXP-1"]["hydrations"] == 2
    assert per["experience:EXP-1"]["attributed"] == 1
    # m-1：content 字面引用命中
    assert per["method:m-1"]["attributed"] == 1
    # 水合【前】的引用不算（锚点之后才开窗）
    assert per["experience:EXP-PRE"]["attributed"] == 0
    assert report["summary"]["attributed_events"] == 1


def test_skill_call_scope_and_legacy_rows(tmp_path):
    sid = "s-3333"
    _write_session(
        tmp_path,
        sid,
        [
            _msg("tool", 200.0, "skill loaded ok"),
            _msg("assistant", 210.0, "按 skill 流程执行", tool_calls=[("skill_load", {"name": "notebook-session"})]),
            _msg("assistant", 220.0, "顺手提到 notebook-session 但仅是闲聊文本"),  # 文本提裸名不算 skill_call 命中
        ],
    )
    rows = _rows(
        {"kind": "hydration", "tool": "skill_load", "status": "success", "ts": 200.2, "session_id": sid, "skill": "notebook-session"},
        {"kind": "hydration", "tool": "search_records", "status": "success", "ts": 205.0,
         "refs": ["experience:LEGACY"], "record_kind": "experience", "query": "q"},  # 无 session_id（旧格式）
    )
    report = mod.build_report(rows, tmp_path)
    per = report["per_ref"]
    # skill 归因只认后续 skill_load 调用形；闲聊文本裸名不计
    assert per["skill:notebook-session"]["hydrations"] == 1
    assert per["skill:notebook-session"]["attributed"] == 1
    # 旧格式无 session：计 hydrations、不进窗口
    assert per["experience:LEGACY"]["hydrations"] == 1
    assert per["experience:LEGACY"]["attributed"] == 0
    assert report["summary"]["windowed_events"] == 1


def test_markdown_render_contains_grade_underest_window(tmp_path):
    report = mod.build_report(_rows(), tmp_path)
    md = mod.render_markdown(report, ledger="x.jsonl")
    assert "A 级" in md and "低估" in md and "窗口" in md
