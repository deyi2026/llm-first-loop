"""Recovery for the 2026-10-18 GLM HTTP-200 reasoning-only disconnect."""

import json
from threading import Event
from unittest import mock

import httpx
import pytest

from llm_loop.core.run_context import child_cancel_event
from llm_loop.feedback.honesty import llm_error_text
from llm_loop.llm.errors import LLMNetworkError, LLMStreamInterruptedError, classify_llm_error
from tests.unit.test_llm_client import _client, _FakeStreamCtx
from tests.unit.test_timeout_recovery import _success


class Interrupted(_FakeStreamCtx):
    def __init__(self, delta, stop=None):
        super().__init__([])
        self.delta = delta
        self.stop = stop

    def iter_lines(self):
        yield "data: " + json.dumps({"choices": [{"delta": self.delta}]})
        if self.stop is not None:
            self.stop.set()
        raise httpx.RemoteProtocolError("peer closed connection (incomplete chunked read)")


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
def test_plain_reasoning_disconnect_recovers_same_request_with_boundary(field):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Interrupted({field: "unfinished thought"}), _success()]
        it = _client(provider="glm").chat_stream([{"role": "user", "content": "task"}], [])
        deltas = []
        while True:
            try:
                deltas.append(next(it))
            except StopIteration as terminal:
                response = terminal.value
                break
    assert stream.call_count == 2
    assert stream.call_args_list[0] == stream.call_args_list[1]
    assert response.content == "recovered"
    assert response.reasoning_content is None
    assert "".join(d.text for d in deltas) == "recovered"
    observed = "".join(d.reasoning or "" for d in deltas)
    assert "unfinished thought" in observed
    assert "响应流中断" in observed and "重新请求" in observed


def test_reasoning_disconnect_recovers_at_most_once_even_with_large_budget():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Interrupted({"reasoning_content": "first"}),
                              Interrupted({"reasoning_content": "second"}), _success()]
        with pytest.raises(LLMNetworkError) as caught:
            _client(provider="glm", retry_disconnect=4).chat([], [])
    assert stream.call_count == 2
    assert isinstance(caught.value, LLMStreamInterruptedError)
    assert caught.value.retries == 1


@pytest.mark.parametrize("delta", [
    {"reasoning_content": "thought", "content": "visible"},
    {"reasoning_details": [{"type": "reasoning.encrypted", "data": "signed-state"}]},
    {"content": "<think>buffered thought"},
    {"reasoning_content": "thought", "tool_calls": [{"index": 0, "function": {"arguments": "{"}}]},
])
def test_actionable_or_opaque_output_never_replays(delta):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Interrupted(delta), _success()]
        with pytest.raises(LLMNetworkError):
            _client().chat([], [])
    assert stream.call_count == 1


@pytest.mark.parametrize("disabled", [False, True])
def test_reasoning_recovery_respects_stop_and_disabled_policy(disabled):
    stop = Event()
    token = child_cancel_event.set(stop)
    try:
        with mock.patch("httpx.Client") as client_cls:
            stream = client_cls.return_value.stream
            stream.side_effect = [Interrupted({"reasoning_content": "thought"}, None if disabled else stop), _success()]
            with pytest.raises(LLMNetworkError):
                _client(retry_disconnect=0 if disabled else 1).chat([], [])
        assert stream.call_count == 1
    finally:
        child_cancel_event.reset(token)


def test_stream_interruption_feedback_reports_observed_facts():
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = Interrupted({"content": "partial"})
        with pytest.raises(LLMNetworkError) as caught:
            _client(provider="glm", model="glm-5.3").chat([], [])
    error = caught.value
    text = llm_error_text(error)
    assert "响应流中断" in text
    assert "glm-5.3" in text and "耗时" in text
    assert "正文 7" in text and "思考 0" in text
    assert "检查网络/Key/模型名" not in text
    assert "网络不可达" not in text
    assert classify_llm_error(error).label == "响应流中断"


@pytest.mark.parametrize("second_error", [httpx.RemoteProtocolError, httpx.ReadTimeout])
def test_reasoning_recovery_does_not_open_more_attempts_after_zero_output_failure(second_error):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Interrupted({"reasoning_content": "first"}),
                              second_error("second attempt failed"), _success()]
        from llm_loop.llm.errors import LLMError

        with pytest.raises(LLMError):
            _client(retry_disconnect=4).chat([], [])
    assert stream.call_count == 2


def test_stop_during_retry_boundary_prevents_second_dispatch():
    stop = Event()
    token = child_cancel_event.set(stop)
    try:
        with mock.patch("httpx.Client") as client_cls:
            stream = client_cls.return_value.stream
            stream.side_effect = [Interrupted({"reasoning_content": "first"}), _success()]
            it = _client().chat_stream([], [])
            assert next(it).reasoning == "first"
            assert "响应流中断" in (next(it).reasoning or "")
            stop.set()
            with pytest.raises(LLMNetworkError):
                next(it)
        assert stream.call_count == 1
    finally:
        child_cancel_event.reset(token)


def test_legacy_function_call_fragment_is_never_replayed():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Interrupted({"function_call": {"name": "write_file"}}), _success()]
        with pytest.raises(LLMNetworkError):
            _client().chat([], [])
    assert stream.call_count == 1


def test_reasoning_recovery_preserves_transport_journal_and_identical_payload(tmp_path):
    from llm_loop.resources.provider_settlement import (
        ProviderAttemptKind,
        ProviderCallOutcome,
        ProviderCallSite,
        bind_provider_call_site,
    )
    from tests.unit.test_provider_call_settlement import _call, _journal

    _store, journal, recorder = _journal(tmp_path)
    call = _call(journal)
    requests = []

    class BrokenBody(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"reasoning_content":"unfinished"}}]}\n\n'
            raise httpx.RemoteProtocolError("incomplete chunked read")

    def handler(request):
        requests.append(request.content)
        if len(requests) == 1:
            return httpx.Response(200, stream=BrokenBody())
        return httpx.Response(200, content=(
            b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            b'data: [DONE]\n\n'
        ))

    client = _client(provider="glm", model="glm-5.3", transport_observer=recorder, guard_enabled=False)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    site = ProviderCallSite(call=call, attempt_kind=ProviderAttemptKind.PRIMARY, site_index=0,
                            provider_id="glm", model_id="glm-5.3")
    try:
        with bind_provider_call_site(site):
            response = client.chat([{"role": "user", "content": "task"}], [])
            assert response.content == "ok" and response.reasoning_content is None
    finally:
        client.close()
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)
    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == snapshot["attempts_settled"] == 2
    first, second = snapshot["attempts"]
    assert (first["outcome"], first["status_code"], first["error_type"]) == ("error", 200, "RemoteProtocolError")
    assert (second["outcome"], second["transport_retry_index"]) == ("success", 1)
    assert second["parent_attempt_id"] == first["attempt_id"]
    assert first["call_id"] == second["call_id"] == call.call_id
    assert len(requests) == 2 and requests[0] == requests[1]
