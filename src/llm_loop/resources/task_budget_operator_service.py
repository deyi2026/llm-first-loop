"""I5-G operator-only Unix-socket budget issuer (never auto-started).

An independently provisioned OS account holds the budget signing key. The
Web account sends an already independently signed `op1` human approval,
never an operator password or private key. The socket peer UID is checked
at the kernel boundary and the server rereads the authoritative EventStore.
This code is NOT a production deployment, key-vault/UX implementation, or
remote Provider/billing qualification. No entrypoint installs a Web route.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import stat
import struct
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from Crypto.PublicKey import ECC

from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_event_authority import _rehydrate_event
from llm_loop.resources.task_budget_operator_proof import load_pinned_operator_verifier
from llm_loop.resources.task_budget_positive_authority import ApprovedOneAttemptIssuer
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

_REQUEST_MAX = 10_240
_RESPONSE_MAX = 12_288


def _deny() -> NoReturn:
    raise TaskBudgetDeniedError("operator_signer_service_denied")


def _owner_directory(path: Path) -> None:
    try:
        st = os.lstat(path)
        if (
            not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or st.st_mode & 0o022  # other users cannot rename socket/key files
        ):
            _deny()
    except OSError:
        _deny()


def _private_budget_key(path: Path) -> bytes:
    """Read a pre-provisioned signer key; never create/print/copy it to Web."""
    _owner_directory(path.parent)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_mode & 0o077 or st.st_nlink != 1
                or st.st_size > 8192
            ):
                _deny()
            raw = os.read(fd, 8193)
        finally:
            os.close(fd)
        if len(raw) > 8192:
            _deny()
        key = ECC.import_key(raw)
        if key.curve != "Ed25519" or not key.has_private():
            _deny()
        return raw
    except (OSError, ValueError, TypeError):
        _deny()


def assert_readonly_web_event_source(
    *, event_store_dir: Path, expected_web_uid: int, session_id: str,
) -> None:
    """Check the ACTUAL issuer UID has read-only Web EventStore access.

    Never infer an ACL from a printed ``ls -le`` string or from a declared
    username. The kernel must allow O_RDONLY and refuse write access in the
    current process. Rotated/multi-segment logs need a separate ACL contract;
    fail closed rather than approving a partial EventStore projection.
    """
    store = EventStore(event_store_dir, enabled=True)
    try:
        if os.geteuid() == expected_web_uid or store._is_multi_segment(session_id):
            _deny()
        directory = os.lstat(event_store_dir)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != expected_web_uid
            or directory.st_mode & 0o002
            or os.access(event_store_dir, os.W_OK)
        ):
            _deny()
        path = Path(store._path(session_id))
        # On macOS mode 0600 can still have an explicit read-only ACL for
        # another UID. Do NOT weaken POSIX modes to 0644 to make this pass.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            source = os.fstat(fd)
            if (
                not stat.S_ISREG(source.st_mode)
                or source.st_uid != expected_web_uid
                or source.st_nlink != 1
                or source.st_mode & 0o077
                or os.access(path, os.W_OK)
            ):
                _deny()
            # Verify a real readable byte/EOF with this process identity.
            os.read(fd, 1)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        _deny()


def _assert_readonly_event_source(config: OperatorServiceConfig, session_id: str) -> None:
    assert_readonly_web_event_source(
        event_store_dir=config.event_store_dir,
        expected_web_uid=config.expected_web_uid, session_id=session_id,
    )


def _peer_uid(conn: socket.socket) -> int:
    """Kernel-authenticated Unix peer identity, fail-closed off Linux/macOS."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.getpeereid
        function.argtypes = (
            ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
        )
        function.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if function(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            _deny()
        return uid.value
    if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
        pid, uid, gid = struct.unpack(
            "3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12),
        )
        if pid < 1 or uid < 0 or gid < 0:
            _deny()
        return uid
    _deny()


def _read_frame(conn: socket.socket, limit: int) -> dict[str, Any]:
    conn.settimeout(3.0)
    content = bytearray()
    while len(content) <= limit:
        fragment = conn.recv(min(4096, limit + 2 - len(content)))
        if not fragment:
            _deny()
        content += fragment
        if b"\n" in fragment:
            if content.count(b"\n") != 1 or content[-1] != 10:
                _deny()
            try:
                value = json.loads(content[:-1])
                if not isinstance(value, dict):
                    _deny()
                return value
            except (ValueError, UnicodeError):
                _deny()
    _deny()


def _send_frame(conn: socket.socket, value: dict[str, Any]) -> None:
    packet = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if len(packet) > _RESPONSE_MAX:
        _deny()
    conn.sendall(packet)


@dataclass(frozen=True)
class OperatorServiceConfig:
    socket_path: Path
    expected_web_uid: int
    event_store_dir: Path
    workspace_root: Path
    budget_key_file: Path
    budget_key_id: str
    operator_trust_file: Path
    audit_dir: Path
    expected_web_gid: int | None = None

    def validate_boundary(self) -> None:
        if (
            os.geteuid() == 0  # do not run the issuer with root capabilities
            or type(self.expected_web_uid) is not int
            or self.expected_web_uid < 0
            or self.expected_web_uid == os.geteuid()
        ):
            _deny()
        _owner_directory(self.socket_path.parent)
        _owner_directory(self.audit_dir)
        # These paths must be intentionally provisioned and are never
        # created as a side effect of constructing or checking this service.
        _private_budget_key(self.budget_key_file)
        load_pinned_operator_verifier(self.operator_trust_file)

    def validate_live_socket_boundary(self) -> None:
        """Only a pre-provisioned operator-owned, Web-group-traversable dir.

        Merely accepting a --web-uid CLI argument or chmodding the socket
        cannot establish a real Web-to-issuer Unix IPC permission boundary.
        This check is mandatory on actual daemon start, not just unit RPC.
        """
        self.validate_boundary()
        if (
            type(self.expected_web_gid) is not int
            or self.expected_web_gid < 0
            or len(os.fsencode(str(self.socket_path))) >= 100
            or not self.socket_path.is_absolute()
        ):
            _deny()
        folder = os.lstat(self.socket_path.parent)
        if (
            folder.st_gid != self.expected_web_gid
            or not folder.st_mode & stat.S_ISGID
            or folder.st_mode & 0o027
            or folder.st_mode & 0o050 != 0o050
        ):
            _deny()
        event_dir = os.lstat(self.event_store_dir)
        if (
            not stat.S_ISDIR(event_dir.st_mode)
            or event_dir.st_uid != self.expected_web_uid
            or event_dir.st_mode & 0o002
            or os.access(self.event_store_dir, os.W_OK)
            or not os.access(self.event_store_dir, os.R_OK | os.X_OK)
        ):
            _deny()


def _audit_receipt(directory: Path, *, event_id: str, session_id: str, token: str) -> None:
    """Write a durable, bounded receipt BEFORE the positive token escapes."""
    _owner_directory(directory)
    # Persistent O_EXCL fence is deliberately independent of the Web Run
    # ledger. Even if a crash happens after file creation but before fsync,
    # a subsequent request for this SAME event MUST NOT issue another token.
    # Never remove/repair an uncertain fence automatically.
    event_key = hashlib.sha256((session_id + "\0" + event_id).encode()).hexdigest()
    fence_path = directory / f"issued-{event_key}.json"
    fence = json.dumps({
        "schema": "operator-approval-one-shot/v1",
        "event_id": event_id, "session_id": session_id,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "timestamp": time.time(),
    }, separators=(",", ":"), ensure_ascii=True).encode()
    try:
        fd = os.open(
            fence_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.write(fd, fence) != len(fence):
                _deny()
            os.fsync(fd)
        finally:
            os.close(fd)
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        _deny()
    path = directory / "approvals.jsonl"
    payload = json.dumps({
        "schema": "operator-one-attempt-issued/v1",
        "event_id": event_id, "session_id": session_id,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "timestamp": time.time(),
    }, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    try:
        fd = os.open(
            path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            details = os.fstat(fd)
            if (
                not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
                or details.st_mode & 0o077 or details.st_nlink != 1
            ):
                _deny()
            if os.write(fd, payload) != len(payload):
                _deny()
            os.fsync(fd)
        finally:
            os.close(fd)
        dirfd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except OSError:
        # A partial or uncertain audit record is NOT evidence of approval.
        _deny()


def _issue_operator_approved(config: OperatorServiceConfig, request: dict[str, Any]) -> str:
    if set(request) != {"protocol", "event_id", "session_id", "operator_proof"}:
        _deny()
    event_id, session_id, proof = (
        request["event_id"], request["session_id"], request["operator_proof"]
    )
    if (
        request["protocol"] != "I5-G-op1-glm-v1"
        or not isinstance(event_id, str) or len(event_id) > 80
        or not isinstance(session_id, str) or len(session_id) > 128
        or not isinstance(proof, str) or len(proof) > 8192
    ):
        _deny()
    _assert_readonly_event_source(config, session_id)
    event_store = EventStore(config.event_store_dir)
    event = _rehydrate_event(event_store, session_id, event_id)
    issuer = ApprovedOneAttemptIssuer(
        key_id=config.budget_key_id,
        private_key_pem=_private_budget_key(config.budget_key_file),
        operator_verifier=load_pinned_operator_verifier(config.operator_trust_file),
    )
    signed = issuer.approve_exact_event(
        event_store=event_store, event=event, operator_proof=proof,
        workspace_root=str(config.workspace_root), session_id=session_id,
    )
    _audit_receipt(config.audit_dir, event_id=event_id, session_id=session_id, token=signed)
    return signed


def serve_authenticated_connection(config: OperatorServiceConfig, conn: socket.socket) -> None:
    """No Web token, model text or assertion can replace kernel peer identity."""
    try:
        if _peer_uid(conn) != config.expected_web_uid:
            _deny()
        request = _read_frame(conn, _REQUEST_MAX)
        signed = _issue_operator_approved(config, request)
        _send_frame(conn, {"ok": True, "positive_proof": signed})
    except (TaskBudgetDeniedError, OSError, ValueError, TypeError, KeyError, TimeoutError):
        # No inbound contents, key bytes, principal or signature in denial.
        with suppress(OSError):
            _send_frame(conn, {"ok": False, "reason": "operator_approval_denied"})


def serve_forever(config: OperatorServiceConfig) -> NoReturn:
    """Operator-started, owner-isolated daemon; never invoked by Web routes."""
    config.validate_live_socket_boundary()
    if os.path.lexists(config.socket_path):
        _deny()
    previous_umask = os.umask(0o117)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(config.socket_path))
            os.chmod(config.socket_path, 0o660)  # operator-owned, group-connect
            mounted = os.lstat(config.socket_path)
            if (
                not stat.S_ISSOCK(mounted.st_mode)
                or mounted.st_uid != os.geteuid()
                or mounted.st_gid != config.expected_web_gid
                or mounted.st_mode & 0o777 != 0o660
            ):
                _deny()
            server.listen(4)
            while True:
                conn, _ = server.accept()
                with conn:
                    serve_authenticated_connection(config, conn)
    finally:
        os.umask(previous_umask)


def request_operator_approved_budget(
    *, socket_path: str | os.PathLike[str], event_id: str,
    session_id: str, operator_proof: str,
) -> str:
    """Web-side IPC; returns only signed token, never private key material."""
    request = {
        "protocol": "I5-G-op1-glm-v1", "event_id": event_id,
        "session_id": session_id, "operator_proof": operator_proof,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3.0)
        conn.connect(os.fspath(socket_path))
        _send_frame(conn, request)
        response = _read_frame(conn, _RESPONSE_MAX)
        if set(response) != {"ok", "positive_proof"} or response["ok"] is not True:
            _deny()
        result = response["positive_proof"]
        if not isinstance(result, str) or not result.startswith("tb3."):
            _deny()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Operator-only GLM one-attempt budget signer")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--web-uid", type=int, required=True)
    parser.add_argument("--web-gid", type=int, required=True)
    parser.add_argument("--event-store", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--budget-key", type=Path, required=True)
    parser.add_argument("--budget-key-id", required=True)
    parser.add_argument("--operator-trust", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    serve_forever(OperatorServiceConfig(
        socket_path=args.socket, expected_web_uid=args.web_uid,
        event_store_dir=args.event_store, workspace_root=args.workspace,
        budget_key_file=args.budget_key, budget_key_id=args.budget_key_id,
        operator_trust_file=args.operator_trust, audit_dir=args.audit_dir,
        expected_web_gid=args.web_gid,
    ))


if __name__ == "__main__":
    main()
