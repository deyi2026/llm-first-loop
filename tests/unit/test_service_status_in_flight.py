"""status targets 视图：非终态动作（in_flight）可见性与收窄（2026-11-02）.

背景：publish+restart 之后下一轮只看到 restart_required=true，看不出"在等
本轮 requester run 结束"还是"卡死了"——非终态动作对 targets 视图完全不可见。"
"""

from datetime import UTC, datetime, timedelta

from llm_loop.runtime.service_control import ServiceControlAction, _in_flight_signal
from llm_loop.tools.builtin.service_control import (
    _annotate_in_flight_liveness,
    _narrow_status_body,
    _targets_status_body,
)

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


def _identity_with_live(matches: dict[str, object]) -> dict:
    """构造 services，live.matches_desired_generation 按 matches 给定（缺失=无判据）."""
    services = {name: {"live": {"matches_desired_generation": state}} for name, state in matches.items()}
    return {
        "deployment": {"generation": 7},
        "services": services,
        "audit_signals": {"in_flight": _in_flight_signal([_action()], now=NOW)},
    }


def test_live_converged_true_when_every_service_already_on_desired():
    """动作仍在飞（等 requester 退出）但四个服务已全在 desired 代 → True."""
    identity = _identity_with_live({name: True for name in ALL_SERVICES})
    _annotate_in_flight_liveness(identity)
    row = identity["audit_signals"]["in_flight"][0]
    assert row["live_converged"] is True
    assert "lagging_services" not in row


def test_live_converged_false_names_the_lagging_service():
    identity = _identity_with_live(
        {"web": True, "feishu": True, "wecom": False, "learning": True}
    )
    _annotate_in_flight_liveness(identity)
    row = identity["audit_signals"]["in_flight"][0]
    assert row["live_converged"] is False
    assert row["lagging_services"] == ["wecom"]


def test_live_converged_none_when_criterion_absent():
    """判据缺失（无 matches 键）不得冒充"已等价"：None 而非 True."""
    identity = _identity_with_live({"web": True, "feishu": None})
    identity["services"]["feishu"] = {"live": {}}
    identity["services"]["wecom"] = {"live": {"matches_desired_generation": True}}
    identity["services"]["learning"] = {"live": {"matches_desired_generation": True}}
    _annotate_in_flight_liveness(identity)
    assert identity["audit_signals"]["in_flight"][0]["live_converged"] is None


def test_live_converged_ignores_services_missing_from_live_facts():
    """动作 statement 覆盖四服务，但 live 事实只读到两个 → 只按读到的判，不臆测."""
    identity = _identity_with_live({"web": True, "feishu": True})
    _annotate_in_flight_liveness(identity)
    row = identity["audit_signals"]["in_flight"][0]
    assert row["services"] == ALL_SERVICES
    assert row["live_converged"] is True


def test_annotation_reaches_targets_and_full_views():
    identity = _identity_with_live({"web": True})
    _annotate_in_flight_liveness(identity)
    targets = _targets_status_body(identity)
    assert targets["audit_summary"]["in_flight"][0]["live_converged"] is True
