"""EVO-20260924-8266b693: service control 终态反馈三修复.

A: succeeded/failed 终态写 requester 会话统一事件流（service_action_terminal）。
B: failed 动作"待确认"语义——verify_acknowledge(accept) 置 acknowledged_at
   （不改判 succeeded）；开场状态提醒构造（STATUS 层）。
C: 受理回执文案（builtin 层，见既有工具测试；此处覆盖回执关键句）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.runtime.service_control import (
    ManagedServiceDeploymentStore,
    _emit_terminal_event,
    acknowledge_verify,
    scan_unacknowledged_failed_actions,
)


def _store_with_action(tmp_path: Path, *, status: str = "failed") -> tuple[
    ManagedServiceDeploymentStore, str
]:
    store = ManagedServiceDeploymentStore(tmp_path)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    action_id = "svc-e2e-001"
    (store.actions_dir / f"{action_id}.json").write_text(
        json.dumps(
            {
                "schema": "service-control-action/v1",
                "action_id": action_id,
                "action": "restart",
                "target": "web",
                "deployment_id": "deploy-90",
                "status": status,
                "deployment_generation": 90,
                "detail": "restart_mirror rc=0 but verify failed; verify=unhealthy",
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "requester_session_id": "11111111-2222-3333-4444-555555555555",
                "reason_ref": "r-ref",
            }
        ),
        encoding="utf-8",
    )
    return store, action_id


def test_terminal_event_written_to_requester_session_stream(tmp_path: Path) -> None:
    """A: failed 终态 → event_logs/<sid>.jsonl 出现 service_action_terminal."""
    store, action_id = _store_with_action(tmp_path, status="failed")
    action = store.read_action(action_id)
    assert action is not None
    _emit_terminal_event(store, action)

    sid = "11111111-2222-3333-4444-555555555555"
    stream = tmp_path / "event_logs" / f"{sid}.jsonl"
    assert stream.exists(), "终态事件未落流"
    events = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines()]
    hits = [e for e in events if e.get("type") == "service_action_terminal"]
    assert hits, "事件流中无 service_action_terminal"
    payload = hits[-1]["payload"]
    assert payload["action_id"] == action_id
    assert payload["status"] == "failed"
    assert payload["target"] == "web"


def test_terminal_event_fail_open_no_session(tmp_path: Path) -> None:
    """A: requester_session_id 缺失 → 不写事件流也不抛（fail-open）."""
    store, action_id = _store_with_action(tmp_path)
    action = store.read_action(action_id)
    assert action is not None
    import dataclasses

    action = store.read_action(action_id)
    assert action is not None
    sid_empty = dataclasses.replace(action, requester_session_id="")
    _emit_terminal_event(store, sid_empty)  # 不抛即通过
    assert not (tmp_path / "event_logs").exists() or not list(
        (tmp_path / "event_logs").glob("*.jsonl")
    )


def test_acknowledge_verify_accept_on_failed_marks_acknowledged(tmp_path: Path) -> None:
    """B: failed + accept → acknowledged_at 置位，状态保持 failed（不改判 succeeded）."""
    store, action_id = _store_with_action(tmp_path, status="failed")
    result = acknowledge_verify(
        store,
        action_id=action_id,
        verdict="accept",
        reason="已知，已被 gen91 接管恢复",
        evidence="service_control status gen=91",
        operator="model",
    )
    assert result["accepted"] is True
    action = store.read_action(action_id)
    assert action is not None
    assert action.status == "failed"
    assert action.acknowledged_at
    # 确认后不再占扫描投影
    assert scan_unacknowledged_failed_actions(tmp_path) == []


def test_opening_notice_status_layer_and_bounded(tmp_path: Path) -> None:
    """B: 开场提醒构造——STATUS 层、含 action_id/接管标注、无正文投喂."""
    from llm_loop.core.loop.engine_services.service_action_notice import (
        build_failed_action_notice_message,
    )

    _store_with_action(tmp_path, status="failed")
    msg = build_failed_action_notice_message(str(tmp_path))
    assert msg is not None
    assert msg.role == "user"
    meta = msg.metadata or {}
    assert meta.get("origin_layer") == "status"
    assert meta.get("program_origin") is True
    assert meta.get("injection_kind") == "service_action_notice"
    assert "svc-e2e-001" in msg.content
    assert "未接管" in msg.content or "已被新代接管" in msg.content
    # 无 failed 动作 → 不注入
    empty_dir = tmp_path / "empty-data"
    empty_dir.mkdir()
    assert build_failed_action_notice_message(str(empty_dir)) is None
    # data_dir 为空 → 不注入
    assert build_failed_action_notice_message(None) is None


def test_acceptance_receipt_copy_mentions_terminal_check(tmp_path: Path) -> None:
    """C: 受理回执关键句（受理≠完成 + 终态核对入口）在工具描述/回执文本面存在."""
    import inspect

    from llm_loop.tools.builtin import service_control as builtin_sc

    src = inspect.getsource(builtin_sc)
    assert "受理≠完成" in src
    assert "service_action_terminal" in src
    assert "verify_acknowledge" in src


def test_engine_opening_notice_once_per_session(
    monkeypatch, fake_settings, build_test_engine
) -> None:
    """B: 开场接线——首 human turn 注入一次（用户原文之前），次 turn 不重复."""
    import llm_loop.runtime.service_control as sc_mod
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setattr(
        sc_mod,
        "scan_unacknowledged_failed_actions",
        lambda data_dir: [
            {
                "action_id": "svc-x",
                "target": "web",
                "generation": 90,
                "updated_at": "2026-09-24T01:00:00+00:00",
                "detail": "verify=unhealthy",
                "superseded": True,
            }
        ],
    )
    engine, _fake = build_test_engine(
        [LLMResponse(content="好的", tool_calls=[], provider="fake")] * 2
    )
    sid = engine.session.create()
    engine.run(sid, "你好")
    sess = engine.session.load(sid)
    opening_notices = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "service_action_notice"
    ]
    assert len(opening_notices) == 1, "首个 human turn 应注入一次开场状态提醒"
    user_positions = [
        i for i, m in enumerate(sess.messages) if m.content == "你好" and m.role == "user"
    ]
    notice_idx = sess.messages.index(opening_notices[0])
    assert notice_idx < user_positions[0], "提醒必须位于用户原文之前（L2 尾位不变量）"

    engine.run(sid, "第二句")
    sess = engine.session.load(sid)
    assert (
        len(
            [
                m
                for m in sess.messages
                if (m.metadata or {}).get("injection_kind") == "service_action_notice"
            ]
        )
        == 1
    ), "同 session 第二个 turn 不重复注入"
