#!/usr/bin/env python3
"""Post-run EEv2.1 analyzer for the frozen v0.1 A/B matrix.

The real-model matrix was frozen and executed by ``freeze_v0_1.py`` / ``run_v0_1.py``.
This module does not change the frozen treatment or task protocol.  It validates the
recorded provenance/wire facts, re-scores rows with the frozen EEv2 scorer, and emits
a compact descriptive qualification result.

The decision intentionally stops at ``QUALIFIED_FOR_REPLICATION_NOT_PRODUCTION``.
The sample is small, provider cache behavior was observed rather than controlled, and
the treatment has not yet been replicated on the current default runtime model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from evals.execution_efficiency_v2.scorer import score_row
from evals.execution_efficiency_v2.surfaces_v0_1 import ARMS_V0_1
from evals.execution_efficiency_v2.tasks_v0_1 import (
    TASK_BY_ID_V0_1,
    schedule_v0_1,
)

HERE = Path(__file__).resolve().parent
BASE = "A-current"
CANDIDATE = "B-portability-contract"
PORTABILITY_MARKERS = (
    "illegal option",
    "invalid option",
    "unknown primary or operator",
    "unrecognized option",
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        row.get(key)
        for row in rows
        if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
    ]
    return float(statistics.median(values)) if values else None


def _sum(rows: list[dict[str, Any]], key: str) -> int:
    return sum(int(row.get(key) or 0) for row in rows)


def _host_portability_failures(raw: dict[str, Any]) -> int:
    if raw.get("family") != "portability":
        return 0
    count = 0
    for call in ((raw.get("fcr_events") or {}).get("calls") or []):
        if call.get("name") != "execute_command" or call.get("ok") is not False:
            continue
        result = str(call.get("result") or "").lower()
        if any(marker in result for marker in PORTABILITY_MARKERS):
            count += 1
    return count


def _cell(scored: list[dict[str, Any]], arm: str, family: str = "all") -> dict[str, Any]:
    rows = [
        row
        for row in scored
        if row["arm"] == arm and (family == "all" or row["family"] == family)
    ]
    return {
        "arm": arm,
        "family": family,
        "rows": len(rows),
        "correct": sum(row.get("correctness_pass") is True for row in rows),
        "fcr": sum(row.get("first_call_ready") is True for row in rows),
        "wrong_first": _sum(rows, "wrong_tool_first_call_count"),
        "oracle_arg_mismatches": _sum(rows, "first_action_oracle_arg_mismatch_count"),
        "contract_rejections": _sum(rows, "mechanical_contract_rejection_count"),
        "runtime_failures": _sum(rows, "runtime_failure_count"),
        "repairs": _sum(rows, "failure_to_repair_count"),
        "schema_rereads": _sum(rows, "schema_reread_count"),
        "redundant_reacquisitions": _sum(rows, "redundant_reacquisition_count"),
        "serial_barriers": _sum(rows, "serial_tool_barrier_count"),
        "median_rounds": _median(rows, "provider_rounds"),
        "median_tools": _median(rows, "tool_call_count"),
        "median_wall_s": _median(rows, "wall_s"),
        "median_uncached_input_tokens": _median(rows, "uncached_input_tokens"),
        "median_cache_hit_tokens": _median(rows, "cache_hit_tokens"),
        "median_output_tokens": _median(rows, "output_tokens"),
    }


def _validate_source_hashes(manifest: dict[str, Any]) -> dict[str, bool]:
    expected = {
        "scorer.py": manifest.get("scorer_sha256"),
        "tasks_v0_1.py": manifest.get("task_source_sha256"),
        "surfaces_v0_1.py": manifest.get("surface_source_sha256"),
        "run_v0_1.py": manifest.get("runner_source_sha256"),
    }
    return {
        name: bool(want) and _sha_file(HERE / name) == want
        for name, want in expected.items()
    }


def _expected_row_ids() -> set[str]:
    return {
        f"{task['id']}__{arm}__r{repeat}"
        for task, arm, repeat in schedule_v0_1()
    }


def _wire_row_ok(row: dict[str, Any], manifest: dict[str, Any]) -> tuple[bool, bool, bool]:
    surface = manifest["surface_facts"][row["arm"]]
    traces = list(row.get("wire_records") or [])
    surface_ok = bool(traces) and all(
        int(trace.get("tools_n") or 0) == int(surface["effective_tool_count"])
        and str(trace.get("tools_hash") or "") == surface["openai_tools_hash16"]
        for trace in traces
    )
    model_ok = bool(traces) and all(
        str(trace.get("model") or "") == str(manifest["resolved_model"])
        for trace in traces
    )
    cache_rows = list(row.get("cache_wire_records") or [])
    cache_surface_ok = bool(cache_rows) and len(cache_rows) == len(traces) and all(
        int(cache.get("tools_n") or 0) == int(surface["effective_tool_count"])
        and str(cache.get("tools_hash16") or "") == surface["openai_tools_hash16"]
        for cache in cache_rows
    )
    return surface_ok, model_ok, cache_surface_ok


def _paired_portability(
    raw_rows: list[dict[str, Any]], scored_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    raw_by_id = {row["row_id"]: row for row in raw_rows}
    scored_by = {
        (row["task_id"], row.get("repeat"), row["arm"]): row
        for row in scored_rows
    }
    raw_by = {
        (row["task_id"], row.get("repeat"), row["arm"]): row
        for row in raw_rows
    }
    pairs: list[dict[str, Any]] = []
    for task_id in sorted(
        task["id"] for task in TASK_BY_ID_V0_1.values() if task["family"] == "portability"
    ):
        for repeat in (1, 2, 3):
            a_raw = raw_by[(task_id, repeat, BASE)]
            b_raw = raw_by[(task_id, repeat, CANDIDATE)]
            a = scored_by[(task_id, repeat, BASE)]
            b = scored_by[(task_id, repeat, CANDIDATE)]
            row = {
                "task_id": task_id,
                "repeat": repeat,
                "a_host_portability_failures": _host_portability_failures(a_raw),
                "b_host_portability_failures": _host_portability_failures(b_raw),
            }
            for key in (
                "runtime_failure_count",
                "serial_tool_barrier_count",
                "provider_rounds",
                "wall_s",
                "uncached_input_tokens",
            ):
                av = a.get(key)
                bv = b.get(key)
                row[f"a_{key}"] = av
                row[f"b_{key}"] = bv
                row[f"delta_{key}"] = (
                    None
                    if not isinstance(av, (int, float)) or not isinstance(bv, (int, float))
                    else bv - av
                )
            pairs.append(row)

    def delta_summary(key: str) -> dict[str, Any]:
        values = [
            pair[key]
            for pair in pairs
            if isinstance(pair.get(key), (int, float))
        ]
        return {
            "sum": sum(values),
            "median": float(statistics.median(values)),
            "mean": float(statistics.mean(values)),
            "improved_pairs": sum(value < 0 for value in values),
            "same_pairs": sum(value == 0 for value in values),
            "worse_pairs": sum(value > 0 for value in values),
        }

    return {
        "pairs": pairs,
        "host_portability_failure_rows": {
            "A": sum(pair["a_host_portability_failures"] > 0 for pair in pairs),
            "B": sum(pair["b_host_portability_failures"] > 0 for pair in pairs),
            "A_only": sum(
                pair["a_host_portability_failures"] > 0
                and pair["b_host_portability_failures"] == 0
                for pair in pairs
            ),
            "B_only": sum(
                pair["a_host_portability_failures"] == 0
                and pair["b_host_portability_failures"] > 0
                for pair in pairs
            ),
            "both": sum(
                pair["a_host_portability_failures"] > 0
                and pair["b_host_portability_failures"] > 0
                for pair in pairs
            ),
        },
        "delta_runtime_failures": delta_summary("delta_runtime_failure_count"),
        "delta_serial_barriers": delta_summary("delta_serial_tool_barrier_count"),
        "delta_provider_rounds": delta_summary("delta_provider_rounds"),
        "delta_wall_s": delta_summary("delta_wall_s"),
        "delta_uncached_input_tokens": delta_summary("delta_uncached_input_tokens"),
        "raw_row_ids_present": len(raw_by_id),
    }


def analyze(
    manifest_path: Path,
    raw_path: Path,
    *,
    wire_path: Path | None = None,
    cache_wire_path: Path | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_rows = _load_jsonl(raw_path)
    source_hashes = _validate_source_hashes(manifest)
    expected_ids = _expected_row_ids()
    actual_ids = [str(row.get("row_id") or "") for row in raw_rows]
    shape_gate = (
        len(raw_rows) == int(manifest.get("row_count") or 0) == 36
        and len(actual_ids) == len(set(actual_ids))
        and set(actual_ids) == expected_ids
    )

    scored_rows: list[dict[str, Any]] = []
    wire_surface_rows = 0
    wire_model_rows = 0
    cache_surface_rows = 0
    provider_model_rows = 0
    run_error_rows = 0
    for raw in raw_rows:
        task = TASK_BY_ID_V0_1[str(raw.get("task_id") or "")]
        scored = score_row(raw, task)
        scored["repeat"] = raw.get("repeat")
        scored["host_portability_failure_count"] = _host_portability_failures(raw)
        scored_rows.append(scored)
        surface_ok, model_ok, cache_ok = _wire_row_ok(raw, manifest)
        wire_surface_rows += int(surface_ok)
        wire_model_rows += int(model_ok)
        cache_surface_rows += int(cache_ok)
        provider_model_rows += int(
            raw.get("resolved_provider") == manifest.get("resolved_provider")
            and raw.get("resolved_model") == manifest.get("resolved_model")
            and raw.get("wire_protocol") == manifest.get("wire_protocol")
            and raw.get("reasoning_effort") == manifest.get("reasoning_effort")
        )
        run_error_rows += int(bool(raw.get("run_error")))

    cells = [
        _cell(scored_rows, arm, family)
        for family in ("all", "portability", "wrong_tool", "edit_control")
        for arm in ARMS_V0_1
    ]
    cell = {(item["arm"], item["family"]): item for item in cells}
    a_all = cell[(BASE, "all")]
    b_all = cell[(CANDIDATE, "all")]
    a_port = cell[(BASE, "portability")]
    b_port = cell[(CANDIDATE, "portability")]
    a_wrong = cell[(BASE, "wrong_tool")]
    b_wrong = cell[(CANDIDATE, "wrong_tool")]
    a_edit = cell[(BASE, "edit_control")]
    b_edit = cell[(CANDIDATE, "edit_control")]
    paired = _paired_portability(raw_rows, scored_rows)

    provenance_gate = all(source_hashes.values())
    wire_gate = (
        wire_surface_rows == 36
        and wire_model_rows == 36
        and cache_surface_rows == 36
        and provider_model_rows == 36
        and run_error_rows == 0
    )
    correctness_gate = a_all["correct"] == 18 and b_all["correct"] == 18
    fcr_no_regression = b_all["fcr"] >= a_all["fcr"]
    portability_activation = (
        paired["host_portability_failure_rows"]["A"]
        > paired["host_portability_failure_rows"]["B"]
        and paired["host_portability_failure_rows"]["B_only"] == 0
    )
    portability_efficiency_direction = (
        b_port["repairs"] <= a_port["repairs"]
        and b_port["serial_barriers"] <= a_port["serial_barriers"]
        and b_port["median_wall_s"] <= a_port["median_wall_s"]
    )
    wrong_tool_no_regression = b_wrong["wrong_first"] <= a_wrong["wrong_first"]
    edit_control_no_regression = (
        b_edit["correct"] >= a_edit["correct"]
        and b_edit["fcr"] >= a_edit["fcr"]
    )
    replication_qualified = all(
        (
            provenance_gate,
            shape_gate,
            wire_gate,
            correctness_gate,
            fcr_no_regression,
            portability_activation,
            portability_efficiency_direction,
            wrong_tool_no_regression,
            edit_control_no_regression,
        )
    )

    result = {
        "schema": "lfl-execution-efficiency-v2.1-result/v0.1",
        "decision": (
            "QUALIFIED_FOR_REPLICATION_NOT_PRODUCTION"
            if replication_qualified
            else "NOT_QUALIFIED"
        ),
        "production_change_authorized": False,
        "weighted_score": None,
        "tool_count_is_not_an_optimization_target": True,
        "artifacts": {
            "manifest": {"path": str(manifest_path), "sha256": _sha_file(manifest_path)},
            "raw": {"path": str(raw_path), "sha256": _sha_file(raw_path)},
            "wire": (
                {"path": str(wire_path), "sha256": _sha_file(wire_path)}
                if wire_path
                else None
            ),
            "cache_wire": (
                {"path": str(cache_wire_path), "sha256": _sha_file(cache_wire_path)}
                if cache_wire_path
                else None
            ),
        },
        "frozen_manifest": {
            "git_head": manifest.get("git_head"),
            "model_ref": manifest.get("model_ref"),
            "runtime_default_model_ref": manifest.get("runtime_default_model_ref"),
            "resolved_provider": manifest.get("resolved_provider"),
            "resolved_model": manifest.get("resolved_model"),
            "reasoning_effort": manifest.get("reasoning_effort"),
            "row_count": manifest.get("row_count"),
            "tool_set_equal": manifest.get("tool_set_equal"),
            "surface_delta_chars": manifest.get("surface_delta_chars"),
            "semantic_tool_hiding": manifest.get("semantic_tool_hiding"),
            "cache_treatment": manifest.get("cache_treatment"),
        },
        "gates": {
            "source_hashes": source_hashes,
            "provenance_gate": provenance_gate,
            "shape_gate": shape_gate,
            "wire_gate": wire_gate,
            "wire_surface_rows": wire_surface_rows,
            "wire_model_rows": wire_model_rows,
            "cache_surface_rows": cache_surface_rows,
            "provider_model_rows": provider_model_rows,
            "run_error_rows": run_error_rows,
            "correctness_gate": correctness_gate,
            "fcr_no_regression": fcr_no_regression,
            "portability_activation": portability_activation,
            "portability_efficiency_direction": portability_efficiency_direction,
            "wrong_tool_no_regression": wrong_tool_no_regression,
            "edit_control_no_regression": edit_control_no_regression,
        },
        "by_arm_family": cells,
        "paired_portability": paired,
        "interpretation": {
            "target_signal": (
                "host-portability failure rows fell from 4/9 to 1/9; no B-only portability "
                "failure pair was observed"
            ),
            "wrong_tool_holdout": (
                "all 6 rows per arm selected the pre-registered exact first tool, so the "
                "holdout proves no regression but provides no wrong-tool error-reduction headroom"
            ),
            "edit_control": (
                "both arms are 1/3 exact-first FCR because two repeats start with search_files "
                "before read_file(snapshot=true); correctness remains 3/3 in both arms, so this "
                "control is symmetric but the exact-first oracle is stricter than the natural task"
            ),
            "cache": (
                "provider-default cache was observed, not controlled; cache_prompt is absent on "
                "the resolved DeepSeek wire. Cache/token values are descriptive, not a promotion gate"
            ),
            "tokens": (
                "median portability uncached input improves, but the paired mean worsens because one "
                "B row has a large +7438-token outlier; token benefit is not established"
            ),
        },
        "limitations": [
            "single resolved model/provider: deepseek/deepseek-flash",
            "current runtime default cognilocal/qwen3.8-flash-next not yet replicated",
            "three repeats per task; portability discordance is directional rather than high-power statistical evidence",
            "provider-default cache not experimentally controlled",
            "wrong-tool prompts explicitly constrain the intended tool and therefore test adherence more than natural discovery",
            "edit-control exact-first oracle treats search_files prelude as a miss even though it can be a legitimate locator step",
        ],
        "next_experiment": {
            "name": "EEv2.2 replication",
            "keep_all_healthy_tools_visible": True,
            "treatment": "same +117-char execute_command portability contract",
            "requirements": [
                "replicate on current default cognilocal/qwen3.8-flash-next",
                "retain the same portability family for paired comparability",
                "add naturalistic wrong-tool holdouts that do not name the desired tool in the prompt",
                "pre-register a side-step policy for locator/search calls before the edit-control exact action",
                "keep correctness/FCR/reject/repair/barrier/wall/token metrics separate",
            ],
        },
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--wire", type=Path)
    ap.add_argument("--cache-wire", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    result = analyze(
        args.manifest,
        args.raw,
        wire_path=args.wire,
        cache_wire_path=args.cache_wire,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
