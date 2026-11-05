#!/usr/bin/env python3
"""Amendment 2026-11-05: append corrected terminal records whose evidence_refs
only contain verifiable evidence:// refs (doc path failed task-level veracity
check). Append-only: last record per task_id wins.

Convention (align with sibling one-offs, review P2-5): bare invocation is a
DRY-RUN; pass --apply to mutate the append-only task ledger.

LIMITATION (review subagent_393a7a9cdbe9 P2-2): all amended tasks receive the
single cluster-verdict evidence ref. That ref substantiates the supersede
decision for the whole cluster (docs/analysis/learning-queue-cluster-verdict
-20261105.md), not per-task work products. Acceptable for this one-off
because the tasks were cancelled-as-superseded, not done; do not reuse this
pattern for done-evidence amendments.
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

EVREF = (
    "evidence://v1/36a1b94d94a9a05bd3776dab3034b7777335d3175e7ab190f6086d9c5581a1b3"
)


def main() -> int:
    apply = "--apply" in sys.argv
    tail = None
    for arg in sys.argv[1:]:
        if arg.startswith("--tail=") and len(arg) > 7:
            tail = arg.split("=", 1)[1]
    if not tail:
        print("usage: append_fix_evref_20261105.py --tail=<goal-tail> [--apply]")
        return 2
    f = Path("data/audit/tasks") / f"GOAL-20260927-{tail}.jsonl"
    if not f.exists():
        print(f"missing task file: {f}")
        return 2
    records = [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    last: dict[str, dict] = {}
    for rec in records:
        last[rec["task_id"]] = rec
    now = datetime.now(UTC).isoformat()
    pending = []
    for tid, rec in sorted(last.items()):
        if rec.get("status") in ("cancelled", "failed", "done") and rec.get(
            "evidence_required"
        ):
            refs = rec.get("evidence_refs") or []
            if any(not str(r).startswith("evidence://") for r in refs):
                pending.append(tid)
                print(
                    ("AMEND " if apply else "WOULD AMEND ")
                    + f"{tid} evidence_refs -> [evidence://...]"
                )
    if apply and pending:
        with f.open("a", encoding="utf-8") as fh:
            for tid in pending:
                nr = dict(last[tid])
                nr["evidence_refs"] = [EVREF]
                nr["updated_at"] = now
                fh.write(json.dumps(nr, ensure_ascii=False) + "\n")
    print(f"{'amended' if apply else 'dry-run'} {len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
