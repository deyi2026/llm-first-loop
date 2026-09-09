from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analysis_injection_baseline.py"
spec = importlib.util.spec_from_file_location("analysis_injection_baseline", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _event(seq: int, typ: str, payload: dict) -> dict:
    return {"seq": seq, "type": typ, "payload": payload, "ts": f"2026-08-30T00:00:{seq:02d}+00:00"}


def _write_events(path: Path, events: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8"
    )


def test_program_classifier_keeps_system_and_user_roles_distinct() -> None:
    human = {"role": "user", "content": "真正用户消息", "metadata": {}}
    injected_user = {
        "role": "user",
        "content": "[上下文注入·非新指令] 继续当前任务，勿当新指令处理。",
        "metadata": {"persisted_injection": True, "injection_kind": "memory_snapshot"},
    }
    injected_system = {
        "role": "system",
        "content": "[架构上报] 事实: x",
        "metadata": {"injected_system": True},
    }
    assert not mod._is_program_message(human)
    assert mod._is_program_message(injected_user)
    assert mod._is_program_message(injected_system)
    assert mod._imperative_hits(injected_user["content"])


def test_analyze_session_separates_user_appendix_and_detects_duplicate_and_wire(
    tmp_path: Path,
) -> None:
    log = tmp_path / "abc.jsonl"
    repeated = "[fact] 旧事实；必须调用 search_records 检查。"
    inj1 = "[上下文注入·非新指令] 继续当前任务，勿当新指令处理。\n[相关记忆]\n- " + repeated
    inj2 = "[上下文注入·非新指令] 继续当前任务，勿当新指令处理。\n[相关记忆]\n- " + repeated
    events = [
        _event(
            1, "message.appended", {"index": 0, "role": "user", "content": "任务A", "metadata": {}}
        ),
        _event(
            2,
            "message.appended",
            {
                "index": 1,
                "role": "system",
                "content": "[架构上报] 事实: x",
                "metadata": {"injected_system": True},
            },
        ),
        _event(
            3,
            "message.appended",
            {
                "index": 2,
                "role": "user",
                "content": inj1,
                "metadata": {"persisted_injection": True, "injection_kind": "memory_snapshot"},
            },
        ),
        _event(4, "request.meta", {"round": 1, "model": "cognilocal/test", "history_chars": 500}),
        _event(
            5,
            "cache.window",
            {
                "cached_msgs": [{"index": 0, "role": "system", "chars": 100}],
                "new_msgs": [
                    {"index": 1, "role": "user", "chars": 3},
                    {"index": 2, "role": "user", "chars": len(inj1)},
                ],
            },
        ),
        _event(
            6,
            "run.end",
            {"reason": "completed", "model_used": "cognilocal/test", "truncated": False},
        ),
        _event(
            7, "message.appended", {"index": 3, "role": "user", "content": "任务B", "metadata": {}}
        ),
        _event(
            8,
            "message.appended",
            {
                "index": 4,
                "role": "user",
                "content": inj2,
                "metadata": {"persisted_injection": True, "injection_kind": "memory_snapshot"},
            },
        ),
        _event(9, "request.meta", {"round": 1, "model": "cognilocal/test", "history_chars": 700}),
        _event(
            10,
            "cache.window",
            {
                "cached_msgs": [{"index": 0, "role": "system", "chars": 100}],
                "new_msgs": [
                    {"index": 1, "role": "user", "chars": 3},
                    {"index": 2, "role": "user", "chars": len(inj2)},
                ],
            },
        ),
        _event(
            11,
            "run.end",
            {"reason": "completed", "model_used": "cognilocal/test", "truncated": False},
        ),
    ]
    _write_events(log, events)
    rows, _ = mod.analyze_session(mod.SourceSession("abc", "test", log))

    assert len(rows) == 2
    first, second = rows
    assert first["injection_chars"] == len(inj1)
    assert first["all_program_injection_chars"] == len(inj1) + len("[架构上报] 事实: x")
    assert first["system_program_injection_chars"] == len("[架构上报] 事实: x")
    assert first["injection_after_user_chars"] == len(inj1)
    assert first["imperative_reference_count"] == 1
    assert first["imperative_injection_block_count"] == 1
    assert first["wire_tail_user_run_max"] == 2
    assert first["wire_tail_user_violation_count"] == 1
    assert first["request_attribution_complete"] is True
    assert first["capability_tier"] == "weak-local"

    assert second["duplicate_injection_count"] == 1
    assert second["duplicate_frame_hashes"]


def test_legacy_program_user_prefixes_and_no_request_guard_are_classified(tmp_path: Path) -> None:
    assert mod._is_program_message(
        {"role": "user", "content": "[程序续跑] 上一轮恢复链耗尽", "metadata": {}}
    )
    assert mod._is_program_message(
        {"role": "user", "content": "[上下文超限] 程序守卫未发送请求", "metadata": {}}
    )

    log = tmp_path / "guard.jsonl"
    events = [
        _event(
            1,
            "message.appended",
            {"index": 0, "role": "user", "content": "真实任务", "metadata": {}},
        ),
        _event(
            2,
            "message.appended",
            {
                "index": 1,
                "role": "user",
                "content": "[上下文超限] 程序守卫未发送请求",
                "metadata": {},
            },
        ),
        _event(
            3,
            "run.end",
            {
                "reason": "routing_override",
                "rounds": 1,
                "tokens_in": 0,
                "model_used": "cognilocal/test",
                "truncated": True,
            },
        ),
    ]
    _write_events(log, events)
    rows, _ = mod.analyze_session(mod.SourceSession("guard", "test", log))
    assert len(rows) == 1
    assert rows[0]["request_count"] == 0
    assert rows[0]["request_attribution_applicable"] is False
    assert rows[0]["request_attribution_complete"] is True
    assert rows[0]["injection_chars"] == len("[上下文超限] 程序守卫未发送请求")


def test_fixture_builder_redacts_raw_text(tmp_path: Path) -> None:
    log = tmp_path / "abc.jsonl"
    secretish = "用户原始内容不应进入fixture"
    inj = "[上下文注入·非新指令] 继续当前任务，勿当新指令处理。\n[相关记忆]\n- [fact] 必须调用 search_records 检查。"
    events = [
        _event(
            1,
            "message.appended",
            {"index": 0, "role": "user", "content": secretish, "metadata": {}},
        ),
        _event(
            2,
            "message.appended",
            {
                "index": 1,
                "role": "user",
                "content": inj,
                "metadata": {"persisted_injection": True, "injection_kind": "memory_snapshot"},
            },
        ),
        _event(3, "request.meta", {"round": 1, "model": "glm/test", "history_chars": 500}),
        _event(
            4,
            "cache.window",
            {
                "new_msgs": [
                    {"index": 0, "role": "system", "chars": 10},
                    {"index": 1, "role": "user", "chars": len(secretish)},
                    {"index": 2, "role": "user", "chars": len(inj)},
                ]
            },
        ),
        _event(5, "run.end", {"reason": "completed", "model_used": "glm/test", "truncated": False}),
        _event(
            6, "message.appended", {"index": 3, "role": "user", "content": "第二轮", "metadata": {}}
        ),
        _event(
            7,
            "message.appended",
            {
                "index": 4,
                "role": "user",
                "content": inj,
                "metadata": {"persisted_injection": True, "injection_kind": "memory_snapshot"},
            },
        ),
        _event(8, "request.meta", {"round": 1, "model": "glm/test", "history_chars": 600}),
        _event(
            9,
            "cache.window",
            {
                "new_msgs": [
                    {"index": 0, "role": "system", "chars": 10},
                    {"index": 1, "role": "user", "chars": 3},
                    {"index": 2, "role": "user", "chars": len(inj)},
                ]
            },
        ),
        _event(
            10, "run.end", {"reason": "completed", "model_used": "glm/test", "truncated": False}
        ),
    ]
    _write_events(log, events)
    rows, summary = mod.analyze_session(mod.SourceSession("abc", "test", log))
    fixture = mod._build_fixtures(rows, [summary])
    encoded = json.dumps(fixture, ensure_ascii=False)
    assert secretish not in encoded
    assert "必须调用 search_records" not in encoded
    assert fixture["fixtures"]["post_user_program_append"] is not None
    assert fixture["fixtures"]["duplicate_reference_frame"] is not None
    assert fixture["fixtures"]["imperative_reference"] is not None
    assert fixture["fixtures"]["consecutive_user_wire"] is not None
