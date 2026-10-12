"""P1.8 isolated Python Reviewer: bounded deterministic acceptance, no LLM.

Unlike the earlier shell hash witness, the guest actually evaluates frozen
acceptance checks. A host verifies each guest conclusion independently. No
production ToolRegistry, Provider client, TaskBudget signer, publisher, or
Fleet takeover is wired to this experimental class.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.assurance.p16_host_broker import (
    BrokerDeniedError,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
)

_DOCKER = Path("/opt/homebrew/bin/docker")
_SOCKET = "unix:///var/run/docker.sock"
_IMAGE = re.compile(r"^lfl/assurance-p18-reviewer@sha256:[a-f0-9]{64}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_CHECK_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ACCEPTANCE_SCHEMA = "lfl.dual_assurance.p18_acceptance/v1"
_REQUEST_SCHEMA = "lfl.dual_assurance.p18_review_request/v1"
_RECEIPT_SCHEMA = "lfl.dual_assurance.p18_review_receipt/v1"
_RECEIPT_KEYS = {
    "schema", "nonce", "candidate_sha256", "acceptance_sha256",
    "evidence_sha256", "verdict", "checks", "production_release_qualified",
}
_MAX_WIRE_BYTES = 16_384
_MAX_GUEST_STDOUT = 2_048
_MAX_CANDIDATE = 4_096
_MAX_EVIDENCE = 8_192


def _canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_acceptance(acceptance: dict[str, Any], candidate: bytes) -> tuple[str, list[dict[str, str]]]:
    if (
        type(acceptance) is not dict
        or set(acceptance) != {"schema", "checks"}
        or acceptance["schema"] != _ACCEPTANCE_SCHEMA
        or type(acceptance["checks"]) is not list
        or not 0 < len(acceptance["checks"]) <= 6
    ):
        raise BrokerDeniedError("review acceptance must be an exact frozen checklist")
    try:
        text = candidate.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BrokerDeniedError("candidate is not bounded UTF-8") from exc
    ids = set()
    results = []
    for check in acceptance["checks"]:
        if type(check) is not dict or set(check) != {"id", "type", "value"}:
            raise BrokerDeniedError("invalid checklist item shape")
        check_id, kind, value = check["id"], check["type"], check["value"]
        if (
            type(check_id) is not str
            or not _CHECK_ID.fullmatch(check_id)
            or check_id in ids
            or type(kind) is not str
            or kind not in {
                "CONTAINS_LITERAL", "EXCLUDES_LITERAL", "SEMANTIC_REVIEW_REQUIRED",
            }
            or type(value) is not str
            or len(value.encode("utf-8")) > 200
            or (kind != "SEMANTIC_REVIEW_REQUIRED" and not value)
        ):
            raise BrokerDeniedError("unsupported or duplicate review assertion")
        ids.add(check_id)
        status = (
            "UNKNOWN" if kind == "SEMANTIC_REVIEW_REQUIRED"
            else "PASS" if (
                value in text if kind == "CONTAINS_LITERAL" else value not in text
            ) else "FAIL"
        )
        results.append({"id": check_id, "verdict": status})
    statuses = {x["verdict"] for x in results}
    overall = "FAIL" if "FAIL" in statuses else (
        "UNCERTAIN" if "UNKNOWN" in statuses else "PASS_BOUNDED"
    )
    return overall, results


def expected_review_operation_id(
    request: OfflineReviewRequest, acceptance_sha256: str,
) -> str:
    """Derive a stable operation ID so alternate attempt IDs can't bypass OPENED."""
    binding = {
        "schema": _REQUEST_SCHEMA,
        "task_id": request.task_id,
        "owner": request.owner,
        "grant_ref": request.grant_ref,
        "task_revision": request.task_revision,
        "control_epoch": request.control_epoch,
        "candidate_sha256": request.candidate_sha256,
        "acceptance_sha256": acceptance_sha256,
        "lease_id": request.lease_ref.lease_id,
        "lease_generation": request.lease_ref.generation,
    }
    return "review_" + _digest(_canonical(binding))[:32]


@dataclass(frozen=True)
class BoundedReviewResult:
    operation_id: str
    transport_state: str
    verdict: str
    guest_receipt_sha256: str | None
    checks: tuple[tuple[str, str], ...] = ()
    production_release_qualified: bool = False
    may_dispatch_effect: bool = False
    may_spawn_worker: bool = False


def verify_reviewer_container(
    spec: dict[str, Any], *, image_ref: str, nonce: str,
) -> None:
    """Read the real daemon inspect before starting the Python interpreter."""
    try:
        host, config = spec["HostConfig"], spec["Config"]
        assert spec["Mounts"] == []
        assert config["Image"] == image_ref
        assert config["User"] == "65534:65534"
        assert config["OpenStdin"] is True
        assert config["Entrypoint"] == [
            "python3", "-I", "-B", "/opt/lfl/reviewer.py",
        ]
        assert config["Labels"] == {
            "lfl.assurance.p18_nonce": nonce,
            "lfl.assurance.p18_offline_only": "true",
        }
        assert set(k.split("=", 1)[0] for k in config["Env"]) <= {
            "PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
            "PYTHONDONTWRITEBYTECODE", "HOME",
        }
        assert host["NetworkMode"] == "none"
        assert host["IpcMode"] == "none"
        assert host["ReadonlyRootfs"] is True
        assert host["Privileged"] is False
        assert host["PidsLimit"] == 32
        assert host["Memory"] == 128 * 1024 * 1024
        assert set(host["CapDrop"]) == {"ALL"}
        assert "no-new-privileges" in host["SecurityOpt"]
        for name in (
            "Binds", "Mounts", "Devices", "DeviceRequests",
            "VolumesFrom", "PortBindings", "ExtraHosts",
        ):
            assert not host.get(name)
        assert host.get("PidMode") in ("", None)
        assert host.get("UsernsMode") in ("", None)
    except (KeyError, TypeError, AssertionError) as exc:
        raise BrokerDeniedError("P1.8 untrusted guest isolation mismatch") from exc


class OfflineBoundedReviewer:
    """One frozen Task-owned checklist per current Fleet generation."""

    def __init__(
        self, broker: OfflineHostReviewBroker, *,
        image_ref: str, experimental_root: Path,
    ) -> None:
        if (
            not _IMAGE.fullmatch(image_ref)
            or experimental_root.name != "assurance-p18-root"
            or experimental_root.is_symlink()
            or not _DOCKER.is_file()
        ):
            raise BrokerDeniedError("P1.8 requires exact local test-only Reviewer image")
        self.broker = broker
        self.image_ref = image_ref

    def _docker(
        self, *args: str, input_bytes: bytes | None = None,
        timeout: float = 10.0,
    ) -> bytes:
        env = {
            "PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
            "DOCKER_CONFIG": "/nonexistent", "LC_ALL": "C",
        }
        result = subprocess.run(
            [str(_DOCKER), "--host", _SOCKET, *args],
            input=input_bytes, capture_output=True,
            timeout=timeout, check=False, env=env,
        )
        if result.returncode != 0 or len(result.stdout) > 65_536:
            raise BrokerDeniedError("isolated Reviewer Docker command failed or oversize")
        return result.stdout

    def _run_isolated_guest(
        self, frame: bytes, *, nonce: str,
    ) -> bytes:
        inspect_image = json.loads(
            self._docker("image", "inspect", "--format", "{{json .RepoDigests}}",
                         self.image_ref)
        )
        if not isinstance(inspect_image, list) or self.image_ref not in inspect_image:
            raise BrokerDeniedError("exact local Python Reviewer image not pinned")
        cid = self._docker(
            "create", "--pull=never",
            "--name", "lfl-assurance-p18-" + nonce,
            "--network=none", "--ipc=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=32", "--memory=128m", "--cpus=1",
            "--user=65534:65534", "--interactive",
            "--env", "HOME=/nonexistent",
            "--label", "lfl.assurance.p18_nonce=" + nonce,
            "--label", "lfl.assurance.p18_offline_only=true",
            self.image_ref,
        ).decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", cid):
            raise BrokerDeniedError("Docker guest created without exact container ID")
        try:
            rows = json.loads(self._docker("inspect", cid))
            if not isinstance(rows, list) or len(rows) != 1 or rows[0]["Id"] != cid:
                raise BrokerDeniedError("Docker guest inspect identity lost")
            verify_reviewer_container(rows[0], image_ref=self.image_ref, nonce=nonce)
            result = self._docker(
                "start", "--attach", "--interactive", cid,
                input_bytes=frame, timeout=15,
            )
            if not 0 < len(result) <= _MAX_GUEST_STDOUT:
                raise BrokerDeniedError("bounded review receipt size rejected")
            return result
        finally:
            # A failure to remove our *exact* synthetic container is an
            # execution uncertainty, not permission to report review PASS.
            try:
                self._docker("rm", "--force", cid)
            except Exception as exc:  # noqa: BLE001 - physical cleanup uncertain
                raise BrokerDeniedError("P1.8 synthetic guest cleanup unconfirmed") from exc

    def review_once(
        self, request: OfflineReviewRequest, *,
        candidate: bytes, acceptance: dict[str, Any],
    ) -> BoundedReviewResult:
        if not isinstance(candidate, bytes) or not 0 < len(candidate) <= _MAX_CANDIDATE:
            raise BrokerDeniedError("frozen candidate input oversized")
        if _digest(candidate) != request.candidate_sha256:
            raise BrokerDeniedError("frozen candidate mismatch")
        expected_verdict, expected_checks = validate_acceptance(acceptance, candidate)
        acc_hash = _digest(_canonical(acceptance))
        if not self.broker._guard(request):
            raise BrokerDeniedError("no active exact Owner/Task/Fleet authority")
        control = self.broker.control.read_exact(request.task_id, request.owner)
        if control.acceptance_sha256 != acc_hash:
            raise BrokerDeniedError("acceptance digest changed or unauthoritative")
        if request.operation_id != expected_review_operation_id(request, acc_hash):
            raise BrokerDeniedError("review operation identity must be deterministic")
        evidence = self.broker.catalog.select(
            task_id=request.task_id, owner=request.owner,
            candidate_sha256=request.candidate_sha256,
            evidence_ids=request.evidence_ids,
        )
        if len(evidence) > _MAX_EVIDENCE:
            raise BrokerDeniedError("bounded evidence frame exceeded")
        nonce = secrets.token_hex(16)
        frame = _canonical({
            "schema": _REQUEST_SCHEMA,
            "nonce": nonce,
            "candidate_b64": base64.b64encode(candidate).decode("ascii"),
            "candidate_sha256": request.candidate_sha256,
            "evidence_b64": base64.b64encode(evidence).decode("ascii"),
            "evidence_sha256": _digest(evidence),
            "acceptance": acceptance,
            "acceptance_sha256": acc_hash,
        })
        if len(frame) > _MAX_WIRE_BYTES:
            raise BrokerDeniedError("serialized review frame exceeded 16KiB")
        # OPENED/physical-unknown must survive a real SIGKILL. No alternate
        # attempt ID can bypass the deterministic task + lease operation ID.
        self.broker.journal.begin(request.operation_id, _digest(frame))
        receipt_hash: str | None = None
        verdict = "UNCERTAIN"
        try:
            if not self.broker._guard(request):
                raise BrokerDeniedError("stop or lease changed before guest create")
            content = self._run_isolated_guest(frame, nonce=nonce)
            response = json.loads(content)
            if type(response) is not dict or set(response) != _RECEIPT_KEYS:
                raise BrokerDeniedError("guest schema or keys invalid")
            checks = response["checks"]
            if (
                response["schema"] != _RECEIPT_SCHEMA
                or response["nonce"] != nonce
                or response["candidate_sha256"] != request.candidate_sha256
                or response["acceptance_sha256"] != acc_hash
                or response["evidence_sha256"] != _digest(evidence)
                or response["production_release_qualified"] is not False
                or type(checks) is not list
                or checks != expected_checks
                or response["verdict"] != expected_verdict
            ):
                raise BrokerDeniedError("guest review not verified against host oracle")
            receipt_hash = _digest(content)
            verdict = expected_verdict
        except Exception:  # noqa: BLE001 - partial guest execution means UNKNOWN
            self.broker.journal.settle(request.operation_id, "OUTCOME_UNKNOWN", None)
            return BoundedReviewResult(request.operation_id, "OUTCOME_UNKNOWN", "UNCERTAIN", None)
        state = (
            "UNVERIFIED_OUTPUT" if self.broker._guard(request)
            else "FENCED_AFTER_MODEL"
        )
        self.broker.journal.settle(request.operation_id, state, receipt_hash)
        return BoundedReviewResult(
            request.operation_id, state,
            verdict if state == "UNVERIFIED_OUTPUT" else "UNCERTAIN",
            receipt_hash,
            tuple((c["id"], c["verdict"]) for c in expected_checks)
            if state == "UNVERIFIED_OUTPUT" else (),
        )
