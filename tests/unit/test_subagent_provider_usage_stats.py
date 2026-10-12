"""Child cost telemetry must use settled physical sends, not model claims."""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.provider_transport_usage_stats import summarize_physical_provider_usage


def _event(
    attempt: str, *, call: str = "pcall:one", provider: str = "minimax",
    model: str = "MiniMax-M3.1", input_tokens: int = 100,
    cache: int | None = 80, output: int = 12, started: float = 10.0,
    settled: float = 10.5,
):
    usage = {"input_tokens": input_tokens, "output_tokens": output}
    if cache is not None:
        usage["cached_input_tokens"] = cache
    return SimpleNamespace(
        type="provider.transport.settled",
        payload={
            "attempt_id": attempt, "call_id": call,
            "provider_id": provider, "model_id": model,
            "started_at": started, "settled_at": settled,
            "usage": usage, "outcome": "success",
        },
    )


def test_physical_hidden_retry_and_model_breakdown_are_counted_without_double_count():
    original = _event("pattempt:1")
    retry = _event("pattempt:2", cache=90, started=10.5, settled=11.0)
    glm = _event(
        "pattempt:3", call="pcall:two", provider="glm", model="glm-5.3",
        cache=0, started=12.0, settled=12.2,
    )
    result = summarize_physical_provider_usage([
        SimpleNamespace(type="provider.call.settled", payload={}),
        original, retry, retry, glm,
    ])
    assert result is not None
    assert result["physical_attempts"] == 3
    assert result["logical_calls_observed"] == 2
    assert result["input_tokens"] == 300
    assert result["output_tokens"] == 36
    assert result["cached_input_tokens"] == 170
    assert result["uncached_input_tokens"] == 130
    assert result["cache_hit_rate"] == 56.67
    assert result["cache_usage_complete"] is True
    assert result["transport_duration_ms"] == 1200.0
    assert result["by_model"]["minimax/MiniMax-M3.1"]["cache_hit_rate"] == 85.0
    assert result["by_model"]["glm/glm-5.3"]["cache_hit_rate"] == 0.0
    assert result["accounting_unit"] == "observed_tokens_not_invoice_currency"


def test_unreported_cache_is_unknown_not_zero_and_not_false_discount():
    result = summarize_physical_provider_usage([
        _event("pattempt:a", cache=0),
        _event("pattempt:b", cache=None),
    ])
    assert result is not None
    assert result["known_input_attempts"] == 2
    assert result["known_cache_attempts"] == 1
    assert result["cache_usage_complete"] is False
    assert result["cache_hit_rate"] is None
    assert result["uncached_input_tokens"] is None
    assert result["cached_input_tokens"] == 0
    assert result["by_model"]["minimax/MiniMax-M3.1"]["cache_hit_rate"] is None


def test_conflicting_attempt_settlement_never_double_counts_or_claims_rate():
    result = summarize_physical_provider_usage([
        _event("pattempt:a", cache=80),
        _event("pattempt:a", cache=79),
    ])
    assert result is not None
    assert result["physical_attempts"] == 1
    assert result["conflicting_attempts"] == 1
    assert result["known_cache_attempts"] == 0
    assert result["cache_hit_rate"] is None


def test_impossible_cache_values_are_not_treated_as_real_hits():
    result = summarize_physical_provider_usage([
        _event("pattempt:a", cache=101),
        _event("pattempt:b", cache=-2),
    ])
    assert result is not None
    assert result["input_tokens"] == 200
    assert result["known_cache_attempts"] == 0
    assert result["cache_hit_rate"] is None


def test_missing_settlements_remain_unknown_not_zero():
    assert summarize_physical_provider_usage([]) is None
    open_only = summarize_physical_provider_usage([
        SimpleNamespace(type="provider.transport.opened", payload={
            "attempt_id": "pattempt:opened", "call_id": "pcall:unfinished",
            "provider_id": "glm", "model_id": "glm-5.3",
        })
    ])
    assert open_only is not None
    assert open_only["physical_attempts"] == 0
    assert open_only["opened_unsettled_attempts"] == 1
    assert open_only["cache_hit_rate"] is None
    assert open_only["cache_usage_complete"] is False


def test_opened_but_unsettled_attempt_disables_complete_rate():
    result = summarize_physical_provider_usage([
        _event("pattempt:settled", cache=90),
        SimpleNamespace(type="provider.transport.opened", payload={
            "attempt_id": "pattempt:unknown", "call_id": "pcall:two",
            "provider_id": "minimax", "model_id": "MiniMax-M3.1",
        }),
    ])
    assert result is not None
    assert result["physical_attempts"] == 1
    assert result["opened_unsettled_attempts"] == 1
    assert result["cache_hit_rate"] is None
