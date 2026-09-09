"""A3 execution runner with experimental Action-Plane guards.

Historical/frozen scripts/calib/runner.py is imported read-only and never patched.
All A3 variants use the exact same Full-Slim-v1 prompt; only action mechanics vary.
"""

from __future__ import annotations

import contextlib
import json
import time

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMError
from scripts.calib import runner as base
from scripts.calib.action_guard import (
    GuardConfig,
    GuardState,
    handle_request_fixture,
    visible_tools,
)
from scripts.calib.treatments import build_task_prompt, request_fixture_tool_spec
from scripts.calib.treatments_a2 import build_system_prompt_a2

A3_VARIANTS = [
    "C0-NoGuard",
    "C1-DuplicateSuppression",
    "C2-BudgetTerminal",
    "C3-CombinedGuard",
]

_GUARDS = {
    "C0-NoGuard": GuardConfig(False, False),
    "C1-DuplicateSuppression": GuardConfig(True, False),
    "C2-BudgetTerminal": GuardConfig(False, True),
    "C3-CombinedGuard": GuardConfig(True, True),
}


def guard_config_for(variant: str) -> GuardConfig:
    try:
        return _GUARDS[variant]
    except KeyError as exc:
        raise ValueError(f"unknown A3 variant: {variant}") from exc


def build_system_prompt_a3(variant: str) -> str:
    guard_config_for(variant)  # validate only; variant is intentionally prompt-blind
    return build_system_prompt_a2("B2-Full-Slim-v1")


class FakeLoopLLM:
    """Test helper: emits queued fixture calls while the tool exists, then answers."""

    def __init__(self, sources: list[str], final: str = "Final Decision: done"):
        self.sources = list(sources)
        self.final = final
        self.i = 0

    def chat_stream(self, messages, tools, **kwargs):
        if tools and self.i < len(self.sources):
            src = self.sources[self.i]
            self.i += 1
            resp = LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=f"loop_{self.i}",
                        name="request_fixture",
                        arguments=json.dumps({"source": src}),
                    )
                ],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=5,
            )
        else:
            resp = LLMResponse(
                content=self.final,
                tool_calls=[],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=20,
            )
        if False:
            yield None
        return resp

    def close(self):
        return None


def execute_run_a3(
    run_id: str,
    seed_id: str,
    variant: str,
    *,
    dry: bool = False,
    provider: str = "minimax",
    data=None,
    llm_override=None,
) -> dict:
    if data is None:
        raise ValueError("A3 data module is required")
    profile = base._PROVIDER_PROFILE[provider]
    config = guard_config_for(variant)
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt_a3(variant)},
        {"role": "user", "content": build_task_prompt(seed_id, data.INITIAL_PACKETS)},
    ]
    base_tools = [request_fixture_tool_spec()]
    trace: list[dict] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    final_answer = None
    reasoning_parts: list[str] = []
    status = "COMPLETED"
    infra_error = None
    requested_sources: list[str] = []
    state = GuardState()
    rounds_to_final = 0

    if llm_override is not None:
        llm = llm_override
        model_used = "fake-override"
    elif dry:
        llm = base.FakeCalibLLM(seed_id, mode="pass", data=data)
        model_used = "fake-dry"
    else:
        llm = base._build_client(provider)
        model_used = f"{provider}/{profile['model']}"

    t0 = time.monotonic()
    try:
        for round_index in range(1, base.MAX_ROUNDS + 1):
            tools = visible_tools(base_tools, state, config)
            resp = base._chat_once(llm, messages, tools, run_id, provider, profile["model"])
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
                    requested_sources.append(source)
                    if tc.name == "request_fixture":
                        outcome = handle_request_fixture(
                            source=source,
                            args=args,
                            state=state,
                            config=config,
                            source_limit=data.SOURCE_LIMIT,
                            lookup=lambda s: data.lookup_source(seed_id, s),
                            unavailable_response=data.UNAVAILABLE_RESPONSE,
                            limit_exceeded_response=data.LIMIT_EXCEEDED_RESPONSE,
                        )
                        content = outcome.content
                        disposition = outcome.disposition
                        executed = outcome.executed
                    else:
                        state.tool_attempt_count += 1
                        content = data.UNAVAILABLE_RESPONSE
                        disposition = "unsupported_tool"
                        executed = False
                    trace.append(
                        {
                            "round": round_index,
                            "name": tc.name,
                            "arguments": args_json,
                            "source": source,
                            "result_head": content[:500],
                            "result_full": content,
                            "action_disposition": disposition,
                            "executed": executed,
                            "tool_attempt_count": state.tool_attempt_count,
                            "tool_execution_count": state.tool_execution_count,
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
                final_answer = resp.content
                rounds_to_final = round_index
                break
        else:
            status = "ROUND_LIMIT"
            rounds_to_final = base.MAX_ROUNDS
    except LLMError as exc:
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    finally:
        stats["latency_s"] = round(time.monotonic() - t0, 3)
        if not dry and llm_override is None:
            with contextlib.suppress(Exception):  # close 失败不影响结果
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
        # Compatibility alias: requested_count is model attempts, not executions.
        "requested_count": state.tool_attempt_count,
        "tool_attempt_count": state.tool_attempt_count,
        "tool_execution_count": state.tool_execution_count,
        "duplicate_suppressed_count": state.duplicate_suppressed_count,
        "budget_blocked_count": state.budget_blocked_count,
        "limit_exceeded_count": state.limit_exceeded_count,
        "tool_budget_exhausted": state.tool_budget_exhausted,
        "rounds_to_final": rounds_to_final,
        "guard": {
            "duplicate_suppression": config.duplicate_suppression,
            "budget_terminal": config.budget_terminal,
        },
        "trace": trace,
        "stats": stats,
    }
