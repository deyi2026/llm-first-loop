"""Silent network recovery must surface UI facts without becoming model output."""

from threading import Event
from unittest import mock

import httpx
import pytest

from llm_loop.core.run_context import child_cancel_event
from llm_loop.llm.errors import LLMTimeoutError
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
