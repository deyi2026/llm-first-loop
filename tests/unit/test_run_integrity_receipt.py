from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from llm_loop.runtime.causality import (
    background_run_generation_fact,
    build_run_integrity_receipt,
    effective_generation_contract,
)


@dataclass
class _Client:
    provider: str = "fake"
    model: str = "base-model"
    max_tokens: int = 4096
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    min_p: float = 0.0
    wire_protocol: str = "openai"
    send_tool_choice: bool = True
    reasoning_split: bool = False
    api_key: str = "MUST-NOT-APPEAR"


def test_background_run_generation_fact_is_exact_and_honest() -> None:
    class _Runner:
        enabled = True

        def get_handle(self, session_id: str):
            assert session_id == "sid"
            return {"run_generation": "gen-exact", "status": "running"}

    assert background_run_generation_fact(SimpleNamespace(runner=_Runner()), "sid") == {
        "state": "bound",
        "generation": "gen-exact",
    }
    assert background_run_generation_fact(SimpleNamespace(runner=None), "sid") == {
        "state": "not_background",
        "generation": "",
    }

    class _FaultRunner:
        enabled = True

        def get_handle(self, session_id: str):
            raise RuntimeError(session_id)

    assert background_run_generation_fact(SimpleNamespace(runner=_FaultRunner()), "sid") == {
        "state": "unknown",
        "generation": "",
    }


def test_build_run_integrity_receipt_is_mechanical_secret_free_and_actualizes_model() -> None:
    client = _Client()
    runtime = {
        "snapshot_id": "runtime-1",
        "tool_registry_fp": "tools-runtime-fp",
        "pid": 1234,
        "git_head": "abc",
    }
    receipt = build_run_integrity_receipt(
        session_id="sid",
        background_run={"state": "bound", "generation": "gen-1"},
        origin_ingress_channel="cli",
        current_ingress_channel="web",
        current_ingress_entry="web.chat",
        workspace_epoch=7,
        queue_id="q_123",
        routing_identity={"epoch": 2, "registry_fp": "registry-fp", "transition": "switch_model:fake/new"},
        provider="fake",
        model="fake/new",
        generation_contract=effective_generation_contract(client),
        provider_call_id="pcall:123",
        attempt_id="attempt-1",
        system_fp="system-fp",
        tools_fp="tools-fp",
        runtime_snapshot=runtime,
    )

    assert receipt == {
        "schema": "run-integrity/v1",
        "session_id": "sid",
        "background_run_generation": "gen-1",
        "run_generation_state": "bound",
        "origin_ingress_channel": "cli",
        "current_ingress_channel": "web",
        "current_ingress_entry": "web.chat",
        "workspace_epoch": 7,
        "queue_id": "q_123",
        "routing_epoch": 2,
        "routing_registry_fp": "registry-fp",
        "routing_transition": "switch_model:fake/new",
        "provider": "fake",
        "model": "fake/new",
        "generation_contract": {
            **effective_generation_contract(client),
            "provider": "fake",
            "model": "fake/new",
        },
        "provider_call_id": "pcall:123",
        "attempt_id": "attempt-1",
        "system_fp": "system-fp",
        "tools_fp": "tools-fp",
        "runtime_snapshot_id": "runtime-1",
        "tool_registry_fp": "tools-runtime-fp",
    }
    raw = repr(receipt)
    assert "MUST-NOT-APPEAR" not in raw
    forbidden = {
        "clean",
        "contaminated",
        "task_completion",
        "task_success",
        "retry",
        "rebind",
        "latest",
        "system_fp_match",
    }
    assert forbidden.isdisjoint(receipt)


def test_build_run_integrity_receipt_preserves_unknown_as_observation_not_authority() -> None:
    receipt = build_run_integrity_receipt(
        session_id="sid",
        background_run={"state": "unknown", "generation": ""},
        origin_ingress_channel="",
        current_ingress_channel="",
        current_ingress_entry="",
        workspace_epoch=0,
        queue_id="",
        routing_identity={},
        provider="",
        model="",
        generation_contract={},
        provider_call_id="",
        attempt_id="attempt-x",
        system_fp="changed-but-observed-only",
        tools_fp="",
        runtime_snapshot={},
    )
    assert receipt["run_generation_state"] == "unknown"
    assert receipt["background_run_generation"] == ""
    assert receipt["origin_ingress_channel"] == ""
    assert receipt["provider"] == ""
    assert receipt["system_fp"] == "changed-but-observed-only"
    assert "decision" not in receipt and "allowed" not in receipt and "blocked" not in receipt



def test_system_fingerprint_mismatch_remains_observability_only(
    build_test_engine, tmp_path
) -> None:
    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse

    engine, fake = build_test_engine([LLMResponse(content="still-runs", tool_calls=[], provider="fake")])
    event_store = EventStore(tmp_path / "system-fp-events")
    engine._event_store = event_store  # noqa: SLF001
    engine.session._event_store = event_store  # noqa: SLF001
    sid = engine.session.create()
    # Deliberately force the cache-health baseline to disagree with the real prompt.
    # This may affect cache observability but must never become provider admission authority.
    engine._cache_monitor._system_baselines[sid] = "definitely-not-current"  # noqa: SLF001

    result = engine.run(sid, "continue normally", ingress=issue_ingress("web"))

    assert result.final_answer.startswith("still-runs")
    assert len(fake.calls) == 1
    meta = next(event for event in event_store.read(sid) if event.type == "request.meta")
    receipt = meta.payload["run_integrity_receipt"]
    assert receipt["system_fp"]
    assert receipt["system_fp"] != "definitely-not-current"
    assert "system_fp_match" not in receipt
    assert "blocked" not in receipt



def test_receipt_distinguishes_first_origin_current_ingress_and_queue(
    build_test_engine, tmp_path
) -> None:
    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse

    engine, _fake = build_test_engine(
        [
            LLMResponse(content="first", tool_calls=[], provider="fake"),
            LLMResponse(content="second", tool_calls=[], provider="fake"),
        ]
    )
    event_store = EventStore(tmp_path / "ingress-receipt-events")
    engine._event_store = event_store  # noqa: SLF001
    engine.session._event_store = event_store  # noqa: SLF001
    sid = engine.session.create()

    engine.run(sid, "from cli", ingress=issue_ingress("cli"))
    engine.run(
        sid,
        "from web queue",
        ingress=issue_ingress("web"),
        user_metadata={"human_turn_queue_id": "q_exact_receipt"},
    )

    metas = [event for event in event_store.read(sid) if event.type == "request.meta"]
    assert len(metas) == 2
    first = metas[0].payload["run_integrity_receipt"]
    second = metas[1].payload["run_integrity_receipt"]
    assert first["origin_ingress_channel"] == "cli"
    assert first["current_ingress_channel"] == "cli"
    assert first["queue_id"] == ""
    assert second["origin_ingress_channel"] == "cli"
    assert second["current_ingress_channel"] == "web"
    assert second["current_ingress_entry"] == "web"
    assert second["queue_id"] == "q_exact_receipt"


def test_explicit_switch_routing_identity_is_reflected_without_new_authority(
    build_test_engine
) -> None:
    engine, _fake = build_test_engine([])
    # This is a receipt projection test only: Routing Epoch owns whether a transition is legal.
    engine._run_state_mgr.last_active_sid = "sid-switch-receipt"  # noqa: SLF001
    from llm_loop.core.run_context import current_session_id

    token = current_session_id.set("sid-switch-receipt")
    try:
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        snapshot = engine.llm_pool.registry_snapshot()
        engine._routing._advance_run_routing_epoch(  # noqa: SLF001
            snapshot, "fake/fake-model"
        )
        identity = engine._routing._routing_identity()  # noqa: SLF001
    finally:
        current_session_id.reset(token)
    receipt = build_run_integrity_receipt(
        session_id="sid-switch-receipt",
        background_run={"state": "not_background", "generation": ""},
        origin_ingress_channel="web",
        current_ingress_channel="web",
        current_ingress_entry="web",
        workspace_epoch=0,
        queue_id="",
        routing_identity=identity,
        provider="fake",
        model="fake-model",
        generation_contract=effective_generation_contract(_Client()),
        provider_call_id="",
        attempt_id="attempt-switch",
        system_fp="",
        tools_fp="",
        runtime_snapshot={},
    )
    assert receipt["routing_epoch"] == 1
    assert receipt["routing_transition"] == "switch_model:fake/fake-model"
    assert "authorized" not in receipt and "decision" not in receipt
