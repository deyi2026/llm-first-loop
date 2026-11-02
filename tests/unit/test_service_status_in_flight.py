"""status targets 视图：非终态动作（in_flight）可见性与收窄（2026-11-02）.

背景：publish+restart 之后下一轮只看到 restart_required=true，看不出"在等
本轮 requester run 结束"还是"卡死了"——非终态动作对 targets 视图完全不可见。"
"""

from datetime import UTC, datetime, timedelta

from llm_loop.runtime.service_control import ServiceControlAction, _in_flight_signal
from llm_loop.tools.builtin.service_control import _narrow_status_body, _targets_status_body

NOW = datetime(2026, 11, 2, 3, 0, 0, tzinfo=UTC)
ALL_SERVICES = ["web", "feishu", "wecom", "learning"]


def _action(
    action_id="svc-a1",
    *,
    status="waiting_for_requester_exit",
    target="all",
    age_s=120,
    generation=7,
):
    ts = (NOW - timedelta(seconds=age_s)).isoformat()
    return ServiceControlAction(
        schema="service-control-action/v1",
        action_id=action_id,
        action="restart",
        target=target,
        deployment_id=f"deploy-{generation}",
        deployment_generation=generation,
        requester_session_id="sess-x",
        status=status,
        created_at=ts,
        updated_at=ts,
    )


def _identity(in_flight):
    return {
        "deployment": {"generation": 7},
        "services": {"web": {"live": {}, "restart_required": True, "reasons": []}},
        "audit_signals": {"in_flight": in_flight},
    }


def test_restart_all_folds_into_one_row_not_four():
    rows = _in_flight_signal([_action()], now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["services"] == ALL_SERVICES
    assert row["gates"] == ["waiting_for_requester_exit"]
    assert "requester run 结束时" in row["when"]
    assert row["age_s"] == 120


def test_terminal_actions_are_not_in_flight():
    for status in ("succeeded", "failed"):
        assert _in_flight_signal([_action(status=status)], now=NOW) == []
    assert _in_flight_signal([], now=NOW) == []


def test_in_flight_caps_and_orders_newest_first():
    actions = [_action(f"svc-{i}", age_s=i * 10) for i in range(7)]
    rows = _in_flight_signal(actions, now=NOW)
    assert len(rows) == 5
    assert [row["action_id"] for row in rows] == [
        "svc-0", "svc-1", "svc-2", "svc-3", "svc-4",
    ]


def test_targets_view_surfaces_in_flight():
    body = _targets_status_body(_identity(_in_flight_signal([_action()], now=NOW)))
    in_flight = body["audit_summary"]["in_flight"]
    assert [row["action_id"] for row in in_flight] == ["svc-a1"]


def test_narrow_keeps_all_target_action_but_trims_services():
    rows = _in_flight_signal([_action()], now=NOW)
    narrowed = _narrow_status_body(_targets_status_body(_identity(rows)), "web")
    kept = narrowed["audit_summary"]["in_flight"]
    assert len(kept) == 1
    assert kept[0]["services"] == ["web"]


def test_narrow_drops_action_that_does_not_cover_scope():
    rows = _in_flight_signal([_action(target="feishu")], now=NOW)
    narrowed = _narrow_status_body(_targets_status_body(_identity(rows)), "web")
    assert narrowed["audit_summary"]["in_flight"] == []
