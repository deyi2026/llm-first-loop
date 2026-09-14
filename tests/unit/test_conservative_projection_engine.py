"""Current durable truth rebuild at the real engine/client transport boundary."""

from __future__ import annotations

from copy import deepcopy
from unittest import mock

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.llm.errors import LLMHTTPError, LLMProjectionError
from tests.conftest import FakeLLM
from tests.unit.test_llm_client import _FakeStreamCtx


def _wire_client(engine):
    client = LLMClient(
        api_key="test", base_url="https://fake.local/v1", model="m",
        provider="glm", timeout_s=1.0,
    )
    engine.llm_pool.default_client = client
    return client


def _stream():
    return _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "done"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ])


def test_engine_rebuild_uses_latest_durable_truth(build_test_engine, monkeypatch):
    engine, _ = build_test_engine([])
    client = _wire_client(engine)
    original_build = engine._build_llm_messages
    snapshots = []

    def damaged_projection(sess, *args, **kwargs):
        original_build(sess, *args, **kwargs)
        # A result committed since any previous wire must survive rebuilding.
        sess.messages.append(Message(
            role="assistant", content="LATEST_DURABLE_FACT", source=MessageSource.USER,
        ))
        engine.session.save(sess)
        snapshots.append(deepcopy(sess.messages))
        return [{"role": "system", "content": "STALE_WIRE"}]

    monkeypatch.setattr(engine, "_build_llm_messages", damaged_projection)
    sid = engine.session.create()
    with mock.patch.object(client, "_client") as transport:
        transport.stream.return_value = _stream()
        result = engine.run(sid, "CURRENT_INGRESS")
        assert transport.stream.call_count == 1, result
        sent = transport.stream.call_args.kwargs["json"]["messages"]
    assert result.projection_validator_failed
    assert result.projection_rebuilt
    assert not result.projection_cannot_fit
    assert not result.run_incomplete
    assert any("LATEST_DURABLE_FACT" in str(row.get("content")) for row in sent)
    assert all("STALE_WIRE" not in str(row.get("content")) for row in sent)
    assert all("_active_run_ingress_ref" not in row for row in sent)
    assert engine.session.load(sid).messages[:len(snapshots[0])] == snapshots[0]


def test_llm_client_blocks_invalid_canonical_wire_before_transport():
    client = LLMClient(
        api_key="test", base_url="https://fake.local/v1", model="m",
        provider="glm", timeout_s=1.0, guard_enabled=False,
    )
    client._client = mock.Mock()
    invalid_messages = [
        [{"role": "system", "content": "SYS"}, {"role": "alien", "content": "x"}],
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": {"text": "x"}}],
    ]

    for messages in invalid_messages:
        with pytest.raises(LLMProjectionError):
            client.chat(messages, [])

    client._client.stream.assert_not_called()


def test_approximate_window_estimate_cannot_block_conservative_rebuild_transport(
    build_test_engine, monkeypatch,
):
    """Chars/token window estimates are planning facts, never pre-provider hard authority."""
    engine, _ = build_test_engine([])
    client = _wire_client(engine)
    monkeypatch.setattr(engine, "_build_llm_messages", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_effective_history_budget", lambda *a, **k: 1)
    monkeypatch.setattr(
        engine, "_effective_history_budget_detail",
        lambda *a, **k: {
            "effective_budget": 1,
            "model_window_budget": 1,
            "limited_by": "model_window",
        },
    )
    sid = engine.session.create()
    with mock.patch.object(client, "_client") as transport:
        transport.stream.return_value = _stream()
        result = engine.run(sid, "CURRENT_INGRESS_TOO_LARGE")
        assert transport.stream.call_count == 1, result
    assert result.projection_validator_failed
    assert result.projection_rebuilt
    assert not result.projection_cannot_fit
    assert not result.run_incomplete
    assert not result.provider_output_truncated
    assert any(m.content == "CURRENT_INGRESS_TOO_LARGE" for m in engine.session.load(sid).messages)


def test_provider_overflow_on_mandatory_only_rebuild_is_cannot_fit(
    build_test_engine, monkeypatch,
):
    """Only provider overflow can prove the conservative mandatory set cannot fit."""
    engine, _ = build_test_engine([])
    client = _wire_client(engine)
    monkeypatch.setattr(engine, "_build_llm_messages", lambda *a, **k: [])
    overflow = LLMHTTPError("maximum context length exceeded", status_code=400)
    sid = engine.session.create()
    with mock.patch.object(client, "_client") as transport:
        transport.stream.side_effect = overflow
        result = engine.run(sid, "MANDATORY_ONLY_CURRENT_INGRESS")
        assert transport.stream.call_count == 1, (
            "provider-authoritative minimal overflow must not be retried", result
        )

    assert result.projection_validator_failed
    assert result.projection_rebuilt
    assert result.projection_cannot_fit
    assert result.run_incomplete
    assert not result.provider_output_truncated
    assert "上下文压力" in result.final_answer
    assert any(
        m.content == "MANDATORY_ONLY_CURRENT_INGRESS" for m in engine.session.load(sid).messages
    )


@pytest.mark.parametrize("persistent_corruption", [False, True])
def test_final_validator_gets_one_durable_rebuild(
    build_test_engine, monkeypatch, persistent_corruption,
):
    engine, _ = build_test_engine([])
    client = _wire_client(engine)
    original_normalize = client._normalize_tool_call_args
    attempts = []

    def corrupt_after_projection(messages):
        messages, diag = original_normalize(messages)
        attempts.append(deepcopy(messages))
        if persistent_corruption or len(attempts) == 1:
            messages = [*messages, {"role": "system", "content": "INVALID_LATE_SYSTEM"}]
        return messages, diag

    monkeypatch.setattr(client, "_normalize_tool_call_args", corrupt_after_projection)
    sid = engine.session.create()
    with mock.patch.object(client, "_client") as transport:
        transport.stream.return_value = _stream()
        result = engine.run(sid, "CURRENT_INGRESS")
        assert transport.stream.call_count == (0 if persistent_corruption else 1), result
    assert len(attempts) == 2
    assert result.projection_validator_failed
    assert result.projection_rebuilt
    assert result.run_incomplete is persistent_corruption
    assert not result.provider_output_truncated
    assert result.rounds == 1  # Pre-transport repair is not a new model round.


def test_tool_round_truncation_is_not_lost_after_completed_response(build_test_engine):
    engine, _ = build_test_engine([
        LLMResponse(
            content="", tool_calls=[FakeLLM.tool("read_file", {"path": "missing.txt"})],
            provider="fake", truncated=True,
        ),
        {"content": "done"},
    ])
    result = engine.run(engine.session.create(), "check")
    assert result.provider_output_truncated
    assert result.run_incomplete
    assert result.truncated
