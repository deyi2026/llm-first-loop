"""P1.12 smallest real Executor -> independent Reviewer -> local Gate path.

An offline harness demonstration, NOT production dual-agent permission.
Executor is a genuine LoopEngine Run whose sole tool writes one bounded file.
Reviewer is a separate Task-owned LoopEngine OS process plus the P1.8
independent Docker acceptance checker. Host-side gate never publishes,
deploys, invokes a real model, or grants production tool capability.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.assurance.p1_review_supervisor import OfflineReviewProcess, ReviewProcessOutcome
from llm_loop.assurance.p16_host_broker import OfflineHostReviewBroker, OfflineReviewRequest
from llm_loop.assurance.p18_bounded_reviewer import BoundedReviewResult
from llm_loop.assurance.p112_functional_evidence import (
    BASE_IMAGE,
    SUITE,
    frozen_merge_acceptance_sha256,
    run_host_functional_review,
)
from llm_loop.assurance.task_control_store import InvalidContractError
from llm_loop.core.message import ToolResult, ToolResultStatus

_MAX_CANDIDATE = 4_096


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class OfflineExecutorWriteTool:
    """One actual artifact write; no arbitrary paths, commands or retries."""

    name = "write_offline_candidate"
    description = "Write one UTF-8 candidate in a dedicated offline test directory"
    parameters = {
        "type": "object",
        "properties": {"content": {"type": "string", "maxLength": _MAX_CANDIDATE}},
        "required": ["content"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path) -> None:
        if (
            root.name != "assurance-p112-executor-root"
            or root.is_symlink()
            or (root.exists() and not root.is_dir())
        ):
            raise InvalidContractError("P1.12 requires isolated offline Executor root")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / "candidate.py"

    def execute(self, **kwargs: Any) -> ToolResult:
        data = kwargs.get("content")
        if (
            set(kwargs) != {"content"}
            or not isinstance(data, str)
            or not 0 < len(data.encode("utf-8")) <= _MAX_CANDIDATE
        ):
            return ToolResult(ToolResultStatus.FAILURE, "candidate invalid", "", self.name)
        raw = data.encode("utf-8")
        fd = -1
        try:
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            if os.write(fd, raw) != len(raw):
                raise OSError("incomplete offline write")
            os.fsync(fd)
            os.close(fd)
            fd = -1
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            return ToolResult(
                ToolResultStatus.FAILURE,
                "candidate already exists or persistence failed",
                "", self.name,
            )
        finally:
            if fd >= 0:
                os.close(fd)
        return ToolResult(
            ToolResultStatus.SUCCESS,
            "offline_candidate_sha256=" + _sha(raw), "", self.name,
        )


@dataclass(frozen=True)
class LocalGateReceipt:
    verdict: str
    task_id: str
    candidate_sha256: str
    executor_session_id: str
    reviewer_session_id: str | None
    bounded_verdict: str | None
    reason: str
    may_publish: bool = False
    may_dispatch_production_effect: bool = False
    functional_verdict: str | None = None
    functional_passed: int | None = None
    functional_receipt_sha256: str | None = None


def evaluate_offline_delivery(
    *,
    executor_session_id: str,
    candidate_path: Path,
    broker: OfflineHostReviewBroker,
    request: OfflineReviewRequest,
    reviewer_process: OfflineReviewProcess,
    reviewer_result: ReviewProcessOutcome,
    bounded_result: BoundedReviewResult | None,
    functional_image_ref: str = BASE_IMAGE,
) -> LocalGateReceipt:
    """Host enforces known functional acceptance, never reads model PASS text.

    The exact frozen TaskControl acceptance SHA selects the functional suite.
    A different checklist cannot opt out merely by claiming semantic PASS.
    Existing non-merge synthetic tasks preserve their structural-only local
    result; no result here can grant production effects.
    """
    reason = "LOCAL_ACCEPTANCE_NOT_VERIFIED"
    result_sha = request.candidate_sha256
    reviewer_sid = reviewer_process.reviewer_session_id
    try:
        candidate = candidate_path.read_bytes()
    except OSError:
        candidate = b""
    if _sha(candidate) != result_sha or not 0 < len(candidate) <= _MAX_CANDIDATE:
        reason = "EXECUTOR_CANDIDATE_DRIFT"
    elif not broker._guard(request):
        reason = "TASK_STOP_OR_FLEET_FENCED"
    elif (
        reviewer_process.task_id != request.task_id
        or reviewer_process.owner != request.owner
        or reviewer_process.candidate_sha256 != result_sha
        or reviewer_sid == executor_session_id
        or not reviewer_result.physical_process_ended
        or reviewer_result.process_exit != 0
        or reviewer_result.phase != "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS"
        or reviewer_result.worker_receipt is None
        or reviewer_result.worker_receipt.get("reviewer_session_id") != reviewer_sid
        or reviewer_result.worker_receipt.get("candidate_sha256") != result_sha
        or reviewer_result.worker_receipt.get("tool_names_attempted")
        != ["review_frozen_candidate"]
    ):
        reason = "REVIEWER_SESSION_OR_PROCESS_UNQUALIFIED"
    elif bounded_result is None or (
        bounded_result.operation_id != request.operation_id
        or bounded_result.transport_state != "UNVERIFIED_OUTPUT"
        or bounded_result.verdict != "PASS_BOUNDED"
        or not bounded_result.guest_receipt_sha256
        or bounded_result.production_release_qualified
        or bounded_result.may_dispatch_effect
        or bounded_result.may_spawn_worker
    ):
        reason = "INDEPENDENT_BOUNDED_ACCEPTANCE_FAILED_OR_UNKNOWN"
    elif not broker._guard(request):
        reason = "TASK_STOP_OR_FLEET_FENCED"
    else:
        control = broker.control.read_exact(request.task_id, request.owner)
        pinned = frozen_merge_acceptance_sha256()
        functional_required = control.acceptance_sha256 == pinned
        if b"def merge_closed_intervals(" in candidate and not functional_required:
            reason = "FUNCTIONAL_ACCEPTANCE_NOT_FROZEN"
        elif functional_required:
            # Never accept a review verdict from Executor or Reviewer as
            # evidence; the Host runs a fresh, independent Docker oracle.
            functional = run_host_functional_review(
                candidate, expected_sha256=result_sha,
                suite=SUITE, image_ref=functional_image_ref,
            )
            # A candidate may be replaced while the Docker subprocess runs.
            # Bind local acceptance to on-disk bytes *after* verification.
            try:
                after_review = candidate_path.read_bytes()
            except OSError:
                after_review = b""
            if after_review != candidate or _sha(after_review) != result_sha:
                reason = "EXECUTOR_CANDIDATE_DRIFT"
            elif not broker._guard(request):
                reason = "TASK_STOP_OR_FLEET_FENCED"
            if reason != "LOCAL_ACCEPTANCE_NOT_VERIFIED":
                return LocalGateReceipt(
                    "BLOCKED", request.task_id, result_sha,
                    executor_session_id, reviewer_sid,
                    bounded_result.verdict, reason,
                    functional_verdict=functional.verdict,
                    functional_passed=functional.passed,
                    functional_receipt_sha256=functional.guest_receipt_sha256,
                )
            if functional.verdict != "PASS_FUNCTIONAL":
                return LocalGateReceipt(
                    "BLOCKED", request.task_id, result_sha,
                    executor_session_id, reviewer_sid,
                    bounded_result.verdict,
                    "FUNCTIONAL_ORACLE_FAIL" if functional.verdict == "FAIL_FUNCTIONAL"
                    else "FUNCTIONAL_EVIDENCE_UNKNOWN",
                    functional_verdict=functional.verdict,
                    functional_passed=functional.passed,
                    functional_receipt_sha256=functional.guest_receipt_sha256,
                )
            else:
                return LocalGateReceipt(
                    "LOCAL_EXPERIMENT_VERIFIED", request.task_id, result_sha,
                    executor_session_id, reviewer_sid,
                    bounded_result.verdict, "OFFLINE_FUNCTIONAL_EVIDENCE_VERIFIED",
                    functional_verdict=functional.verdict,
                    functional_passed=functional.passed,
                    functional_receipt_sha256=functional.guest_receipt_sha256,
                )
        if reason != "LOCAL_ACCEPTANCE_NOT_VERIFIED":
            return LocalGateReceipt(
                "BLOCKED", request.task_id, result_sha,
                executor_session_id, reviewer_sid,
                bounded_result.verdict, reason,
            )
        return LocalGateReceipt(
            "LOCAL_EXPERIMENT_VERIFIED", request.task_id, result_sha,
            executor_session_id, reviewer_sid,
            bounded_result.verdict, "OFFLINE_ONLY_NO_PRODUCTION_AUTHORITY",
        )
    return LocalGateReceipt(
        "BLOCKED", request.task_id, result_sha,
        executor_session_id, reviewer_sid,
        None if bounded_result is None else bounded_result.verdict, reason,
    )
