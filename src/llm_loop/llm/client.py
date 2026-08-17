"""LLM 流式客户端（多协议：OpenAI 兼容 / Anthropic Messages / Google Gemini）.

`wire_protocol`（ModelSpec 元数据，providers.json 模型条目可配）:
- openai（默认，零回归）：POST {base}/chat/completions，SSE choices[].delta
- anthropic：POST {base}/v1/messages，x-api-key + anthropic-version 头，
  SSE content_block_* 事件（text_delta / thinking_delta / input_json_delta / tool_use）
- google：POST {base}/v1beta/models/{model}:streamGenerateContent?alt=sse，
  x-goog-api-key 头，SSE candidates[0].content.parts（text / functionCall）

异常分类/思考分片/工具聚合/用量/截断语义三协议统一（LLMError 体系不变）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from llm_loop.core.message import ToolCall
from llm_loop.llm.errors import (
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)
from llm_loop.llm.schemas import ToolCallDeltaAggregator  # finish() 含 json.loads 归一（约束 C5）


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    provider: str = "openai-compat"
    truncated: bool = False
    reasoning_content: str | None = None  # M20 THK-02/03
    prompt_tokens: int = 0  # M52: 缺失保持 0 = 未提供，不伪造
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0  # M58: provider 前缀缓存命中 token（省钱可观测）


@dataclass
class ToolRoundInfo:
    """单轮工具调用摘要（引擎回执 + 事件日志）."""

    tool_name: str
    round_index: int
    args_summary: str = ""
    tool_call_id: str = ""


@dataclass
class StreamDelta:
    text: str = ""
    reasoning: str | None = None
    tool_round: ToolRoundInfo | None = None


@dataclass
class _StreamAcc:
    """协议无关的流式聚合状态."""

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    truncated: bool = False
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0


def _finish_response(
    acc: _StreamAcc, agg: ToolCallDeltaAggregator, provider: str
) -> LLMResponse:
    raw_calls = agg.finish()
    tool_calls: list[ToolCall] = [
        ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in raw_calls
    ]
    return LLMResponse(
        content="".join(acc.content_parts) or None,
        tool_calls=tool_calls,
        provider=provider,
        truncated=acc.truncated,
        reasoning_content="".join(acc.reasoning_parts) or None,
        prompt_tokens=acc.prompt_tokens,
        completion_tokens=acc.completion_tokens,
        prompt_cache_hit_tokens=acc.prompt_cache_hit_tokens,
    )


@dataclass
class LLMClient:
    """多协议流式客户端（OpenAI 兼容 / Anthropic / Google；wire_protocol 分发）.

    通过 `LLMClient.chat(messages, tools)` 发起请求；
    测试用 FakeLLM 需实现相同接口（Duck typing）。
    """

    api_key: str
    base_url: str
    model: str
    timeout_s: float = 120.0
    max_tokens: int | None = None  # 2026-08-15: 显式输出预算（None=不发字段，模型默认）
    max_retries: int = 0
    wire_protocol: str = "openai"  # P3-5: openai / anthropic / google（ModelSpec 元数据）

    # 兼容构造: settings 装配（保留字段注入）
    provider: str = "openai-compat"
    # M20 THK-01/CFG-03: DeepSeek V4 思考模式（默认开启；非 DeepSeek 不发）
    thinking_mode: bool = True
    reasoning_effort: str = "high"

    # M47（design §5.5）: 思考参数泛化 - 显式传入时以此为准（消除硬编码 deepseek.com）;
    # None 时保持原 _thinking_supported() 行为（向后兼容，零回归）.
    thinking_supported: bool | None = None

    def __post_init__(self) -> None:
        self._client = httpx.Client(timeout=self.timeout_s)

    def _thinking_supported(self) -> bool:
        """思考参数发送判定（M20 CFG-03 + M47 §5.5）.

        - thinking_supported 显式传入（非 None）→ 以传入值为准（注册表元数据驱动）
        - thinking_supported=None → 原行为: provider 为 deepseek 或 base_url 含 deepseek.com
        """
        if self.thinking_supported is not None:
            return self.thinking_supported
        return self.provider == "deepseek" or "deepseek.com" in self.base_url

    def close(self) -> None:
        self._client.close()

    # ── 统一入口（协议分发） ──
    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,  # PARAM-01: 每次调用可覆盖超时（None 用构造值）
        model: str | None = None,  # WEB: 每次调用可覆盖模型（None 用构造值，供 Web 模型切换）
    ) -> Iterator[StreamDelta]:
        """流式请求，逐 content delta yield；generator 结束返回完整 LLMResponse.

        异常按类型抛出 LLMError 子类，由循环如实反馈。
        """
        protocol = self.wire_protocol
        # 注意：Python 3.11+ 裸 `yield from` 会丢弃子生成器 return 值（StopIteration.value=None），
        # 必须显式捕获后 return 才能把终态 LLMResponse 传给消费者（engine 经 StopIteration.value 取终态）。
        if protocol == "anthropic":
            result = yield from self._stream_anthropic(messages, tools, timeout_s=timeout_s, model=model)
        elif protocol == "google":
            result = yield from self._stream_google(messages, tools, timeout_s=timeout_s, model=model)
        else:
            result = yield from self._stream_openai(messages, tools, timeout_s=timeout_s, model=model)
        return result

    # ── OpenAI 兼容（既有行为，零回归） ──
    def _stream_openai(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",  # 约束 C6
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # 2026-08-15: 显式输出预算（None=不发字段，模型默认——思考链模型默认 4096 时
        # 思考占大半、最终分析被截断，用户现场反馈"回答被截断"根因）
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        # M20 THK-01: DeepSeek V4 思考模式显式声明（thinking_mode AND provider 支持才发送）
        # P1-FEISHU: 本地 provider (LM Studio) 不发 OpenAI 的 `thinking` 字段
        if self.thinking_mode and self._thinking_supported() and self.api_key:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.reasoning_effort
        # P1-FEISHU: 本地 provider（api_key 为空）显式关闭 thinking
        if not self.api_key:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        # 本地 provider（api_key 为空）不发 Authorization 头
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    self._check_sse_error(chunk)
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        # M58 修复（审查中危）: 缺失不覆盖——部分 provider 在中间 chunk
                        # 带 usage 但缺字段（或全 0），覆盖式赋值会把已累计值清零。
                        pt = usage.get("prompt_tokens")
                        if pt:
                            acc.prompt_tokens = int(pt)
                        ct = usage.get("completion_tokens")
                        if ct:
                            acc.completion_tokens = int(ct)
                        # M58: 前缀缓存命中（DeepSeek prompt_cache_hit_tokens；Kimi 兜底 cached_tokens）
                        hit = usage.get("prompt_cache_hit_tokens")
                        if hit is None:
                            hit = usage.get("cached_tokens")
                        if hit:
                            acc.prompt_cache_hit_tokens = int(hit)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        acc.content_parts.append(content)
                        yield StreamDelta(text=content)
                    rc = delta.get("reasoning_content")
                    if rc:
                        acc.reasoning_parts.append(rc)
                        yield StreamDelta(text="", reasoning=rc)
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            agg.add_delta(tc)
                    fr = choice.get("finish_reason")
                    if fr:
                        acc.finish_reason = fr
                    if acc.finish_reason == "length":
                        acc.truncated = True
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider)

    # ── Anthropic Messages API（wire_protocol=anthropic，P3-5） ──
    def _stream_anthropic(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        url = f"{self.base_url.rstrip('/')}/v1/messages"
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        msgs = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": self._to_anthropic_messages(msgs),
            "tools": self._to_anthropic_tools(tools) or None,
            "stream": True,
            "max_tokens": self.max_tokens or 4096,
        }
        if system_parts:
            payload["system"] = "\n\n".join(str(p) for p in system_parts)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    evt_type = evt.get("type")
                    if evt_type == "message_start":
                        usage = (evt.get("message") or {}).get("usage") or {}
                        acc.prompt_tokens = int(usage.get("input_tokens") or 0)
                        acc.completion_tokens = int(usage.get("output_tokens") or 0)
                        # M58: Anthropic 缓存命中（cache_read_input_tokens）
                        acc.prompt_cache_hit_tokens = int(usage.get("cache_read_input_tokens") or 0)
                    elif evt_type == "content_block_start":
                        block = evt.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            # 流式语义：start 时 input 恒为空 dict——不并入 arguments，
                            # 参数由随后的 input_json_delta 分片拼装（并入 "{}" 会破坏 JSON）
                            start_input = block.get("input") or {}
                            start_args = (
                                json.dumps(start_input, ensure_ascii=False)
                                if start_input
                                else ""
                            )
                            agg.add_delta(
                                {
                                    "index": evt.get("index", 0),
                                    "id": block.get("id", ""),
                                    "function": {"name": block.get("name", ""), "arguments": start_args},
                                }
                            )
                    elif evt_type == "content_block_delta":
                        delta = evt.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta" and delta.get("text"):
                            acc.content_parts.append(delta["text"])
                            yield StreamDelta(text=delta["text"])
                        elif dtype == "thinking_delta" and delta.get("thinking"):
                            acc.reasoning_parts.append(delta["thinking"])
                            yield StreamDelta(text="", reasoning=delta["thinking"])
                        elif dtype == "input_json_delta":
                            agg.add_delta(
                                {
                                    "index": evt.get("index", 0),
                                    "function": {"arguments": delta.get("partial_json") or ""},
                                }
                            )
                    elif evt_type == "message_delta":
                        stop = ((evt.get("delta") or {}).get("stop_reason")) or ""
                        if stop:
                            acc.finish_reason = stop
                        if acc.finish_reason in ("max_tokens", "length"):
                            acc.truncated = True
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider)

    # ── Google Gemini API（wire_protocol=google，P3-5） ──
    def _stream_google(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        model_id = self.model if model is None else model
        url = (
            f"{self.base_url.rstrip('/')}/v1beta/models/{model_id}:streamGenerateContent?alt=sse"
        )
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        msgs = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "contents": self._to_google_contents(msgs),
            "generationConfig": {"maxOutputTokens": self.max_tokens or 4096},
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(str(p) for p in system_parts)}]
            }
        gtools = self._to_google_tools(tools)
        if gtools:
            payload["tools"] = gtools
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        google_fc_index = 0  # Google functionCall 每次独立工具调用（index 递增）
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if not data:
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usageMetadata") or {}
                    if usage:
                        # M58 修复（审查中危）: 缺失不覆盖（与 openai 路径一致）
                        pt = usage.get("promptTokenCount")
                        if pt:
                            acc.prompt_tokens = int(pt)
                        ct = usage.get("candidatesTokenCount")
                        if ct:
                            acc.completion_tokens = int(ct)
                    finish = chunk.get("candidates", [{}])[0].get("finishReason", "") if chunk.get("candidates") else ""
                    if finish:
                        acc.finish_reason = finish
                        if finish in ("MAX_TOKENS", "LENGTH"):
                            acc.truncated = True
                    parts = ((chunk.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    for part in parts:
                        if part.get("text"):
                            acc.content_parts.append(part["text"])
                            yield StreamDelta(text=part["text"])
                        if part.get("functionCall"):
                            fc = part["functionCall"]
                            agg.add_delta(
                                {
                                    "index": google_fc_index,
                                    "id": f"fc_{int(time.time() * 1000)}",
                                    "function": {
                                        "name": fc.get("name", ""),
                                        "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False),
                                    },
                                }
                            )
                            google_fc_index += 1
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider)

    # ── 共享工具方法 ──
    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            body = resp.read().decode("utf-8", errors="replace")[:2000]
            raise LLMHTTPError(
                f"HTTP {resp.status_code}: {resp.reason_phrase} | {body}",
                status_code=resp.status_code,
                body=body,
                provider=self.provider,
            )

    def _check_sse_error(self, chunk: dict[str, Any]) -> None:
        """P1-FEISHU: LM Studio SSE 错误事件检测（HTTP 200 + data: {error:...}）."""
        err_obj = chunk.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or err_obj.get("code") or "未知 SSE 错误"
            code = err_obj.get("code") or 500
            try:
                code_i = int(code)
            except Exception:
                code_i = 500
            raise LLMHTTPError(
                f"SSE provider error: {msg[:500]}",
                status_code=code_i,
                body=msg[:2000],
                provider=self.provider,
            )

    # ── 消息/工具协议转换 ──
    @staticmethod
    def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "tool":
                # 工具回执 → tool_result 块（OpenAI 历史中 tool_call_id 关联）
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": str(m.get("tool_call_id") or ""),
                                "content": str(content),
                            }
                        ],
                    }
                )
                continue
            if role == "assistant" and m.get("tool_calls"):
                # 声明侧工具调用 → tool_use 块 + 文本
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                for tc in m.get("tool_calls") or []:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(tc.get("id") or ""),
                            "name": str(tc.get("name") or ""),
                            "input": tc.get("arguments") or {},
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": role, "content": str(content)})
        return out

    @staticmethod
    def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
        out = []
        for t in tools:
            fn = t.get("function") or t
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return out

    @staticmethod
    def _to_google_contents(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": str(m.get("tool_name") or ""),
                                    "response": {"result": str(m.get("content") or "")},
                                }
                            }
                        ],
                    }
                )
                continue
            if role == "assistant" and m.get("tool_calls"):
                parts: list[dict] = []
                if m.get("content"):
                    parts.append({"text": str(m["content"])})
                for tc in m.get("tool_calls") or []:
                    parts.append({"functionCall": {"name": str(tc.get("name") or ""), "args": tc.get("arguments") or {}}})
                out.append({"role": "model", "parts": parts})
                continue
            out.append({"role": "user" if role == "user" else "model", "parts": [{"text": str(m.get("content") or "")}]})
        return out

    @staticmethod
    def _to_google_tools(tools: list[dict]) -> list[dict]:
        decls = []
        for t in tools:
            fn = t.get("function") or t
            decls.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return [{"functionDeclarations": decls}] if decls else []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,  # PARAM-01: 每次调用可覆盖超时（None 用构造值）
        model: str | None = None,
    ) -> LLMResponse:
        """非流式：内部走流式聚合（终态与流式一致，含思考链/截断/用量）."""
        it = self.chat_stream(messages, tools, timeout_s=timeout_s, model=model)
        result: LLMResponse | None = None
        while True:  # 消费全部 delta；终态 LLMResponse 经 StopIteration.value 捕获
            try:
                next(it)
            except StopIteration as exc:
                result = exc.value
                break
        return result if result is not None else LLMResponse(content=None, tool_calls=[], provider=self.provider)


if __name__ == "__main__":  # pragma: no cover
    pass
