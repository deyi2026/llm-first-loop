#!/usr/bin/env python3
"""One fresh LFL worker for frozen MF-5 model-friendly A/B qualification."""

from __future__ import annotations

import argparse
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

from protocol import ALLOWED_TOOLS, MODEL_REF  # noqa: E402


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def _safe_error(exc: Exception) -> str:
    return str(exc).replace(str(Path.cwd()), "<run_dir>").replace(str(REPO), "<repo>")[:500]


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(value) if isinstance(value, dict) else {}
    return {}


def _recursive_closed(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("type") == "object" and node.get("additionalProperties") is not False:
            return False
        return all(_recursive_closed(child) for child in node.values())
    if isinstance(node, list):
        return all(_recursive_closed(child) for child in node)
    return True


def _configure_arm(engine: Any, arm: str) -> None:
    tool = engine.registry.get("browser_semantic_operation")
    if arm == "A":
        tool.parameters = tool._CLAUSE_PARAMETERS
        tool.lazy_parameters = tool._CLAUSE_LAZY_PARAMETERS
        tool.description = (
            "Bounded Browser semantic operation：模型声明有序 clauses；对象只按模型给出的 "
            "kind/role/name exact-unique 匹配，0或>1立即停止；args: click={}，"
            "fill={text,mode(replace|append)}，select={value}，scroll={delta_pages}，"
            "navigate={url}；wait复用typed Predicate；不 fuzzy/auto-target/latest/rebind/retry，"
            "不判断任务完成。"
        )
    elif arm != "B":
        raise ValueError(f"unknown MF5 arm: {arm}")


def _surface(engine: Any, arm: str) -> dict[str, Any]:
    _configure_arm(engine, arm)
    allowed = set(ALLOWED_TOOLS)
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    names = engine.registry.names()
    lazy_schemas = engine.registry.schemas(lazy=True)
    full_schemas = engine.registry.schemas(lazy=False)
    lazy_by_name = {str(row.get("name") or ""): row for row in lazy_schemas}
    full_by_name = {str(row.get("name") or ""): row for row in full_schemas}
    operation = lazy_by_name["browser_semantic_operation"]
    full_operation = full_by_name["browser_semantic_operation"]
    params = operation.get("parameters") or {}
    full_params = full_operation.get("parameters") or {}
    return {
        "arm": arm,
        "names": names,
        "exact": set(names) == allowed,
        "sha256": _sha(lazy_schemas),
        "json_chars": len(json.dumps(lazy_schemas, ensure_ascii=False, sort_keys=True)),
        "full_surface_sha256": _sha(full_schemas),
        "operation_parameter_names": sorted((params.get("properties") or {}).keys()),
        "operation_parameters_sha256": _sha(params),
        "operation_required": sorted(params.get("required") or []),
        "full_operation_parameters_sha256": _sha(full_params),
        "full_operation_recursive_closed": _recursive_closed(full_params),
        "description_chars": len(str(operation.get("description") or "")),
        "hidden_atomic_tools_present": bool(
            set(names)
            & {
                "browser_perceive",
                "browser_wait_scope_url",
                "browser_wait_scope_ready",
                "browser_wait_scope_count",
                "browser_wait_object_state",
                "browser_wait_object_text",
                "browser_semantic_execute",
                "browser_action",
                "playwright_exec",
            }
        ),
    }


def _safe_tool_trace(trace: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {
        "operation": 0,
        "operation_failure": 0,
        "operation_error": 0,
        "get_tool_schema": 0,
        "read_evidence": 0,
        "direct_atomic_browser": 0,
    }
    hidden = {
        "browser_perceive",
        "browser_wait_scope_url",
        "browser_wait_scope_ready",
        "browser_wait_scope_count",
        "browser_wait_object_state",
        "browser_wait_object_text",
        "browser_semantic_execute",
        "browser_action",
        "playwright_exec",
    }
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
        if name == "browser_semantic_operation":
            counts["operation"] += 1
            counts["operation_failure"] += int(status == "failure")
            counts["operation_error"] += int(status == "error")
            sequence = args.get("clauses") if "clauses" in args else args.get("steps")
            row["operation_root"] = (
                "clauses" if "clauses" in args else ("steps" if "steps" in args else "unknown")
            )
            row["operation_item_count"] = len(sequence) if isinstance(sequence, list) else None
        elif name == "get_tool_schema":
            counts["get_tool_schema"] += 1
        elif name == "read_evidence":
            counts["read_evidence"] += 1
        if name in hidden:
            counts["direct_atomic_browser"] += 1
        rows.append(row)
    return rows, counts


def _json_object_from_tool_content(content: str) -> dict[str, Any] | None:
    pos = content.find("{")
    if pos < 0:
        return None
    try:
        value = json.loads(content[pos:])
    except json.JSONDecodeError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _operation_message_facts(data_dir: Path, session_id: str) -> dict[str, Any]:
    path = data_dir / "event_logs" / f"{session_id}.jsonl"
    facts = {
        "operation_receipt_count": 0,
        "operation_clauses_exhausted_count": 0,
        "operation_halted_count": 0,
        "operation_unparsed_result_count": 0,
        "task_completion_violation_count": 0,
        "operation_automatic_retry_true_count": 0,
        "exact_match_zero_count": 0,
        "exact_match_ambiguous_count": 0,
        "operation_halt_reasons": {},
        "operation_result_chars_total": 0,
    }
    if not path.is_file():
        return facts
    reasons: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message.appended":
            continue
        payload = event.get("payload") or {}
        if (
            payload.get("role") != "tool"
            or payload.get("tool_name") != "browser_semantic_operation"
        ):
            continue
        content = str(payload.get("content") or "")
        facts["operation_result_chars_total"] += len(content)
        doc = _json_object_from_tool_content(content)
        if doc is None:
            facts["operation_unparsed_result_count"] += 1
            continue
        schema = str(doc.get("schema") or "")
        if schema == "smc.bounded_semantic_operation_receipt.v0.1":
            facts["operation_receipt_count"] += 1
            status = str(doc.get("execution_status") or "")
            facts["operation_clauses_exhausted_count"] += int(status == "clauses_exhausted")
            facts["operation_halted_count"] += int(status == "halted")
            retry = doc.get("retry") or {}
            facts["operation_automatic_retry_true_count"] += int(
                bool(retry.get("automatic_retry_performed"))
            )
            for clause in doc.get("clauses") or []:
                if isinstance(clause, dict):
                    exact = clause.get("exact_match_count")
                    facts["exact_match_zero_count"] += int(exact == 0)
                    facts["exact_match_ambiguous_count"] += int(
                        isinstance(exact, int) and exact > 1
                    )
            reason = str(doc.get("halt_reason") or "")
            task_completion = doc.get("task_completion")
        elif schema == "smc.browser_semantic_operation_compact_receipt.v0.1":
            facts["operation_receipt_count"] += 1
            status = str(doc.get("status") or "")
            facts["operation_clauses_exhausted_count"] += int(status == "completed")
            facts["operation_halted_count"] += int(status == "halted")
            facts["operation_automatic_retry_true_count"] += int(doc.get("automatic_retry") is True)
            exact = doc.get("match_count")
            facts["exact_match_zero_count"] += int(exact == 0)
            facts["exact_match_ambiguous_count"] += int(isinstance(exact, int) and exact > 1)
            reason = str(doc.get("halt_reason") or "")
            task_completion = doc.get("task_completion")
        else:
            facts["operation_unparsed_result_count"] += 1
            continue
        facts["task_completion_violation_count"] += int(task_completion != "not_evaluated")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    facts["operation_halt_reasons"] = dict(sorted(reasons.items()))
    return facts


def _action_receipt_facts(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "browser_action"
    terminal: list[dict[str, Any]] = []
    automatic_retry = 0
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
                reasons = [str(x) for x in ((doc.get("completeness") or {}).get("reasons") or [])]
                automatic_retry += int(retry.get("automatic_retry_performed") is True)
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                    scope_blockers += int(
                        "version_scope_mismatch" in reason
                        or "different_snapshot_same_generation" in reason
                        or "expected_version_unavailable" in reason
                        or "resource_scope_mismatch" in reason
                    )
                if doc.get("status") in {"ok", "failed", "rejected"}:
                    terminal.append({"status": doc.get("status"), "verb": doc.get("verb")})
    return {
        "terminal_count": len(terminal),
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
        "automatic_retry_true_count": automatic_retry,
        "scope_blocker_count": scope_blockers,
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="")
    parser.add_argument("--arm", choices=("A", "B"), required=True)
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
        "configured_model": MODEL_REF,
        "resolved_max_iterations": settings.max_iterations,
        "arm": args.arm,
    }
    try:
        surface = _surface(engine, args.arm)
        payload["surface"] = surface
        _atomic_json(Path(args.result_json).with_name("worker-startup.json"), payload)
        if args.surface_only:
            payload["status"] = "SURFACE_ONLY"
        else:
            sid = engine.session.create()
            result = engine.run(sid, args.prompt, ingress=issue_ingress("cli"))
            trace, counts = _safe_tool_trace(list(result.tool_calls or []))
            operation_facts = _operation_message_facts(Path(settings.data_dir), sid)
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
                    "operation_call_count": counts["operation"],
                    "operation_arg_chars_total": sum(
                        int(row.get("args_chars") or 0)
                        for row in trace
                        if row.get("name") == "browser_semantic_operation"
                    ),
                    "operation_tool_failure_count": counts["operation_failure"],
                    "operation_tool_error_count": counts["operation_error"],
                    "get_tool_schema_count": counts["get_tool_schema"],
                    "read_evidence_count": counts["read_evidence"],
                    "direct_atomic_browser_call_count": counts["direct_atomic_browser"],
                    **operation_facts,
                    "action_receipt_facts": _action_receipt_facts(Path(settings.data_dir)),
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
    _atomic_json(out, payload)
    return 0 if payload.get("status") in {"RUN_OK", "SURFACE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
