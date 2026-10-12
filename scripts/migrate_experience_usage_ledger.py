#!/usr/bin/env python3
"""EVO-20261011-945fc53c 方案B：一次性回放迁移.

把事件流 data/event_logs/*.jsonl 中 type=knowledge.experience_declaration 的
历史使用声明，回放进经验使用账本 experiences/usage.jsonl（真值源）。
幂等键 knowledge_event_key，可安全重跑。迁移后事件流降级为观察通道。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.experiences.store import ExperienceStore  # noqa: E402

EVENT_DIR = ROOT / "data" / "event_logs"


def main() -> int:
    store = ExperienceStore(experiences_dir=str(ROOT / "experiences"))
    events = []
    for path in sorted(EVENT_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or "knowledge.experience_declaration" not in line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                print(f"[skip] unparseable line in {path.name}")
                continue
            if evt.get("type") == "knowledge.experience_declaration":
                events.append(evt)
    events.sort(key=lambda e: (str(e.get("ts", "")), str(e.get("seq", 0))))

    before = len(store.usage_entries(limit=200))
    migrated = skipped = 0
    for evt in events:
        payload = evt.get("payload") or {}
        ref = str(payload.get("ref") or "")
        decision = str(payload.get("decision") or "")
        key = str(payload.get("knowledge_event_key") or "")
        if not ref or not decision or not key:
            print(f"[skip] event missing ref/decision/key: {evt.get('event_id')}")
            skipped += 1
            continue
        entry = {
            "ts": str(evt.get("ts", "")),
            "experience_ref": ref,
            "id": ref.removeprefix("experience:"),
            "record_kind": str(payload.get("record_kind", "experience")),
            "verification_state": str(
                payload.get("verification_state", "legacy_unclassified")
            ),
            "status": "active",
            "use_decision": decision,
            "note": "",
            "evidence_refs": [],
            "document_projection_sha256": str(
                payload.get("document_projection_sha256", "")
            ),
            "episode_ref": "",
            "session_id": str(evt.get("session_id", "")),
            "model": "",
            "application_proven": decision in {"applied", "adapted"},
            "authority": "model_declared",
            "task_benefit": "not_evaluated",
            "knowledge_event_key": key,
            "hydration_observed": bool(payload.get("hydration_observed", False)),
        }
        store.record_migrated_entry(entry)
        migrated += 1

    after = store.usage_entries(limit=200)
    integrity = store.check_usage_integrity()
    print(
        json.dumps(
            {
                "events_found": len(events),
                "migrated_calls": migrated,
                "skipped_invalid": skipped,
                "ledger_before": before,
                "ledger_after": len(after),
                "new_rows": len(after) - before,
                "integrity": integrity,
                "ledger_path": str(store.usage_ledger_path()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # 首跑: new_rows == len(events)-skipped；幂等重跑: new_rows == 0。
    # 断言只约束不变量：不丢行、不重复（after-before ∈ {0, len(events)-skipped}）。
    valid = len(after) - before in (0, len(events) - skipped)
    assert valid and integrity.get("lost", -1) == 0, "migration invariant broken"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
