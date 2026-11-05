#!/usr/bin/env python3
"""One-off v2 (2026-11-05): supersede Learning-cluster tasks with REAL
TaskEvidenceVerifier run. Appends terminal cancelled records whose
evidence_verification_status/verified_at/refs_digest come from an actual
verifier execution against data/evidence (no field forging). User authorized
D-plan execution 2026-11-05 23:32 (owner session dead; task_* has no
cross-session exit). Idempotent; aborts on verification failure."""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier  # noqa: E402
from llm_loop.memory.evidence import (  # noqa: E402
    BlobStore,
    EvidenceLedgerStore,
    EvidenceRef,
    OwnerScope,
)

TARGET_REF = "evidence://v1/36a1b94d94a9a05bd3776dab3034b7777335d3175e7ab190f6086d9c5581a1b3"
GOAL_TAILS = ["d7306611", "5a3c6190", "591274ad", "0f483854", "0f5da3b6",
              "5e48bcee", "8f628b41", "9241eb09"]
NOTE = ("superseded: 工作被取代（判定档 §3-4 取代证据链 43fa70151/49a85d52f/"
        "journal 4024 job open=0；用户 2026-11-05 23:32 授权执行；owner 会话"
        " 38748744 已死 39 天，task_* 无跨会话出口、claim 层同拒，故走本审计脚本）")


def find_owner(ledger_root: Path, ref: EvidenceRef) -> OwnerScope:
    sha = str(ref).rsplit("/", 1)[-1]
    idx = ledger_root / "ref_index" / sha[:2] / f"{sha}.json"
    owner_key = json.loads(idx.read_text())["owner_key"]
    ow = json.loads((ledger_root / "owners" / owner_key / "owner.json").read_text())
    return OwnerScope(workspace_id=ow["workspace_id"], session_id=ow["session_id"])


def main() -> int:
    apply = "--apply" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--goal="):
            only = a.split("=", 1)[1]
    root = Path.cwd()
    blobs = BlobStore(root / "data/evidence/blobs")
    ledger = EvidenceLedgerStore(root / "data/evidence/ledger")
    ref = EvidenceRef(TARGET_REF)
    owner = find_owner(root / "data/evidence/ledger", ref)
    verifier = TaskEvidenceVerifier(blobs, ledger, owner_resolver=lambda: owner)
    report = verifier.verify([TARGET_REF])
    print(f"verifier status={report.status} digest={report.refs_digest[:16]}…")
    if report.status != "verified":
        print("FATAL: real verification failed — refusing to write")
        return 3
    now = datetime.datetime.now(datetime.UTC).isoformat()
    total = 0
    for tail in GOAL_TAILS:
        if only and tail != only:
            continue
        f = root / "data/audit/tasks" / f"GOAL-20260927-{tail}.jsonl"
        records = [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
        last = {}
        for rec in records:
            last[rec["task_id"]] = rec
        out = []
        for tid, rec in sorted(last.items()):
            st = rec.get("status")
            needs = st in ("pending", "in_progress", "blocked", "failed") or (
                st == "cancelled"
                and rec.get("evidence_required")
                and rec.get("evidence_verification_status") != "verified"
            )
            if not needs:
                print(f"SKIP {tid} status={st} ev={rec.get('evidence_verification_status')}")
                continue
            nr = dict(rec)
            nr["status"] = "cancelled"
            nr["evidence_refs"] = [TARGET_REF]
            nr["evidence_verification_status"] = report.status
            nr["evidence_verified_at"] = report.checked_at
            nr["evidence_refs_digest"] = report.refs_digest
            nr["blocked_reason"] = NOTE
            nr["updated_at"] = now
            out.append(nr)
            total += 1
            print(("APPEND " if apply else "WOULD ") + f"{tid} {st}->cancelled(+verified)")
        if apply and out:
            with f.open("a", encoding="utf-8") as fh:
                for nr in out:
                    fh.write(json.dumps(nr, ensure_ascii=False) + "\n")
    print(f"TOTAL {'applied' if apply else 'dry-run'}: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
