"""Preserve the actual deployed privacy protections during the restart repair."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_loop.cache_guard.guard import _check_privacy
from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import LLMResponse
from llm_loop.memory.extractor import MemoryExtractor
from llm_loop.memory.store import MemoryStore
from llm_loop.security_guard import redact_secrets_for_transport, redact_sensitive_content


def _synthetic_key() -> str:
    return "sk-" + "a1b2c3d4" * 8


def test_privacy_check_covers_the_later_tool_message(monkeypatch):
    for name in ("LLM_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    messages = [{"role": "user", "content": "safe"} for _ in range(4)]
    messages.append({"role": "tool", "content": _synthetic_key()})
    decision = _check_privacy(messages, "")
    assert decision is not None and decision.rule == "privacy_leak"


def test_sensitive_file_values_are_redacted_before_context():
    value = _synthetic_key()
    redacted, count = redact_sensitive_content(
        "MINIMAX_API_KEY=" + value + "\nWORKSPACE=example\n"
    )
    assert count > 0 and value not in redacted
    assert "WORKSPACE=example" in redacted
    assert "MINIMAX_API_KEY=" in redacted


def test_transport_redaction_keeps_ordinary_token_counts():
    value = _synthetic_key()
    redacted, count = redact_secrets_for_transport("token: 3; credential " + value)
    assert count > 0 and value not in redacted
    assert "token: 3" in redacted
    assert _check_privacy([{"role": "user", "content": redacted}], "") is None


def test_memory_extraction_does_not_send_historical_secret(tmp_path):
    value = _synthetic_key()
    seen = []

    class Client:
        def chat(self, messages, tools):
            seen.extend(messages)
            return LLMResponse(content="", tool_calls=[], provider="fake")

    message = Message(role="tool", content=value, source=MessageSource.TOOL)
    store = SimpleNamespace(load=lambda _sid: SimpleNamespace(messages=[message]))
    extractor = MemoryExtractor(
        llm_client=Client(), memory=MemoryStore(tmp_path / "memory"),
        session_store=store, audit_dir=tmp_path / "audit",
    )
    extractor.extract_session("privacy-preservation", trigger="manual")
    assert seen
    assert all(value not in str(m) for m in seen)
    assert message.content == value


@pytest.mark.parametrize("assigned", [True, False])
@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("redactor", [redact_sensitive_content, redact_secrets_for_transport])
def test_private_key_body_is_removed_with_its_header(assigned, closed, redactor):
    header = "-----" + "BEGIN " + "RSA " + "PRIVATE KEY" + "-----"
    footer = "-----" + "END " + "RSA " + "PRIVATE KEY" + "-----"
    body = "SYNTHETIC_PRIVATE_BODY_FOR_LOCAL_TEST"
    source = header + "\n" + body + ("\n" + footer if closed else "")
    if assigned:
        source = "PRIVATE_KEY=" + chr(34) + source + chr(34)
    redacted, count = redactor(source)
    assert count > 0
    assert body not in redacted
    assert footer not in redacted
    assert _check_privacy([{"role": "tool", "content": redacted}], "") is None
    if closed:
        after, _ = redactor(source + "\nordinary trailing content")
        assert "ordinary trailing content" in after


def test_sensitive_read_entrypoint_discloses_redaction(tmp_path, monkeypatch):
    import llm_loop.tools.builtin.read_file as read_mod

    monkeypatch.setattr(read_mod, "seal_enabled", lambda: False)
    path = tmp_path / ".env"
    original = "MINIMAX_API_KEY=" + _synthetic_key() + "\nWORKSPACE=example\n"
    path.write_text(original)
    result = read_mod.ReadFileTool().execute(path=str(path))
    assert result.status.value == "success"
    assert _synthetic_key() not in result.content
    assert "敏感内容已脱敏" in result.content
    assert "WORKSPACE=example" in result.content
    assert path.read_text() == original


def test_sensitive_snapshot_is_refused_before_storage(tmp_path, monkeypatch):
    import llm_loop.tools.builtin.read_file as read_mod

    monkeypatch.setattr(read_mod, "seal_enabled", lambda: False)
    path = tmp_path / ".env"
    path.write_text("MINIMAX_API_KEY=" + _synthetic_key())
    result = read_mod.ReadFileTool().execute(path=str(path), snapshot=True)
    assert result.status.value == "failure"
    assert result.error_type == "SensitivePathSnapshotRefused"
    assert _synthetic_key() not in result.content
