"""Silent network recovery must surface UI facts without becoming model output."""

from threading import Event
from unittest import mock

import httpx
import pytest

from llm_loop.core.run_context import child_cancel_event
from llm_loop.llm.errors import LLMNetworkError, LLMTimeoutError
from tests.unit.test_llm_client import _client
from tests.unit.test_timeout_recovery import _success


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_retry_notice_precedes_recovery_and_never_changes_payload_or_answer(error):
    with mock.patch("httpx.Client") as client_cls:
        stream = client_cls.return_value.stream
        stream.side_effect = [error("private-endpoint-must-not-be-displayed"), _success()]
        it = _client().chat_stream([{"role": "user", "content": "task"}], [])
        notice = next(it)
        assert notice.provider_retry is not None
        assert notice.provider_retry.retry_index == 1
        assert notice.provider_retry.max_retries == 1
        assert notice.provider_retry.reason == (
            "timeout" if error is httpx.ReadTimeout else "disconnect"
        )
        assert not notice.text and not notice.reasoning
        assert stream.call_count == 1  # report before issuing the next request
        while True:
            try:
                next(it)
            except StopIteration as terminal:
                response = terminal.value
                break
    assert stream.call_args_list[0] == stream.call_args_list[1]
    assert response.content == "recovered"
    assert response.reasoning_content is None


def test_stop_after_retry_notice_cannot_start_another_request():
    stop = Event()
    token = child_cancel_event.set(stop)
    try:
        with mock.patch("httpx.Client") as client_cls:
            stream = client_cls.return_value.stream
            stream.side_effect = [httpx.ReadTimeout("silent"), _success()]
            it = _client().chat_stream([], [])
            assert next(it).provider_retry is not None
            stop.set()
            with pytest.raises(LLMTimeoutError):
                next(it)
        assert stream.call_count == 1
    finally:
        child_cancel_event.reset(token)


def test_ssl_eof_retry_rebuilds_transport_with_same_proxy_policy_and_payload():
    """Pool retirement must not make the current retry reuse stale proxy mounts."""
    first = mock.Mock()
    second = mock.Mock()
    first.stream.side_effect = httpx.ConnectError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
    )
    second.stream.return_value = _success()
    with mock.patch("httpx.Client", side_effect=[first, second]) as client_cls:
        result = _client().chat([{"role": "user", "content": "task"}], [])
    assert result.content == "recovered"
    assert client_cls.call_count == 2
    assert client_cls.call_args_list[0] == client_cls.call_args_list[1]
    assert first.stream.call_count == second.stream.call_count == 1
    assert first.stream.call_args == second.stream.call_args
    first.close.assert_not_called()  # concurrent calls may still own it
    second.close.assert_called_once_with()


def test_ssl_eof_no_retry_does_not_create_second_transport():
    first = mock.Mock()
    first.stream.side_effect = httpx.ConnectError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] handshake failed"
    )
    with mock.patch("httpx.Client", return_value=first) as client_cls, pytest.raises(LLMNetworkError):
        _client(retry_disconnect=0).chat([], [])
    assert client_cls.call_count == 1
    first.close.assert_not_called()
