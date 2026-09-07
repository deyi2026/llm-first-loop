from __future__ import annotations

from llm_loop.event_log.model import REGISTRY, Event
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.runtime.causal_diagnose import diagnose_causality
from llm_loop.runtime.causality import exceptional_attempt_payload


def _event(seq: int, event_type: str, payload: dict) -> Event:
    return Event(
        event_id=f"e{seq}",
        session_id="s",
        seq=seq,
        type=event_type,
        ts=f"2026-09-08T00:00:{seq:02d}+00:00",
        payload=payload,
    )


def _meta(
    seq: int,
    *,
    runtime: str = "rt1",
    max_tokens: int = 8192,
    dialogue_pairs: int = 3,
    provider_fp: str = "payload-a",
    history_chars: int = 1000,
) -> Event:
    return _event(
        seq,
        "request.meta",
        {
            "round": seq,
            "attempt_id": f"attempt-{seq}",
            "attempt_kind": "primary",
            "attempt_index": 0,
            "model": "p/m",
            "tools_count": 5,
            "history_chars": history_chars,
            "reasoning_chars": 0,
            "provider_visible_chars": history_chars + 100,
            "provider_structure_fp": provider_fp,
            "runtime_snapshot": {"snapshot_id": runtime},
            "generation_contract": {
                "provider": "p",
                "model": "m",
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            "influence": {
                "ingress": {
                    "storage_messages": 10,
                    "trace_messages": 10,
                    "eligible_messages": 8,
                    "provider_base_messages": 8,
                    "stale_cleanup": {"resolved_or_consumed": 2},
                    "working_state_reason": "",
                    "tool_working_set": {"enabled": False},
                },
                "history": {
                    "effective_budget": 100000,
                    "compacted": False,
                    "anchor_moved": False,
                    "reopened_marker_count": 0,
                },
                "recent_continuity": {
                    "applied": True,
                    "source": "recent_dialogue_window",
                    "dialogue_pairs": dialogue_pairs,
                    "rehydrated": True,
                    "runtime_fact": False,
                },
            },
        },
    )


def _usage(seq: int, *, tokens_out: int = 100, max_headroom: int = 10000) -> Event:
    return _event(
        seq,
        "request.usage",
        {
            "tokens_in": 1000,
            "tokens_out": tokens_out,
            "context_headroom_tokens": max_headroom,
        },
    )


def test_ordinary_new_turn_does_not_false_positive_on_payload_growth() -> None:
    report = diagnose_causality(
        [
            _meta(1, provider_fp="payload-a", history_chars=1000),
            _usage(2),
            _meta(3, provider_fp="payload-b", history_chars=1500),
            _usage(4),
        ]
    )
    assert report["status"] == "compared"
    assert report["earliest_mechanical_divergence"] is None
    # Payload/content growth remains visible as an observed fact, but is not called a
    # program-mechanism divergence merely because a new human turn changed bytes.
    assert report["observed_facts"]["target"]["provider_structure_fp"] == "payload-b"


def test_recent_dialogue_mechanical_divergence_is_localized() -> None:
    report = diagnose_causality([_meta(1, dialogue_pairs=3), _usage(2), _meta(3, dialogue_pairs=1)])
    div = report["earliest_mechanical_divergence"]
    assert div["stage"] == "recent_continuity"
    assert "recent_continuity" in div["component"]
    assert div["reference"]["dialogue_pairs"] == 3
    assert div["target"]["dialogue_pairs"] == 1


def test_generation_contract_change_precedes_later_stages() -> None:
    report = diagnose_causality([_meta(1, max_tokens=8192), _usage(2), _meta(3, max_tokens=4096)])
    assert report["earliest_mechanical_divergence"]["stage"] == "generation_contract"


def test_runtime_snapshot_change_is_first_mechanical_divergence() -> None:
    report = diagnose_causality([_meta(1, runtime="rt1"), _usage(2), _meta(3, runtime="rt2")])
    assert report["earliest_mechanical_divergence"]["stage"] == "runtime"


def test_output_budget_hit_is_reported_as_constraint_not_semantic_cause() -> None:
    report = diagnose_causality(
        [_meta(1, max_tokens=8192), _usage(2), _meta(3, max_tokens=4096), _usage(4, tokens_out=4096)]
    )
    assert report["constraint_hits"] == [
        {
            "constraint": "output_budget",
            "observed": 4096,
            "limit": 4096,
            "mechanical_fact": "provider output tokens reached configured max_tokens",
        }
    ]


def test_causality_status_callback_is_lazy_and_session_scoped() -> None:
    calls: list[str] = []
    provider = ArchitectureStatusProvider()
    provider.set_causality_fn(lambda sid: calls.append(sid) or {"status": "ok", "sid": sid})

    full = provider.snapshot()
    assert full["causality"] == {"available": True, "on_demand": True}
    assert calls == []

    exact = provider.snapshot(session_id="s-123", dimensions=["causality"])
    assert exact["causality"] == {"status": "ok", "sid": "s-123"}
    assert calls == ["s-123"]


def test_exceptional_attempt_event_is_registered_and_secret_free() -> None:
    assert REGISTRY.spec("request.attempt") is not None

    class Client:
        provider = "p"
        model = "m"
        max_tokens = 4096
        temperature = 0.0
        top_p = 1.0
        top_k = 0
        min_p = 0.0
        wire_protocol = "openai"
        send_tool_choice = True
        reasoning_split = False
        api_key = "SECRET-NOT-RECORDED"

    payload = exceptional_attempt_payload(
        attempt_id="attempt-2",
        kind="err1210_retry",
        attempt_index=1,
        round_no=7,
        client=Client(),
        messages=[{"role": "user", "content": "x"}],
        tools=[],
        transform={"wire_shape_changed": True},
    )
    assert payload["attempt_kind"] == "err1210_retry"
    assert payload["provider_structure_fp"]
    assert "SECRET-NOT-RECORDED" not in repr(payload)


def test_architecture_status_causality_dimension_uses_current_session_without_schema_change() -> None:
    import json

    from llm_loop.introspection.corrections import CorrectionContext
    from llm_loop.introspection.tools_status import run_status

    calls: list[str] = []
    provider = ArchitectureStatusProvider()
    provider.set_causality_fn(lambda sid: calls.append(sid) or {"status": "ok", "sid": sid})
    ctx = CorrectionContext()
    ctx.session_id = "s-current"
    result = run_status(ctx, provider, {"dimensions": ["causality"]})
    body = json.loads(result.content)
    assert body["causality"] == {"status": "ok", "sid": "s-current"}
    assert calls == ["s-current"]
