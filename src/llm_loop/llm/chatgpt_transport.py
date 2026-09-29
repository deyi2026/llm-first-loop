"""Browser transport for :class:`llm_loop.llm.chatgpt_web.ChatGPTWebModelClient`.

The transport owns browser binding/protocol I/O only.  It never executes an
LFL tool and never decides whether the task is complete; both remain LoopEngine
responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from llm_loop.llm.chatgpt_protocol import (
    CHATGPT_WEB_PROVIDER_ID,
    MODEL_PROTOCOL,
    ChatGPTModelProtocolError,
)
from llm_loop.llm.errors import LLMRequestTooLargeError

from .chatgpt_page import ChatGPTPageAdapter, PageBinding, PageContractError

logger = logging.getLogger(__name__)

_REQUEST_PREAMBLE = (
    "[lfl-model/request]\n"
    "This is one model-provider request from LFL LoopEngine, not an ordinary ChatGPT "
    "conversation. The JSON snapshot below is authoritative for this model decision. "
    "Treat request.messages as the actual LFL conversation and preserve role semantics: "
    "messages with role=system are LFL system instructions for this delegated model "
    "decision and must be followed subject only to higher-priority platform safety. "
    "The snapshot has already been composed by LFL context management; it can contain "
    "LFL-compacted history, working-state/working-set facts, and retrieved "
    "Rule/Method/Experience/Memory/Docs/Skill or tool-schema results. Treat only the "
    "current snapshot as task context; do not use earlier messages from the outer "
    "ChatGPT conversation as supplemental task memory. If relevant LFL context is absent, "
    "use the discovery/hydration tools actually present in request.tools rather than "
    "guessing or relying on outer ChatGPT memory. "
    "Do not substitute facts about the outer ChatGPT web session for LFL runtime facts. "
    "request.tools are LFL tools: when the LFL messages require current evidence about "
    "the LFL model/runtime/workspace/config/files/external state, request the appropriate "
    "LFL tool instead of answering from your own identity, memory, or web-app state. "
    "Do not execute any tool yourself and do not use ChatGPT native tools. "
    "Return exactly one fenced lfl-model-response block. "
    "Its JSON object must have exactly protocol, request_id, content, tool_calls, "
    "finish_reason. tool_calls items must have exactly id, name, arguments. "
    "Use finish_reason=tool_calls when requesting LFL tools; use stop with non-empty "
    "content when giving the model answer. Echo protocol/request_id exactly.\n\n"
    "```lfl-model-request\n"
)


def _canonical_nested_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_nested_json(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonical_nested_json(item) for item in value]
    return value


class ChatGPTWebPageTransport:
    RESPONSE_FENCE = "lfl-model-response"

    def __init__(
        self,
        adapter: ChatGPTPageAdapter,
        *,
        binding: PageBinding | None = None,
        turn_timeout_s: float = 90.0,
        send_timeout_s: float = 30.0,
        poll_ms: int = 100,
        stability_polls: int = 2,
        max_request_chars: int = 150_000,
    ) -> None:
        self.adapter = adapter
        self.binding = binding or adapter.observe_identity()
        self.turn_timeout_s = float(turn_timeout_s)
        self.send_timeout_s = float(send_timeout_s)
        self.poll_ms = int(poll_ms)
        self.stability_polls = int(stability_polls)
        self.max_request_chars = int(max_request_chars)
        self.last_prefix_diagnostics: dict[str, Any] = {}

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if request.get("protocol") != MODEL_PROTOCOL:
            raise ChatGPTModelProtocolError("transport received wrong model protocol")
        self.adapter.require_binding(self.binding)
        before = self.adapter.observe_generation()
        self.last_prefix_diagnostics = self._prefix_diagnostics(request)
        logger.info(
            "chatgpt-web cache_prefix stable_sha256=%s stable_chars=%s payload_chars=%s",
            self.last_prefix_diagnostics["stable_prefix_sha256"],
            self.last_prefix_diagnostics["stable_prefix_chars"],
            self.last_prefix_diagnostics["request_payload_chars"],
        )
        rendered_request = self._render_request(request)
        if self.max_request_chars > 0 and len(rendered_request) > self.max_request_chars:
            raise LLMRequestTooLargeError(
                "request_too_large: ChatGPT Web rendered request exceeds qualified text "
                f"ingress limit (rendered_chars={len(rendered_request)}, "
                f"max_request_chars={self.max_request_chars})",
                observed_chars=len(rendered_request),
                limit_chars=self.max_request_chars,
                provider=CHATGPT_WEB_PROVIDER_ID,
            )
        request_id = str(request.get("request_id") or "")
        turn_timeout_s = float(timeout_s or self.turn_timeout_s)
        receipt = self.adapter.send_text(
            rendered_request,
            timeout_s=min(turn_timeout_s, self.send_timeout_s),
            confirm_timeout_s=turn_timeout_s,
            poll_ms=self.poll_ms,
            confirm_token=request_id or None,
        )
        if self.binding.conversation_id is None:
            current = self.adapter.observe_identity()
            self.binding = PageBinding(
                profile_label=current.profile_label,
                url=current.url,
                title=current.title,
                project_ref=current.project_ref,
                conversation_id=receipt.conversation_id,
            )
        elif receipt.conversation_id != self.binding.conversation_id:
            raise PageContractError("model transport conversation drift during send")
        state = self.adapter.wait_for_assistant_completion(
            before.assistant_count,
            baseline_assistant_identity=before.latest_assistant_identity,
            expected_user_identity=receipt.user_message_identity,
            expected_user_token=request_id or None,
            timeout_s=turn_timeout_s,
            poll_ms=self.poll_ms,
            stability_polls=self.stability_polls,
        )
        self.adapter.require_binding(self.binding)
        native = self.adapter.observe_native_tool_activity()
        if native.latest_assistant_citation_count:
            raise ChatGPTModelProtocolError(
                "ChatGPT native Web Search detected during LFL model call"
            )
        blocks = self.adapter.observe_latest_code_blocks()
        if len(blocks) != 1 or blocks[0].language != self.RESPONSE_FENCE:
            raise ChatGPTModelProtocolError(
                "ChatGPT model call must return exactly one lfl-model-response fenced block"
            )
        try:
            value = json.loads(blocks[0].text)
        except json.JSONDecodeError as exc:
            raise ChatGPTModelProtocolError(f"invalid lfl-model-response JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ChatGPTModelProtocolError("lfl-model-response body must be object")
        if state.streaming:
            raise ChatGPTModelProtocolError("assistant still streaming after completion")
        return value

    def close(self) -> None:
        return None

    def rebind(self, binding: PageBinding | None = None) -> PageBinding:
        """Re-anchor the transport after the owned tab starts a fresh outer thread."""
        self.binding = binding or self.adapter.observe_identity()
        return self.binding

    @staticmethod
    def _wire_request(request: dict[str, Any]) -> dict[str, Any]:
        # Stable high-volume fields come before dynamic dialogue/request_id so a
        # provider-side prefix cache can reuse them when available. Nested objects
        # are canonicalized independently; top-level order is intentionally fixed.
        return {
            "protocol": request.get("protocol"),
            "model": request.get("model"),
            "tools": _canonical_nested_json(request.get("tools") or []),
            "messages": _canonical_nested_json(request.get("messages") or []),
            "request_id": request.get("request_id"),
        }

    @classmethod
    def _request_payload(cls, request: dict[str, Any]) -> str:
        return json.dumps(
            cls._wire_request(request),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def _stable_prefix(cls, request: dict[str, Any]) -> str:
        head = {
            "protocol": request.get("protocol"),
            "model": request.get("model"),
            "tools": _canonical_nested_json(request.get("tools") or []),
        }
        encoded = json.dumps(head, ensure_ascii=False, separators=(",", ":"))
        return _REQUEST_PREAMBLE + encoded[:-1] + ',"messages":'

    @classmethod
    def _prefix_diagnostics(cls, request: dict[str, Any]) -> dict[str, Any]:
        stable = cls._stable_prefix(request)
        payload = cls._request_payload(request)
        return {
            "stable_prefix_sha256": hashlib.sha256(stable.encode("utf-8")).hexdigest(),
            "stable_prefix_chars": len(stable),
            "request_payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "request_payload_chars": len(payload),
            "authoritative": False,
        }

    @classmethod
    def _render_request(cls, request: dict[str, Any]) -> str:
        return _REQUEST_PREAMBLE + cls._request_payload(request) + "\n```"
