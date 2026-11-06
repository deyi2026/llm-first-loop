"""Live model check must send the same wire model name as the runtime client.

Regression: ``LLM_MODEL=minimax/MiniMax-M3.1-Flash`` is a registry reference.
The runtime client sends the bare model id (the OpenAI-compatible endpoint
rejects the qualified form), so the online check used to report
model_not_found for a perfectly working configuration.
"""

from __future__ import annotations

import json

from llm_loop.runtime import model_check


class _Response:
    status = 200

    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _settings(**overrides):
    base = {
        "llm_api_key": "sk-test-key",
        "llm_base_url": "https://api.minimax.cn/v1",
        "llm_model": "minimax/MiniMax-M3.1-Flash",
        "llm_wire_protocol": "openai",
        "data_dir": "",
    }
    base.update(overrides)
    return base


def _capture(monkeypatch) -> dict:
    seen: dict = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data.decode("utf-8")) if request.data else {}
        return _Response(json.dumps({"choices": [{"message": {"content": "pong"}}]}))

    monkeypatch.setattr(model_check, "_open", fake_urlopen)
    return seen


def _provider_dir(tmp_path) -> str:
    """DATA_DIR with a minimax provider registered (mirrors a real install)."""
    (tmp_path / "providers.local.json").write_text(
        json.dumps({"minimax": {"base_url": "https://api.minimax.cn/v1", "models": {}}}),
        encoding="utf-8",
    )
    return str(tmp_path)


def test_known_provider_prefix_is_sent_as_bare_model(monkeypatch, tmp_path):
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(_settings(data_dir=_provider_dir(tmp_path)))
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "MiniMax-M3.1-Flash"
    assert seen["url"] == "https://api.minimax.cn/v1/chat/completions"


def test_unknown_provider_prefix_is_preserved(monkeypatch, tmp_path):
    """Only known provider ids are stripped: a model name may contain "/"."""
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(llm_model="qwen/qwen3-32b", data_dir=_provider_dir(tmp_path))
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "qwen/qwen3-32b"


def test_bare_model_is_unchanged(monkeypatch, tmp_path):
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(llm_model="MiniMax-M3.1-Flash", data_dir=_provider_dir(tmp_path))
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "MiniMax-M3.1-Flash"


def test_explicit_wire_model_wins(monkeypatch, tmp_path):
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(llm_wire_model="MiniMax-M2.5", data_dir=_provider_dir(tmp_path))
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "MiniMax-M2.5"


def test_anthropic_protocol_sends_bare_model(monkeypatch, tmp_path):
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(
            llm_wire_protocol="anthropic",
            llm_base_url="https://api.minimax.cn/anthropic",
            data_dir=_provider_dir(tmp_path),
        )
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "MiniMax-M3.1-Flash"
    assert seen["url"] == "https://api.minimax.cn/anthropic/v1/messages"


def test_google_protocol_sends_bare_model_in_url(monkeypatch, tmp_path):
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(
            llm_wire_protocol="google",
            llm_base_url="https://generativelanguage.googleapis.com",
            data_dir=_provider_dir(tmp_path),
        )
    )
    assert result["status"] == "ok"
    assert "minimax" not in seen["url"]
    assert "/models/MiniMax-M3.1-Flash:generateContent" in seen["url"]


def test_provider_id_derived_from_base_url_without_registry(monkeypatch, tmp_path):
    """L0 path: the endpoint itself identifies the provider id."""
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(data_dir=str(tmp_path / "no-registry"))
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "MiniMax-M3.1-Flash"


def test_model_providers_json_id_is_stripped(monkeypatch, tmp_path):
    """A provider id registered through MODEL_PROVIDERS is a known id."""
    seen = _capture(monkeypatch)
    result = model_check.check_model_config(
        _settings(
            llm_model="myco/model-x",
            llm_base_url="https://api.myco.example/v1",
            model_providers_raw=json.dumps({"myco": {"base_url": "https://api.myco.example/v1"}}),
            data_dir=str(tmp_path / "no-registry"),
        )
    )
    assert result["status"] == "ok"
    assert seen["payload"]["model"] == "model-x"
