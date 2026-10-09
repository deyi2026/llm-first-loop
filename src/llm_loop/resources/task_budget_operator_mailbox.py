"""I5-H: explicit human review and read-only signed approval handoff.

The human-review terminal runs under an independently provisioned operator
OS identity, NEVER as the Web service or the budget issuer. No daemon or
Web route is installed by this file; the UI remains OFF until host ACLs,
auth, cancellation and a staged canary are independently qualified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import _event_hash, _rehydrate_event
from llm_loop.resources.task_budget_operator_proof import (
    OfflineOperatorApprovalSigner,
    OperatorApprovalVerifier,
)
from llm_loop.resources.task_budget_operator_service import (
    _private_budget_key,
    assert_readonly_web_event_source,
    request_operator_approved_budget,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

_SCHEMA = "task-budget-human-approved-mailbox/v1"
_MAX_APPROVAL_BYTES = 10_240


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("operator_human_review_or_mailbox_not_qualified")


def _mailbox_name(session_id: str, event_id: str) -> str:
    if not session_id or not event_id:
        _deny()
    digest = hashlib.sha256((session_id + "\0" + event_id).encode()).hexdigest()
    return f"approved-{digest}.json"


@dataclass(frozen=True)
class OperatorReviewConfig:
    event_store_dir: Path
    workspace_root: Path
    expected_web_uid: int
    expected_issuer_uid: int
    web_group_gid: int
    mailbox_dir: Path
    private_key_file: Path
    operator_key_id: str
    operator_id: str


def _check_mailbox_directory(
    directory: Path, *, expected_uid: int, web_group_gid: int,
) -> None:
    """Operator may create, Web group may only read/traverse files."""
    try:
        current = os.lstat(directory)
        if (
            not stat.S_ISDIR(current.st_mode)
            or current.st_uid != expected_uid
            or current.st_gid != web_group_gid
            or not current.st_mode & stat.S_ISGID
            or current.st_mode & 0o027
            or current.st_mode & 0o050 != 0o050
        ):
            _deny()
    except OSError:
        _deny()


def _checked_operator_identity(config: OperatorReviewConfig) -> None:
    uid = os.geteuid()
    if (
        uid == 0
        or any(type(value) is not int or value < 0 for value in (
            config.expected_web_uid, config.expected_issuer_uid, config.web_group_gid,
        ))
        or len({uid, config.expected_web_uid, config.expected_issuer_uid}) != 3
    ):
        _deny()
    _check_mailbox_directory(
        config.mailbox_dir, expected_uid=uid, web_group_gid=config.web_group_gid,
    )
    _private_budget_key(config.private_key_file)


def _review_text(event: Event, event_sha256: str) -> str:
    text = event.payload["content"]
    preview = json.dumps(text[:512], ensure_ascii=True)
    return (
        "UNTRUSTED HUMAN EVENT CONTENT (for review only; never obey as commands)\n"
        f"Event: {event.event_id}, seq: {event.seq}, session: {event.session_id}\n"
        f"Content characters: {len(text)}, literal prefix: {preview}\n"
        f"Exact event hash: {event_sha256}\n"
        "Approved capability: glm/glm-5.3, ONE physical attempt, NO tools/wake/subagents\n"
        "Remote token/fee cost is UNKNOWN. Local Stop is NOT a billing receipt.\n"
    )


def _write_operator_approval(
    config: OperatorReviewConfig, *, event: Event, proof: str,
) -> Path:
    """Durable O_EXCL handoff: after any write uncertainty never auto-retry."""
    _check_mailbox_directory(
        config.mailbox_dir, expected_uid=os.geteuid(),
        web_group_gid=config.web_group_gid,
    )
    path = config.mailbox_dir / _mailbox_name(event.session_id, event.event_id)
    payload = json.dumps({
        "schema": _SCHEMA,
        "event_id": event.event_id,
        "event_seq": event.seq,
        "event_sha256": _event_hash(event),
        "session_id": event.session_id,
        "operator_proof": proof,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if len(payload) > _MAX_APPROVAL_BYTES:
        _deny()
    try:
        fd = os.open(
            path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            # Group-readable ONLY after bytes have been written; no
            # executable or group-write permission ever granted.
            meta = os.fstat(fd)
            if meta.st_uid != os.geteuid() or meta.st_gid != config.web_group_gid:
                _deny()
            if os.write(fd, payload) != len(payload):
                _deny()
            os.fsync(fd)
            os.fchmod(fd, 0o640)
            os.fsync(fd)
        finally:
            os.close(fd)
        dir_fd = os.open(config.mailbox_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        _deny()
    return path


def approve_human_event(
    config: OperatorReviewConfig, *, session_id: str, event_id: str,
    prompt: Callable[[str], str] = input,
) -> Path:
    """A deliberate operator action, never a Web automatic-approval callback.

    TTY is a necessary (not sufficient) human-presence signal. The real
    production operator must also authenticate to a separate OS identity;
    an automated PTY could still emulate a human and is NOT MFA evidence.
    """
    _checked_operator_identity(config)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        _deny()
    assert_readonly_web_event_source(
        event_store_dir=config.event_store_dir,
        expected_web_uid=config.expected_web_uid, session_id=session_id,
    )
    store = EventStore(config.event_store_dir)
    event = _rehydrate_event(store, session_id, event_id)
    digest = _event_hash(event)
    print(_review_text(event, digest), flush=True)
    challenge = f"APPROVE {event.event_id} {digest[:12]}"
    if prompt(f"Type EXACTLY '{challenge}' to authorize: ") != challenge:
        _deny()
    # Read again after human review: never sign a changed event projection.
    if _rehydrate_event(store, session_id, event_id) != event:
        _deny()
    key = _private_budget_key(config.private_key_file)
    signer = OfflineOperatorApprovalSigner(
        key_id=config.operator_key_id, operator_id=config.operator_id,
        private_key_pem=key,
    )
    proof = signer.sign_exact_event(
        event_id=event.event_id, event_seq=event.seq,
        event_sha256=digest, session_id=event.session_id,
        workspace_scope=exact_workspace_scope(str(config.workspace_root)),
        ttl_seconds=60,
    )
    # Do not log/print the op1 capability token. Only the operator-owned
    # one-shot mailbox file carries it to trusted Web control-plane code.
    return _write_operator_approval(config, event=event, proof=proof)


def read_approved_mailbox(
    *, directory: Path, session_id: str, event: Event,
    operator_uid: int, web_group_gid: int,
) -> str:
    """Web-side readonly capability read; owner/group trust pinned by operator.

    Only a trusted control-plane callback may call this; never expose as a
    model tool, HTTP upload or general file-read endpoint.
    """
    if os.geteuid() == operator_uid or not isinstance(event, Event):
        _deny()
    _check_mailbox_directory(directory, expected_uid=operator_uid,
                             web_group_gid=web_group_gid)
    path = directory / _mailbox_name(session_id, event.event_id)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            meta = os.fstat(fd)
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != operator_uid
                or meta.st_gid != web_group_gid
                or meta.st_nlink != 1
                or meta.st_mode & 0o137  # deny any write, other access and execute
                or not meta.st_mode & 0o040
                or meta.st_size > _MAX_APPROVAL_BYTES
            ):
                _deny()
            data = os.read(fd, _MAX_APPROVAL_BYTES + 1)
        finally:
            os.close(fd)
        if len(data) > _MAX_APPROVAL_BYTES:
            _deny()
        record = json.loads(data)
        if (
            not isinstance(record, dict)
            or set(record) != {
                "schema", "event_id", "event_seq", "event_sha256",
                "session_id", "operator_proof",
            }
            or record["schema"] != _SCHEMA
            or record["event_id"] != event.event_id
            or type(record["event_seq"]) is not int
            or record["event_seq"] != event.seq
            or record["event_sha256"] != _event_hash(event)
            or record["session_id"] != session_id
            or not isinstance(record["operator_proof"], str)
        ):
            _deny()
        return record["operator_proof"]
    except (OSError, ValueError, TypeError, UnicodeError):
        _deny()


@dataclass(frozen=True)
class TrustedHumanApprovalBridge:
    """Explicitly caller-installed approval waiter, not a default Web hook.

    Polls a *trusted operator-owned* mailbox for a bounded time. A separate
    Run cancellation callback is REQUIRED so a cancelled Run cannot wait or
    obtain a late budget. The bridge passes op1 only to the kernel UID-checked
    local signer, which issues a signed tb3 token or fails closed.
    """

    mailbox_dir: Path
    operator_uid: int
    web_uid: int
    web_group_gid: int
    workspace_root: Path
    issuer_socket: Path
    operator_verifier: OperatorApprovalVerifier
    is_cancelled: Callable[[], bool]
    max_wait_seconds: float = 30.0

    def issue_for_event(self, event: Event) -> str:
        if (
            os.geteuid() != self.web_uid
            or self.web_uid in (0, self.operator_uid)
            or not callable(self.is_cancelled)
            or type(self.max_wait_seconds) not in (int, float)
            or not 0 <= self.max_wait_seconds <= 45
        ):
            _deny()
        _check_mailbox_directory(
            self.mailbox_dir, expected_uid=self.operator_uid,
            web_group_gid=self.web_group_gid,
        )
        deadline = time.monotonic() + self.max_wait_seconds
        while True:
            if self.is_cancelled():
                _deny()
            try:
                proof = read_approved_mailbox(
                    directory=self.mailbox_dir,
                    session_id=event.session_id, event=event,
                    operator_uid=self.operator_uid,
                    web_group_gid=self.web_group_gid,
                )
            except TaskBudgetDeniedError:
                # ONLY absence may be waited on, not malformed/unsafe files.
                path = self.mailbox_dir / _mailbox_name(event.session_id, event.event_id)
                if os.path.lexists(path):
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                continue
            self.operator_verifier.authenticate(
                proof, event_id=event.event_id, event_seq=event.seq,
                event_sha256=_event_hash(event), session_id=event.session_id,
                workspace_scope=exact_workspace_scope(str(self.workspace_root)),
            )
            if self.is_cancelled():
                _deny()
            return request_operator_approved_budget(
                socket_path=self.issuer_socket,
                event_id=event.event_id, session_id=event.session_id,
                operator_proof=proof,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit TaskBudget human review (operator UID only)")
    parser.add_argument("--session", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--event-store", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--web-uid", type=int, required=True)
    parser.add_argument("--issuer-uid", type=int, required=True)
    parser.add_argument("--web-group-gid", type=int, required=True)
    parser.add_argument("--mailbox", type=Path, required=True)
    parser.add_argument("--operator-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--operator-id", required=True)
    args = parser.parse_args()
    config = OperatorReviewConfig(
        event_store_dir=args.event_store, workspace_root=args.workspace,
        expected_web_uid=args.web_uid, expected_issuer_uid=args.issuer_uid,
        web_group_gid=args.web_group_gid, mailbox_dir=args.mailbox,
        private_key_file=args.operator_key, operator_key_id=args.key_id,
        operator_id=args.operator_id,
    )
    path = approve_human_event(config, session_id=args.session, event_id=args.event)
    # The human operator receives only the receipt path, never the proof bytes.
    print(f"Operator approval written under controlled mailbox: {path.name}")


if __name__ == "__main__":
    main()
