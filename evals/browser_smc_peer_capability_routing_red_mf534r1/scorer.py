from __future__ import annotations

from typing import Any

PERCEIVE_OWNED_ACTIONS = frozenset({"snapshot", "hydrate", "diff", "wait"})
OPERATE_OWNED_ACTIONS = frozenset(
    {"navigate", "click", "set_text", "append_text", "select", "scroll"}
)
BROWSER_CAPABILITIES = frozenset({"browser_perceive", "browser_operate"})


def _first_browser_call(tool_calls: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    for index, call in enumerate(tool_calls):
        if str(call.get("name") or "") in BROWSER_CAPABILITIES:
            return index, call
    return None


def score_historical_trace(record: dict[str, Any]) -> dict[str, Any]:
    """Score first-call routing independently from later recovery/task success."""
    calls = list(record.get("tool_calls") or [])
    first_match = _first_browser_call(calls)
    if first_match is None:
        return {
            "routing_verdict": "INVALID",
            "first_call_routing_valid": False,
            "failure_kind": "missing_browser_call",
            "recovered_later": False,
            "task_pass": bool(record.get("task_oracle_pass")),
        }

    first_index, first = first_match
    name = str(first.get("name") or "")
    status = str(first.get("status") or "")
    perceive_action = str(first.get("perceive_action") or "")
    operation_do = str(first.get("operation_do") or "")

    family_valid = False
    cross_bound_action = ""
    expected_peer = ""
    if name == "browser_perceive":
        family_valid = perceive_action in PERCEIVE_OWNED_ACTIONS
        if perceive_action in OPERATE_OWNED_ACTIONS:
            cross_bound_action = perceive_action
            expected_peer = "browser_operate"
    elif name == "browser_operate":
        family_valid = operation_do in OPERATE_OWNED_ACTIONS
        if operation_do in PERCEIVE_OWNED_ACTIONS:
            cross_bound_action = operation_do
            expected_peer = "browser_perceive"

    first_valid = status == "success" and family_valid
    failure_kind = ""
    if not first_valid:
        if cross_bound_action:
            failure_kind = "cross_capability_routing"
        elif status != "success":
            failure_kind = "first_call_contract_failure"
        else:
            failure_kind = "wrong_action_family"

    recovered_later = False
    recovery_index: int | None = None
    if cross_bound_action and expected_peer:
        for later_index, call in enumerate(calls[first_index + 1 :], start=first_index + 1):
            if str(call.get("name") or "") != expected_peer:
                continue
            if str(call.get("status") or "") != "success":
                continue
            actual = (
                str(call.get("operation_do") or "")
                if expected_peer == "browser_operate"
                else str(call.get("perceive_action") or "")
            )
            if actual == cross_bound_action:
                recovered_later = True
                recovery_index = later_index + 1
                break

    task_pass = bool(record.get("task_oracle_pass"))
    return {
        "routing_verdict": "PASS" if first_valid else "FAIL",
        "first_call_routing_valid": first_valid,
        "first_call_index": first_index + 1,
        "first_call_name": name,
        "failure_kind": failure_kind or None,
        "cross_bound_action": cross_bound_action or None,
        "expected_peer": expected_peer or None,
        "recovered_later": recovered_later,
        "recovery_call_index": recovery_index,
        "task_pass": task_pass,
        "task_success_overrides_routing": False,
    }


def score_compact_boundary(perceive_description: str, operate_description: str) -> dict[str, Any]:
    """Mechanical visibility score for one compact-description-only hypothesis.

    This is not a model-quality score and does not claim causality.  It asks only
    whether both peer descriptions make navigation ownership explicit in both
    directions while preserving the existing read/write split.
    """
    p = str(perceive_description or "")
    o = str(operate_description or "")
    checks = {
        "perceive_declares_read_only": "只读" in p,
        "perceive_excludes_navigation": "不导航" in p,
        "perceive_routes_navigation_to_peer": "browser_operate" in p and "do=navigate" in p,
        "perceive_names_closed_action_family": all(
            token in p for token in ("snapshot", "hydrate", "diff", "wait")
        )
        and "action" in p,
        "operate_declares_navigation": "do=navigate" in o,
        "operate_routes_wait_to_peer": "browser_perceive" in o and "wait" in o,
        "operate_names_navigation_binding": "browser_operate" in o and "do=navigate" in o,
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "failed_checks": sorted(key for key, value in checks.items() if not value),
    }


def compact_description_treatment(
    perceive_description: str, operate_description: str
) -> tuple[str, str]:
    """Test-local B arm.  Only compact description strings change."""
    perceive = (
        str(perceive_description)
        + " browser_perceive.action仅snapshot|hydrate|diff|wait；"
        + "导航必须调用browser_operate(do=navigate,url=...)。"
    )
    operate = (
        str(operate_description)
        + " 导航绑定browser_operate(do=navigate,url=...)；"
        + "browser_perceive.action仅用于snapshot|hydrate|diff|wait。"
    )
    return perceive, operate
