#!/usr/bin/env python3
"""One fresh LFL worker for frozen MF-5.2 cognition-preserving qualification."""

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

_HIDDEN_BROWSER_TOOLS = {
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


def _surface(engine: Any) -> dict[str, Any]:
    allowed = set(ALLOWED_TOOLS)
    for name in list(engine.registry.names()):
        if name not in allowed:
            engine.registry.unregister(name)
    names = engine.registry.names()
    lazy_schemas = engine.registry.schemas(lazy=True)
    full_schemas = engine.registry.schemas(lazy=False)
    lazy = {str(row.get("name") or ""): row for row in lazy_schemas}
    full = {str(row.get("name") or ""): row for row in full_schemas}
    operation = lazy["browser_semantic_operation"]
    full_operation = full["browser_semantic_operation"]
    params = operation.get("parameters") or {}
    full_params = full_operation.get("parameters") or {}
    branches = (((params.get("properties") or {}).get("steps") or {}).get("items") or {}).get(
        "oneOf"
    ) or []
    branch_do = [
        tuple(((branch.get("properties") or {}).get("do") or {}).get("enum") or [])
        for branch in branches
        if isinstance(branch, dict)
    ]
    desc = str(operation.get("description") or "")
    return {
        "names": names,
        "exact": set(names) == allowed,
        "sha256": _sha(lazy_schemas),
        "json_chars": len(json.dumps(lazy_schemas, ensure_ascii=False, sort_keys=True)),
        "full_surface_sha256": _sha(full_schemas),
        "operation_parameter_names": sorted((params.get("properties") or {}).keys()),
        "operation_required": sorted(params.get("required") or []),
        "operation_parameters_sha256": _sha(params),
        "full_operation_parameters_sha256": _sha(full_params),
        "full_operation_recursive_closed": _recursive_closed(full_params),
        "branch_do": branch_do,
        "description_chars": len(desc),
        "cognition_contract_visible": all(
            marker in desc
            for marker in (
                "steps仅是调用容器",
                "单个已决定动作",
                "多个动作",
                "已经决定",
                "wait=until",
            )
        ),
        "hidden_atomic_tools_present": bool(set(names) & _HIDDEN_BROWSER_TOOLS),
    }


def _safe_tool_trace(
    trace: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
    rows: list[dict[str, Any]] = []
    counts: dict[str, int | bool] = {
        "operation": 0,
        "operation_failure": 0,
        "operation_error": 0,
        "get_tool_schema": 0,
        "read_evidence": 0,
        "direct_atomic_browser": 0,
        "single_action_operation": 0,
        "multi_action_operation": 0,
        "first_operation_contract_valid": False,
    }
    saw_first_operation = False
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
            counts["operation"] = int(counts["operation"]) + 1
            counts["operation_failure"] = int(counts["operation_failure"]) + int(
                status == "failure"
            )
            counts["operation_error"] = int(counts["operation_error"]) + int(status == "error")
            steps = args.get("steps")
            item_count = len(steps) if isinstance(steps, list) else None
            row["operation_item_count"] = item_count
            if item_count == 1:
                counts["single_action_operation"] = int(counts["single_action_operation"]) + 1
            elif isinstance(item_count, int) and item_count > 1:
                counts["multi_action_operation"] = int(counts["multi_action_operation"]) + 1
            if not saw_first_operation:
                counts["first_operation_contract_valid"] = status == "success"
                saw_first_operation = True
        elif name == "get_tool_schema":
            counts["get_tool_schema"] = int(counts["get_tool_schema"]) + 1
        elif name == "read_evidence":
            counts["read_evidence"] = int(counts["read_evidence"]) + 1
        if name in _HIDDEN_BROWSER_TOOLS:
            counts["direct_atomic_browser"] = int(counts["direct_atomic_browser"]) + 1
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
        "operation_halted_count": 0,
        "operation_unparsed_result_count": 0,
        "task_completion_violation_count": 0,
        "operation_automatic_retry_true_count": 0,
        "operation_result_chars_total": 0,
        "operation_halt_reasons": {},
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
        if (
            doc is None
            or doc.get("schema") != "smc.browser_semantic_operation_compact_receipt.v0.1"
        ):
            facts["operation_unparsed_result_count"] += 1
            continue
        facts["operation_receipt_count"] += 1
        facts["operation_halted_count"] += int(doc.get("status") == "halted")
        facts["operation_automatic_retry_true_count"] += int(doc.get("automatic_retry") is True)
        facts["task_completion_violation_count"] += int(
            doc.get("task_completion") != "not_evaluated"
        )
        reason = str(doc.get("halt_reason") or "")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        # Do not infer declared/undeclared structural-transition behavior from the
        # compact receipt. A successful navigate legitimately carries boundary events,
        # while a non-navigate boundary must halt. Only the durable full operation
        # receipt retains the clause verb needed to distinguish those cases; the
        # qualification Gate consumes _full_operation_receipt_facts() below.
    facts["operation_halt_reasons"] = dict(sorted(reasons.items()))
    return facts


def _full_operation_receipt_facts(data_dir: Path) -> dict[str, int]:
    root = data_dir / "browser_semantic_operation"
    full_count = 0
    undeclared_boundary_halts = 0
    undeclared_boundary_continuations = 0
    if not root.is_dir():
        return {
            "full_operation_receipt_count": 0,
            "undeclared_boundary_halt_count": 0,
            "undeclared_boundary_continuation_count": 0,
        }
    for path in root.rglob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("schema") != "smc.browser_semantic_operation_full_receipt.v0.1":
            continue
        content = doc.get("content")
        if not isinstance(content, dict):
            continue
        full_count += 1
        clauses = [x for x in (content.get("clauses") or []) if isinstance(x, dict)]
        offending: list[int] = []
        for clause in clauses:
            if clause.get("kind") != "mutate" or clause.get("verb") == "navigate":
                continue
            action = clause.get("action_receipt")
            events = action.get("boundary_events") if isinstance(action, dict) else None
            if isinstance(events, list) and events:
                offending.append(int(clause.get("index") or 0))
        if not offending:
            continue
        correctly_halted = (
            content.get("execution_status") == "halted"
            and content.get("halt_reason") == "undeclared_structural_transition"
        )
        if correctly_halted:
            undeclared_boundary_halts += 1
        max_offending = max(offending)
        later_clause_executed = any(int(x.get("index") or 0) > max_offending for x in clauses)
        if not correctly_halted or later_clause_executed:
            undeclared_boundary_continuations += 1
    return {
        "full_operation_receipt_count": full_count,
        "undeclared_boundary_halt_count": undeclared_boundary_halts,
        "undeclared_boundary_continuation_count": undeclared_boundary_continuations,
    }


def _action_receipt_facts(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "browser_action"
    terminal: list[dict[str, Any]] = []
    automatic_retry = 0
    scope_blockers = 0
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
                automatic_retry += int(retry.get("automatic_retry_performed") is True)
                reasons = [str(x) for x in ((doc.get("completeness") or {}).get("reasons") or [])]
                scope_blockers += sum(
                    "version_scope_mismatch" in reason
                    or "different_snapshot_same_generation" in reason
                    or "expected_version_unavailable" in reason
                    or "resource_scope_mismatch" in reason
                    for reason in reasons
                )
                if doc.get("status") in {"ok", "failed", "rejected"}:
                    terminal.append({"status": doc.get("status"), "verb": doc.get("verb")})
    return {
        "terminal_count": len(terminal),
        "ok_count": sum(row["status"] == "ok" for row in terminal),
        "navigate_ok_count": sum(
            row["status"] == "ok" and row["verb"] == "navigate" for row in terminal
        ),
        "object_ok_count": sum(
            row["status"] == "ok" and row["verb"] in {"click", "fill", "select", "scroll"}
            for row in terminal
        ),
        "failed_count": sum(row["status"] == "failed" for row in terminal),
        "rejected_count": sum(row["status"] == "rejected" for row in terminal),
        "automatic_retry_true_count": automatic_retry,
        "scope_blocker_count": scope_blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
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
        "configured_model": MODEL_REF,
        "resolved_max_iterations": settings.max_iterations,
    }
    try:
        surface = _surface(engine)
        payload["surface"] = surface
        _atomic_json(Path(args.result_json).with_name("worker-startup.json"), payload)
        if args.surface_only:
            payload["status"] = "SURFACE_ONLY"
        else:
            sid = engine.session.create()
            result = engine.run(sid, args.prompt, ingress=issue_ingress("cli"))
            trace, counts = _safe_tool_trace(list(result.tool_calls or []))
            operation_facts = _operation_message_facts(Path(settings.data_dir), sid)
            operation_failures = int(counts["operation_failure"])
            schema_calls = int(counts["get_tool_schema"])
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
                    "operation_call_count": int(counts["operation"]),
                    "operation_arg_chars_total": sum(
                        int(row.get("args_chars") or 0)
                        for row in trace
                        if row.get("name") == "browser_semantic_operation"
                    ),
                    "operation_tool_failure_count": operation_failures,
                    "operation_tool_error_count": int(counts["operation_error"]),
                    "get_tool_schema_count": schema_calls,
                    "read_evidence_count": int(counts["read_evidence"]),
                    "direct_atomic_browser_call_count": int(counts["direct_atomic_browser"]),
                    "single_action_operation_count": int(counts["single_action_operation"]),
                    "multi_action_operation_count": int(counts["multi_action_operation"]),
                    "first_operation_contract_valid": bool(
                        counts["first_operation_contract_valid"]
                    ),
                    "protocol_repair_episode_count": operation_failures + schema_calls,
                    **operation_facts,
                    **_full_operation_receipt_facts(Path(settings.data_dir)),
                    "action_receipt_facts": _action_receipt_facts(Path(settings.data_dir)),
                }
            )
    except Exception as exc:  # noqa: BLE001
        payload.update(
            {"status": "WORKER_ERROR", "error_type": type(exc).__name__, "error": _safe_error(exc)}
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
