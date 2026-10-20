"""Install-time live model check: one bounded request, classified failure, no retry.

``lfl doctor`` defaults to offline local preflight.  Only an explicit request
(``lfl doctor --online`` or the post-write check in ``lfl init``) calls this module.
It does not build an Engine, write configuration, retry, switch models or probe
beyond the single user-facing request needed to answer one question: "does the
configured endpoint accept this key and model right now?"

The result never contains credential or configuration values: no API key, no
model name, no endpoint host.  Provider response bodies are truncated and
redacted before they leave this module.  Redirects are not followed, so the
credential-bearing request is never forwarded to a different host.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

DEFAULT_TIMEOUT_S = 15.0
_MAX_BODY_CHARS = 4096
_MAX_MESSAGE_CHARS = 300


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: follow nothing, forward credentials nowhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _open(request: urllib.request.Request, timeout: float):
    """Single dispatch seam (tests patch this) that never follows redirects."""
    return _OPENER.open(request, timeout=timeout)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _endpoint(base_url: str, protocol: str, model: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Return (url, headers, payload) for one minimal completion request."""
    url = base_url.rstrip("/")
    protocol = (protocol or "openai").strip().lower()
    if protocol == "anthropic":
        if not url.endswith("/messages"):
            url = url + "/messages" if url.endswith("/v1") else url + "/v1/messages"
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        return url, {"anthropic-version": "2023-06-01", "Content-Type": "application/json"}, payload
    if protocol == "google":
        if ":generateContent" not in url:
            quoted = urllib.parse.quote(model, safe="")
            url = url + "/v1beta/models/" + quoted + ":generateContent"
        payload = {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
        return url, {"Content-Type": "application/json"}, payload
    # OpenAI-compatible: DeepSeek / GLM / OpenAI / most gateways.
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions" if url.endswith("/v1") else url + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    return url, {"Content-Type": "application/json"}, payload


def _auth_headers(protocol: str, api_key: str) -> dict[str, str]:
    protocol = (protocol or "openai").strip().lower()
    if protocol == "anthropic":
        return {"x-api-key": api_key}
    if protocol == "google":
        return {"x-goog-api-key": api_key}
    return {"Authorization": "Bearer " + api_key}


def _redact(value: str, secrets: list[str]) -> str:
    out = value
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, "***")
    return out


def _extract_error_message(body: str, secrets: list[str]) -> str:
    """Best-effort human-readable message from common provider error shapes."""
    message = ""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = _text(error.get("message") or error.get("detail") or error.get("code"))
        elif isinstance(error, str):
            message = _text(error)
        if not message:
            message = _text(data.get("message") or data.get("detail") or data.get("msg"))
    if not message:
        message = " ".join(body.split())
    return _redact(message, secrets)[:_MAX_MESSAGE_CHARS]


def _network_status(exc: BaseException) -> tuple[str, str, str]:
    reason = getattr(exc, "reason", exc)
    text = str(reason).lower()
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
        return (
            "network_timeout",
            "连接 LLM_BASE_URL 超时。",
            "检查网络/代理与目标地址是否可达（例如 curl -I <base_url>），"
            "或在配置中适当提高 LLM_TIMEOUT_S；企业网络通常需要 HTTPS_PROXY。",
        )
    if isinstance(reason, socket.gaierror) or "name or service not known" in text or "nodename nor servname" in text:
        return (
            "dns_error",
            "无法解析 LLM_BASE_URL 的主机名。",
            "检查 LLM_BASE_URL 拼写与 DNS；离线环境请改用可访问的内网网关地址。",
        )
    if isinstance(reason, ssl.SSLError) or "certificate" in text or "ssl" in text:
        return (
            "tls_error",
            "TLS/证书校验失败。",
            "检查代理或网关证书链，使用受信任证书；不要通过关闭校验绕过（会泄露凭据）。",
        )
    if isinstance(reason, ConnectionRefusedError) or "refused" in text:
        return (
            "connection_refused",
            "目标地址拒绝连接。",
            "确认 LLM_BASE_URL 的协议、端口与路径正确，且服务已启动；"
            "常见错误是填了网页地址而不是 API 地址。",
        )
    return (
        "network_error",
        "无法连接模型服务。",
        "检查网络、代理、DNS 与 LLM_BASE_URL；确认该地址可从当前机器访问。",
    )


def _http_status(
    status: int, body: str, secrets: list[str], *, protocol: str
) -> tuple[str, str, str]:
    message = _extract_error_message(body, secrets)
    text = (message + " " + body).lower()
    if 300 <= status < 400:
        return (
            "redirect",
            "LLM_BASE_URL 返回了重定向（HTTP " + str(status) + "），本检测不跟随重定向。",
            "把服务商文档中的最终 API 地址（通常含 /v1 路径）直接填入 LLM_BASE_URL；"
            "本检测不跟随重定向，避免凭据被转发到其他主机。",
        )
    if status in (401, 403):
        return (
            "unauthorized",
            "模型服务拒绝凭据（HTTP " + str(status) + "）。" + ((" " + message) if message else ""),
            "检查 LLM_API_KEY 是否有效、是否与 LLM_BASE_URL 属于同一服务商；"
            "Key 可能已过期或被禁用。重新运行 lfl init 可安全替换配置。",
        )
    if (
        status == 404
        or "model_not_found" in text
        or "model not found" in text
        or "does not exist" in text
        or "invalid model" in text
        or "unknown model" in text
    ):
        return (
            "model_not_found",
            "模型不可用（HTTP " + str(status) + "）。" + ((" " + message) if message else ""),
            "检查 LLM_MODEL 是否为服务商真实模型名；确认 LLM_BASE_URL 路径正确"
            "（OpenAI 兼容接口通常以 /v1 结尾）。DeepSeek 常用 deepseek-flash / deepseek-reasoner，"
            "GLM 常用 glm-4.5 / glm-4.6，以服务商控制台为准。",
        )
    if status == 429 or "rate limit" in text or "too many requests" in text:
        # Quota/balance wording only; a bare "rate limit exceeded" stays a limit.
        quota = any(k in text for k in ("quota", "balance", "insufficient", "credit", "billing"))
        if quota:
            return (
                "quota_exceeded",
                "账户配额或余额不足（HTTP 429）。" + ((" " + message) if message else ""),
                "到服务商控制台确认余额/配额并充值或提额；也可能需要更换 API Key。",
            )
        return (
            "rate_limited",
            "请求被限流（HTTP 429）。" + ((" " + message) if message else ""),
            "稍后重试；检查账户并发/速率限制，或降低并发后再启动。",
        )
    if status == 400:
        return (
            "bad_request",
            "模型服务拒绝了请求参数（HTTP 400）。" + ((" " + message) if message else ""),
            "确认 LLM_BASE_URL 指向 OpenAI 兼容 API（通常以 /v1 结尾）且 LLM_MODEL 名称正确；"
            "如果使用 Anthropic/Google 协议，请设置 LLM_WIRE_PROTOCOL 为 anthropic/google。",
        )
    if 500 <= status < 600:
        return (
            "server_error",
            "模型服务暂时不可用（HTTP " + str(status) + "）。" + ((" " + message) if message else ""),
            "这是服务端错误，稍后重试；持续出现时查看服务商状态页或联系服务商。",
        )
    return (
        "http_error",
        "模型服务返回 HTTP " + str(status) + "。" + ((" " + message) if message else ""),
        "核对 LLM_BASE_URL 是否为 API 端点（不是网页地址），并查看服务商错误说明。",
    )


def check_model_config(
    settings: Mapping[str, Any] | Any,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run exactly one live request and return a classified, value-free result.

    ``settings`` may be a Settings object or a mapping with ``llm_api_key``,
    ``llm_base_url``, ``llm_model`` and optional ``llm_wire_protocol``.
    """

    def get(name: str, default: str = "") -> str:
        if isinstance(settings, Mapping):
            value = settings.get(name, default)
        else:
            value = getattr(settings, name, default)
        return _text(value) or default

    api_key = get("llm_api_key")
    base_url = get("llm_base_url")
    model = get("llm_model")
    protocol = get("llm_wire_protocol", "openai")
    secrets = [api_key]
    try:
        password = urllib.parse.urlsplit(base_url).password
        if password:
            secrets.append(password)
    except ValueError:
        pass
    started = time.monotonic()

    def result(status: str, message: str, action: str, *, http_status: int | None = None,
               body: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "ok": status == "ok",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "message": _redact(message, secrets)[:_MAX_MESSAGE_CHARS],
            "action": _redact(action, secrets),
        }
        # No config values here on purpose: no model name, no endpoint host.
        # The interactive init prints its own local hint; reports stay value-free.
        if http_status is not None:
            payload["http_status"] = http_status
        if body:
            payload["detail"] = _extract_error_message(body, secrets)
        return payload

    if not api_key or not base_url:
        missing = [name for name, value in (("LLM_API_KEY", api_key), ("LLM_BASE_URL", base_url)) if not value]
        return result(
            "not_configured",
            "缺少模型配置：" + ", ".join(missing) + "。",
            "运行 lfl init 创建配置，或设置 " + ", ".join(missing) + "（环境变量/配置文件）。",
        )
    if not model:
        return result(
            "not_configured",
            "缺少 LLM_MODEL。",
            "设置 LLM_MODEL（DeepSeek 可用 deepseek-flash），或移除该键以使用内置默认值。",
        )

    url, headers, payload = _endpoint(base_url, protocol, model)
    headers.update(_auth_headers(protocol, api_key))
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with _open(request, timeout=max(1.0, float(timeout_s))) as response:
            raw = response.read(_MAX_BODY_CHARS)
            body = raw.decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(_MAX_BODY_CHARS).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - error body is best effort only
            body = ""
        status_id, message, action = _http_status(int(exc.code), body, secrets, protocol=protocol)
        return result(status_id, message, action, http_status=int(exc.code), body=body)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        status_id, message, action = _network_status(exc)
        return result(status_id, message, action)
    except Exception as exc:  # noqa: BLE001 - classify unknown transport failures honestly
        return result(
            "network_error",
            "模型检测请求失败：" + type(exc).__name__ + "。",
            "检查 LLM_BASE_URL 与网络；若持续失败，请提供该错误类型给维护者。",
        )

    if status_code != 200:
        status_id, message, action = _http_status(status_code, body, secrets, protocol=protocol)
        return result(status_id, message, action, http_status=status_code, body=body)
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return result(
            "invalid_response",
            "模型返回了非 JSON 响应，可能命中了网页或网关页面。",
            "确认 LLM_BASE_URL 是 API 端点而不是网页地址；OpenAI 兼容接口通常以 /v1 结尾。",
            http_status=status_code,
            body=body,
        )
    if not isinstance(parsed, dict):
        return result(
            "invalid_response",
            "模型返回结构不符合预期。",
            "确认 LLM_BASE_URL 与服务协议（LLM_WIRE_PROTOCOL）匹配。",
            http_status=status_code,
            body=body,
        )
    return result("ok", "模型可用：一次最小请求成功。", "", http_status=status_code)
