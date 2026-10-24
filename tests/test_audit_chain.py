"""P2-5：审计哈希链可检测篡改 + 破坏性操作审计 fail-closed。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.tools.safety import CatastrophicGuard, verify_audit_chain

RM = "r" + "m"
RF = "-r" + "f"


def _guard(tmp_path: Path) -> CatastrophicGuard:
    return CatastrophicGuard(audit_dir=tmp_path / "audit")


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_block_record_is_chained(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    assert guard.guard("execute_command", {"command": f"{RM} {RF} /"}).blocked
    assert guard.guard("execute_command", {"command": f"{RM} {RF} ~"}).blocked

    path = tmp_path / "audit" / "safety_blocks.jsonl"
    recs = _records(path)
    assert len(recs) == 2
    assert recs[0]["prev_hash"] == ""
    assert recs[1]["prev_hash"] == recs[0]["entry_hash"]
    ok, line, detail = verify_audit_chain(path)
    assert ok and line == 0, detail


def test_allow_record_is_chained(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    assert guard.guard("execute_command", {"command": f"{RM} {RF} ./build"}) is None
    path = tmp_path / "audit" / "safety_allows.jsonl"
    recs = _records(path)
    assert recs[0]["kind"] == "allow_destructive"
    assert verify_audit_chain(path)[0]


def test_tampered_content_is_detected(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    guard.guard("execute_command", {"command": f"{RM} {RF} /"})
    path = tmp_path / "audit" / "safety_blocks.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["command"] = f"{RM} {RF} ./harmless"
    lines[0] = json.dumps(rec, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, line, detail = verify_audit_chain(path)
    assert not ok and line == 1 and detail == "entry_hash mismatch"


def test_deleted_line_breaks_chain(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    for command in (f"{RM} {RF} /", f"{RM} {RF} ~", f"{RM} {RF} /etc"):
        guard.guard("execute_command", {"command": command})
    path = tmp_path / "audit" / "safety_blocks.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    ok, line, detail = verify_audit_chain(path)
    assert not ok and line == 2 and detail == "prev_hash mismatch"


def test_audit_failure_fails_closed_for_destructive(tmp_path: Path) -> None:
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    guard = CatastrophicGuard(audit_dir=blocker / "audit")

    decision = guard.guard("execute_command", {"command": f"{RM} {RF} ./build"})
    assert decision is not None and decision.blocked
    assert "fail-closed" in decision.reason


def test_audit_failure_does_not_block_readonly(tmp_path: Path) -> None:
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    guard = CatastrophicGuard(audit_dir=blocker / "audit")
    assert guard.guard("execute_command", {"command": "echo hi"}) is None


def test_guard_without_audit_dir_is_unchanged() -> None:
    guard = CatastrophicGuard()
    assert guard.guard("execute_command", {"command": f"{RM} {RF} ./build"}) is None
    assert guard.guard("execute_command", {"command": f"{RM} {RF} /"}).blocked
