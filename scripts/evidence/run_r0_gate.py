#!/usr/bin/env python3
"""Execute the frozen Evidence Recoverability R0-1..R0-12 blocking gate."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "tests" / "fixtures" / "evidence_r0_phase7_gate_v1.json"
REPORT_PATH = ROOT / "data" / "audit" / "evidence_r0_phase7_gate_v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_env_key(name: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip()
    return None


def _validate_map(gate: dict[str, Any]) -> dict[str, Any]:
    oracle_path = ROOT / str(gate["oracle_fixture"])
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    if gate.get("network_policy") != "deny" or gate.get("all_cases_blocking") is not True:
        raise RuntimeError("Phase7 gate must deny network and make every case blocking")
    expected_ids = [f"R0-{i}" for i in range(1, 13)]
    actual_ids = [str(case["id"]) for case in gate["cases"]]
    if actual_ids != expected_ids:
        raise RuntimeError(f"gate ids mismatch: {actual_ids}")
    oracle_by_id = {str(case["id"]): case for case in oracle["cases"]}
    for case in gate["cases"]:
        cid = str(case["id"])
        if set(case["covers"]) != set(oracle_by_id[cid]["oracle"]):
            raise RuntimeError(f"oracle clause coverage mismatch for {cid}")
        if not case["selectors"]:
            raise RuntimeError(f"missing selectors for {cid}")
    spec = ROOT / ".codeartsdoer" / "specs" / "ev_recov" / "spec.md"
    design = ROOT / ".codeartsdoer" / "specs" / "ev_recov" / "design.md"
    if _sha(spec) != oracle["contract_sha256"]["spec"]:
        raise RuntimeError("frozen spec hash drift")
    if _sha(design) != oracle["contract_sha256"]["design"]:
        raise RuntimeError("frozen design hash drift")
    if oracle.get("provider_calls_allowed") is not False:
        raise RuntimeError("R0 oracle unexpectedly permits provider calls")
    return oracle


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    prefixes = [str(ROOT / "src"), str(ROOT)]
    if existing:
        prefixes.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(prefixes)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "scripts.evidence.r0_no_network",
        *[str(selector) for selector in case["selectors"]],
    ]
    started = monotonic()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = monotonic() - started
    lines = proc.stdout.splitlines()
    return {
        "id": case["id"],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 3),
        "covers": case["covers"],
        "selectors": case["selectors"],
        "output_tail": lines[-12:],
    }


def main() -> int:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    oracle = _validate_map(gate)
    results = [_run_case(case) for case in gate["cases"]]
    passed = all(row["status"] == "PASS" for row in results)
    evidence_mode = _read_env_key("EVIDENCE_MODE")
    pipeline = _read_env_key("TOOL_PIPELINE_ENABLED")
    report = {
        "schema": "evidence-r0-phase7-gate/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "all_cases_blocking": True,
        "provider_calls_allowed": False,
        "network_policy": "deny-via-pytest-plugin",
        "oracle_version": oracle["version"],
        "oracle_sha256": _sha(ROOT / str(gate["oracle_fixture"])),
        "gate_map_sha256": _sha(GATE_PATH),
        "contract_sha256": oracle["contract_sha256"],
        "runtime_audit": {
            "evidence_mode": "unset->off" if evidence_mode is None else evidence_mode,
            "tool_pipeline_enabled": pipeline,
            "enforce_pipeline_combination": "fail-closed-by-test",
        },
        "cases": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence R0 Phase7: {report['status']} ({sum(r['status']=='PASS' for r in results)}/12)")
    for row in results:
        print(f"{row['id']}: {row['status']} ({row['elapsed_s']}s)")
    print(f"report={REPORT_PATH.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
