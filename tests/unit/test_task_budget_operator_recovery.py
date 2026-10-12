"""I5-H: persistent one-event issuance fence and read-only ACL denial."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from llm_loop.resources.task_budget_operator_service import (
    _assert_readonly_event_source,
    _audit_receipt,
    _issue_operator_approved,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from tests.unit.test_task_budget_operator_service import _fixture


def _marker(directory: Path, event_id: str, session_id: str) -> Path:
    fingerprint = hashlib.sha256((session_id + "\0" + event_id).encode()).hexdigest()
    return directory / f"issued-{fingerprint}.json"


def test_same_human_event_has_one_persistent_signature_fence(tmp_path: Path, monkeypatch) -> None:
    config, event, request, _trust, _save, _public = _fixture(tmp_path)
    # Test-only simulated cross-UID ACL; production requires a real kernel
    # read/no-write check in the operating issuer process.
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_service._assert_readonly_event_source",
        lambda _config, _session: None,
    )
    first = _issue_operator_approved(config, request)
    with pytest.raises(TaskBudgetDeniedError):
        _issue_operator_approved(config, request)
    assert first.startswith("tb3.")
    marker = _marker(config.audit_dir, event.event_id, event.session_id)
    assert json.loads(marker.read_text())["token_sha256"] == hashlib.sha256(first.encode()).hexdigest()
    assert len((config.audit_dir / "approvals.jsonl").read_text().splitlines()) == 1


def test_simultaneous_issuer_threads_cannot_mint_two_tokens(tmp_path: Path, monkeypatch) -> None:
    config, _event, request, _trust, _save, _public = _fixture(tmp_path)
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_service._assert_readonly_event_source",
        lambda _config, _session: None,
    )
    barrier = threading.Barrier(2)

    def try_issue(_: int) -> str:
        barrier.wait(timeout=2.0)
        try:
            _issue_operator_approved(config, request)
            return "approved"
        except TaskBudgetDeniedError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_issue, range(2)))
    assert sorted(results) == ["approved", "denied"]


def test_partial_after_create_stays_blocked_after_restart(tmp_path: Path) -> None:
    config, event, _request, _trust, _save, _public = _fixture(tmp_path)
    real_fsync = os.fsync
    with mock.patch(
        "llm_loop.resources.task_budget_operator_service.os.fsync",
        side_effect=OSError("injected after create"),
    ), pytest.raises(TaskBudgetDeniedError):
        _audit_receipt(config.audit_dir, event_id=event.event_id,
                       session_id=event.session_id, token="not-returned")
    assert os.fsync is real_fsync
    # Whether bytes were physically persisted is UNKNOWN. Never delete or
    # reuse this identity just because the audit row is absent/corrupt.
    assert _marker(config.audit_dir, event.event_id, event.session_id).exists()
    with pytest.raises(TaskBudgetDeniedError):
        _audit_receipt(config.audit_dir, event_id=event.event_id,
                       session_id=event.session_id, token="second-token")


def test_event_store_readonly_gate_rejects_fake_separate_uid(tmp_path: Path) -> None:
    config, event, _request, _trust, _save, _public = _fixture(tmp_path)
    # Fixture file owner is this test UID, not the synthetic Web UID, so
    # the actual service must refuse it despite being able to read bytes.
    with pytest.raises(TaskBudgetDeniedError):
        _assert_readonly_event_source(config, event.session_id)


def test_one_shot_marker_symlink_denies_without_writing_target(tmp_path: Path) -> None:
    config, event, _request, _trust, _save, _public = _fixture(tmp_path)
    other = tmp_path / "outside.json"
    other.write_text("original")
    _marker(config.audit_dir, event.event_id, event.session_id).symlink_to(other)
    with pytest.raises(TaskBudgetDeniedError):
        _audit_receipt(config.audit_dir, event_id=event.event_id,
                       session_id=event.session_id, token="non-authorized")
    assert other.read_text() == "original"


def test_daemon_start_requires_real_uid_group_and_event_acl(tmp_path: Path) -> None:
    config, _event, _request, _trust, _save, _public = _fixture(tmp_path)
    # Missing group qualification is an unconditional startup STOP.
    with pytest.raises(TaskBudgetDeniedError):
        config.validate_live_socket_boundary()
    # A same-UID fixture cannot masquerade as a different Web file owner.
    socket_parent = tmp_path / "socket"
    socket_parent.mkdir()
    socket_parent.chmod(0o2750)
    configured = replace(
        config, socket_path=socket_parent / "issuer.sock",
        expected_web_gid=os.getegid(),
    )
    with pytest.raises(TaskBudgetDeniedError):
        configured.validate_live_socket_boundary()
    assert not (socket_parent / "issuer.sock").exists()


def test_private_issuer_directory_must_not_be_group_writable(tmp_path: Path) -> None:
    config, _event, _request, _trust, _save, _public = _fixture(tmp_path)
    config.audit_dir.chmod(0o777)
    with pytest.raises(TaskBudgetDeniedError):
        config.validate_boundary()
