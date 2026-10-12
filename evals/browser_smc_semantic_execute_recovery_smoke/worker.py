#!/usr/bin/env python3
"""One fresh LFL A2 run with semantic_execute + mechanically typed waits."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from protocol import ARMS, MODEL_REF  # noqa: E402

from evals.browser_smc_semantic_execute_recovery_smoke.observations import atomic_json  # noqa: E402

_TYPED_WAIT_TOOLS = {
    "browser_wait_scope_url",
    "browser_wait_scope_ready",
    "browser_wait_scope_count",
    "browser_wait_object_state",
    "browser_wait_object_text",
}
_OLD_GENERIC_WAIT_TOOLS = {"browser_wait_scope", "browser_wait_object"}
_WAIT_REQUIRED = {
    "browser_wait_scope_url": {
        "scope_ref",
        "operator",
        "value",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_scope_ready": {
        "scope_ref",
        "state",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_scope_count": {
        "scope_ref",
        "operator",
        "count",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_object_state": {
        "object_ref",
        "property",
        "value",
        "timeout_ms",
        "interval_ms",
    },
    "browser_wait_object_text": {
        "object_ref",
        "property",
        "operator",
        "value",
        "timeout_ms",
        "interval_ms",
    },
}


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    return str(exc).replace(str(Path.cwd()), "<run_dir>").replace(str(REPO), "<repo>")[:500]


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return dict(value) if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _target_ref_kind(value: str) -> str:
    if value.endswith("/resource/page"):
        return "resource"
    if "/object/" in value:
        return "object"
    return "other"


def _safe_tool_trace(
    trace: list[dict[str, Any]], arm: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {
        "smc_perceive": 0,
        "semantic_execute": 0,
        "mutation_failures": 0,
        "typed_wait": 0,
        "typed_wait_failures": 0,
        "old_generic_wait": 0,
        "legacy_perceive_wait": 0,
        "snapshot_predicate": 0,
        "get_tool_schema": 0,
    }
    mutation_tool = str(ARMS[arm]["mutation_tool"])
    for index, call in enumerate(trace, start=1):
        name = str(call.get("name") or "")
        args = _parse_args(call.get("arguments"))
        status = str(call.get("status") or "")
        row: dict[str, Any] = {
            "index": index,
            "name": name,
            "status": status,
            "arg_keys": sorted(args),
            "args_sha256": _sha(args),
            "args_chars": len(json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)),
        }
        if name == "browser_perceive":
            counts["smc_perceive"] += 1
            row["action"] = str(args.get("action") or "")
            row["has_predicate"] = "predicate" in args
            counts["legacy_perceive_wait"] += int(row["action"] == "wait")
            counts["snapshot_predicate"] += int(
                row["action"] == "snapshot" and row["has_predicate"]
            )
        elif name in _TYPED_WAIT_TOOLS:
            counts["typed_wait"] += 1
            counts["typed_wait_failures"] += int(status != "success")
            row["structurally_complete"] = set(args) == _WAIT_REQUIRED[name]
            ref_key = "scope_ref" if name.startswith("browser_wait_scope_") else "object_ref"
            ref = str(args.get(ref_key) or "")
            row["ref_kind"] = (
                "scope"
                if ref.startswith("browser-")
                else "object"
                if "/object/" in ref
                else "other"
            )
            if name == "browser_wait_scope_url":
                row["property"] = "url"
                row["operator"] = str(args.get("operator") or "")
                value = args.get("value")
            elif name == "browser_wait_scope_ready":
                row["property"] = "document_ready_state"
                row["operator"] = "eq"
                value = args.get("state")
            elif name == "browser_wait_scope_count":
                row["property"] = "object_count"
                row["operator"] = str(args.get("operator") or "")
                value = args.get("count")
            elif name == "browser_wait_object_state":
                row["property"] = str(args.get("property") or "")
                row["operator"] = "eq"
                value = args.get("value")
            else:
                row["property"] = str(args.get("property") or "")
                row["operator"] = str(args.get("operator") or "")
                value = args.get("value")
            row["value_type"] = type(value).__name__
        elif name in _OLD_GENERIC_WAIT_TOOLS:
            counts["old_generic_wait"] += 1
        elif name == "browser_semantic_execute":
            counts["semantic_execute"] += 1
            row["verb"] = str(args.get("verb") or "")
            row["target_ref_kind"] = _target_ref_kind(str(args.get("target_ref") or ""))
            verb_args = args.get("args")
            row["verb_arg_keys"] = sorted(verb_args) if isinstance(verb_args, dict) else []
        elif name == "get_tool_schema":
            counts["get_tool_schema"] += 1
        if name == mutation_tool and status != "success":
            counts["mutation_failures"] += 1
        rows.append(row)
    return rows, counts


def _wait_message_facts(data_dir: Path, session_id: str) -> dict[str, Any]:
    path = data_dir / "event_logs" / f"{session_id}.jsonl"
    facts: dict[str, Any] = {
        "missing_predicate_failure_count": 0,
        "scope_target_mismatch_failure_count": 0,
        "typed_wait_results": [],
    }
    if not path.is_file():
        return facts
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message.appended":
            continue
        payload = event.get("payload") or {}
        if payload.get("role") != "tool":
            continue
        tool_name = str(payload.get("tool_name") or "")
        content = str(payload.get("content") or "")
        lowered = content.lower()
        facts["missing_predicate_failure_count"] += int(
            "predicate must be a structured object" in lowered or "predicate 必须" in content
        )
        facts["scope_target_mismatch_failure_count"] += int(
            "scope predicate target must equal its exact scope_ref" in lowered
        )
        if tool_name not in _TYPED_WAIT_TOOLS:
            continue
        parsed: dict[str, Any] = {}
        pos = content.find("{")
        if pos >= 0:
            try:
                value = json.loads(content[pos:])
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                pass
        predicate_result = parsed.get("predicate_result") or {}
        observation = parsed.get("observation") or {}
        predicate = parsed.get("predicate") or {}
        facts["typed_wait_results"].append(
            {
                "tool": tool_name,
                "status": str(payload.get("status") or ""),
                "result": str(predicate_result.get("result") or ""),
                "sample_count": int(predicate_result.get("sample_count") or 0),
                "observer_error_count": int(predicate_result.get("observer_error_count") or 0),
                "observation_reason": observation.get("reason"),
                "predicate_value_type": type(predicate.get("value")).__name__,
            }
        )
    return facts


def _partial_pressure_facts(data_dir: Path, session_id: str) -> dict[str, Any]:
    """E-diagnostics from the session event log only (schema verified 2026-09-13).

    llm.partial_checkpoint payload: round, partial_sha256, tool_call_draft_count, ...
    tool.execution.declared payload: round, tool_name, args_sha256, ...
    """
    path = data_dir / "event_logs" / f"{session_id}.jsonl"
    facts: dict[str, Any] = {
        "partial_checkpoint_count": 0,
        "partial_checkpoint_top_repeat": 0,
        "max_partial_sha256_duplicate": 0,
        "partial_checkpoint_peak_tool_draft_count": 0,
        "decided_but_not_dispatched_rounds": 0,
        "partial_only_loop_rounds": 0,
    }
    if not path.is_file():
        return facts
    dispatched_rounds: set[int] = set()
    drafted_rounds: set[int] = set()
    last_sha: str | None = None
    run_len = 0
    top_repeat = 0
    sha_counts: collections.Counter[str] = collections.Counter()
    per_round_partials: collections.Counter[int] = collections.Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        payload = event.get("payload") or {}
        if etype == "llm.partial_checkpoint":
            facts["partial_checkpoint_count"] += 1
            drafts = int(payload.get("tool_call_draft_count") or 0)
            if drafts > facts["partial_checkpoint_peak_tool_draft_count"]:
                facts["partial_checkpoint_peak_tool_draft_count"] = drafts
            if isinstance(payload.get("round"), int):
                rd = payload["round"]
                per_round_partials[rd] += 1
                if drafts > 0:
                    drafted_rounds.add(rd)
            sha = payload.get("partial_sha256")
            if sha:
                sha_counts[sha] += 1
                if sha == last_sha:
                    run_len += 1
                else:
                    last_sha = sha
                    run_len = 1
                top_repeat = max(top_repeat, run_len)
        elif etype == "tool.execution.declared":
            if isinstance(payload.get("round"), int):
                dispatched_rounds.add(payload["round"])
    facts["partial_checkpoint_top_repeat"] = top_repeat
    facts["max_partial_sha256_duplicate"] = max(sha_counts.values()) if sha_counts else 0
    facts["decided_but_not_dispatched_rounds"] = len(drafted_rounds - dispatched_rounds)
    # Row4-class generation stall: long reasoning-only partial stream in one
    # round with no committed draft and no dispatched tool call (>=10 partials).
    facts["partial_only_loop_rounds"] = sum(
        1
        for rd, count in per_round_partials.items()
        if count >= 10 and rd not in drafted_rounds and rd not in dispatched_rounds
    )
    return facts


def _receipt_facts(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "browser_action"
    terminal: list[dict[str, Any]] = []
    retry_true = 0
    scope_blockers = 0
    reason_counts: dict[str, int] = {}
    if root.is_dir():
        for path in root.rglob("receipts.jsonl"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                retry = doc.get("retry") or {}
                completeness = doc.get("completeness") or {}
                reasons = [str(reason) for reason in (completeness.get("reasons") or [])]
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                scope_blockers += sum(
                    "version_scope_mismatch" in reason
                    or "different_snapshot_same_generation" in reason
                    or "expected_version_unavailable" in reason
                    or "resource_scope_mismatch" in reason
                    for reason in reasons
                )
                retry_true += int(retry.get("automatic_retry_performed") is True)
                if doc.get("status") in {"ok", "failed", "rejected"}:
                    terminal.append(
                        {
                            "status": doc.get("status"),
                            "verb": doc.get("verb"),
                            "completeness_reasons": reasons,
                        }
                    )
    return {
        "terminal_count": len(terminal),
        "automatic_retry_true_count": retry_true,
        "ok_count": sum(row["status"] == "ok" for row in terminal),
        "object_ok_count": sum(
            row["status"] == "ok" and row["verb"] in {"click", "fill", "select", "scroll"}
            for row in terminal
        ),
        "navigate_ok_count": sum(
            row["status"] == "ok" and row["verb"] == "navigate" for row in terminal
        ),
        "failed_count": sum(row["status"] == "failed" for row in terminal),
        "rejected_count": sum(row["status"] == "rejected" for row in terminal),
        "scope_blocker_count": scope_blockers,
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _surface(engine: Any, arm: str) -> dict[str, Any]:
    allowed = set(ARMS[arm]["allowed_tools"])
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    names = engine.registry.names()
    schemas = engine.registry.schemas(lazy=True)
    tool_sha256 = {str(row["name"]): _sha(row) for row in schemas}
    mutation_tool = str(ARMS[arm]["mutation_tool"])
    mutation_schema = next(row for row in schemas if row.get("name") == mutation_tool)
    mutation_props = sorted((mutation_schema.get("parameters") or {}).get("properties") or {})
    mutation_desc = str(mutation_schema.get("description") or "")
    perceive_schema = next(row for row in schemas if row.get("name") == "browser_perceive")
    perceive_props = (perceive_schema.get("parameters") or {}).get("properties") or {}
    by_name = {str(row.get("name") or ""): row for row in schemas}
    wait_params = {
        name: by_name[name].get("parameters") or {} for name in sorted(_TYPED_WAIT_TOOLS)
    }
    target_ref_desc = str(
        (
            ((mutation_schema.get("parameters") or {}).get("properties") or {}).get("target_ref")
            or {}
        ).get("description")
        or ""
    )
    return {
        "names": names,
        "exact": set(names) == allowed,
        "sha256": _sha(schemas),
        "json_chars": len(json.dumps(schemas, ensure_ascii=False, sort_keys=True)),
        "tool_sha256": tool_sha256,
        "mutation_tool": mutation_tool,
        "mutation_parameter_names": mutation_props,
        "mutation_description_sha256": hashlib.sha256(mutation_desc.encode("utf-8")).hexdigest(),
        "perceive_actions": list((perceive_props.get("action") or {}).get("enum") or []),
        "perceive_has_predicate": "predicate" in perceive_props,
        "wait_required": {
            name: sorted(params.get("required") or []) for name, params in wait_params.items()
        },
        "wait_interval": {
            name: (params.get("properties") or {}).get("interval_ms")
            for name, params in wait_params.items()
        },
        "ready_state_schema": (wait_params["browser_wait_scope_ready"].get("properties") or {}).get(
            "state"
        ),
        "object_state_value_schema": (
            wait_params["browser_wait_object_state"].get("properties") or {}
        ).get("value"),
        "object_state_properties": list(
            (
                (wait_params["browser_wait_object_state"].get("properties") or {}).get("property")
                or {}
            ).get("enum")
            or []
        ),
        "scope_count_schema": (wait_params["browser_wait_scope_count"].get("properties") or {}).get(
            "count"
        ),
        "old_generic_wait_present": bool(set(names) & _OLD_GENERIC_WAIT_TOOLS),
        "semantic_usage_visible": (
            mutation_tool == "browser_semantic_execute"
            and all(
                marker in mutation_desc
                for marker in (
                    "snapshot",
                    "GroundingRef",
                    "target_ref",
                    "resource_ref",
                    "ActionReceipt",
                    "没有 snapshot/ref 不要调用",
                    "不要把 URL 当 target_ref",
                )
            )
            and all(
                marker in target_ref_desc
                for marker in ("先 snapshot", "resource_ref", "不要把 URL")
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--surface-only", action="store_true")
    args = parser.parse_args()

    import llm_loop
    from llm_loop.config import load_settings
    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from llm_loop.factory import build_engine

    expected_root = os.environ.get("SMC_EXPECTED_RUNTIME_ROOT")
    if (
        expected_root
        and Path(llm_loop.__file__).resolve().parents[2] != Path(expected_root).resolve()
    ):
        raise RuntimeError("worker imported a different runtime source root")

    settings = load_settings()
    engine = build_engine(settings)
    started = time.monotonic()
    payload: dict[str, Any] = {
        "arm": args.arm,
        "configured_model": MODEL_REF,
        "mutation_tool": ARMS[args.arm]["mutation_tool"],
        "resolved_max_iterations": settings.max_iterations,
    }
    try:
        surface = _surface(engine, args.arm)
        payload["surface"] = surface
        atomic_json(Path(args.result_json).with_name("worker-startup.json"), payload)
        if args.surface_only:
            payload["status"] = "SURFACE_ONLY"
        else:
            sid = engine.session.create()
            result = engine.run(sid, args.prompt, ingress=issue_ingress("cli"))
            trace, counts = _safe_tool_trace(list(result.tool_calls or []), args.arm)
            receipts = _receipt_facts(Path(settings.data_dir))
            wait_message_facts = _wait_message_facts(Path(settings.data_dir), sid)
            partial_pressure_facts = _partial_pressure_facts(Path(settings.data_dir), sid)
            mutation_count = counts["semantic_execute"]
            invalid_target_ref_failure_count = sum(
                row.get("name") == "browser_semantic_execute"
                and row.get("status") != "success"
                and row.get("target_ref_kind") == "other"
                for row in trace
            )
            object_level_wait_count = sum(
                1
                for row in trace
                if row.get("name") in _TYPED_WAIT_TOOLS and row.get("ref_kind") == "object"
            )
            semantic_execute_rejection_count = 0
            wait_calls_after_unresolved_rejection = 0
            action_recovery_after_rejection_count = 0
            _rejected_seen = False
            _rejected_verb = ""
            for row in trace:
                name = str(row.get("name") or "")
                if name != "browser_semantic_execute":
                    if _rejected_seen and name in _TYPED_WAIT_TOOLS:
                        wait_calls_after_unresolved_rejection += 1
                    continue
                if (
                    _rejected_seen
                    and row.get("status") == "success"
                    and str(row.get("verb") or "") == _rejected_verb
                ):
                    action_recovery_after_rejection_count += 1
                    _rejected_seen = False
                elif row.get("status") != "success":
                    semantic_execute_rejection_count += 1
                    _rejected_seen = True
                    _rejected_verb = str(row.get("verb") or "")
                else:
                    _rejected_seen = False
            payload.update(
                {
                    "status": "RUN_OK",
                    "session_sha256": hashlib.sha256(sid.encode("utf-8")).hexdigest(),
                    "rounds": result.rounds,
                    "tool_calls": trace,
                    "tool_call_count": len(trace),
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cache_hit_tokens": result.tokens_cache_hit,
                    "truncated": bool(result.truncated),
                    "model_used": result.model_used,
                    "fallback_used": bool(result.fallback_receipt),
                    "final_answer_chars": len(result.final_answer or ""),
                    "final_answer_sha256": hashlib.sha256(
                        (result.final_answer or "").encode("utf-8")
                    ).hexdigest(),
                    "smc_perceive_count": counts["smc_perceive"],
                    "typed_wait_call_count": counts["typed_wait"],
                    "typed_wait_failure_count": counts["typed_wait_failures"],
                    "old_generic_wait_call_count": counts["old_generic_wait"],
                    "legacy_perceive_wait_misuse_count": counts["legacy_perceive_wait"],
                    "snapshot_predicate_count": counts["snapshot_predicate"],
                    "mutation_call_count": mutation_count,
                    "mutation_failure_call_count": counts["mutation_failures"],
                    "get_tool_schema_count": counts["get_tool_schema"],
                    "smc_adopted": counts["smc_perceive"] > 0 and mutation_count > 0,
                    "invalid_target_ref_failure_count": invalid_target_ref_failure_count,
                    "object_level_wait_invoked": object_level_wait_count > 0,
                    "object_level_wait_count": object_level_wait_count,
                    "semantic_execute_rejection_count": semantic_execute_rejection_count,
                    "wait_calls_after_unresolved_rejection": wait_calls_after_unresolved_rejection,
                    "action_recovery_after_rejection": semantic_execute_rejection_count > 0
                    and action_recovery_after_rejection_count > 0,
                    "action_recovery_after_rejection_count": action_recovery_after_rejection_count,
                    **partial_pressure_facts,
                    **wait_message_facts,
                    "receipt_facts": receipts,
                }
            )
    except Exception as exc:  # noqa: BLE001
        payload.update(
            {
                "status": "WORKER_ERROR",
                "error_type": type(exc).__name__,
                "error": _safe_error(exc),
            }
        )
    finally:
        payload["wall_s"] = round(time.monotonic() - started, 3)
        engine.close()

    out = Path(args.result_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(out, payload)
    return 0 if payload.get("status") in {"RUN_OK", "SURFACE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
