"""I5-H human review and unprivileged mailbox, not actual multi-UID qualification."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from Crypto.PublicKey import ECC

from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import _event_hash
from llm_loop.resources.task_budget_operator_mailbox import (
    OperatorReviewConfig,
    TrustedHumanApprovalBridge,
    approve_human_event,
    read_approved_mailbox,
)
from llm_loop.resources.task_budget_operator_proof import OperatorApprovalVerifier
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from tests import env_channel


def _fixture(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    event = store.append_durable_human_message(
        "web-session", build_message_payload(
            index=0, role="user", source="user", content="please review exact event",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    key = ECC.generate(curve="Ed25519")
    priv = key.export_key(format="PEM")
    pub = key.public_key().export_key(format="PEM")
    secret = tmp_path / "operator-private.pem"
    secret.write_bytes(priv.encode() if isinstance(priv, str) else priv)
    secret.chmod(0o600)
    mailbox = tmp_path / "approval-mailbox"
    mailbox.mkdir()
    mailbox.chmod(0o2750)
    config = OperatorReviewConfig(
        event_store_dir=tmp_path / "events", workspace_root=tmp_path,
        expected_web_uid=os.geteuid() + 1,
        expected_issuer_uid=os.geteuid() + 2,
        web_group_gid=os.getegid(), mailbox_dir=mailbox,
        private_key_file=secret, operator_key_id="operator-a",
        operator_id="human-a",
    )
    verifier = OperatorApprovalVerifier(
        trusted_keys={"operator-a": pub.encode() if isinstance(pub, str) else pub},
        authorized_operators={"human-a": "operator-a"},
    )
    return config, event, verifier


def _tty(monkeypatch) -> None:
    # TTY + cross-UID EventStore ACL are simulated. Production requires
    # real separately owned accounts and independent human authentication.
    stream = SimpleNamespace(isatty=lambda: True, write=lambda _: None,
                             flush=lambda: None)
    monkeypatch.setattr(sys, "stdin", stream)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox.assert_readonly_web_event_source",
        lambda **_: None,
    )


def _review(config, event, monkeypatch):
    _tty(monkeypatch)
    challenge = f"APPROVE {event.event_id} {_event_hash(event)[:12]}"
    return approve_human_event(
        config, session_id=event.session_id, event_id=event.event_id,
        prompt=lambda _text: challenge,
    )


@pytest.mark.skipif(
    env_channel.operator_mailbox_absent(),
    reason="环境受限：本通道 tmp 根目录 gid=wheel 且 SGID 不可设置，合格 operator "
           "mailbox ACL 前置不可达成（operator_human_review_or_mailbox_not_qualified）【RED-12】",
)
def test_exact_human_challenge_durable_one_shot_and_valid_op1(tmp_path: Path, monkeypatch) -> None:
    config, event, verifier = _fixture(tmp_path)
    approval_path = _review(config, event, monkeypatch)
    row = json.loads(approval_path.read_text())
    assert approval_path.stat().st_mode & 0o777 == 0o640
    assert row["event_sha256"] == _event_hash(event)
    assert verifier.authenticate(
        row["operator_proof"], event_id=event.event_id, event_seq=event.seq,
        event_sha256=_event_hash(event), session_id=event.session_id,
        workspace_scope=exact_workspace_scope(str(config.workspace_root)),
    ) == "human-a"
    with pytest.raises(TaskBudgetDeniedError):
        _review(config, event, monkeypatch)


def test_refused_challenge_has_no_mailbox_side_effect(tmp_path: Path, monkeypatch) -> None:
    config, event, _ = _fixture(tmp_path)
    _tty(monkeypatch)
    with pytest.raises(TaskBudgetDeniedError):
        approve_human_event(config, session_id=event.session_id,
                            event_id=event.event_id, prompt=lambda _: "yes")
    assert list(config.mailbox_dir.glob("*.json")) == []


def test_not_tty_never_approves(tmp_path: Path, monkeypatch) -> None:
    config, event, _ = _fixture(tmp_path)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(TaskBudgetDeniedError):
        approve_human_event(config, session_id=event.session_id,
                            event_id=event.event_id)


@pytest.mark.skipif(
    env_channel.operator_mailbox_absent(),
    reason="环境受限：同 RED-12——mailbox ACL 资格前置不可达成【RED-13】",
)
def test_actual_same_uid_denied_as_independent_web(tmp_path: Path, monkeypatch) -> None:
    config, event, _ = _fixture(tmp_path)
    _review(config, event, monkeypatch)
    with pytest.raises(TaskBudgetDeniedError):
        read_approved_mailbox(
            directory=config.mailbox_dir, event=event,
            session_id=event.session_id, operator_uid=os.geteuid(),
            web_group_gid=os.getegid(),
        )


def test_operator_role_must_differ_from_web_and_issuer(tmp_path: Path) -> None:
    config, event, _ = _fixture(tmp_path)
    for variant in (
        replace(config, expected_web_uid=os.geteuid()),
        replace(config, expected_issuer_uid=os.geteuid()),
        replace(config, expected_issuer_uid=config.expected_web_uid),
    ):
        with pytest.raises(TaskBudgetDeniedError):
            approve_human_event(variant, session_id=event.session_id,
                                event_id=event.event_id)


def test_mailbox_permissions_must_exclude_world_and_group_write(
    tmp_path: Path, monkeypatch,
) -> None:
    config, event, _ = _fixture(tmp_path)
    for mode in (0o2752, 0o2770, 0o0750):
        config.mailbox_dir.chmod(mode)
        with pytest.raises(TaskBudgetDeniedError):
            _review(config, event, monkeypatch)


def test_changed_event_after_human_review_denied(tmp_path: Path, monkeypatch) -> None:
    from llm_loop.resources import task_budget_operator_mailbox as module

    config, event, _ = _fixture(tmp_path)
    _tty(monkeypatch)
    original = module._rehydrate_event
    calls = []

    def altered(*args):
        calls.append(1)
        result = original(*args)
        return replace(result, seq=result.seq + 1) if len(calls) > 1 else result

    monkeypatch.setattr(module, "_rehydrate_event", altered)
    challenge = f"APPROVE {event.event_id} {_event_hash(event)[:12]}"
    with pytest.raises(TaskBudgetDeniedError):
        approve_human_event(config, session_id=event.session_id,
                            event_id=event.event_id, prompt=lambda _: challenge)
    assert list(config.mailbox_dir.glob("*.json")) == []


@pytest.mark.skipif(
    env_channel.operator_mailbox_absent(),
    reason="环境受限：同 RED-12——mailbox ACL 资格前置不可达成【RED-14】",
)
def test_mailbox_fsync_uncertainty_cannot_auto_retry(tmp_path: Path, monkeypatch) -> None:
    config, event, _ = _fixture(tmp_path)
    _tty(monkeypatch)
    challenge = f"APPROVE {event.event_id} {_event_hash(event)[:12]}"
    with monkeypatch.context() as patch:
        patch.setattr(
            "llm_loop.resources.task_budget_operator_mailbox.os.fsync",
            mock.Mock(side_effect=OSError("disk failure")),
        )
        with pytest.raises(TaskBudgetDeniedError):
            approve_human_event(config, session_id=event.session_id,
                                event_id=event.event_id, prompt=lambda _: challenge)
    assert len(list(config.mailbox_dir.glob("approved-*.json"))) == 1
    with pytest.raises(TaskBudgetDeniedError):
        approve_human_event(config, session_id=event.session_id,
                            event_id=event.event_id, prompt=lambda _: challenge)


def test_bridge_cancelled_before_operator_rpc(tmp_path: Path, monkeypatch) -> None:
    config, event, verifier = _fixture(tmp_path)
    bridge = TrustedHumanApprovalBridge(
        mailbox_dir=config.mailbox_dir, operator_uid=os.geteuid() + 1,
        web_uid=os.geteuid(), web_group_gid=os.getegid(),
        workspace_root=tmp_path, issuer_socket=tmp_path / "issuer.sock",
        operator_verifier=verifier, is_cancelled=lambda: True,
    )
    with mock.patch(
        "llm_loop.resources.task_budget_operator_mailbox.request_operator_approved_budget",
    ) as outbound, pytest.raises(TaskBudgetDeniedError):
        bridge.issue_for_event(event)
    outbound.assert_not_called()


def test_bridge_missing_mailbox_only_waits_bounded_time(tmp_path: Path, monkeypatch) -> None:
    config, event, verifier = _fixture(tmp_path)
    # The actual cross-UID mailbox owner cannot exist under one CI account;
    # tests therefore mock only the directory ACL, not the Run safety gate.
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox._check_mailbox_directory",
        lambda *_args, **_kw: None,
    )
    bridge = TrustedHumanApprovalBridge(
        mailbox_dir=config.mailbox_dir, operator_uid=os.geteuid() + 1,
        web_uid=os.geteuid(), web_group_gid=os.getegid(),
        workspace_root=tmp_path, issuer_socket=tmp_path / "issuer.sock",
        operator_verifier=verifier, is_cancelled=lambda: False,
        max_wait_seconds=0.02,
    )
    with pytest.raises(TaskBudgetDeniedError):
        bridge.issue_for_event(event)


@pytest.mark.skipif(
    env_channel.operator_mailbox_absent(),
    reason="环境受限：同 RED-12——mailbox ACL 资格前置不可达成【RED-15】",
)
def test_bridge_valid_signed_op1_sends_only_bound_event_to_service(
    tmp_path: Path, monkeypatch,
) -> None:
    config, event, verifier = _fixture(tmp_path)
    approved_path = _review(config, event, monkeypatch)
    proof = json.loads(approved_path.read_text())["operator_proof"]
    # Simulates ONLY an OS-level cross-UID mailbox ACL already independently
    # proven on target host. Cryptographic event binding is verified for real.
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox._check_mailbox_directory",
        lambda *_args, **_kw: None,
    )
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox.read_approved_mailbox",
        lambda **_kwargs: proof,
    )
    bridge = TrustedHumanApprovalBridge(
        mailbox_dir=config.mailbox_dir, operator_uid=os.geteuid() + 1,
        web_uid=os.geteuid(), web_group_gid=os.getegid(),
        workspace_root=tmp_path, issuer_socket=tmp_path / "issuer.sock",
        operator_verifier=verifier, is_cancelled=lambda: False,
    )
    with mock.patch(
        "llm_loop.resources.task_budget_operator_mailbox.request_operator_approved_budget",
        return_value="tb3.test-only-control-receipt",
    ) as outgoing:
        assert bridge.issue_for_event(event) == "tb3.test-only-control-receipt"
    outgoing.assert_called_once_with(
        socket_path=tmp_path / "issuer.sock", event_id=event.event_id,
        session_id=event.session_id, operator_proof=proof,
    )


def test_bridge_fake_op1_cannot_issue_without_rpc(tmp_path: Path, monkeypatch) -> None:
    config, event, verifier = _fixture(tmp_path)
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox._check_mailbox_directory",
        lambda *_args, **_kw: None,
    )
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_mailbox.read_approved_mailbox",
        lambda **_kwargs: "browser-auth-cookie",
    )
    bridge = TrustedHumanApprovalBridge(
        mailbox_dir=config.mailbox_dir, operator_uid=os.geteuid() + 1,
        web_uid=os.geteuid(), web_group_gid=os.getegid(),
        workspace_root=tmp_path, issuer_socket=tmp_path / "issuer.sock",
        operator_verifier=verifier, is_cancelled=lambda: False,
    )
    with mock.patch(
        "llm_loop.resources.task_budget_operator_mailbox.request_operator_approved_budget",
    ) as outgoing, pytest.raises(TaskBudgetDeniedError):
        bridge.issue_for_event(event)
    outgoing.assert_not_called()
