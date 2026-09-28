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
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_reasoning_effort, current_session_id
from llm_loop.llm.client import LLMResponse

MODEL_PROTOCOL = "lfl-model/0.1"
CHATGPT_WEB_PROVIDER_ID = "chatgpt-web"
CHATGPT_WEB_MODEL_ID = "web-gpt"
CHATGPT_WEB_MODEL_REF = f"{CHATGPT_WEB_PROVIDER_ID}/{CHATGPT_WEB_MODEL_ID}"
CHATGPT_WEB_DISPLAY_NAME = "网页版 GPT"
CHATGPT_WEB_SEGMENT_MAX_REQUESTS = 8
CHATGPT_WEB_SEGMENT_BUDGET_RATIO = 0.75
CHATGPT_WEB_REASONING_READY_TIMEOUT_S = 20.0


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
    reasoning_efforts = ("instant", "medium", "high", "xhigh", "pro")

    def __init__(
        self,
        transport: ChatGPTModelTransport,
        *,
        model_label: str = CHATGPT_WEB_MODEL_ID,
        reasoning_effort: str = "high",
        max_request_chars: int = 150_000,
    ) -> None:
        self.transport = transport
        self.model = model_label
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort in self.reasoning_efforts
            else "high"
        )
        self.max_request_chars = max(0, int(max_request_chars or 0))
        self.request_soft_limit_chars = (
            int(self.max_request_chars * 0.90) if self.max_request_chars > 0 else 0
        )
        self.calls: list[dict[str, Any]] = []
        self._request_seq = itertools.count(1)
        # One browser conversation is a serial transport.  The ModelClientPool
        # caches one client for this provider, so concurrent Web sessions must
        # not interleave composer/send/observe cycles on the same owned tab.
        self._guard = threading.RLock()

    def request_envelope_preflight(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> dict[str, int | bool]:
        """Measure the canonical browser request before BrowserSurface is touched."""

        from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport

        request = {
            "protocol": MODEL_PROTOCOL,
            "request_id": "lfl-model-0000",
            "model": model or self.model,
            "messages": messages,
            "tools": tools,
        }
        observed = len(ChatGPTWebPageTransport._render_request(request))
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
            requested_effort = str(current_reasoning_effort.get() or "").strip().lower()
            if requested_effort not in self.reasoning_efforts:
                requested_effort = ""
            request = {
                "protocol": MODEL_PROTOCOL,
                "request_id": request_id,
                "model": model or self.model,
                "messages": messages,
                "tools": tools,
                # Transport-local control metadata.  ChatGPTWebPageTransport's
                # canonical wire projection intentionally ignores unknown
                # request keys, so this never enters the model-visible LFL
                # protocol payload.
                "_reasoning_effort": requested_effort or None,
                "_lfl_session_id": str(current_session_id.get() or "").strip() or None,
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

    def __init__(
        self,
        inner: ChatGPTModelTransport,
        *,
        surface: Any,
        adapter: Any,
        session_store: Any | None = None,
        project_ref: str = "",
        segment_max_chars: int = 0,
        segment_max_requests: int = CHATGPT_WEB_SEGMENT_MAX_REQUESTS,
        reasoning_effort: str = "high",
    ) -> None:
        self.inner = inner
        self.surface = surface
        self.adapter = adapter
        self.session_store = session_store
        self.project_ref = str(project_ref or "").strip()
        self.segment_max_chars = max(0, int(segment_max_chars or 0))
        self.segment_max_requests = max(1, int(segment_max_requests or 1))
        self.reasoning_effort = reasoning_effort
        self._closed = False

    @staticmethod
    def _request_chars(request: dict[str, Any]) -> int:
        from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport

        return len(ChatGPTWebPageTransport._render_request(request))

    def _prepare_session_binding(
        self,
        request: dict[str, Any],
    ) -> tuple[Any | None, int]:
        session_id = str(request.get("_lfl_session_id") or "").strip()
        if not session_id or self.session_store is None or not self.project_ref:
            # Fail-safe compatibility for out-of-run callers/tests: no attributable
            # LFL session means no reusable outer history.
            self.surface.reset_to_project_root()
            return None, 0

        request_chars = self._request_chars(request)
        binding = self.session_store.get_or_create(
            session_id=session_id,
            project_ref=self.project_ref,
        )
        rollover_reason = ""
        should_roll = binding.segment_request_count >= self.segment_max_requests
        if should_roll:
            rollover_reason = "request_cap"
        if (
            not should_roll
            and self.segment_max_chars > 0
            and binding.segment_request_count > 0
            and binding.segment_request_chars + request_chars > self.segment_max_chars
        ):
            should_roll = True
            rollover_reason = "cumulative_request_chars"

        if should_roll:
            self.surface.reset_to_project_root()
            binding = self.session_store.rollover(
                binding,
                reason=rollover_reason,
            )
        elif binding.conversation_id and binding.conversation_url:
            self.surface.restore_conversation(
                conversation_id=binding.conversation_id,
                conversation_url=binding.conversation_url,
            )
        else:
            self.surface.reset_to_project_root()
        return binding, request_chars

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        # LFL is the sole context owner.  The outer ChatGPT conversation is only
        # a bounded transport segment keyed by the authoritative LFL session.
        # Reuse improves operator manageability; rollover prevents unbounded
        # accumulation of repeated full LFL snapshots in provider-owned history.
        session_binding, request_chars = self._prepare_session_binding(request)
        requested_effort = str(
            request.get("_reasoning_effort") or self.reasoning_effort
        ).strip().lower()
        # Session switches and segment rollovers may navigate from an existing
        # conversation back to the Project root. The route can be stable before
        # the model selector is re-mounted, so use the same bounded readiness
        # scale as surface navigation instead of the adapter's shorter default.
        self.adapter.ensure_reasoning_effort(
            requested_effort,
            timeout_s=CHATGPT_WEB_REASONING_READY_TIMEOUT_S,
        )
        rebinder = getattr(self.inner, "rebind", None)
        if not callable(rebinder):
            raise RuntimeError("ChatGPT Web snapshot transport cannot rebind page identity")
        rebinder()
        response = self.inner.exchange(request, timeout_s=timeout_s)
        # Persist physical route recovery plus the logical LFL-session binding.
        # Neither record is a semantic/history authority.
        lease = self.surface.bind_conversation(self.adapter.observe_identity())
        if session_binding is not None:
            if not lease.conversation_id or not lease.conversation_url:
                raise RuntimeError("ChatGPT Web exchange completed without conversation identity")
            self.session_store.record_exchange(
                session_binding,
                conversation_id=lease.conversation_id,
                conversation_url=lease.conversation_url,
                request_chars=request_chars,
            )
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
    """Keep all synchronous Playwright work on one dedicated OS thread.

    FastAPI may execute consecutive requests for the same cached model client on
    different worker threads. Playwright's sync API is greenlet-backed and its
    objects cannot safely migrate across those threads. This wrapper creates the
    browser surface lazily *inside* one single-thread executor and routes every
    exchange/close through that same executor for the lifetime of the client.
    """

    def __init__(self, builder: Callable[[], ChatGPTModelTransport]) -> None:
        self._builder = builder
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chatgpt-web")
        self._inner: ChatGPTModelTransport | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _get_or_build(self) -> ChatGPTModelTransport:
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
                raise RuntimeError("ChatGPT Web transport is closed")
            future = self._executor.submit(self._exchange_bound, request, timeout_s)
        return future.result()

    def _exchange_bound(
        self,
        request: dict[str, Any],
        timeout_s: float | None,
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
    reasoning_effort = str(
        getattr(settings, "chatgpt_web_reasoning_effort", "high") or "high"
    ).strip().lower()
    max_request_chars = int(
        getattr(settings, "chatgpt_web_max_request_chars", 150_000) or 150_000
    )
    if not endpoint or not project_url or not project_ref or not project_name:
        raise ValueError(
            "ChatGPT Web 未完整配置：需要 CHATGPT_WEB_CDP_ENDPOINT / PROJECT_URL / "
            "PROJECT_REF / PROJECT_NAME"
        )

    lease_root = Path(settings.data_dir) / "chatgpt-web-provider"
    segment_max_chars = max(
        1,
        int(max_request_chars * CHATGPT_WEB_SEGMENT_BUDGET_RATIO),
    )

    def build_surface_transport() -> ChatGPTModelTransport:
        from llm_loop.llm.chatgpt_page import ChatGPTPageAdapter
        from llm_loop.llm.chatgpt_surface import (
            BrowserSurfaceLeaseStore,
            ChatGPTSessionBindingStore,
            ChatGPTSurface,
        )
        from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport

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
            inner = ChatGPTWebPageTransport(
                adapter,
                turn_timeout_s=timeout_s,
                max_request_chars=max_request_chars,
            )
            return _SurfaceOwnedTransport(
                inner,
                surface=surface,
                adapter=adapter,
                session_store=ChatGPTSessionBindingStore(lease_root / "sessions"),
                project_ref=project_ref,
                segment_max_chars=segment_max_chars,
                reasoning_effort=reasoning_effort,
            )
        except Exception as exc:
            surface.close()
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"ChatGPT Web 浏览器连接失败: {exc}") from exc

    transport = _ThreadBoundTransport(build_surface_transport)
    return ChatGPTWebModelClient(
        transport,
        model_label=CHATGPT_WEB_MODEL_ID,
        reasoning_effort=reasoning_effort,
        max_request_chars=max_request_chars,
    )


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
