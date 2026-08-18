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
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from llm_loop.core.message import ToolCall
from llm_loop.llm.errors import (
    LLMError,
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
    # 2026-08-18 cache_guard 规则 G: 响应后回馈命中（闭环——guard 跟踪会话命中率）
    try:
        _pg = getattr(self, "_pg", None)
        if _pg is not None and self.guard_session_id:
            _pg.record_result(self.guard_session_id, acc.prompt_tokens, acc.prompt_cache_hit_tokens)
    except Exception:  # noqa: BLE001
        pass
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
    # 2026-08-18 cache_guard（MCP 出入口）: 请求前规则校验开关（默认开；CACHE_GUARD=0 关闭）
    guard_enabled: bool = True
    # guard 校验的 system 文本（engine 传入——含动态段；None 时用 messages[0] 兜底）
    guard_system: str | None = None
    # 会话上下文（engine 透传——会话级基线/压缩计数/预算）
    guard_session_id: str = ""
    guard_compress_count: int = 0
    guard_history_budget: int = 0
    # 模型切换检测（拷问②）: 记录上次模型——切换时重置 guard 窗口（防旧模型低命中误拦）
    guard_last_model: str = ""
    # M3 适配（2026-08-18）: <think> 标签流式剥离状态（跨 delta 累积）
    _think_buf: str = ""
    _in_think: bool = False

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
        # 2026-08-18 cache_guard（MCP 出入口——唯一出入口）: 发送前规则校验（fail-open）
        self._guard_start_ts = 0
        if self.guard_enabled:
            try:
                from llm_loop.cache_guard.guard import PromptGuard

                _sys = self.guard_system if self.guard_system is not None else (
                    messages[0].get("content", "") if messages and messages[0].get("role") == "system" else ""
                )
                _guard = getattr(self, "_pg", None)
                if _guard is None:
                    _guard = PromptGuard()
                    self._pg = _guard
                # 模型切换 → 重置窗口（不同模型前缀不同——旧窗口命中率无意义）
                if self.guard_last_model and self.guard_last_model != self.model:
                    _guard.reset_session(self.guard_session_id or "__global__")
                self.guard_last_model = self.model
                _d = _guard.check(
                    session_id=self.guard_session_id or "__global__",
                    system_text=_sys,
                    messages=messages,
                    tools=tools,
                    compress_count_this_run=self.guard_compress_count,
                )
                if _d.rule == "submit_ratio" and _d.verdict == "WARN":
                    # 规则 F WARN 升级：注入提示（AI 可见——接近超限提前处理）
                    self.guard_warn_injected = getattr(self, "guard_warn_injected", False)
                if _d.verdict == "BLOCK":
                    from llm_loop.cache_guard.guard import CacheGuardBlockedError

                    raise CacheGuardBlockedError(f"cache_guard 拦截: {_d.detail}")
                if _d.verdict == "WARN":
                    logger.warning("cache_guard: %s（%s）", _d.rule, _d.detail)
            except LLMError:
                raise
            except Exception:  # noqa: BLE001 — fail-open 不阻断
                logger.debug("cache_guard 校验异常（fail-open）", exc_info=True)
        # 注意：Python 3.11+ 裸 `yield from` 会丢弃子生成器 return 值（StopIteration.value=None），
        # 必须显式捕获后 return 才能把终态 LLMResponse 传给消费者（engine 经 StopIteration.value 取终态）。
        if protocol == "anthropic":
            result = yield from self._stream_anthropic(messages, tools, timeout_s=timeout_s, model=model)
        elif protocol == "google":
            result = yield from self._stream_google(messages, tools, timeout_s=timeout_s, model=model)
        elif protocol == "lms-chat":
            result = yield from self._stream_lms_chat(messages, tools, timeout_s=timeout_s, model=model)
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
                        # M58: 前缀缓存命中（DeepSeek prompt_cache_hit_tokens；Kimi 兜底 cached_tokens；
                        # 2026-08-18 MiniMax-M3: prompt_tokens_details.cached_tokens（嵌套——实测 128 命中）
                        hit = usage.get("prompt_cache_hit_tokens")
                        if hit is None:
                            hit = usage.get("cached_tokens")
                        if hit is None:
                            hit = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                        if hit:
                            acc.prompt_cache_hit_tokens = int(hit)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        # 2026-08-18 MiniMax-M3 适配（场景 B）: M3 把思考链放 content 的
                        # <think>...</think> 标签（reasoning_content 字段为空）——流式剥离到 reasoning
                        self._think_buf = getattr(self, "_think_buf", "") + content
                        _in_think = getattr(self, "_in_think", False)
                        while True:
                            if not _in_think:
                                idx = self._think_buf.find("<think>")
                                if idx == -1:
                                    normal = self._think_buf
                                    self._think_buf = ""
                                    if normal:
                                        acc.content_parts.append(normal)
                                        yield StreamDelta(text=normal)
                                    break
                                normal = self._think_buf[:idx]
                                self._think_buf = self._think_buf[idx:]
                                if normal:
                                    acc.content_parts.append(normal)
                                    yield StreamDelta(text=normal)
                                _in_think = True
                            else:
                                end = self._think_buf.find("</think>")
                                if end == -1:
                                    think = self._think_buf
                                    self._think_buf = ""
                                    if think:
                                        acc.reasoning_parts.append(think)
                                        yield StreamDelta(text="", reasoning=think)
                                    break
                                think = self._think_buf[:end]
                                self._think_buf = self._think_buf[end + len("</think>"):]
                                _in_think = False
                                if think:
                                    acc.reasoning_parts.append(think)
                                    yield StreamDelta(text="", reasoning=think)
                        self._in_think = _in_think
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
    def _anthropic_cache_enabled(self) -> bool:
        """prompt caching 开关（EVO-20260817）: env ANTHROPIC_CACHE_CONTROL 显式覆盖；
        未配置时 localhost/127.0.0.1 自动启用（本地模型省 token 主场景），远端默认关
        （官方 API 兼容但默认零回归，避免第三方端点对 cache_control 报错）。"""
        v = os.environ.get("ANTHROPIC_CACHE_CONTROL")
        if v is not None:
            return v.strip().lower() in {"1", "true", "yes", "on"}
        base = (self.base_url or "").lower()
        return "localhost" in base or "127.0.0.1" in base

    def _stream_anthropic(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        # EVO-20260817: base_url 已含 /v1 时（如 LM Studio http://localhost:1234/v1）
        # 避免拼出 /v1/v1/messages 404——归一化后两种配置均正确，官方 API 零回归
        _base = self.base_url.rstrip("/")
        if _base.endswith("/v1"):
            _base = _base[:-3]
        url = f"{_base}/v1/messages"
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        msgs = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": self._to_anthropic_messages(msgs),
            "stream": True,
            "max_tokens": self.max_tokens or 4096,
        }
        # EVO-20260817: 无工具时不发 tools 字段（LM Studio 拒绝 null；官方 API 亦兼容省略）
        _atools = self._to_anthropic_tools(tools)
        if _atools:
            payload["tools"] = _atools
        if system_parts:
            # EVO-20260817 prompt caching（本地模型省 token，用户需求）:
            # system+tools 为"固化固定信息"（每轮不变），打 cache_control 标记 →
            # 首次全量计费、后续轮 cache hit 只计费追加的 messages（实测 LM Studio
            # cache_read_input_tokens 命中，81% 前缀省 token）；messages 尾部追加最新。
            # 默认 localhost 自动启用；官方 API 亦兼容（可 env 覆盖）。
            if self._anthropic_cache_enabled():
                payload["system"] = [
                    {
                        "type": "text",
                        "text": "\n\n".join(str(p) for p in system_parts),
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                if payload.get("tools"):
                    payload["tools"][-1]["cache_control"] = {"type": "ephemeral"}
            else:
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

    # ── LM Studio /api/v1/chat（wire_protocol=lms-chat，EVO-20260817 用户需求） ──
    def _stream_lms_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        """LM Studio 新版 /api/v1/chat 端点适配.

        端点特征（实测 2026-08-17）:
        - input: 模态数组 [{type: text, content: str}]（无 role/system/tools 键——极简接口）
        - SSE 流式: reasoning.delta / message.delta / chat.end 事件（无原生工具事件）
        - 无原生工具调用 → 文本工具协议: 工具描述注入文本, 模型输出
          JSON {"tool": name, "args": {...}}，此处解析为 ToolCall 交给循环执行
        - 工具轮上下文精简（用户需求）: 只保留最近 LMS_CHAT_TAIL 条消息文本化
          （默认 16），不发送全部历史——端点无角色字段天然拼接, 早期历史经压缩
          归档可检索（信息零丢失）
        """
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/v1/chat"
        model_id = self.model if model is None else model
        payload: dict[str, Any] = {
            "model": model_id,
            "input": self._to_lms_input(messages, tools),
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        acc = _StreamAcc()
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                if resp.status_code >= 400:
                    self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except ValueError:
                        continue
                    etype = chunk.get("type")
                    if etype == "reasoning.delta":
                        rc = chunk.get("content") or ""
                        if rc:
                            acc.reasoning_parts.append(rc)
                            yield StreamDelta(text="", reasoning=rc)
                    elif etype == "message.delta":
                        c = chunk.get("content") or ""
                        if c:
                            acc.content_parts.append(c)
                            yield StreamDelta(text=c)
                    elif etype == "chat.end":
                        break
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        content = "".join(acc.content_parts) or None
        reasoning = "".join(acc.reasoning_parts) or None
        tool_calls: list[ToolCall] = []
        if content:
            for i, tc in enumerate(self._parse_text_tool_calls(content)):
                tool_calls.append(ToolCall(id=f"lms-{i}", name=tc["name"], arguments=tc["arguments"]))
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.provider,
            reasoning_content=reasoning,
            prompt_tokens=acc.prompt_tokens,
            completion_tokens=acc.completion_tokens,
        )

    # ── lms-chat 文本工具协议 ──
    _LMS_CHAT_TAIL = int(os.environ.get("LMS_CHAT_TAIL", "16"))  # 工具轮只保留最近 N 条（上下文精简）

    def _to_lms_input(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """消息 → input 模态数组（system + 工具描述 + 最近 N 条历史，文本化）."""
        parts: list[str] = []
        for m in messages:
            if m.get("role") == "system" and m.get("content"):
                parts.append("[系统] " + str(m["content"]))
        if tools:
            parts.append(self._lms_tools_text(tools))
        tail = [m for m in messages if m.get("role") != "system"][-self._LMS_CHAT_TAIL:]
        for m in tail:
            parts.append(self._lms_msg_text(m))
        return [{"type": "text", "content": "\n\n".join(parts)}]

    @staticmethod
    def _lms_msg_text(m: dict) -> str:
        """单条消息文本化（角色前缀标记；工具结果/调用 JSON 化）."""
        role = m.get("role", "user")
        content = m.get("content")
        c = content if isinstance(content, str) else (
            json.dumps(content, ensure_ascii=False) if content else ""
        )
        if role == "tool":
            name = m.get("name") or "tool"
            return f"[工具结果 {name}] {c}"
        if role == "assistant":
            tcs = m.get("tool_calls") or []
            extra = ""
            if tcs:
                bits = []
                for tc in tcs:
                    fn = tc.get("function") or tc
                    bits.append(
                        f'[调用工具 {fn.get("name")} 参数 {json.dumps(fn.get("arguments") or {}, ensure_ascii=False)}]'
                    )
                extra = " " + " ".join(bits)
            return f"[助手] {c}{extra}"
        return f"[用户] {c}"

    @staticmethod
    def _lms_tools_text(tools: list[dict]) -> str:
        """工具描述 → 文本注入（文本工具协议）.

        EVO-20260817 本地模型精简（用户需求）: 本地模型 prefill 随输入线性增长，
        全量 40+ 工具完整 JSON 每轮重发 = token 大头。这里固化精简:
        - 仅 name + description 首句（≤120 字符）+ 参数骨架（字段名+类型+required）
        - 固定不变 → 前缀稳定；尾部追加最新消息（LMS_CHAT_TAIL 已限 16 条）
        - 省 token 但不影响推理: 模型只需知道"有哪些工具/干什么/参数骨架"，
          完整 schema 按需经 get_tool_schema 读取
        """
        lines = ["[可用工具]"]
        for t in tools:
            fn = t.get("function") or t
            desc = (fn.get("description") or "").strip().split("\n")[0][:120]
            params = fn.get("parameters") or {}
            props = (params.get("properties") or {})
            skeleton = {
                k: {"type": v.get("type", "string")}
                for k, v in props.items()
            }
            lines.append(
                json.dumps(
                    {
                        "name": fn.get("name", ""),
                        "description": desc,
                        "parameters": {
                            "type": "object",
                            "properties": skeleton,
                            "required": params.get("required", []),
                        },
                    },
                    ensure_ascii=False,
                )
            )
        lines.append(
            '需要调用工具时，仅输出一行 JSON: {"tool": "工具名", "args": {...}}；'
            "多个调用用换行分隔，不要输出其他内容。"
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_text_tool_calls(text: str) -> list[dict]:
        """从消息文本解析文本协议工具调用 → [{name, arguments(dict)}].

        容错: ```json 围栏、前后杂文本、args 嵌套空对象/数组；
        解析失败返回空（fail-open 当普通回答）。
        实现: 定位 "tool" 键 → 向前找对象起点 → 平衡括号找对象终点 → json.loads。
        """
        import re

        out: list[dict] = []
        s = text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
        if m:
            s = m.group(1).strip()
        for tm in re.finditer(r'"tool"\s*:\s*"[^"]+"', s):
            i = tm.start()
            while i > 0 and s[i] != "{":
                i -= 1
            if s[i] != "{":
                continue
            depth = 0
            in_str = False
            esc = False
            j = i
            while j < len(s):
                ch = s[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            if j >= len(s):
                continue
            try:
                d = json.loads(s[i : j + 1])
            except ValueError:
                continue
            name = d.get("tool")
            if not name:
                continue
            args = d.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            out.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
        return out

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
        """OpenAI 历史 → Anthropic messages（tool_use/tool_result 配对清洗）.

        2026-08-17 修复: 历史可能含"声明了 tool_calls 但回执缺失"的 assistant 消息
        （LLM 调用失败中断/上下文压缩裁剪导致）。Anthropic API 硬约束: tool_use 必须
        紧跟对应 tool_result。清洗策略: 未消费的孤立 tool_use 删除其块（含整条空消息
        剔除）；孤立 tool_result（无对应 tool_use）删除该 user 消息。避免 400 拒绝。
        """
        # 第一遍: 转换 + 记录 tool_use 消费情况
        out: list[dict] = []
        pending_use_ids: list[str] = []   # 已发出但未消费的 tool_use id
        consumed: set[str] = set()        # 已被 tool_result 消费的 id
        # (输出索引, 该条 assistant 的 tool_use id 列表)
        assistant_blocks: list[tuple[int, list[str]]] = []
        # 2026-08-17 修复2: 连续 tool 回执合并为单条 user（含多个 tool_result 块）。
        # Anthropic 硬约束: 每个 tool_use 必须"immediately after"紧跟其 tool_result；
        # 若一条 assistant 声明多个 tool_use、回执拆成多条独立 user → 仅第一个 tool_use
        # 满足紧跟，后续 tool_use 被前一条 user 隔开 → 400（现场: id 360355894）。
        # 合并后: assistant[text, tool_use A, tool_use B] → user[tool_result A, tool_result B]。
        tool_buffer: list[dict] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "tool":
                tid = str(m.get("tool_call_id") or "")
                if tid and tid not in pending_use_ids:
                    # 孤立 tool_result（无对应 tool_use）→ 跳过该消息
                    continue
                tool_buffer.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": str(content),
                    }
                )
                consumed.add(tid)
                continue
            # 非 tool 消息: 先 flush 缓冲的 tool_result（合并为单条 user）
            if tool_buffer:
                out.append({"role": "user", "content": tool_buffer})
                tool_buffer = []
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                ids: list[str] = []
                for tc in m.get("tool_calls") or []:
                    tid = str(tc.get("id") or "")
                    ids.append(tid)
                    pending_use_ids.append(tid)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tid,
                            "name": str(tc.get("name") or ""),
                            "input": tc.get("arguments") or {},
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                assistant_blocks.append((len(out) - 1, ids))
                continue
            out.append({"role": role, "content": str(content)})
        if tool_buffer:  # 循环尾部 flush
            out.append({"role": "user", "content": tool_buffer})
        # 第二遍: 剔除未消费的孤立 tool_use 块（整条消息无文本且全孤立 → 删消息）
        orphan_ids = [tid for tid in pending_use_ids if tid not in consumed]
        if orphan_ids:
            orphan_set = set(orphan_ids)
            for idx, ids in assistant_blocks:
                msgs = out[idx]
                blocks = msgs.get("content") or []
                keep = [b for b in blocks if not (b.get("type") == "tool_use" and b.get("id") in orphan_set)]
                if keep:
                    out[idx]["content"] = keep
                else:
                    # 该 assistant 消息只剩孤立 tool_use → 整条删除
                    out[idx] = None
            out = [m for m in out if m is not None]
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
