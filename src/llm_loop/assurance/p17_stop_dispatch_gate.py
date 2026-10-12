"""P1.7 cooperative STOP-vs-fake-dispatch linearization experiment.

This module is deliberately isolated from production ToolRegistry/Provider.
It can only call the on-disk FakeRemote, never a real network sender.
Every cooperating STOP and dispatch uses one host-side fcntl lock.

This does NOT make an unmodified production Stop route cooperative, guarantee
low-latency cancellation during a blocked send, or certify a real outbound
Provider transport. An uncooperative caller can bypass this experiment.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from llm_loop.assurance.offline_effects import FakeRemote, OfflineEffectJournal
from llm_loop.assurance.p16_host_broker import (
    BrokerDeniedError,
    OfflineHostReviewBroker,
    OfflineReviewRequest,
    ReplayForbiddenError,
)
from llm_loop.assurance.task_control_store import IntentReceipt


@dataclass(frozen=True)
class FakeEffectResult:
    attempt_id: str
    operation_id: str
    status: str
    may_release: bool = False
    may_dispatch_production_effect: bool = False


class OfflineStopDispatchGate:
    def __init__(
        self, *, root: Path, broker: OfflineHostReviewBroker,
        remote: FakeRemote,
    ) -> None:
        if (
            root.name != "assurance-p17-root"
            or root.is_symlink()
            or type(remote) is not FakeRemote
        ):
            raise BrokerDeniedError("P1.7 test-only fake transport required")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = root
        self.broker = broker
        self.remote = remote
        self.journal = OfflineEffectJournal(root / "fake_effect_journal")
        self.lock_path = root / "fake_outbound_control.lock"
        if self.lock_path.is_symlink():
            raise BrokerDeniedError("outbound gate symlink denied")
        # A dedicated experiment journal enforces uniqueness by physical
        # operation as well as attempt ID: changing the attempt_id cannot
        # evade the no-physical-retry constraint.
        with sqlite3.connect(self.journal.path) as db:
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS p17_unique_operation_id "
                "ON attempts(operation_id)"
            )

    @contextmanager
    def _linearization_lock(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.lock_path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BrokerDeniedError("invalid outbound gate file identity")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def accept_stop(
        self, *,
        task_id: str, owner: str, expected_revision: int,
        intent_id: str, payload_sha256: str,
    ) -> IntentReceipt:
        """Cooperative STOP linearizes after any already-admitted fake send.

        Ack may wait for the active fake dispatch; real-time production STOP
        must use a separately audited interruptible physical transport.
        """
        with self._linearization_lock():
            return self.broker.control.append_intent_cas(
                task_id, owner, expected_revision, intent_id,
                "STOP", payload_sha256,
            )

    def _operation_recorded(self, operation_id: str) -> bool:
        with sqlite3.connect(self.journal.path, timeout=5) as db:
            row = db.execute(
                "SELECT 1 FROM attempts WHERE operation_id=? LIMIT 1",
                (operation_id,),
            ).fetchone()
        return row is not None

    def send_synthetic_once(
        self, request: OfflineReviewRequest,
        *,
        attempt_id: str, operation_id: str, action_sha256: str,
        after_opened_for_test: Callable[[], None] | None = None,
        after_remote_for_test: Callable[[], None] | None = None,
    ) -> FakeEffectResult:
        with self._linearization_lock():
            if not self.broker._guard(request):
                raise BrokerDeniedError("STOP/Fleet/Task binding denied fake dispatch")
            if self._operation_recorded(operation_id):
                raise ReplayForbiddenError("operation already physically attempted")
            # A genuine process kill after this durable write means UNKNOWN,
            # even if FakeRemote has not seen an application yet.
            self.journal.start(attempt_id, operation_id, action_sha256)
            if after_opened_for_test:
                after_opened_for_test()
            try:
                self.remote.dispatch(operation_id, action_sha256)
                if after_remote_for_test:
                    after_remote_for_test()
            except Exception:  # noqa: BLE001 - never infer no external effect
                return FakeEffectResult(attempt_id, operation_id, "OUTCOME_UNKNOWN")
            # This fake endpoint alone provides an exact observe() contract.
            state = self.journal.reconcile(attempt_id, self.remote.observe)
            return FakeEffectResult(attempt_id, operation_id, state)

    def recover_without_replay(self, attempt_id: str) -> FakeEffectResult:
        """Observation only. May never call dispatch or start a new attempt."""
        with self._linearization_lock():
            old = self.journal.read(attempt_id)
            state = self.journal.reconcile(attempt_id, self.remote.observe)
            return FakeEffectResult(old.attempt_id, old.operation_id, state)
