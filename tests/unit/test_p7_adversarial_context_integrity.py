"""P7 adversarial concurrency qualification at the physical provider boundary.

These tests deliberately combine ownership layers that earlier phase-specific tests
exercise separately.  They use one production ``LLMClient`` instance and replace only
its already-constructed ``_client.stream`` transport, so assertions observe the JSON
packet that would actually leave the process.
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy

import pytest

from llm_loop.core.loop.runner import SessionBusyError
from llm_loop.llm.client import LLMClient
from tests.unit.test_llm_client import _FakeStreamCtx


def _shared_remote_client(engine) -> LLMClient:
    client = LLMClient(
        api_key="test",
        base_url="https://glm.invalid/v1",
        model="fake-model",
        provider="glm",
        timeout_s=5.0,
        guard_enabled=False,
    )
    engine.llm_pool.default_client = client
    return client


def _completion(text: str) -> _FakeStreamCtx:
    return _FakeStreamCtx(
        [
            f'data: {json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False)}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
    )


def test_two_sessions_share_one_client_without_wire_or_response_crossing(
    build_test_engine,
) -> None:
    """Force two sessions to overlap exactly at ``_client.stream``.

    The test fails if request-scoped ingress/guard/provider state is stored on the
    shared client and overwritten by the other session before physical send.
    """

    engine, _fake = build_test_engine([])
    client = _shared_remote_client(engine)
    barrier = threading.Barrier(2)
    capture_lock = threading.Lock()
    payloads: list[dict] = []

    def stream(_method, _url, **kwargs):
        payload = deepcopy(kwargs["json"])
        wire = json.dumps(payload, ensure_ascii=False)
        with capture_lock:
            payloads.append(payload)
        # Both complete payloads must exist concurrently before either response starts.
        barrier.wait(timeout=5.0)
        if "P7-A" in wire and "P7-B" not in wire:
            return _completion("A-OK")
        if "P7-B" in wire and "P7-A" not in wire:
            return _completion("B-OK")
        raise AssertionError(f"crossed or missing ingress in physical payload: {wire[:500]}")

    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    sid_a = engine.session.create()
    sid_b = engine.session.create()
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def run_one(sid: str, text: str, key: str) -> None:
        try:
            results[key] = engine.run(sid, text)
        except BaseException as exc:  # noqa: BLE001 - thread qualification must retain exact failure
            errors.append(exc)

    ta = threading.Thread(target=run_one, args=(sid_a, "P7-A", "a"), daemon=True)
    tb = threading.Thread(target=run_one, args=(sid_b, "P7-B", "b"), daemon=True)
    ta.start()
    tb.start()
    ta.join(timeout=10.0)
    tb.join(timeout=10.0)

    assert not ta.is_alive() and not tb.is_alive(), "concurrent provider requests did not settle"
    assert not errors, errors
    assert results["a"].final_answer.startswith("A-OK")
    assert results["b"].final_answer.startswith("B-OK")
    assert len(payloads) == 2

    wires = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    assert sum("P7-A" in wire for wire in wires) == 1
    assert sum("P7-B" in wire for wire in wires) == 1
    assert all("_active_run_ingress_ref" not in wire for wire in wires)
    assert all("_provider_replay" not in wire for wire in wires)

    durable_a = json.dumps(
        [{"role": m.role, "content": m.content} for m in engine.session.load(sid_a).messages],
        ensure_ascii=False,
    )
    durable_b = json.dumps(
        [{"role": m.role, "content": m.content} for m in engine.session.load(sid_b).messages],
        ensure_ascii=False,
    )
    assert "P7-A" in durable_a and "P7-B" not in durable_a
    assert "P7-B" in durable_b and "P7-A" not in durable_b


def test_same_session_overlap_is_rejected_before_second_physical_send(
    build_test_engine,
) -> None:
    """Hold run A at transport; a second run for the same Session must fail closed."""

    engine, _fake = build_test_engine([])
    client = _shared_remote_client(engine)
    entered = threading.Event()
    release = threading.Event()
    capture_lock = threading.Lock()
    payloads: list[dict] = []

    def stream(_method, _url, **kwargs):
        with capture_lock:
            payloads.append(deepcopy(kwargs["json"]))
        entered.set()
        assert release.wait(timeout=5.0), "qualification transport release timed out"
        return _completion("FIRST-OK")

    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    sid = engine.session.create()
    first: dict[str, object] = {}
    first_errors: list[BaseException] = []

    def run_first() -> None:
        try:
            first["result"] = engine.run(sid, "P7-FIRST")
        except BaseException as exc:  # noqa: BLE001
            first_errors.append(exc)

    thread = threading.Thread(target=run_first, daemon=True)
    thread.start()
    assert entered.wait(timeout=5.0), "first run did not reach physical transport"
    try:
        with pytest.raises(SessionBusyError):
            engine.run(sid, "P7-SECOND")
        assert len(payloads) == 1, "busy same-session request reached physical transport"
    finally:
        release.set()
        thread.join(timeout=10.0)

    assert not thread.is_alive()
    assert not first_errors, first_errors
    assert first["result"].final_answer.startswith("FIRST-OK")
    durable = json.dumps(
        [{"role": m.role, "content": m.content} for m in engine.session.load(sid).messages],
        ensure_ascii=False,
    )
    assert "P7-FIRST" in durable
    assert "P7-SECOND" not in durable
