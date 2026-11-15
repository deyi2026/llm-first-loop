"""The Provider sees a safe projection; durable Session/Evidence stay untouched."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from llm_loop.cache_guard.guard import CacheGuardBlockedError
from llm_loop.llm.client import GuardRequestContext, LLMClient
from llm_loop.llm.outbound_privacy import redact_provider_request

SECRET = "SYNTHETIC_LFL_ENV_CREDENTIAL_" + "q" * 32


class _Stream:
    status_code = 200
    reason_phrase = "OK"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self):
        yield 'data: {"choices": [{"delta": {"content": "ok"}}]}'
        yield 'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}'
        yield "data: [DONE]"


def _client(tmp_path):
    return LLMClient(
        api_key="k", base_url="https://fake.local/v1",
        model="m", guard_audit_file=tmp_path / "guard.jsonl",
    )


def _paired_history(secret):
    return [
        {"role": "system", "content": "Safe baseline"},
        {"role": "user", "content": "Explain the tool result"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function", "function": {
                "name": "read_evidence", "arguments": '{"evidence_ref":"evidence://safe"}',
            },
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "safe"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_2", "type": "function", "function": {
                "name": "read_evidence", "arguments": '{"evidence_ref":"evidence://safe2"}',
            },
        }]},
        {"role": "tool", "tool_call_id": "call_2", "content": "historical: " + secret},
    ]


def test_historical_late_tool_secret_redacted_before_guard_and_wire(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    raw = _paired_history(SECRET)
    with mock.patch("httpx.Client") as cls:
        cls.return_value.stream.return_value = _Stream()
        response = _client(tmp_path).chat(raw, tools=[])
        payload = cls.return_value.stream.call_args.kwargs["json"]
    assert response.content == "ok"
    assert SECRET not in json.dumps(payload)
    assert payload["messages"][-1]["tool_call_id"] == "call_2"
    assert payload["messages"][-1]["content"].startswith("historical: ")
    assert raw[-1]["content"].endswith(SECRET)  # no historical mutation
    audit = [json.loads(s) for s in (tmp_path / "guard.jsonl").read_text().splitlines()]
    assert audit[-1]["verdict"] == "ALLOW"


def test_nested_tool_args_and_tool_schema_are_sanitized(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    msgs = [{"role": "assistant", "tool_calls": [{
        "id": "call_3", "type": "function",
        "function": {"name": "lookup", "arguments": {"nested": [SECRET]}},
    }]}]
    tools = [{"type": "function", "function": {
        "name": "lookup", "description": "credential " + SECRET,
        "parameters": {"type": "object", "properties": {"arg": {"default": SECRET}}},
    }}]
    safe_msgs, safe_tools, safe_sys, count = redact_provider_request(msgs, tools, "sys " + SECRET)
    assert count >= 4
    assert SECRET not in json.dumps([safe_msgs, safe_tools, safe_sys])
    assert safe_msgs[0]["tool_calls"][0]["id"] == "call_3"
    assert SECRET in json.dumps([msgs, tools])  # original unchanged


def test_clean_request_is_identity_preserving(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    msgs = [{"role": "assistant", "content": "normal", "tool_calls": [{
        "id": "c", "type": "function", "function": {"name": "safe", "arguments": "{}"},
    }], "reasoning_details": [{"signature": "signed-token", "text": "safe"}]}]
    tools = [{"type": "function", "function": {"name": "safe", "description": "safe"}}]
    safe_msgs, safe_tools, safe_sys, count = redact_provider_request(msgs, tools, "baseline")
    assert safe_msgs is msgs and safe_tools is tools and safe_sys == "baseline"
    assert count == 0


@pytest.mark.parametrize("protected_field", ["id", "tool_call_id", "signature", "reasoning_details"])
def test_secret_in_structural_or_signed_field_is_hard_block(monkeypatch, protected_field):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    msgs = [{"role": "assistant", protected_field: SECRET}]
    with pytest.raises(CacheGuardBlockedError, match="未发送 Provider"):
        redact_provider_request(msgs, [], "baseline")
    assert msgs[0][protected_field] == SECRET


def test_signed_replay_failure_never_calls_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    with mock.patch("httpx.Client") as cls:
        client = _client(tmp_path)
        with pytest.raises(CacheGuardBlockedError):
            client.chat([{"role": "assistant", "reasoning_details": [{
                "signature": "signed", "text": SECRET,
            }]}], [])
        cls.return_value.stream.assert_not_called()


def test_redactor_failure_is_hard_block_even_when_guard_disabled(monkeypatch, tmp_path):
    import llm_loop.llm.outbound_privacy as privacy

    def fail(_text):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(privacy, "redact_secrets_for_transport", fail)
    with mock.patch("httpx.Client") as cls:
        client = _client(tmp_path)
        client.guard_enabled = False
        with pytest.raises(CacheGuardBlockedError, match="未发送 Provider"):
            client.chat([{"role": "user", "content": "safe"}], [])
        cls.return_value.stream.assert_not_called()


def test_guard_context_uses_redacted_system_and_is_not_mutated(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    ctx = GuardRequestContext(session_id="safe-session", system_text="system " + SECRET)
    with mock.patch("httpx.Client") as cls:
        cls.return_value.stream.return_value = _Stream()
        client = _client(tmp_path)
        guard = client.ensure_guard()
        with mock.patch.object(guard, "check", wraps=guard.check) as spy:
            response = client.chat([{"role": "user", "content": "hi"}], [], guard_context=ctx)
            assert SECRET not in spy.call_args.kwargs["system_text"]
        assert response.content == "ok"
    assert ctx.system_text.endswith(SECRET)


def test_other_high_confidence_pattern_redacted(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    synthetic = "sk" + "-" + "Z" * 40
    raw = [{"role": "tool", "content": synthetic}]
    safe, _, _, count = redact_provider_request(raw, [], "")
    assert count >= 1 and synthetic not in safe[0]["content"]
    assert raw[0]["content"] == synthetic


def test_no_cross_session_secret_state(monkeypatch):
    first = SECRET
    second = "SYNTHETIC_OTHER_ENV_CREDENTIAL_" + "p" * 32
    monkeypatch.setenv("LLM_API_KEY", first)
    a, _, _, _ = redact_provider_request([{"role": "user", "content": first}], [], "")
    monkeypatch.setenv("LLM_API_KEY", second)
    b, _, _, _ = redact_provider_request([{"role": "user", "content": second}], [], "")
    assert first not in a[0]["content"] and second not in b[0]["content"]
