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
    round_no: int | None = None,
    tools_count: int = 5,
    storage_messages: int = 10,
    eligible_messages: int = 8,
    resolved_or_consumed: int = 2,
    input_tokens: int | None = None,
    allowed_input_tokens: int | None = None,
    tool_schema_reserve_chars: int = 0,
) -> Event:
    return _event(
        seq,
        "request.meta",
        {
            "round": seq if round_no is None else round_no,
            "attempt_id": f"attempt-{seq}",
            "attempt_kind": "primary",
            "attempt_index": 0,
            "model": "p/m",
            "tools_count": tools_count,
            "history_chars": history_chars,
            "reasoning_chars": 0,
            "provider_visible_chars": history_chars + 100,
            "provider_structure_fp": provider_fp,
            **(
                {
                    "input_budget": {
                        "requested_input_tokens": input_tokens,
                        "allowed_input_tokens": (
                            input_tokens if allowed_input_tokens is None else allowed_input_tokens
                        ),
                        "tool_schema_reserve_chars": tool_schema_reserve_chars,
                        "effective_history_budget_chars": 100000,
                        "limited_by": "input_token_budget" if input_tokens else "model_window",
                    }
                }
                if input_tokens is not None
                else {}
            ),
            "runtime_snapshot": {"snapshot_id": runtime},
            "generation_contract": {
                "provider": "p",
                "model": "m",
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 0,
                "min_p": 0.0,
                "wire_protocol": "openai",
                "send_tool_choice": True,
                "reasoning_split": False,
            },
            "influence": {
                "ingress": {
                    "storage_messages": storage_messages,
                    "trace_messages": storage_messages,
                    "eligible_messages": eligible_messages,
                    "provider_base_messages": eligible_messages,
                    "stale_cleanup": {"resolved_or_consumed": resolved_or_consumed},
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


def _usage(
    seq: int,
    *,
    tokens_out: int = 100,
    max_headroom: int = 10000,
    stable_prefix_fp: str = "",
    prefix_changed: bool = False,
    prefix_change_reason: str = "",
    cache_prefix_epoch: int = 0,
    compaction_epoch: int = 0,
) -> Event:
    return _event(
        seq,
        "request.usage",
        {
            "tokens_in": 1000,
            "tokens_out": tokens_out,
            "context_headroom_tokens": max_headroom,
            "stable_prefix_fp": stable_prefix_fp,
            "prefix_changed": prefix_changed,
            "prefix_change_reason": prefix_change_reason,
            "cache_prefix_epoch": cache_prefix_epoch,
            "compaction_epoch": compaction_epoch,
        },
    )


def _interrupted(
    seq: int,
    *,
    completion_tokens: int | None,
    reasoning_tail_chars: int = 0,
    text_tail_chars: int = 0,
    tool_call_draft_count: int = 0,
    finish_reason: str = "",
) -> Event:
    return _event(
        seq,
        "llm.interrupted",
        {
            "reason": "llm_error",
            "completion_tokens": completion_tokens,
            "reasoning_tail_chars": reasoning_tail_chars,
            "text_tail_chars": text_tail_chars,
            "tool_call_draft_count": tool_call_draft_count,
            "finish_reason": finish_reason,
            "provider_truncated": False,
            "timing": {"first_reasoning_ms": 12.0, "provider_total_ms": 4100.0},
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



def test_natural_ingress_volume_growth_is_observed_not_ranked_as_divergence() -> None:
    report = diagnose_causality(
        [
            _meta(1, storage_messages=10, eligible_messages=8, resolved_or_consumed=2),
            _usage(2),
            _meta(3, storage_messages=20, eligible_messages=14, resolved_or_consumed=6),
            _usage(4),
        ]
    )
    assert report["earliest_mechanical_divergence"] is None
    target = report["observed_facts"]["target"]
    assert target["ingress_volume"]["eligibility_removed"] == 6
    assert target["ingress_volume"]["stale_cleanup"]["resolved_or_consumed"] == 6


def test_ingress_mechanism_activation_remains_a_ranked_divergence() -> None:
    report = diagnose_causality(
        [
            _meta(1, storage_messages=10, eligible_messages=10, resolved_or_consumed=0),
            _usage(2),
            _meta(3, storage_messages=12, eligible_messages=10, resolved_or_consumed=2),
            _usage(4),
        ]
    )
    assert report["earliest_mechanical_divergence"]["stage"] == "ingress"

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


def test_oracle_context_layer_recent_dialogue_loss_is_first_mechanical_divergence() -> None:
    report = diagnose_causality(
        [
            _meta(1, history_chars=90916, dialogue_pairs=3),
            _usage(2),
            _meta(3, history_chars=2327, dialogue_pairs=1),
        ]
    )
    div = report["earliest_mechanical_divergence"]
    assert div["stage"] == "recent_continuity"
    assert report["observed_facts"]["reference"]["history_chars"] == 90916
    assert report["observed_facts"]["target"]["history_chars"] == 2327


def test_oracle_reasoning_only_empty_response_uses_terminal_failure_facts() -> None:
    report = diagnose_causality(
        [
            _meta(1, max_tokens=4096),
            _interrupted(
                2,
                completion_tokens=4096,
                reasoning_tail_chars=8000,
                text_tail_chars=0,
                tool_call_draft_count=0,
                finish_reason="length",
            ),
        ]
    )
    hit = report["constraint_hits"][0]
    assert hit["constraint"] == "output_budget"
    assert hit["observed"] == 4096
    assert hit["limit"] == 4096
    assert hit["evidence_source"] == "llm.interrupted"
    assert hit["terminal_shape"] == "reasoning_only_no_visible_text_or_tool_draft"
    assert "provider completion constraint unknown" not in report["unknown"]


def test_oracle_reasoning_only_without_completion_tokens_stays_unknown() -> None:
    report = diagnose_causality(
        [_meta(1, max_tokens=4096), _interrupted(2, completion_tokens=None, reasoning_tail_chars=8000)]
    )
    assert report["constraint_hits"] == []
    assert "provider completion constraint unknown" in report["unknown"]


def test_oracle_cache_drop_localizes_earlier_tool_surface_change() -> None:
    report = diagnose_causality(
        [
            _meta(1, tools_count=62),
            _usage(
                2,
                stable_prefix_fp="stable-a",
                prefix_changed=False,
                cache_prefix_epoch=4,
            ),
            _meta(3, tools_count=63),
            _usage(
                4,
                stable_prefix_fp="stable-b",
                prefix_changed=True,
                prefix_change_reason="stable_prefix_changed",
                cache_prefix_epoch=5,
            ),
        ]
    )
    div = report["earliest_mechanical_divergence"]
    assert div["stage"] == "tool_surface"
    assert div["reference"]["tools_count"] == 62
    assert div["target"]["tools_count"] == 63


def test_oracle_err1210_retry_compares_with_same_round_primary_and_wire_transform() -> None:
    class Client:
        provider = "p"
        model = "m"
        max_tokens = 8192
        temperature = 0.0
        top_p = 1.0
        top_k = 0
        min_p = 0.0
        wire_protocol = "openai"
        send_tool_choice = True
        reasoning_split = False

    retry = exceptional_attempt_payload(
        attempt_id="attempt-retry",
        kind="err1210_retry",
        attempt_index=1,
        round_no=7,
        client=Client(),
        messages=[{"role": "user", "content": "a\n\n============================\n\nb"}],
        tools=[{}, {}, {}, {}, {}],
        transform={
            "wire_shape_changed": True,
            "messages_before": 9,
            "messages_after": 2,
            "tail_users_merged": 8,
        },
    )
    report = diagnose_causality(
        [
            _meta(1, round_no=6),
            _usage(2),
            _meta(3, round_no=7, tools_count=5),
            _event(4, "request.attempt", retry),
        ]
    )
    assert report["observed_facts"]["reference_basis"] == "preceding_attempt_same_round"
    assert report["observed_facts"]["reference"]["seq"] == 3
    div = report["earliest_mechanical_divergence"]
    assert div["stage"] == "wire_transform"
    assert div["target"]["tail_users_merged"] == 8


def test_oracle_restart_remains_runtime_first() -> None:
    report = diagnose_causality(
        [_meta(1, runtime="pid-old"), _usage(2), _meta(3, runtime="pid-new"), _usage(4)]
    )
    assert report["earliest_mechanical_divergence"]["stage"] == "runtime"


def test_oracle_ordinary_new_user_turn_remains_non_alarm() -> None:
    report = diagnose_causality(
        [
            _meta(1, provider_fp="payload-a", history_chars=2000),
            _usage(2),
            _meta(3, provider_fp="payload-b", history_chars=4200),
            _usage(4),
        ]
    )
    assert report["earliest_mechanical_divergence"] is None


def test_input_budget_change_is_first_class_mechanical_divergence():
    report = diagnose_causality(
        [
            _meta(1, input_tokens=184000, tool_schema_reserve_chars=20000),
            _usage(2),
            _meta(3, input_tokens=64000, allowed_input_tokens=48000, tool_schema_reserve_chars=20000),
        ]
    )
    assert report["earliest_mechanical_divergence"]["stage"] == "input_budget"
    assert report["earliest_mechanical_divergence"]["reference"]["requested_input_tokens"] == 184000
    assert report["earliest_mechanical_divergence"]["target"]["allowed_input_tokens"] == 48000
