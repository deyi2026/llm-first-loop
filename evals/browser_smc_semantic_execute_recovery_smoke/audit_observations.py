"""Read-only, content-free facts from durable browser smoke evidence.

Missing sources remain unknown. Terminal action IDs are counted once; text
occurrences and running receipts are not independent normalization events.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    records = []
    malformed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("non-object record")
            records.append(item)
        except ValueError:
            malformed += 1
    return records, malformed


def audit_data(data_dir: Path) -> dict[str, Any]:
    logs = sorted((data_dir / "event_logs").glob("*.jsonl"))
    if len(logs) != 1:
        return {"coverage": "unknown", "event_log_count": len(logs)}
    events, malformed = read_jsonl(logs[0])
    partials: collections.Counter[int] = collections.Counter()
    drafts: set[int] = set()
    dispatched: set[int] = set()
    timestamps: dict[int, list[str]] = {}
    for event in events:
        payload = event.get("payload") or {}
        rd = payload.get("round")
        if not isinstance(rd, int):
            continue
        if event.get("type") == "llm.partial_checkpoint":
            partials[rd] += 1
            timestamps.setdefault(rd, []).append(str(event.get("ts") or ""))
            if int(payload.get("tool_call_draft_count") or 0) > 0:
                drafts.add(rd)
        elif event.get("type") == "tool.execution.declared":
            dispatched.add(rd)
    terminal: dict[str, dict[str, Any]] = {}
    receipt_hashes = []
    for path in sorted((data_dir / "browser_action").rglob("receipts.jsonl")):
        records, errors = read_jsonl(path)
        malformed += errors
        receipt_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        for receipt in records:
            if receipt.get("status") in {"ok", "failed", "rejected"}:
                terminal[str(receipt["action_id"])] = receipt
    receipts = list(terminal.values())
    return {
        "coverage": "partial" if malformed else "available_prefix",
        "malformed_records": malformed,
        "event_log_sha256": hashlib.sha256(logs[0].read_bytes()).hexdigest(),
        "receipt_source_sha256": sorted(receipt_hashes),
        "run_end_observed": any(e.get("type") == "run.end" for e in events),
        "partial_checkpoint_count": sum(partials.values()),
        "decided_but_not_dispatched_rounds": len(drafts - dispatched),
        "partial_only_loop_rounds": sum(
            count >= 10 and rd not in drafts and rd not in dispatched
            for rd, count in partials.items()
        ),
        "rounds": [
            {
                "round": rd,
                "partial_count": partials[rd],
                "draft_observed": rd in drafts,
                "dispatch_declared": rd in dispatched,
                "first_partial_at": timestamps[rd][0],
                "last_partial_at": timestamps[rd][-1],
            }
            for rd in sorted(partials)
        ],
        "navigate_ok_count": sum(
            r.get("status") == "ok" and r.get("verb") == "navigate" for r in receipts
        ),
        "object_ok_count": sum(
            r.get("status") == "ok" and r.get("verb") in {"click", "fill", "select", "scroll"}
            for r in receipts
        ),
        "normalized_terminal_action_count": sum(
            (r.get("args_normalization") or {}).get("applied") is True for r in receipts
        ),
        "terminal_action_count": len(receipts),
    }


def audit_run(root: Path) -> dict[str, Any]:
    records, malformed = read_jsonl(root / "results.jsonl")
    rows = [
        {
            "index": r["index"],
            "run_id": r["run_id"],
            "status": r["status"],
            "facts": audit_data(root / r["run_id"] / ".lfldata"),
        }
        for r in records
    ]
    covered = all(r["facts"]["coverage"] == "available_prefix" for r in rows)
    return {
        "schema": "smc.fc1.observation_audit.v1",
        "source_results_sha256": hashlib.sha256((root / "results.jsonl").read_bytes()).hexdigest(),
        "malformed_result_records": malformed,
        "rows": rows,
        "all_rows_covered": covered,
        "partial_checkpoint_total": sum(r["facts"]["partial_checkpoint_count"] for r in rows)
        if covered
        else None,
        "navigate_ok_rows": sum(r["facts"]["navigate_ok_count"] > 0 for r in rows)
        if covered
        else None,
        "rows_partial_only_loop": sum(r["facts"]["partial_only_loop_rounds"] > 0 for r in rows)
        if covered
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_run(args.run_dir)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
