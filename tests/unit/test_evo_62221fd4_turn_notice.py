"""EVO-20260924-62221fd4: 后台动作失败终态的轮级注入（补全 v0.6.19 闭环最后一环）.

每个 human turn 检查**新出现**的未确认 failed 动作：
- 幂等：同一 action_id 本会话只注入一次（开场卡登记 + 轮卡增量）；
- 闭合即停：verify_acknowledge 后扫描不再返回 → 不再注入；
- ≤3 条硬上限；提示非指令。
"""

from __future__ import annotations

import llm_loop.runtime.service_control as sc_mod
from llm_loop.core.loop.engine_services.service_action_notice import (
    build_failed_action_turn_notice,
    injected_turn_action_ids,
)
from llm_loop.llm.client import LLMResponse


def _item(action_id: str, *, superseded: bool = False) -> dict:
    return {
        "action_id": action_id,
        "target": "web",
        "generation": 94,
        "updated_at": "2026-09-24T04:00:00+00:00",
        "detail": "deployment binding failed: git_head mismatch",
        "superseded": superseded,
    }


def test_builder_filters_injected_and_caps_three(monkeypatch) -> None:
    """构造器：过滤已注入 ids；新项超 3 条只取 3；无新项返回 None."""
    _pool = [_item(f"svc-{c}") for c in "abcde"]
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: _pool
    )
    cards = [
        build_failed_action_turn_notice("data", {"svc-a"}),
        build_failed_action_turn_notice("data", {"svc-a", "svc-b", "svc-c", "svc-d", "svc-e"}),
        build_failed_action_turn_notice(None, set()),
    ]
    ids0 = cards[0].metadata["service_action_ids"]
    assert ids0 == ["svc-b", "svc-c", "svc-d"], "已注入 svc-a 过滤 + 上限 3"
    assert "svc-a" not in cards[0].content and "svc-b" in cards[0].content
    assert (cards[0].metadata or {}).get("injection_kind") == "service_action_turn_notice"
    assert cards[1] is None, "全部已注入 → 不注入（幂等）"
    assert cards[2] is None, "无 data_dir → 不注入"


def test_builder_content_is_status_layer_non_imperative(monkeypatch) -> None:
    """STATUS 层渲染：程序附录仲裁句 + [通知·状态] 前缀 + 消费入口（非指令语义）."""
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: [_item("svc-z")]
    )
    msg = build_failed_action_turn_notice("data", set())
    assert msg.content.startswith("[程序附录·非用户输入]")
    assert "[通知·状态]" in msg.content
    assert "verify_acknowledge" in msg.content
    assert (msg.metadata or {}).get("origin_layer") == "status"


def test_engine_injects_turn_notice_before_user_text(
    monkeypatch, fake_settings, build_test_engine
) -> None:
    """轮级接线：第二轮出现新 failed → 一张轮卡置于该轮用户原文之前."""
    scan_results: list[list[dict]] = [[_item("svc-a")], [_item("svc-a"), _item("svc-new", superseded=True)]]
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: scan_results[0]
    )
    engine, _fake = build_test_engine(
        [LLMResponse(content="好的", tool_calls=[], provider="fake")] * 2
    )
    sid = engine.session.create()
    engine.run(sid, "第一轮")  # 开场卡注入 svc-a
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: scan_results[1]
    )
    engine.run(sid, "第二轮")  # svc-new 出现 → 轮卡（svc-a 已去重）

    sess = engine.session.load(sid)
    turn_cards = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "service_action_turn_notice"
    ]
    assert len(turn_cards) == 1, "第二轮恰注入一张轮卡"
    meta = turn_cards[0].metadata or {}
    assert meta.get("service_action_ids") == ["svc-new"], "只含新出现的 svc-new"
    idx = sess.messages.index(turn_cards[0])
    user_positions = [
        i for i, m in enumerate(sess.messages) if m.role == "user" and m.content == "第二轮"
    ]
    assert user_positions and idx < user_positions[0], "轮卡位于用户原文之前（L2 尾位）"


def test_engine_no_repeat_when_no_new_actions(
    monkeypatch, fake_settings, build_test_engine
) -> None:
    """幂等：扫描结果不变 → 两轮后仍只有开场卡，无轮卡."""
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: [_item("svc-a")]
    )
    engine, _fake = build_test_engine(
        [LLMResponse(content="好", tool_calls=[], provider="fake")] * 2
    )
    sid = engine.session.create()
    engine.run(sid, "第一轮")
    engine.run(sid, "第二轮")
    sess = engine.session.load(sid)
    turn_cards = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "service_action_turn_notice"
    ]
    assert turn_cards == [], "无新动作 → 不注入轮卡"
    opening = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "service_action_notice"
    ]
    assert len(opening) == 1
    assert injected_turn_action_ids(sess.messages) == {"svc-a"}


def test_engine_stops_after_acknowledge(
    monkeypatch, fake_settings, build_test_engine
) -> None:
    """闭合即停：第二轮扫描为空（已 acknowledge）→ 无轮卡."""
    results: dict[str, list[dict]] = {"r1": [_item("svc-a")], "r2": []}
    current = {"list": results["r1"]}
    monkeypatch.setattr(
        sc_mod, "scan_unacknowledged_failed_actions", lambda data_dir: current["list"]
    )
    engine, _fake = build_test_engine(
        [LLMResponse(content="好", tool_calls=[], provider="fake")] * 2
    )
    sid = engine.session.create()
    engine.run(sid, "第一轮")
    current["list"] = results["r2"]  # 模拟 verify_acknowledge 后扫描不返回
    engine.run(sid, "第二轮")
    sess = engine.session.load(sid)
    turn_cards = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "service_action_turn_notice"
    ]
    assert turn_cards == [], "闭合后不再注入"
