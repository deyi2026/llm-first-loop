"""Recover transient zero-output timeouts without replaying model/tool output."""

from unittest import mock

import httpx
import pytest

from llm_loop.feedback.honesty import llm_error_text
from llm_loop.llm.errors import LLMTimeoutError
from tests.unit.test_llm_client import _client, _FakeStreamCtx


def _success():
    return _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "recovered"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        'data: [DONE]',
    ])


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectTimeout])
def test_zero_output_timeout_retries_same_request_once(error_type):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [error_type("transient"), _success()]
        response = _client().chat([{"role": "user", "content": "task"}], [])
    assert response.content == "recovered"
    assert stream.call_count == 2
    assert stream.call_args_list[0] == stream.call_args_list[1]


def test_repeated_timeout_stops_at_shared_transport_budget():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = httpx.ReadTimeout("unavailable")
        with pytest.raises(LLMTimeoutError):
            _client().chat([], [])
    assert stream.call_count == 2


def test_disconnect_then_timeout_does_not_multiply_retry_budget():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [httpx.RemoteProtocolError("closed"), httpx.ReadTimeout("slow"), _success()]
        with pytest.raises(LLMTimeoutError):
            _client().chat([], [])
    assert stream.call_count == 2


def test_timeout_retry_can_be_disabled():
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = httpx.ReadTimeout("slow")
        with pytest.raises(LLMTimeoutError):
            _client(retry_disconnect=0).chat([], [])
    assert stream.call_count == 1


@pytest.mark.parametrize("source", ["run", "child", "checker_failure"])
def test_timeout_does_not_retry_after_owner_stop(source):
    from threading import Event

    from llm_loop.core.run_context import child_cancel_event, current_wait_cancel_check

    stopped = Event()

    def checker():
        if source == "checker_failure":
            raise RuntimeError("cancellation authority unavailable")
        return source == "run" and stopped.is_set()

    def interrupted(*_args, **_kwargs):
        stopped.set()
        raise httpx.ReadTimeout("read interrupted after Stop")

    run_token = current_wait_cancel_check.set(checker)
    child_token = child_cancel_event.set(stopped if source == "child" else None)
    try:
        with mock.patch("httpx.Client") as client_cls:
            stream = client_cls.return_value.stream
            stream.side_effect = interrupted
            with pytest.raises(LLMTimeoutError):
                _client().chat([], [])
        assert stream.call_count == 1
    finally:
        child_cancel_event.reset(child_token)
        current_wait_cancel_check.reset(run_token)


@pytest.mark.parametrize("delta", [
    {"content": "partial"},
    {"reasoning_content": "thinking"},
    {"reasoning_details": [{"type": "reasoning.text", "text": "thinking"}]},
    {"reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque-state", "signature": "sig"}]},
    {"content": "<think>partial hidden text"},
    {"tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "write_file", "arguments": "{"}}]},
])
def test_timeout_after_any_output_is_never_replayed(delta):
    import json

    class Partial(_FakeStreamCtx):
        def iter_lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": delta}]})
            raise httpx.ReadTimeout("interrupted")

    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Partial([]), _success()]
        with pytest.raises(LLMTimeoutError):
            _client().chat([], [])
    assert stream.call_count == 1


@pytest.mark.parametrize("error_type", [httpx.WriteTimeout, httpx.PoolTimeout])
def test_other_timeout_phases_are_not_retried(error_type):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [error_type("timeout"), _success()]
        with pytest.raises(LLMTimeoutError):
            _client().chat([], [])
    assert stream.call_count == 1


def test_timeout_feedback_does_not_misdiagnose_credentials():
    text = llm_error_text(LLMTimeoutError("LLM 请求超时（120.0s）"))
    assert "LLMTimeoutError" in text and "120.0s" in text
    assert "Key/模型名配置" not in text
    assert "超时不等于" in text
    assert "重试" in text


def test_read_timeout_after_total_deadline_does_not_reset_stream_budget(monkeypatch):
    import llm_loop.llm.client as client_mod

    clock = {"now": 49.0}
    monkeypatch.setattr(client_mod, "_stream_total_deadline", lambda _: 50.0)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: clock["now"])

    class Expired(_FakeStreamCtx):
        def iter_lines(self):
            yield ": heartbeat"
            clock["now"] = 51.0
            raise httpx.ReadTimeout("read after total deadline")

    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [Expired([]), _success()]
        with pytest.raises(LLMTimeoutError, match="总时长"):
            _client().chat([], [])
    assert stream.call_count == 1


def test_timeout_retry_preserves_each_transport_receipt(tmp_path):
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

    def handler(request):
        requests.append(request.content)
        if len(requests) == 1:
            raise httpx.ReadTimeout("silent provider", request=request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
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
            assert client.chat([{"role": "user", "content": "task"}], []).content == "ok"
    finally:
        client.close()
    journal.settle_call(call, ProviderCallOutcome.SUCCESS)
    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == snapshot["attempts_settled"] == 2
    first, second = snapshot["attempts"]
    assert (first["outcome"], first["error_type"], first["transport_retry_index"]) == ("error", "ReadTimeout", 0)
    assert (second["outcome"], second["transport_retry_index"]) == ("success", 1)
    assert second["parent_attempt_id"] == first["attempt_id"]
    assert first["call_id"] == second["call_id"] == call.call_id
    assert len(requests) == 2 and requests[0] == requests[1]


def test_stop_during_disconnect_backoff_prevents_next_request(monkeypatch):
    from threading import Event

    import llm_loop.llm.client as client_mod
    from llm_loop.core.run_context import current_wait_cancel_check
    from llm_loop.llm.errors import LLMNetworkError

    stopped = Event()
    monkeypatch.setattr(client_mod.time, "sleep", lambda _: stopped.set())
    token = current_wait_cancel_check.set(stopped.is_set)
    try:
        with mock.patch("httpx.Client") as client_cls:
            stream = client_cls.return_value.stream
            stream.side_effect = [httpx.ConnectError("refused"), _success()]
            with pytest.raises(LLMNetworkError):
                _client().chat([], [])
        assert stopped.is_set() and stream.call_count == 1
    finally:
        current_wait_cancel_check.reset(token)
