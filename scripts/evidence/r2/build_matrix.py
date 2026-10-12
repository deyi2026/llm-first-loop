from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED = 20260826
rows = []
for provider in ("minimax", "deepseek"):
    for seed_id in ("F1", "F2", "F3", "F4", "F5", "F6"):
        for condition in ("B0", "E1"):
            for rep in range(1, 4):
                rows.append(
                    {"provider": provider, "seed_id": seed_id, "condition": condition, "rep": rep}
                )
r = random.Random(SEED)
r.shuffle(rows)
for i, row in enumerate(rows, 1):
    row["run_id"] = f"R2-{i:03d}"
out = {"schema": "evidence-r2-matrix-v1", "random_seed": SEED, "count": len(rows), "runs": rows}
p = ROOT / "tests/fixtures/evidence_r2/matrix_v1.json"
p.write_text(json.dumps(out, indent=2) + "\n")
print(p, len(rows), hashlib.sha256(p.read_bytes()).hexdigest())
