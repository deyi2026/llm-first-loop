"""Regression: first-view bounds must not masquerade as physical context limits.

All observations are synthetic and no Provider or source tool is executed.
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.engine_services.observation_visibility import (
    ensure_latest_observation_visible,
    group_visible_in_provider_view,
    latest_completed_tool_group,
)
from llm_loop.core.message import Message, MessageSource
from llm_loop.tools.registry import ToolRegistry


def _scenario(*, raw_sizes=(9307,), alter_arguments=False, omit_receipt=False):
    calls = [
        {
            "id": f"c{i}",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"source.txt"}'},
        }
        for i in range(len(raw_sizes))
    ]
    source = [
        Message(role="user", content="Summarize evidence", source=MessageSource.USER),
        Message(role="assistant", content="", source=MessageSource.SYSTEM, tool_calls=calls),
    ]
    for i, size in enumerate(raw_sizes):
        source.append(
            Message(
                role="tool",
                content=f"RAW_{i}:" + "x" * size,
                source=MessageSource.TOOL,
                tool_call_id=f"c{i}",
            )
        )
    provider_calls = [dict(call, function=dict(call["function"])) for call in calls]
    if alter_arguments:
        provider_calls[0]["function"]["arguments"] = '{"path":"other.txt"}'
    view = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "Summarize evidence", "_active_run_ingress_ref": "0"},
        {"role": "assistant", "content": "", "tool_calls": provider_calls},
    ]
    for i, _size in enumerate(raw_sizes):
        if omit_receipt and i == len(raw_sizes) - 1:
            continue
        view.append(
            {
                "role": "tool",
                "tool_call_id": f"c{i}",
                "content": f"[tool_result_bounded_first_view] RAW_{i}:" + "x" * 8192,
            }
        )
    events = []
    rebuild_calls = []

    def rebuild(*_args, **_kwargs):
        rebuild_calls.append(True)
        return SimpleNamespace(state="rebuilt", messages=tuple(view), projected_chars=30000)

    engine = SimpleNamespace(
        registry=ToolRegistry(),
        _build_conservative_active_run_messages=rebuild,
        _event_append=lambda _sid, name, payload: events.append((name, payload)),
        _record_action=lambda *_args: None,
    )
    return engine, SimpleNamespace(messages=source), view, events, rebuild_calls


def _check(engine, sess, view, *, budget=1000000, preflight=None):
    return ensure_latest_observation_visible(
        engine,
        sess,
        view,
        session_id="test-session",
        active_turn_ref=0,
        active_ingress_ref="0",
        effective_budget=budget,
        budget_info={"limited_by": "model_window"},
        request_preflight=preflight or (lambda *_args, **_kwargs: {"hard_overflow": False}),
        tools_param=[],
        chat_model_arg="glm-5.3",
        model="glm-5.3",
        planned_label="glm/glm-5.3",
        rounds=3,
    )


def test_bounded_latest_result_restores_raw_before_provider_send():
    engine, sess, view, events, rebuild_calls = _scenario()
    original = [dict(row) for row in view]
    result, hold = _check(engine, sess, view)
    assert hold == ""
    assert group_visible_in_provider_view(
        latest_completed_tool_group(sess.messages, 0), result, active_ingress_ref="0"
    )
    assert result[-1]["content"] == sess.messages[-1].content
    assert view == original, "provider projection must not mutate shared input"
    assert not rebuild_calls, "bounded result is already protocol-paired"
    assert any(event.get("action") == "raw_group_restored_from_session" for _, event in events)


def test_multi_tool_group_restores_all_results_atomically():
    engine, sess, view, _events, _rebuild_calls = _scenario(raw_sizes=(9307, 1400, 8048, 6282))
    result, hold = _check(engine, sess, view)
    assert hold == ""
    assert [row["content"] for row in result if row["role"] == "tool"] == [
        row.content for row in sess.messages if row.role == "tool"
    ]


def test_changed_call_arguments_must_not_restore_unrelated_observation():
    engine, sess, view, _events, rebuild_calls = _scenario(alter_arguments=True)
    result, hold = _check(engine, sess, view)
    assert hold == "context_capacity_unavailable"
    assert result == view
    assert rebuild_calls, "only a validated conservative rebuild can repair wrong arguments"


def test_incomplete_group_must_not_restore_partial_tool_observation():
    engine, sess, view, _events, _rebuild_calls = _scenario(
        raw_sizes=(9307, 1400), omit_receipt=True
    )
    result, hold = _check(engine, sess, view)
    assert hold == "context_capacity_unavailable"
    assert result == view


def test_real_physical_overflow_still_holds_without_authorized_exact_ref():
    engine, sess, view, _events, _rebuild_calls = _scenario()
    result, hold = _check(engine, sess, view, budget=4000)
    assert hold == "context_capacity_unavailable"
    assert result == view


def test_provider_preflight_hard_overflow_still_holds_without_exact_ref():
    engine, sess, view, _events, _rebuild_calls = _scenario()
    result, hold = _check(
        engine, sess, view, preflight=lambda *_args, **_kwargs: {"hard_overflow": True}
    )
    assert hold == "context_capacity_unavailable"
    assert result == view
