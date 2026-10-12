"""Isolated post-run Method self-distillation.

This module never mutates the user-visible final answer. It projects only observable episode
facts (no hidden reasoning_content), asks the same routed model for a compact Method candidate,
and persists only a structured candidate. Failure is always fail-open.
"""
from __future__ import annotations

import json
from collections.abc import Callable
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
    candidate_payload: dict[str, Any] | None = None
    method_discovery_diagnostics: dict[str, Any] | None = None


def friction_facts(*, rounds: int, tool_trace: list[dict[str, Any]], run_end_reason: str) -> dict[str, Any]:
    failures = sum(1 for row in tool_trace if str(row.get("status", "")).lower() not in {"success", "ok"})
    counts: dict[str, int] = {}
    for row in tool_trace:
        key = json.dumps([row.get("name"), row.get("arguments")], ensure_ascii=False, sort_keys=True, default=str)
        counts[key] = counts.get(key, 0) + 1
    duplicate_calls = sum(max(0, n - 1) for n in counts.values())
    return {
        "rounds": int(rounds),
        "tool_calls": len(tool_trace),
        "tool_failures": failures,
        "duplicate_calls": duplicate_calls,
        "run_end_reason": str(run_end_reason),
    }


def should_reflect(*, facts: dict[str, Any], min_rounds: int, min_tools: int, min_failures: int) -> bool:
    return bool(
        int(facts.get("rounds", 0)) >= max(1, min_rounds)
        or int(facts.get("tool_calls", 0)) >= max(1, min_tools)
        or int(facts.get("tool_failures", 0)) >= max(1, min_failures)
        or int(facts.get("duplicate_calls", 0)) >= 2
        or str(facts.get("run_end_reason", "")) in {"stagnation", "max_iterations"}
    )


def _observable_messages(messages: list[Any], *, max_messages: int = 36, max_total_chars: int = 18000) -> list[dict[str, str]]:
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
    return all(isinstance(value.get(k), str) and str(value.get(k)).strip() for k in ("name", "description", "body"))


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


def _call(client: Any, *, system: str, facts_payload: dict[str, Any], timeout_s: float) -> dict[str, Any] | None:
    response = client.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(facts_payload, ensure_ascii=False, sort_keys=True)},
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
    episode_ref: str = "",
    min_rounds: int = 6,
    min_tools: int = 6,
    min_failures: int = 2,
    timeout_s: float = 120.0,
) -> ReflectionOutcome:
    if mode != "auto" or store is None or llm_client is None:
        return ReflectionOutcome(attempted=False, triggered=False, reason="disabled_or_unavailable")
    facts = friction_facts(rounds=rounds, tool_trace=tool_trace, run_end_reason=run_end_reason)
    if not should_reflect(facts=facts, min_rounds=min_rounds, min_tools=min_tools, min_failures=min_failures):
        return ReflectionOutcome(attempted=False, triggered=False, reason="below_mechanical_friction_threshold")
    core = store.get("method:method-self-distill")
    if core is None:
        return ReflectionOutcome(attempted=False, triggered=True, reason="self_distill_method_missing")
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
        "return {\"decision\":\"none\",\"reason\":\"...\"}. If there is one, return decision=candidate with name, description, body. "
        "The body must include trigger/discriminator/short_path/stop_conditions/verification/counterexamples and must not copy task-private literals unless necessary.\n\n"
        + core.body
    )
    try:
        value = _call(llm_client, system=system, facts_payload=payload, timeout_s=timeout_s)
        if value and value.get("decision") == "none":
            return ReflectionOutcome(attempted=True, triggered=True, reason=str(value.get("reason", "no_reusable_method"))[:300])
        used_teacher = False
        teacher_refs: list[str] = []
        if not _valid_candidate(value):
            teacher, teacher_refs = _teacher_text(store)
            if not teacher:
                return ReflectionOutcome(attempted=True, triggered=True, reason="invalid_candidate_no_teacher")
            used_teacher = True
            value = _call(
                llm_client,
                system=system + "\n\nTeacher exemplars teach abstraction style only; do not copy their concrete answers:\n" + teacher,
                facts_payload=payload,
                timeout_s=timeout_s,
            )
        if not _valid_candidate(value):
            return ReflectionOutcome(attempted=True, triggered=True, used_teacher_fallback=used_teacher, reason="invalid_candidate")
        candidate = cast(dict[str, Any], value)
        record = store.save_candidate(
            name=str(candidate["name"]),
            description=str(candidate["description"]),
            body=str(candidate["body"]),
            source_model=source_model,
            teacher_refs=teacher_refs if used_teacher else [],
            source_episode_refs=[episode_ref] if episode_ref.startswith("episode:") else [],
        )
        return ReflectionOutcome(attempted=True, triggered=True, saved_ref=record.method_ref, used_teacher_fallback=used_teacher, reason="candidate_saved")
    except Exception as exc:  # noqa: BLE001 - post-run learning must never break the user run
        return ReflectionOutcome(attempted=True, triggered=True, reason=f"reflection_failed:{type(exc).__name__}")


# ---------------------------------------------------------------------------
# Learning Plane: episode-driven reflection (session-decoupled)
# ---------------------------------------------------------------------------

def build_episode_material(
    entry: dict[str, Any] | None,
    *,
    max_total_chars: int = 18000,
) -> list[dict[str, str]]:
    """Project one durable episode snapshot into visible observation rows.

    Episode snapshots already exclude hidden reasoning_content, so this is a
    pure projection of visible facts for exactly one user turn. When the char
    budget forces truncation the first user row and the final assistant row
    are always kept; middle rows are dropped.
    """
    rows: list[dict[str, str]] = []
    if not isinstance(entry, dict):
        return rows
    messages = entry.get("messages") or []
    visible = [
        {"role": str(m.get("role", "")), "content": str(m.get("content", "") or "")}
        for m in messages
        if str(m.get("role", "")) in {"user", "assistant", "tool"} and str(m.get("content", "") or "").strip()
    ]
    if not visible:
        return rows
    reserved = visible[0] if visible[0]["role"] == "user" else None
    tail = visible[-1] if visible[-1]["role"] == "assistant" else None

    def _budgeted(items: list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        remaining = max_total_chars
        for row in items:
            chunk = row["content"][: min(1800, remaining)]
            if not chunk:
                break
            out.append({"role": row["role"], "content": chunk})
            remaining -= len(chunk)
        return out

    body = [m for m in visible if m is not reserved and m is not tail]
    kept = _budgeted(body)
    head = [reserved] if reserved else []
    tail_rows = [tail] if tail else []
    rows = head + kept + tail_rows
    if sum(len(r["content"]) for r in rows) > max_total_chars and kept:
        kept = _budgeted(kept[: max(0, len(kept) - 1)])
        rows = head + kept + tail_rows
    return rows


_CANDIDATE_LIST_FIELDS = ("short_path", "stop_conditions", "verification", "counterexamples")


def validate_candidate(value: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Mechanical closed-schema check: fields exist, types correct, lengths legal.

    This validates record format completeness only; it never judges whether the
    content is smart. That judgment stays with the model.
    """
    errors: list[str] = []
    if not isinstance(value, dict):
        return False, ["payload must be a JSON object"]
    if value.get("decision") != "candidate":
        return False, ["decision must be 'candidate'"]
    for key, limit in (("name", 96), ("description", 600)):
        field = value.get(key)
        if not isinstance(field, str) or not field.strip():
            errors.append(f"{key} must be a non-empty string")
        elif len(field) > limit:
            errors.append(f"{key} exceeds {limit} chars")
    for key in ("trigger", "discriminator"):
        field = value.get(key)
        if not isinstance(field, str) or not field.strip():
            errors.append(f"{key} must be a non-empty string")
        elif len(field) > 2000:
            errors.append(f"{key} exceeds 2000 chars")
    for key in _CANDIDATE_LIST_FIELDS:
        items = value.get(key)
        if not isinstance(items, list) or not items:
            errors.append(f"{key} must be a non-empty list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{key}[{i}] must be a non-empty string")
    return (not errors), errors


def render_candidate_body(value: dict[str, Any]) -> str:
    """Mechanically render a validated candidate payload into a Method body."""
    def section(title: str, content: Any) -> str:
        if isinstance(content, list):
            lines = [f"- {str(item).strip()}" for item in content if str(item).strip()]
            return f"## {title}\n" + ("\n".join(lines) if lines else "(none)") + "\n"
        text = str(content or "").strip()
        return f"## {title}\n{text}\n" if text else f"## {title}\n(none)\n"

    return "\n".join(
        [
            section("Trigger", value.get("trigger", "")),
            section("Discriminator", value.get("discriminator", "")),
            section("Short path", value.get("short_path", [])),
            section("Stop conditions", value.get("stop_conditions", [])),
            section("Verification", value.get("verification", [])),
            section("Counterexamples", value.get("counterexamples", [])),
        ]
    )


_MAX_EXISTING_BRIEFS = 30
_BRIEF_DESC_CHARS = 110
_DEDUP_STATUSES = frozenset({"active", "qualified"})
_METHOD_DISCOVERY_LIMIT = 6
_METHOD_DISCOVERY_QUERY_CHARS = 1200
_METHOD_QUERY_USER_CHARS = 760
_METHOD_QUERY_ASSISTANT_CHARS = 280
_METHOD_QUERY_TRIGGER_CHARS = 320

MethodDiscovery = Callable[
    [str, int], tuple[list[dict[str, Any]], dict[str, Any] | None]
]


def _existing_method_briefs(store: MethodStore) -> list[str]:
    """One-line briefs of active/qualified methods as a reflection dedup gate.

    Injected into the reflection payload so the model can short-circuit
    semantic duplicates to decision=none. Byte-level idempotence in
    MethodStore only blocks identical bodies; near-identical rewrites mint
    new ids (different content hash) and both waste reflection tokens and
    grow the pool with redundant cards (2026-09-24). Fail-open: an empty list
    degrades to pre-existing behaviour, never blocks reflection.
    """
    briefs: list[str] = []
    try:
        for card in store.list(query="", limit=200):
            if str(card.get("status") or "") not in _DEDUP_STATUSES:
                continue
            desc = str(card.get("description") or "").strip().replace("\n", " ")
            briefs.append(f"{card.get('id')} — {desc[:_BRIEF_DESC_CHARS]}")
            if len(briefs) >= _MAX_EXISTING_BRIEFS:
                break
    except Exception:  # noqa: BLE001 — 清单不可得时反思照常进行
        return []
    return briefs


def _method_discovery_query(
    material: list[dict[str, str]],
    trigger_facts: dict[str, Any],
    final_answer: str,
) -> str:
    """Build a bounded semantic query from durable, model-visible facts only.

    ``material`` is already projected by :func:`build_episode_material`, which excludes
    hidden reasoning.  Keep the query task-shaped rather than dumping the whole episode:
    user intent dominates, trigger facts provide failure/context discriminators, and a
    small final-outcome preview helps distinguish otherwise similar tasks.
    """
    user_text = "\n".join(
        str(row.get("content") or "").strip()
        for row in material
        if str(row.get("role") or "") == "user"
    )[:_METHOD_QUERY_USER_CHARS]
    assistant_text = str(final_answer or "").strip()
    if not assistant_text:
        for row in reversed(material):
            if str(row.get("role") or "") == "assistant":
                assistant_text = str(row.get("content") or "").strip()
                break
    assistant_text = assistant_text[:_METHOD_QUERY_ASSISTANT_CHARS]
    trigger_text = json.dumps(
        trigger_facts or {}, ensure_ascii=False, sort_keys=True, default=str
    )[:_METHOD_QUERY_TRIGGER_CHARS]
    parts = [
        f"task: {user_text}" if user_text else "",
        f"friction: {trigger_text}" if trigger_text and trigger_text != "{}" else "",
        f"outcome: {assistant_text}" if assistant_text else "",
    ]
    return "\n".join(part for part in parts if part)[:_METHOD_DISCOVERY_QUERY_CHARS]


def _related_method_projection(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project discovery cards into a compact advisory model-visible shape.

    Only active/qualified Methods may influence the duplicate/reuse context.  Discovery
    never asserts applicability; that remains an explicit model judgment grounded in the
    current episode.
    """
    result: list[dict[str, str]] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status not in _DEDUP_STATUSES:
            continue
        ref = str(row.get("key") or row.get("ref") or "")
        if not ref:
            method_id = str(row.get("id") or "")
            ref = f"method:{method_id}" if method_id else ""
        if not ref:
            continue
        result.append(
            {
                "ref": ref,
                "status": status,
                "name": str(row.get("summary") or row.get("name") or "")[:120],
                "description": str(row.get("description") or "")[:360],
                "task_applicability": str(
                    row.get("task_applicability") or "not_evaluated"
                ),
            }
        )
        if len(result) >= _METHOD_DISCOVERY_LIMIT:
            break
    return result


def _discover_related_methods(
    method_discovery: MethodDiscovery | None,
    *,
    material: list[dict[str, str]],
    trigger_facts: dict[str, Any],
    final_answer: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if method_discovery is None:
        return [], {"semantic_requested": False, "semantic_effective": False}
    query = _method_discovery_query(material, trigger_facts, final_answer)
    if not query:
        return [], {
            "semantic_requested": False,
            "semantic_effective": False,
            "semantic_fallback_reason": "empty_observable_query",
        }
    try:
        rows, raw_diag = method_discovery(query, _METHOD_DISCOVERY_LIMIT)
    except Exception as exc:  # noqa: BLE001 - background learning discovery is fail-open
        return [], {
            "semantic_requested": True,
            "semantic_effective": False,
            "semantic_fallback_reason": f"discovery_error:{type(exc).__name__}",
        }
    diag = dict(raw_diag or {})
    safe_diag: dict[str, Any] = {
        "semantic_requested": bool(diag.get("semantic_requested", True)),
        "semantic_effective": bool(diag.get("semantic_effective", False)),
    }
    for key in (
        "scope",
        "semantic_fallback_reason",
        "semantic_latency_ms",
        "query_embedding_ms",
        "semantic_hit_count",
        "keyword_hit_count",
        "fused_hit_count",
        "candidate_missing_count",
        "canonical_hydration_failures",
        "empty_render_count",
        "prewarm_scheduled",
    ):
        if key in diag:
            safe_diag[key] = diag[key]
    related = _related_method_projection(list(rows or []))
    safe_diag["related_method_count"] = len(related)
    return related, safe_diag


def reflect_on_episode(
    *,
    llm_client: Any,
    store: MethodStore | None,
    episode_entry: dict[str, Any] | None,
    trigger_facts: dict[str, Any],
    tool_trace: list[dict[str, Any]],
    run_end_reason: str,
    final_answer: str,
    timeout_s: float = 120.0,
    max_material_chars: int = 18000,
    method_discovery: MethodDiscovery | None = None,
) -> ReflectionOutcome:
    """Run reflection over exactly one durable episode; do NOT persist anything.

    Returns a validated candidate payload in the outcome; the caller
    (ReflectionRun on the Learning Plane) supplies runtime provenance and
    performs the only write via MethodStore.save_candidate.
    """
    if store is None or llm_client is None:
        return ReflectionOutcome(attempted=False, triggered=True, reason="disabled_or_unavailable")
    core = store.get("method:method-self-distill")
    if core is None:
        return ReflectionOutcome(attempted=False, triggered=True, reason="self_distill_method_missing")
    material = build_episode_material(episode_entry, max_total_chars=max_material_chars)
    if not material:
        return ReflectionOutcome(attempted=False, triggered=True, reason="episode_material_empty")
    related_methods, method_diag = _discover_related_methods(
        method_discovery,
        material=material,
        trigger_facts=trigger_facts,
        final_answer=final_answer,
    )
    payload = {
        "observable_friction": trigger_facts,
        "episode_material": material,
        "tool_trace": tool_trace[-40:],
        "final_outcome": {"reason": run_end_reason, "answer_preview": final_answer[:800]},
        # 防重复门（2026-09-24）：方法池 active/qualified 卡一行摘要；语义重复 → none
        "existing_methods": _existing_method_briefs(store),
        # Learning semantic Method discovery is advisory context only. Applicability is
        # deliberately not evaluated by retrieval; the model must compare it to this episode.
        "related_methods": related_methods,
        "method_discovery": method_diag,
        "output_contract": {
            "decision": "candidate|none",
            "candidate_fields": {
                "name": "string <= 96 chars",
                "description": "string <= 600 chars",
                "trigger": "string",
                "discriminator": "string",
                "short_path": "non-empty list of strings",
                "stop_conditions": "non-empty list of strings",
                "verification": "non-empty list of strings",
                "counterexamples": "non-empty list of strings",
            },
            "none_reason": "short string",
        },
    }
    system = (
        "You are performing isolated post-task Method self-distillation on the Learning Plane. "
        "Never reveal or reconstruct hidden chain-of-thought. Use only the observable facts of this "
        "single episode supplied by the caller. Return exactly one JSON object following the output_contract. "
        'If there is no reusable method, return {"decision":"none","reason":"..."}. If there is one, return '
        "decision=candidate with ALL required fields (name, description, trigger, discriminator, short_path, "
        "stop_conditions, verification, counterexamples). Do not copy task-private literals unless necessary.\n"
        "existing_methods lists the current pool's active/qualified cards. If the method you would distil "
        "is a semantic duplicate of any listed entry (same trigger and mechanism, cosmetic rewording), "
        'return {"decision":"none","reason":"dup:<that method id>"} instead of minting a redundant card; '
        "candidate is for genuinely new discriminators only.\n"
        "related_methods is a bounded retrieval hint for this episode. Its task_applicability is explicitly "
        "not_evaluated: compare the trigger/discriminator against the observable episode yourself; do not "
        "treat retrieval rank as authority. If one is the same reusable mechanism, return dup:<ref>.\n\n"
        + core.body
    )
    try:
        value = _call(llm_client, system=system, facts_payload=payload, timeout_s=timeout_s)
    except Exception:  # noqa: BLE001 - Learning Plane failures never reach the user session
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            reason="reflection_call_failed",
            method_discovery_diagnostics=method_diag,
        )
    if value is None:
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            reason="reflection_model_not_json",
            method_discovery_diagnostics=method_diag,
        )
    if value.get("decision") != "candidate":
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            reason=str(value.get("reason", "none"))[:200],
            method_discovery_diagnostics=method_diag,
        )
    ok, errors = validate_candidate(value)
    if not ok:
        return ReflectionOutcome(
            attempted=True,
            triggered=True,
            reason="candidate_schema_invalid: " + "; ".join(errors[:6]),
            method_discovery_diagnostics=method_diag,
        )
    value["body"] = render_candidate_body(value)
    return ReflectionOutcome(
        attempted=True,
        triggered=True,
        reason="schema_ok",
        candidate_payload=value,
        method_discovery_diagnostics=method_diag,
    )
