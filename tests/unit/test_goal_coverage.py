"""Coverage checks fail closed without writing a second progress ledger."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from llm_loop.introspection.goal_coverage import (
    CoverageFormatError,
    audit_coverage,
    parse_requirements,
)
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
from llm_loop.introspection.task_store import TaskStore

GOAL = "GOAL-20261120-demo"
ACCEPTANCE = "失败后恢复且不重复写入"


def _matrix(
    task_id: str = "TASK-demo-001",
    *,
    required: str = "yes",
    approval: str = "-",
    acceptance: str = ACCEPTANCE,
    extra: str = "",
) -> str:
    return (
        f"# 实现范围\n\n<!-- LFL-REQ-GOAL: {GOAL} -->\n"
        "| REQ | Task | Slice | Required | Acceptance | Incremental | Final | Scope approval |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "<!-- LFL-REQ-MATRIX:v1 -->\n"
        "| REQ | Task | Slice | Required | Acceptance | Incremental | Final | Scope approval |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| REQ-001 | {task_id} | A | {required} | {acceptance} | tests/unit/test_x.py | R9,CI | {approval} |\n"
        f"{extra}"
        "<!-- /LFL-REQ-MATRIX -->\n"
    )


class _Verifier:
    def verify(self, refs):
        assert refs
        return SimpleNamespace(
            status="verified",
            failing_ref="",
            checked_at="2026-11-20T00:00:00+00:00",
            refs_digest="fixture-digest",
        )


def _verified_store(tmp_path: Path) -> TaskStore:
    # Test double only: TaskStore consumes the verifier's verified report.
    return TaskStore(tmp_path, evidence_verifier=cast(TaskEvidenceVerifier, _Verifier()))


def _task(store: TaskStore, *, done: bool = True, evidence: bool = True):
    task = store.create(
        GOAL, "验证恢复", acceptance=[ACCEPTANCE], evidence_required=evidence
    )
    if done:
        store.update(GOAL, task.task_id, status="in_progress")
        store.update(
            GOAL,
            task.task_id,
            status="done",
            evidence_refs=["evidence://v1/test-fixture"] if evidence else None,
        )
    return task


def _audit(tmp_path: Path, design: str, *, candidate_sha: str = "") -> dict:
    path = tmp_path / "design.md"
    path.write_text(design, encoding="utf-8")
    return audit_coverage(
        design_path=path,
        audit_dir=tmp_path,
        goal_id=GOAL,
        candidate_sha=candidate_sha,
    )


def _codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["issues"]}


def test_parser_only_reads_marked_table_not_example():
    rows = parse_requirements(_matrix())
    assert [row["req_id"] for row in rows] == ["REQ-001"]
    assert rows[0]["incremental"] == ["tests/unit/test_x.py"]


@pytest.mark.parametrize(
    "design",
    [
        "# No matrix\n| REQ-001 | TASK-x-001 |",
        _matrix() + "<!-- LFL-REQ-MATRIX:v1 -->",
        _matrix(extra="| REQ-001 | TASK-demo-002 | A | yes | x | t | R9 | - |\n"),
        _matrix(required="maybe"),
        _matrix(approval="evidence://unapproved"),
        _matrix(required="no", approval="-"),
        _matrix(acceptance="TBD"),
    ],
)
def test_parser_rejects_ambiguous_scope(design):
    with pytest.raises(CoverageFormatError):
        parse_requirements(design)


def test_verified_task_passes_structural_coverage_only(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    report = _audit(tmp_path, _matrix(task.task_id), candidate_sha="a" * 40)
    assert report["status"] == "PASS"
    assert report["requirements_verified"] == 1
    assert report["finality_qualified"] is False
    assert len(report["design_sha256"]) == 64
    assert len(report["ledger_sha256"]) == 64


def test_missing_task_is_not_silent(tmp_path):
    store = _verified_store(tmp_path)
    _task(store)
    report = _audit(tmp_path, _matrix("TASK-demo-999"))
    assert {"task_missing", "unmapped_task"} <= _codes(report)


def test_unverified_evidence_blocks_even_if_done(tmp_path):
    store = TaskStore(tmp_path)
    task = _task(store, evidence=False)
    report = _audit(tmp_path, _matrix(task.task_id))
    assert "evidence_unverified" in _codes(report)


def test_cancelled_required_task_blocks(tmp_path):
    store = TaskStore(tmp_path)
    task = _task(store, done=False)
    store.update(GOAL, task.task_id, status="cancelled")
    report = _audit(tmp_path, _matrix(task.task_id))
    assert "required_not_done" in _codes(report)


def test_changed_acceptance_and_stale_premise_block(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    store.update(GOAL, task.task_id, acceptance=["新验收条件"])
    report = _audit(tmp_path, _matrix(task.task_id))
    assert {"acceptance_mismatch", "acceptance_revised_requires_review"} <= _codes(report)


def test_optional_approval_reference_is_not_self_verifying(tmp_path):
    store = TaskStore(tmp_path)
    task = _task(store, done=False)
    report = _audit(
        tmp_path,
        _matrix(task.task_id, required="no", approval="evidence://v1/approval"),
    )
    assert "scope_approval_unverified" in _codes(report)


def test_malformed_task_ledger_fails_closed(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    ledger = tmp_path / "tasks" / f"{GOAL}.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write("{malformed}\n")
    report = _audit(tmp_path, _matrix(task.task_id))
    assert "coverage_unavailable" in _codes(report)


def test_missing_ledger_and_invalid_candidate_block(tmp_path):
    report = _audit(tmp_path, _matrix())
    assert "coverage_unavailable" in _codes(report)
    report = _audit(tmp_path, _matrix(), candidate_sha="bad")
    assert "coverage_unavailable" in _codes(report)


def test_extra_task_and_more_than_40_requirements_are_not_accepted(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    _task(store, done=False)
    report = _audit(tmp_path, _matrix(task.task_id))
    assert "unmapped_task" in _codes(report)
    rows = "".join(
        f"| REQ-{i:03d} | TASK-demo-{i:03d} | A | yes | x | t | R9 | - |\n"
        for i in range(2, 42)
    )
    report = _audit(tmp_path, _matrix(task.task_id, extra=rows))
    assert report["requirements_total"] == 41
    assert report["status"] == "BLOCKED"
    assert "goal_task_limit_exceeded" in _codes(report)
    assert "task_missing" in _codes(report)


def test_design_goal_binding_mismatch_blocks(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    report = _audit(
        tmp_path,
        _matrix(task.task_id).replace(GOAL, "GOAL-other"),
    )
    assert "coverage_unavailable" in _codes(report)


def test_taskstore_ledger_is_never_rewritten_by_audit(tmp_path):
    store = _verified_store(tmp_path)
    task = _task(store)
    ledger = tmp_path / "tasks" / f"{GOAL}.jsonl"
    before = ledger.read_bytes()
    _audit(tmp_path, _matrix(task.task_id))
    assert ledger.read_bytes() == before
    assert json.loads(before.splitlines()[-1])["task_id"] == task.task_id
