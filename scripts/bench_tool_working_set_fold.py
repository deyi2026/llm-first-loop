#!/usr/bin/env python3
"""Deterministic P1 active-run working-set fold benchmark.

The fixture never calls a provider and never judges evidence relevance.  It feeds a
fixed assistant(tool_calls)->tool sequence through the production projection and
measures representation size plus byte-prefix continuity between consecutive
provider views.  Output is JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from llm_loop.core.episode_history import project_active_tool_working_set_with_stats
from llm_loop.core.message import Message, MessageSource, ToolResultStatus


def _assistant(call_id: str, round_no: int, closure_marker_round: int) -> Message:
    marker = ""
    if round_no == closure_marker_round:
        marker = " I now have enough evidence; one narrow verification remains."
    return Message(
        role="assistant",
        content=f"Evidence is accumulating. round={round_no}.{marker}",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
        model_used="cognilocal/ornith",
        metadata={"answer_origin": "model"},
    )


def _tool(call_id: str, round_no: int, raw_chars: int) -> Message:
    prefix = f"ROUND={round_no};FACT=root-cause-{round_no};"
    text = prefix + chr(65 + round_no % 26) * max(0, raw_chars - len(prefix))
    return Message(
        role="tool",
        content=text,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name="read_file",
        metadata={
            "recoverability_status": "recorded",
            "evidence_ref": f"evidence://v1/synth-{round_no}",
            "evidence_representation": "excerpt",
            "evidence_projection_complete": False,
            "evidence_source_label": f"read_file:src/f{round_no}.py",
            "evidence_coverage_label": "source_line:0-200",
        },
    )


def _wire(messages: list[Message]) -> str:
    return "\n".join(
        json.dumps(
            message.to_llm_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for message in messages
    )


def _lcp(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    idx = 0
    while idx < limit and a[idx] == b[idx]:
        idx += 1
    return idx


def run_case(
    *,
    batch_chars: int,
    grace_groups: int,
    soft_result_cap: int,
    hard_result_cap: int,
    min_net_gain_chars: int,
    rounds: int,
    raw_chars_per_result: int,
    closure_marker_round: int,
) -> dict[str, Any]:
    os.environ["LFL_TOOL_WORKING_SET_RECEIPTS"] = "1"
    os.environ["LFL_TOOL_WORKING_SET_BATCH_CHARS"] = str(batch_chars)
    os.environ["LFL_TOOL_WORKING_SET_GRACE_GROUPS"] = str(grace_groups)
    os.environ["LFL_TOOL_WORKING_SET_SOFT_RESULT_CAP"] = str(soft_result_cap)
    os.environ["LFL_TOOL_WORKING_SET_HARD_RESULT_CAP"] = str(hard_result_cap)
    os.environ["LFL_TOOL_WORKING_SET_MIN_NET_GAIN_CHARS"] = str(min_net_gain_chars)
    messages = [Message(role="user", content="synthetic task", source=MessageSource.USER)]
    previous_wire = _wire(messages)
    previous_folded = 0
    rows: list[dict[str, Any]] = []
    for round_no in range(1, rounds + 1):
        call_id = f"c{round_no}"
        messages.extend(
            [
                _assistant(call_id, round_no, closure_marker_round),
                _tool(call_id, round_no, raw_chars_per_result),
            ]
        )
        projected, stats = project_active_tool_working_set_with_stats(messages)
        current_wire = _wire(projected)
        prefix_chars = _lcp(previous_wire, current_wire)
        new_fold = stats.folded_results > previous_folded
        rows.append(
            {
                "round": round_no,
                "new_fold": new_fold,
                "folded_results": stats.folded_results,
                "folded_groups": stats.folded_groups,
                "raw_tool_chars": stats.raw_tool_chars,
                "projected_tool_chars": stats.projected_tool_chars,
                "receipt_chars": stats.receipt_chars,
                "grace_raw_chars": stats.grace_raw_chars,
                "grace_results": stats.grace_results,
                "pending_raw_chars": stats.pending_raw_chars,
                "pending_receipt_chars": stats.pending_receipt_chars,
                "pending_net_gain_chars": stats.pending_net_gain_chars,
                "pending_results": stats.pending_results,
                "latest_raw_chars": stats.latest_raw_chars,
                "fold_boundaries": list(stats.fold_boundaries),
                "fold_triggers": list(stats.fold_triggers),
                "prev_wire_chars": len(previous_wire),
                "wire_chars": len(current_wire),
                "lcp_chars": prefix_chars,
                "prefix_retained_ratio": round(
                    prefix_chars / max(1, len(previous_wire)), 6
                ),
                "closure_marker_already_present": round_no > closure_marker_round,
            }
        )
        previous_wire = current_wire
        previous_folded = stats.folded_results
    final = rows[-1]
    fold_rows = [row for row in rows if row["new_fold"]]
    return {
        "batch_chars": batch_chars,
        "grace_groups": grace_groups,
        "soft_result_cap": soft_result_cap,
        "hard_result_cap": hard_result_cap,
        "min_net_gain_chars": min_net_gain_chars,
        "rounds": rounds,
        "raw_chars_per_result": raw_chars_per_result,
        "closure_marker_round": closure_marker_round,
        "final_raw_tool_chars": final["raw_tool_chars"],
        "final_projected_tool_chars": final["projected_tool_chars"],
        "compression_ratio": round(
            final["projected_tool_chars"] / max(1, final["raw_tool_chars"]), 6
        ),
        "mean_projected_tool_chars": round(
            sum(row["projected_tool_chars"] for row in rows) / len(rows), 3
        ),
        "new_fold_count": len(fold_rows),
        "fold_rounds": [row["round"] for row in fold_rows],
        "fold_triggers": [row["fold_triggers"] for row in fold_rows],
        "fold_prefix_retained": [
            row["prefix_retained_ratio"] for row in fold_rows
        ],
        "post_fold_next_round_prefix_retained": [
            rows[row["round"]]["prefix_retained_ratio"]
            for row in fold_rows
            if row["round"] < len(rows)
        ],
        "fold_after_closure_marker_rounds": [
            row["round"]
            for row in fold_rows
            if row["closure_marker_already_present"]
        ],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-chars", type=int, nargs="+", default=[16384, 32768, 65536, 131072])
    parser.add_argument("--grace-groups", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    parser.add_argument("--soft-result-cap", type=int, default=12)
    parser.add_argument("--hard-result-cap", type=int, default=32)
    parser.add_argument("--min-net-gain-chars", type=int, default=16384)
    parser.add_argument("--rounds", type=int, default=18)
    parser.add_argument("--raw-chars", type=int, default=12000)
    parser.add_argument("--closure-marker-round", type=int, default=8)
    args = parser.parse_args()
    results = [
        run_case(
            batch_chars=batch,
            grace_groups=grace,
            soft_result_cap=args.soft_result_cap,
            hard_result_cap=args.hard_result_cap,
            min_net_gain_chars=args.min_net_gain_chars,
            rounds=args.rounds,
            raw_chars_per_result=args.raw_chars,
            closure_marker_round=args.closure_marker_round,
        )
        for batch in args.batch_chars
        for grace in args.grace_groups
    ]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
