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
