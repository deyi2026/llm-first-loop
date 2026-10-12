"""Sandbox-only offline P1 subprocess entrypoint, never a production provider.

The trusted supervisor owns TaskControlStore and starts this process with
macOS sandbox-exec. This module cannot be run directly without an opt-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from llm_loop.assurance.review_contract import FrozenReviewRequest
from llm_loop.assurance.task_control_store import InvalidContractError
from llm_loop.assurance.task_owned_reviewer_probe import (
    FrozenCandidateReadTool,
    run_real_loopengine_review_probe,
)
from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse


def _probe_sandbox(candidate_path: Path, scratch: Path) -> dict[str, bool]:
    """Adversarial OS probes, without real external service connections."""
    checks = {
        "candidate_write_denied": False,
        "subprocess_write_denied": False,
        "network_denied": False,
        "scratch_write_allowed": False,
        "other_owner_read_denied": False,
        "subprocess_other_owner_read_denied": False,
        "symlink_other_owner_read_denied": False,
        "process_fork_denied": False,
        "subprocess_spawn_denied": False,
    }
    try:
        candidate_path.write_text("MALICIOUS_REVIEWER_OVERWRITE", encoding="utf-8")
    except OSError:
        checks["candidate_write_denied"] = True

    # Even a spawned subprocess must inherit the OS-level sandbox. The Python
    # source text is a trusted test fixture, not an instruction from the model.
    try:
        sub = subprocess.run(
            [sys.executable, "-c", "import sys;open(sys.argv[1],'wb').write(b'REVIEWER_ESCAPE')",
             str(candidate_path)],
            capture_output=True, timeout=2.5, check=False,
        )
        checks["subprocess_write_denied"] = sub.returncode != 0
    except OSError:
        checks["subprocess_write_denied"] = True
        checks["subprocess_spawn_denied"] = True
    try:
        forked_pid = os.fork()
        if forked_pid == 0:
            os._exit(0)
        os.waitpid(forked_pid, 0)
    except OSError:
        checks["process_fork_denied"] = True
    try:
        sock = socket.socket()
        try:
            sock.settimeout(0.3)
            sock.connect(("127.0.0.1", 9))
        finally:
            sock.close()
    except PermissionError:
        checks["network_denied"] = True
    except OSError:
        # Connection refused ≠ sandbox denied: do not overstate the result.
        checks["network_denied"] = False

    try:
        (scratch / "probe-ok").write_text("only private scratch", encoding="utf-8")
        checks["scratch_write_allowed"] = True
    except OSError:
        pass
    # A separate user's data must not become readable just because Reviewer is
    # "read-only". The fixture file is a synthetic string, never real user data.
    other_owner_path = candidate_path.parents[3] / "other-owner-private" / "secret.txt"
    try:
        other_owner_path.read_bytes()
    except OSError:
        checks["other_owner_read_denied"] = True
    try:
        subread = subprocess.run(
            [sys.executable, "-c", "import sys;open(sys.argv[1],'rb').read()",
             str(other_owner_path)],
            capture_output=True, timeout=2.5, check=False,
        )
        checks["subprocess_other_owner_read_denied"] = subread.returncode != 0
    except OSError:
        checks["subprocess_other_owner_read_denied"] = True
    # An explicitly denied Owner root should remain denied when reached
    # through a symlink placed inside the otherwise writable scratch area.
    indirect = scratch / "other-owner-symlink"
    try:
        indirect.symlink_to(other_owner_path)
        indirect.read_bytes()
    except OSError:
        checks["symlink_other_owner_read_denied"] = True
    return checks


class OfflineReviewerLLM:
    """Narrow deterministic fake model; never makes HTTP requests."""

    max_tokens = None
    wire_protocol = "openai"

    def __init__(self, *, mode: str, candidate_sha: str, scratch: Path) -> None:
        self.mode = mode
        self.candidate_sha = candidate_sha
        self.scratch = scratch
        self.calls = 0

    def chat(
        self, messages: list[dict], tools: list[dict],
        *, timeout_s: float | None = None, model: str | None = None,
    ) -> LLMResponse:
        del messages, tools, timeout_s, model
        self.calls += 1
        if self.mode == "unsafe_tool" and self.calls == 1:
            return LLMResponse(
                content="", provider="fake",
                tool_calls=[ToolCall(
                    id="sandbox_shell_attempt", name="execute_command",
                    arguments={"command": "touch /tmp/untrusted"},
                )],
            )
        if self.mode == "read_then_final" and self.calls == 1:
            return LLMResponse(
                content="", provider="fake",
                tool_calls=[ToolCall(
                    id="sandbox_read_candidate", name="review_frozen_candidate",
                    arguments={"candidate_sha256": self.candidate_sha},
                )],
            )
        if self.mode in {"block_until_release", "ignore_term"}:
            # Test a stuck provider call; stop is enforced by the outside
            # Supervisor, not by granting this model process control-store IO.
            (self.scratch / "entered_block.flag").write_text("model blocked", encoding="utf-8")
            while not (self.scratch / "release.flag").exists():
                time.sleep(0.05)
        return LLMResponse(
            content="Offline-only bounded review; never a release PASS",
            tool_calls=[], provider="fake",
        )


def _write_receipt(path: Path, body: dict[str, Any]) -> None:
    raw = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--offline-experiment":
        raise InvalidContractError("offline P1 sandbox must be explicitly launched")
    spec_path = Path(sys.argv[2]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if (
        not isinstance(spec, dict)
        or spec.get("schema") != "lfl.dual_assurance.p1_offline_review_request/v1"
        or spec_path.parent.name != "immutable"
        or spec_path.parent.parent.parent.name != "assurance-p1-root"
    ):
        raise InvalidContractError("invalid or unbound sandbox request")
    scratch = Path(spec["scratch_path"]).resolve()
    candidate_path = Path(spec["candidate_path"]).resolve()
    result_path = Path(spec["receipt_path"]).resolve()
    run_root = spec_path.parent.parent
    if (
        scratch != run_root / "scratch"
        or candidate_path != run_root / "immutable" / "candidate.txt"
        or result_path != run_root / "receipts" / "terminal.json"
    ):
        raise InvalidContractError("forged or out-of-root reviewer paths")

    original = candidate_path.read_bytes()
    sha = hashlib.sha256(original).hexdigest()
    if sha != spec["candidate_sha256"]:
        raise InvalidContractError("candidate fingerprint drift at launch")
    os_probe: dict[str, bool] = {}
    if spec["mode"] == "ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if spec["mode"] == "os_probe":
        os_probe = _probe_sandbox(candidate_path, scratch)
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.memory.store import MemoryStore
    from llm_loop.tools.registry import ToolRegistry

    settings = Settings(
        llm_api_key="k", llm_base_url="https://example.invalid/v1",
        llm_model="offline", data_dir=str(scratch / "data"),
        extract_enabled=False, max_iterations=4,
    )
    registry = ToolRegistry()
    registry.register(FrozenCandidateReadTool(original, sha))
    engine = LoopEngine(
        llm_client=OfflineReviewerLLM(
            mode=spec["mode"], candidate_sha=sha, scratch=scratch,
        ),  # type: ignore[arg-type] - offline LLM protocol stub
        registry=registry,
        memory=MemoryStore(settings.memory_dir),
        session=SessionStore(settings.sessions_dir),
        settings=settings,
    )
    bound = FrozenReviewRequest(
        task_id=spec["task_id"],
        owner=spec["owner"],
        candidate_sha256=sha,
        acceptance_sha256=spec["acceptance_sha256"],
        author_session_id=spec["author_session_id"],
        reviewer_session_id=spec["reviewer_session_id"],
    )
    outcome = run_real_loopengine_review_probe(
        review_request=bound,
        engine=engine,
        frozen_bytes=original,
        accepted_stop_epoch=spec["accepted_epoch"],
        # This is a structural probe. Only the outside Supervisor can read
        # authoritative STOP; it always rechecks before trusting the receipt.
        read_current_stop_epoch=lambda _task: spec["accepted_epoch"],
    )
    if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != sha:
        raise InvalidContractError("candidate changed while reviewer executed")
    _write_receipt(result_path, {
        "schema": "lfl.dual_assurance.p1_offline_review_result/v1",
        "job_id": spec["job_id"],
        "task_id": bound.task_id,
        "owner": bound.owner,
        "reviewer_session_id": outcome.reviewer_session_id,
        "candidate_sha256": sha,
        "accepted_epoch": spec["accepted_epoch"],
        "status": outcome.status,
        "terminal_text_sha256": outcome.terminal_text_sha256,
        "tool_names_attempted": list(outcome.tool_names_attempted),
        "os_probe": os_probe,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
