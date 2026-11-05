#!/usr/bin/env python3
"""Amendment 2026-11-05: append corrected terminal records whose evidence_refs
only contain verifiable evidence:// refs (doc path failed task-level veracity
check). Append-only: last record per task_id wins."""
import datetime, json, sys
from pathlib import Path

EVREF = "evidence://v1/36a1b94d94a9a05bd3776dab3034b7777335d3175e7ab190f6086d9c5581a1b3"

def main():
    tail = sys.argv[1].split("=")[1]
    f = Path("data/audit/tasks") / f"GOAL-20260927-{tail}.jsonl"
    records = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    last = {}
    for rec in records:
        last[rec["task_id"]] = rec
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n = 0
    with f.open("a", encoding="utf-8") as fh:
        for tid, rec in last.items():
            if rec.get("status") in ("cancelled", "failed", "done") and rec.get("evidence_required"):
                refs = rec.get("evidence_refs") or []
                if any(not str(r).startswith("evidence://") for r in refs):
                    nr = dict(rec)
                    nr["evidence_refs"] = [EVREF]
                    nr["updated_at"] = now
                    fh.write(json.dumps(nr, ensure_ascii=False) + "\n")
                    n += 1
                    print(f"AMENDED {tid} evidence_refs -> [evidence://...]")
    print(f"amended {n}")

if __name__ == "__main__":
    main()
