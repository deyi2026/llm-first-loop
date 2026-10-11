"""P1 provider-free, macOS-only Task-owned review subprocess *experiment*.

This supervisor is NOT part of the deployed LoopEngine, ReleaseBroker or Web
control plane. It retains the only writable TaskControlStore authority. The
subprocess receives only a frozen candidate and a fresh scratch SessionStore.

Important limitations:
- Supervisor liveness itself is not yet durably recovered across crashes.
- Sandbox allows broad host file reads for Python imports: owner-scoped
  confidential evidence reads are NOT qualified.
- No real LLM/provider or external effect is permitted.
- A successful process result is NOT a ReviewGate PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.assurance.task_control_store import (
    AuthorityError,
    InvalidContractError,
    TaskControlStore,
)

_SANDBOX = "/usr/bin/sandbox-exec"
_MODES = frozenset({"read_then_final", "unsafe_tool", "block_until_release", "os_probe", "ignore_term"})
_MAX_CANDIDATE_BYTES = 16_384


def _safe_sandbox_literal(path: Path) -> str:
    """Escape a trusted resolved path into an SBPL double-quoted literal."""
    value = str(path.resolve())
    if any(ord(ch) < 32 for ch in value):
        raise InvalidContractError("invalid sandbox path")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()


@dataclass(frozen=True)
class ReviewProcessOutcome:
    phase: str
    process_exit: int | None
    worker_receipt: dict[str, Any] | None
    physical_process_ended: bool
    task_control_epoch: int | None


class OfflineReviewProcess:
    """Hold the real Popen capability: never signal a recovered PID by guessing."""

    def __init__(
        self, *,
        proc: subprocess.Popen[bytes], root: Path,
        store: TaskControlStore, task_id: str, owner: str, accepted_epoch: int,
        job_id: str, candidate_sha256: str, reviewer_session_id: str,
    ) -> None:
        self._proc = proc
        self.root = root
        self._store = store
        self.task_id = task_id
        self.owner = owner
        self.accepted_epoch = accepted_epoch
        self.job_id = job_id
        self.candidate_sha256 = candidate_sha256
        self.reviewer_session_id = reviewer_session_id

    @property
    def pid(self) -> int:
        return self._proc.pid

    def _process_group_alive(self) -> bool:
        """Check the whole sandbox process group, not just the Popen wrapper.

        macOS may return EPERM from killpg(0) after the sandbox process is
        already gone. When Popen has exited, consult OS group membership
        (ignoring zombies). An unavailable observation is still UNKNOWN.
        """
        if self._proc.poll() is not None:
            try:
                observed = subprocess.run(
                    ["/bin/ps", "-A", "-o", "pgid=,stat="],
                    capture_output=True, text=True, timeout=1.3, check=True,
                )
                for line in observed.stdout.splitlines():
                    parts = line.split()
                    if (
                        len(parts) >= 2
                        and int(parts[0]) == self._proc.pid
                        and not parts[1].startswith("Z")
                    ):
                        return True
                return False
            except (OSError, ValueError, subprocess.SubprocessError):
                return True
        try:
            os.killpg(self._proc.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # cannot prove death => UNKNOWN
        return True

    def _signal_owned_group(self, signum: int) -> bool:
        try:
            os.killpg(self._proc.pid, signum)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return True

    def _stop_confirmed(self) -> ReviewProcessOutcome:
        if self._process_group_alive():
            self._signal_owned_group(signal.SIGTERM)
            deadline = time.monotonic() + 0.65
            while self._process_group_alive() and time.monotonic() < deadline:
                time.sleep(0.025)
        if self._process_group_alive():
            self._signal_owned_group(signal.SIGKILL)
            deadline = time.monotonic() + 2.0
            while self._process_group_alive() and time.monotonic() < deadline:
                time.sleep(0.025)
        if self._process_group_alive():
            return ReviewProcessOutcome(
                phase="STOP_UNCERTAIN_PROCESS_GROUP_STILL_PRESENT",
                process_exit=self._proc.poll(), worker_receipt=None,
                physical_process_ended=False,
                task_control_epoch=self._store.read_exact(
                    self.task_id, self.owner
                ).control_epoch,
            )
        if self._proc.poll() is None:
            try:
                self._proc.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                return ReviewProcessOutcome(
                    phase="STOP_UNCERTAIN_WRAPPER_STILL_RUNNING",
                    process_exit=None, worker_receipt=None,
                    physical_process_ended=False,
                    task_control_epoch=self._store.read_exact(
                        self.task_id, self.owner
                    ).control_epoch,
                )
        return ReviewProcessOutcome(
            phase="STOPPED_PROCESS_CONFIRMED_EXTERNAL_EFFECTS_NOT_PROVEN",
            process_exit=self._proc.returncode,
            worker_receipt=None,
            physical_process_ended=True,
            task_control_epoch=self._store.read_exact(self.task_id, self.owner).control_epoch,
        )

    def cancel_for_test_cleanup(self) -> None:
        """For P1 tests only: kill precisely the Popen child capability we own."""
        if self._process_group_alive():
            self._signal_owned_group(signal.SIGKILL)
        if self._proc.poll() is None:
            self._proc.wait(timeout=3.0)

    def _receipt(self) -> dict[str, Any] | None:
        receipt_path = self.root / "receipts" / "terminal.json"
        if not receipt_path.is_file():
            return None
        try:
            body = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(body, dict) or set(body) != {
                "schema", "job_id", "task_id", "owner", "reviewer_session_id",
                "candidate_sha256", "accepted_epoch", "status",
                "terminal_text_sha256", "tool_names_attempted", "os_probe",
            }:
                return None
            if any((
                body["schema"] != "lfl.dual_assurance.p1_offline_review_result/v1",
                body["job_id"] != self.job_id,
                body["task_id"] != self.task_id,
                body["owner"] != self.owner,
                body["candidate_sha256"] != self.candidate_sha256,
                body["reviewer_session_id"] != self.reviewer_session_id,
                body["accepted_epoch"] != self.accepted_epoch,
            )):
                return None
            if (
                not isinstance(body["tool_names_attempted"], list)
                or not all(isinstance(name, str) for name in body["tool_names_attempted"])
                or not isinstance(body["terminal_text_sha256"], str)
                or len(body["terminal_text_sha256"]) != 64
                or not isinstance(body["os_probe"], dict)
            ):
                return None
            return body
        except (OSError, ValueError):
            return None

    def observe(self) -> ReviewProcessOutcome:
        """Must compare current durable STOP before accepting any terminal receipt."""
        try:
            state = self._store.read_exact(self.task_id, self.owner)
        except AuthorityError:
            # Losing the control authority is an immediate process-stop event.
            # This process may still have had an in-flight external effect; do not
            # infer anything about such effects from process termination.
            self.cancel_for_test_cleanup()
            return ReviewProcessOutcome("CONTROL_AUTHORITY_UNREADABLE", self._proc.poll(), None, True, None)
        if state.state != "ACTIVE" or state.control_epoch != self.accepted_epoch:
            return self._stop_confirmed()
        exitcode = self._proc.poll()
        if exitcode is None:
            return ReviewProcessOutcome("RUNNING", None, None, False, state.control_epoch)
        try:
            candidate_now = (self.root / "immutable" / "candidate.txt").read_bytes()
            if hashlib.sha256(candidate_now).hexdigest() != self.candidate_sha256:
                return ReviewProcessOutcome(
                    "UNQUALIFIED_CANDIDATE_DRIFT",
                    exitcode, None, True, state.control_epoch,
                )
        except OSError:
            return ReviewProcessOutcome(
                "UNQUALIFIED_CANDIDATE_UNREADABLE",
                exitcode, None, True, state.control_epoch,
            )
        body = self._receipt() if exitcode == 0 else None
        if body is None:
            return ReviewProcessOutcome("FAILED_OR_UNBOUND_RECEIPT", exitcode, None, True, state.control_epoch)
        status = str(body["status"])
        if status not in {
            "STRUCTURAL_PROBE_ONLY_NO_REVIEW_GATE_PASS",
            "UNQUALIFIED_UNSAFE_TOOL_ATTEMPT",
        }:
            return ReviewProcessOutcome("UNQUALIFIED_WORKER_RECEIPT", exitcode, None, True, state.control_epoch)
        return ReviewProcessOutcome(status, exitcode, body, True, state.control_epoch)

    def wait(self, *, timeout_s: float = 5.0, poll_s: float = 0.04) -> ReviewProcessOutcome:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self.observe()
            if result.phase != "RUNNING":
                return result
            time.sleep(poll_s)
        return ReviewProcessOutcome(
            "WAIT_TIMEOUT_STILL_RUNNING", self._proc.poll(), None,
            self._proc.poll() is not None, None,
        )


class OfflineReviewSupervisor:
    """Experiment-only Task-owned process launcher, not production entrypoint."""

    # 显式类级注解：__init__ 含条件 raise 守卫，属性赋值位于分支之后；
    # 在部分环境下 pyright 对该形态的推断会退化为 partial（OfflineReviewSupervisor*），
    # 显式声明使 self.root/control/owner/denied_read_roots 的类型不依赖推断。
    root: Path
    control: TaskControlStore
    owner: str
    denied_read_roots: tuple[Path, ...]

    def __init__(
        self, root: Path | str, control: TaskControlStore, owner: str,
        *, denied_read_roots: tuple[Path, ...],
        offline_experiment_approved: bool = False,
    ) -> None:
        base = Path(root).resolve()
        if base.name != "assurance-p1-root" or offline_experiment_approved is not True:
            raise InvalidContractError("P1 supervisor requires isolated test root and opt-in")
        if sys.platform != "darwin" or not Path(_SANDBOX).is_file():
            raise InvalidContractError("P1 macOS sandbox-exec unavailable; fail closed")
        self.root = base
        self.control = control
        self.owner = owner
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not denied_read_roots:
            raise InvalidContractError("explicit P1 forbidden owner roots required")
        self.denied_read_roots = tuple(path.resolve() for path in denied_read_roots)
        for path in self.denied_read_roots:
            if (
                not path.is_dir()
                or path.is_symlink()
                or not path.is_relative_to(self.root.parent)
                or path == self.root
                or self.root.is_relative_to(path)
            ):
                raise InvalidContractError("invalid forbidden owner root")

    def start(self, task_id: str, candidate: bytes, *, mode: str) -> OfflineReviewProcess:
        if mode not in _MODES:
            raise InvalidContractError("unapproved offline FakeLLM reviewer mode")
        if len(candidate) == 0 or len(candidate) > _MAX_CANDIDATE_BYTES:
            raise InvalidContractError("empty or oversized reviewer candidate")
        state = self.control.read_exact(task_id, self.owner)
        if state.state != "ACTIVE":
            raise InvalidContractError("durable STOP prohibits new reviewer")
        job_id = "review_" + secrets.token_hex(14)
        root = self.root / job_id
        for folder in ("immutable", "scratch", "receipts"):
            (root / folder).mkdir(parents=True, mode=0o700)
        immutable, scratch, receipts = (
            root / "immutable", root / "scratch", root / "receipts"
        )
        candidate_sha = hashlib.sha256(candidate).hexdigest()
        candidate_path = immutable / "candidate.txt"
        candidate_path.write_bytes(candidate)
        candidate_path.chmod(0o400)

        # Only the trusted supervisor creates the exact reviewer session.
        from llm_loop.config import Settings
        from llm_loop.core.session import SessionStore

        settings = Settings(
            llm_api_key="k", llm_base_url="https://example.invalid/v1",
            llm_model="offline", data_dir=str(scratch / "data"),
            extract_enabled=False, max_iterations=4,
        )
        reviewer_session_id = SessionStore(settings.sessions_dir).create()
        spec = {
            "schema": "lfl.dual_assurance.p1_offline_review_request/v1",
            "job_id": job_id,
            "task_id": task_id,
            "owner": self.owner,
            "candidate_path": str(candidate_path),
            "candidate_sha256": candidate_sha,
            "acceptance_sha256": state.acceptance_sha256,
            "accepted_epoch": state.control_epoch,
            "reviewer_session_id": reviewer_session_id,
            "author_session_id": "offline_executor_already_terminal",
            "scratch_path": str(scratch),
            "receipt_path": str(receipts / "terminal.json"),
            "mode": mode,
        }
        _atomic_json(immutable / "spec.json", spec)
        # macOS sandbox-exec does not currently launch this venv reliably
        # with a fully closed file-read allowlist. Explicit denied OwnerScope
        # roots are enforced by OS sandbox, but other arbitrary reads remain
        # possible. This is a *known P1 NO-GO* for sensitive data, not a
        # production readonly Reviewer policy.
        denied_read_clauses = "\n".join(
            f"(deny file-read* (subpath {_safe_sandbox_literal(path)}))"
            for path in self.denied_read_roots
        )
        profile = (
            "(version 1)\n"
            "(deny default)\n"
            "(allow file-read*)\n"
            f"{denied_read_clauses}\n"
            "(allow process*)\n"
            "(deny process-fork)\n"
            "(allow sysctl-read)\n"
            "(allow mach-lookup)\n"
            f"(allow file-write* (subpath {_safe_sandbox_literal(scratch)}))\n"
            f"(allow file-write* (subpath {_safe_sandbox_literal(receipts)}))\n"
        )
        (immutable / "sandbox.sb").write_text(profile, encoding="utf-8")
        (immutable / "sandbox.sb").chmod(0o400)

        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(scratch),
            "TMPDIR": str(scratch),
            "LFL_DATA_DIR": str(scratch / "data"),
            "DATA_DIR": str(scratch / "data"),
            "LFL_LEAK_GUARD_MODE": "observe",  # offline tests only
            "LC_ALL": "C",
        }
        # Fail-closed on incorrect sandbox policies. No unsandboxed fallback.
        sandbox_args = [
            _SANDBOX, "-f", str(immutable / "sandbox.sb"), sys.executable,
            "-m", "llm_loop.assurance.p1_review_worker",
            "--offline-experiment", str(immutable / "spec.json"),
        ]
        # Preparing a candidate and the Python SessionStore takes time.
        # Do not reuse the admission snapshot if a human STOP arrived during
        # that preparation. This is a necessary (NOT atomic/sufficient) fence:
        # a post-check STOP still needs a separate dispatch-release handshake
        # before provider/tool operations can be considered production-safe.
        current = self.control.read_exact(task_id, self.owner)
        if current.state != "ACTIVE" or current.control_epoch != state.control_epoch:
            raise InvalidContractError("Task STOP/control epoch changed during preparation")
        with (scratch / "stdout.log").open("wb") as stdout, (
            scratch / "stderr.log"
        ).open("wb") as stderr:
            proc = subprocess.Popen(
                sandbox_args, env=env, cwd=scratch,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                start_new_session=True,
            )
        if not proc.pid:
            raise InvalidContractError("no child process identity")
        return OfflineReviewProcess(
            proc=proc, root=root, store=self.control,
            task_id=task_id, owner=self.owner,
            accepted_epoch=state.control_epoch,
            job_id=job_id, candidate_sha256=candidate_sha,
            reviewer_session_id=reviewer_session_id,
        )
