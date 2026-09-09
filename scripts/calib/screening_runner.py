"""Stage S1 generic multi-provider screening runner.

No provider-specific benchmark semantics live here. Provider/model/runtime controls
come from tests/fixtures/calib/s_provider_manifest.json. S fixtures are P01-P08 and are
fresh effectiveness-screening tasks, separate from calibration holdouts.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
from llm_loop.llm.errors import LLMError
from scripts.calib import fixtures_s
from scripts.calib.treatments import build_system_prompt

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "calib" / "s_provider_manifest.json"
MAX_ROUNDS = 8


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _provider_profile(provider: str) -> dict:
    manifest = load_manifest()
    try:
        return manifest["providers"][provider]
    except KeyError as exc:
        raise ValueError(f"unknown S provider: {provider}") from exc


def build_screening_task_prompt(seed_id: str) -> str:
    packet = fixtures_s.INITIAL_PACKETS[seed_id]
    return (
        packet
        + "\n\n要求：\n"
        + "1. 区分 observation / fact / hypothesis / decision，不要把摘要或历史材料自动当事实。\n"
        + "2. 只在能改变当前 Decision 时请求证据；每个任务最多 2 个 source。\n"
        + "3. 高风险/不可逆动作必须满足当前 scope 的充分证据与约束。\n"
        + "4. 最后给出明确 Final Decision，并说明采取/不采取什么行动。"
    )


def screening_tool_spec() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "request_fixture",
            "description": "请求本任务列出的一个证据源。每个任务最多 2 个；未列出的 source 返回 SOURCE_NOT_AVAILABLE。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "例如 fixture://P01/write_fence"}
                },
                "required": ["source"],
            },
        },
    }


def _build_client(provider: str) -> LLMClient:
    manifest = load_manifest()
    common = manifest["benchmark_policy"]
    p = _provider_profile(provider)
    env_name = p["api_key_env"]
    api_key = os.environ.get(env_name, "")
    if not api_key:
        raise RuntimeError(f"{env_name} not set for provider={provider}")
    return LLMClient(
        api_key=api_key,
        base_url=p["base_url"],
        model=p["model"],
        provider=provider,
        timeout_s=float(common["timeout_s"]),
        max_tokens=int(common["benchmark_max_tokens"]),
        wire_protocol=common["wire_protocol"],
        thinking_mode=bool(p["thinking_supported"]),
        reasoning_effort=common["reasoning_effort"],
        thinking_supported=bool(p["thinking_supported"]),
        guard_enabled=False,
    )


def _chat_once(llm, messages, tools, run_id: str, provider: str, model: str):
    gen = llm.chat_stream(
        messages,
        tools,
        guard_context=GuardRequestContext(session_id=run_id, provider=provider, model=model),
    )
    it = iter(gen)
    while True:
        try:
            next(it)
        except StopIteration as exc:
            return exc.value


class FakeScreeningLLM:
    def __init__(self, seed_id: str, mode: str = "pass"):
        self.seed_id = seed_id
        self.mode = mode

    def chat_stream(self, messages, tools, **kwargs):
        return self._gen(messages)

    def _gen(self, messages):
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        expected = fixtures_s.ORACLES[self.seed_id]["expected_sources"]
        if self.mode == "pass" and len(tool_msgs) < len(expected):
            source = expected[len(tool_msgs)]
            resp = LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=f"call_fake_{len(tool_msgs) + 1}",
                        name="request_fixture",
                        arguments=json.dumps({"source": source}),
                    )
                ],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=5,
            )
        else:
            if self.mode == "pass":
                o = fixtures_s.ORACLES[self.seed_id]
                answer = (
                    o["expected_decision"]
                    + f" 新信号 {o['novel_signal']['field']}={o['novel_signal']['truth']}。"
                )
            else:
                answer = "Final Decision: 直接按已有摘要执行，不需要进一步核实。"
            resp = LLMResponse(
                content=answer,
                tool_calls=[],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=40,
            )
        if False:  # pragma: no cover
            yield None
        return resp


def execute_screening_run(
    run_id: str,
    provider: str,
    seed_id: str,
    variant: str,
    *,
    dry: bool = False,
    dry_mode: str = "pass",
) -> dict:
    p = _provider_profile(provider)
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(variant)},
        {"role": "user", "content": build_screening_task_prompt(seed_id)},
    ]
    tools = [screening_tool_spec()]
    trace: list[dict] = []
    requested_sources: list[str] = []
    requested_count = 0
    reasoning_parts: list[str] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    status = "COMPLETED"
    infra_error = None
    final_answer = None

    try:
        llm = FakeScreeningLLM(seed_id, dry_mode) if dry else _build_client(provider)
    except Exception as exc:  # no network request made
        return {
            "run_id": run_id,
            "provider_id": provider,
            "seed_id": seed_id,
            "variant": variant,
            "status": "INFRA_FAILURE",
            "infra_error": f"{type(exc).__name__}: {exc}",
            "model_used": f"{provider}/{p['model']}",
            "thinking_mode": bool(p["thinking_supported"]),
            "final_answer": None,
            "reasoning": None,
            "requested_sources": [],
            "requested_count": 0,
            "trace": [],
            "stats": stats,
        }

    model_used = "fake-dry" if dry else f"{provider}/{p['model']}"
    t0 = time.monotonic()
    try:
        for round_index in range(1, MAX_ROUNDS + 1):
            resp = _chat_once(llm, messages, tools, run_id, provider, p["model"])
            stats["prompt_tokens"] += getattr(resp, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(resp, "completion_tokens", 0) or 0
            stats["cache_hit_tokens"] += getattr(resp, "prompt_cache_hit_tokens", 0) or 0
            rc = getattr(resp, "reasoning_content", None) or getattr(resp, "reasoning", None)
            if rc:
                reasoning_parts.append(rc)
            if not resp.tool_calls:
                final_answer = resp.content
                break
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
                    if requested_count > fixtures_s.SOURCE_LIMIT:
                        content = fixtures_s.LIMIT_EXCEEDED_RESPONSE
                    else:
                        content = (
                            fixtures_s.lookup_source(seed_id, source)
                            or fixtures_s.UNAVAILABLE_RESPONSE
                        )
                    requested_sources.append(source)
                else:
                    content = fixtures_s.UNAVAILABLE_RESPONSE
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
                assistant_msg = {
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
                if rc:
                    assistant_msg["reasoning_content"] = rc
                messages.append(assistant_msg)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
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
        "provider_id": provider,
        "seed_id": seed_id,
        "variant": variant,
        "status": status,
        "infra_error": infra_error,
        "model_used": model_used,
        "thinking_mode": bool(p["thinking_supported"]),
        "final_answer": final_answer,
        "reasoning": "\n".join(reasoning_parts) if reasoning_parts else None,
        "requested_sources": requested_sources,
        "requested_count": requested_count,
        "trace": trace,
        "stats": stats,
    }


def snapshot_provider(provider: str, out_dir: Path) -> dict:
    manifest = load_manifest()
    common = manifest["benchmark_policy"]
    p = _provider_profile(provider)
    snap = {
        "provider": provider,
        "service": p["service"],
        "model": p["model"],
        "base_url": p["base_url"],
        "api_key_env": p["api_key_env"],
        "api_key_set": bool(os.environ.get(p["api_key_env"])),
        "context_tokens": p["context_tokens"],
        "thinking_supported": p["thinking_supported"],
        "benchmark_max_tokens": common["benchmark_max_tokens"],
        "timeout_s": common["timeout_s"],
        "wire_protocol": common["wire_protocol"],
        "reasoning_effort": common["reasoning_effort"],
        "temperature": common["temperature"],
        "top_p": common["top_p"],
        "fallback": common["fallback"],
        "cache_policy": common["cache_policy"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"provider_snapshot_{provider}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snap
