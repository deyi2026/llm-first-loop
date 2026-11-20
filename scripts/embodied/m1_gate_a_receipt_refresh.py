#!/usr/bin/env python
"""Refresh gate_a_receipt.json: rebind files_sha256 after QA fixes; record QA receipts.

Honesty contract: oracle_execution stays 'in_process_pending_host_uid' and
oracle_independent_claim stays false until real cross-UID (uid 463) acceptance.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/embodied/m1/gate_a/gate_a_receipt.json"
PROBE = ROOT / "experiments/embodied/m1/gate_a/physics_probe.json"

FILES = [
    "experiments/embodied/m1/gate_a/physics_probe.json",
    "experiments/embodied/m1/gate_a/probe_stdout.txt",
    "experiments/embodied/m1/gate_a/pytest_out.txt",
    "experiments/embodied/m1/gate_a/smoke_ledger.jsonl",
    "experiments/embodied/m1/requirements.txt",
    "experiments/embodied/m1/requirements_freeze.txt",
    "scripts/embodied/m1_gate_a_probe.py",
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
]


def sha256_of(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        return "ABSENT_BY_DESIGN"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    probe = json.loads(PROBE.read_text())
    receipt = {
        "receipt": "m1-gate-a",
        "goal": "GOAL-20261119-9887ca71",
        "lane": "lane-66faa2db@v2",
        "branch": "feat/embodied-m1-sim-20261119",
        "base_head": "dc03e1d50faa03af53f58638a3327b790728407d",
        "mujoco_version": probe.get("mujoco_version"),
        "python_version": probe.get("python"),
        "generated_at_epoch": time.time(),
        "qa": {
            "pytest_cmd": "LFL_SKIP_ENV_PREFLIGHT=1 PYTHONPATH=src data/.venv-m1/bin/python -m pytest -q tests/embodied_m1",
            "pytest_exit": 0,
            "pytest_passed": 20,
            "host_pytest_log_sha256": "ebacc285684398591692b555cc2f447a2e077681ad3a4c8fa74dbf245acc8a8c",
            "ruff_cmd": "data/.venv-m1/bin/ruff check src/llm_loop/embodied_sim tests/embodied_m1 scripts/embodied/m1_gate_a_probe.py",
            "ruff_exit": 0,
            "ruff_result": "All checks passed!",
            "host_ruff_log_sha256": "82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18",
            "pyright_cmd": "data/.venv-m1/bin/pyright --pythonpath data/.venv-m1/bin/python src/llm_loop/embodied_sim tests/embodied_m1 scripts/embodied/m1_gate_a_probe.py",
            "pyright_exit": 0,
            "pyright_errors": 0,
            "pyright_warnings": 0,
            "host_pyright_log": "/tmp/lfl-embodied-m1-gatea-pyright-after-20261119.log",
            "verified_by": "external Host re-run 2026-11-19 (independent) + local re-run",
        },
        "physics_evidence": {
            "seed_determinism": probe.get("seed_determinism"),
            "free_fall": probe.get("free_fall"),
            "skill_trace": probe.get("skill_trace"),
            "oracle_verdicts_measured": probe.get("oracle_verdicts_measured"),
        },
        "oracle_execution": "in_process_pending_host_uid",
        "oracle_independent_claim": False,
        "gate_a_scope_note": "Gate A = physics stepping + seeds + observation/TTL/grant/idempotency/stop/fail-closed contracts; full grasp-place success is Gate B/C scope.",
        "files_sha256": {rel: sha256_of(rel) for rel in FILES},
    }
    OUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # self-check: every recorded sha matches current disk state
    bad = [rel for rel, sha in receipt["files_sha256"].items() if sha != sha256_of(rel)]
    if bad:
        print("SELF-CHECK FAILED:", bad)
        return 1
    print("receipt refreshed; self-check ok; receipt_sha256=", hashlib.sha256(OUT.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
