from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.evidence.r4.fixtures import FIXTURES

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tests/fixtures/evidence_r4/fixtures_v1.json"

payload = {
    "schema": "evidence-r4-fixtures-v1",
    "fixtures": {
        key: {
            "seed_id": f.seed_id,
            "title": f.title,
            "source_kind": f.source_kind,
            "initial_content": f.initial_content,
            "current_content": f.current_content,
            "answer": f.answer,
            "initial_answer": f.initial_answer,
            "current_answer": f.current_answer,
            "task": f.task,
            "mutate_after_first": f.mutate_after_first,
            "historical_answer": f.historical_answer,
            "side_effect": f.side_effect,
        }
        for key, f in FIXTURES.items()
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(OUT, hashlib.sha256(OUT.read_bytes()).hexdigest())
for key, f in FIXTURES.items():
    print(key, len(f.initial_content), len(f.current_content), f.answer)
