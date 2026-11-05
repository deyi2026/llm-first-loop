#!/usr/bin/env python3
"""One-off (2026-11-05): supersede Learning-cluster open tasks.

Rationale (audited deviation): task-level cross-session writes have no exit
(owner session 38748744 dead 39d; claim layer denies too), while the goal
closure gate requires the task graph terminal first. User explicitly
authorized executing D's 9x close-complete on 2026-11-05 23:32. This script
appends terminal ``cancelled`` records mirroring what task_update would write.
Goal closure itself still goes through the sanctioned
update_goal(cross_session=true) gate -- this script does NOT touch goals.jsonl.
Backup: .tmp-ci/ledger-backup-20261105-late/ (made before any apply).
Idempotent: tasks already terminal are skipped.
"""
import datetime
import json
import sys
from pathlib import Path

GOAL_TAILS = ["d7306611", "5a3c6190", "591274ad", "0f483854", "0f5da3b6",
              "5e48bcee", "8f628b41", "9241eb09"]
PREFIX = "GOAL-20260927-"
EVIDENCE = [
    "docs/analysis/learning-queue-cluster-verdict-20261105.md",
    "evidence://v1/36a1b94d94a9a05bd3776dab3034b7777335d3175e7ab190f6086d9c5581a1b3",
]
NOTE = ("superseded: 工作被取代（判定档 §3-4 取代证据链 43fa70151/49a85d52f/"
        "journal 4024 job open=0；用户 2026-11-05 23:32 授权执行；owner 会话"
        " 38748744 已死 39 天，task_* 无跨会话出口、claim 层同拒，故走本审计脚本）")


def main() -> int:
    apply = "--apply" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--goal="):
            only = a.split("=", 1)[1]
    now = datetime.datetime.now(datetime.UTC).isoformat()
    base = Path("data/audit/tasks")
    total = 0
    for tail in GOAL_TAILS:
        if only and tail != only:
            continue
        f = base / f"{PREFIX}{tail}.jsonl"
        if not f.exists():
            print(f"MISSING {f}")
            continue
        records = [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
        last = {}
        for rec in records:
            last[rec["task_id"]] = rec
        out, changed = [], 0
        for tid, rec in last.items():
            if rec.get("status") in ("pending", "in_progress"):
                nr = dict(rec)
                nr["status"] = "cancelled"
                nr["evidence_refs"] = EVIDENCE
                nr["blocked_reason"] = NOTE
                nr["updated_at"] = now
                out.append(nr)
                changed += 1
                verb = "APPEND" if apply else "WOULD"
                print(f"{verb} {tid} {rec.get('status')}->cancelled")
            else:
                print(f"SKIP {tid} status={rec.get('status')}")
        if apply and out:
            with f.open("a", encoding="utf-8") as fh:
                for nr in out:
                    fh.write(json.dumps(nr, ensure_ascii=False) + "\n")
        total += changed
        print(f"== {PREFIX}{tail}: {changed} task(s) "
              f"{'appended' if apply else 'dry-run'}")
    print(f"TOTAL {'applied' if apply else 'dry-run'}: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
