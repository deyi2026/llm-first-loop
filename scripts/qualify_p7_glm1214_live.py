#!/usr/bin/env python3
"""P7 privacy-safe live GLM-5.3 qualification for the ERR1214 ingress boundary.

The runner intentionally does not persist raw prompts, raw answers, provider bodies,
or credential values.  It replays the frozen *shape* of the production delegated
compaction incident through the current history projector and production LLMClient.

Success is purely mechanical: compaction happened; exactly one delegated active-run
ingress remains; tool declarations/results are paired; final provider validation strips
the internal ingress marker; and the real provider accepts the first request without an
HTTP/projection error.  Model answer quality is not a gate.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_loop.config import load_env_file, load_settings  # noqa: E402
from llm_loop.core.history import validate_tool_call_pairing  # noqa: E402
from llm_loop.core.message import Message, MessageSource, ToolResultStatus  # noqa: E402
from llm_loop.core.prompt_build.stages.history_projection import (  # noqa: E402
    run_history_projection,
)
from llm_loop.llm.client import (  # noqa: E402
    GuardRequestContext,
    LLMClient,
    provider_structure_violations,
)
from llm_loop.llm.errors import (  # noqa: E402
    LLMHTTPError,
    LLMProjectionError,
    parse_provider_error_code,
)
from llm_loop.llm.pool import ModelClientPool  # noqa: E402
from llm_loop.llm.providers import load_registry  # noqa: E402


class _CacheMonitor:
    force_head_keep = False

    @staticmethod
    def breaker_freeze_compression(_session_id: str) -> bool:
        return False


def _fixture_messages(fixture: dict[str, Any], trial: int) -> tuple[list[Message], int]:
    ingress_spec = fixture["ingress"]
    ingress_seq = int(ingress_spec["msg_seq"])
    rows = fixture["archived_span"]
    base: list[Message] = []
    current_turn_ref = -1
    active_calls: list[str] = []

    # One old assistant row recreates the follow-up shape where compaction can retire
    # surrounding history but must never retire the current delegated ingress.
    base.append(Message(role="assistant", content="H" * 170, source=MessageSource.USER))

    for row in rows:
        role = str(row["role"])
        seq = int(row["msg_seq"])
        content_len = int(row.get("content_chars") or 0)
        if role == "user":
            # Keep the exact production length while making the live prompt synthetic.
            prefix = f"P7-DELEGATED-LIVE-{trial}-Reply P7-OK only. FILLER:"
            content = (prefix + ("X" * max(0, content_len - len(prefix))))[:content_len]
            metadata = dict(ingress_spec["metadata"]) if seq == ingress_seq else {}
            message = Message(
                role="user",
                content=content,
                source=MessageSource.USER,
                metadata=metadata,
            )
            base.append(message)
            if seq == ingress_seq:
                current_turn_ref = len(base) - 1
            active_calls = []
            continue
        if role == "assistant":
            content = "A" * content_len
            count = int(row.get("tool_call_count") or 0)
            active_calls = [f"p7-{trial}-{seq}-{ordinal}" for ordinal in range(count)]
            base.append(
                Message(
                    role="assistant",
                    content=content,
                    source=MessageSource.USER,
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps(
                                    {"path": f"synthetic-{trial}-{seq}.txt"},
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for call_id in active_calls
                    ],
                )
            )
            continue
        ordinal = int(row["tool_result_ordinal"])
        call_id = active_calls[ordinal]
        base.append(
            Message(
                role="tool",
                content="R" * content_len,
                source=MessageSource.TOOL,
                tool_call_id=call_id,
                tool_name="read_file",
                status=ToolResultStatus.SUCCESS,
            )
        )

    if current_turn_ref < 0:
        raise RuntimeError("fixture missing delegated active ingress")
    return base, current_turn_ref


def _project(
    fixture: dict[str, Any], trial: int, history_budget: int
) -> tuple[list[dict], str, dict[str, Any]]:
    base, current_turn_ref = _fixture_messages(fixture, trial)
    archived: list[Message] = []
    session_id = f"p7-glm-live-{trial}"
    projection = run_history_projection(
        base=base,
        system_prompt="P7 mechanical context-integrity qualification.",
        filtered_indices=list(range(len(base))),
        sess_anchor=0,
        prefix_len=0,
        session_id=session_id,
        max_chars=history_budget,
        runtime_history_budget_value=history_budget,
        compact_ratio=0.85,
        archive_sink=lambda _sid, message: archived.append(message),
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=None,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=history_budget,
        current_turn_ref=current_turn_ref,
    )
    marked = [m for m in projection.built if m.get("_active_run_ingress_ref")]
    if len(marked) != 1:
        raise RuntimeError(f"active ingress marker count={len(marked)}")
    active_ref = str(marked[0]["_active_run_ingress_ref"])
    pairing = validate_tool_call_pairing(projection.built)
    if pairing:
        raise RuntimeError(f"tool pairing violations={pairing}")
    compacted = bool(projection.compacted_box and projection.compacted_box[0])
    if not compacted or not archived:
        raise RuntimeError("qualification shape did not actually compact history")
    retained_tool_results = sum(m.get("role") == "tool" for m in projection.built)
    retained_tool_declarations = sum(
        len(m.get("tool_calls") or [])
        for m in projection.built
        if m.get("role") == "assistant"
    )
    summary = {
        "source_message_count": len(base),
        "projected_message_count": len(projection.built),
        "projected_roles": [str(m.get("role") or "") for m in projection.built],
        "compacted": compacted,
        "archived_count": len(archived),
        "compacted_source_count": len(projection.cache_compacted_source_box),
        "active_marker_count": len(marked),
        "tool_pairing_violations": 0,
        "retained_tool_results": retained_tool_results,
        "retained_tool_declarations": retained_tool_declarations,
        "anchor_after": projection.anchor_box[0] if projection.anchor_box else None,
    }
    return list(projection.built), active_ref, summary


def _tool_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a synthetic qualification file if needed.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def _safe_error(exc: BaseException, elapsed_s: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "result_kind": "error",
        "error_type": type(exc).__name__,
        "elapsed_s": round(elapsed_s, 3),
    }
    if isinstance(exc, LLMHTTPError):
        row["status_code"] = int(exc.status_code)
        row["provider_code"] = parse_provider_error_code(exc.body)
    if isinstance(exc, LLMProjectionError):
        row["violations"] = list(exc.violations)
    return row


def _wire_summary(payload: object) -> dict[str, Any]:
    """Return privacy-safe facts about the exact outbound JSON body."""
    body = payload if isinstance(payload, dict) else {}
    messages = body.get("messages") if isinstance(body, dict) else None
    wire_messages = messages if isinstance(messages, list) else []
    roles = [
        str(message.get("role") or "")
        for message in wire_messages
        if isinstance(message, dict)
    ]
    internal_marker_count = sum(
        1
        for message in wire_messages
        if isinstance(message, dict) and "_active_run_ingress_ref" in message
    )
    provider_replay_key_count = sum(
        1
        for message in wire_messages
        if isinstance(message, dict) and "_provider_replay" in message
    )
    delegated_probe_count = sum(
        1
        for message in wire_messages
        if isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and message["content"].startswith("P7-DELEGATED-LIVE-")
    )
    violations = provider_structure_violations(wire_messages)
    return {
        "message_count": len(wire_messages),
        "roles": roles,
        "internal_marker_count": internal_marker_count,
        "provider_replay_key_count": provider_replay_key_count,
        "delegated_probe_count": delegated_probe_count,
        "tool_pairing_violations": list(violations),
    }


def _install_wire_probe(client: LLMClient, sink: list[dict[str, Any]]) -> None:
    """Observe exact physical request JSON without retaining content or credentials."""
    original_stream = client._client.stream  # noqa: SLF001

    def probed_stream(*args: Any, **kwargs: Any):
        sink.append(_wire_summary(kwargs.get("json")))
        return original_stream(*args, **kwargs)

    client._client.stream = probed_stream  # type: ignore[method-assign]  # noqa: SLF001


def _make_pool(model_providers_raw: str) -> tuple[ModelClientPool, str]:
    # load_settings is used only for existing parsing/defaults.  The temporary data dir
    # prevents accidental qualification writes to production state, while provider
    # contracts are pinned to the tracked registry bytes passed via MODEL_PROVIDERS.
    temp_dir = tempfile.mkdtemp(prefix="lfl-p7-glm-live-")
    settings = dataclasses.replace(
        load_settings(),
        data_dir=temp_dir,
        model_providers_raw=model_providers_raw,
    )
    registry = load_registry(settings)
    default = LLMClient(
        api_key="",
        base_url="http://127.0.0.1:1",
        model="qualification-default",
        timeout_s=5.0,
        max_tokens=512,
        guard_enabled=False,
    )
    return (
        ModelClientPool(
            registry=registry,
            default_client=default,
            base_timeout_s=180.0,
            base_max_tokens=512,
        ),
        temp_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument(
        "--fixture", default=str(ROOT / "tests/fixtures/err1214_delegated_compaction_v1.json")
    )
    parser.add_argument("--providers", default=str(ROOT / "data/providers.json"))
    parser.add_argument("--model", default="glm/glm-5.3")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--history-budget", type=int, default=2_400)
    parser.add_argument("--min-retained-tool-results", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    load_env_file(args.env_file)
    fixture_path = Path(args.fixture)
    providers_path = Path(args.providers)
    fixture_bytes = fixture_path.read_bytes()
    provider_bytes = providers_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    model_providers_raw = provider_bytes.decode("utf-8")

    result: dict[str, Any] = {
        "schema": "p7-glm1214-live/v1",
        "model": args.model,
        "trials_requested": int(args.trials),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "providers_sha256": hashlib.sha256(provider_bytes).hexdigest(),
        "credentials_redacted": True,
        "raw_prompts_persisted": False,
        "raw_answers_persisted": False,
        "raw_provider_bodies_persisted": False,
        "rows": [],
    }
    pool, temp_dir = _make_pool(model_providers_raw)
    wire_summaries: list[dict[str, Any]] = []
    try:
        client, provider_id, model_id = pool.get_resolved_client(args.model)
        _install_wire_probe(client, wire_summaries)
        client.guard_enabled = False
        client.max_tokens = max(1, int(args.max_tokens))
        for trial in range(1, int(args.trials) + 1):
            messages, active_ref, projection = _project(
                fixture, trial, max(1, int(args.history_budget))
            )
            structure_events: list[dict[str, Any]] = []
            guard = GuardRequestContext(
                session_id=f"p7-glm-live-{trial}",
                history_budget=max(1, int(args.history_budget)),
                run_round=trial,
                provider=provider_id,
                model=model_id,
                active_run_ingress_ref=active_ref,
                active_run_ingress_kind="delegated",
                structure_state_hook=lambda state, _events=structure_events: _events.append(
                    dict(state)
                ),
            )
            wire_start = len(wire_summaries)
            started = time.monotonic()
            try:
                response = client.chat(
                    messages,
                    _tool_schema(),
                    timeout_s=float(args.timeout),
                    model=model_id,
                    guard_context=guard,
                )
                elapsed = time.monotonic() - started
                row = {
                    "trial": trial,
                    "result_kind": "success",
                    "elapsed_s": round(elapsed, 3),
                    "projection": projection,
                    "structure_states": structure_events,
                    "prompt_tokens": int(response.prompt_tokens or 0),
                    "completion_tokens": int(response.completion_tokens or 0),
                    "cache_hit_tokens": int(response.prompt_cache_hit_tokens or 0),
                    "finish_reason": str(response.finish_reason or ""),
                    "truncated": bool(response.truncated),
                    "tool_call_count": len(response.tool_calls or []),
                    "answer_chars": len(str(response.content or "")),
                    "answer_sha256": hashlib.sha256(
                        str(response.content or "").encode("utf-8")
                    ).hexdigest(),
                    "reasoning_chars": len(str(response.reasoning_content or "")),
                }
            except BaseException as exc:  # evidence runner must serialize every failure safely
                row = {
                    "trial": trial,
                    "projection": projection,
                    "structure_states": structure_events,
                    **_safe_error(exc, time.monotonic() - started),
                }
            trial_wire = wire_summaries[wire_start:]
            row["wire"] = {
                "request_count": len(trial_wire),
                "requests": trial_wire,
            }
            result["rows"].append(row)
            print(
                json.dumps(
                    {
                        "trial": trial,
                        "result_kind": row["result_kind"],
                        "elapsed_s": row["elapsed_s"],
                        "status_code": row.get("status_code"),
                        "provider_code": row.get("provider_code"),
                        "prompt_tokens": row.get("prompt_tokens"),
                        "completion_tokens": row.get("completion_tokens"),
                        "finish_reason": row.get("finish_reason"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        with contextlib.suppress(Exception):
            pool.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    rows = list(result["rows"])
    result["qualified"] = bool(
        len(rows) == int(args.trials)
        and rows
        and all(row.get("result_kind") == "success" for row in rows)
        and all((row.get("projection") or {}).get("compacted") is True for row in rows)
        and all((row.get("projection") or {}).get("active_marker_count") == 1 for row in rows)
        and all(
            (row.get("projection") or {}).get("tool_pairing_violations") == 0 for row in rows
        )
        and all(
            int((row.get("projection") or {}).get("retained_tool_results") or 0)
            >= max(0, int(args.min_retained_tool_results))
            for row in rows
        )
        and all(
            int((row.get("projection") or {}).get("retained_tool_declarations") or 0)
            >= max(0, int(args.min_retained_tool_results))
            for row in rows
        )
        and all((row.get("wire") or {}).get("request_count") == 1 for row in rows)
        and all(
            ((row.get("wire") or {}).get("requests") or [{}])[0].get("internal_marker_count") == 0
            for row in rows
        )
        and all(
            ((row.get("wire") or {}).get("requests") or [{}])[0].get("provider_replay_key_count") == 0
            for row in rows
        )
        and all(
            ((row.get("wire") or {}).get("requests") or [{}])[0].get("delegated_probe_count") == 1
            for row in rows
        )
        and all(
            not ((row.get("wire") or {}).get("requests") or [{}])[0].get("tool_pairing_violations")
            for row in rows
        )
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"qualified": result["qualified"], "output": str(output)}), flush=True)
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
