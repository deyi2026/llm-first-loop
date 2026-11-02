"""#1/#2/#5 回归：status 视图瘦身、并发重启假失败消解、failed 覆盖标注。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from llm_loop.runtime import service_control as sc
from llm_loop.runtime.service_control import ServiceControlAction
from llm_loop.tools.builtin import service_control as svc_tool


def _action(**over):
    base = dict(
        schema=sc._ACTION_SCHEMA,
        action_id="svc-x",
        action="restart",
        target="web",
        deployment_id="dep",
        deployment_generation=8,
        requester_session_id="sess",
        status="succeeded",
        created_at="2026-11-01T10:00:00+08:00",
        updated_at="2026-11-01T10:00:05+08:00",
    )
    base.update(over)
    return ServiceControlAction(**base)


def _identity_stub():
    services = {}
    for name in ("web", "feishu", "wecom", "learning"):
        services[name] = {
            "live": {
                "pid": 100,
                "pid_alive": True,
                "started_at": "2026-11-01T10:00:00+08:00",
                "git_head": "deadbeef" * 5,
                "manifest_present": True,
                "matches_desired_generation": True,
                "guard_code_drift": {"status": "current"},
            },
            "stable": None,
            "restart_required": False,
            "reasons": [],
            "admission_barrier": None,
            "terminal_action_barrier": None,
        }
    lag = [
        {
            "target": target,
            "generation": 7,
            "lag_generations": 1,
            "succeeded_actions": 3,
        }
        for target in ("web", "feishu", "wecom", "learning", "all")
    ]
    return {
        "deployment": {"generation": 8, "git_head": "deadbeef" * 5},
        "services": services,
        "admission_barriers": [],
        "available_exits": [],
        "gate_classification": [{"gate": "barrier", "exit_action": "release"}],
        "compat_retirement": [],
        "idle_state": {"web": {"state": "confirmed_idle", "detail": "x"}},
        "stage_facts": {
            "web": {
                "action_id": "svc-x",
                "status": "succeeded",
                "stage_fact": "started",
            }
        },
        "evidence_refs": {"web": {"action_id": "svc-x", "reason_ref": "ref"}},
        "audit_signals": {
            "generation_lag": lag,
            "orphan_barrier": [],
            "barrier_dir_changed": [],
            "waiting_timeout": [],
        },
    }


@pytest.fixture()
def stub_identity(monkeypatch):
    monkeypatch.setattr(
        svc_tool,
        "compose_service_identity_with_guard_freshness",
        lambda store: _identity_stub(),
    )


def test_status_default_view_is_compact_and_full_opts_in(stub_identity):
    store = object()
    default = svc_tool._compose_status_body(store)
    assert default["view"] == "targets"
    assert "gate_classification" not in default
    assert sorted(default["services"]) == ["feishu", "learning", "web", "wecom"]
    assert default["services"]["web"]["guard_code_drift"] == "current"
    assert default["services"]["web"]["alive"] is True
    compact_chars = len(json.dumps(default, ensure_ascii=False))
    assert compact_chars < 4000, compact_chars
    full = svc_tool._compose_status_body(store, "", "full")
    assert full["view"] == "full"
    assert full["gate_classification"]
    assert len(json.dumps(full, ensure_ascii=False)) > compact_chars


def test_status_target_narrows_and_rejects_unknown(stub_identity):
    narrowed = svc_tool._compose_status_body(object(), "web")
    assert sorted(narrowed["services"]) == ["web"]
    assert narrowed["target"] == "web"
    assert sorted(narrowed["stage_facts"]) == ["web"]
    # idle_state 只在 full 视图出现；收窄对它同样生效
    narrowed_full = svc_tool._compose_status_body(object(), "web", "full")
    assert set(narrowed_full["idle_state"]) == {"web"}
    with pytest.raises(ValueError):
        svc_tool._compose_status_body(object(), "nope")
    with pytest.raises(ValueError):
        svc_tool._compose_status_body(object(), "", "bogus")


def test_generation_lag_dedupes_per_target():
    deployment = SimpleNamespace(generation=8)
    actions = [
        _action(action_id="a1", target="web", deployment_generation=5),
        _action(action_id="a2", target="web", deployment_generation=6),
        _action(action_id="a3", target="web", deployment_generation=7),
        _action(action_id="a4", target="feishu", deployment_generation=7),
        _action(action_id="a5", target="learning", deployment_generation=8),
        _action(action_id="a6", target="wecom", status="failed", deployment_generation=3),
    ]
    entries = sc._generation_lag_signal(actions, deployment)
    by_target = {entry["target"]: entry for entry in entries}
    assert set(by_target) == {"web", "feishu"}
    assert by_target["web"]["generation"] == 7
    assert by_target["web"]["succeeded_actions"] == 3
    assert by_target["feishu"]["succeeded_actions"] == 1
    assert sc._generation_lag_signal(actions, None) == []


def test_stage_facts_marks_failed_action_as_covered():
    failed = _action(
        action_id="svc-fail",
        target="wecom",
        status="failed",
        created_at="2026-11-01T10:00:00+08:00",
        updated_at="2026-11-01T10:05:00+08:00",
    )
    cover = _action(
        action_id="svc-ok",
        target="wecom",
        updated_at="2026-11-01T10:01:00+08:00",
    )
    view = sc._stage_facts_view({"wecom": failed}, [failed, cover])
    assert view["wecom"]["status"] == "failed"
    assert view["wecom"]["covered"] is True
    assert view["wecom"]["covered_by"] == "svc-ok"


def test_stage_facts_leaves_uncovered_failure_visible():
    failed = _action(
        action_id="svc-fail",
        target="wecom",
        status="failed",
        created_at="2026-11-01T10:00:00+08:00",
        updated_at="2026-11-01T10:05:00+08:00",
    )
    older = _action(
        action_id="svc-old",
        target="wecom",
        updated_at="2026-11-01T09:00:00+08:00",
    )
    older_generation = _action(
        action_id="svc-oldgen",
        target="all",
        deployment_generation=7,
        updated_at="2026-11-01T10:02:00+08:00",
    )
    view = sc._stage_facts_view({"wecom": failed}, [failed, older, older_generation])
    assert view["wecom"]["covered"] is False
    assert view["wecom"]["covered_by"] is None


def _manifest_started_before(began):
    return {
        "pid": 4242,
        "git_head": "head-current",
        "started_at": (began - timedelta(seconds=90)).isoformat(),
    }


def test_verify_restart_targets_adopts_concurrent_restart(monkeypatch):
    began = datetime.now(UTC) - timedelta(seconds=30)
    monkeypatch.setattr(
        sc, "_read_runtime_manifest", lambda store, service: _manifest_started_before(began)
    )
    monkeypatch.setattr(sc, "_pid_alive", lambda pid: True)
    other = _action(
        action_id="svc-other",
        target="wecom",
        deployment_generation=9,
        updated_at=datetime.now(UTC).isoformat(),
    )
    monkeypatch.setattr(sc, "read_all_actions", lambda store: [other])
    deployment = SimpleNamespace(generation=9, git_head="head-current")
    verdict, summary, healthy = sc._verify_restart_targets(
        object(), deployment, ["wecom"], began.isoformat(), "svc-self"
    )
    assert verdict == "confirmed_ok", summary
    assert "adopted_by=svc-other" in summary
    assert healthy == ("wecom",)


def test_verify_restart_targets_keeps_failure_without_cover(monkeypatch):
    began = datetime.now(UTC) - timedelta(seconds=30)
    monkeypatch.setattr(
        sc, "_read_runtime_manifest", lambda store, service: _manifest_started_before(began)
    )
    monkeypatch.setattr(sc, "_pid_alive", lambda pid: True)
    deployment = SimpleNamespace(generation=9, git_head="head-current")
    monkeypatch.setattr(sc, "read_all_actions", lambda store: [])
    verdict, summary, _ = sc._verify_restart_targets(
        object(), deployment, ["wecom"], began.isoformat(), "svc-self"
    )
    assert verdict == "confirmed_fail"
    assert "started_before_restart" in summary
    other = _action(
        action_id="svc-other",
        target="wecom",
        deployment_generation=9,
        updated_at=datetime.now(UTC).isoformat(),
    )
    monkeypatch.setattr(sc, "read_all_actions", lambda store: [other])
    verdict2, summary2, _ = sc._verify_restart_targets(
        object(), deployment, ["wecom"], began.isoformat(), "svc-other"
    )
    assert verdict2 == "confirmed_fail"
    assert "started_before_restart" in summary2


def test_concurrent_cover_picks_earliest_settled_regardless_of_read_order(
    monkeypatch,
) -> None:
    """独立审查 P2-2：接管动作取最早落定的那个，不随读到顺序漂移。"""
    began = datetime.fromisoformat("2026-11-01T10:00:00+08:00")
    late = _action(
        action_id="svc-late", target="wecom", deployment_generation=9,
        updated_at="2026-11-01T10:04:00+08:00",
    )
    early = _action(
        action_id="svc-early", target="wecom", deployment_generation=9,
        updated_at="2026-11-01T10:02:00+08:00",
    )
    deployment = SimpleNamespace(generation=9, git_head="head-current")
    for order in ([late, early], [early, late]):
        monkeypatch.setattr(sc, "read_all_actions", lambda store, rows=order: list(rows))
        covers = sc._concurrent_restart_covers(
            object(), ["wecom"], began, deployment, "svc-self"
        )
        assert covers["wecom"] == "svc-early", "读到顺序不该改变接管归属"
