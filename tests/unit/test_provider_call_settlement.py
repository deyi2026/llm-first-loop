from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMClient
from llm_loop.resources.contracts import ExecutionClass, ServicePriority
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
    ProviderCallSettlementJournal,
    ProviderCallSite,
    ProviderTransportOutcome,
    bind_provider_call_site,
)
from llm_loop.resources.transport_observation import ShadowTransportRecorder


def _journal(tmp_path):
    store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(store, clock=lambda: 100.0)
    recorder = ShadowTransportRecorder(clock=lambda: 100.0)
    recorder.set_settlement_journal(journal)
    return store, journal, recorder


def _call(journal, *, key: str = "task:s1:turn:2:round:1"):
    return journal.open_call(
        session_id="s1",
        idempotency_key=key,
        owner_ref="task:s1:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )


def _site(call, *, kind=ProviderAttemptKind.PRIMARY, site_index: int = 0):
    return ProviderCallSite(
        call=call,
        attempt_kind=kind,
        site_index=site_index,
        provider_id="deepseek",
        model_id="deepseek-flash",
    )


def test_logical_call_id_is_stable_and_raw_idempotency_key_is_not_persisted(tmp_path):
    store, journal, _recorder = _journal(tmp_path)
    key = "task:s1:turn:2:round:1"
    first = _call(journal, key=key)
    second = _call(journal, key=key)
    assert first.call_id == second.call_id

    opened = [event for event in store.read("s1") if event.type == journal.CALL_OPENED]
    assert len(opened) == 1
    payload_text = json.dumps(opened[0].payload, ensure_ascii=False)
    assert key not in payload_text
    assert opened[0].payload["call_id"] == first.call_id
    assert opened[0].payload["purpose"] == "task"


def test_transport_settlement_merges_usage_chunks_without_summing_snapshots(tmp_path):
    _store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    with bind_provider_call_site(_site(call)), recorder.transport_attempt(
        provider_id="deepseek", model_id="deepseek-flash", transport_retry_index=0
    ) as attempt:
        assert attempt is not None
        recorder.record_response(
            provider_id="deepseek",
            model_id="deepseek-flash",
            status_code=200,
            headers={},
        )
        recorder.record_usage(
            provider_id="deepseek",
            model_id="deepseek-flash",
            usage={"prompt_tokens": 10, "total_tokens": 12},
        )
        recorder.record_usage(
            provider_id="deepseek",
            model_id="deepseek-flash",
            usage={"completion_tokens": 3, "total_tokens": 13},
        )
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)

    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == 1
    assert snapshot["attempts_settled"] == 1
    assert snapshot["attempts_complete"] is True
    usage = snapshot["attempts"][0]["usage"]
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 3
    assert usage["total_tokens"] == 13
    assert snapshot["known_usage_sum"]["total_tokens"] == 13
    assert snapshot["usage_complete"]["input_tokens"] is True
    assert snapshot["usage_complete"]["cached_input_tokens"] is False
    assert snapshot["call_outcome"] == "success"


def test_known_sum_does_not_claim_completeness_when_one_retry_omits_usage(tmp_path):
    _store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    site = _site(call)
    with bind_provider_call_site(site):
        with pytest.raises(httpx.ReadError), recorder.transport_attempt(
            provider_id="deepseek", model_id="deepseek-flash", transport_retry_index=0
        ):
            raise httpx.ReadError("disconnect")
        with recorder.transport_attempt(
            provider_id="deepseek", model_id="deepseek-flash", transport_retry_index=1
        ):
            recorder.record_usage(
                provider_id="deepseek",
                model_id="deepseek-flash",
                usage={"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            )
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)

    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == 2
    assert snapshot["attempts_settled"] == 2
    assert snapshot["known_usage_sum"]["input_tokens"] == 7
    assert snapshot["usage_complete"]["input_tokens"] is False
    assert snapshot["attempts"][1]["parent_attempt_id"] == snapshot["attempts"][0]["attempt_id"]


def test_attempt_settlement_is_idempotent_and_conflicts_do_not_overwrite(tmp_path):
    _store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    with bind_provider_call_site(_site(call)):
        attempt = journal.open_transport_attempt(_site(call), transport_retry_index=0)
    kwargs = dict(
        session_id="s1",
        attempt=attempt,
        outcome=ProviderTransportOutcome.SUCCESS,
        usage={"input_tokens": 2},
        usage_observations=1,
        status_code=200,
        provider_code=None,
        retry_after_seconds=None,
        rate_limits=(),
        error_type=None,
    )
    first = journal.settle_transport_attempt(**kwargs)
    second = journal.settle_transport_attempt(**kwargs)
    assert first == second
    with pytest.raises(ValueError, match="conflicting provider transport settlement"):
        journal.settle_transport_attempt(
            **{**kwargs, "outcome": ProviderTransportOutcome.ERROR, "error_type": "ReadError"}
        )


def test_llmclient_disconnect_retry_becomes_two_physical_attempts_under_one_call(
    tmp_path, monkeypatch
):
    _store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            raise httpx.ReadError("peer closed", request=request)
        body = (
            'data: {"usage":{"prompt_tokens":4,"completion_tokens":1,"total_tokens":5}}\n\n'
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body.encode(),
        )

    client = LLMClient(
        api_key="k",
        base_url="https://provider.invalid/v1",
        model="deepseek-flash",
        provider="deepseek",
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("LLM_RETRY_DISCONNECT", "1")
    try:
        with bind_provider_call_site(_site(call)):
            response = client.chat([{"role": "user", "content": "x"}], tools=[])
    finally:
        client.close()
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)

    assert response.content == "ok"
    assert requests == 2
    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == 2
    assert snapshot["attempts_settled"] == 2
    first, second = snapshot["attempts"]
    assert first["outcome"] == "error"
    assert first["error_type"] == "ReadError"
    assert first["transport_retry_index"] == 0
    assert second["outcome"] == "success"
    assert second["transport_retry_index"] == 1
    assert second["parent_attempt_id"] == first["attempt_id"]
    assert snapshot["known_usage_sum"]["total_tokens"] == 5
    assert snapshot["usage_complete"]["total_tokens"] is False


class _NoRuntimeAdapter:
    def observe(self, _client):
        return None


class _SettlementFakeLLM:
    provider = "shadow-provider"
    model = "shadow-model"
    base_url = "https://shadow.invalid/v1"

    def __init__(self, recorder, *, content: str = "ok") -> None:
        self.transport_observer = recorder
        self.content = content
        self.sites = []

    def chat(self, *args, **kwargs):
        del args, kwargs
        from llm_loop.llm.client import LLMResponse
        from llm_loop.resources.provider_settlement import current_provider_call_site

        site = current_provider_call_site()
        self.sites.append(site)
        with self.transport_observer.transport_attempt(
            provider_id=self.provider,
            model_id=self.model,
            transport_retry_index=0,
        ):
            self.transport_observer.record_response(
                provider_id=self.provider,
                model_id=self.model,
                status_code=200,
                headers={},
            )
            self.transport_observer.record_usage(
                provider_id=self.provider,
                model_id=self.model,
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            )
        return LLMResponse(content=self.content, tool_calls=[], provider=self.provider)


def _coordinator_with_fake(tmp_path, *, content: str = "ok"):
    from llm_loop.resources.governor import ResourceGovernor
    from llm_loop.resources.provider_calls import ProviderCallCoordinator

    store = EventStore(tmp_path / "provider-events")
    journal = ProviderCallSettlementJournal(store)
    recorder = ShadowTransportRecorder()
    recorder.set_settlement_journal(journal)
    client = _SettlementFakeLLM(recorder, content=content)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NoRuntimeAdapter(),
        settlement_journal=journal,
    )
    return store, journal, recorder, client, coordinator


def test_journal_rehydrates_attempt_topology_and_usage_from_eventstore(tmp_path):
    store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    with bind_provider_call_site(_site(call)), recorder.transport_attempt(
        provider_id="deepseek", model_id="deepseek-flash", transport_retry_index=0
    ):
        recorder.record_usage(
            provider_id="deepseek",
            model_id="deepseek-flash",
            usage={"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        )
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)

    reloaded_store = EventStore(tmp_path / "events")
    reloaded = ProviderCallSettlementJournal(reloaded_store)
    snapshot = reloaded.snapshot_call(call.call_id, session_id=call.session_id)
    assert snapshot["attempts_opened"] == 1
    assert snapshot["attempts_settled"] == 1
    assert snapshot["attempts_complete"] is True
    assert snapshot["known_usage_sum"]["total_tokens"] == 10
    assert snapshot["usage_complete"]["total_tokens"] is True
    assert snapshot["call_outcome"] == "success"


def test_summarizer_settles_with_distinct_purpose_on_shared_journal(tmp_path):
    from llm_loop.core.run_context import current_session_id
    from llm_loop.memory.summarize import Summarizer

    _store, journal, _recorder, client, coordinator = _coordinator_with_fake(
        tmp_path, content="summary text"
    )
    summarizer = Summarizer(
        llm_client=client,
        mode="sync",
        provider_call_coordinator=coordinator,
    )
    token = current_session_id.set("summary-session")
    try:
        result = summarizer.summarize("source text")
    finally:
        current_session_id.reset(token)
    assert result.source == "llm"
    assert client.sites and client.sites[-1] is not None
    call = client.sites[-1].call
    assert call.purpose is ProviderCallPurpose.SUMMARIZER
    assert call.execution_class is ExecutionClass.FOREGROUND_TASK
    assert journal.snapshot_call(call)["known_usage_sum"]["total_tokens"] == 5


def test_memory_extractor_settles_with_own_purpose(tmp_path):
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionStore
    from llm_loop.memory.extractor import MemoryExtractor
    from llm_loop.memory.store import MemoryStore

    _store, journal, _recorder, client, coordinator = _coordinator_with_fake(tmp_path, content="")
    sessions = SessionStore(tmp_path / "sessions")
    session_id = sessions.create()
    sessions.append(
        session_id,
        Message(role="user", content="rememberable fact", source=MessageSource.USER),
    )
    extractor = MemoryExtractor(
        llm_client=client,
        memory=MemoryStore(tmp_path / "memory"),
        session_store=sessions,
        provider_call_coordinator=coordinator,
    )
    extractor.extract_session(session_id, trigger="manual")
    assert client.sites and client.sites[-1] is not None
    call = client.sites[-1].call
    assert call.purpose is ProviderCallPurpose.MEMORY_EXTRACTOR
    assert call.execution_class is ExecutionClass.FOREGROUND_TASK
    assert journal.snapshot_call(call)["attempts_complete"] is True


def test_subagent_settles_under_subagent_execution_class(tmp_path):
    from llm_loop.core.session import SessionStore
    from llm_loop.subagent.runner import SubAgentRunner
    from llm_loop.tools.registry import ToolRegistry

    _store, journal, _recorder, client, coordinator = _coordinator_with_fake(
        tmp_path, content="child done"
    )
    runner = SubAgentRunner(
        llm=client,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        session_store=SessionStore(tmp_path / "subagent-sessions"),
        max_iterations=1,
        provider_call_coordinator=coordinator,
    )
    result = runner.run("child task")
    assert result.final_answer == "child done"
    assert client.sites and client.sites[-1] is not None
    call = client.sites[-1].call
    assert call.purpose is ProviderCallPurpose.SUBAGENT
    assert call.execution_class is ExecutionClass.SUBAGENT
    assert call.service_priority is ServicePriority.P1_ACTIVE_TASK_AUXILIARY
    assert journal.snapshot_call(call)["call_outcome"] == "success"


def test_learning_plane_settles_under_background_learning_purpose(tmp_path, monkeypatch):
    from llm_loop.methods.learning_journal import LearningJournal
    from llm_loop.methods.learning_plane import LearningPlane
    from llm_loop.methods.reflection import ReflectionOutcome
    from llm_loop.resources.governor import ResourceGovernor

    _store, journal, _recorder, client, coordinator = _coordinator_with_fake(
        tmp_path, content='{"decision":"none","reason":"none"}'
    )
    learning_journal = LearningJournal(tmp_path / "learning.jsonl")
    job = learning_journal.enqueue(
        "episode:learn-session:3:abc",
        session_id="learn-session",
        source_model="shadow-provider/shadow-model",
        trigger_facts={"rounds": 7},
    )
    assert job is not None

    def fake_reflect(**kwargs):
        kwargs["llm_client"].chat(messages=[], tools=[])
        return ReflectionOutcome(attempted=True, triggered=True, reason="none")

    monkeypatch.setattr("llm_loop.methods.learning_plane.reflect_on_episode", fake_reflect)
    plane = LearningPlane(
        journal=learning_journal,
        episode_store=SimpleNamespace(
            get=lambda *_args: {"messages": [{"role": "assistant", "content": "done"}]}
        ),
        method_store=SimpleNamespace(),
        engine=SimpleNamespace(settings=SimpleNamespace(method_reflection_timeout_s=5.0)),
        model_resolver=lambda _model: client,
        resource_governor=ResourceGovernor(),
        resource_target_resolver=lambda _model: ("shadow-provider", "shadow-model"),
        provider_call_coordinator=coordinator,
        quiet_period_s=0.0,
        poll_interval_s=1.0,
    )
    assert plane._try_execute(job) is True
    assert client.sites and client.sites[-1] is not None
    call = client.sites[-1].call
    assert call.purpose is ProviderCallPurpose.LEARNING
    assert call.execution_class is ExecutionClass.BACKGROUND_LEARNING
    assert call.service_priority is ServicePriority.P3_BACKGROUND_LEARNING
    assert journal.snapshot_call(call)["call_outcome"] == "success"


def test_independent_manual_memory_extracts_do_not_share_logical_call_identity(tmp_path):
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionStore
    from llm_loop.memory.extractor import MemoryExtractor
    from llm_loop.memory.store import MemoryStore

    _store, _journal, _recorder, client, coordinator = _coordinator_with_fake(tmp_path, content="")
    sessions = SessionStore(tmp_path / "manual-sessions")
    session_id = sessions.create()
    sessions.append(
        session_id,
        Message(role="user", content="same snapshot", source=MessageSource.USER),
    )
    extractor = MemoryExtractor(
        llm_client=client,
        memory=MemoryStore(tmp_path / "manual-memory"),
        session_store=sessions,
        provider_call_coordinator=coordinator,
    )
    extractor.extract_session(session_id, trigger="manual")
    extractor.extract_session(session_id, trigger="manual")
    call_ids = [site.call.call_id for site in client.sites if site is not None]
    assert len(call_ids) == 2
    assert call_ids[0] != call_ids[1]


def test_primary_1210_retry_and_fallback_share_one_ordered_transport_lineage(tmp_path):
    from llm_loop.resources.governor import ResourceGovernor
    from llm_loop.resources.provider_calls import ProviderCallCoordinator

    _store, journal, recorder = _journal(tmp_path)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NoRuntimeAdapter(),
        settlement_journal=journal,
    )
    client = _SettlementFakeLLM(recorder)
    call = coordinator.open_shadow_call_for_client(
        client,
        session_id="lineage-session",
        idempotency_key="lineage:turn:1:round:1",
        owner_ref="task:lineage-session:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )
    assert call is not None

    for kind, site_index in (
        (ProviderAttemptKind.PRIMARY, 0),
        (ProviderAttemptKind.ERR1210_RETRY, 1),
        (ProviderAttemptKind.FALLBACK, 2),
    ):
        with coordinator.bind_shadow_call_site(
            call,
            client,
            attempt_kind=kind,
            site_index=site_index,
        ):
            client.chat(messages=[], tools=[])
    coordinator.settle_shadow_call(call, ProviderCallOutcome.SUCCESS)

    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == 3
    attempts = snapshot["attempts"]
    assert [row["attempt_kind"] for row in attempts] == [
        "primary",
        "err1210_retry",
        "fallback",
    ]
    assert [row["site_index"] for row in attempts] == [0, 1, 2]
    assert attempts[0]["parent_attempt_id"] is None
    assert attempts[1]["parent_attempt_id"] == attempts[0]["attempt_id"]
    assert attempts[2]["parent_attempt_id"] == attempts[1]["attempt_id"]
    assert len({row["call_id"] for row in attempts}) == 1
    assert snapshot["known_usage_sum"]["total_tokens"] == 15
    assert snapshot["usage_complete"]["total_tokens"] is True
