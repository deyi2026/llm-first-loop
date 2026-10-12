"""P0 structural Task-owned review receipt probe; no model/tool runtime wiring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from llm_loop.assurance.task_control_store import InvalidContractError, _check_id, _check_sha


@dataclass(frozen=True)
class FrozenReviewRequest:
    task_id: str
    owner: str
    candidate_sha256: str
    acceptance_sha256: str
    author_session_id: str
    reviewer_session_id: str

    def __post_init__(self) -> None:
        for item in (self.task_id, self.owner, self.author_session_id, self.reviewer_session_id):
            _check_id(item)
        for item in (self.candidate_sha256, self.acceptance_sha256):
            _check_sha(item)
        if self.author_session_id == self.reviewer_session_id:
            raise InvalidContractError("author session cannot review its own candidate")


def validate_structural_receipt(
    frozen: FrozenReviewRequest, candidate_path: Path, report_path: Path
) -> str:
    """No semantic claim: returns STRUCTURALLY_VALID, not REVIEW_GATE_PASS."""
    digest = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    if digest != frozen.candidate_sha256:
        return "UNCERTAIN_CANDIDATE_DRIFT"
    try:
        body = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "UNCERTAIN_REPORT_MISSING_OR_INVALID"
    if not isinstance(body, dict) or set(body) != {
        "schema", "task_id", "reviewer_session_id", "candidate_sha256",
        "acceptance_sha256", "status", "finding_count",
    }:
        return "UNCERTAIN_REPORT_SCHEMA"
    if (
        body["schema"] != "lfl.dual_assurance.review_report/v1"
        or body["task_id"] != frozen.task_id
        or body["reviewer_session_id"] != frozen.reviewer_session_id
        or body["candidate_sha256"] != frozen.candidate_sha256
        or body["acceptance_sha256"] != frozen.acceptance_sha256
        or body["status"] not in {"PASS_BOUNDED", "FAIL", "UNCERTAIN"}
        or type(body["finding_count"]) is not int
    ):
        return "UNCERTAIN_REPORT_IDENTITY"
    return "STRUCTURALLY_VALID_NOT_INDEPENDENTLY_QUALIFIED"
