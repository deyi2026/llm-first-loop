from __future__ import annotations

from dataclasses import asdict, fields

import httpx
import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.llm.errors import LLMHTTPError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
from llm_loop.resources.contracts import ProviderResponseFacts, ProviderUsageFacts, RateLimitMetric
from llm_loop.resources.transport_observation import (
    ShadowTransportRecorder,
    TransportObservationKind,
)


def _sse(*chunks: str) -> bytes:
    return ("\n\n".join(chunks) + "\n\n").encode("utf-8")


def _client(recorder: object, handler) -> LLMClient:
    client = LLMClient(
        api_key="test-key",
        base_url="https://provider.invalid/v1",
        model="model-a",
        provider="deepseek",
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_openai_shadow_preserves_reported_zero_usage_and_safe_rate_headers() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 100.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "x-ratelimit-limit-requests": "60",
                "x-ratelimit-remaining-requests": "59",
                "x-ratelimit-reset-requests": "1s",
                "x-ratelimit-limit-tokens": "100000",
                "x-ratelimit-remaining-tokens": "99000",
                "x-ratelimit-reset-tokens": "250ms",
                "set-cookie": "session=must-not-survive",
                "authorization": "Bearer must-not-survive",
            },
            content=_sse(
                'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}',
                'data: {"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"prompt_tokens_details":{"cached_tokens":0}},"choices":[]}',
                "data: [DONE]",
            ),
        )

    client = _client(recorder, handler)
    try:
        response = client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()

    assert response.content == "OK"
    observations = recorder.snapshot()
    response_facts = [item.fact for item in observations if item.kind is TransportObservationKind.RESPONSE]
    usage_facts = [item.fact for item in observations if item.kind is TransportObservationKind.USAGE]
    assert len(response_facts) == 1
    assert len(usage_facts) == 1
    assert isinstance(response_facts[0], ProviderResponseFacts)
    assert isinstance(usage_facts[0], ProviderUsageFacts)
    assert usage_facts[0].input_tokens == 0
    assert usage_facts[0].output_tokens == 0
    assert usage_facts[0].cached_input_tokens == 0
    assert usage_facts[0].total_tokens == 0
    request_limit = next(
        fact for fact in response_facts[0].rate_limits if fact.metric is RateLimitMetric.REQUESTS
    )
    token_limit = next(
        fact for fact in response_facts[0].rate_limits if fact.metric is RateLimitMetric.TOTAL_TOKENS
    )
    assert (request_limit.limit, request_limit.remaining, request_limit.reset_after_seconds) == (
        60,
        59,
        1.0,
    )
    assert (token_limit.limit, token_limit.remaining, token_limit.reset_after_seconds) == (
        100000,
        99000,
        0.25,
    )
    serialized = repr([asdict(item.fact) for item in observations]).lower()
    assert "must-not-survive" not in serialized
    assert "set-cookie" not in serialized
    assert "authorization" not in serialized


def test_unreported_usage_is_absent_not_fabricated_zero() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 101.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ),
        )

    client = _client(recorder, handler)
    try:
        client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()

    assert not [item for item in recorder.snapshot() if item.kind is TransportObservationKind.USAGE]


def test_http_429_shadow_records_only_typed_error_retry_and_reset_facts() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 200.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={
                "content-type": "application/json",
                "retry-after": "2",
                "x-ratelimit-limit-requests": "20",
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "2s",
                "x-secret-debug": "do-not-record-this",
            },
            json={"error": {"code": "rate_limit_exceeded", "message": "private diagnostic"}},
        )

    client = _client(recorder, handler)
    try:
        with pytest.raises(LLMHTTPError) as caught:
            client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()

    assert caught.value.status_code == 429
    errors = [item.fact for item in recorder.snapshot() if item.kind is TransportObservationKind.ERROR]
    assert len(errors) == 1
    error = errors[0]
    assert error.status_code == 429
    assert error.provider_code == "rate_limit_exceeded"
    assert error.retry_after_seconds == 2.0
    assert len(error.rate_limits) == 1
    assert error.rate_limits[0].metric is RateLimitMetric.REQUESTS
    assert error.rate_limits[0].remaining == 0
    serialized = repr(asdict(error)).lower()
    assert "private diagnostic" not in serialized
    assert "do-not-record-this" not in serialized
    assert "x-secret-debug" not in serialized


def test_http_date_retry_after_is_normalized_to_seconds_without_raw_header() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 784111777.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "Sun, 06 Nov 1994 08:49:39 GMT"},
            json={"error": {"code": 429}},
        )

    client = _client(recorder, handler)
    try:
        with pytest.raises(LLMHTTPError):
            client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()

    error = next(item.fact for item in recorder.snapshot() if item.kind is TransportObservationKind.ERROR)
    assert error.retry_after_seconds == 2.0


def test_http_200_sse_error_is_recorded_as_provider_error_without_message_text() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 300.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                'data: {"error":{"code":1210,"message":"parameter details should not be retained"}}'
            ),
        )

    client = _client(recorder, handler)
    try:
        with pytest.raises(LLMHTTPError):
            client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()

    errors = [item.fact for item in recorder.snapshot() if item.kind is TransportObservationKind.ERROR]
    assert len(errors) == 1
    assert errors[0].status_code == 200
    assert errors[0].provider_code == "1210"
    assert "parameter details" not in repr(asdict(errors[0])).lower()


def test_observer_failure_is_fail_open_for_success_and_original_http_error() -> None:
    class BrokenObserver:
        def record_response(self, **_kwargs):
            raise RuntimeError("observer unavailable")

        def record_usage(self, **_kwargs):
            raise RuntimeError("observer unavailable")

        def record_error(self, **_kwargs):
            raise RuntimeError("observer unavailable")

    def ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}',
                'data: {"usage":{"prompt_tokens":1,"completion_tokens":1},"choices":[]}',
                "data: [DONE]",
            ),
        )

    client = _client(BrokenObserver(), ok_handler)
    try:
        assert client.chat([{"role": "user", "content": "hi"}], tools=[]).content == "OK"
    finally:
        client.close()

    def error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"code": 429}})

    client = _client(BrokenObserver(), error_handler)
    try:
        with pytest.raises(LLMHTTPError) as caught:
            client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()
    assert caught.value.status_code == 429


def test_pool_propagates_one_shared_shadow_recorder_to_routed_clients(monkeypatch) -> None:
    monkeypatch.setenv("ROUTED_TEST_KEY", "k")
    recorder = ShadowTransportRecorder()
    default = LLMClient(
        api_key="",
        base_url="http://127.0.0.1:8901/v1",
        model="local-model",
        provider="cognilocal",
        guard_enabled=False,
        transport_observer=recorder,
    )
    registry = ProviderRegistry(
        providers={
            "glm": ProviderSpec(
                id="glm",
                base_url="https://glm.invalid/v1",
                api_key_env="ROUTED_TEST_KEY",
                models={"glm-test": ModelSpec()},
                default_model="glm-test",
            )
        }
    )
    try:
        pool = ModelClientPool(
            registry=registry,
            default_client=default,
            transport_observer=recorder,
        )
        routed = pool.get_client("glm/glm-test")
        assert routed.transport_observer is recorder
        assert pool.transport_observer is recorder
        pool.close()
    finally:
        default.close()


def test_rg3b_shadow_is_not_consumed_by_governor_or_provider_admission() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2]
    governor = (root / "src/llm_loop/resources/governor.py").read_text(encoding="utf-8")
    provider_calls = (root / "src/llm_loop/resources/provider_calls.py").read_text(encoding="utf-8")
    assert "transport_observation" not in governor
    assert "ProviderUsageFacts" not in governor
    assert "ProviderErrorFacts" not in governor
    assert "transport_observation" not in provider_calls
    assert "ProviderUsageFacts" not in provider_calls
    assert "ProviderErrorFacts" not in provider_calls


def test_ambiguous_numeric_rate_reset_is_not_guessed_as_seconds() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 400.0)
    recorder.record_response(
        provider_id="glm",
        model_id="glm-5.3",
        status_code=200,
        headers={
            "x-ratelimit-limit-requests": "10",
            "x-ratelimit-remaining-requests": "9",
            "x-ratelimit-reset-requests": "1730000000",
        },
    )
    facts = recorder.snapshot()[0].fact
    request_limit = next(item for item in facts.rate_limits if item.metric is RateLimitMetric.REQUESTS)
    assert request_limit.reset_after_seconds is None
    assert request_limit.reset_at is None


def test_shadow_recorder_is_bounded_without_changing_fact_sequence() -> None:
    recorder = ShadowTransportRecorder(max_entries=2, clock=lambda: 500.0)
    for status in (200, 201, 202):
        recorder.record_response(
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
            status_code=status,
            headers={},
        )
    snapshot = recorder.snapshot()
    assert [item.sequence for item in snapshot] == [2, 3]
    assert [item.fact.status_code for item in snapshot] == [201, 202]


def test_transport_fact_contracts_cannot_store_raw_transport_or_task_payloads() -> None:
    forbidden = {
        "headers", "raw_headers", "body", "raw_body", "prompt", "messages",
        "api_key", "authorization", "cookie", "task_text",
    }
    from llm_loop.resources.contracts import ProviderErrorFacts

    for cls in (ProviderResponseFacts, ProviderUsageFacts, ProviderErrorFacts):
        assert {item.name for item in fields(cls)}.isdisjoint(forbidden)


def test_factory_shares_one_shadow_recorder_between_default_and_routed_clients(tmp_path, monkeypatch) -> None:
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    monkeypatch.setenv("RG3B_ROUTED_KEY", "k")
    (tmp_path / "providers.json").write_text(
        '{"default":{"base_url":"http://127.0.0.1:8901/v1","api_key_env":"","models":{"local":{"context":131072}},"default_model":"local"},"glm":{"base_url":"https://glm.invalid/v1","api_key_env":"RG3B_ROUTED_KEY","models":{"glm-test":{"context":131072}},"default_model":"glm-test"}}',
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=str(tmp_path),
        llm_api_key="",
        llm_base_url="http://127.0.0.1:8901/v1",
        llm_model="local",
    )
    engine = build_engine(settings)
    try:
        default = engine.llm
        routed = engine.llm_pool.get_client("glm/glm-test")
        assert default.transport_observer is engine.llm_pool.transport_observer
        assert routed.transport_observer is default.transport_observer
        assert isinstance(default.transport_observer, ShadowTransportRecorder)
    finally:
        engine.close()


def test_unstructured_error_string_is_not_recast_as_provider_code() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 600.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "private_diagnostic_tokenlike"})

    client = _client(recorder, handler)
    try:
        with pytest.raises(LLMHTTPError):
            client.chat([{"role": "user", "content": "hi"}], tools=[])
    finally:
        client.close()
    error = next(item.fact for item in recorder.snapshot() if item.kind is TransportObservationKind.ERROR)
    assert error.provider_code is None
    assert "private_diagnostic_tokenlike" not in repr(asdict(error))


def test_usage_mapping_with_no_valid_typed_values_is_not_recorded() -> None:
    recorder = ShadowTransportRecorder(clock=lambda: 601.0)
    recorder.record_usage(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        usage={"prompt_tokens": None, "completion_tokens": "not-a-number"},
    )
    assert recorder.snapshot() == ()
