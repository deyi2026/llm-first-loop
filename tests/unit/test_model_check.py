"""Install-time live model check: classification, redaction and endpoint shape."""

from __future__ import annotations

import io
import json
import urllib.error

from llm_loop.runtime import model_check


def _settings(**overrides):
    base = {
        "llm_api_key": "sk-secret-value",
        "llm_base_url": "https://api.deepseek.com",
        "llm_model": "deepseek-flash",
        "llm_wire_protocol": "openai",
    }
    base.update(overrides)
    return base


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


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.deepseek.com/v1/chat/completions", code, "error", {}, io.BytesIO(body.encode())
    )


def test_missing_configuration_returns_not_configured_without_network(monkeypatch):
    called = []
    monkeypatch.setattr(model_check, "_open", lambda *a, **k: called.append(1))
    result = model_check.check_model_config(_settings(llm_api_key=""))
    assert result["status"] == "not_configured"
    assert result["ok"] is False
    assert "LLM_API_KEY" in result["action"]
    assert called == []


def test_success_returns_ok_and_uses_openai_compatible_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        return _Response(json.dumps({"choices": [{"message": {"content": "pong"}}]}))

    monkeypatch.setattr(model_check, "_open", fake_urlopen)
    result = model_check.check_model_config(_settings(), timeout_s=7)
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert seen["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert seen["timeout"] == 7
    assert seen["auth"] == "Bearer sk-secret-value"


def test_base_url_already_ending_with_v1_is_not_doubled(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda request, timeout: (seen.setdefault("url", request.full_url), _Response("{}"))[1],
    )
    model_check.check_model_config(_settings(llm_base_url="https://gateway.example/v1"))
    assert seen["url"] == "https://gateway.example/v1/chat/completions"


def test_unauthorized_has_actionable_guidance(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(401, json.dumps({"error": {"message": "invalid api key"}}))
        ),
    )
    result = model_check.check_model_config(_settings())
    assert result["status"] == "unauthorized"
    assert result["http_status"] == 401
    assert "LLM_API_KEY" in result["action"]


def test_model_not_found_is_classified(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(404, json.dumps({"error": {"message": "model not found: foo"}}))
        ),
    )
    result = model_check.check_model_config(_settings(llm_model="foo"))
    assert result["status"] == "model_not_found"
    assert "LLM_MODEL" in result["action"]


def test_quota_exhausted_is_not_reported_as_plain_rate_limit(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(429, json.dumps({"error": {"message": "insufficient balance"}}))
        ),
    )
    result = model_check.check_model_config(_settings())
    assert result["status"] == "quota_exceeded"
    assert "余额" in result["action"]


def test_network_timeout_is_classified(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(model_check, "_open", fake_urlopen)
    result = model_check.check_model_config(_settings())
    assert result["status"] == "network_timeout"
    assert result["ok"] is False


def test_provider_error_body_never_leaks_api_key(monkeypatch):
    leaked = "sk-secret-value"
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(401, json.dumps({"error": {"message": "bad key " + leaked}}))
        ),
    )
    result = model_check.check_model_config(_settings())
    assert leaked not in json.dumps(result, ensure_ascii=False)


def test_non_json_200_is_invalid_response(monkeypatch):
    monkeypatch.setattr(
        model_check, "_open", lambda *a, **k: _Response("<html>gateway</html>")
    )
    result = model_check.check_model_config(_settings())
    assert result["status"] == "invalid_response"


def test_anthropic_protocol_uses_messages_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["key"] = request.get_header("X-api-key")
        return _Response("{}")

    monkeypatch.setattr(model_check, "_open", fake_urlopen)
    model_check.check_model_config(
        _settings(llm_base_url="https://api.anthropic.com", llm_wire_protocol="anthropic")
    )
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["key"] == "sk-secret-value"


def test_result_contains_no_config_values(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: _Response(json.dumps({"choices": [{"message": {"content": "pong"}}]})),
    )
    result = model_check.check_model_config(_settings())
    dumped = json.dumps(result, ensure_ascii=False)
    assert "sk-secret-value" not in dumped
    assert "deepseek-flash" not in dumped
    assert "api.deepseek.com" not in dumped
    assert "model" not in result and "endpoint_host" not in result


def test_rate_limit_exceeded_is_not_misclassified_as_quota(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(429, json.dumps({"error": {"message": "rate limit exceeded"}}))
        ),
    )
    result = model_check.check_model_config(_settings())
    assert result["status"] == "rate_limited"


def test_quota_wording_still_classified_as_quota(monkeypatch):
    monkeypatch.setattr(
        model_check,
        "_open",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(429, json.dumps({"error": {"message": "You exceeded your current quota"}}))
        ),
    )
    result = model_check.check_model_config(_settings())
    assert result["status"] == "quota_exceeded"


def test_redirect_is_refused_and_classified(monkeypatch):
    redirect = _Response("")
    redirect.status = 302
    monkeypatch.setattr(model_check, "_open", lambda *a, **k: redirect)
    result = model_check.check_model_config(_settings())
    assert result["status"] == "redirect"
    assert "LLM_BASE_URL" in result["action"]
    # The opener itself never follows: credentials cannot be forwarded.
    handler = model_check._NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other.example") is None
