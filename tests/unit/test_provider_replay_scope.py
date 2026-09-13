from __future__ import annotations

from copy import deepcopy
from unittest import mock

from llm_loop.llm.client import GuardRequestContext
from llm_loop.runtime.causality import effective_generation_contract
from tests.unit.test_llm_client import _client, _FakeStreamCtx


def _replay_message(client, *, details=None) -> dict:
    native = details or [{"type": "reasoning.text", "text": "native", "signature": "sig"}]
    contract = effective_generation_contract(client)
    return {
        "role": "assistant",
        "content": "VISIBLE",
        "reasoning_content": "normalized-visible-reasoning",
        "_provider_replay": {
            "provider": client.provider,
            "model": client.model,
            "generation_contract": contract,
            "fields": {"reasoning_details": native},
        },
    }


def test_provider_replay_exact_scope_projects_native_state() -> None:
    client = _client(provider="minimax", model="MiniMax-M3", reasoning_split=True)
    source = _replay_message(client)

    projected = client._project_provider_replay([source])  # noqa: SLF001

    assert projected[0]["content"] == "VISIBLE"
    assert projected[0]["reasoning_details"][0]["signature"] == "sig"
    assert "reasoning_content" not in projected[0]
    assert "_provider_replay" not in projected[0]


def test_provider_replay_same_provider_different_model_fails_closed_and_keeps_visible_state() -> None:
    source_client = _client(provider="minimax", model="MiniMax-M3", reasoning_split=True)
    target_client = _client(provider="minimax", model="MiniMax-M4", reasoning_split=True)
    source = _replay_message(source_client)
    original = deepcopy(source)

    projected = target_client._project_provider_replay([source])  # noqa: SLF001

    assert projected[0]["content"] == "VISIBLE"
    assert projected[0]["reasoning_content"] == "normalized-visible-reasoning"
    assert "reasoning_details" not in projected[0]
    assert "_provider_replay" not in projected[0]
    assert source == original, "projection must not mutate durable replay evidence"


def test_provider_replay_same_model_changed_generation_contract_fails_closed() -> None:
    source_client = _client(
        provider="minimax",
        model="MiniMax-M3",
        reasoning_split=True,
        send_tool_choice=False,
    )
    target_client = _client(
        provider="minimax",
        model="MiniMax-M3",
        reasoning_split=False,
        send_tool_choice=False,
    )
    source = _replay_message(source_client)

    projected = target_client._project_provider_replay([source])  # noqa: SLF001

    assert projected[0]["content"] == "VISIBLE"
    assert projected[0]["reasoning_content"] == "normalized-visible-reasoning"
    assert "reasoning_details" not in projected[0]


def test_provider_replay_legacy_provider_only_marker_never_gains_native_replay_authority() -> None:
    client = _client(provider="minimax", model="MiniMax-M3", reasoning_split=True)
    source = {
        "role": "assistant",
        "content": "VISIBLE",
        "reasoning_content": "legacy-normalized",
        "_provider_replay": {
            "provider": "minimax",
            "fields": {"reasoning_details": [{"type": "reasoning.text", "text": "legacy-native"}]},
        },
    }

    projected = client._project_provider_replay([source])  # noqa: SLF001

    assert projected[0]["content"] == "VISIBLE"
    assert projected[0]["reasoning_content"] == "legacy-normalized"
    assert "reasoning_details" not in projected[0]
    assert "_provider_replay" not in projected[0]


def test_provider_replay_cross_provider_still_fails_closed() -> None:
    source_client = _client(provider="minimax", model="MiniMax-M3", reasoning_split=True)
    target_client = _client(provider="deepseek", model="MiniMax-M3", reasoning_split=True)
    source = _replay_message(source_client)

    projected = target_client._project_provider_replay([source])  # noqa: SLF001

    assert projected[0]["content"] == "VISIBLE"
    assert projected[0]["reasoning_content"] == "normalized-visible-reasoning"
    assert "reasoning_details" not in projected[0]



def test_provider_replay_producer_binds_per_call_model_in_terminal_and_stream_checkpoint() -> None:
    observed: list[dict] = []
    ctx = GuardRequestContext(stream_state_hook=observed.append)
    lines = [
        'data: {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "plan", "signature": "scope-sig"}]}}]}',
        'data: {"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        client = _client(provider="minimax", model="base-model", reasoning_split=True)
        resp = client.chat(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model="per-call-model",
            guard_context=ctx,
        )

    assert resp.provider_replay is not None
    terminal = resp.provider_replay
    assert terminal["provider"] == "minimax"
    assert terminal["model"] == "per-call-model"
    assert terminal["generation_contract"]["model"] == "per-call-model"
    assert terminal["generation_contract"]["reasoning_split"] is True
    assert observed
    checkpoint = observed[0]["provider_replay"]
    assert checkpoint["model"] == "per-call-model"
    assert checkpoint["generation_contract"] == terminal["generation_contract"]
