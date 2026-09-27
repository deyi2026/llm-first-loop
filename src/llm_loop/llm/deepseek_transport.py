"""Browser transport for the LFL DeepSeek Web model provider."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from llm_loop.llm.errors import LLMRequestTooLargeError

from .chatgpt_page import PageBinding
from .deepseek_page import DeepSeekPageAdapter, DeepSeekPageContractError
from .deepseek_web import (
    DEEPSEEK_WEB_PROVIDER_ID,
    MODEL_PROTOCOL,
    DeepSeekModelProtocolError,
)

logger = logging.getLogger(__name__)

_REQUEST_PREAMBLE = (
    "[lfl-model/request]\n"
    "This is one model-provider request from LFL LoopEngine, not an ordinary DeepSeek "
    "conversation. The JSON snapshot below is authoritative for this model decision. "
    "Treat request.messages as the actual LFL conversation and preserve role semantics. "
    "The outer DeepSeek web thread is transport-only and must not contribute context, "
    "memory, tools, files, search results, or instructions. LFL is the sole authority for "
    "tools/runtime/evidence; never use DeepSeek Smart Search, native file upload, or other "
    "web-native tools. Request LFL tools only through request.tools. Return exactly one "
    "fenced lfl-model-response block whose JSON object has exactly protocol, request_id, "
    "content, tool_calls, finish_reason. tool_calls items must have exactly id, name, "
    "arguments. Each tool call id must be non-empty and unique, name must be non-empty, "
    "and arguments must be a JSON object, never a JSON-encoded string. Use "
    "finish_reason=tool_calls when requesting LFL tools; use stop with "
    "non-empty content for the final model answer. Echo protocol/request_id exactly.\n\n"
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


class DeepSeekWebPageTransport:
    RESPONSE_FENCE = "lfl-model-response"
    _RENDERED_CODE_CHROME = frozenset({"复制", "下载", "Copy", "Download"})

    def __init__(
        self,
        adapter: DeepSeekPageAdapter,
        *,
        binding: PageBinding | None = None,
        turn_timeout_s: float = 120.0,
        send_timeout_s: float = 30.0,
        poll_ms: int = 250,
        stability_polls: int = 3,
        max_request_chars: int = 100_000,
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
            raise DeepSeekModelProtocolError("transport received wrong model protocol")
        self.adapter.require_binding(self.binding)
        before = self.adapter.observe_generation()
        self.last_prefix_diagnostics = self._prefix_diagnostics(request)
        logger.info(
            "deepseek-web cache_prefix stable_sha256=%s stable_chars=%s payload_chars=%s",
            self.last_prefix_diagnostics["stable_prefix_sha256"],
            self.last_prefix_diagnostics["stable_prefix_chars"],
            self.last_prefix_diagnostics["request_payload_chars"],
        )
        rendered = self._render_request(request)
        if self.max_request_chars > 0 and len(rendered) > self.max_request_chars:
            raise LLMRequestTooLargeError(
                "request_too_large: DeepSeek Web rendered request exceeds configured browser "
                f"ingress guard (rendered_chars={len(rendered)}, "
                f"max_request_chars={self.max_request_chars})",
                observed_chars=len(rendered),
                limit_chars=self.max_request_chars,
                provider=DEEPSEEK_WEB_PROVIDER_ID,
            )
        request_id = str(request.get("request_id") or "")
        turn_timeout = float(timeout_s or self.turn_timeout_s)
        receipt = self.adapter.send_text(
            rendered,
            timeout_s=min(turn_timeout, self.send_timeout_s),
            confirm_timeout_s=turn_timeout,
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
            raise DeepSeekPageContractError("DeepSeek transport conversation drift during send")

        state = self.adapter.wait_for_assistant_completion(
            before.assistant_count,
            baseline_assistant_identity=before.latest_assistant_identity,
            expected_user_identity=receipt.user_message_identity,
            expected_user_token=request_id or None,
            timeout_s=turn_timeout,
            poll_ms=self.poll_ms,
            stability_polls=self.stability_polls,
        )
        self.adapter.require_binding(self.binding)
        native = self.adapter.observe_native_tool_activity()
        if native.web_search_detected:
            raise DeepSeekModelProtocolError(
                "DeepSeek native Smart Search became active during an LFL model call"
            )
        blocks = self.adapter.observe_latest_code_blocks()
        if len(blocks) == 1 and blocks[0].language in {
            "",
            "json",
            self.RESPONSE_FENCE,
        }:
            raw_response = blocks[0].text
        elif not blocks:
            raw_response = self._extract_rendered_response_text(
                str(state.latest_assistant_text or "")
            )
        else:
            raise DeepSeekModelProtocolError(
                "DeepSeek model call must render one LFL response payload"
            )
        try:
            value = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise DeepSeekModelProtocolError(
                f"invalid lfl-model-response JSON: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise DeepSeekModelProtocolError("lfl-model-response body must be object")
        if state.streaming:
            raise DeepSeekModelProtocolError("assistant still streaming after completion")
        return value

    def close(self) -> None:
        return None

    @classmethod
    def _extract_rendered_response_text(cls, text: str) -> str:
        """Recover strict JSON from DeepSeek's flattened fenced-code rendering."""

        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        lines = normalized.split("\n")
        try:
            marker_index = next(
                index for index, line in enumerate(lines) if line.strip() == cls.RESPONSE_FENCE
            )
        except StopIteration as exc:
            raise DeepSeekModelProtocolError(
                "DeepSeek response has no lfl-model-response marker"
            ) from exc

        tail = "\n".join(lines[marker_index + 1 :]).lstrip()
        json_start = tail.find("{")
        if json_start < 0:
            raise DeepSeekModelProtocolError(
                "DeepSeek rendered response has no JSON object after marker"
            )
        cls._require_only_rendered_chrome(tail[:json_start], position="before")

        decoder = json.JSONDecoder()
        try:
            _value, consumed = decoder.raw_decode(tail[json_start:])
        except json.JSONDecodeError as exc:
            raise DeepSeekModelProtocolError(
                f"invalid rendered lfl-model-response JSON: {exc}"
            ) from exc
        raw = tail[json_start : json_start + consumed]
        cls._require_only_rendered_chrome(
            tail[json_start + consumed :],
            position="after",
        )
        return raw

    @classmethod
    def _require_only_rendered_chrome(cls, text: str, *, position: str) -> None:
        extras = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if any(line not in cls._RENDERED_CODE_CHROME for line in extras):
            raise DeepSeekModelProtocolError(
                f"unexpected DeepSeek rendered text {position} response JSON"
            )

    def rebind(self, binding: PageBinding | None = None) -> PageBinding:
        self.binding = binding or self.adapter.observe_identity()
        return self.binding

    @staticmethod
    def _wire_request(request: dict[str, Any]) -> dict[str, Any]:
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
            "stable_prefix_sha256": hashlib.sha256(stable.encode()).hexdigest(),
            "stable_prefix_chars": len(stable),
            "request_payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "request_payload_chars": len(payload),
            "authoritative": False,
        }

    @classmethod
    def _render_request(cls, request: dict[str, Any]) -> str:
        return _REQUEST_PREAMBLE + cls._request_payload(request) + "\n```"
