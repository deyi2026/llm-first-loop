"""RED: quarantine/verify/abort should be real without pretending to cut over."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from zipfile import ZipFile

import pytest

from llm_loop import cli


@pytest.fixture()
def user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, str]:
    for key in ("LFL_HOME", "LFL_ENV_FILE", "DATA_DIR", "LFL_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / "data").mkdir()
    (home / "data" / "session.jsonl").write_bytes(b"unchanged\n")
    monkeypatch.setattr(cli, "bundle_root", lambda: tmp_path / "installed-bundle")
    monkeypatch.setattr(cli, "default_home", lambda: home)
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("bootstrap called"))
    monkeypatch.setattr(cli, "main", lambda *_args, **_kw: pytest.fail("provider called"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_args, **_kw: pytest.fail("network used"))
    wheel = tmp_path / "llm_first_loop-0.6.33-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("llm_first_loop-0.6.33.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: llm-first-loop\nVersion: 0.6.33\n")
        archive.writestr("llm_first_loop-0.6.33.dist-info/WHEEL",
                         "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
    return home, wheel, hashlib.sha256(wheel.read_bytes()).hexdigest()


def invoke(capsys: pytest.CaptureFixture[str], *tokens: str) -> tuple[int, dict]:
    code = cli.application_main(["upgrade", *tokens, "--json"])
    capture = capsys.readouterr()
    assert capture.out.strip(), capture.err
    return code, json.loads(capture.out)


def test_stage_verify_abort_preserves_active_install_and_user_data(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    rc, staged = invoke(capsys, "--stage", "--candidate", str(wheel), "--expected-sha256", digest)
    assert rc == 0 and staged["staged"] and not staged["ready_for_cutover"]
    assert staged["candidate_sha256"] == digest and staged["candidate_version"] == "0.6.33"
    assert not staged["active_version_changed"] and not staged["services_changed"]
    assert staged["source_trusted"] is False
    identifier = staged["stage_id"]
    assert len(identifier) == 24
    stage = home / "upgrade-staging" / identifier
    assert stage.is_dir() and (stage / "candidate.whl").read_bytes() == wheel.read_bytes()
    assert stage.stat().st_mode & 0o777 == 0o700
    rc, verified = invoke(capsys, "--verify-stage", "--id", identifier)
    assert rc == 0 and verified["valid"] and verified["read_only"]
    rc, aborted = invoke(capsys, "--abort", "--id", identifier)
    assert rc == 0 and aborted["aborted"]
    assert not stage.exists()
    assert (home / "data" / "session.jsonl").read_bytes() == b"unchanged\n"


def test_stage_refuses_bad_hash_and_symlink_without_creating_staging(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, _ = user_home
    rc, report = invoke(capsys, "--stage", "--candidate", str(wheel),
                        "--expected-sha256", "0" * 64)
    assert rc == 1 and report["reason"] == "candidate_hash_mismatch"
    assert not (home / "upgrade-staging").exists()
    alias = wheel.parent / "alias.whl"
    alias.symlink_to(wheel)
    rc, report = invoke(capsys, "--stage", "--candidate", str(alias),
                        "--expected-sha256", "0" * 64)
    assert rc == 1 and not (home / "upgrade-staging").exists()


def test_forged_transaction_and_foreign_sentinel_never_removed(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, _wheel, _digest = user_home
    (home / "backup").mkdir()
    (home / "backup" / "sentinel").write_bytes(b"do-not-delete")
    rc, report = invoke(capsys, "--abort", "--id", "a" * 24)
    assert rc == 1 and report["reason"] == "unknown_transaction"
    rc, report = invoke(capsys, "--commit", "--receipt", str(home / "backup" / "fake"),
                        "--confirm-cutover")
    assert rc == 1 and report["reason"] == "transaction_unverified"
    assert (home / "backup" / "sentinel").read_bytes() == b"do-not-delete"


def test_tampered_stage_cannot_be_marked_valid_or_deleted(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    rc, report = invoke(capsys, "--stage", "--candidate", str(wheel), "--expected-sha256", digest)
    assert rc == 0
    stage = home / "upgrade-staging" / report["stage_id"]
    (stage / "candidate.whl").write_bytes(b"tampered")
    assert invoke(capsys, "--verify-stage", "--id", report["stage_id"])[0] == 1
    assert invoke(capsys, "--abort", "--id", report["stage_id"])[0] == 1
    assert stage.exists() and (stage / "candidate.whl").read_bytes() == b"tampered"


def test_active_cutover_and_false_service_stop_declaration_rejected(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    rc, report = invoke(capsys, "--prepare", "--candidate", str(wheel),
                        "--expected-sha256", digest, "--confirm-services-stopped")
    assert rc == 1 and report["reason"] == "service_identity_unverified"
    assert not (home / "upgrade-staging").exists()


def test_foreign_stage_contents_are_not_deleted(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    status, report = invoke(capsys, "--stage", "--candidate", str(wheel),
                            "--expected-sha256", digest)
    assert status == 0
    stage = home / "upgrade-staging" / report["stage_id"]
    (stage / "unrelated-backup.txt").write_bytes(b"do not erase")
    assert invoke(capsys, "--abort", "--id", report["stage_id"])[0] == 1
    assert (stage / "unrelated-backup.txt").read_bytes() == b"do not erase"


def test_require_trust_never_executes_untrusted_wheel(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    rc, report = invoke(capsys, "--stage", "--candidate", str(wheel),
                        "--expected-sha256", digest, "--require-trust")
    assert rc == 1 and report["reason"] == "candidate_trust_unknown"
    assert not (home / "upgrade-staging").exists()


def test_symlink_transaction_directory_never_followed(
    user_home: tuple[Path, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    home, wheel, digest = user_home
    rc, report = invoke(capsys, "--stage", "--candidate", str(wheel),
                        "--expected-sha256", digest)
    assert rc == 0
    directory = home / "upgrade-staging" / report["stage_id"]
    directory.rename(directory.with_name("stored"))
    directory.symlink_to(directory.with_name("stored"), target_is_directory=True)
    assert invoke(capsys, "--verify-stage", "--id", report["stage_id"])[0] == 1
    assert invoke(capsys, "--abort", "--id", report["stage_id"])[0] == 1
    assert directory.with_name("stored").is_dir()


# ── DESIGN-20261107 §5.6/§5.7/§3.3.1：升级事务 journal 与 supervisor 单实例 ──


def _new_tx(tmp_path: Path, **overrides: object) -> dict:
    from llm_loop.runtime.upgrade_stage import create_transaction
    kwargs: dict[str, object] = {
        "idempotency_key": "idem-1",
        "old_version": "0.6.40",
        "candidate_version": "0.6.41",
        "wheel_sha256": "a" * 64,
        "expected_generation": 7,
        "target_generation": 8,
    }
    kwargs.update(overrides)
    return create_transaction(tmp_path, **kwargs)


def test_transaction_journal_created_with_private_permissions(tmp_path: Path) -> None:
    import json as _json
    import stat as _stat

    tx = _new_tx(tmp_path)
    tx_dir = tmp_path / "upgrade-transactions" / tx["transaction_id"]
    journal = tx_dir / "journal.json"
    assert journal.is_file()
    assert _stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert _stat.S_IMODE(tx_dir.stat().st_mode) == 0o700
    raw = _json.loads(journal.read_text(encoding="utf-8"))
    assert raw["schema"] == "lfl.upgrade.transaction/v1"
    assert raw["state"] == "observed"
    assert raw["idempotency_key"] == "idem-1"
    assert raw["expected_generation"] == 7 and raw["target_generation"] == 8
    assert raw["old_version"] == "0.6.40" and raw["candidate_version"] == "0.6.41"
    assert raw["wheel_sha256"] == "a" * 64


def test_second_active_transaction_is_refused(tmp_path: Path) -> None:
    from llm_loop.runtime.upgrade_stage import TransactionError

    _new_tx(tmp_path)
    with pytest.raises(TransactionError) as exc:
        _new_tx(tmp_path, idempotency_key="idem-2")
    assert "transaction_already_active" in str(exc.value)


def test_transaction_advance_is_expected_state_cas_and_idempotent(
    tmp_path: Path,
) -> None:
    from llm_loop.runtime.upgrade_stage import (
        TransactionError,
        advance_transaction,
        read_transaction,
    )
    tx = _new_tx(tmp_path)
    tx_id = tx["transaction_id"]
    moved = advance_transaction(
        tmp_path, tx_id, from_state="observed", to_state="candidate_resolved"
    )
    assert moved["state"] == "candidate_resolved"
    # 重复推进同一步：幂等（不报冲突，不重复记录）。
    again = advance_transaction(
        tmp_path, tx_id, from_state="candidate_resolved", to_state="candidate_resolved"
    )
    assert again["state"] == "candidate_resolved"
    # 过期期望状态 → CAS 冲突。
    with pytest.raises(TransactionError) as exc:
        advance_transaction(
            tmp_path, tx_id, from_state="observed", to_state="staged_release_built"
        )
    assert "transaction_state_conflict" in str(exc.value)
    # journal 持久且可读回。
    assert read_transaction(tmp_path, tx_id)["state"] == "candidate_resolved"


def test_transaction_terminal_states_release_the_single_slot(tmp_path: Path) -> None:
    from llm_loop.runtime.upgrade_stage import advance_transaction

    tx = _new_tx(tmp_path)
    tx_id = tx["transaction_id"]
    advance_transaction(
        tmp_path, tx_id,
        from_state="observed", to_state="aborted_before_cutover",
        failure_reason="staging_failed",
    )
    # 终态后可以开新事务。
    nxt = _new_tx(tmp_path, idempotency_key="idem-next")
    assert nxt["transaction_id"] != tx_id


def test_supervisor_lock_is_single_instance_and_conflict_is_explicit(
    tmp_path: Path,
) -> None:
    from llm_loop.runtime.upgrade_stage import SupervisorLock

    first = SupervisorLock(tmp_path)
    assert first.acquire() is True
    lock_path = tmp_path / "upgrade-transactions" / "supervisor.lock"
    assert lock_path.is_file()
    import stat as _stat

    assert _stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    second = SupervisorLock(tmp_path)
    assert second.acquire() is False  # supervisor_conflict：不改任何状态
    first.release()
    third = SupervisorLock(tmp_path)
    assert third.acquire() is True
    third.release()


def test_supervisor_handover_records_cas_and_rollback_pending_on_settle_failure(
    tmp_path: Path,
) -> None:
    from llm_loop.runtime.upgrade_stage import (
        TransactionError,
        advance_transaction,
        handover_complete_cas,
        handover_mark_new_ready,
    )
    tx = _new_tx(tmp_path)
    tx_id = tx["transaction_id"]
    advance_transaction(
        tmp_path, tx_id, from_state="observed", to_state="committed"
    )
    # 新 supervisor ready(generation=N+1) → journal 记录 handover=ready。
    handover_mark_new_ready(tmp_path, tx_id, generation=8)
    tx_now = None
    from llm_loop.runtime.upgrade_stage import read_transaction

    tx_now = read_transaction(tmp_path, tx_id)
    assert tx_now["handover"]["new_ready_generation"] == 8
    assert tx_now["handover"]["phase"] == "ready"
    # CAS 成功路径：expected_generation 匹配 → 交接完成记录权威实例信息。
    done = handover_complete_cas(
        tmp_path, tx_id, expected_generation=8, authority_pid=4242,
        authority_start_time="2026-11-07T16:30:00+08:00",
    )
    assert done["handover"]["phase"] == "settled"
    assert done["handover"]["authority_pid"] == 4242
    # CAS 失败路径（期望代不匹配）：置 rollback_pending，不标 settled。
    tx2 = _new_tx(tmp_path.parent / "tx2", idempotency_key="h2")
    advance_transaction(
        tmp_path.parent / "tx2", tx2["transaction_id"],
        from_state="observed", to_state="committed",
    )
    handover_mark_new_ready(tmp_path.parent / "tx2", tx2["transaction_id"], generation=9)
    with pytest.raises(TransactionError) as exc:
        handover_complete_cas(
            tmp_path.parent / "tx2", tx2["transaction_id"],
            expected_generation=42, authority_pid=1, authority_start_time="x",
        )
    assert "handover_cas_conflict" in str(exc.value)
    from llm_loop.runtime.upgrade_stage import read_transaction as _rt

    final = _rt(tmp_path.parent / "tx2", tx2["transaction_id"])
    assert final["handover"]["phase"] == "rollback_pending"


# ── P2-2（审查 b7691f4e）：journal 写入必须真原子（tmp+fsync+rename）──


def test_journal_write_is_atomic_via_rename_and_failure_keeps_old_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """原子性契约：①成功写入换 inode（rename 语义）；②中途失败旧字节不丢。"""
    import os as _os

    from llm_loop.runtime.upgrade_stage import (
        TransactionError,
        _atomic_write_journal,
        advance_transaction,
        read_transaction,
    )

    tx = _new_tx(tmp_path)
    tx_id = tx["transaction_id"]
    journal = tmp_path / "upgrade-transactions" / tx_id / "journal.json"
    before_inode = journal.stat().st_ino

    # ① 原地 truncate+write 不会换 inode；tmp+rename 会。
    advance_transaction(
        tmp_path, tx_id, from_state="observed", to_state="candidate_resolved"
    )
    assert journal.stat().st_ino != before_inode, (
        "journal write must replace the file (rename), not truncate in place"
    )

    # ② 写入中途失败（fsync 注入 OSError）：旧 journal 字节必须完整保留。
    latest = read_transaction(tmp_path, tx_id)
    keep_bytes = journal.read_bytes()
    real_fsync = _os.fsync

    def flaky_fsync(fd: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(_os, "fsync", flaky_fsync)
    with pytest.raises(TransactionError):
        _atomic_write_journal(journal, dict(latest, state="staged_release_built"))
    monkeypatch.setattr(_os, "fsync", real_fsync)
    assert journal.read_bytes() == keep_bytes, (
        "failed journal write must leave the previous journal intact"
    )
    # 不残留 tmp 半成品。
    leftovers = [p.name for p in journal.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], leftovers
    # 失败后 journal 仍可读、状态未推进。
    after = read_transaction(tmp_path, tx_id)
    assert after["state"] == "candidate_resolved"
