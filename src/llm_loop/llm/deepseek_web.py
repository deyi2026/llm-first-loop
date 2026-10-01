"""DeepSeek Web as an LFL model provider, never as a second agent runtime."""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any, Protocol, cast

from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_reasoning_effort
from llm_loop.llm.client import LLMResponse

# Leaf-module re-export (R9-P2-06a): these three symbols moved to
# ``deepseek_protocol`` so the transport can consume them without a module-scope
# cycle. Re-exported here so existing importers keep working unchanged.
from llm_loop.llm.deepseek_protocol import (  # noqa: F401  (re-export)
    DEEPSEEK_WEB_PROVIDER_ID,
    MODEL_PROTOCOL,
    DeepSeekModelProtocolError,
)

DEEPSEEK_WEB_MODEL_ID = "web-deepseek"
DEEPSEEK_WEB_MODEL_REF = f"{DEEPSEEK_WEB_PROVIDER_ID}/{DEEPSEEK_WEB_MODEL_ID}"
DEEPSEEK_WEB_DISPLAY_NAME = "DeepSeek 网页版"


class DeepSeekModelTransport(Protocol):
    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]: ...


class DeepSeekWebModelClient:
    provider = DEEPSEEK_WEB_PROVIDER_ID
    model = DEEPSEEK_WEB_MODEL_ID
    wire_protocol = MODEL_PROTOCOL
    max_tokens = 0
    thinking_supported = False
    reasoning_capable = True
    reasoning_control = "provider_owned"
    reasoning_efforts = ("instant", "high")

    def __init__(
        self,
        transport: DeepSeekModelTransport,
        *,
        model_label: str = DEEPSEEK_WEB_MODEL_ID,
        reasoning_effort: str = "high",
        max_request_chars: int = 100_000,
        transport_observer: Any | None = None,
    ) -> None:
        self.transport = transport
        self.transport_observer = transport_observer
        self.model = model_label
        self.reasoning_effort = (
            reasoning_effort if reasoning_effort in self.reasoning_efforts else "high"
        )
        self.max_request_chars = max(0, int(max_request_chars or 0))
        self.request_soft_limit_chars = (
            int(self.max_request_chars * 0.90) if self.max_request_chars > 0 else 0
        )
        self.calls: list[dict[str, Any]] = []
        self._request_seq = itertools.count(1)
        self._guard = threading.RLock()

    def _transport_attempt_scope(self, *, model_id: str) -> AbstractContextManager[Any]:
        """RG-3C shadow settlement scope around the physical browser exchange (fail-open)."""
        observer: Any = self.transport_observer
        attempt: Any = getattr(observer, "transport_attempt", None) if observer is not None else None
        if not callable(attempt):
            return nullcontext()
        try:
            return cast(
                "AbstractContextManager[Any]",
                attempt(provider_id=self.provider, model_id=model_id, transport_retry_index=0),
            )
        except Exception:
            return nullcontext()

    def request_envelope_preflight(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> dict[str, int | bool]:
        from llm_loop.llm.deepseek_transport import DeepSeekWebPageTransport

        request = {
            "protocol": MODEL_PROTOCOL,
            "request_id": "lfl-model-0000",
            "model": model or self.model,
            "messages": messages,
            "tools": tools,
        }
        observed = len(DeepSeekWebPageTransport._render_request(request))
        hard = self.max_request_chars
        soft = self.request_soft_limit_chars
        return {
            "observed_chars": observed,
            "soft_limit_chars": soft,
            "hard_limit_chars": hard,
            "soft_pressure": bool(soft > 0 and observed > soft),
            "hard_overflow": bool(hard > 0 and observed > hard),
        }

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        with self._guard:
            request_id = f"lfl-model-{next(self._request_seq):04d}"
            requested = str(current_reasoning_effort.get() or "").strip().lower()
            if requested not in self.reasoning_efforts:
                requested = ""
            request = {
                "protocol": MODEL_PROTOCOL,
                "request_id": request_id,
                "model": model or self.model,
                "messages": messages,
                "tools": tools,
                # Transport-local only; canonical wire projection omits it.
                "_reasoning_effort": requested or None,
            }
            self.calls.append(request)
            with self._transport_attempt_scope(model_id=str(request.get("model") or self.model)):
                raw = self.transport.exchange(request, timeout_s=timeout_s)
            response = _validate_response(raw, request_id=request_id)
            calls = [
                ToolCall(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    arguments=dict(row["arguments"]),
                )
                for row in response["tool_calls"]
            ]
            return LLMResponse(
                content=response["content"],
                tool_calls=calls,
                provider=self.provider,
                finish_reason=str(response["finish_reason"]),
                reasoning_content=None,
            )

    def close(self) -> None:
        closer = getattr(self.transport, "close", None)
        if callable(closer):
            closer()


class _SurfaceOwnedTransport:
    def __init__(
        self,
        inner: DeepSeekModelTransport,
        *,
        surface: Any,
        adapter: Any,
        reasoning_effort: str = "high",
    ) -> None:
        self.inner = inner
        self.surface = surface
        self.adapter = adapter
        self.reasoning_effort = reasoning_effort
        self._closed = False

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        # Every LFL model decision starts from a fresh outer DeepSeek chat.
        self.surface.reset_to_root()
        self.adapter.require_ready()
        requested = str(
            request.get("_reasoning_effort") or self.reasoning_effort
        ).strip().lower()
        self.adapter.ensure_runtime_controls(requested)
        rebinder = getattr(self.inner, "rebind", None)
        if not callable(rebinder):
            raise RuntimeError("DeepSeek Web transport cannot rebind page identity")
        rebinder()
        response = self.inner.exchange(request, timeout_s=timeout_s)
        self.surface.bind_conversation(self.adapter.observe_identity())
        return response

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            closer = getattr(self.inner, "close", None)
            if callable(closer):
                closer()
        finally:
            self.surface.close()


class _ThreadBoundTransport:
    """Keep Playwright objects on one dedicated OS thread."""

    def __init__(self, builder: Callable[[], DeepSeekModelTransport]) -> None:
        self._builder = builder
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deepseek-web")
        self._inner: DeepSeekModelTransport | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _get_or_build(self) -> DeepSeekModelTransport:
        if self._inner is None:
            self._inner = self._builder()
        return self._inner

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError("DeepSeek Web transport is closed")
            future = self._executor.submit(self._exchange_bound, request, timeout_s)
        return future.result()

    def _exchange_bound(
        self, request: dict[str, Any], timeout_s: float | None
    ) -> dict[str, Any]:
        return self._get_or_build().exchange(request, timeout_s=timeout_s)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            future = self._executor.submit(self._close_bound)
        try:
            future.result()
        finally:
            self._executor.shutdown(wait=True, cancel_futures=False)

    def _close_bound(self) -> None:
        if self._inner is None:
            return
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()


def build_deepseek_web_model_client(
    settings: Any, *, transport_observer: Any | None = None
) -> DeepSeekWebModelClient:
    endpoint = str(getattr(settings, "deepseek_web_cdp_endpoint", "") or "").strip()
    root_url = str(
        getattr(settings, "deepseek_web_root_url", "https://chat.deepseek.com/")
        or "https://chat.deepseek.com/"
    ).strip()
    profile_label = str(
        getattr(settings, "deepseek_web_profile_label", "lfl-web-deepseek")
        or "lfl-web-deepseek"
    ).strip()
    timeout_s = float(getattr(settings, "deepseek_web_turn_timeout_s", 120.0) or 120.0)
    reasoning_effort = str(
        getattr(settings, "deepseek_web_reasoning_effort", "high") or "high"
    ).strip().lower()
    max_request_chars = int(
        getattr(settings, "deepseek_web_max_request_chars", 100_000) or 100_000
    )
    if not endpoint or not root_url:
        raise ValueError(
            "DeepSeek Web 未完整配置：需要 DEEPSEEK_WEB_CDP_ENDPOINT / ROOT_URL"
        )

    lease_root = Path(settings.data_dir) / "deepseek-web-provider"

    def build_surface_transport() -> DeepSeekModelTransport:
        from llm_loop.llm.chatgpt_surface import BrowserSurfaceLeaseStore
        from llm_loop.llm.deepseek_page import DeepSeekPageAdapter
        from llm_loop.llm.deepseek_surface import DeepSeekSurface
        from llm_loop.llm.deepseek_transport import DeepSeekWebPageTransport

        surface = DeepSeekSurface(
            endpoint,
            lease_store=BrowserSurfaceLeaseStore(lease_root),
            root_url=root_url,
            profile_label=profile_label,
        )
        try:
            page = surface.open()
            adapter = DeepSeekPageAdapter(page, profile_label=profile_label)
            adapter.require_ready()
            inner = DeepSeekWebPageTransport(
                adapter,
                turn_timeout_s=timeout_s,
                max_request_chars=max_request_chars,
            )
            return _SurfaceOwnedTransport(
                inner,
                surface=surface,
                adapter=adapter,
                reasoning_effort=reasoning_effort,
            )
        except Exception as exc:
            surface.close()
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"DeepSeek Web 浏览器连接失败: {exc}") from exc

    transport = _ThreadBoundTransport(build_surface_transport)
    return DeepSeekWebModelClient(
        transport,
        model_label=DEEPSEEK_WEB_MODEL_ID,
        reasoning_effort=reasoning_effort,
        max_request_chars=max_request_chars,
        transport_observer=transport_observer,
    )


def _validate_response(value: Any, *, request_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DeepSeekModelProtocolError("model response must be a JSON object")
    allowed = {"protocol", "request_id", "content", "tool_calls", "finish_reason"}
    if set(value) != allowed:
        raise DeepSeekModelProtocolError(
            f"model response keys mismatch: expected={sorted(allowed)} actual={sorted(value)}"
        )
    if value.get("protocol") != MODEL_PROTOCOL:
        raise DeepSeekModelProtocolError(f"wrong protocol: {value.get('protocol')!r}")
    if value.get("request_id") != request_id:
        raise DeepSeekModelProtocolError(
            f"request_id mismatch: expected={request_id!r} actual={value.get('request_id')!r}"
        )
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        raise DeepSeekModelProtocolError("content must be string|null")
    tool_calls = value.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise DeepSeekModelProtocolError("tool_calls must be an array")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in tool_calls:
        if not isinstance(row, Mapping) or set(row) != {"id", "name", "arguments"}:
            raise DeepSeekModelProtocolError("tool_calls item shape is invalid")
        call_id = str(row["id"])
        name = str(row["name"])
        arguments = row["arguments"]
        if isinstance(arguments, str):
            try:
                decoded_arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise DeepSeekModelProtocolError(
                    "tool_calls item arguments string must contain one JSON object"
                ) from exc
            if not isinstance(decoded_arguments, Mapping):
                raise DeepSeekModelProtocolError(
                    "tool_calls item arguments string must decode to object"
                )
            arguments = decoded_arguments
        if not call_id or call_id in seen or not name or not isinstance(arguments, Mapping):
            raise DeepSeekModelProtocolError("tool_calls item identity/arguments invalid")
        seen.add(call_id)
        normalized.append({"id": call_id, "name": name, "arguments": dict(arguments)})
    finish_reason = value.get("finish_reason")
    if finish_reason not in {"stop", "tool_calls"}:
        raise DeepSeekModelProtocolError("finish_reason must be stop|tool_calls")
    if normalized and finish_reason != "tool_calls":
        raise DeepSeekModelProtocolError("tool_calls require finish_reason=tool_calls")
    if not normalized and finish_reason != "stop":
        raise DeepSeekModelProtocolError("no tool_calls requires finish_reason=stop")
    if not normalized and not (content or "").strip():
        raise DeepSeekModelProtocolError("stop response requires non-empty content")
    return {
        "protocol": MODEL_PROTOCOL,
        "request_id": request_id,
        "content": content,
        "tool_calls": normalized,
        "finish_reason": finish_reason,
    }
