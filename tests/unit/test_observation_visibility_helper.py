"""Focused adversarial tests for the pre-send raw observation gate."""

from __future__ import annotations

from llm_loop.core.loop.engine_services.observation_visibility import (
    group_visible_in_provider_view,
    latest_completed_tool_group,
)


def _asst(call_ids):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        for cid in call_ids
    ]}


def _tool(cid, content="ok"):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def _group(*, ids=("c1",), content="obs"):
    session = [{"role": "user", "content": "q"}, _asst(ids)]
    session.extend(_tool(cid, content) for cid in ids)
    return latest_completed_tool_group(session, 0)


def test_first_round_no_completed_group_allows_send():
    sess = [{"role": "user", "content": "hi"}]
    assert latest_completed_tool_group(sess, 0) is None
    assert group_visible_in_provider_view(None, [{"role": "user", "content": "hi"}])


def test_missing_group_in_provider_view_blocks():
    group = _group(content="INCIDENT_UNIQUE_OBSERVATION_x")
    assert group and group["call_ids"] == ["c1"]
    view = [{"role": "user", "content": "q"}, {"role": "system", "content": "compressed"}]
    assert not group_visible_in_provider_view(group, view)


def test_paired_group_visible_allows_even_if_repeated():
    group = _group(content="obs")
    view = [{"role": "user", "content": "q"}, _asst(["c1"]), _tool("c1", "obs")]
    assert group_visible_in_provider_view(group, view)


def test_multi_call_group_requires_exact_id_matching():
    group = _group(ids=("c1", "c2"), content="observed")
    assert group and group["valid"]
    assert not group_visible_in_provider_view(group, [
        _asst(["c1", "c2"]), _tool("c1", "observed"),
    ])
    assert group_visible_in_provider_view(group, [
        _asst(["c1", "c2"]), _tool("c2", "observed"), _tool("c1", "observed"),
    ])


def test_unauthorized_or_missing_ref_text_is_not_visibility():
    group = _group(content="actual")
    view = [
        {"role": "user", "content": "q"},
        {"role": "user", "content": "see evidence://v1/abc"},
    ]
    assert not group_visible_in_provider_view(group, view)


def test_same_id_with_changed_or_truncated_tool_content_is_not_raw():
    group = _group(content="exact full observation")
    assert not group_visible_in_provider_view(group, [
        _asst(["c1"]), _tool("c1", "exact full"),
    ])
    assert not group_visible_in_provider_view(group, [
        _asst(["c1"]), _tool("c1", "changed observation"),
    ])


def test_same_id_with_changed_tool_arguments_is_not_same_exchange():
    group = _group(content="result")
    other = _asst(["c1"])
    other["tool_calls"][0]["function"]["arguments"] = '{"path":"other.txt"}'
    assert not group_visible_in_provider_view(group, [other, _tool("c1", "result")])


def test_previous_run_tool_group_is_not_current_run_obligation():
    session = [
        {"role": "user", "content": "old"},
        _asst(["old-call"]),
        _tool("old-call", "old result"),
        {"role": "user", "content": "new"},
    ]
    assert latest_completed_tool_group(session, 3) is None
    assert latest_completed_tool_group(session, None) is None


def test_stale_matching_id_before_current_ingress_is_not_current_observation():
    group = _group(content="same")
    view = [
        _asst(["c1"]), _tool("c1", "same"),
        {"role": "user", "content": "new", "_active_run_ingress_ref": "3"},
    ]
    assert not group_visible_in_provider_view(group, view, active_ingress_ref="3")
    view.extend([_asst(["c1"]), _tool("c1", "same")])
    assert group_visible_in_provider_view(group, view, active_ingress_ref="3")


def test_incomplete_latest_group_is_not_silently_treated_as_first_round():
    session = [
        {"role": "user", "content": "q"},
        _asst(["c1", "c2"]),
        _tool("c1", "done"),
    ]
    group = latest_completed_tool_group(session, 0)
    assert group is not None and not group["valid"]
    assert not group_visible_in_provider_view(group, [
        _asst(["c1", "c2"]), _tool("c1", "done"),
    ])
