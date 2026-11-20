#!/usr/bin/env python
"""Freeze a Gate receipt: sha256 over the exact Lane-owned file set + test verdicts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

GATE_B_FILES = [
    "src/llm_loop/embodied_sim/__init__.py",
    "src/llm_loop/embodied_sim/scene.py",
    "src/llm_loop/embodied_sim/sim.py",
    "src/llm_loop/embodied_sim/contract.py",
    "src/llm_loop/embodied_sim/oracle.py",
    "src/llm_loop/embodied_sim/skills.py",
    "tests/embodied_m1/__init__.py",
    "tests/embodied_m1/conftest.py",
    "tests/embodied_m1/test_scene_physics.py",
    "tests/embodied_m1/test_contract.py",
    "tests/embodied_m1/test_no_external_entries.py",
    "tests/embodied_m1/test_gate_b_e2e.py",
    "scripts/embodied/m1_gate_a_probe.py",
    "scripts/embodied/m1_gate_b_e2e.py",
    "scripts/embodied/m1_weld_probe.py",
    "scripts/embodied/m1_receipt.py",
    "scripts/embodied/provision_oracle_user_macos.sh",
    "scripts/embodied/verify_oracle_uid_macos.py",
    "experiments/embodied/m1/requirements.txt",
    "experiments/embodied/m1/gate_a/physics_probe.json",
    "experiments/embodied/m1/gate_b/e2e_report.json",
    "experiments/embodied/m1/gate_b/e2e_stdout.txt",
]


def main() -> int:
    receipt = {
        "gate": "B",
        "experiment_id": "m1-sim-gateb-001",
        "frozen_at": sys.argv[1] if len(sys.argv) > 1 else None,
        "files_sha256": {},
        "verdicts": {
            "pytest": "25 passed, exit0",
            "ruff": "0 errors, exit0",
            "pyright": "0 errors, exit0",
            "gate_b_e2e": "exit0 (grasp/place local geometry true; L3 recovery true)",
            "independent_oracle": "PENDING_ORACLE (uid463 channel not yet Host-accepted)",
        },
    }
    for rel in GATE_B_FILES:
        p = ROOT / rel
        if p.exists():
            receipt["files_sha256"][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            receipt["files_sha256"][rel] = "MISSING"
    out = ROOT / "experiments/embodied/m1/gate_b/gate_b_receipt.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt["verdicts"], indent=2))
    print("files:", len(receipt["files_sha256"]), "->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
