"""Isolated post-run Method self-distillation.

This module never mutates the user-visible final answer. It projects only observable episode
facts (no hidden reasoning_content), asks the same routed model for a compact Method candidate,
and persists only a structured candidate. Failure is always fail-open.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from llm_loop.methods.store import MethodStore


@dataclass(frozen=True)
class ReflectionOutcome:
    attempted: bool
    triggered: bool
    saved_ref: str = ""
    used_teacher_fallback: bool = False
    reason: str = ""


def friction_facts(
    *, rounds: int, tool_trace: list[dict[str, Any]], run_end_reason: str
) -> dict[str, Any]:
    failures = sum(
        1 for row in tool_trace if str(row.get("status", "")).lower() not in {"success", "ok"}
    )
    counts: dict[str, int] = {}
    for row in tool_trace:
        key = json.dumps(
            [row.get("name"), row.get("arguments")], ensure_ascii=False, sort_keys=True, default=str
        )
        counts[key] = counts.get(key, 0) + 1
    duplicate_calls = sum(max(0, n - 1) for n in counts.values())
    return {
        "rounds": int(rounds),
        "tool_calls": len(tool_trace),
        "tool_failures": failures,
        "duplicate_calls": duplicate_calls,
        "run_end_reason": str(run_end_reason),
    }


def should_reflect(
    *, facts: dict[str, Any], min_rounds: int, min_tools: int, min_failures: int
) -> bool:
    return bool(
        int(facts.get("rounds", 0)) >= max(1, min_rounds)
        or int(facts.get("tool_calls", 0)) >= max(1, min_tools)
        or int(facts.get("tool_failures", 0)) >= max(1, min_failures)
        or int(facts.get("duplicate_calls", 0)) >= 2
        or str(facts.get("run_end_reason", "")) in {"stagnation", "max_iterations"}
    )


def _observable_messages(
    messages: list[Any], *, max_messages: int = 36, max_total_chars: int = 18000
) -> list[dict[str, str]]:
    """Mechanical bounded projection; deliberately ignores reasoning_content/provider replay."""
    rows: list[dict[str, str]] = []
    remaining = max_total_chars
    for msg in messages[-max_messages:]:
        role = str(getattr(msg, "role", ""))
        if role == "system":
            continue
        content = str(getattr(msg, "content", "") or "")
        if not content:
            continue
        chunk = content[: min(1800, remaining)]
        if not chunk:
            break
        rows.append({"role": role, "content": chunk})
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return rows


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _valid_candidate(value: dict[str, Any] | None) -> bool:
    if not value or value.get("decision") != "candidate":
        return False
    return all(
        isinstance(value.get(k), str) and str(value.get(k)).strip()
        for k in ("name", "description", "body")
    )


def _teacher_text(store: MethodStore) -> tuple[str, list[str]]:
    chunks: list[str] = []
    refs: list[str] = []
    for card in store.list("", 100):
        if card.get("status") != "teacher":
            continue
        rec = store.get(str(card.get("key", "")))
        if rec is not None:
            refs.append(rec.method_ref)
            chunks.append(f"## {rec.method_ref}\n{rec.body}")
    return "\n\n".join(chunks), refs


def _call(
    client: Any, *, system: str, facts_payload: dict[str, Any], timeout_s: float
) -> dict[str, Any] | None:
    response = client.chat(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(facts_payload, ensure_ascii=False, sort_keys=True),
            },
        ],
        tools=[],
        timeout_s=timeout_s,
        model=None,
    )
    return _extract_json(str(getattr(response, "content", "") or ""))


def reflect_after_run(
    *,
    mode: str,
    llm_client: Any,
    store: MethodStore | None,
    session_id: str,
    messages: list[Any],
    rounds: int,
    tool_trace: list[dict[str, Any]],
    run_end_reason: str,
    final_answer: str,
    source_model: str,
    min_rounds: int = 6,
    min_tools: int = 6,
    min_failures: int = 2,
    timeout_s: float = 120.0,
) -> ReflectionOutcome:
    if mode != "auto" or store is None or llm_client is None:
        return ReflectionOutcome(attempted=False, triggered=False, reason="disabled_or_unavailable")
    facts = friction_facts(rounds=rounds, tool_trace=tool_trace, run_end_reason=run_end_reason)
    if not should_reflect(
        facts=facts, min_rounds=min_rounds, min_tools=min_tools, min_failures=min_failures
    ):
        return ReflectionOutcome(
            attempted=False, triggered=False, reason="below_mechanical_friction_threshold"
        )
    core = store.get("method:method-self-distill")
    if core is None:
        return ReflectionOutcome(
            attempted=False, triggered=True, reason="self_distill_method_missing"
        )
    payload = {
        "observable_friction": facts,
        "episode_messages": _observable_messages(messages),
        "tool_trace": tool_trace[-40:],
        "final_outcome": {"reason": run_end_reason, "answer_preview": final_answer[:800]},
        "output_contract": {
            "decision": "candidate|none",
            "candidate_fields": ["name", "description", "body"],
            "none_reason": "short string",
        },
    }
    system = (
        "You are performing isolated post-task Method self-distillation. Never reveal or reconstruct hidden chain-of-thought. "
        "Use only the observable facts supplied by the caller. Return exactly one JSON object. If there is no reusable method, "
        'return {"decision":"none","reason":"..."}. If there is one, return decision=candidate with name, description, body. '
        "The body must include trigger/discriminator/short_path/stop_conditions/verification/counterexamples and must not copy task-private literals unless necessary.\n\n"
        + core.body
    )
    try:
        value = _call(llm_client, system=system, facts_payload=payload, timeout_s=timeout_s)
        if value and value.get("decision") == "none":
            return ReflectionOutcome(
                attempted=True,
                triggered=True,
                reason=str(value.get("reason", "no_reusable_method"))[:300],
            )
        used_teacher = False
        teacher_refs: list[str] = []
        if not _valid_candidate(value):
            teacher, teacher_refs = _teacher_text(store)
            if not teacher:
                return ReflectionOutcome(
                    attempted=True, triggered=True, reason="invalid_candidate_no_teacher"
                )
            used_teacher = True
            value = _call(
                llm_client,
                system=system
                + "\n\nTeacher exemplars teach abstraction style only; do not copy their concrete answers:\n"
                + teacher,
                facts_payload=payload,
                timeout_s=timeout_s,
            )
        if not _valid_candidate(value):
            return ReflectionOutcome(
                attempted=True,
                triggered=True,
                used_teacher_fallback=used_teacher,
                reason="invalid_candidate",
            )
        candidate = cast(dict[str, Any], value)
        record = store.save_candidate(
            name=str(candidate["name"]),
            description=str(candidate["description"]),
            body=str(candidate["body"]),
            source_model=source_model,
            teacher_refs=teacher_refs if used_teacher else [],
            source_episode_refs=[f"session:{session_id}"],
        )
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            saved_ref=record.method_ref,
            used_teacher_fallback=used_teacher,
            reason="candidate_saved",
        )
    except Exception as exc:  # noqa: BLE001 - post-run learning must never break the user run
        return ReflectionOutcome(
            attempted=True, triggered=True, reason=f"reflection_failed:{type(exc).__name__}"
        )
