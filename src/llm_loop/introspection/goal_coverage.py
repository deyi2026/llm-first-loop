"""Read-only design REQ <-> TaskStore coverage audit.

This module deliberately does not own progress state. The approved Markdown
matrix owns scope; TaskStore owns execution state and evidence verification.
Its PASS means *coverage* only, never a release or deployment qualification.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from llm_loop.introspection.task_store import TASK_LIMIT_PER_GOAL, TaskStore, safe_goal_id

MATRIX_START = "<!-- LFL-REQ-MATRIX:v1 -->"
MATRIX_END = "<!-- /LFL-REQ-MATRIX -->"
MATRIX_HEADER = (
    "REQ",
    "Task",
    "Slice",
    "Required",
    "Acceptance",
    "Incremental",
    "Final",
    "Scope approval",
)
_REQ_ID = re.compile(r"REQ-[A-Z0-9][A-Z0-9-]*\Z")
_TASK_ID = re.compile(r"TASK-[A-Za-z0-9_-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_GOAL_MARKER = re.compile(r"<!-- LFL-REQ-GOAL: ([A-Za-z0-9_-]+) -->")


class CoverageFormatError(ValueError):
    """A scope manifest is missing, malformed, or ambiguous."""


def resolve_design_path(audit_dir: str | Path, design_path: str) -> Path:
    """Resolve a pinned design under the repository; refuse external files.

    The runtime audit root must be the repository's data/audit. Do not use the
    caller's current directory (Web and CLI have different cwd conventions).
    """
    audit = Path(audit_dir).resolve()
    if audit.name != "audit" or audit.parent.name != "data":
        raise CoverageFormatError("repository audit root cannot be established")
    if not design_path.startswith("docs/design/") or not design_path.endswith(".md"):
        raise CoverageFormatError("requirements scope must be a docs/design Markdown file")
    relative = Path(design_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CoverageFormatError("requirements scope path traversal")
    repo = audit.parent.parent
    resolved = (repo / relative).resolve()
    if not resolved.is_relative_to((repo / "docs" / "design").resolve()):
        raise CoverageFormatError("requirements scope escaped docs/design")
    return resolved


def _cells(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        raise CoverageFormatError("matrix rows must begin and end with |")
    return [cell.strip() for cell in line[1:-1].split("|")]


def parse_requirements(design: str) -> list[dict[str, Any]]:
    """Parse the one explicitly marked, strict Markdown table; ignore examples."""
    if design.count(MATRIX_START) != 1 or design.count(MATRIX_END) != 1:
        raise CoverageFormatError("exactly one LFL-REQ-MATRIX:v1 section required")
    section = design.split(MATRIX_START, 1)[1].split(MATRIX_END, 1)[0]
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if len(lines) < 3 or tuple(_cells(lines[0])) != MATRIX_HEADER:
        raise CoverageFormatError("REQ matrix header missing or changed")
    separator = _cells(lines[1])
    if len(separator) != len(MATRIX_HEADER) or any(
        not re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        raise CoverageFormatError("REQ matrix separator invalid")
    rows: list[dict[str, Any]] = []
    req_ids: set[str] = set()
    task_ids: set[str] = set()
    for line in lines[2:]:
        cells = _cells(line)
        if len(cells) != len(MATRIX_HEADER):
            raise CoverageFormatError("REQ matrix row has wrong column count")
        req_id, task_id, slice_id, required, acceptance, incremental, final, approval = cells
        if not _REQ_ID.fullmatch(req_id) or req_id in req_ids:
            raise CoverageFormatError(f"invalid or duplicate REQ ID: {req_id}")
        if not _TASK_ID.fullmatch(task_id) or task_id in task_ids:
            raise CoverageFormatError(f"invalid or duplicate Task ID: {task_id}")
        if required not in ("yes", "no"):
            raise CoverageFormatError(f"{req_id}: Required must be yes or no")
        if not slice_id or not acceptance or not incremental or not final:
            raise CoverageFormatError(f"{req_id}: required matrix cell empty")
        if any(x in ("TBD", "-", "?") for x in (acceptance, incremental, final)):
            raise CoverageFormatError(f"{req_id}: placeholder is not acceptance")
        if required == "no" and not approval.startswith("evidence://"):
            raise CoverageFormatError(f"{req_id}: optional scope requires approval ref")
        if required == "yes" and approval not in ("", "-"):
            raise CoverageFormatError(f"{req_id}: required REQ cannot carry scope waiver")
        req_ids.add(req_id)
        task_ids.add(task_id)
        rows.append(
            {
                "req_id": req_id,
                "task_id": task_id,
                "slice": slice_id,
                "required": required == "yes",
                "acceptance": acceptance,
                "incremental": [x.strip() for x in incremental.split(",") if x.strip()],
                "final": [x.strip() for x in final.split(",") if x.strip()],
                "scope_approval": approval if required == "no" else "",
            }
        )
    if not rows:
        raise CoverageFormatError("REQ matrix must contain at least one requirement")
    return rows


def audit_coverage(
    *,
    design_path: str | Path,
    audit_dir: str | Path,
    goal_id: str,
    candidate_sha: str = "",
    required_design_sha256: str = "",
    evidence_verifier: Any | None = None,
) -> dict[str, Any]:
    """Inspect immutable scope and existing TaskStore without changing either.

    A passing coverage report does NOT attest candidate code, Reviewer, R9,
    CI, or deployment. Finality must be checked separately by trusted gates.
    """
    result: dict[str, Any] = {
        "schema": "lfl.goal_coverage.v1",
        "goal_id": goal_id,
        "candidate_sha": candidate_sha,
        "status": "BLOCKED",
        "finality_qualified": False,
        "requirements_total": 0,
        "requirements_verified": 0,
        "issues": [],
    }

    def issue(code: str, *, req_id: str = "", detail: str = "") -> None:
        result["issues"].append({"code": code, "req_id": req_id, "detail": detail})

    try:
        if not goal_id or (candidate_sha and not _SHA.fullmatch(candidate_sha)):
            raise CoverageFormatError("goal_id missing or candidate SHA invalid")
        design_bytes = Path(design_path).read_bytes()
        result["design_sha256"] = hashlib.sha256(design_bytes).hexdigest()
        if required_design_sha256 and (
            not re.fullmatch(r"[0-9a-f]{64}", required_design_sha256)
            or result["design_sha256"] != required_design_sha256
        ):
            raise CoverageFormatError("pinned design SHA256 mismatch")
        design_text = design_bytes.decode("utf-8")
        declared_goals = _GOAL_MARKER.findall(design_text)
        if declared_goals != [goal_id]:
            raise CoverageFormatError("design goal binding missing, duplicate, or mismatched")
        rows = parse_requirements(design_text)
        result["requirements_total"] = len(rows)
        if len(rows) > TASK_LIMIT_PER_GOAL:
            issue("goal_task_limit_exceeded", detail=str(len(rows)))
        ledger = Path(audit_dir) / "tasks" / f"{safe_goal_id(goal_id)}.jsonl"
        if not ledger.is_file():
            raise CoverageFormatError("TaskStore ledger missing; cannot assert coverage")
        before = ledger.read_bytes()
        if not before.strip():
            raise CoverageFormatError("TaskStore ledger empty")
        for number, line in enumerate(before.splitlines(), 1):
            if line.strip():
                try:
                    if not isinstance(json.loads(line), dict):
                        raise ValueError("not a JSON object")
                except (ValueError, UnicodeDecodeError) as exc:
                    raise CoverageFormatError(f"TaskStore row {number} invalid: {exc}") from exc
        tasks = {t.task_id: t for t in TaskStore(audit_dir).list_for_goal(goal_id)}
        after = ledger.read_bytes()
        if before != after:
            raise CoverageFormatError("TaskStore ledger changed during audit")
        result["ledger_sha256"] = hashlib.sha256(after).hexdigest()
        mapped = {r["task_id"] for r in rows}
        for row in rows:
            req_id = str(row["req_id"])
            task = tasks.get(str(row["task_id"]))
            if task is None:
                issue("task_missing", req_id=req_id, detail=str(row["task_id"]))
                continue
            if row["acceptance"] not in task.acceptance:
                issue("acceptance_mismatch", req_id=req_id)
            if task.acceptance_revised:
                issue("acceptance_revised_requires_review", req_id=req_id)
            if task.premise_stale:
                issue("premise_stale", req_id=req_id)
            if row["required"]:
                if task.status != "done":
                    issue("required_not_done", req_id=req_id, detail=task.status)
                if (
                    not task.evidence_required
                    or not task.evidence_refs
                    or task.evidence_verification_status != "verified"
                ):
                    issue("evidence_unverified", req_id=req_id)
                elif evidence_verifier is not None:
                    report = evidence_verifier.verify(task.evidence_refs)
                    if getattr(report, "status", "") != "verified":
                        issue("evidence_stale", req_id=req_id)
            else:
                if evidence_verifier is None or getattr(
                    evidence_verifier.verify([row["scope_approval"]]), "status", ""
                ) != "verified":
                    issue("scope_approval_unverified", req_id=req_id)
            if not any(x["req_id"] == req_id for x in result["issues"]):
                result["requirements_verified"] += 1
        for task_id in sorted(tasks.keys() - mapped):
            issue("unmapped_task", detail=task_id)
        if not result["issues"]:
            result["status"] = "PASS"
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, CoverageFormatError) as exc:
        issue("coverage_unavailable", detail=str(exc))
    return result
