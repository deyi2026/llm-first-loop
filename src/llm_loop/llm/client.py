"""OpenAI 兼容流式 LLM 客户端（design.md §2.2.2.4 / DFX-CMP-01/02）.

- 流式请求（DFX-PERF-01），SSE 增量解析
- 严格 function calling（约束 C1-C6）: tool_choice="auto"，tool_calls 按 index 聚合
- 异常分类（DFX-REL-02）: LLMTimeoutError / LLMNetworkError / LLMHTTPError / LLMProtocolError
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from llm_loop.core.message import ToolCall
from llm_loop.llm.errors import (
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)
from llm_loop.llm.schemas import ToolCallDeltaAggregator


@dataclass
class LLMResponse:
    """一次 LLM 往返的解析结果（design.md §2.2.2.4）.

    M20（THK-02/03）: reasoning_content 聚合思考链（DeepSeek V4 思考模式）；缺失态 None。
    """

    content: str | None
    tool_calls: list[ToolCall]
    provider: str
    truncated: bool = False  # 流式是否被截断（如实标注）
    reasoning_content: str | None = None  # M20: 思考链（存在态按序拼接/缺失态 None）


@dataclass
class LLMClient:
    """OpenAI 兼容流式客户端.

    通过 `LLMClient.chat(messages, tools)` 发起请求；
    测试用 FakeLLM 需实现相同接口（Duck typing）。
    """

    api_key: str
    base_url: str
    model: str
    timeout_s: float = 120.0
    max_retries: int = 0

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

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,  # PARAM-01: 每次调用可覆盖超时（None 用构造值）
        model: str | None = None,  # WEB: 每次调用可覆盖模型（None 用构造值，供 Web 模型切换）
    ) -> LLMResponse:
        """流式请求并聚合 tool_calls（同步阻塞式消费 SSE）.

        异常按类型抛出 LLMError 子类，由循环如实反馈。
        """
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",  # 约束 C6
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # M20 THK-01: DeepSeek V4 思考模式显式声明（thinking_mode AND provider 支持才发送）
        if self.thinking_mode and self._thinking_supported():
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        content_parts: list[str] = []
        reasoning_parts: list[str] = []  # M20 THK-02: 思考链分片（与 content/tool_calls 并行）
        agg = ToolCallDeltaAggregator()
        truncated = False
        finish_reason = ""

        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")[:2000]
                    raise LLMHTTPError(
                        f"HTTP {resp.status_code}: {resp.reason_phrase} | {body}",
                        status_code=resp.status_code,
                        body=body,
                        provider=self.provider,
                    )
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
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        content_parts.append(content)
                    # M20 THK-02: reasoning_content 独立分支（与 content/tool_calls 互不读写并行）
                    rc = delta.get("reasoning_content")
                    if rc:
                        reasoning_parts.append(rc)
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            agg.add_delta(tc)
                    fr = choice.get("finish_reason")
                    if fr:
                        finish_reason = fr
                    if finish_reason == "length":
                        truncated = True
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc

        raw_calls = agg.finish()
        tool_calls: list[ToolCall] = []
        for c in raw_calls:
            if not c["id"]:
                # 约束 C1: 缺 id 声明不可执行 — 保留原始信息由循环如实反馈
                # 此处以空 id 构造，循环层会拒绝执行并注入反馈
                pass
            tool_calls.append(
                ToolCall(
                    id=c["id"],
                    name=c["name"],
                    arguments=c["arguments"],
                )
            )

        content = "".join(content_parts) or None
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.provider,
            truncated=truncated,
            reasoning_content="".join(reasoning_parts) or None,  # M20 THK-02/03
        )
