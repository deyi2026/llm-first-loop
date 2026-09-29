#!/usr/bin/env python3
"""Execution Efficiency v2 conservative offline scorer.

The scorer intentionally does not optimize for fewer tools or a smaller schema.
Correctness is the hard gate.  The remaining fields are independent diagnostics:
First-Call-Ready, observable wrong/rejected calls, repair paths, serial tool-call
barriers, and whole-run token/time cost.

Only mechanically supported claims are emitted.  In particular, a
``get_tool_schema`` call is *not* classified as avoidable unless the benchmark task
explicitly says schema rereads are unnecessary.  Likewise, ``wrong_tool`` is a
conservative lower bound based on the existing first-call oracle rather than a new
semantic classifier.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from evals.execution_efficiency_v2.oracles import FIRST_ACTION_ACCEPTABLE_CLASSES

ARGUMENT_REJECTION_MARKERS = (
    "[参数错误]",
    "参数错误",
    "invalid argument",
    "invalid arguments",
    "missing required",
    "required field",
    "argument validation",
    "schema validation",
    "validation error",
)

MECHANICAL_CONTRACT_REJECTION_MARKERS = ARGUMENT_REJECTION_MARKERS + (
    "expected_snapshot_ref",
    "required_call=read_file",
    "版本前置条件",
    "snapshot 不属于当前工作区",
    "old_string 为空无法定位",
    "[安全拒绝]",
    "[权限拒绝]",
)


def _json_args(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _stable(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _canonical_path(value: str, workspace: str = "") -> str:
    """Normalize the same workspace resource across relative/absolute spellings.

    This deliberately does not resolve symlinks or touch the filesystem.  Historical
    eval workspaces often no longer exist; the row-local workspace name is enough to
    strip the run-specific absolute prefix mechanically.
    """
    raw = str(value or "").replace("\\", "/")
    ws = str(workspace or "").strip("/")
    if ws:
        marker = f"/{ws}/"
        if marker in raw:
            raw = raw.split(marker, 1)[1]
        elif raw.endswith(f"/{ws}"):
            raw = "."
    norm = posixpath.normpath(raw)
    return norm[2:] if norm.startswith("./") else norm


def _read_resource_key(call: dict[str, Any], workspace: str) -> tuple[Any, ...] | None:
    """Return a conservative acquisition identity for exact rereads.

    Read ranges/pages are identity-bearing.  Therefore reading another page of the
    same file is not a redundant reacquisition.  The main benefit over exact argument
    equality is path canonicalization (absolute vs row-relative), which fixes the
    historical scorer undercount without guessing semantic equivalence.
    """
    name = str(call.get("name") or "")
    args = _json_args(call.get("args"))
    if args is None:
        return None
    if name == "read_file" and isinstance(args.get("path"), str):
        return (
            name,
            _canonical_path(args["path"], workspace),
            args.get("start_line"),
            args.get("end_line"),
            args.get("start"),
            args.get("limit"),
        )
    identity_fields = {
        "read_evidence": ("ref", "evidence_ref"),
        "read_attachment": ("ref", "attachment_id", "path"),
        "read_image": ("path", "ref"),
        "source_synopsis": ("path", "source_ref", "ref"),
    }
    for field in identity_fields.get(name, ()):
        value = args.get(field)
        if isinstance(value, str) and value:
            if field == "path":
                value = _canonical_path(value, workspace)
            return (name, field, value)
    return None


def _argument_rejection(call: dict[str, Any]) -> bool:
    if call.get("ok") is not False:
        return False
    result = str(call.get("result") or "").lower()
    return any(marker.lower() in result for marker in ARGUMENT_REJECTION_MARKERS)


def _mechanical_contract_rejection(call: dict[str, Any]) -> bool:
    if call.get("ok") is not False:
        return False
    result = str(call.get("result") or "").lower()
    return any(marker.lower() in result for marker in MECHANICAL_CONTRACT_REJECTION_MARKERS)


def _first_action_selection(
    row: dict[str, Any], calls: list[dict[str, Any]], task: dict[str, Any] | None
) -> bool | None:
    if not calls:
        return None
    explicit = (task or {}).get("first_action_acceptable_classes_v2")
    acceptable = (
        frozenset(str(x) for x in explicit)
        if isinstance(explicit, (list, tuple, set, frozenset)) and explicit
        else FIRST_ACTION_ACCEPTABLE_CLASSES.get(str(row.get("task_id") or ""))
    )
    if not acceptable:
        return None
    classes = {str(x) for x in (calls[0].get("classes") or [])}
    return bool(classes & acceptable)


def _first_action_dispatchable(calls: list[dict[str, Any]]) -> bool | None:
    """Whether the first declared call crossed the tool contract successfully.

    A real task/process failure is still mechanically dispatchable.  For example the
    first ``python3 gen.py`` in t02 is designed to exit 1; treating that as invalid args
    would make FCR reward avoiding the required experiment.  Contract/schema/safety
    rejections are the negative case.  If execution status is unavailable, return None.
    """
    if not calls:
        return None
    first = calls[0]
    if first.get("ok") is None:
        return None
    return not _mechanical_contract_rejection(first)


def _avoidable_schema_rereads(
    schema_calls: list[dict[str, Any]], task: dict[str, Any] | None
) -> int | None:
    if not schema_calls:
        return 0
    task = task or {}
    policy = task.get("schema_reread_policy")
    if policy == "forbidden":
        return len(schema_calls)
    if policy == "allowed":
        return 0
    # Unknown is materially different from zero: reading a schema can be the correct
    # action for an unfamiliar or boundary use and must not be punished by default.
    return None


def _numeric(row: dict[str, Any], key: str) -> int | float | None:
    value = row.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def score_row(row: dict[str, Any], task: dict[str, Any] | None = None) -> dict[str, Any]:
    events = row.get("fcr_events") if isinstance(row.get("fcr_events"), dict) else {}
    calls = list(events.get("calls") or [])
    fcr = row.get("fcr_scored") if isinstance(row.get("fcr_scored"), dict) else {}
    workspace = str(row.get("workspace") or "")

    legacy_selection = fcr.get("first_tool_selection_correct")
    selection = _first_action_selection(row, calls, task)
    dispatchable = _first_action_dispatchable(calls)
    first_call_ready_v2 = (
        None if selection is None or dispatchable is None else bool(selection and dispatchable)
    )
    wrong_first = None if selection is None else int(selection is False)
    schema_calls = [c for c in calls if c.get("name") == "get_tool_schema"]
    rejected = [c for c in calls if c.get("ok") is False]
    invalid_args = [c for c in rejected if _argument_rejection(c)]
    contract_rejected = [c for c in rejected if _mechanical_contract_rejection(c)]

    seen_success: set[tuple[str, str]] = set()
    exact_duplicate_success = 0
    for call in calls:
        if call.get("ok") is not True:
            continue
        key = (str(call.get("name") or ""), _stable(call.get("args")))
        if key in seen_success:
            exact_duplicate_success += 1
        else:
            seen_success.add(key)

    seen_resources: dict[tuple[Any, ...], int] = {}
    redundant_reacquisition = 0
    for call in calls:
        if call.get("ok") is not True:
            continue
        key = _read_resource_key(call, workspace)
        turn = call.get("turn")
        if key is None or not isinstance(turn, int):
            continue
        previous_turn = seen_resources.get(key)
        if previous_turn is not None and turn > previous_turn:
            redundant_reacquisition += 1
        else:
            seen_resources[key] = turn

    turn_counts = Counter(
        int(c["turn"])
        for c in calls
        if isinstance(c.get("turn"), int) and int(c["turn"]) > 0
    )
    tool_rounds = len(turn_counts)
    serial_barriers = max(tool_rounds - 1, 0)

    external_pass = row.get("external_pass")
    if not isinstance(external_pass, bool):
        external_pass = None
    legacy_first_call_ready = fcr.get("first_call_ready")
    if not isinstance(legacy_first_call_ready, bool):
        legacy_first_call_ready = None

    return {
        "schema": "lfl-execution-efficiency-v2-row/v0.1",
        "row_id": str(row.get("row_id") or ""),
        "task_id": str(row.get("task_id") or ""),
        "arm": str(row.get("arm") or ""),
        "cache_cohort": row.get("cache_cohort"),
        "correctness_pass": external_pass,
        "first_call_ready": first_call_ready_v2,
        "first_tool_selection_correct": selection,
        "first_call_mechanically_dispatchable": dispatchable,
        "legacy_first_call_ready": legacy_first_call_ready,
        "legacy_first_tool_selection_correct": (
            legacy_selection if isinstance(legacy_selection, bool) else None
        ),
        "wrong_tool_first_call_count": wrong_first,
        "invalid_argument_rejection_count": len(invalid_args),
        "mechanical_contract_rejection_count": len(contract_rejected),
        "runtime_failure_count": len(rejected) - len(contract_rejected),
        "rejected_call_count": len(rejected),
        "unexpected_failure_count": fcr.get("unexpected_failure_count"),
        "expected_failure_count": fcr.get("expected_failure_count"),
        "failure_to_repair_count": fcr.get("failure_to_repair_count"),
        "confirmed_effect_repair_count": fcr.get("confirmed_repair_count"),
        "schema_reread_count": len(schema_calls),
        "avoidable_schema_reread_count": _avoidable_schema_rereads(schema_calls, task),
        "exact_duplicate_success_count": exact_duplicate_success,
        "redundant_reacquisition_count": redundant_reacquisition,
        "provider_rounds": _numeric(row, "rounds"),
        "tool_call_count": len(calls),
        "tool_call_round_count": tool_rounds,
        "serial_tool_barrier_count": serial_barriers,
        "max_parallel_tool_width": max(turn_counts.values(), default=0),
        "input_tokens": _numeric(row, "tokens_in"),
        "uncached_input_tokens": _numeric(row, "new_prefill_tokens"),
        "cache_hit_tokens": _numeric(row, "cache_hit_tokens"),
        "output_tokens": _numeric(row, "tokens_out"),
        "reasoning_tokens": _numeric(row, "reasoning_tokens"),
        "wall_s": _numeric(row, "elapsed_s"),
        "history_compacted": bool(row.get("history_compacted")),
        "run_error": str(row.get("run_error") or ""),
        "run_incomplete": bool(row.get("run_incomplete")),
    }


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r.get(key) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return float(statistics.median(values)) if values else None


def _sum_known(rows: list[dict[str, Any]], key: str) -> int | float | None:
    values = [r.get(key) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return sum(values) if values else None


def _cell(rows: list[dict[str, Any]], *, arm: str | None = None) -> dict[str, Any]:
    correctness = [r["correctness_pass"] for r in rows if isinstance(r.get("correctness_pass"), bool)]
    fcr = [r["first_call_ready"] for r in rows if isinstance(r.get("first_call_ready"), bool)]
    legacy_fcr = [
        r["legacy_first_call_ready"]
        for r in rows
        if isinstance(r.get("legacy_first_call_ready"), bool)
    ]
    avoidable_known = [
        r["avoidable_schema_reread_count"]
        for r in rows
        if isinstance(r.get("avoidable_schema_reread_count"), int)
    ]
    out: dict[str, Any] = {
        "rows": len(rows),
        "correctness_known_rows": len(correctness),
        "correctness_pass": sum(correctness),
        "correctness_gate": bool(correctness) and len(correctness) == len(rows) and all(correctness),
        "fcr_known_rows": len(fcr),
        "fcr_ready": sum(fcr),
        "legacy_fcr_known_rows": len(legacy_fcr),
        "legacy_fcr_ready": sum(legacy_fcr),
        "wrong_tool_first_calls": _sum_known(rows, "wrong_tool_first_call_count"),
        "invalid_argument_rejections": _sum_known(rows, "invalid_argument_rejection_count"),
        "mechanical_contract_rejections": _sum_known(
            rows, "mechanical_contract_rejection_count"
        ),
        "runtime_failures": _sum_known(rows, "runtime_failure_count"),
        "rejected_calls": _sum_known(rows, "rejected_call_count"),
        "unexpected_failures": _sum_known(rows, "unexpected_failure_count"),
        "failure_to_repair": _sum_known(rows, "failure_to_repair_count"),
        "confirmed_effect_repairs": _sum_known(rows, "confirmed_effect_repair_count"),
        "schema_rereads": _sum_known(rows, "schema_reread_count"),
        "avoidable_schema_rereads_known_rows": len(avoidable_known),
        "avoidable_schema_rereads": sum(avoidable_known) if avoidable_known else None,
        "exact_duplicate_successes": _sum_known(rows, "exact_duplicate_success_count"),
        "redundant_reacquisitions": _sum_known(rows, "redundant_reacquisition_count"),
        "serial_tool_barriers": _sum_known(rows, "serial_tool_barrier_count"),
        "median_provider_rounds": _median(rows, "provider_rounds"),
        "median_tool_call_rounds": _median(rows, "tool_call_round_count"),
        "median_tool_calls": _median(rows, "tool_call_count"),
        "median_max_parallel_tool_width": _median(rows, "max_parallel_tool_width"),
        "median_uncached_input_tokens": _median(rows, "uncached_input_tokens"),
        "median_cache_hit_tokens": _median(rows, "cache_hit_tokens"),
        "median_output_tokens": _median(rows, "output_tokens"),
        "median_wall_s": _median(rows, "wall_s"),
        "history_compacted_rows": sum(bool(r.get("history_compacted")) for r in rows),
        "run_error_rows": sum(bool(r.get("run_error")) for r in rows),
        "run_incomplete_rows": sum(bool(r.get("run_incomplete")) for r in rows),
    }
    if arm is not None:
        out["arm"] = arm
    return out


def summarize(scored: list[dict[str, Any]], *, dataset: str = "") -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        by_arm[str(row.get("arm") or "")].append(row)
    return {
        "schema": "lfl-execution-efficiency-v2-summary/v0.1",
        "dataset": dataset,
        "objective_order": [
            "verified_correctness_hard_gate",
            "first_call_ready",
            "wrong_rejected_repair_calls",
            "serial_barriers_and_wall_time",
            "uncached_input_and_output_tokens",
        ],
        "weighted_score": None,
        "tool_count_is_not_an_optimization_target": True,
        "overall": _cell(scored),
        "by_arm": [_cell(by_arm[arm], arm=arm) for arm in sorted(by_arm)],
    }


def _load_tasks() -> dict[str, dict[str, Any]]:
    try:
        from evals.pilot.tasks import TASKS
    except Exception:
        return {}
    return {str(task.get("id") or ""): task for task in TASKS}


def score_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = _load_tasks()
    return [score_row(row, tasks.get(str(row.get("task_id") or ""))) for row in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--dataset", default="")
    ap.add_argument("--scored-output", type=Path)
    ap.add_argument("--summary-output", type=Path)
    args = ap.parse_args()
    rows = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scored = score_rows(rows)
    summary = summarize(scored, dataset=args.dataset or args.results.name)
    if args.scored_output:
        args.scored_output.parent.mkdir(parents=True, exist_ok=True)
        args.scored_output.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scored),
            encoding="utf-8",
        )
    payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.summary_output:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
