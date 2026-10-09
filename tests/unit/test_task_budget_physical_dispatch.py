"""I2/I3 real transport / ToolRegistry pre-dispatch tests. HTTP is mocked."""

# ruff: noqa: SIM117 - nested scopes deliberately distinguish scope admission from action errors

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from unittest import mock

import httpx
import pytest

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension as D,
)
from llm_loop.resources.task_budget_contracts import (
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import (
    TaskBudgetExecution,
    active_task_budget,
    bind_task_budget,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetDeniedError,
    TaskBudgetStore,
)
from llm_loop.tools.registry import ToolRegistry

_OK_LINES = (
    'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
    "data: [DONE]",
)
_EMPTY_LINES = ('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}', "data: [DONE]")


def _bound(
    tmp_path: Path, *,
    physical: int = 1,
    tool: int = 0,
    allowed: frozenset[str] | None = frozenset(),
    allow_wake: bool = False,
) -> TaskBudgetExecution:
    store = TaskBudgetStore(tmp_path / "budget", clock=lambda: 1000.0)
    grant = TaskBudgetGrant(
        budget_id="budget-phys",
        issuer="offline-operator",
        authority_source="offline-unit",
        workspace_scope="unit-workspace",
        session_id="unit-session",
        human_turn_ref="human-turn-1",
        surface="offline_test",
        profile="smoke",
        policy_version="I2-v1",
        deadline_epoch_s=5000.0,
        limits=TaskBudgetLimits(
            logical_calls=1,
            physical_attempts=physical,
            rounds=1,
            tool_invocations=tool,
        ),
        capabilities=TaskBudgetCapabilities(
            allowed_tools=allowed,
            allow_wake=allow_wake,
        ),
    )
    store.issue_root(grant, root_run_generation="test-run-1", ingress_kind="web")
    store.activate(grant.budget_id, expected_revision=1)
    root = TaskBudgetMember.from_dict(
        store.read(grant.budget_id)["members"][grant.budget_id]
    )
    return TaskBudgetExecution(store=store, budget_id=grant.budget_id, member=root)


class _FakeStream:
    def __init__(self, lines: tuple[str, ...], *, failure: Exception | None = None) -> None:
        self.lines = lines
        self.failure = failure
        self.headers: dict[str, str] = {}
        self.status_code = 200
        self.reason_phrase = "OK"

    def __enter__(self) -> _FakeStream:
        if self.failure is not None:
            raise self.failure
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def iter_lines(self):
        yield from self.lines

    def read(self) -> bytes:
        return b""


def _client(
    stream: _FakeStream, *, protocol: str = "openai"
) -> tuple[LLMClient, mock.MagicMock]:
    with mock.patch("httpx.Client") as client_cls:
        transport = client_cls.return_value
        transport.stream.return_value = stream
        client = LLMClient(
            api_key="k",
            base_url="https://never-usable.invalid/v1",
            model="glm-5.3",
            provider="glm",
            wire_protocol=protocol,
            timeout_s=4.0,
            thinking_mode=False,
            max_tokens=32,
        )
    return client, transport


def _once(client: LLMClient) -> str:
    response = client.chat(
        messages=[{"role": "user", "content": "offline physical test"}],
        tools=[],
    )
    return response.content or ""


def test_no_bound_grant_keeps_legacy_provider_wire_and_transport() -> None:
    client, transport = _client(_FakeStream(_OK_LINES))
    assert active_task_budget() is None
    assert _once(client) == "ok"
    assert transport.stream.call_count == 1


def test_one_physical_attempt_bound_denies_second_http_send(tmp_path: Path) -> None:
    execution = _bound(tmp_path)
    client, transport = _client(_FakeStream(_OK_LINES))
    with bind_task_budget(execution):
        assert _once(client) == "ok"
        with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"):
            _once(client)
    assert transport.stream.call_count == 1
    report = execution.store.report(execution.budget_id)
    assert report["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1
    assert len(report["outstanding_or_unknown"]) == 1
    assert report["physical_quiescence_verified"] is False
    assert active_task_budget() is None


def test_empty_response_retry_reenters_transport_gate_and_is_denied(tmp_path: Path, monkeypatch) -> None:
    execution = _bound(tmp_path)
    client, transport = _client(_FakeStream(_EMPTY_LINES))
    monkeypatch.setattr(time, "sleep", lambda *_args: None)
    with bind_task_budget(execution):
        with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted"):
            _once(client)
    assert transport.stream.call_count == 1
    assert len(execution.store.read(execution.budget_id)["reservations"]) == 1


def test_disconnect_retry_cannot_silently_dial_again(tmp_path: Path, monkeypatch) -> None:
    execution = _bound(tmp_path)
    client, transport = _client(
        _FakeStream((), failure=httpx.ConnectError("offline injected failure"))
    )
    monkeypatch.setattr(time, "sleep", lambda *_args: None)
    with bind_task_budget(execution):
        with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted"):
            _once(client)
    assert transport.stream.call_count == 1
    assert execution.store.report(execution.budget_id)["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1


def test_provider_attempt_is_blocked_on_stopped_budget(tmp_path: Path) -> None:
    execution = _bound(tmp_path)
    row = execution.store.read(execution.budget_id)
    execution.store.request_stop(
        execution.budget_id, expected_revision=row["revision"], reason="owner_stop"
    )
    client, transport = _client(_FakeStream(_OK_LINES))
    with pytest.raises(TaskBudgetDeniedError, match="budget_not_active"):
        with bind_task_budget(execution):
            _once(client)
    assert transport.stream.call_count == 0


class _SideEffectTool:
    description = "offline test tool"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str, effects: list[str]) -> None:
        self.name = name
        self.effects = effects

    def execute(self, **_kwargs: object) -> str:
        self.effects.append(self.name)
        return "offline done"


def test_registry_zero_tool_scope_blocks_schedule_and_execute_command(tmp_path: Path) -> None:
    execution = _bound(tmp_path)
    effects: list[str] = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("schedule", effects))
    registry.register(_SideEffectTool("execute_command", effects))
    with bind_task_budget(execution):
        for name in ("schedule", "execute_command"):
            result = registry.execute(
                ToolCall(id=f"offline-{name}", name=name, arguments={"wake": True})
            )
            assert result.status == ToolResultStatus.BLOCKED
            assert result.tool_call_id == f"offline-{name}"
    assert not effects
    assert execution.store.read(execution.budget_id)["reservations"] == {}


def test_real_registry_allow_one_tool_then_deny_next(tmp_path: Path) -> None:
    execution = _bound(tmp_path, tool=1, allowed=frozenset({"read_file"}))
    effects: list[str] = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("read_file", effects))
    with bind_task_budget(execution):
        first = registry.execute(ToolCall(id="call-1", name="read_file", arguments={}))
        second = registry.execute(ToolCall(id="call-2", name="read_file", arguments={}))
    assert first.status == ToolResultStatus.SUCCESS
    assert second.status == ToolResultStatus.BLOCKED
    assert effects == ["read_file"]
    report = execution.store.report(execution.budget_id)
    assert report["used_or_reserved"][D.TOOL_INVOCATIONS.value] == 1


def test_registry_concurrent_calls_share_atomic_one_tool_budget(tmp_path: Path) -> None:
    execution = _bound(
        tmp_path, tool=1,
        allowed=frozenset({"read_file", "search_records"}),
    )
    effects: list[str] = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("read_file", effects))
    registry.register(_SideEffectTool("search_records", effects))
    calls = [
        ToolCall(id="tool-A", name="read_file", arguments={}),
        ToolCall(id="tool-B", name="search_records", arguments={}),
    ]
    with bind_task_budget(execution):
        results = registry.execute_many(calls)
    assert sorted(r.status.value for r in results) == ["blocked", "success"]
    assert len(effects) == 1
    assert execution.store.report(execution.budget_id)["used_or_reserved"][D.TOOL_INVOCATIONS.value] == 1


def test_schedule_requires_distinct_capability_not_just_listed_tool(tmp_path: Path) -> None:
    execution = _bound(
        tmp_path, tool=1,
        allowed=frozenset({"schedule"}), allow_wake=False,
    )
    registry = ToolRegistry()
    effects: list[str] = []
    registry.register(_SideEffectTool("schedule", effects))
    with bind_task_budget(execution):
        outcome = registry.execute(ToolCall(
            id="schedule-1", name="schedule",
            arguments={"wake": True, "after": 5, "message": "illegal"},
        ))
    assert outcome.status == ToolResultStatus.BLOCKED
    assert effects == []


def test_wrong_member_scope_fails_before_transport(tmp_path: Path) -> None:
    execution = _bound(tmp_path)
    invalid = replace(
        execution,
        member=replace(execution.member, session_id="another-session"),
    )
    client, transport = _client(_FakeStream(_OK_LINES))
    with pytest.raises(TaskBudgetDeniedError, match="member_identity_mismatch"):
        with bind_task_budget(invalid):
            _once(client)
    assert transport.stream.call_count == 0


def test_bound_state_no_secrets_and_no_provider_call_in_test(tmp_path: Path) -> None:
    execution = _bound(tmp_path)
    body = json.dumps(execution.store.read(execution.budget_id))
    assert '"api_key"' not in body
    assert "https://never-usable.invalid" not in body
    assert "human-turn-1" in body
    assert "run" in body


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_zero_attempt_profile_blocks_every_model_protocol_before_network(
    tmp_path: Path, protocol: str
) -> None:
    execution = _bound(tmp_path / protocol, physical=0)
    client, transport = _client(_FakeStream(_OK_LINES), protocol=protocol)
    with bind_task_budget(execution), pytest.raises(
        TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"
    ):
        _once(client)
    assert transport.stream.call_count == 0
    assert execution.store.read(execution.budget_id)["reservations"] == {}


def test_cancellation_revokes_admission_without_faking_transport_ack(tmp_path: Path) -> None:
    execution = _bound(tmp_path, physical=2, tool=1, allowed=frozenset({"read_file"}))
    client, transport = _client(_FakeStream(_OK_LINES))
    with bind_task_budget(execution):
        assert _once(client) == "ok"
        execution.request_stop(reason="offline-operator")
        with pytest.raises(TaskBudgetDeniedError, match="budget_not_active"):
            _once(client)
    assert transport.stream.call_count == 1
    report = execution.store.report(execution.budget_id)
    assert report["phase"] == "stop_requested"
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_budget_deadline_blocks_tool_before_preflight(tmp_path: Path) -> None:
    execution = _bound(tmp_path, tool=1, allowed=frozenset({"read_file"}))
    effects: list[str] = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("read_file", effects))
    execution.store._clock = lambda: 10000.0
    with pytest.raises(TaskBudgetDeniedError, match="deadline_expired"), bind_task_budget(execution):
        registry.execute(ToolCall(id="late", name="read_file", arguments={}))
    assert not effects


def test_schedule_true_capability_does_not_bypass_unwired_wake_lifecycle(tmp_path: Path) -> None:
    execution = _bound(
        tmp_path, tool=1,
        allowed=frozenset({"schedule"}), allow_wake=True,
    )
    effects: list[str] = []
    registry = ToolRegistry()
    registry.register(_SideEffectTool("schedule", effects))
    with bind_task_budget(execution):
        result = registry.execute(ToolCall(
            id="wake-1", name="schedule",
            arguments={"wake": True, "after": 5, "message": "no lineage"},
        ))
    assert result.status == ToolResultStatus.BLOCKED
    assert "derived_execution_capability_unqualified" in result.content
    assert not effects


def test_timeout_tool_receipt_is_not_mislabelled_physically_settled(
    tmp_path: Path, monkeypatch
) -> None:
    execution = _bound(tmp_path, tool=1, allowed=frozenset({"read_file"}))
    registry = ToolRegistry()
    registry.register(_SideEffectTool("read_file", []))
    monkeypatch.setattr(
        registry, "_run_with_timeout",
        lambda *_args: ToolResult(
            status=ToolResultStatus.TIMEOUT,
            content="running tool timed out",
            tool_call_id="timeout-A", tool_name="read_file",
        ),
    )
    with bind_task_budget(execution):
        reply = registry.execute(ToolCall(id="timeout-A", name="read_file", arguments={}))
    assert reply.status == ToolResultStatus.TIMEOUT
    row = execution.store.read(execution.budget_id)
    assert next(iter(row["reservations"].values()))["phase"] == "unknown"
    assert len(execution.store.report(execution.budget_id)["outstanding_or_unknown"]) == 1


def test_model_tool_projection_strips_zero_budget_and_preserves_normal_default(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService

    service = ToolCycleService(SimpleNamespace())  # type: ignore[arg-type] - focused projection host stub
    schemas = [
        {"name": "schedule", "parameters": {"type": "object"}},
        {"name": "read_file", "parameters": {"type": "object"}},
    ]

    def project() -> list[dict]:
        return service._project_tool_schemas_for_round(
            schemas, planned_label="glm", user_text="test", session_messages=[],
            logical_round=1,
        )

    assert {r["name"] for r in project()} == {"schedule", "read_file"}
    execution = _bound(tmp_path)
    with bind_task_budget(execution):
        assert project() == []
    assert {r["name"] for r in project()} == {"schedule", "read_file"}


def test_active_run_generation_and_session_cannot_borrow_other_grant(tmp_path: Path) -> None:
    from llm_loop.core.run_context import current_run_generation, current_session_id

    execution = _bound(tmp_path)
    mismatched = current_run_generation.set("another-run")
    try:
        with pytest.raises(TaskBudgetDeniedError, match="active_run_generation_mismatch"):
            with bind_task_budget(execution):
                pass
    finally:
        current_run_generation.reset(mismatched)
    mismatched = current_session_id.set("another-session")
    try:
        with pytest.raises(TaskBudgetDeniedError, match="active_session_scope_mismatch"):
            with bind_task_budget(execution):
                pass
    finally:
        current_session_id.reset(mismatched)


_STREAM_TEXT = {
    "openai": 'data: {"choices":[{"delta":{"content":"one"}}]}',
    "anthropic": 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"one"}}',
    "google": 'data: {"candidates":[{"content":{"parts":[{"text":"one"}]}}]}',
    "lms-chat": 'data: {"type":"message.delta","content":"one"}',
}


class _ObservedStream(_FakeStream):
    def __init__(self, protocol: str):
        super().__init__((_STREAM_TEXT[protocol], _STREAM_TEXT[protocol]))
        self.actual_lines = 0
        self.exited = False
        self.exit_type: type[BaseException] | None = None

    def iter_lines(self):
        for item in self.lines:
            self.actual_lines += 1
            yield item

    def __exit__(self, typ, *_args: object) -> bool:
        self.exited = True
        self.exit_type = typ
        return False


@pytest.mark.parametrize("protocol", sorted(_STREAM_TEXT))
def test_stop_during_bound_stream_closes_context_and_keeps_usage_unknown(
    tmp_path: Path, protocol: str
) -> None:
    execution = _bound(tmp_path, physical=1)
    stream = _ObservedStream(protocol)
    client, http = _client(stream, protocol=protocol)

    with bind_task_budget(execution):
        iterator = client.chat_stream(
            messages=[{"role": "user", "content": "offline stream stop"}],
            tools=[],
        )
        first = next(iterator)
        assert first.text == "one"
        assert stream.actual_lines == 1
        execution.request_stop(reason="user_stop")
        with pytest.raises(TaskBudgetDeniedError, match="budget_not_active"):
            next(iterator)

    assert http.stream.call_count == 1
    assert stream.actual_lines == 1  # no second SSE line read after stop
    assert stream.exited and stream.exit_type is TaskBudgetDeniedError
    row = execution.store.read(execution.budget_id)
    reservation = next(iter(row["reservations"].values()))
    assert reservation["phase"] == "unknown"
    assert reservation["outcome"] == "failure"
    assert execution.store.report(execution.budget_id)["physical_quiescence_verified"] is False


@pytest.mark.parametrize("protocol", sorted(_STREAM_TEXT))
def test_wall_deadline_during_bound_stream_stops_next_read(
    tmp_path: Path, protocol: str
) -> None:
    execution = _bound(tmp_path, physical=1)
    stream = _ObservedStream(protocol)
    client, http = _client(stream, protocol=protocol)

    with bind_task_budget(execution):
        iterator = client.chat_stream(
            messages=[{"role": "user", "content": "deadline test"}], tools=[]
        )
        assert next(iterator).text == "one"
        execution.store._clock = lambda: 6000.0
        with pytest.raises(TaskBudgetDeniedError, match="deadline_expired"):
            next(iterator)
    assert http.stream.call_count == 1
    assert stream.actual_lines == 1
    assert stream.exited
    assert next(iter(execution.store.read(execution.budget_id)["reservations"].values()))["phase"] == "unknown"


def test_unbound_stream_preserves_all_lines_without_budget_store(tmp_path: Path) -> None:
    stream = _ObservedStream("openai")
    client, http = _client(stream)
    iterator = client.chat_stream(
        messages=[{"role": "user", "content": "legacy no budget"}], tools=[]
    )
    deltas = list(iterator)
    assert [delta.text for delta in deltas if delta.text] == ["one", "one"]
    assert stream.actual_lines == 2
    assert http.stream.call_count == 1
    assert stream.exited
    assert not (tmp_path / "budget").exists()
