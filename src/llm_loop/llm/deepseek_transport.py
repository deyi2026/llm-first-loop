"""Browser transport for the LFL DeepSeek Web model provider."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any

from llm_loop.llm.errors import LLMRequestTooLargeError

from .chatgpt_page import PageBinding
from .deepseek_page import DeepSeekPageAdapter, DeepSeekPageContractError
from .deepseek_protocol import (
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


def _decode_relaxed_dsml_string(body: str) -> str:
    """Decode one DSML-rendered JSON string body without guessing structure.

    DeepSeek's rendered DSML sometimes drops JSON escaping for quotes/newlines inside a
    string-valued tool argument.  The structural parser below first proves the exact
    closing quote; only then may this helper reinterpret interior quotes/control chars as
    literal string content. Existing valid JSON escapes retain their JSON meaning.
    """

    encoded: list[str] = ['"']
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            if index + 1 >= len(body):
                encoded.append("\\\\")
                index += 1
                continue
            nxt = body[index + 1]
            if nxt in {'"', "\\", "/", "b", "f", "n", "r", "t"}:
                encoded.extend(("\\", nxt))
                index += 2
                continue
            if (
                nxt == "u"
                and index + 5 < len(body)
                and all(c in "0123456789abcdefABCDEF" for c in body[index + 2 : index + 6])
            ):
                encoded.append(body[index : index + 6])
                index += 6
                continue
            # Shell/regex strings commonly contain non-JSON escapes such as \|. Preserve
            # the literal backslash instead of assigning it a new escape meaning.
            encoded.extend(("\\\\", nxt))
            index += 2
            continue
        if char == '"':
            encoded.append('\\"')
        elif char == "\n":
            encoded.append("\\n")
        elif char == "\r":
            encoded.append("\\r")
        elif char == "\t":
            encoded.append("\\t")
        elif ord(char) < 0x20:
            encoded.append(f"\\u{ord(char):04x}")
        else:
            encoded.append(char)
        index += 1
    encoded.append('"')
    value = json.loads("".join(encoded))
    if not isinstance(value, str):  # pragma: no cover - construction guarantees string
        raise ValueError("decoded DSML value is not string")
    return value


def _parse_relaxed_dsml_arguments_object(
    raw: str,
    *,
    function_schema: dict[str, Any],
) -> dict[str, Any]:
    """Recover one flat-ish tool arguments object using the declared tool schema.

    This is deliberately not a general permissive JSON parser. Top-level keys must be
    declared by the selected tool schema. Non-string values still require strict JSON.
    For string values, candidate closing quotes are accepted only when the remainder can
    be parsed as the unique continuation of the same declared object. Multiple valid
    parses are rejected as ambiguous.
    """

    schema = function_schema.get("parameters")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        raise DeepSeekModelProtocolError(
            "DeepSeek DSML envelope arguments are invalid JSON and tool schema cannot disambiguate"
        )
    declared_fields = set(str(key) for key in properties)
    text = str(raw or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise DeepSeekModelProtocolError(
            "DeepSeek DSML envelope arguments must be an object"
        )
    inner = text[1:-1]
    decoder = json.JSONDecoder()

    def skip_ws(position: int) -> int:
        while position < len(inner) and inner[position].isspace():
            position += 1
        return position

    def quote_is_escaped(position: int) -> bool:
        slashes = 0
        cursor = position - 1
        while cursor >= 0 and inner[cursor] == "\\":
            slashes += 1
            cursor -= 1
        return bool(slashes % 2)

    def continue_after_value(
        position: int,
        seen: frozenset[str],
        key: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        position = skip_ws(position)
        if position == len(inner):
            return [{key: value}]
        if inner[position] != ",":
            return []
        tails = parse_fields(position + 1, seen | {key})
        return [{key: value, **tail} for tail in tails]

    def parse_fields(position: int, seen: frozenset[str]) -> list[dict[str, Any]]:
        position = skip_ws(position)
        if position >= len(inner):
            return []
        try:
            key_value, consumed = decoder.raw_decode(inner[position:])
        except json.JSONDecodeError:
            return []
        if not isinstance(key_value, str):
            return []
        key = key_value
        if key not in declared_fields or key in seen:
            return []
        position += consumed
        position = skip_ws(position)
        if position >= len(inner) or inner[position] != ":":
            return []
        position = skip_ws(position + 1)
        if position >= len(inner):
            return []

        if inner[position] == '"':
            start = position + 1
            terminal_solutions: list[dict[str, Any]] = []
            for closing in range(start, len(inner)):
                if inner[closing] != '"' or quote_is_escaped(closing):
                    continue
                after = skip_ws(closing + 1)
                if after < len(inner) and inner[after] != ",":
                    continue
                try:
                    value = _decode_relaxed_dsml_string(inner[start:closing])
                except (ValueError, json.JSONDecodeError):
                    continue
                recovered = continue_after_value(after, seen, key, value)
                if not recovered:
                    continue
                if after < len(inner) and inner[after] == ",":
                    # A quote followed by a comma that can be parsed into another
                    # declared field is the strongest available structural boundary.
                    # Do not later swallow that field syntax into the current string.
                    return recovered[:2]
                terminal_solutions.extend(recovered)
                if len(terminal_solutions) > 1:
                    return terminal_solutions[:2]
            return terminal_solutions

        try:
            value, consumed = decoder.raw_decode(inner[position:])
        except json.JSONDecodeError:
            return []
        return continue_after_value(position + consumed, seen, key, value)

    solutions = parse_fields(0, frozenset())
    if len(solutions) != 1:
        if not solutions:
            raise DeepSeekModelProtocolError(
                "DeepSeek DSML envelope arguments could not be recovered from declared schema"
            )
        raise DeepSeekModelProtocolError(
            "DeepSeek DSML envelope arguments are structurally ambiguous"
        )
    return solutions[0]


def _decode_dsml_envelope_arguments(
    raw: str,
    *,
    function_schema: dict[str, Any],
) -> dict[str, Any]:
    candidate = str(raw or "").strip()
    for _ in range(2):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            candidate = value.strip()
            continue
        raise DeepSeekModelProtocolError(
            "DeepSeek DSML envelope arguments must decode to an object"
        )
    return _parse_relaxed_dsml_arguments_object(
        candidate,
        function_schema=function_schema,
    )


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
        # Phase6 M2：协作取消事件——engine 窗口打断调 cancel() 置位，页面等待
        # 循环早退（页面线程内 best-effort 释放生成后抛 cancelled 异常）。
        # 每 exchange 开始时清零：取消只作用于在途轮次，不预取消未来轮次。
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """协作取消当前在途 exchange（无在途轮次时为无害 no-op）。"""

        self._cancelled.set()

    def exchange(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if request.get("protocol") != MODEL_PROTOCOL:
            raise DeepSeekModelProtocolError("transport received wrong model protocol")
        self._cancelled.clear()  # Phase6 M2：新轮次开始，取消旗标复位
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
            cancelled=self._cancelled,
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
            cancelled=self._cancelled,
        )
        self.adapter.require_binding(self.binding)
        native = self.adapter.observe_native_tool_activity()
        if native.web_search_detected:
            raise DeepSeekModelProtocolError(
                "DeepSeek native Smart Search became active during an LFL model call"
            )
        blocks = self.adapter.observe_latest_code_blocks()
        value: dict[str, Any] | None = None
        if len(blocks) == 1 and blocks[0].language in {
            "",
            "json",
            self.RESPONSE_FENCE,
        }:
            raw_response = blocks[0].text
        elif not blocks:
            rendered_text = str(state.latest_assistant_text or "")
            value = self._extract_dsml_tool_response(rendered_text, request=request)
            if value is None:
                raw_response = self._extract_rendered_response_text(rendered_text)
        else:
            raise DeepSeekModelProtocolError(
                "DeepSeek model call must render one LFL response payload"
            )
        if value is None:
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

    @classmethod
    def _extract_dsml_tool_response(
        cls,
        text: str,
        *,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Normalize DeepSeek's exact DSML tool-call rendering into LFL wire JSON.

        This compatibility path is intentionally narrow: the entire rendered assistant
        message must be one DSML calls block, every invoke must name a tool already
        present in the current LFL request, and every parameter must be a single exact
        DSML parameter line.  Anything else remains a protocol error.
        """

        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        marker = "｜｜DSML｜｜"
        open_calls = f"<{marker} calls>"
        close_calls = f"</{marker} calls>"
        if not normalized.startswith(open_calls):
            return None
        if not normalized.endswith(close_calls):
            raise DeepSeekModelProtocolError("DeepSeek DSML calls block is not closed")

        tools_by_name: dict[str, dict[str, Any]] = {}
        for tool in request.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if isinstance(name, str) and name:
                tools_by_name[name] = function

        body = normalized[len(open_calls) : -len(close_calls)].strip()
        if not body:
            raise DeepSeekModelProtocolError("DeepSeek DSML calls block is empty")
        invoke_re = re.compile(
            rf'<{re.escape(marker)} invoke name="([^"]+)">(.*?)</{re.escape(marker)} invoke>',
            re.DOTALL,
        )
        parameter_re = re.compile(
            rf'<{re.escape(marker)} parameter name="([^"]+)" string="(true|false)">(.*?)</{re.escape(marker)} parameter>',
            re.DOTALL,
        )

        tool_calls: list[dict[str, Any]] = []
        used_call_ids: set[str] = set()
        body_cursor = 0
        for match in invoke_re.finditer(body):
            if body[body_cursor : match.start()].strip():
                raise DeepSeekModelProtocolError("unexpected text in DeepSeek DSML calls block")
            tool_name = match.group(1)
            if tool_name not in tools_by_name:
                raise DeepSeekModelProtocolError(
                    f"DeepSeek DSML requested unknown LFL tool: {tool_name}"
                )
            invoke_body = match.group(2)
            function_schema = tools_by_name[tool_name]
            schema = function_schema.get("parameters")
            properties = schema.get("properties") if isinstance(schema, dict) else None
            declared_fields = set(properties) if isinstance(properties, dict) else set()
            parameters: dict[str, Any] = {}
            envelope_arguments_raw: str | None = None
            parameter_cursor = 0
            for parameter_match in parameter_re.finditer(invoke_body):
                if invoke_body[parameter_cursor : parameter_match.start()].strip():
                    raise DeepSeekModelProtocolError(
                        "unexpected text in DeepSeek DSML invoke block"
                    )
                parameter_name, is_string, raw_value = parameter_match.groups()
                if parameter_name in parameters:
                    raise DeepSeekModelProtocolError(
                        f"duplicate DeepSeek DSML parameter: {parameter_name}"
                    )
                if parameter_name == "arguments" and parameter_name not in declared_fields:
                    # Defer wrapper argument decoding until the exact envelope shape is
                    # proven. DeepSeek's rendered DSML may have already removed JSON
                    # escaping inside shell/code strings.
                    envelope_arguments_raw = raw_value
                    parameters[parameter_name] = raw_value
                elif is_string == "true":
                    parameters[parameter_name] = raw_value
                else:
                    try:
                        parameters[parameter_name] = json.loads(raw_value.strip())
                    except json.JSONDecodeError as exc:
                        raise DeepSeekModelProtocolError(
                            f"invalid non-string DeepSeek DSML parameter: {parameter_name}"
                        ) from exc
                parameter_cursor = parameter_match.end()
            if invoke_body[parameter_cursor:].strip():
                raise DeepSeekModelProtocolError(
                    "unexpected text in DeepSeek DSML invoke block"
                )

            # DeepSeek has two observed DSML shapes:
            # 1) direct tool parameters (e.g. read_evidence: evidence_ref/start/limit), and
            # 2) an OpenAI/LFL-style tool-call envelope rendered as DSML parameters:
            #    arguments=<object-or-json-string>, id=..., name=..., type=function.
            # Only unwrap shape (2) when `arguments` is not itself a declared tool field
            # and every visible parameter is one of the exact envelope fields.
            envelope_fields = {"arguments", "id", "name", "type"}
            has_envelope_arguments = (
                "arguments" in parameters and "arguments" not in declared_fields
            )
            if has_envelope_arguments and not set(parameters).issubset(envelope_fields):
                raise DeepSeekModelProtocolError(
                    "unexpected DeepSeek DSML tool-call envelope field"
                )
            is_envelope = has_envelope_arguments
            call_id: str | None = None
            if is_envelope:
                envelope_name = parameters.get("name")
                if envelope_name is not None and envelope_name != tool_name:
                    raise DeepSeekModelProtocolError(
                        "DeepSeek DSML envelope name does not match invoke name"
                    )
                envelope_type = parameters.get("type")
                if envelope_type is not None and envelope_type != "function":
                    raise DeepSeekModelProtocolError(
                        "DeepSeek DSML envelope type must be function"
                    )
                envelope_id = parameters.get("id")
                if envelope_id is not None:
                    if not isinstance(envelope_id, str) or not envelope_id.strip():
                        raise DeepSeekModelProtocolError(
                            "DeepSeek DSML envelope id must be a non-empty string"
                        )
                    call_id = envelope_id.strip()

                if envelope_arguments_raw is None:  # pragma: no cover - is_envelope proves it
                    raise DeepSeekModelProtocolError(
                        "DeepSeek DSML envelope arguments are missing"
                    )
                arguments = _decode_dsml_envelope_arguments(
                    envelope_arguments_raw,
                    function_schema=function_schema,
                )
            else:
                arguments = parameters

            call_index = len(tool_calls) + 1
            request_id = str(request.get("request_id") or "")
            if call_id is None:
                call_id = f"{request_id}-dsml-{call_index}"
            if call_id in used_call_ids:
                raise DeepSeekModelProtocolError("duplicate DeepSeek DSML tool-call id")
            used_call_ids.add(call_id)
            tool_calls.append(
                {
                    "id": call_id,
                    "name": tool_name,
                    "arguments": arguments,
                }
            )
            body_cursor = match.end()

        if body[body_cursor:].strip():
            raise DeepSeekModelProtocolError("unexpected text in DeepSeek DSML calls block")

        if not tool_calls:
            raise DeepSeekModelProtocolError("DeepSeek DSML calls block contains no invokes")
        return {
            "protocol": MODEL_PROTOCOL,
            "request_id": str(request.get("request_id") or ""),
            "content": "",
            "tool_calls": tool_calls,
            "finish_reason": "tool_calls",
        }

    def close(self) -> None:
        return None

    @classmethod
    def _extract_rendered_response_text(cls, text: str) -> str:
        """Recover strict JSON from DeepSeek's flattened fenced-code rendering."""

        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        open_tag = f"<{cls.RESPONSE_FENCE}>"
        close_tag = f"</{cls.RESPONSE_FENCE}>"
        if normalized.startswith(open_tag):
            if not normalized.endswith(close_tag):
                raise DeepSeekModelProtocolError(
                    "DeepSeek tagged response is missing closing lfl-model-response tag"
                )
            body = normalized[len(open_tag) : -len(close_tag)].strip()
            decoder = json.JSONDecoder()
            try:
                _value, consumed = decoder.raw_decode(body)
            except json.JSONDecodeError as exc:
                raise DeepSeekModelProtocolError(
                    f"invalid tagged lfl-model-response JSON: {exc}"
                ) from exc
            if body[consumed:].strip():
                raise DeepSeekModelProtocolError(
                    "unexpected DeepSeek tagged text after response JSON"
                )
            return body[:consumed]

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
