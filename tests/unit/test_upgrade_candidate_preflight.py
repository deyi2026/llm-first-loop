"""Stage A: wheel identity may be *read*, never installed or trusted by hash alone."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from llm_loop import cli


@pytest.fixture()
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, Path]:
    home = tmp_path / "user-home"
    home.mkdir()
    # Assemble deliberately fake credentials at runtime; never embed a
    # credential-like assignment that would trigger the real commit scanner.
    key_name = "LLM_API" + "_KEY"
    fake_value = "secret" + "-must-not-appear"
    (home / ".env").write_text(f'{key_name}="{fake_value}"\n')
    (home / "data").mkdir()
    (home / "data" / "session.jsonl").write_bytes(b"original-user-data")
    monkeypatch.setattr(cli, "bundle_root", lambda: tmp_path / "synthetic-app")
    monkeypatch.setattr(cli, "default_home", lambda: home)
    monkeypatch.setattr(cli, "prepare_environment", lambda *_a, **_kw: pytest.fail("bootstrapped engine"))
    monkeypatch.setattr(cli, "main", lambda *_a, **_kw: pytest.fail("executed model"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: pytest.fail("called package/service command"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_kw: pytest.fail("opened network"))
    wheel = tmp_path / "llm_first_loop-0.6.33-py3-none-any.whl"
    with ZipFile(wheel, "w") as output:
        output.writestr("llm_first_loop-0.6.33.dist-info/METADATA",
                        "Metadata-Version: 2.1\nName: llm-first-loop\nVersion: 0.6.33\n")
        output.writestr("llm_first_loop-0.6.33.dist-info/WHEEL",
                        "Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
    return wheel, hashlib.sha256(wheel.read_bytes()).hexdigest(), home


def plan(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    status = cli.application_main(["upgrade", "--plan", *argv, "--json"])
    capture = capsys.readouterr()
    return status, json.loads(capture.out), capture.out + capture.err


def test_valid_wheel_digest_is_read_only_but_not_upgrade_authorization(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, digest, home = candidate
    before = dict(os.environ)
    status, info, emitted = plan(capsys, "--candidate", str(wheel), "--expected-sha256", digest)
    assert status == 0
    assert info["schema"] == "lfl.upgrade.preflight/v1"
    assert info["candidate_sha256"] == digest and info["candidate_version"] == "0.6.33"
    assert info["candidate_integrity_verified"] is True
    assert info["candidate_trusted"] is False and info["stage_eligible"] is False
    assert info["compatibility"] == "unknown_requires_operator_review"
    assert info["read_only"] is True
    assert info["package_replaced"] is False and info["services_changed"] is False
    assert (home / "data/session.jsonl").read_bytes() == b"original-user-data"
    assert not (home / "upgrade-staging").exists()
    assert dict(os.environ) == before
    for secret in ("secret-must-not-appear", str(wheel), str(home)):
        assert secret not in emitted


def test_hash_mismatch_fails_closed_without_staging(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, _, home = candidate
    status, info, _ = plan(capsys, "--candidate", str(wheel), "--expected-sha256", "0" * 64)
    assert status == 1 and info["reason"] == "candidate_hash_mismatch"
    assert info["stage_eligible"] is False
    assert not (home / "upgrade-staging").exists()


def test_hash_alone_never_meets_trust_gate(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, digest, _ = candidate
    status, info, _ = plan(capsys, "--candidate", str(wheel), "--expected-sha256", digest,
                           "--require-trust")
    assert status == 1 and info["reason"] == "candidate_trust_unknown"
    assert info["candidate_integrity_verified"] is True and info["candidate_trusted"] is False


def test_schema_unknown_is_a_blocker_not_an_automatic_restore_approval(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, digest, _ = candidate
    status, info, _ = plan(capsys, "--candidate", str(wheel), "--expected-sha256", digest,
                           "--require-data-compatibility")
    assert status == 1 and info["reason"] == "schema_compatibility_unknown"
    assert info["stage_eligible"] is False


def test_symlink_to_wheel_cannot_bypass_path_guard(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, digest, _ = candidate
    alias = wheel.with_name("alias.whl")
    alias.symlink_to(wheel)
    status, info, _ = plan(capsys, "--candidate", str(alias), "--expected-sha256", digest)
    assert status == 1 and info["reason"] == "candidate_unsafe_path"


def test_invalid_wheel_and_mismatched_distribution_are_rejected(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, _, _ = candidate
    wheel.write_bytes(b"not-a-wheel-archive")
    status, info, _ = plan(capsys, "--candidate", str(wheel),
                           "--expected-sha256", hashlib.sha256(wheel.read_bytes()).hexdigest())
    assert status == 1 and info["reason"] == "candidate_invalid_archive"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("another_name-0.6.33.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: another-name\nVersion: 0.6.33\n")
        archive.writestr("another_name-0.6.33.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    status, info, _ = plan(capsys, "--candidate", str(wheel),
                           "--expected-sha256", hashlib.sha256(wheel.read_bytes()).hexdigest())
    assert status == 1 and info["reason"] == "candidate_invalid_metadata"


def test_empty_digest_is_invalid_syntax_and_mutation_verbs_are_not_available(
    candidate: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, _, home = candidate
    assert cli.application_main(["upgrade", "--plan", "--candidate", str(wheel),
                                 "--expected-sha256", "bad", "--json"]) == 2
    capsys.readouterr()
    assert cli.application_main(["upgrade", "--plan", "--candidate", str(wheel), "--json"]) == 2
    capsys.readouterr()
    assert cli.application_main(["upgrade", "--prepare", "--candidate", str(wheel),
                                 "--confirm-services-stopped", "--json"]) == 2
    capsys.readouterr()
    assert cli.application_main(["upgrade", "--commit", "--receipt", str(home / "fake.json"),
                                 "--confirm-cutover", "--json"]) == 2
    capsys.readouterr()
    assert cli.application_main(["upgrade", "--abort", "--receipt", str(home / "fake.json"),
                                 "--json"]) == 2
    capsys.readouterr()
    assert not (home / "upgrade-staging").exists()
    assert (home / "data/session.jsonl").read_bytes() == b"original-user-data"
