from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from scripts.evidence.r7v2.fixtures import FIXTURES

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_OUT = ROOT / "tests/fixtures/evidence_r7v2/fixtures_v1.json"
MATRIX_OUT = ROOT / "tests/fixtures/evidence_r7v2/matrix_v1.json"
SEED = 20260826

fixture_payload = {
    "schema": "evidence-r7v2-fixtures-v1",
    "fixtures": {key: vars(fixture) for key, fixture in FIXTURES.items()},
}
FIXTURE_OUT.parent.mkdir(parents=True, exist_ok=True)
FIXTURE_OUT.write_text(
    json.dumps(fixture_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

rows: list[dict[str, object]] = []
for provider in ("minimax", "deepseek"):
    for seed_id in ("Q1", "Q2", "Q3", "Q4"):
        for rep in range(1, 4):
            rows.append({"provider": provider, "seed_id": seed_id, "rep": rep})
rng = random.Random(SEED)
rng.shuffle(rows)
for idx, row in enumerate(rows, 1):
    row["run_id"] = f"R7V2-{idx:03d}"
MATRIX_OUT.write_text(
    json.dumps(
        {"schema": "evidence-r7v2-matrix-v1", "random_seed": SEED, "count": len(rows), "runs": rows},
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
for path in (FIXTURE_OUT, MATRIX_OUT):
    print(hashlib.sha256(path.read_bytes()).hexdigest(), path)
for key, fixture in FIXTURES.items():
    print(key, len(fixture.initial_content), len(fixture.current_content), fixture.expected_answer)
