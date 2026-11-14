"""M2: T1 budgeted-write Web canary — real dispatch/canary fixtures, no GLM."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import (
    bind_task_budget,
    checked_provider_attempt,
    checked_tool_dispatch,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetConflictError,
    TaskBudgetDeniedError,
    TaskBudgetStore,
)
from llm_loop.resources.task_budget_t1_web_profile import (
    CONFIG_SCHEMA,
    PROFILE,
    T1WebBudgetExecution,
    T1WebEventPlan,
    prepare_t1_web_event_budget,
)
from llm_loop.web.task_budget_canary import (
    WebTaskBudgetCanary,
    _read_operator_config,
    bind_web_canary,
    choose_signed_web_canary,
)

_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _attempt() -> str:
    return "pattempt:" + uuid.uuid4().hex


def _prepared(size: int = 1000, max_tokens: int = 128) -> dict:
    return {"projected_bytes": size, "controls": {"max_tokens": max_tokens}}


def _setup(tmp_path: Path, *, sid: str = "web-t1", text: str = "do the T1 edit"):
    events = EventStore(tmp_path / "events")
    event = events.append_durable_human_message(
        sid,
        build_message_payload(
            index=0, role="user", source="user", content=text,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    target_dir = tmp_path / "docs"
    target_dir.mkdir(exist_ok=True)
    target = target_dir / "target.md"
    target.write_text("# T1 target\n- Review window opens: 2026-11-06\n")
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    now = time.time()
    plan = T1WebEventPlan(
        session_id=sid, workspace_scope=exact_workspace_scope(str(tmp_path)),
        authorization_id="b" * 32, target_path="docs/target.md",
        prepared_target_sha256=sha,
        valid_from_epoch_s=now - 20, valid_until_epoch_s=now + 600,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "ledger"),
    )
    return events, event, target, plan


def _open(
    plan, event, tmp_path, *, generation="run-1", sid="web-t1", text="do the T1 edit"
) -> T1WebBudgetExecution:
    execution = prepare_t1_web_event_budget(
        plan=plan, event=event, session_id=sid,
        workspace_root=str(tmp_path), run_generation=generation,
        user_text=text, ingress=issue_ingress("web"),
    )
    assert isinstance(execution, T1WebBudgetExecution)
    return execution


def _seed_transport(
    events: EventStore, sid: str, attempt: str, *,
    generation: str = "run-1",
    opened: bool = True, opened_projected: int | None = 1000,
    opened_max_tokens: int | None = 128,
    settled: bool = True, usage_in: int = 500, usage_out: int = 20,
    usage_cached: int | None = 0,
    opened_call_id: str | None = None,
):
    call_id = "pcall:" + uuid.uuid4().hex
    events.append(sid, "provider.call.opened", {
        "call_id": call_id, "origin_run_generation": generation,
    })
    if opened:
        events.append(sid, "provider.transport.opened", {
            "call_id": opened_call_id or call_id, "attempt_id": attempt,
            "provider_id": "glm", "model_id": "glm-5.3",
            "prepared": {
                "projected_bytes": opened_projected,
                "controls": {"max_tokens": opened_max_tokens},
            },
        })
    if settled:
        events.append(sid, "provider.transport.settled", {
            "call_id": call_id, "attempt_id": attempt,
            "provider_id": "glm", "model_id": "glm-5.3",
            "outcome": "success", "usage_observations": 1, "status_code": 200,
            "usage": {
                "input_tokens": usage_in, "output_tokens": usage_out,
                **({"cached_input_tokens": usage_cached} if usage_cached is not None else {}),
            },
        })


@contextmanager
def _attempt_scope(prepared):
    """Qualified attempt scope: the T1 profile now sits inside the shared
    positive-profile endpoint/transport gate, so every synthetic attempt
    must bind the exclusive verified isolated transport first."""
    with (
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        checked_provider_attempt(
            provider_id="glm", model_id="glm-5.3",
            wire_protocol="openai", target_url=_URL, prepared=prepared,
        ),
    ):
        yield


def test_t1_plan_validates_strict_fields(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    assert plan.budget_id == "webt1-" + "b" * 32
    now = time.time()
    with pytest.raises(TaskBudgetDeniedError, match="t1_plan_invalid"):
        T1WebEventPlan(
            session_id="s", workspace_scope="w",
            authorization_id="nothex", target_path="docs/target.md",
            prepared_target_sha256="0" * 64,
            valid_from_epoch_s=now, valid_until_epoch_s=now + 60,
            event_store=events, budget_store=TaskBudgetStore(tmp_path / "l2"),
        )
    with pytest.raises(TaskBudgetDeniedError, match="t1_plan_invalid"):
        T1WebEventPlan(
            session_id="s", workspace_scope="w", authorization_id="b" * 32,
            target_path="docs/target.md", prepared_target_sha256="zz" * 32,
            valid_from_epoch_s=now, valid_until_epoch_s=now + 60,
            event_store=events, budget_store=TaskBudgetStore(tmp_path / "l2"),
        )


def test_operator_config_whitelist(tmp_path: Path) -> None:
    now = time.time()
    config = {
        "schema": CONFIG_SCHEMA, "authorization_id": "b" * 32,
        "session_id": "web-t1", "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3", "target_path": "docs/target.md",
        "prepared_target_sha256": "0" * 64,
        "valid_from_epoch_s": now - 10, "valid_until_epoch_s": now + 600,
    }
    path = tmp_path / "t1.json"
    path.write_text(json.dumps(config))
    os.chmod(path, 0o600)
    assert _read_operator_config(path) == config
    bad = dict(config, extra_key="x")
    path.write_text(json.dumps(bad))
    with pytest.raises(TaskBudgetDeniedError):
        _read_operator_config(path)


def test_canary_load_selection_and_scopes(tmp_path: Path, monkeypatch) -> None:
    events, event, target, plan = _setup(tmp_path)
    engine = SimpleNamespace(
        session=SimpleNamespace(exists=lambda sid: sid == "web-t1"),
        workspace_root=str(tmp_path),
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _event_store=events,
        runner=SimpleNamespace(enabled=True, is_cancelled=lambda sid: False),
    )
    import llm_loop.web.task_budget_canary as canary_module
    from llm_loop.web.task_budget_canary import load_operator_web_canary

    monkeypatch.setattr(
        canary_module,
        "business_config_snapshot",
        lambda service: {},
    )

    config_path = tmp_path / "t1.json"
    now = time.time()
    config_path.write_text(json.dumps({
        "schema": CONFIG_SCHEMA, "authorization_id": "b" * 32,
        "session_id": "web-t1", "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3", "target_path": "docs/target.md",
        "prepared_target_sha256": plan.prepared_target_sha256,
        "valid_from_epoch_s": now - 10, "valid_until_epoch_s": now + 600,
    }))
    os.chmod(config_path, 0o600)
    monkeypatch.setattr(
        canary_module,
        "business_config_snapshot",
        lambda service: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(config_path)},
    )
    canary = load_operator_web_canary(engine)
    assert isinstance(canary, WebTaskBudgetCanary)
    assert isinstance(canary.plan, T1WebEventPlan)

    # Real API-auth selection matrix (same harness as canary API tests).
    from starlette.applications import Starlette
    from starlette.requests import Request

    monkeypatch.setenv("WEB_API_KEY", "unit-key")

    def _request(sid: str = "web-t1") -> Request:
        app = Starlette()
        app.state.task_budget_web_canary = canary
        return Request({
            "type": "http", "app": app, "method": "POST",
            "path": "/api/v1/chat/stream", "scheme": "http",
            "headers": [(b"host", b"127.0.0.1:1"), (b"authorization", b"Bearer unit-key")],
            "server": ("127.0.0.1", 1), "client": ("127.0.0.1", 1),
            "query_string": b"",
        })

    assert choose_signed_web_canary(
        _request(), "web-t1", model="glm/glm-5.3",
        resume=False, queued=False, attachments=False,
    ) is canary
    assert choose_signed_web_canary(
        _request(), "other-session", model="glm/glm-5.3",
        resume=False, queued=False, attachments=False,
    ) is None
    base = {"model": "glm/glm-5.3", "resume": False, "queued": False, "attachments": False}
    # resume bypasses the canary (ordinary path), the rest hard-deny.
    assert choose_signed_web_canary(_request(), "web-t1", **{**base, "resume": True}) is None
    for override in (
        {"model": "deepseek/chat"},
        {"queued": True},
        {"attachments": True},
    ):
        with pytest.raises(TaskBudgetDeniedError):
            choose_signed_web_canary(_request(), "web-t1", **{**base, **override})

    # Bind pins the write scope to the ONE attested target and the tool set.
    from llm_loop.core.run_context import (
        current_tool_discovery_scope,
        current_write_scope,
    )

    with bind_web_canary(canary):
        write_scope = current_write_scope.get()
        assert write_scope is not None
        assert write_scope.paths == ("docs/target.md",)
        assert current_tool_discovery_scope.get() == frozenset(
            {"read_file", "edit_file"}
        )
    assert current_write_scope.get() is None
    assert current_tool_discovery_scope.get() is None


def test_budgeted_attempt_settles_from_eventstore(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    attempt = _attempt()
    _seed_transport(events, "web-t1", attempt, usage_in=500, usage_out=20)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass  # offline: settlement consumes the pre-seeded durable events
    row = plan.budget_store.read(plan.budget_id)
    (rid, reservation) = next(iter(row["reservations"].items()))
    assert reservation["kind"] == "physical_attempts"
    assert reservation["phase"] == "settled"
    assert reservation["outcome"] == "success"
    assert reservation["allocations"]["input_tokens"] == 500
    assert reservation["allocations"]["output_tokens"] == 20
    assert reservation["allocations"]["payload_bytes"] == 1000
    assert reservation["receipt_ref"].startswith("webt1ev:")
    report = plan.budget_store.report(plan.budget_id)
    assert report["used_or_reserved"]["input_tokens"] == 500
    assert report["used_or_reserved"]["output_tokens"] == 20
    assert report["used_or_reserved"]["payload_bytes"] == 1000


def test_single_authorization_cas_and_restart_reuse_denied(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with pytest.raises(TaskBudgetDeniedError):
        _open(plan, event, tmp_path)  # duplicate authorization CAS refusal
    execution.request_stop(reason="owner_revoked")
    with pytest.raises(TaskBudgetDeniedError):
        _open(plan, event, tmp_path)  # sealed root is never reusable


def test_target_attestation_and_expiry_gates(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    target.write_text("# T1 target\n- tampered\n")
    with pytest.raises(TaskBudgetDeniedError, match="t1_prepared_target_sha_mismatch"):
        _open(plan, event, tmp_path)
    now = time.time()
    expired = T1WebEventPlan(
        session_id="web-t1", workspace_scope=plan.workspace_scope,
        authorization_id="c" * 32, target_path="docs/target.md",
        prepared_target_sha256=plan.prepared_target_sha256,
        valid_from_epoch_s=now - 600, valid_until_epoch_s=now - 10,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "l3"),
    )
    with pytest.raises(TaskBudgetDeniedError, match="t1_authorization_expired"):
        _open(expired, event, tmp_path)
    missing = T1WebEventPlan(
        session_id="web-t1", workspace_scope=plan.workspace_scope,
        authorization_id="d" * 32, target_path="docs/gone.md",
        prepared_target_sha256=plan.prepared_target_sha256,
        valid_from_epoch_s=now - 10, valid_until_epoch_s=now + 600,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "l4"),
    )
    with pytest.raises(TaskBudgetDeniedError, match="t1_prepared_target_missing"):
        _open(missing, event, tmp_path)


def test_prepared_request_envelope_gates(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
    ):
        with pytest.raises(TaskBudgetDeniedError, match="t1_prepared_request_missing"), _attempt_scope(None):
            pass
        with pytest.raises(TaskBudgetDeniedError, match="t1_prepared_request_unqualified"), _attempt_scope(_prepared(size=40_001)):
            pass
        with pytest.raises(TaskBudgetDeniedError, match="t1_prepared_request_unqualified"), _attempt_scope(_prepared(max_tokens=3_001)):
            pass
        assert not plan.budget_store.read(plan.budget_id)["reservations"]


def _failing_settle_case(tmp_path, seed) -> tuple:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    attempt = _attempt()
    seed(events, attempt)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass
    return plan, execution


def _assert_unknown_and_stopped(plan, execution) -> None:
    row = plan.budget_store.read(plan.budget_id)
    reservation = next(iter(row["reservations"].values()))
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 2 * 1000 + 8_000
    assert row["phase"] == "stop_requested"
    with (
        pytest.raises(TaskBudgetDeniedError), bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass


def test_usage_missing_keeps_unknown_and_stops(tmp_path: Path) -> None:
    plan, execution = _failing_settle_case(
        tmp_path,
        lambda events, attempt: _seed_transport(
            events, "web-t1", attempt, settled=False
        ),
    )
    _assert_unknown_and_stopped(plan, execution)


def test_duplicate_settled_events_fail_closed(tmp_path: Path) -> None:
    def seed(events, attempt):
        _seed_transport(events, "web-t1", attempt)
        _seed_transport(events, "web-t1", _attempt())

    plan, execution = _failing_settle_case(tmp_path, seed)
    _assert_unknown_and_stopped(plan, execution)


def test_wrong_generation_fail_closed(tmp_path: Path) -> None:
    plan, execution = _failing_settle_case(
        tmp_path,
        lambda events, attempt: _seed_transport(
            events, "web-t1", attempt, generation="other-run"
        ),
    )
    _assert_unknown_and_stopped(plan, execution)


def test_usage_exceeds_envelope_fail_closed(tmp_path: Path) -> None:
    plan, execution = _failing_settle_case(
        tmp_path,
        lambda events, attempt: _seed_transport(
            events, "web-t1", attempt, usage_in=2 * 1000 + 8_001
        ),
    )
    _assert_unknown_and_stopped(plan, execution)


def test_opened_envelope_drift_fail_closed(tmp_path: Path) -> None:
    plan, execution = _failing_settle_case(
        tmp_path,
        lambda events, attempt: _seed_transport(
            events, "web-t1", attempt, opened_projected=2000
        ),
    )
    _assert_unknown_and_stopped(plan, execution)


def test_cas_conflict_keeps_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    attempt = _attempt()
    _seed_transport(events, "web-t1", attempt, usage_in=500, usage_out=20)
    from llm_loop.resources.task_budget_t1_web_profile import _MAX_CAS_RETRIES

    real_mutate = plan.budget_store._mutate
    calls = {"n": 0}

    def conflicting_mutate(*args, **kwargs):
        # Window: calls 1-2 (reserve + mark_dispatched) pass through, the
        # next _MAX_CAS_RETRIES calls exhaust the T1 settlement CAS retries,
        # and everything after lets the I2 super().settle UNKNOWN write land.
        calls["n"] += 1
        if 2 < calls["n"] <= 2 + _MAX_CAS_RETRIES:
            raise TaskBudgetConflictError("stale budget revision CAS: injected")
        return real_mutate(*args, **kwargs)

    monkeypatch.setattr(plan.budget_store, "_mutate", conflicting_mutate)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass
    monkeypatch.undo()
    row = plan.budget_store.read(plan.budget_id)
    reservation = next(iter(row["reservations"].values()))
    assert reservation["phase"] == "unknown"
    assert reservation["allocations"]["input_tokens"] == 2 * 1000 + 8_000
    assert row["phase"] == "stop_requested"


def test_tool_allowlist_and_quota(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    assert plan.budget_store.read(plan.budget_id)["grant"]["profile"] == PROFILE
    with bind_task_budget(execution):
        with pytest.raises(TaskBudgetDeniedError, match="tool_not_allowed"), checked_tool_dispatch("execute_command"):
            pass
        # P1-3: qualified reads carry the attested path with snapshot=True
        # (the argument gate denies any other read shape outright).
        qualified_read = {"path": "docs/target.md", "snapshot": True}
        with pytest.raises(TaskBudgetDeniedError, match="t1_read_requires_target_snapshot"), checked_tool_dispatch("read_file"):
            pass
        for _ in range(3):
            with checked_tool_dispatch("read_file", arguments=qualified_read) as outcome:
                outcome["complete"] = True
        with pytest.raises(TaskBudgetDeniedError), checked_tool_dispatch("edit_file"):
            pass


def test_settle_replay_is_idempotent(tmp_path: Path) -> None:
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    attempt = _attempt()
    _seed_transport(events, "web-t1", attempt, usage_in=500, usage_out=20)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass
    rid = next(iter(plan.budget_store.read(plan.budget_id)["reservations"]))
    first = plan.budget_store.read(plan.budget_id)
    execution.settle(rid, outcome="success", complete=False)  # replay no-op
    second = plan.budget_store.read(plan.budget_id)
    assert second["revision"] == first["revision"]
    assert (
        second["reservations"][rid]["receipt_ref"]
        == first["reservations"][rid]["receipt_ref"]
    )


# -- cross-review hardening (2026-11-14 01:04) ------------------------------


def test_consecutive_attempts_each_bind_both_events(tmp_path: Path) -> None:
    """Point 1: settled reservations bind BOTH their settled and opened
    event ids, so a later attempt's unbound scan never re-counts a prior
    opened event (the old settled-only binding broke attempt #2)."""
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution):
        for _ in range(3):
            attempt = _attempt()
            _seed_transport(events, "web-t1", attempt, usage_in=500, usage_out=20)
            with _attempt_scope(_prepared()):
                pass
        row = execution.store.read(execution.budget_id)
    physical = [
        e for e in row["reservations"].values()
        if e["kind"] == BudgetDimension.PHYSICAL_ATTEMPTS.value
    ]
    assert len(physical) == 3
    assert row["phase"] == "active"  # no false stop from stale opened events
    assert all(e["phase"] == "settled" and e["outcome"] == "success" for e in physical)
    assert all(e["allocations"]["input_tokens"] == 500 for e in physical)
    assert all(e["allocations"]["output_tokens"] == 20 for e in physical)


def test_foreign_run_event_pollution_fails_closed(tmp_path: Path) -> None:
    """Point 2: a complete event triple from ANOTHER run generation in the
    same session pollutes the unbound scan — settle must fail closed."""
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution):
        _seed_transport(events, "web-t1", _attempt(), generation="run-1")
        _seed_transport(events, "web-t1", _attempt(), generation="another-run")
        with _attempt_scope(_prepared()):
            pass
        row = execution.store.read(execution.budget_id)
    rid = next(iter(row["reservations"]))
    assert row["reservations"][rid]["phase"] == "unknown"
    assert row["phase"] == "stop_requested"


def test_opened_call_id_must_match_settled_call(tmp_path: Path) -> None:
    """Point 2: the joined transport.opened event must carry the SAME
    call_id as the settled event (and that call must belong to this run)."""
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution):
        _seed_transport(
            events, "web-t1", _attempt(), opened_call_id="pcall:" + "f" * 24
        )
        with _attempt_scope(_prepared()):
            pass
        row = execution.store.read(execution.budget_id)
    rid = next(iter(row["reservations"]))
    assert row["reservations"][rid]["phase"] == "unknown"
    assert row["phase"] == "stop_requested"


def test_usage_cached_invalid_fails_closed(tmp_path: Path) -> None:
    """Point 3: cached_input_tokens must be a valid int within [0, input];
    above-input, negative, and MISSING values all keep UNKNOWN + stop."""
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    for sid, cached in (("web-a", 501), ("web-b", -5), ("web-c", None)):
        sub = tmp_path / sid
        sub.mkdir(exist_ok=True)
        events, event, target, plan = _setup(sub, sid=sid)
        execution = _open(plan, event, sub, sid=sid)
        with bind_task_budget(execution):
            _seed_transport(
                events, sid, _attempt(), usage_in=500, usage_cached=cached
            )
            with _attempt_scope(_prepared()):
                pass
            row = execution.store.read(execution.budget_id)
        rid = next(
            r
            for r, e in row["reservations"].items()
            if e["kind"] == BudgetDimension.PHYSICAL_ATTEMPTS.value
        )
        assert row["reservations"][rid]["phase"] == "unknown", sid
        assert row["phase"] == "stop_requested", sid


def test_target_path_must_be_strictly_normalized(tmp_path: Path) -> None:
    """Point 4: multi-segment strictly-normalized relative paths are the
    REAL shape (t1-sandbox/outputs/...); every non-normalized or escaping
    variant is rejected at plan construction."""
    now = time.time()
    store_events = EventStore(tmp_path / "events")

    def _plan(target: str) -> None:
        T1WebEventPlan(
            session_id="web-t1", workspace_scope=exact_workspace_scope(str(tmp_path)),
            authorization_id="b" * 32, target_path=target,
            prepared_target_sha256="0" * 64,
            valid_from_epoch_s=now - 20, valid_until_epoch_s=now + 600,
            event_store=store_events, budget_store=TaskBudgetStore(tmp_path / "l"),
        )

    _plan("t1-sandbox/outputs/fx05-v3r3-fixture.md")  # multi-segment OK
    _plan("docs/target.md")
    for bad in (
        "docs//target.md",
        "docs/./target.md",
        "docs/target.md/",
        "./docs/target.md",
        "docs/../docs/target.md",
        "/docs/target.md",
        "a\\b",
        ".",
    ):
        with pytest.raises(TaskBudgetDeniedError, match="t1_plan_invalid"):
            _plan(bad)


def test_edit_gate_rechecks_target_every_invocation(tmp_path: Path) -> None:
    """Point 4: every edit_file dispatch re-verifies the pinned write scope
    AND the prepared-target attestation — not only at authorization time."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    try:
        execution.reserve(
            BudgetDimension.TOOL_INVOCATIONS, tool_id="edit_file"
        )  # intact target passes
        target.write_text("# T1 target\n- Review window opens: 2099-01-01\n")
        with pytest.raises(TaskBudgetDeniedError, match="t1_target_drift"):
            execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="edit_file")
        current_write_scope.reset(token)
        token = None
        with pytest.raises(TaskBudgetDeniedError, match="t1_write_scope_drift"):
            execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="edit_file")
    finally:
        if token is not None:
            current_write_scope.reset(token)


def test_pending_envelope_is_exclusive(tmp_path: Path) -> None:
    """Point 5: a second note_prepared_request while one envelope is still
    un-consumed fails closed — concurrent/retried scopes can never borrow
    or overwrite another attempt's precharge."""
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    execution.note_prepared_request(_prepared())
    with pytest.raises(TaskBudgetDeniedError, match="t1_pending_envelope_conflict"):
        execution.note_prepared_request(_prepared())
    # Consumed by a reservation, arming becomes possible again (the manual
    # clear simulates the reserve() consumption without a second scope).
    from llm_loop.resources.task_budget_contracts import BudgetDimension  # noqa: F401

    execution._t1_pending_envelope = None  # type: ignore[attr-defined]
    with bind_task_budget(execution), _attempt_scope(_prepared()):
        pass
    execution.note_prepared_request(_prepared())  # no raise


def test_t1_endpoint_gate_blocks_unqualified_url_before_send_scope(
    tmp_path: Path,
) -> None:
    """Cross-review P1-1: a bound T1 execution must hard-deny any
    unqualified endpoint/wire BEFORE the send scope opens.

    Exact parent counterexample (fully synthetic, never touches the
    network): ``wire_protocol='http'`` against ``http://evil.invalid/api/``
    previously slipped through assert_provider_target — the T1 profile was
    absent from the positive-profile endpoint gate set and the scope
    entered (UNQUALIFIED_ENDPOINT_ENTERED_SEND_SCOPE). It must now be
    denied at the wire/URL layer with zero HTTP bytes possible.
    """
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
    ):
        with (
            pytest.raises(
                TaskBudgetDeniedError,
                match="positive_budget_provider_wire_unqualified",
            ),
            checked_provider_attempt(
                provider_id="glm",
                model_id="glm-5.3",
                wire_protocol="http",
                target_url="http://evil.invalid/api/",
                prepared=_prepared(),
            ),
        ):
            pytest.fail("unqualified endpoint entered the send scope")
        # Same-fight on the URL layer: qualified wire but a foreign host
        # with credentials/query is equally refused before the scope opens.
        with (
            pytest.raises(TaskBudgetDeniedError),
            checked_provider_attempt(
                provider_id="glm",
                model_id="glm-5.3",
                wire_protocol="openai",
                target_url="https://evil.example/api/x?k=1",
                prepared=_prepared(),
            ),
        ):
            pytest.fail("foreign endpoint entered the send scope")
        # The qualified endpoint passes the target gate and opens the
        # precharged scope normally (no HTTP is performed by this test).
        with checked_provider_attempt(
            provider_id="glm",
            model_id="glm-5.3",
            wire_protocol="openai",
            target_url=_URL,
            prepared=_prepared(),
        ):
            pass


def test_t1_run_stream_never_falls_back_to_signed_or_offline_budget(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-review P1-2: with a T1 plan bound, the REAL run_stream budget
    preparation must select the T1 path only.

    The lifecycle gate previously read ``if _event_plan is None and
    _admin_plan is None`` — a bound T1 plan fell through into
    prepare_signed_web_run_budget / the offline budget fixture. Both
    fallbacks are now monkeypatched to hard-assert; the test drives the
    real LoopEngine.run_stream (FakeLLM, zero network) and only passes if
    neither fallback is ever reached while the T1 budget is prepared.
    """
    import llm_loop.resources.task_budget_authority as authority_mod
    import llm_loop.resources.task_budget_run_scope as run_scope_mod
    from llm_loop.resources.task_budget_t1_web_profile import bind_t1_web_plan

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("T1 run must not fall back to signed/offline budget")

    monkeypatch.setattr(authority_mod, "prepare_signed_web_run_budget", _forbidden)
    monkeypatch.setattr(run_scope_mod, "prepare_offline_run_budget", _forbidden)

    engine, fake = build_test_engine([])
    # The T1 branch requires engine._event_store IS plan.event_store
    # (identity check in lifecycle) and run_stream needs an enabled store
    # for the durable human message: install one enabled instance for both.
    engine._event_store = EventStore(tmp_path / "t1-events")
    workspace = Path(engine.workspace_root)
    (workspace / "docs").mkdir(parents=True, exist_ok=True)
    target = workspace / "docs" / "target.md"
    target.write_text("# T1 target\n- Review window opens: 2026-11-06\n")
    now = time.time()
    plan = T1WebEventPlan(
        session_id="web-t1",
        workspace_scope=exact_workspace_scope(str(workspace)),
        authorization_id="b" * 32,
        target_path="docs/target.md",
        prepared_target_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        valid_from_epoch_s=now - 20,
        valid_until_epoch_s=now + 600,
        event_store=engine._event_store,
        budget_store=TaskBudgetStore(tmp_path / "t1-ledger"),
    )
    fake.chat_stream = lambda *a, **k: iter(())
    # Reaching the provider gate proves the real run_stream budget
    # preparation selected the T1 path: both fallbacks are patched to
    # hard-assert and were never invoked, and the FakeLLM is then
    # correctly refused by the T1 provider gate (which only admits
    # real LLMClient transports - fail-closed by design).
    with (
        bind_t1_web_plan(plan),
        pytest.raises(TaskBudgetDeniedError, match="provider_adapter_unqualified"),
    ):
        list(
            engine.run_stream(
                "web-t1", "do the T1 edit", ingress=issue_ingress("web")
            )
        )
    # The T1 budget root was really created through the T1 path.
    assert list((tmp_path / "t1-ledger").glob("*.json")), (
        "T1 budget root was never created"
    )


def test_t1_tool_gate_requires_armed_read_then_bound_edit(tmp_path: Path) -> None:
    """Cross-review P1-3: the T1 tool gate checks the argument pattern.

    read_file must target exactly the attested path with snapshot=True;
    edit_file must carry a non-empty expected_snapshot_ref on that same
    path AND consume the armed read; a second edit without a fresh read,
    a foreign tool, or a foreign path all fail closed before dispatch.
    """
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope

    good_read = {"path": "docs/target.md", "snapshot": True}
    good_edit = {
        "path": "docs/target.md",
        "expected_snapshot_ref": "artifact://v1/test-snapshot",
        # P1-2: a real edit carries its replacement strings; the size-bound
        # gate is fail-closed without them (cannot prove <= 2 MiB).
        "old_string": "# T1 target",
        "new_string": "beta",
    }
    with bind_task_budget(execution):
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_read_requires_target_snapshot"
            ),
            checked_tool_dispatch(
                "read_file",
                arguments={"path": "docs/other.md", "snapshot": True},
            ),
        ):
            pytest.fail("foreign read path dispatched")
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_read_requires_target_snapshot"
            ),
            checked_tool_dispatch(
                "read_file",
                arguments={"path": "docs/target.md", "snapshot": False},
            ),
        ):
            pytest.fail("non-snapshot read dispatched")
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_requires_bound_snapshot"
            ),
            checked_tool_dispatch(
                "edit_file",
                arguments={"path": "docs/target.md", "expected_snapshot_ref": ""},
            ),
        ):
            pytest.fail("edit without a snapshot ref dispatched")
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_without_armed_read"
            ),
            checked_tool_dispatch("edit_file", arguments=good_edit),
        ):
            pytest.fail("edit before any armed read dispatched")
        with (
            pytest.raises(TaskBudgetDeniedError, match="tool_not_allowed"),
            checked_tool_dispatch("execute_command", arguments={}),
        ):
            pytest.fail("foreign tool dispatched")
        # Armed read -> bound edit passes the argument gate (the reserve
        # layer then re-checks the target SHA / write scope as before).
        # Tool quota is MAX_TOOLS=3 per root, so this stays within budget.
        token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
        try:
            # P1-3 (hardened): a qualified read alone does NOT arm — only a
            # REAL successful read_file result carrying its own snapshot ref
            # (reported via note_t1_read_result) arms the gate.
            with checked_tool_dispatch("read_file", arguments=good_read) as outcome:
                outcome["complete"] = True  # real engine sets this on success
            with (
                pytest.raises(
                    TaskBudgetDeniedError, match="t1_edit_without_armed_read"
                ),
                checked_tool_dispatch("edit_file", arguments=good_edit),
            ):
                pytest.fail("qualified-but-unreported read armed an edit")
            # A failed/ref-less read result never arms.
            execution.note_t1_read_result(good_read, (None,))
            execution.note_t1_read_result(good_read, ())
            with (
                pytest.raises(
                    TaskBudgetDeniedError, match="t1_edit_without_armed_read"
                ),
                checked_tool_dispatch("edit_file", arguments=good_edit),
            ):
                pytest.fail("ref-less read result armed an edit")
            # The real read result arms exactly the ref it carries; a
            # forged different ref is refused.
            execution.note_t1_read_result(
                good_read,
                ({"artifact_ref": "artifact://v1/test-snapshot"},),
            )
            with (
                pytest.raises(
                    TaskBudgetDeniedError, match="t1_edit_snapshot_ref_not_armed"
                ),
                checked_tool_dispatch(
                    "edit_file",
                    arguments={
                        "path": "docs/target.md",
                        "expected_snapshot_ref": "artifact://v1/forged",
                    },
                ),
            ):
                pytest.fail("forged snapshot ref dispatched")
            with checked_tool_dispatch("edit_file", arguments=good_edit) as outcome:
                outcome["complete"] = True  # real engine sets this on success
            with (
                pytest.raises(
                    TaskBudgetDeniedError, match="t1_edit_without_armed_read"
                ),
                checked_tool_dispatch("edit_file", arguments=good_edit),
            ):
                pytest.fail("stale second edit dispatched")
            # A fresh successful read re-arms exactly one more edit.
            execution.note_t1_read_result(
                good_read,
                ({"artifact_ref": "artifact://v1/test-snapshot-2"},),
            )
        finally:
            current_write_scope.reset(token)


def test_t1_edit_size_bound_is_checked_before_write(tmp_path: Path) -> None:
    """P1-2: the 2 MiB Goal bound is a pre-execution denial, not a post-write
    apology. An oversized target, a provably-oversized result, multi-byte
    UTF-8 growth, and a replace_all amplification are all refused in the
    argument gate BEFORE the tool layer touches the file."""
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope

    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        # Arm via a real read result (target file is small in _setup).
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/size-bound"},),
        )
        # Small edit on a small target stays within the bound.
        with checked_tool_dispatch(
            "edit_file",
            arguments={
                "path": "docs/target.md",
                "expected_snapshot_ref": "artifact://v1/size-bound",
                "old_string": "# T1 target",
                "new_string": "beta",
            },
        ) as outcome:
            outcome["complete"] = True  # real engine sets this on success
        # Re-arm; multi-byte UTF-8 growth counts BYTES not characters.
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/size-bound-2"},),
        )
        with checked_tool_dispatch(
            "edit_file",
            arguments={
                "path": "docs/target.md",
                "expected_snapshot_ref": "artifact://v1/size-bound-2",
                "old_string": "# T1 target",
                "new_string": "βετα-βετα-βετα",  # 5 chars -> 24 UTF-8 bytes
            },
        ) as outcome:
            outcome["complete"] = True  # real engine sets this on success
        # Re-arm; a replace_all amplification that would exceed the bound
        # is denied BEFORE any write.
        target.write_text("x" * 16 + "\n" + "x" * 16 + "\n", encoding="utf-8")
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/size-bound-3"},),
        )
        huge = "y" * (2 * 1024 * 1024 - 8)
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_result_exceeds_size_bound"
            ),
            checked_tool_dispatch(
                "edit_file",
                arguments={
                    "path": "docs/target.md",
                    "expected_snapshot_ref": "artifact://v1/size-bound-3",
                    "old_string": "x" * 16,
                    "new_string": huge,
                    "replace_all": True,
                },
            ),
        ):
            pytest.fail("replace_all amplification past 2 MiB dispatched")
        # The file itself is already beyond the hard bound -> every edit is
        # denied outright (dry_run included).
        target.write_bytes(b"z" * (2 * 1024 * 1024 + 1))
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/size-bound-4"},),
        )
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_target_exceeds_size_bound"
            ),
            checked_tool_dispatch(
                "edit_file",
                arguments={
                    "path": "docs/target.md",
                    "expected_snapshot_ref": "artifact://v1/size-bound-4",
                    "old_string": "z",
                    "new_string": "w",
                    "dry_run": True,
                },
            ),
        ):
            pytest.fail("edit on an already-oversized target dispatched")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_t1_edit_size_bound_crlf_cross_line_replace_all(tmp_path: Path) -> None:
    """Parent review 2026-11-14 06:59 counterexample #1, byte-exact.

    A CRLF target matched by an LF-form old_string ("x\\n") has ZERO raw
    occurrences but thousands of normalized occurrences; FileService.edit
    replaces every normalized match and then restores CRLF across the
    whole result. An estimation gate that counts on raw bytes sees ~1
    growth and lets a >2 MiB write through; the isomorphic gate must
    compute the exact final UTF-8 size and refuse BEFORE any write, with
    the file left byte-identical (verified against the production
    FileService dry_run expected_after_bytes, which also exceeds 2 MiB).
    """
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope

    # CRLF target: 60,000 lines of "x\r\n" -> 180,000 raw bytes, and the
    # normalized text contains "x\n" 60,000 times (raw bytes: 0 times).
    crlf_body = "x\r\n" * 60_000
    target.write_bytes(crlf_body.encode("utf-8"))
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/crlf-x"},),
        )
        # ~36 bytes per replacement * 60,000 -> the real result is far
        # past 2 MiB even though the raw bytes match ZERO times.
        new_string = "yy\nzz\r\nqq\nrr\n" * 5
        args = {
            "path": "docs/target.md",
            "expected_snapshot_ref": "artifact://v1/crlf-x",
            "old_string": "x\n",  # LF form: 0 raw hits, 60k normalized hits
            "new_string": new_string,
            "replace_all": True,
        }
        # Cross-check with the production service: its own dry_run proves
        # the committed result would indeed exceed the bound (same
        # normalize/replace/CRLF-restore algorithm, no estimation).
        from llm_loop.workspace.file_service import FileService

        preview = FileService().edit(
            path=target,
            old_string=args["old_string"],
            new_string=args["new_string"],
            replace_all=True,
            dry_run=True,
        )
        assert len(preview.expected_after_bytes) > 2 * 1024 * 1024
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_result_exceeds_size_bound"
            ),
            checked_tool_dispatch("edit_file", arguments=args),
        ):
            pytest.fail("CRLF cross-line replace_all amplification dispatched")
        # Fail-closed means zero bytes touched, CRLF line endings intact.
        assert target.read_bytes() == crlf_body.encode("utf-8")
        # Same shape WITHOUT replace_all: FileService would raise
        # MultipleMatches (60,000 > 1), so the isomorphic gate refuses it
        # as a fail-closed preview instead of counting it once.
        args.pop("replace_all")
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_multiple_matches_preview"
            ),
            checked_tool_dispatch("edit_file", arguments=args),
        ):
            pytest.fail("multi-match single edit dispatched")
        assert target.read_bytes() == crlf_body.encode("utf-8")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_t1_edit_size_bound_lf_heavy_new_string_under_crlf_restore(
    tmp_path: Path,
) -> None:
    """Parent review 2026-11-14 06:59 counterexample #2, byte-exact.

    A CRLF-dominant target with a SINGLE old_string match is still risky
    when new_string carries many LF newlines: FileService restores the
    dominant CRLF ending across the whole result, so every injected
    newline gains one extra byte. The isomorphic gate computes the exact
    restored size (raw base ~1.05 MiB + 100k LF in new_string -> +100k
    restore bytes + new_string body -> > 2 MiB) and refuses pre-write.
    """
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope

    # CRLF-dominant target ~1.1 MiB with exactly ONE anchor occurrence.
    body = ("line\r\n" * 200_000) + "anchor\r\n" + ("tail\r\n" * 80_000)
    target.write_bytes(body.encode("utf-8"))
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        execution.note_t1_read_result(
            {"path": "docs/target.md", "snapshot": True},
            ({"artifact_ref": "artifact://v1/crlf-lf"},),
        )
        # One match; new_string carries ~1 MiB of LF newlines plus body:
        # after CRLF restoration every \n costs one extra byte, pushing
        # the final result past 2 MiB even though old matches once.
        args = {
            "path": "docs/target.md",
            "expected_snapshot_ref": "artifact://v1/crlf-lf",
            "old_string": "anchor\r\n",
            "new_string": ("w" * 8 + "\n") * 100_000,
        }
        from llm_loop.workspace.file_service import FileService

        preview = FileService().edit(
            path=target,
            old_string=args["old_string"],
            new_string=args["new_string"],
            replace_all=False,
            dry_run=True,
        )
        assert len(preview.expected_after_bytes) > 2 * 1024 * 1024
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_result_exceeds_size_bound"
            ),
            checked_tool_dispatch("edit_file", arguments=args),
        ):
            pytest.fail("LF-heavy new_string under CRLF restore dispatched")
        assert target.read_bytes() == body.encode("utf-8")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_transport_failure_latches_durable_stop_and_blocks_next_attempt(
    tmp_path: Path,
) -> None:
    """P1-2 (parent-measured): a failed physical transport keeps the
    reservation UNKNOWN AND latches a durable stop immediately.

    Before the fix the failed settle left the root ACTIVE, so a second
    provider send could still go out and a restart could rebind the same
    authorization. Now: (a) the RuntimeError inside the attempt scope
    settles outcome=failure -> unknown liability + stop_requested root;
    (b) the NEXT checked_provider_attempt is refused before any send
    scope opens; (c) a freshly constructed execution bound to the same
    durable root (restart / rebind) is refused at reserve as well.
    """
    from llm_loop.resources.task_budget_contracts import TaskBudgetMember

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    prepared = _prepared()
    with bind_task_budget(execution):
        with (
            pytest.raises(RuntimeError, match="synthetic transport failure"),
            _attempt_scope(prepared),
        ):
            raise RuntimeError("synthetic transport failure")
        row = plan.budget_store.read(plan.budget_id)
        assert row["phase"] == "stop_requested"
        (rid, reservation) = next(iter(row["reservations"].items()))
        assert reservation["kind"] == "physical_attempts"
        assert reservation["phase"] == "unknown"
        # Second provider attempt: refused BEFORE the send scope yields.
        with (
            pytest.raises(TaskBudgetDeniedError),
            _attempt_scope(prepared),
        ):
            pytest.fail("stopped root admitted a further provider attempt")

    # Restart / rebind on the same durable root and authorization: the
    # stop is durable — a fresh execution instance cannot even bind the
    # stopped root (budget_not_active), far less open a send scope.
    durable_row = plan.budget_store.read(plan.budget_id)
    fresh = T1WebBudgetExecution(
        store=plan.budget_store,
        budget_id=plan.budget_id,
        member=TaskBudgetMember.from_dict(
            durable_row["members"][plan.budget_id]
        ),
    )
    with (
        pytest.raises(TaskBudgetDeniedError, match="budget_not_active"),
        bind_task_budget(fresh),
    ):
        pytest.fail("restart-rebound execution bound a stopped root")
    assert plan.budget_store.read(plan.budget_id)["phase"] == "stop_requested"


def test_settle_replay_with_forged_receipt_ref_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-2: a same-prefix forged receipt_ref is NOT an idempotent replay.

    The old fast path only checked the receipt prefix and allocation
    bounds, so a tampered-but-plausible receipt_ref would silently pass
    as an already-committed settlement. Now the replay no-op requires
    the FULL re-derivation from durable EventStore facts (settled event
    by event_id, its single opened event, generation-bound call, exact
    envelope, usage equality, recomputed canonical digest). A one-byte
    tamper fails the re-derivation, falls through to the join path, and
    the unbound-event scan finds nothing (the real events are already
    bound) -> durable fail-closed stop, never a silent success replay.
    """
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    attempt = _attempt()
    _seed_transport(events, "web-t1", attempt, usage_in=500, usage_out=20)
    with (
        bind_task_budget(execution),
        bind_isolated_provider_transport(IsolatedTransportProfile()),
        _attempt_scope(_prepared()),
    ):
        pass
    row = plan.budget_store.read(plan.budget_id)
    (rid, committed) = next(iter(row["reservations"].items()))
    assert committed["phase"] == "settled"
    committed_ref = committed["receipt_ref"]
    assert committed_ref.startswith("webt1ev:")
    flipped = "0" if committed_ref[-1] != "0" else "1"
    forged_ref = committed_ref[:-1] + flipped
    assert forged_ref != committed_ref  # same prefix + event_id, tampered digest
    real_read = plan.budget_store.read

    def forged_read(budget_id):
        forged = dict(real_read(budget_id))
        forged["reservations"] = dict(forged["reservations"])
        forged["reservations"][rid] = dict(forged["reservations"][rid])
        forged["reservations"][rid]["receipt_ref"] = forged_ref
        return forged

    monkeypatch.setattr(plan.budget_store, "read", forged_read)
    execution.settle(rid, outcome="success", complete=False)
    monkeypatch.undo()
    final = plan.budget_store.read(plan.budget_id)
    # The durable truth is unchanged and the run failed closed instead of
    # blessing the forged receipt as an idempotent committed settlement.
    assert final["reservations"][rid]["receipt_ref"] == committed_ref
    assert final["reservations"][rid]["phase"] == "settled"
    assert final["phase"] == "stop_requested"


def _t1_engine_plan(tmp_path: Path, engine, session_id: str = "web-t1-fence"):
    """Minimal T1 plan wiring over an already-built test engine."""
    engine._event_store = EventStore(tmp_path / "t1-events")
    workspace = Path(engine.workspace_root)
    (workspace / "docs").mkdir(parents=True, exist_ok=True)
    target = workspace / "docs" / "target.md"
    target.write_text("# T1 target\n- Review window opens: 2026-11-06\n")
    now = time.time()
    plan = T1WebEventPlan(
        session_id=session_id,
        workspace_scope=exact_workspace_scope(str(workspace)),
        authorization_id="c" * 32,
        target_path="docs/target.md",
        prepared_target_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        valid_from_epoch_s=now - 20,
        valid_until_epoch_s=now + 600,
        event_store=engine._event_store,
        budget_store=TaskBudgetStore(tmp_path / "t1-ledger"),
    )
    return plan, target


def test_t1_restricted_session_fence_blocks_unplanned_direct_runs(
    build_test_engine, tmp_path: Path
) -> None:
    """P1-1: a T1-authorized session is fenced exactly like admin-once.

    create_app now binds ``engine._task_budget_restricted_session_id`` for
    BOTH operator plan kinds. This test pins the fence BEHAVIOR on the
    alternate entrypoint family (direct Engine.run_stream with no plan
    bound — the same admission code every queue/sync route reaches): the
    restricted session is refused outright, while an unrestricted session
    keeps taking the default (non-T1) budgeted path.
    """
    from llm_loop.resources.task_budget_t1_web_profile import bind_t1_web_plan

    engine, fake = build_test_engine([])
    plan, _target = _t1_engine_plan(tmp_path, engine)
    fake.chat_stream = lambda *a, **k: iter(())
    # Simulate exactly what create_app binds for a T1 canary plan.
    engine._task_budget_restricted_session_id = plan.session_id
    # No plan bound: the direct run is refused BEFORE any provider/tool
    # work — no fallback to an unbudgeted default path exists for a
    # restricted session.
    with pytest.raises(
        TaskBudgetDeniedError, match="restricted_web_session_requires_budget_plan"
    ):
        list(
            engine.run_stream(
                plan.session_id, "unplanned direct run", ingress=issue_ingress("web")
            )
        )
    # With the plan bound the same session proceeds down the T1 path
    # (FakeLLM then fails the T1 provider gate — fail-closed, no fallback).
    with (
        bind_t1_web_plan(plan),
        pytest.raises(TaskBudgetDeniedError, match="provider_adapter_unqualified"),
    ):
        list(
            engine.run_stream(
                plan.session_id, "planned run", ingress=issue_ingress("web")
            )
        )
    # The fence never leaks into other engines/sessions: a fresh engine
    # (e.g. after a restart without the T1 canary config) carries no
    # restricted binding at all.
    engine2, _fake2 = build_test_engine([])
    assert getattr(engine2, "_task_budget_restricted_session_id", None) is None


class _SyntheticSSE:
    """Minimal httpx-like streaming response for the provider POST stub."""

    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self) -> _SyntheticSSE:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def iter_lines(self):
        yield from self._lines
        yield "data: [DONE]"


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False)


def _tool_round(call_id: str, name: str, arguments: str) -> list[str]:
    return [
        _sse(
            {
                "model": "glm-5.3",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": name, "arguments": arguments},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        ),
        _sse(
            {
                "model": "glm-5.3",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            }
        ),
        _sse(
            {
                "model": "glm-5.3",
                "choices": [],
                "usage": {"prompt_tokens": 120, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 0}},
            }
        ),
    ]


def test_t1_engine_scope_e2e_synthetic_provider_stream(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-4: engine-scope e2e — production bind_web_canary(T1) arm ->
    engine.run_stream -> REAL LLMClient -> EventStore -> budget CAS ->
    controlled edit, fully synthetic (zero real GLM).

    Scope disclosure (parent review 07:11): this test drives the REAL
    engine.run_stream under the REAL Web-entry canary bind — it does NOT
    go through the HTTP FastAPI route layer or BackgroundRunner dispatch
    (those are covered separately by
    test_t1_real_web_stream_passes_pinned_plan_to_background_runner).
    Only the HTTP transport function is stubbed (synthetic SSE frames);
    everything else is production code: the T1 plan admission, the real
    LLMClient streaming parse, the transport journal (call.opened /
    transport.opened with prepared facts / transport.settled with usage),
    the budget reservation/CAS settlement joined against EventStore, the
    read->arm->edit->CAS tool chain, and the final natural round.
    """
    import llm_loop.llm.client as client_mod
    from llm_loop.llm.client import LLMClient
    from llm_loop.resources.provider_settlement import (
        ProviderCallSettlementJournal,
    )
    engine, _fake = build_test_engine([])
    plan, target = _t1_engine_plan(tmp_path, engine, session_id="web-t1-e2e")
    # The bare test registry's read_file has no artifact store (snapshot
    # refs unavailable); re-register the production wiring (factory-style
    # shared WorkspaceArtifactStore + FileService) so snapshot=True works.
    from llm_loop.tools.builtin.read_file import ReadFileTool
    from llm_loop.workspace.artifacts import WorkspaceArtifactStore
    from llm_loop.workspace.file_service import FileService

    _artifacts = WorkspaceArtifactStore(str(tmp_path / "t1-artifacts"))
    _files = FileService(
        artifact_store=_artifacts, lock_root=tmp_path / "t1-file-locks"
    )
    engine.registry.register(
        ReadFileTool(artifact_store=_artifacts, file_service=_files)
    )
    # Same production wiring for the controlled edit tool (four-stage
    # read->match->diff->apply with version precondition, exactly as the
    # factory registers it).
    from llm_loop.tools.builtin.edit_file import EditFileTool as _EditTool

    engine.registry.register(
        _EditTool(
            artifact_store=_artifacts,
            file_service=_files,
            require_version_precondition=True,
        )
    )
    # Production settlement journal over the run's EventStore.
    journal = ProviderCallSettlementJournal(engine._event_store, projection_sink=None)
    from llm_loop.resources.transport_observation import ShadowTransportRecorder

    observer = ShadowTransportRecorder()
    observer.set_settlement_journal(journal)
    # Production provider-call correlation: shadow call + bound call site
    # are what make the journal write call.opened/transport events. The
    # real coordinator is constructed with no governor (shadow calls never
    # touch admission); engine.run drives it per round.
    from llm_loop.resources.provider_calls import ProviderCallCoordinator

    engine.provider_call_coordinator = ProviderCallCoordinator(
        # Shadow calls never touch admission; the typed governor slot is
        # irrelevant for the synthetic correlation path under test.
        governor=None,  # type: ignore[arg-type]
        local_runtime=None,
        settlement_journal=journal,
    )
    client = LLMClient(
        api_key="k",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3",
        provider="glm",
        max_tokens=3000,
        trust_env=False,
    )
    client.transport_observer = observer
    # Route the engine at the REAL client (pool bypassed, as lifecycle
    # does when no pool is installed).
    engine.llm_pool = None
    engine.llm = client

    state: dict[str, Any] = {"round": 0, "armed_ref": None}

    # Spy on the P1-3 arm hook: the real note_t1_read_result (installed by
    # the tool executor after the REAL read_file succeeded) is preserved;
    # the spy only records the armed ref so the synthetic edit round can
    # present exactly what the live execution object armed.
    from llm_loop.resources.task_budget_t1_web_profile import (
        T1WebBudgetExecution,
    )

    _orig_note = T1WebBudgetExecution.note_t1_read_result

    def _spy_note(self, arguments, artifact_facts):  # noqa: ANN001, ANN202
        _orig_note(self, arguments, artifact_facts)
        state["armed_ref"] = self._t1_armed_ref

    monkeypatch.setattr(T1WebBudgetExecution, "note_t1_read_result", _spy_note)

    def _edit_arguments() -> str:
        armed = state["armed_ref"]
        assert armed, "read round did not arm the edit gate"
        return json.dumps(
            {
                "path": "docs/target.md",
                "expected_snapshot_ref": armed,
                "old_string": "2026-11-06",
                "new_string": "2026-11-13",
            }
        )

    def _final_round() -> list[str]:
        return [
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [
                        {"index": 0, "delta": {"content": "done."}, "finish_reason": None}
                    ],
                }
            ),
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            ),
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 12, "prompt_tokens_details": {"cached_tokens": 0}},
                }
            ),
        ]

    def _synthetic_post(_http, method, url, **kwargs):  # noqa: ANN001, ANN202
        state["round"] += 1
        if state["round"] == 1:
            lines = _tool_round(
                "call-read",
                "read_file",
                json.dumps({"path": "docs/target.md", "snapshot": True}),
            )
        elif state["round"] == 2:
            lines = _tool_round("call-edit", "edit_file", _edit_arguments())
        else:
            lines = _final_round()
        return _SyntheticSSE(lines)

    monkeypatch.setattr(client_mod, "_task_budget_provider_stream", _synthetic_post)


    # REAL Web-entry scope: the production bind_web_canary T1 arm used by
    # the routes layer (plan bind + isolated transport + operator-attested
    # single-target write scope + two-tool discovery scope). Driving the
    # engine through this scope is what the actual stream route does per
    # generator step.
    from llm_loop.web.task_budget_canary import WebTaskBudgetCanary, bind_web_canary

    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    with bind_web_canary(canary):
        list(
            engine.run_stream(
                plan.session_id, "apply the approved date edit", ingress=issue_ingress("web")
            )
        )

    # 1) The controlled edit really landed on the target file.
    assert "2026-11-13" in target.read_text(encoding="utf-8")
    # 2) The EventStore carries the full production event chain.
    events = engine._event_store.read(plan.session_id)
    kinds = [event.type for event in events]
    assert kinds.count("provider.transport.opened") == 3
    assert kinds.count("provider.transport.settled") == 3
    # 3) The budget ledger settled everything with real joins.
    ledger_files = list((tmp_path / "t1-ledger").glob("*.json"))
    assert len(ledger_files) == 1
    row = json.loads(ledger_files[0].read_text())
    kinds_by_res = {}
    for rid, res in row["reservations"].items():
        kinds_by_res.setdefault(res["kind"], []).append(res)
        assert res["phase"] == "settled", (rid, res["phase"])
        assert res["outcome"] == "success"
    assert len(kinds_by_res.get("physical_attempts", [])) == 3
    assert len(kinds_by_res.get("tool_invocations", [])) == 2
    # 4) Physical allocations are the OBSERVED synthetic usage figures.
    observed_input = sorted(
        res["allocations"]["input_tokens"]
        for res in kinds_by_res["physical_attempts"]
    )
    assert observed_input == [90, 120, 120]
    # 5) Every settled physical reservation binds the EventStore event.
    for res in kinds_by_res["physical_attempts"]:
        assert res["receipt_ref"].startswith("webt1ev:")


def test_parent_replay_failed_read_never_arms_and_blocks_edit(tmp_path: Path) -> None:
    """Parent-side synthetic replay 1+2 (2026-11-14 06:41): a read_file that
    fails inside the real checked_tool_dispatch scope must NEVER arm the edit
    gate, and any edit with an arbitrary non-empty expected_snapshot_ref must
    then be refused before entering the pre-dispatch scope."""
    events, event, target, plan = _setup(tmp_path)
    budget = _open(plan, event, tmp_path)
    # Gate qualification for the read passes (arguments are valid)...
    budget.assert_t1_tool_action(
        "read_file", {"path": "docs/target.md", "snapshot": True}
    )
    # ...but the REAL read fails inside the dispatch scope (tool error).
    with (
        bind_task_budget(budget),
        pytest.raises(RuntimeError, match="simulated read failure"),
        checked_tool_dispatch(
            "read_file", arguments={"path": "docs/target.md", "snapshot": True}
        ),
    ):
        raise RuntimeError("simulated read failure")
    # FAILED_READ_ARMED must be False: a failed read never arms.
    assert budget._t1_armed_ref is None
    # EDIT_ENTERED_AFTER_FAILED_READ must be False: a forged non-empty ref is
    # refused inside the real dispatch scope (never reaches pre-send).
    with (
        bind_task_budget(budget),
        pytest.raises(TaskBudgetDeniedError, match="t1_edit_without_armed_read"),
        checked_tool_dispatch(
            "edit_file",
            arguments={
                "path": "docs/target.md",
                "expected_snapshot_ref": "artifact://v1/" + "f" * 64,
                "old_string": "2026-11-06",
                "new_string": "2026-11-13",
            },
        ),
    ):
        pytest.fail("edit entered pre-dispatch scope after a failed read")
    assert target.read_text() == "# T1 target\n- Review window opens: 2026-11-06\n"


def test_parent_replay_oversized_edit_fails_before_write(tmp_path: Path) -> None:
    """Parent-side synthetic replay 3 (2026-11-14 06:41): a legitimately armed
    edit whose new_string alone is 2,100,000 ASCII bytes (>2 MiB) must be
    refused by the pre-dispatch size bound; the target file is never written."""
    events, event, target, plan = _setup(tmp_path)
    budget = _open(plan, event, tmp_path)
    # Arm legitimately: qualified read + SUCCESS result carrying its ref.
    budget.assert_t1_tool_action(
        "read_file", {"path": "docs/target.md", "snapshot": True}
    )
    ref = "artifact://v1/" + "a" * 64
    budget.note_t1_read_result(
        {"path": "docs/target.md", "snapshot": True},
        ({"artifact_ref": ref},),
    )
    assert budget._t1_armed_ref == ref
    before = target.read_bytes()
    with (
        bind_task_budget(budget),
        pytest.raises(
            TaskBudgetDeniedError, match="t1_edit_result_exceeds_size_bound"
        ),
        checked_tool_dispatch(
            "edit_file",
            arguments={
                "path": "docs/target.md",
                "expected_snapshot_ref": ref,
                "old_string": "2026-11-06",
                "new_string": "x" * 2_100_000,
            },
        ),
    ):
        pytest.fail("oversized edit entered pre-dispatch scope")
    # OVER_2MIB_EDIT_ENTERED_PRESEND must be False — and nothing was written.
    assert target.read_bytes() == before


def _crlf_setup(tmp_path: Path, repeat: int = 100_000):
    """Parent P1 counterexample fixture: CRLF-dominated target.

    raw = (b'A\\r\\nX') * repeat — 400,000 bytes at the parent's size; the
    LF-form old_string 'A\\nX' matches zero times on the raw bytes but
    `repeat` times on the LF-normalized text FileService actually edits.
    """
    target_dir = tmp_path / "docs"
    target_dir.mkdir(exist_ok=True)
    target = target_dir / "target.md"
    raw = (b"A\r\nX") * repeat
    target.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    events = EventStore(tmp_path / "events")
    event = events.append_durable_human_message(
        "web-t1",
        build_message_payload(
            index=0, role="user", source="user", content="do the T1 edit",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    now = time.time()
    plan = T1WebEventPlan(
        session_id="web-t1", workspace_scope=exact_workspace_scope(str(tmp_path)),
        authorization_id="b" * 32, target_path="docs/target.md",
        prepared_target_sha256=sha,
        valid_from_epoch_s=now - 20, valid_until_epoch_s=now + 600,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "ledger"),
    )
    return events, event, target, plan


def test_parent_p1_crlf_replace_all_bound_uses_normalized_count(tmp_path: Path) -> None:
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    """Parent-measured P1 counterexample (2026-11-14): a CRLF target with an
    LF-form old_string made the raw-byte occurrence count zero, so the old
    gate predicted a single 29-byte growth and let a replace_all edit enter
    the tool scope; FileService matched 100,000 normalized occurrences and
    produced 3,300,000 bytes > 2 MiB. Now replace_all is refused outright
    (T1 edits are single uniquely anchored replacements) BEFORE any
    dispatch, and the FileService dry_run cross-check proves the real
    result would indeed have been oversize."""
    from llm_loop.workspace.file_service import FileService

    events, event, target, plan = _crlf_setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        execution._t1_armed_ref = "artifact://v1/crlf-armed"
        args = {
            "path": "docs/target.md",
            "expected_snapshot_ref": "artifact://v1/crlf-armed",
            "old_string": "A\nX",
            "new_string": "A\n" + "Y" * 30,
            "replace_all": True,
        }
        before = target.read_bytes()
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_result_exceeds_size_bound"
            ),
            checked_tool_dispatch("edit_file", arguments=args),
        ):
            pytest.fail("oversize CRLF replace_all edit entered tool dispatch")
        assert target.read_bytes() == before  # zero bytes written
        # Ground truth the gate now refuses to even approach: the real
        # FileService result for these arguments is exactly the parent's
        # measured oversize figure.
        dry = FileService().edit(
            path=target,
            old_string="A\nX",
            new_string="A\n" + "Y" * 30,
            replace_all=True,
            dry_run=True,
        )
        assert len(dry.expected_after_bytes) == 3_300_000
        assert len(dry.expected_after_bytes) > 2 * 1024 * 1024
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_parent_p1_crlf_single_edit_bound_uses_normalized_count(tmp_path: Path) -> None:
    """Same CRLF fixture WITHOUT replace_all: the LF-normalized text still
    matches 'A\\nX' 100,000 times. Under the isomorphic gate this is now
    refused exactly like FileService.edit would (MultipleMatches) — a
    fail-closed preview, never a single-growth estimate. The pre-fix gate
    saw raw.count(old_b)==0 and would have passed straight through."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    events, event, target, plan = _crlf_setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        execution._t1_armed_ref = "artifact://v1/crlf-armed"
        args = {
            "path": "docs/target.md",
            "expected_snapshot_ref": "artifact://v1/crlf-armed",
            "old_string": "A\nX",
            "new_string": "A\n" + "Y" * 30,
        }
        before = target.read_bytes()
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_edit_multiple_matches_preview"
            ),
            checked_tool_dispatch("edit_file", arguments=args),
        ):
            pytest.fail("normalized-count-oversize edit entered tool dispatch")
        assert target.read_bytes() == before
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_parent_p1_bounded_single_edit_actual_size_verified(tmp_path: Path) -> None:
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    """Positive control: a genuinely small, uniquely anchored CRLF edit
    passes the gate, enters the tool dispatch scope, and the REAL applied
    result (FileService) stays within the 2 MiB bound — the parent asked
    for actual-result-size verification, not just rejections."""
    from llm_loop.workspace.file_service import FileService

    events, event, target, plan = _crlf_setup(tmp_path, repeat=3)
    target.write_bytes(b"A\r\nX\r\nA\r\nZ\r\nQ\r\nA\r\nX\r\n")
    raw_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan = T1WebEventPlan(
        session_id="web-t1", workspace_scope=exact_workspace_scope(str(tmp_path)),
        authorization_id="b" * 32, target_path="docs/target.md",
        prepared_target_sha256=raw_sha,
        valid_from_epoch_s=time.time() - 20, valid_until_epoch_s=time.time() + 600,
        event_store=events, budget_store=TaskBudgetStore(tmp_path / "ledger"),
    )
    event = events.append_durable_human_message(
        "web-t1",
        build_message_payload(
            index=1, role="user", source="user", content="unique anchor edit",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    execution = _open(plan, event, tmp_path, text="unique anchor edit")
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        execution._t1_armed_ref = "artifact://v1/crlf-armed"
        args = {
            "path": "docs/target.md",
            "expected_snapshot_ref": "artifact://v1/crlf-armed",
            "old_string": "Z\nQ",
            "new_string": "Z\n" + "y" * 10,
        }
        # Gate passes and the dispatch scope is entered (body is a no-op).
        with checked_tool_dispatch("edit_file", arguments=args):
            pass
        # Real application stays inside the bound and keeps CRLF.
        result = FileService().edit(
            path=target, old_string="Z\nQ", new_string="Z\n" + "y" * 10
        )
        assert result.applied is True
        after = target.read_bytes()
        assert after == result.actual_after_bytes
        assert len(after) <= 2 * 1024 * 1024
        assert b"Z\r\n" + b"y" * 10 in after
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)


def test_parent_f18_unpersisted_stop_unknown_liability_blocks_new_instance(
    tmp_path: Path,
) -> None:
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    """F18 replay: when a prior instance's durable stop write lost its CAS
    race (or never persisted), the root stays ACTIVE with an UNKNOWN
    liability. The same-instance local latch is valid and is NOT a defect
    (see test_transport_failure_latches_durable_stop_and_blocks_next_attempt
    for the persisted-stop path); the point is a FRESH execution instance
    bound to the same root — it must find the liability in the durable
    ledger and refuse its first reservation (fail-closed across the
    process boundary), instead of resuming spending on an encumbered root.
    """
    from llm_loop.resources.task_budget_contracts import TaskBudgetMember

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        with (
            pytest.raises(RuntimeError, match="synthetic tool failure"),
            checked_tool_dispatch(
                "read_file", arguments={"path": "docs/target.md", "snapshot": True}
            ),
        ):
            raise RuntimeError("synthetic tool failure")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    row = plan.budget_store.read(plan.budget_id)
    # No durable stop landed (the F18 premise: CAS lost / never persisted):
    # the root is still ACTIVE but carries an UNKNOWN liability.
    assert row["phase"] == "active"
    assert any(
        reservation["phase"] == "unknown"
        for reservation in row["reservations"].values()
    )
    fresh = T1WebBudgetExecution(
        store=plan.budget_store,
        budget_id=plan.budget_id,
        member=TaskBudgetMember.from_dict(row["members"][plan.budget_id]),
    )
    from llm_loop.resources.task_budget_t1_web_profile import bind_t1_web_plan

    # Rebind the plan wiring exactly as prepare_t1_web_event_budget does
    # (the restart path a fresh process would replay before first spend).
    fresh._t1_event_store = plan.event_store
    fresh._t1_workspace_root = str(tmp_path)
    fresh._t1_target_path = plan.target_path
    fresh._t1_target_sha = plan.prepared_target_sha256
    with bind_t1_web_plan(plan):
        token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
        bind_token = bind_task_budget(fresh)
        try:
            bind_token.__enter__()
            with (
                pytest.raises(
                    TaskBudgetDeniedError, match="t1_root_has_unsettled_liability"
                ),
                checked_tool_dispatch(
                    "read_file",
                    arguments={"path": "docs/target.md", "snapshot": True},
                ),
            ):
                pytest.fail("fresh instance resumed spending on an encumbered root")
        finally:
            bind_token.__exit__(None, None, None)
            current_write_scope.reset(token)


def _t1_route_app(build_test_engine, tmp_path: Path, monkeypatch, *, authenticated: bool):
    """Real FastAPI app + BackgroundRunner wiring for the T1 canary route.

    Reuses the cutover test template (tests/unit/test_task_budget_web_cutover.
    py::test_real_web_stream_passes_pinned_plan_to_background_runner): the
    operator-pinned T1 plan is installed on app.state exactly as
    load_operator_web_canary would, the runner is a spy, and zero real GLM
    is reachable. Returns (app, runner, canary, ledger_dir).
    """

    engine, _ = build_test_engine([])
    # A REAL registered session id (engine.session.create) — the route layer
    # resolves the session before the canary gate; a literal string id would
    # 404 session_not_found like any normal unknown session.
    plan, _target = _t1_engine_plan(
        tmp_path, engine, session_id=engine.session.create()
    )
    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    from llm_loop.web import auth, build_app
    from llm_loop.web import task_budget_canary as _web_canary

    # Same isolation as the cutover route test: hide any developer .env
    # canary config and pin the auth decision deterministically.
    monkeypatch.setattr(_web_canary, "business_config_snapshot", lambda _s: {})
    monkeypatch.setattr(auth, "request_authenticated", lambda _req: authenticated)
    app = build_app(engine=engine)
    app.state.task_budget_web_canary = canary
    runner = BackgroundRunner(engine)
    engine.runner = runner
    return app, runner, canary, tmp_path / "t1-ledger"


def test_t1_real_web_stream_passes_pinned_plan_to_background_runner(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parent review 07:11 item 1: the REAL HTTP route
    /api/v1/chat/stream dispatches the operator-pinned T1 plan to
    BackgroundRunner.start as signed_web_canary (TestClient; zero real GLM,
    runner.start is a spy so no Provider traffic can happen)."""
    from unittest import mock

    app, runner, canary, ledger_dir = _t1_route_app(
        build_test_engine, tmp_path, monkeypatch, authenticated=True
    )
    captured: list[object] = []

    def record(_sid: str, _text: str, **kwargs: object):
        captured.append(kwargs.get("signed_web_canary"))
        return None, None  # pre-start route test: no run side effect

    with mock.patch.object(runner, "start", side_effect=record):
        response = TestClient(app).post(
            "/api/v1/chat/stream",
            json={
                "session_id": canary.session_id,
                "message": "one limited request",
                "model": "glm/glm-5.3",
                "model_change": True,
            },
        )
    assert response.status_code == 200
    assert captured == [canary]
    assert isinstance(captured[0].plan, T1WebEventPlan)  # type: ignore[union-attr]
    # The sync route keeps refusing the budgeted session (stream-only).
    sync = TestClient(app).post(
        "/api/v1/chat",
        json={"session_id": canary.session_id, "message": "sync attempt"},
    )
    assert sync.status_code == 409
    assert sync.json()["error"] == "budget_canary_requires_stream"


@pytest.mark.parametrize(
    "model,queue_id,attachments,authenticated",
    [
        ("glm/glm-5.3", None, False, False),
        ("glm/glm-5.2", None, False, True),
        ("glm/glm-5.3", "q-unclaimed", False, True),
        ("glm/glm-5.3", None, True, True),
    ],
)
def test_t1_web_stream_route_denies_unqualified_requests(
    build_test_engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    queue_id: str | None,
    attachments: bool,
    authenticated: bool,
) -> None:
    """Unauthenticated, wrong-model, queued, or attachment-bearing requests
    against the T1 canary session are rejected before any run starts: zero
    BackgroundRunner dispatch, zero budget allocation (fail-closed at the
    route layer, on top of the choose_signed_web_canary gate matrix)."""
    from unittest import mock

    app, runner, canary, ledger_dir = _t1_route_app(
        build_test_engine, tmp_path, monkeypatch, authenticated=authenticated
    )
    body: dict[str, object] = {
        "session_id": canary.session_id,
        "message": "unqualified request",
        "model": model,
        "model_change": True,
    }
    if queue_id is not None:
        body["queue_id"] = queue_id
    if attachments:
        body["attachments"] = [{"ref": "attachment://" + "0" * 32}]
    captured: list[object] = []

    def record(_sid: str, _text: str, **kwargs: object):
        captured.append(kwargs.get("signed_web_canary"))
        return None, None

    with mock.patch.object(runner, "start", side_effect=record):
        response = TestClient(app).post("/api/v1/chat/stream", json=body)
    # All four are rejected before any run starts — some even earlier than
    # the canary gate: queue_id hits the queue-claim validation (409) and
    # attachments hit the attachment-ownership validation (400), both
    # fail-closed ahead of the 403 budget_canary_not_qualified gate.
    assert response.status_code in (400, 403, 409), response.text
    if queue_id is None and not attachments:
        assert response.json()["error"] == "budget_canary_not_qualified"
    assert captured == []
    assert not list(ledger_dir.glob("*.json"))


# -- parent cross-review 2026-11-14 07:21: single-flight & crash debt ------


def _reservations_of_kind(plan, kind_value: str) -> list[dict]:
    row = plan.budget_store.read(plan.budget_id)
    return [
        reservation
        for reservation in row["reservations"].values()
        if reservation.get("kind") == kind_value
    ]


def test_t1_nested_provider_scope_rejected_by_single_flight_gate(
    tmp_path: Path,
) -> None:
    """Parent finding ①: opening a SECOND provider send scope while the
    first is still unresolved used to admit both (physical reservations
    reached 2). The store-level single-flight hard gate denies the nested
    reserve inside the reserve CAS itself: one unresolved physical
    reservation at a time, no local latch involved."""
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    with (
        bind_task_budget(execution), _attempt_scope(_prepared()), pytest.raises(
            TaskBudgetDeniedError, match="t1_single_flight_provider_denied"
        ),
        _attempt_scope(_prepared()),
    ):
        pytest.fail("nested provider scope admitted a second attempt")
    physical = _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)
    assert len(physical) == 1
    # The outer scope settles with no matching EventStore evidence (nothing
    # was seeded), so its liability stays an open phase — never refunded.
    assert physical[0]["phase"] in {"dispatched", "unknown"}


def test_t1_crashed_dispatched_physical_denies_fresh_instances(
    tmp_path: Path,
) -> None:
    """Parent finding ②: a crash between reserve and settle leaves the root
    ACTIVE with the reservation DISPATCHED. Both a FRESH T1 execution and a
    raw store-level reserve on the same root must be denied — the single-
    flight gate lives in the durable reserve CAS, not in any process-local
    state, so crash debt can never be spent past."""
    from llm_loop.resources.task_budget_contracts import (
        BudgetDimension,
        TaskBudgetMember,
    )

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    # Reserve one physical attempt and "crash" before any settle.
    execution.note_prepared_request(_prepared())
    execution.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    row = plan.budget_store.read(plan.budget_id)
    assert row["phase"] == "active"
    assert _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)[0][
        "phase"
    ] == "dispatched"

    # (a) Raw store-level reserve — proves the gate is IN the store CAS and
    # would hold even for a hypothetical non-T1 execution instance.
    member = TaskBudgetMember.from_dict(row["members"][plan.budget_id])
    revision = row["revision"]
    with pytest.raises(
        TaskBudgetDeniedError, match="t1_single_flight_provider_denied"
    ):
        plan.budget_store.reserve(
            plan.budget_id,
            expected_revision=revision,
            member=member,
            reservation_id="dispatch-singleflight-probe",
            kind=BudgetDimension.PHYSICAL_ATTEMPTS,
            tool_id="",
            measures={
                BudgetDimension.INPUT_TOKENS: 2_100,
                BudgetDimension.OUTPUT_TOKENS: 128,
                BudgetDimension.PAYLOAD_BYTES: 1_000,
            },
        )

    # (b) A fresh T1 execution bound to the same store/member: its first
    # provider entry is refused (either the first-spend liability guard or
    # the store gate — both fail closed; neither may admit the entry).
    fresh = T1WebBudgetExecution(
        store=plan.budget_store,
        budget_id=plan.budget_id,
        member=member,
    )
    with bind_task_budget(fresh):
        fresh.note_prepared_request(_prepared())
        with pytest.raises(TaskBudgetDeniedError) as denied:
            fresh.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
        assert "t1_single_flight_provider_denied" in str(denied.value) or (
            "t1_root_has_unsettled_liability" in str(denied.value)
        )
    # Still exactly one physical reservation after both attempts.
    assert len(
        _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)
    ) == 1


def test_t1_local_stop_latch_blocks_same_instance_when_durable_cas_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parent finding ③: when the real request_stop durable CAS fails, the
    SAME execution instance must still be blocked by its local latch (set
    BEFORE the CAS write) — never fail-open within the instance. The
    cross-instance exposure is exactly what the store-level single-flight
    gate above now closes durable-side."""
    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)

    def failing_request_stop(*args: object, **kwargs: object) -> None:
        raise TaskBudgetConflictError("stale budget revision CAS: injected")

    monkeypatch.setattr(plan.budget_store, "request_stop", failing_request_stop)
    # The durable write exhausts its CAS retries and raises — that IS the
    # "durable stop write failed" premise of parent finding ③.
    with pytest.raises(TaskBudgetDeniedError, match="cas_contention_exhausted"):
        execution.request_stop(reason="local_latch_probe")
    monkeypatch.undo()
    # The durable write failed and the root stays ACTIVE — but the local
    # latch (set before the CAS) still blocks this same instance.
    assert plan.budget_store.read(plan.budget_id)["phase"] == "active"
    with pytest.raises(TaskBudgetDeniedError):
        execution.assert_tool_allowed("read_file")
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    execution.note_prepared_request(_prepared())
    with pytest.raises(TaskBudgetDeniedError):
        execution.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)


def test_t1_nested_tool_scopes_rejected_by_single_flight_gate(
    tmp_path: Path,
) -> None:
    """Parent finding ④: two nested read_file(snapshot) tool scopes used to
    admit both (tool reservations reached 2). The store-level single-flight
    gate treats tool invocations the same way: one unresolved tool
    reservation at a time (serial read -> edit -> read stays legal because
    each settles before the next reserves)."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        arguments = {"path": "docs/target.md", "snapshot": True}
        with (
            checked_tool_dispatch("read_file", arguments=arguments), pytest.raises(
                TaskBudgetDeniedError, match="t1_single_flight_tool_denied"
            ),
            checked_tool_dispatch("read_file", arguments=arguments),
        ):
            pytest.fail("nested tool scope admitted a second reservation")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    tools = _reservations_of_kind(plan, BudgetDimension.TOOL_INVOCATIONS.value)
    assert len(tools) == 1
    # The interrupted outer read never reported completion: its liability
    # stays open (unknown), never upgraded, never refunded.
    assert tools[0]["phase"] in {"reserved", "dispatched", "unknown"}


# -- parent review 2026-11-14 07:41: full-stack chained e2e (P1-6) ---------


def test_t1_full_stack_stream_route_real_runner_real_llmclient_synthetic_sse(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parent 07:41 gap closure: ONE chained offline e2e — real TestClient
    POST /api/v1/chat/stream -> REAL BackgroundRunner.start (real daemon
    thread; the production signed_web_canary.bind scope from runner._consume)
    -> REAL engine.run_stream -> REAL LLMClient parsing synthetic SSE frames
    -> T1 plan binding, budget ledger, EventStore journal and the controlled
    edit artifact. Zero real GLM: only the module-level provider transport
    function is stubbed (same synthetic isolation as the P1-4 engine-scope
    e2e); BackgroundRunner.start is NOT spied, patched, or replaced here —
    this closes the "two segments, no single-chain evidence" gap between
    test_t1_engine_scope_e2e_synthetic_provider_stream and
    test_t1_real_web_stream_passes_pinned_plan_to_background_runner.
    """
    import llm_loop.llm.client as client_mod
    from llm_loop.llm.client import LLMClient
    from llm_loop.resources.provider_calls import ProviderCallCoordinator
    from llm_loop.resources.provider_settlement import (
        ProviderCallSettlementJournal,
    )
    from llm_loop.resources.transport_observation import ShadowTransportRecorder
    from llm_loop.tools.builtin.edit_file import EditFileTool
    from llm_loop.tools.builtin.read_file import ReadFileTool
    from llm_loop.workspace.artifacts import WorkspaceArtifactStore
    from llm_loop.workspace.file_service import FileService

    engine, _fake = build_test_engine([])
    # A REAL registered session id: the route layer resolves the session
    # before the canary gate (a literal string id would 404).
    sid = engine.session.create()
    plan, target = _t1_engine_plan(tmp_path, engine, session_id=sid)

    # Production tool wiring (same as P1-4): factory-style shared
    # WorkspaceArtifactStore + FileService so read_file(snapshot=True) and
    # the four-stage edit_file with version precondition work for real.
    _artifacts = WorkspaceArtifactStore(str(tmp_path / "t1-artifacts"))
    _files = FileService(
        artifact_store=_artifacts, lock_root=tmp_path / "t1-file-locks"
    )
    engine.registry.register(
        ReadFileTool(artifact_store=_artifacts, file_service=_files)
    )
    engine.registry.register(
        EditFileTool(
            artifact_store=_artifacts,
            file_service=_files,
            require_version_precondition=True,
        )
    )
    # Production settlement journal + shadow-call correlation over the run's
    # EventStore; the real LLMClient reports every transport open/settle.
    journal = ProviderCallSettlementJournal(engine._event_store, projection_sink=None)
    observer = ShadowTransportRecorder()
    observer.set_settlement_journal(journal)
    engine.provider_call_coordinator = ProviderCallCoordinator(
        # Shadow calls never touch admission; the typed governor slot is
        # irrelevant for the synthetic correlation path under test.
        governor=None,  # type: ignore[arg-type]
        local_runtime=None,
        settlement_journal=journal,
    )
    client = LLMClient(
        api_key="k",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-5.3",
        provider="glm",
        max_tokens=3000,
        trust_env=False,
    )
    client.transport_observer = observer
    # Route the engine at the REAL client (pool bypassed, as lifecycle does
    # when no pool is installed).
    engine.llm_pool = None
    engine.llm = client

    state: dict[str, Any] = {"round": 0, "armed_ref": None}

    # Same arm-hook spy as P1-4: the real note_t1_read_result still runs; the
    # spy only records the armed ref so the synthetic edit round presents
    # exactly what the live execution object armed.
    from llm_loop.resources.task_budget_t1_web_profile import (
        T1WebBudgetExecution,
    )

    _orig_note = T1WebBudgetExecution.note_t1_read_result

    def _spy_note(self, arguments, artifact_facts):  # noqa: ANN001, ANN202
        _orig_note(self, arguments, artifact_facts)
        state["armed_ref"] = self._t1_armed_ref

    monkeypatch.setattr(T1WebBudgetExecution, "note_t1_read_result", _spy_note)

    def _edit_arguments() -> str:
        armed = state["armed_ref"]
        assert armed, "read round did not arm the edit gate"
        return json.dumps(
            {
                "path": "docs/target.md",
                "expected_snapshot_ref": armed,
                "old_string": "2026-11-06",
                "new_string": "2026-11-13",
            }
        )

    def _final_round() -> list[str]:
        return [
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [
                        {"index": 0, "delta": {"content": "done."}, "finish_reason": None}
                    ],
                }
            ),
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            ),
            _sse(
                {
                    "model": "glm-5.3",
                    "choices": [],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 12, "prompt_tokens_details": {"cached_tokens": 0}},
                }
            ),
        ]

    def _synthetic_post(_http, method, url, **kwargs):  # noqa: ANN001, ANN202
        state["round"] += 1
        if state["round"] == 1:
            lines = _tool_round(
                "call-read",
                "read_file",
                json.dumps({"path": "docs/target.md", "snapshot": True}),
            )
        elif state["round"] == 2:
            lines = _tool_round("call-edit", "edit_file", _edit_arguments())
        else:
            lines = _final_round()
        return _SyntheticSSE(lines)

    monkeypatch.setattr(client_mod, "_task_budget_provider_stream", _synthetic_post)

    # App assembly identical to _t1_route_app, except BackgroundRunner.start
    # stays REAL: the route dispatches into a real daemon thread which binds
    # the signed canary and consumes engine.run_stream.
    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    from llm_loop.web import auth, build_app
    from llm_loop.web import task_budget_canary as _web_canary

    monkeypatch.setattr(_web_canary, "business_config_snapshot", lambda _s: {})
    monkeypatch.setattr(auth, "request_authenticated", lambda _req: True)
    app = build_app(engine=engine)
    app.state.task_budget_web_canary = canary
    runner = BackgroundRunner(engine)
    engine.runner = runner

    response = TestClient(app).post(
        "/api/v1/chat/stream",
        json={
            "session_id": canary.session_id,
            "message": "apply the approved date edit",
            "model": "glm/glm-5.3",
            "model_change": True,
        },
    )
    # The SSE stream completed through the real chain: a run_started frame,
    # visible tool rounds, a terminal done frame, and zero error frames.
    # (Wire framing is `data: {"type": ..., "data": ...}` envelopes.)
    assert response.status_code == 200, response.text
    frames = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    frame_types = [frame.get("type") for frame in frames]
    assert frame_types[:1] == ["run_started"], frame_types
    assert "tool_round" in frame_types, frame_types
    assert frame_types[-1] == "done", frame_types
    assert "error" not in frame_types, frame_types

    # 1) The run REALLY went through the provider three times via the real
    # route -> runner daemon thread -> engine -> LLMClient chain.
    assert state["round"] == 3
    # 2) The controlled edit really landed on the target file.
    assert "2026-11-13" in target.read_text(encoding="utf-8")
    # 3) The EventStore carries the full production transport chain.
    events = engine._event_store.read(plan.session_id)
    kinds = [event.type for event in events]
    assert kinds.count("provider.transport.opened") == 3
    assert kinds.count("provider.transport.settled") == 3
    # 4) The budget ledger settled everything with real joins (T1 plan
    # binding: the ledger row is the plan's own budget root).
    ledger_files = list((tmp_path / "t1-ledger").glob("*.json"))
    assert len(ledger_files) == 1
    row = json.loads(ledger_files[0].read_text())
    kinds_by_res: dict[str, list[dict]] = {}
    for rid, res in row["reservations"].items():
        kinds_by_res.setdefault(res["kind"], []).append(res)
        assert res["phase"] == "settled", (rid, res["phase"])
        assert res["outcome"] == "success"
    assert len(kinds_by_res.get("physical_attempts", [])) == 3
    assert len(kinds_by_res.get("tool_invocations", [])) == 2
    # 5) Physical allocations are the OBSERVED synthetic usage figures.
    observed_input = sorted(
        res["allocations"]["input_tokens"]
        for res in kinds_by_res["physical_attempts"]
    )
    assert observed_input == [90, 120, 120]
    # 6) Every settled physical reservation binds the EventStore event.
    for res in kinds_by_res["physical_attempts"]:
        assert res["receipt_ref"].startswith("webt1ev:")


# --- Parent cross-review 2026-11-14 07:44: P1-A (F18 operator revocation)
# --- and P1-B (global cross-kind single-flight) fail-closed negatives. ---


def _loader_plan(tmp_path: Path, monkeypatch, *, sid: str = "web-t1"):
    """Build a REAL loader-backed plan whose revocation facts are armed.

    Writes the 0600 operator config, loads it through the production
    ``load_operator_web_canary`` (which pins the exact bytes' sha256), and
    returns ``(plan, config_path)``. Deleting or rotating ``config_path``
    afterwards is exactly the operator revocation under test.
    """
    import llm_loop.web.task_budget_canary as canary_module
    from llm_loop.web.task_budget_canary import load_operator_web_canary

    events, event, target, plan = _setup(tmp_path, sid=sid)
    config_path = tmp_path / "t1.json"
    now = time.time()
    config_path.write_text(json.dumps({
        "schema": CONFIG_SCHEMA, "authorization_id": "b" * 32,
        "session_id": sid, "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3", "target_path": "docs/target.md",
        "prepared_target_sha256": plan.prepared_target_sha256,
        "valid_from_epoch_s": now - 10, "valid_until_epoch_s": now + 600,
    }))
    os.chmod(config_path, 0o600)
    monkeypatch.setattr(
        canary_module,
        "business_config_snapshot",
        lambda service: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(config_path)},
    )
    engine = SimpleNamespace(
        session=SimpleNamespace(exists=lambda s: s == sid),
        workspace_root=str(tmp_path),
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _event_store=events,
        runner=SimpleNamespace(enabled=True, is_cancelled=lambda s: False),
    )
    canary = load_operator_web_canary(engine)
    assert isinstance(canary, WebTaskBudgetCanary)
    assert isinstance(canary.plan, T1WebEventPlan)
    plan = canary.plan
    assert plan.operator_config_path == str(config_path)
    return events, event, target, plan, config_path


def _request_for(canary, *, sid: str = "web-t1"):
    from starlette.applications import Starlette
    from starlette.requests import Request

    app = Starlette()
    app.state.task_budget_web_canary = canary
    return Request({
        "type": "http", "app": app, "method": "POST",
        "path": "/api/v1/chat/stream", "scheme": "http",
        "headers": [(b"host", b"127.0.0.1:1"), (b"authorization", b"Bearer unit-key")],
        "server": ("127.0.0.1", 1), "client": ("127.0.0.1", 1),
        "query_string": b"",
    })


def test_t1_operator_config_deletion_denies_new_run_and_prepare(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A: unlinking the 0600 operator config revokes the cached plan.

    Both the web entry (choose_signed_web_canary) and a direct
    prepare_t1_web_event_budget must deny after deletion — the startup
    cache may never outlive its authorization."""
    from llm_loop.web.task_budget_canary import (
        WebTaskBudgetCanary,
        choose_signed_web_canary,
    )

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    monkeypatch.setenv("WEB_API_KEY", "unit-key")
    request = _request_for(canary)
    # Sanity: the config still exists, selection works.
    chosen = choose_signed_web_canary(
        request, "web-t1", model="glm/glm-5.3",
        resume=False, queued=False, attachments=False,
    )
    assert chosen is canary
    # Operator deletes the config file: authorization revoked.
    config_path.unlink()
    with pytest.raises(TaskBudgetDeniedError):
        choose_signed_web_canary(
            request, "web-t1", model="glm/glm-5.3",
            resume=False, queued=False, attachments=False,
        )
    with pytest.raises(TaskBudgetDeniedError, match="t1_operator_canary_revoked"):
        prepare_t1_web_event_budget(
            plan=plan, event=event, session_id="web-t1",
            workspace_root=str(tmp_path), run_generation="run-1",
            user_text="do the T1 edit", ingress=issue_ingress("web"),
        )
    # No new budget root was issued for the denied run.
    roots = list((tmp_path / "data" / "task_budget_t1_web").glob("*"))
    assert all(p.suffix == ".lock" for p in roots)


def test_t1_revocation_between_read_and_edit_stops_durably(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A: revocation between two tool actions stops the root durably.

    The first read_file settles; the operator then deletes the config; the
    next action (edit_file reserve) is denied with a durable stop — and a
    FRESH execution instance on the same store stays denied too."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        arguments = {"path": "docs/target.md", "snapshot": True}
        with checked_tool_dispatch("read_file", arguments=arguments) as outcome:
            outcome["complete"] = True  # real engine sets this on success
        execution.note_t1_read_result(
            arguments, ({"artifact_ref": "artifact://v1/revoked-mid-run"},)
        )
        config_path.unlink()  # operator revokes mid-run
        with (
            pytest.raises(
                TaskBudgetDeniedError, match="t1_operator_canary_revoked"
            ),
            checked_tool_dispatch(
                "edit_file",
                arguments={
                    "path": "docs/target.md", "old_string": "2026-11-06",
                    "new_string": "2026-11-13",
                    "expected_snapshot_ref": "artifact://v1/revoked-mid-run",
                },
            ),
        ):
            pytest.fail("revoked authorization admitted a further action")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    row = plan.budget_store.read(execution.budget_id)
    assert row["phase"] == "stop_requested"
    # Durable across restart: a fresh execution on the same root is denied.
    fresh = _open.__wrapped__(plan, event, tmp_path) if hasattr(_open, "__wrapped__") else None
    assert fresh is None  # _open re-issues a NEW root; the stopped root is separate
    with pytest.raises(TaskBudgetDeniedError):
        execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="read_file")


def test_t1_revocation_survives_process_restart(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A + 08:01 ruling: configured-but-deleted config => typed fail-closed.

    A NEW process calling ``load_operator_web_canary`` must NOT get None:
    an invisible OFF would let the previously restricted session fall back
    to the unbudgeted default path (fail-OPEN). The typed error fails the
    ``build_app`` call itself, and the previously stopped root keeps
    denying every action through the durable store phase."""
    from llm_loop.resources.task_budget_contracts import BudgetDimension
    from llm_loop.web.task_budget_canary import (
        TaskBudgetCanaryConfigMissingError,
        load_operator_web_canary,
    )

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    execution = _open(plan, event, tmp_path)
    config_path.unlink()
    engine = SimpleNamespace(
        session=SimpleNamespace(exists=lambda s: s == "web-t1"),
        workspace_root=str(tmp_path),
        settings=SimpleNamespace(data_dir=str(tmp_path / "data")),
        _event_store=events,
        runner=SimpleNamespace(enabled=True, is_cancelled=lambda s: False),
    )
    with pytest.raises(TaskBudgetCanaryConfigMissingError):
        load_operator_web_canary(engine)
    # And the run-level revocation stop is durable for the issued root.
    config_path.write_text("{}")  # rotated bytes never restore authority
    with pytest.raises(TaskBudgetDeniedError):
        execution.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)


def test_t1_configured_but_missing_config_fails_build_app_closed(
    build_test_engine: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """08:01 ruling: the typed error propagates through the REAL build_app.

    With the canary config path configured but the artifact gone, the Web
    process must refuse to boot (fail-closed startup) instead of silently
    running the default path while a previously restricted session loses
    its Run fence."""
    from llm_loop.web import build_app
    from llm_loop.web import task_budget_canary as _web_canary
    from llm_loop.web.task_budget_canary import TaskBudgetCanaryConfigMissingError

    engine, _ = build_test_engine([])
    monkeypatch.setattr(
        _web_canary,
        "business_config_snapshot",
        lambda _scope: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(tmp_path / "gone.json")},
    )
    with pytest.raises(TaskBudgetCanaryConfigMissingError):
        build_app(engine=engine)


def test_t1_operator_config_rotation_is_revocation(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A: a rotated operator config (any byte change) revokes too —
    the pinned sha256 must match verbatim, not just the file's presence."""
    from llm_loop.web.task_budget_canary import (
        WebTaskBudgetCanary,
        choose_signed_web_canary,
    )

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    monkeypatch.setenv("WEB_API_KEY", "unit-key")
    request = _request_for(canary)
    now = time.time()
    config_path.write_text(json.dumps({
        "schema": CONFIG_SCHEMA, "authorization_id": "c" * 32,
        "session_id": "web-t1", "workspace_root": str(tmp_path),
        "model_ref": "glm/glm-5.3", "target_path": "docs/target.md",
        "prepared_target_sha256": plan.prepared_target_sha256,
        "valid_from_epoch_s": now - 10, "valid_until_epoch_s": now + 600,
    }))
    os.chmod(config_path, 0o600)
    with pytest.raises(TaskBudgetDeniedError):
        choose_signed_web_canary(
            request, "web-t1", model="glm/glm-5.3",
            resume=False, queued=False, attachments=False,
        )


def test_t1_revocation_stop_is_idempotent_on_already_stopped_root(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A CAS semantics: when the root is ALREADY stopped for another
    reason, the revocation latch's request_stop conflicts are suppressed —
    the action is still denied and the first stop reason stays recorded."""
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    execution = _open(plan, event, tmp_path)
    execution.request_stop(reason="owner_revoked")  # durable stop first
    config_path.unlink()
    # The revocation gate must not crash on the conflict CAS: it denies.
    with pytest.raises(TaskBudgetDeniedError, match="t1_operator_canary_revoked"):
        execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="read_file")
    row = plan.budget_store.read(execution.budget_id)
    assert row["phase"] == "stop_requested"
    assert row["stop_reason"] == "owner_revoked"


def test_t1_provider_open_rejects_nested_tool_across_kinds(
    tmp_path: Path,
) -> None:
    """P1-B: a tool dispatch inside a STILL-OPEN provider scope is denied.

    The single-flight gate is GLOBAL across action kinds: with one
    unresolved physical reservation, a nested checked_tool_dispatch
    (read_file) is rejected in the same reserve CAS and never opens a tool
    reservation; the provider liability stays unresolved, never refunded."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        arguments = {"path": "docs/target.md", "snapshot": True}
        with (
            _attempt_scope(_prepared()),
            pytest.raises(
                TaskBudgetDeniedError, match="t1_single_flight_tool_denied"
            ),
            checked_tool_dispatch("read_file", arguments=arguments),
        ):
            pytest.fail("tool scope admitted while provider scope open")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    physical = _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)
    tools = _reservations_of_kind(plan, BudgetDimension.TOOL_INVOCATIONS.value)
    assert len(physical) == 1 and physical[0]["phase"] in {
        "dispatched", "unknown",
    }
    assert tools == []  # the nested tool reservation never existed


def test_t1_tool_open_rejects_nested_provider_across_kinds(
    tmp_path: Path,
) -> None:
    """P1-B mirror: a provider send inside a STILL-OPEN tool scope is
    denied by the same global gate (provider reserve rejected, the open
    tool liability stays unresolved)."""
    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        arguments = {"path": "docs/target.md", "snapshot": True}
        with (
            checked_tool_dispatch("read_file", arguments=arguments),
            pytest.raises(
                TaskBudgetDeniedError, match="t1_single_flight_provider_denied"
            ),
            _attempt_scope(_prepared()),
        ):
            pytest.fail("provider scope admitted while tool scope open")
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    tools = _reservations_of_kind(plan, BudgetDimension.TOOL_INVOCATIONS.value)
    physical = _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)
    assert len(tools) == 1 and tools[0]["phase"] in {"dispatched", "unknown"}
    assert physical == []


def test_t1_serial_mixed_provider_tool_flow_passes_global_gate(
    tmp_path: Path,
) -> None:
    """P1-B legality proof: the REAL engine ordering — provider settles,
    then a tool runs and settles, then the next provider — never holds two
    open action reservations, so the global gate stays open for it."""

    from llm_loop.core.run_context import current_write_scope
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.resources.task_budget_contracts import BudgetDimension

    events, event, target, plan = _setup(tmp_path)
    execution = _open(plan, event, tmp_path)
    token = current_write_scope.set(WriteScope(paths=("docs/target.md",)))
    bind_token = bind_task_budget(execution)
    try:
        bind_token.__enter__()
        for _ in range(3):
            attempt = _attempt()
            _seed_transport(events, "web-t1", attempt, usage_in=90)
            with _attempt_scope(_prepared()):
                pass  # reserves, dispatches, and settles with seeded evidence
        read_args = {"path": "docs/target.md", "snapshot": True}
        with checked_tool_dispatch("read_file", arguments=read_args) as outcome:
            outcome["complete"] = True  # real engine sets this on success
        execution.note_t1_read_result(
            read_args, ({"artifact_ref": "artifact://v1/serial-mixed"},)
        )
        with checked_tool_dispatch(
            "edit_file",
            arguments={
                "path": "docs/target.md",
                "old_string": "2026-11-06",
                "new_string": "2026-11-13",
                "expected_snapshot_ref": "artifact://v1/serial-mixed",
            },
        ) as outcome:
            outcome["complete"] = True
    finally:
        bind_token.__exit__(None, None, None)
        current_write_scope.reset(token)
    physical = _reservations_of_kind(plan, BudgetDimension.PHYSICAL_ATTEMPTS.value)
    tools = _reservations_of_kind(plan, BudgetDimension.TOOL_INVOCATIONS.value)
    assert len(physical) == 3 and all(r["phase"] == "settled" for r in physical)
    assert len(tools) == 2 and all(r["phase"] == "settled" for r in tools)


# --- Parent cross-review 2026-11-14 07:50: the F18 revocation re-check must
# --- validate the FULL startup artifact identity, not just readable bytes. ---


def test_t1_operator_config_identity_relaxation_is_revocation(
    tmp_path: Path, monkeypatch,
) -> None:
    """P1-A (07:50): chmod-0644, a byte-identical symlink swap, a hardlink
    bump, a FIFO, and an oversized artifact all revoke — even when the
    pinned sha256 would still match whatever ``read_bytes`` would return.

    Parent-side TemporaryDirectory probes showed the previous bytes-only
    comparison missed exactly these: the same inode with relaxed perms, and
    an unlink+symlink pointing at another 0600 file holding byte-identical
    content. The re-check now reuses the ``_read_operator_config``
    contract: O_NOFOLLOW (symlink -> ELOOP), fstat S_ISREG / owner in
    {root, euid} / mode & 0o077 == 0 / nlink == 1 / size <= 16 KiB, one
    bounded read (O_NONBLOCK so a FIFO never waits for a writer), then the
    sha256 comparison."""
    from llm_loop.web.task_budget_canary import (
        WebTaskBudgetCanary,
        choose_signed_web_canary,
    )

    events, event, target, plan, config_path = _loader_plan(tmp_path, monkeypatch)
    canary = WebTaskBudgetCanary(session_id=plan.session_id, plan=plan)
    monkeypatch.setenv("WEB_API_KEY", "unit-key")
    request = _request_for(canary)

    def _assert_fence_denies() -> None:
        with pytest.raises(TaskBudgetDeniedError):
            choose_signed_web_canary(
                request, "web-t1", model="glm/glm-5.3",
                resume=False, queued=False, attachments=False,
            )

    # 0) Baseline: the untouched 0600 regular artifact stays authorized.
    assert not plan.operator_revoked()

    # 1) chmod 0644 — same inode, same bytes, relaxed perms: revoked.
    os.chmod(config_path, 0o644)
    assert plan.operator_revoked()
    _assert_fence_denies()
    os.chmod(config_path, 0o600)
    assert not plan.operator_revoked()  # restored identity reauthorizes

    # 2) unlink + symlink to a byte-identical 0600 twin: revoked via
    #    O_NOFOLLOW even though the readable bytes hash identically.
    twin = tmp_path / "twin.json"
    original = config_path.read_bytes()
    twin.write_bytes(original)
    os.chmod(twin, 0o600)
    config_path.unlink()
    config_path.symlink_to(twin)
    assert plan.operator_revoked()
    _assert_fence_denies()
    config_path.unlink()
    config_path.write_bytes(original)
    os.chmod(config_path, 0o600)
    assert not plan.operator_revoked()

    # 3) hardlink bump: nlink != 1 with identical bytes is revoked.
    link = tmp_path / "hardlink.json"
    os.link(config_path, link)
    assert plan.operator_revoked()
    _assert_fence_denies()
    link.unlink()
    assert not plan.operator_revoked()

    # 4) FIFO at the pinned path: O_NONBLOCK open + S_ISREG check revoke
    #    immediately (never blocks waiting for a writer, never reads).
    config_path.unlink()
    os.mkfifo(config_path, 0o600)
    assert plan.operator_revoked()
    _assert_fence_denies()

    # 5) oversized artifact (>16 KiB): rejected from fstat before any read.
    config_path.unlink()
    config_path.write_text("x" * 16385)
    os.chmod(config_path, 0o600)
    assert plan.operator_revoked()
    _assert_fence_denies()


def test_t1_build_app_autowires_real_operator_config_loader_to_fence(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-A (07:50): the REAL loader→fence chain over ``build_app``.

    Unlike the route tests that install a hand-built plan on app.state,
    this test wires a REAL 0600 operator config through the production
    startup path: ``build_app`` itself calls ``load_operator_web_canary``
    (web/__init__ wiring), which validates the artifact identity, pins the
    sha256 fingerprint, and mounts the T1 plan. The HTTP fence then admits
    the pinned session on that same app instance — and a chmod-0644
    relaxation mid-flight makes the SAME app instance refuse the next
    request through the per-request identity re-check (no process restart,
    no manual state injection anywhere)."""
    from unittest import mock

    from fastapi.testclient import TestClient

    from llm_loop.web import auth, build_app
    from llm_loop.web import task_budget_canary as canary_module
    from llm_loop.web.task_budget_canary import WebTaskBudgetCanary

    engine, _ = build_test_engine([])
    sid = engine.session.create()
    engine._event_store = EventStore(tmp_path / "t1-events")
    # build_test_engine leaves engine.workspace_root empty; the loader
    # compares it verbatim against the config, so point both at one real
    # scratch workspace under tmp_path.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    engine.workspace_root = str(workspace)
    (workspace / "docs").mkdir(parents=True, exist_ok=True)
    target = workspace / "docs" / "target.md"
    target.write_text("# T1 target\n- Review window opens: 2026-11-06\n")
    config_path = tmp_path / "t1-operator.json"
    now = time.time()
    config_path.write_text(json.dumps({
        "schema": CONFIG_SCHEMA,
        "authorization_id": "d" * 32,
        "session_id": sid,
        "workspace_root": str(workspace),
        "model_ref": "glm/glm-5.3",
        "target_path": "docs/target.md",
        "prepared_target_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "valid_from_epoch_s": now - 20,
        "valid_until_epoch_s": now + 600,
    }))
    os.chmod(config_path, 0o600)
    monkeypatch.setattr(
        canary_module,
        "business_config_snapshot",
        lambda _s: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG": str(config_path)},
    )
    # The loader gate requires a live runner BEFORE build_app runs.
    runner = BackgroundRunner(engine)
    engine.runner = runner
    app = build_app(engine=engine)
    canary = app.state.task_budget_web_canary
    assert isinstance(canary, WebTaskBudgetCanary)
    plan = canary.plan
    assert isinstance(plan, T1WebEventPlan)
    assert plan.session_id == sid
    assert plan.operator_config_path == str(config_path.resolve())
    assert plan.operator_config_sha256 == hashlib.sha256(
        config_path.read_bytes()
    ).hexdigest()
    assert not plan.operator_revoked()
    # The HTTP fence admits the pinned session on this app instance.
    monkeypatch.setattr(auth, "request_authenticated", lambda _req: True)
    captured: list[object] = []

    def record(_sid: str, _text: str, **kwargs: object):
        captured.append(kwargs.get("signed_web_canary"))
        return None, None  # pre-start probe: no run side effect

    with mock.patch.object(runner, "start", side_effect=record):
        admitted = TestClient(app).post(
            "/api/v1/chat/stream",
            json={
                "session_id": sid,
                "message": "one limited request",
                "model": "glm/glm-5.3",
                "model_change": True,
            },
        )
    assert admitted.status_code == 200
    assert captured == [canary]
    # Mid-flight identity relaxation: the SAME app instance now refuses.
    os.chmod(config_path, 0o644)
    assert plan.operator_revoked()
    with mock.patch.object(runner, "start", side_effect=record):
        refused = TestClient(app).post(
            "/api/v1/chat/stream",
            json={
                "session_id": sid,
                "message": "second request after relaxation",
                "model": "glm/glm-5.3",
                "model_change": True,
            },
        )
    assert refused.status_code != 200
    assert len(captured) == 1  # the runner never saw the revoked request
