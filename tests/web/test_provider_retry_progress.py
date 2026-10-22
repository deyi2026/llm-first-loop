"""Retry facts survive both SSE paths and cannot be reordered behind recovery."""

import queue
from types import SimpleNamespace
from unittest import mock

import pytest

from llm_loop.core.loop import LoopResult
from tests.web.test_stream_endpoint import _make_client, _parse_sse


@pytest.mark.parametrize("background", [False, True])
def test_retry_is_an_ordered_sse_fact_not_answer_or_reasoning(build_test_engine, background):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.llm.client import ProviderRetryInfo, StreamDelta

    engine, _ = build_test_engine([])
    sid = engine.session.create()
    result = LoopResult(session_id=sid, final_answer="beforeafter")
    deltas = [
        StreamDelta(text="before"),
        StreamDelta(provider_retry=ProviderRetryInfo("timeout", 1, 1)),
        StreamDelta(text="after"),
    ]
    client = _make_client(engine)

    if background:
        engine.runner = BackgroundRunner(engine, enabled=True)
        events = queue.Queue()
        for delta in deltas:
            events.put({"type": "delta", "delta": delta})
        events.put({"type": "done", "result": result})
        with (
            mock.patch.object(engine.runner, "start", return_value=(
                SimpleNamespace(run_generation="retry-generation"), events,
            )),
            mock.patch.object(engine.runner, "unsubscribe"),
        ):
            response = client.post("/api/v1/chat/stream", json={"message": "task", "session_id": sid})
    else:
        def run(*args, **kwargs):
            yield from deltas
            return result

        with mock.patch.object(engine, "_run_stream_with_acquired", side_effect=run):
            response = client.post("/api/v1/chat/stream", json={"message": "task", "session_id": sid})

    facts = [e for e in _parse_sse(response.text) if e["type"] != "run_started"]
    assert [e["type"] for e in facts] == ["answer_delta", "provider_retry", "answer_delta", "done"]
    assert facts[1]["data"] == {"reason": "timeout", "retry_index": 1, "max_retries": 1}
    assert facts[0]["data"]["data"] == "before"
    assert facts[2]["data"]["data"] == "after"


@pytest.mark.parametrize("background", [False, True])
def test_engine_forwards_retry_without_persisting_program_text(build_test_engine, background):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.llm.client import ProviderRetryInfo, StreamDelta
    from tests.unit.test_stream_equivalence import StreamingFakeLLM

    class RetryingLLM(StreamingFakeLLM):
        def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
            yield StreamDelta(provider_retry=ProviderRetryInfo("disconnect", 1, 1))
            return (yield from super().chat_stream(messages, tools, timeout_s=timeout_s, model=model))

    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = RetryingLLM("recovered")
    if background:
        engine.runner = BackgroundRunner(engine, enabled=True)
    response = _make_client(engine).post("/api/v1/chat/stream", json={"message": "task"})
    facts = _parse_sse(response.text)
    assert len([e for e in facts if e["type"] == "provider_retry"]) == 1
    done = facts[-1]["data"]
    assert done["final_answer"] == "recovered"
    assert not done.get("reasoning_content")
