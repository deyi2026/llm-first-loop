from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tests/fixtures/evidence_r4/matrix_v1.json"
SEED = 20260826
rows: list[dict[str, object]] = []
for provider in ("minimax", "deepseek"):
    for seed_id in ("K1", "K2", "K3", "K4", "K5", "K6"):
        for rep in range(1, 4):
            rows.append({"provider": provider, "seed_id": seed_id, "rep": rep})
rng = random.Random(SEED)
rng.shuffle(rows)
for i, row in enumerate(rows, 1):
    row["run_id"] = f"R4-{i:03d}"
payload = {"schema": "evidence-r4-matrix-v1", "random_seed": SEED, "count": len(rows), "runs": rows}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(OUT, len(rows), hashlib.sha256(OUT.read_bytes()).hexdigest())
