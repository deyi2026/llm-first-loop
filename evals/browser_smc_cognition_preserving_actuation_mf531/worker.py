#!/usr/bin/env python3
"""One fresh LFL worker for frozen MF-5.3.1 root-direct Perceive+Operate qualification."""

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

from protocol import ALLOWED_TOOLS, BROWSER_CAPABILITIES, MODEL_REF  # noqa: E402

_HIDDEN_BROWSER_TOOLS = {
    "browser_wait_scope_url",
    "browser_wait_scope_ready",
    "browser_wait_scope_count",
    "browser_wait_object_state",
    "browser_wait_object_text",
    "browser_semantic_execute",
    "browser_action",
    "playwright_exec",
    "playwright_test",
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
    perceive = lazy["browser_perceive"]
    operation = lazy["browser_semantic_operation"]
    full_perceive = full["browser_perceive"]
    full_operation = full["browser_semantic_operation"]
    perceive_params = perceive.get("parameters") or {}
    operation_params = operation.get("parameters") or {}
    full_perceive_params = full_perceive.get("parameters") or {}
    full_operation_params = full_operation.get("parameters") or {}
    perceive_props = perceive_params.get("properties") or {}
    perceive_actions = list((perceive_props.get("action") or {}).get("enum") or [])

    def branch_signature(branch: Any) -> dict[str, Any] | None:
        if not isinstance(branch, dict):
            return None
        props = branch.get("properties") or {}
        action_schema = props.get("action") or {}
        action_values = list(action_schema.get("enum") or [])
        action = str(action_values[0]) if len(action_values) == 1 else ""
        kind_schema = props.get("kind") or {}
        kind_values = list(kind_schema.get("enum") or [])
        kind = str(kind_values[0]) if len(kind_values) == 1 else ""
        return {
            "action": action,
            "kind": kind,
            "fields": sorted(str(key) for key in props),
            "required": sorted(str(key) for key in (branch.get("required") or [])),
            "closed": branch.get("additionalProperties") is False,
        }

    perceive_branches = [
        sig for sig in (branch_signature(branch) for branch in (perceive_params.get("oneOf") or []))
        if sig is not None
    ]
    full_perceive_branches = [
        sig for sig in (branch_signature(branch) for branch in (full_perceive_params.get("oneOf") or []))
        if sig is not None
    ]
    wait_kinds = sorted(
        str(row.get("kind") or "")
        for row in perceive_branches
        if row.get("action") == "wait" and row.get("kind")
    )
    operation_props = operation_params.get("properties") or {}
    operation_verbs = list((operation_props.get("do") or {}).get("enum") or [])
    perceive_desc = str(perceive.get("description") or "")
    operation_desc = str(operation.get("description") or "")
    browser_names = sorted(name for name in names if name.startswith("browser_"))
    return {
        "names": names,
        "exact": set(names) == allowed,
        "browser_capability_names": browser_names,
        "browser_capabilities_exact": browser_names == sorted(BROWSER_CAPABILITIES),
        "sha256": _sha(lazy_schemas),
        "json_chars": len(json.dumps(lazy_schemas, ensure_ascii=False, sort_keys=True)),
        "full_surface_sha256": _sha(full_schemas),
        "perceive_actions": perceive_actions,
        "perceive_wait_kinds": wait_kinds,
        "perceive_root_direct": bool(perceive_params.get("oneOf")),
        "perceive_branch_count": len(perceive_branches),
        "perceive_branch_signatures": perceive_branches,
        "full_perceive_branch_signatures": full_perceive_branches,
        "perceive_lazy_full_branch_equal": perceive_branches == full_perceive_branches,
        "perceive_has_nested_condition": "condition" in perceive_props,
        "perceive_parameters_sha256": _sha(perceive_params),
        "full_perceive_parameters_sha256": _sha(full_perceive_params),
        "full_perceive_recursive_closed": _recursive_closed(full_perceive_params),
        "perceive_exposes_poll_interval": "interval_ms" in perceive_props,
        "operation_verbs": operation_verbs,
        "operation_parameters_sha256": _sha(operation_params),
        "full_operation_parameters_sha256": _sha(full_operation_params),
        "full_operation_recursive_closed": _recursive_closed(full_operation_params),
        "operation_has_steps": "steps" in operation_props,
        "operation_direct_root": bool(operation_params.get("oneOf")) and "do" in operation_props,
        "perceive_description_chars": len(perceive_desc),
        "operation_description_chars": len(operation_desc),
        "cognition_contract_visible": (
            "wait页面ready/URL" in perceive_desc
            and "method_ref=" in perceive_desc
            and "browser_semantic_execute" not in perceive_desc
            and "Observe -> Ground -> Execute" not in perceive_desc
            and "一次调用一个已决定mutation" in operation_desc
            and "wait属于browser_perceive" in operation_desc
            and "不fuzzy/rebind/retry/完成判断" in operation_desc
        ),
        "hidden_atomic_tools_present": bool(set(names) & _HIDDEN_BROWSER_TOOLS),
    }



def _safe_tool_trace(
    trace: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
    rows: list[dict[str, Any]] = []
    counts: dict[str, int | bool] = {
        "perceive": 0,
        "perceive_snapshot": 0,
        "perceive_hydrate": 0,
        "perceive_diff": 0,
        "perceive_wait": 0,
        "perceive_failure": 0,
        "perceive_error": 0,
        "operation": 0,
        "operation_failure": 0,
        "operation_error": 0,
        "operation_direct": 0,
        "get_tool_schema": 0,
        "read_evidence": 0,
        "direct_atomic_browser": 0,
        "first_browser_call_contract_valid": False,
    }
    saw_first_browser = False
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
        if name in BROWSER_CAPABILITIES and not saw_first_browser:
            counts["first_browser_call_contract_valid"] = status == "success"
            saw_first_browser = True
        if name == "browser_perceive":
            counts["perceive"] = int(counts["perceive"]) + 1
            counts["perceive_failure"] = int(counts["perceive_failure"]) + int(
                status == "failure"
            )
            counts["perceive_error"] = int(counts["perceive_error"]) + int(status == "error")
            action = str(args.get("action") or "")
            row["perceive_action"] = action
            key = {
                "snapshot": "perceive_snapshot",
                "hydrate": "perceive_hydrate",
                "diff": "perceive_diff",
                "wait": "perceive_wait",
            }.get(action)
            if key:
                counts[key] = int(counts[key]) + 1
        elif name == "browser_semantic_operation":
            counts["operation"] = int(counts["operation"]) + 1
            counts["operation_failure"] = int(counts["operation_failure"]) + int(
                status == "failure"
            )
            counts["operation_error"] = int(counts["operation_error"]) + int(status == "error")
            direct = isinstance(args.get("do"), str) and "steps" not in args
            counts["operation_direct"] = int(counts["operation_direct"]) + int(direct)
            row["operation_do"] = str(args.get("do") or "")
            row["operation_direct"] = direct
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
    facts: dict[str, Any] = {
        "operation_receipt_count": 0,
        "operation_halted_count": 0,
        "operation_unparsed_result_count": 0,
        "task_completion_violation_count": 0,
        "operation_automatic_retry_true_count": 0,
        "operation_result_chars_total": 0,
        "operation_halt_reasons": {},
        "operation_compact_statuses": [],
        "operation_diff_refs": [],
        "ground_probe_amplification_count": 0,
        "operation_delta_complete_count": 0,
        "operation_delta_incomplete_count": 0,
    }
    if not path.is_file():
        return facts
    reasons: dict[str, int] = {}
    statuses: list[str] = []
    diff_refs: list[str | None] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message.appended":
            continue
        payload = event.get("payload") or {}
        if payload.get("role") != "tool" or payload.get("tool_name") != "browser_semantic_operation":
            continue
        content = str(payload.get("content") or "")
        facts["operation_result_chars_total"] += len(content)
        doc = _json_object_from_tool_content(content)
        if doc is None or doc.get("schema") != "smc.browser_semantic_operation_compact_receipt.v0.1":
            facts["operation_unparsed_result_count"] += 1
            statuses.append("unparsed")
            diff_refs.append(None)
            continue
        facts["operation_receipt_count"] += 1
        status = str(doc.get("status") or "unknown")
        statuses.append(status)
        facts["operation_halted_count"] += int(status == "halted")
        facts["operation_automatic_retry_true_count"] += int(doc.get("automatic_retry") is True)
        facts["task_completion_violation_count"] += int(doc.get("task_completion") != "not_evaluated")
        reason = str(doc.get("halt_reason") or "")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        if reason in {"target_not_found", "ambiguous_target"}:
            facts["ground_probe_amplification_count"] += 1
        delta_raw = doc.get("delta")
        delta: dict[str, Any] = delta_raw if isinstance(delta_raw, dict) else {}
        diff_ref = str(delta.get("ref") or doc.get("diff_ref") or "").strip() or None
        diff_refs.append(diff_ref)
        if delta:
            if delta.get("complete") is True:
                facts["operation_delta_complete_count"] += 1
            else:
                facts["operation_delta_incomplete_count"] += 1
    facts["operation_halt_reasons"] = dict(sorted(reasons.items()))
    facts["operation_compact_statuses"] = statuses
    facts["operation_diff_refs"] = diff_refs
    return facts


def _perceive_message_facts(data_dir: Path, session_id: str) -> dict[str, int]:
    path = data_dir / "event_logs" / f"{session_id}.jsonl"
    chars = 0
    count = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "message.appended":
                continue
            payload = event.get("payload") or {}
            if payload.get("role") == "tool" and payload.get("tool_name") == "browser_perceive":
                count += 1
                chars += len(str(payload.get("content") or ""))
    return {"perceive_result_count": count, "perceive_result_chars_total": chars}


def _post_operation_diagnostics(
    trace: list[dict[str, Any]], statuses: list[str], diff_refs: list[str | None]
) -> dict[str, int]:
    op_rows = [row for row in trace if row.get("name") == "browser_semantic_operation"]
    completed_fingerprints: set[str] = set()
    duplicates = 0
    delta_only = 0
    delta_to_hydrate = 0
    delta_to_snapshot = 0
    delta_to_hydrate_then_snapshot = 0
    basis = 0
    for op_index, op_row in enumerate(op_rows):
        status = statuses[op_index] if op_index < len(statuses) else "missing"
        if status == "completed":
            fp = str(op_row.get("args_sha256") or "")
            if fp and fp in completed_fingerprints:
                duplicates += 1
            elif fp:
                completed_fingerprints.add(fp)
        diff_ref = diff_refs[op_index] if op_index < len(diff_refs) else None
        if status != "completed" or not diff_ref:
            continue
        basis += 1
        trace_pos = int(op_row.get("index") or 0)
        next_op_pos = None
        if op_index + 1 < len(op_rows):
            next_op_pos = int(op_rows[op_index + 1].get("index") or 0)
        between = [
            row
            for row in trace
            if int(row.get("index") or 0) > trace_pos
            and (next_op_pos is None or int(row.get("index") or 0) < next_op_pos)
            and row.get("name") == "browser_perceive"
        ]
        exact_hydrate = False
        snapshot = False
        for row in between:
            action = str(row.get("perceive_action") or "")
            if action == "snapshot":
                snapshot = True
            elif action == "hydrate":
                # _safe_tool_trace intentionally keeps only hashes/keys. This diagnostic
                # is therefore conservative: any hydrate after a compact delta counts as
                # hydrate escalation; exact ref integrity remains enforced by the tool.
                exact_hydrate = True
        if exact_hydrate and snapshot:
            delta_to_hydrate_then_snapshot += 1
        elif exact_hydrate:
            delta_to_hydrate += 1
        elif snapshot:
            delta_to_snapshot += 1
        else:
            delta_only += 1
    return {
        "duplicate_successful_mutation_count": duplicates,
        "delta_escalation_basis_count": basis,
        "delta_only_count": delta_only,
        "delta_to_hydrate_count": delta_to_hydrate,
        "delta_to_snapshot_count": delta_to_snapshot,
        "delta_to_hydrate_then_snapshot_count": delta_to_hydrate_then_snapshot,
    }



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
            data_dir = Path(settings.data_dir)
            operation_facts = _operation_message_facts(data_dir, sid)
            perceive_facts = _perceive_message_facts(data_dir, sid)
            post_operation = _post_operation_diagnostics(
                trace,
                list(operation_facts.get("operation_compact_statuses") or []),
                list(operation_facts.get("operation_diff_refs") or []),
            )
            perceive_failures = int(counts["perceive_failure"])
            perceive_errors = int(counts["perceive_error"])
            operation_failures = int(counts["operation_failure"])
            operation_errors = int(counts["operation_error"])
            schema_calls = int(counts["get_tool_schema"])
            browser_arg_chars = sum(
                int(row.get("args_chars") or 0)
                for row in trace
                if row.get("name") in BROWSER_CAPABILITIES
            )
            browser_result_chars = int(operation_facts["operation_result_chars_total"]) + int(
                perceive_facts["perceive_result_chars_total"]
            )
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
                    "perceive_call_count": int(counts["perceive"]),
                    "perceive_snapshot_count": int(counts["perceive_snapshot"]),
                    "perceive_hydrate_count": int(counts["perceive_hydrate"]),
                    "perceive_diff_count": int(counts["perceive_diff"]),
                    "perceive_wait_count": int(counts["perceive_wait"]),
                    "perceive_tool_failure_count": perceive_failures,
                    "perceive_tool_error_count": perceive_errors,
                    "operation_call_count": int(counts["operation"]),
                    "operation_direct_count": int(counts["operation_direct"]),
                    "operation_tool_failure_count": operation_failures,
                    "operation_tool_error_count": operation_errors,
                    "get_tool_schema_count": schema_calls,
                    "read_evidence_count": int(counts["read_evidence"]),
                    "direct_atomic_browser_call_count": int(counts["direct_atomic_browser"]),
                    "first_browser_call_contract_valid": bool(
                        counts["first_browser_call_contract_valid"]
                    ),
                    "protocol_repair_episode_count": (
                        perceive_failures
                        + perceive_errors
                        + operation_failures
                        + operation_errors
                        + schema_calls
                    ),
                    "browser_arg_chars_total": browser_arg_chars,
                    "browser_result_chars_total": browser_result_chars,
                    **operation_facts,
                    **perceive_facts,
                    **post_operation,
                    **_full_operation_receipt_facts(data_dir),
                    "action_receipt_facts": _action_receipt_facts(data_dir),
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
