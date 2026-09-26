"""ChatGPT Web as an LFL model provider.

This module deliberately lives on the LFL model side of the architecture.  It
does not own an agent/tool loop.  One ``chat()`` call corresponds to one model
decision inside :class:`llm_loop.core.loop.LoopEngine`:

``LoopEngine -> ChatGPTWebModelClient -> transport -> ChatGPT Web``

The transport returns a structured provider response which is converted into
the ordinary :class:`LLMResponse` / :class:`ToolCall` objects that LoopEngine
already understands.  Tool execution therefore remains exclusively inside the
LFL ``ToolRegistry`` and its safety/evidence/recovery pipeline.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse

MODEL_PROTOCOL = "lfl-model/0.1"
CHATGPT_WEB_PROVIDER_ID = "chatgpt-web"
CHATGPT_WEB_MODEL_ID = "web-gpt"
CHATGPT_WEB_MODEL_REF = f"{CHATGPT_WEB_PROVIDER_ID}/{CHATGPT_WEB_MODEL_ID}"
CHATGPT_WEB_DISPLAY_NAME = "网页版 GPT"


class ChatGPTModelProtocolError(RuntimeError):
    """The ChatGPT transport returned an invalid provider response."""


class ChatGPTModelTransport(Protocol):
    """One request/response exchange with the external ChatGPT Web surface."""

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]: ...


class ChatGPTWebModelClient:
    """Duck-typed LFL model client backed by ChatGPT Web.

    The class intentionally does **not** expose ``chat_stream`` yet.  LoopEngine
    will use its already-supported synchronous provider path while the browser
    transport itself still performs bounded streaming observation internally.
    """

    provider = CHATGPT_WEB_PROVIDER_ID
    model = CHATGPT_WEB_MODEL_ID
    wire_protocol = "lfl-model/0.1"
    max_tokens = 0
    thinking_supported = False
    reasoning_capable = True
    reasoning_control = "provider_owned"

    def __init__(
        self,
        transport: ChatGPTModelTransport,
        *,
        model_label: str = CHATGPT_WEB_MODEL_ID,
    ) -> None:
        self.transport = transport
        self.model = model_label
        self.calls: list[dict[str, Any]] = []
        self._request_seq = itertools.count(1)
        # One browser conversation is a serial transport.  The ModelClientPool
        # caches one client for this provider, so concurrent Web sessions must
        # not interleave composer/send/observe cycles on the same owned tab.
        self._guard = threading.RLock()

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
            request = {
                "protocol": MODEL_PROTOCOL,
                "request_id": request_id,
                "model": model or self.model,
                "messages": messages,
                "tools": tools,
            }
            self.calls.append(request)
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
    """Own the BrowserSurfaceLease lifecycle behind one model transport."""

    def __init__(self, inner: ChatGPTModelTransport, *, surface: Any, adapter: Any) -> None:
        self.inner = inner
        self.surface = surface
        self.adapter = adapter
        self._closed = False

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        response = self.inner.exchange(request, timeout_s=timeout_s)
        # The first Project-root send creates the concrete conversation id.
        # Persist it into the same logical surface lease so browser/target loss
        # can recover the exact conversation instead of guessing among tabs.
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


def build_chatgpt_web_model_client(settings: Any) -> ChatGPTWebModelClient:
    """Build the configured ChatGPT Web browser model lazily.

    The normal engine starts without touching Chrome.  This factory is invoked
    only after the user/session explicitly routes to ``chatgpt-web/web-gpt``.
    Browser ownership remains below the model client; LFL LoopEngine stays the
    sole tool/rule/execution authority.
    """

    endpoint = str(getattr(settings, "chatgpt_web_cdp_endpoint", "") or "").strip()
    project_url = str(getattr(settings, "chatgpt_web_project_url", "") or "").strip()
    project_ref = str(getattr(settings, "chatgpt_web_project_ref", "") or "").strip()
    project_name = str(getattr(settings, "chatgpt_web_project_name", "") or "").strip()
    profile_label = str(
        getattr(settings, "chatgpt_web_profile_label", "lfl-web-gpt") or "lfl-web-gpt"
    ).strip()
    timeout_s = float(getattr(settings, "chatgpt_web_turn_timeout_s", 120.0) or 120.0)
    if not endpoint or not project_url or not project_ref or not project_name:
        raise ValueError(
            "ChatGPT Web 未完整配置：需要 CHATGPT_WEB_CDP_ENDPOINT / PROJECT_URL / "
            "PROJECT_REF / PROJECT_NAME"
        )

    from llm_loop.llm.chatgpt_page import ChatGPTPageAdapter
    from llm_loop.llm.chatgpt_surface import BrowserSurfaceLeaseStore, ChatGPTSurface
    from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport

    lease_root = Path(settings.data_dir) / "chatgpt-web-provider"
    surface = ChatGPTSurface(
        endpoint,
        lease_store=BrowserSurfaceLeaseStore(lease_root),
        project_url=project_url,
        project_ref=project_ref,
        profile_label=profile_label,
    )
    try:
        page = surface.open()
        if project_ref not in str(getattr(page, "url", "")):
            raise ValueError("owned ChatGPT surface is outside the configured Project")
        adapter = ChatGPTPageAdapter(
            page,
            profile_label=profile_label,
            project_name=project_name,
        )
        inner = ChatGPTWebPageTransport(adapter, turn_timeout_s=timeout_s)
        transport = _SurfaceOwnedTransport(inner, surface=surface, adapter=adapter)
        return ChatGPTWebModelClient(transport, model_label=CHATGPT_WEB_MODEL_ID)
    except Exception as exc:
        surface.close()
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"ChatGPT Web 浏览器连接失败: {exc}") from exc


def _validate_response(value: Any, *, request_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChatGPTModelProtocolError("model response must be a JSON object")
    allowed = {"protocol", "request_id", "content", "tool_calls", "finish_reason"}
    keys = set(value)
    if keys != allowed:
        raise ChatGPTModelProtocolError(
            f"model response keys mismatch: expected={sorted(allowed)} actual={sorted(keys)}"
        )
    if value.get("protocol") != MODEL_PROTOCOL:
        raise ChatGPTModelProtocolError(f"wrong protocol: {value.get('protocol')!r}")
    if value.get("request_id") != request_id:
        raise ChatGPTModelProtocolError(
            f"request_id mismatch: expected={request_id!r} actual={value.get('request_id')!r}"
        )
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        raise ChatGPTModelProtocolError("content must be string|null")
    tool_calls = value.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise ChatGPTModelProtocolError("tool_calls must be an array")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(tool_calls):
        if not isinstance(row, Mapping) or set(row) != {"id", "name", "arguments"}:
            raise ChatGPTModelProtocolError(
                f"tool_calls[{index}] must contain exactly id/name/arguments"
            )
        call_id = str(row.get("id") or "")
        name = str(row.get("name") or "")
        arguments = row.get("arguments")
        if not call_id or call_id in seen:
            raise ChatGPTModelProtocolError(f"tool_calls[{index}] id missing/duplicate")
        if not name:
            raise ChatGPTModelProtocolError(f"tool_calls[{index}] name missing")
        if not isinstance(arguments, Mapping):
            raise ChatGPTModelProtocolError(f"tool_calls[{index}] arguments must be object")
        seen.add(call_id)
        normalized.append({"id": call_id, "name": name, "arguments": dict(arguments)})
    finish_reason = value.get("finish_reason")
    if finish_reason not in {"stop", "tool_calls"}:
        raise ChatGPTModelProtocolError("finish_reason must be stop|tool_calls")
    if normalized and finish_reason != "tool_calls":
        raise ChatGPTModelProtocolError("tool_calls require finish_reason=tool_calls")
    if not normalized and finish_reason != "stop":
        raise ChatGPTModelProtocolError("no tool_calls requires finish_reason=stop")
    if not normalized and not (content or "").strip():
        raise ChatGPTModelProtocolError("stop response requires non-empty content")
    return {
        "protocol": MODEL_PROTOCOL,
        "request_id": request_id,
        "content": content,
        "tool_calls": normalized,
        "finish_reason": finish_reason,
    }
