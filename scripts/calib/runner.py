"""C0/C1 单 run 执行器 — 独立 runner 直连 MiniMax / DeepSeek API（llm_loop.llm.client），dry 模式走 FakeCalibLLM.

冻结依据:
- C0 执行顺序: `docs/CALIBRATION-MATRIX-v1.md`
- C1 执行顺序: `docs/CALIBRATION-MATRIX-C1.md`
- 同 seed 三 variant 只允许 treatment 不同（Pilot §4.1）
- 每个 run 新 session；resolved model 必须 minimax/MiniMax-M3（C0）或 deepseek/deepseek-v4-flash（C1）；
  fallback/其它 model → INFRA_FAILURE（FROZEN-v2 §7）
- Retry: 同 run 最多 1 次 INFRA retry（FROZEN-v2 §FROZEN-v1 Retry Policy 迁移）
- cache carry-over: record-and-randomize；不人为加 nonce
- C1 reasoning: DeepSeek thinking 输出写入 result["reasoning"]（Reasoning-Field Policy B）
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import (
    current_reasoning_effort,  # noqa: F401  # 保持与引擎同款导入路径
)
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
from llm_loop.llm.errors import LLMError
from scripts.calib import fixtures as _fixtures_default
from scripts.calib.fixtures import (  # noqa: F401  # 保持既有导入兼容
    LIMIT_EXCEEDED_RESPONSE,
    ORACLES,
    SOURCE_LIMIT,
    UNAVAILABLE_RESPONSE,
    lookup_source,
)
from scripts.calib.treatments import (
    build_system_prompt,
    build_task_prompt,
    request_fixture_tool_spec,
)

MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
MINIMAX_MODEL = "MiniMax-M3"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
MAX_ROUNDS = 8

_PROVIDER_PROFILE = {
    "minimax": {
        "api_key_env": "MINIMAX_API_KEY",
        "base_url": MINIMAX_BASE_URL,
        "model": MINIMAX_MODEL,
        "max_tokens": 65536,
        "thinking_supported": False,
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": DEEPSEEK_BASE_URL,
        "model": DEEPSEEK_MODEL,
        "max_tokens": 16384,
        "thinking_supported": True,
    },
}


def _chat_once(llm, messages, tools, run_id: str, provider: str, model: str):
    """调用一次 chat_stream，消费流并取终态 LLMResponse（generator return value）。"""
    gen = llm.chat_stream(
        messages,
        tools,
        guard_context=GuardRequestContext(
            session_id=run_id,
            provider=provider,
            model=model,
        ),
    )
    it = iter(gen)
    while True:
        try:
            next(it)
        except StopIteration as exc:
            return exc.value


def _build_client(provider: str) -> LLMClient:
    profile = _PROVIDER_PROFILE[provider]
    api_key = os.environ.get(profile["api_key_env"], "")
    if not api_key:
        raise RuntimeError(f"{profile['api_key_env']} 未设置（真实模式需要）")
    return LLMClient(
        api_key=api_key,
        base_url=profile["base_url"],
        model=profile["model"],
        provider=provider,
        timeout_s=300.0,
        max_tokens=profile["max_tokens"],
        wire_protocol="openai",
        thinking_supported=profile["thinking_supported"],
        guard_enabled=False,
    )


class FakeCalibLLM:
    """dry 模式假 LLM：实现 chat_stream 接口（Duck typing），按预设脚本驱动完整工具循环。"""

    def __init__(self, seed_id: str, mode: str = "pass", data=None):
        self.seed_id = seed_id
        self.mode = mode
        self.data = data if data is not None else _fixtures_default

    def chat_stream(self, messages, tools, **kwargs):
        return self._gen(messages)

    def _gen(self, messages):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        expected = self.data.ORACLES[self.seed_id]["expected_sources"]
        if self.mode == "pass" and len(tool_msgs) < len(expected):
            source = expected[len(tool_msgs)]
            tc = ToolCall(
                id=f"call_fake_{len(tool_msgs) + 1}",
                name="request_fixture",
                arguments=json.dumps({"source": source}, ensure_ascii=False),
            )
            resp = LLMResponse(
                content=None, tool_calls=[tc], provider="fake",
                prompt_tokens=10, completion_tokens=5,
            )
        else:
            resp = LLMResponse(
                content=_fake_answer(self.seed_id, self.mode, self.data),
                tool_calls=[],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=40,
            )
        if False:  # pragma: no cover — 仅使函数成为 generator 以承载 return value
            yield None
        return resp


def _fake_answer(seed_id: str, mode: str, data=None) -> str:
    data = data if data is not None else _fixtures_default
    oracle = data.ORACLES[seed_id]
    if mode == "pass":
        ns = oracle["novel_signal"]
        return (
            "Final Decision: " + oracle["expected_decision"] + " "
            f"关键新信号 {ns['field']}（{ns['truth']}）已核实并纳入判断。"
        )
    return (
        "Final Decision: 依据上下文材料直接判断，无需进一步核实。"
    )


def execute_run(
    run_id: str,
    seed_id: str,
    variant: str,
    *,
    dry: bool = False,
    dry_mode: str = "pass",
    provider: str = "minimax",
    data=None,
) -> dict:
    """执行单个 run。返回完整结果 dict（trace / final_answer / reasoning / stats / status）。

    data: 数据层模块（默认 scripts.calib.fixtures；C1H H2 传入 scripts.calib.fixtures_h2）。
    """
    if data is None:
        data = _fixtures_default
    profile = _PROVIDER_PROFILE[provider]
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(variant)},
        {"role": "user", "content": build_task_prompt(seed_id, data.INITIAL_PACKETS)},
    ]
    tools = [request_fixture_tool_spec()]
    trace: list[dict] = []
    stats = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_hit_tokens": 0,
        "latency_s": 0.0,
    }
    final_answer: str | None = None
    reasoning_parts: list[str] = []
    status = "COMPLETED"
    infra_error: str | None = None
    requested_sources: list[str] = []
    requested_count = 0

    llm = FakeCalibLLM(seed_id, mode=dry_mode, data=data) if dry else _build_client(provider)
    model_used = "fake-dry" if dry else f"{provider}/{profile['model']}"
    t0 = time.monotonic()
    try:
        for round_index in range(1, MAX_ROUNDS + 1):
            resp = _chat_once(llm, messages, tools, run_id, provider, profile["model"])
            stats["prompt_tokens"] += getattr(resp, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(resp, "completion_tokens", 0) or 0
            stats["cache_hit_tokens"] += getattr(resp, "prompt_cache_hit_tokens", 0) or 0
            rc = getattr(resp, "reasoning_content", None) or getattr(resp, "reasoning", None)
            if rc:
                reasoning_parts.append(rc)
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    if isinstance(tc.arguments, dict):
                        args = tc.arguments
                    elif isinstance(tc.arguments, str):
                        try:
                            args = json.loads(tc.arguments or "{}")
                        except (ValueError, TypeError):
                            args = {}
                    else:
                        args = {}
                    args_json = json.dumps(args, ensure_ascii=False)
                    source = str(args.get("source", ""))
                    if tc.name == "request_fixture":
                        requested_count += 1
                        if requested_count > data.SOURCE_LIMIT:
                            content = data.LIMIT_EXCEEDED_RESPONSE
                        else:
                            content = data.lookup_source(seed_id, source) or data.UNAVAILABLE_RESPONSE
                        requested_sources.append(source)
                    else:
                        content = data.UNAVAILABLE_RESPONSE
                    trace.append(
                        {
                            "round": round_index,
                            "name": tc.name,
                            "arguments": args_json,
                            "source": source,
                            "result_head": content[:500],
                            "result_full": content,
                            "requested_count": requested_count,
                        }
                    )
                    assistant_msg: dict = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": args_json},
                            }
                        ],
                    }
                    rc = getattr(resp, "reasoning_content", None) or getattr(resp, "reasoning", None)
                    if rc:
                        assistant_msg["reasoning_content"] = rc  # M20 THK-04: 携带 tool_calls 必须回传否则 400
                    messages.append(assistant_msg)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": content}
                    )
            else:
                final_answer = resp.content
                break
        else:
            status = "ROUND_LIMIT"
    except LLMError as exc:
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    finally:
        stats["latency_s"] = round(time.monotonic() - t0, 3)
        if not dry:
            with contextlib.suppress(Exception):  # noqa: BLE001 — close 失败不影响结果
                llm.close()

    return {
        "run_id": run_id,
        "seed_id": seed_id,
        "variant": variant,
        "status": status,
        "infra_error": infra_error,
        "model_used": model_used,
        "final_answer": final_answer,
        "reasoning": "\n".join(reasoning_parts) if reasoning_parts else None,
        "requested_sources": requested_sources,
        "requested_count": requested_count,
        "trace": trace,
        "stats": stats,
    }


def write_run_result(run_id: str, result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def snapshot_provider(out_dir: Path, provider: str = "minimax") -> dict:
    """before 首个 run：快照 resolved request parameters（FROZEN Readiness 要求）。"""
    profile = _PROVIDER_PROFILE[provider]
    snap = {
        "provider": provider,
        "model": profile["model"],
        "base_url": profile["base_url"],
        "api_key_env": profile["api_key_env"],
        "api_key_set": bool(os.environ.get(profile["api_key_env"])),
        "timeout_s": 300.0,
        "max_tokens": profile["max_tokens"],
        "thinking_supported": profile["thinking_supported"],
        "wire_protocol": "openai",
        "temperature": None,
        "top_p": None,
        "seed": None,
        "guard_enabled": False,
        "history_budget_chars_registry": {"minimax": 400000, "deepseek": 300000}.get(provider),
        "context_tokens_registry": 1000000,
        "cache_policy": "record-and-randomize",
        "fallback": "无（fallback → INFRA_FAILURE）",
        "note": "temperature/top_p 无应用层显式配置，不编造数值；同一 stage 内保持一致。",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "provider_snapshot.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap
