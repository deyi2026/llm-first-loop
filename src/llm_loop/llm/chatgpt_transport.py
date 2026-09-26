"""Browser transport for :class:`llm_loop.llm.chatgpt_web.ChatGPTWebModelClient`.

The transport owns browser binding/protocol I/O only.  It never executes an
LFL tool and never decides whether the task is complete; both remain LoopEngine
responsibilities.
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.llm.chatgpt_web import MODEL_PROTOCOL, ChatGPTModelProtocolError

from .chatgpt_page import ChatGPTPageAdapter, PageBinding, PageContractError


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
    ) -> None:
        self.adapter = adapter
        self.binding = binding or adapter.observe_identity()
        self.turn_timeout_s = float(turn_timeout_s)
        self.send_timeout_s = float(send_timeout_s)
        self.poll_ms = int(poll_ms)
        self.stability_polls = int(stability_polls)

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
        rendered_request = self._render_request(request)
        request_id = str(request.get("request_id") or "")
        receipt = self.adapter.send_text(
            rendered_request,
            timeout_s=min(float(timeout_s or self.turn_timeout_s), self.send_timeout_s),
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
            timeout_s=float(timeout_s or self.turn_timeout_s),
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

    @staticmethod
    def _render_request(request: dict[str, Any]) -> str:
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        return (
            "[lfl-model/request]\n"
            "This is one model-provider request from LFL LoopEngine, not an ordinary ChatGPT "
            "conversation. The JSON snapshot below is authoritative for this model decision. "
            "Treat request.messages as the actual LFL conversation and preserve role semantics: "
            "messages with role=system are LFL system instructions for this delegated model "
            "decision and must be followed subject only to higher-priority platform safety. "
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
            f"{payload}\n"
            "```"
        )
