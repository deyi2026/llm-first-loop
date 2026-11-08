"""P1 install upgrade/backup/rollback safety contract: Stage-A RED to GREEN."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop import cli
from llm_loop.runtime import install_recovery


@pytest.fixture()
def installed_clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key in (
        "LFL_HOME", "LFL_ENV_FILE", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        "DATA_DIR", "LFL_DATA_DIR", "EXPERIENCES_DIR", "METHODS_DIR",
        "LFL_RUNTIME_ROOT", "LFL_WORKSPACE_ROOT", "SKILLS_DIR", "DOCS_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "read-only-bundle"
    bundle.mkdir()
    monkeypatch.setattr(cli, "bundle_root", lambda: bundle)
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path / "application-home")
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("upgrade/backup called mutating bootstrap"))
    monkeypatch.setattr(cli, "main", lambda *_a, **_kw: pytest.fail("upgrade/backup started Engine"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_kw: pytest.fail("upgrade/backup used network"))
    return tmp_path


def test_upgrade_plan_json_is_offline_and_no_side_effects(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before_env = dict(os.environ)
    result = cli.application_main(["upgrade", "--plan", "--json"])
    out = capsys.readouterr()
    assert result == 0
    report = json.loads(out.out)
    assert report["schema"] == "lfl.upgrade.plan/v1"
    assert report["read_only"] is True
    assert report["package_replaced"] is False
    assert report["services_changed"] is False
    assert "compatibility" in report
    assert dict(os.environ) == before_env
    assert not (installed_clean / "application-home").exists()


def test_backup_plan_reports_coverage_not_full_and_redacts_sources(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = installed_clean / "external-experiences"
    monkeypatch.setenv("EXPERIENCES_DIR", str(outside))
    monkeypatch.setenv("LLM_API_KEY", "invisible-test-secret")
    before = dict(os.environ)
    result = cli.application_main(["backup", "--plan", "--json"])
    out = capsys.readouterr()
    assert result == 0
    report = json.loads(out.out)
    assert report["schema"] == "lfl.backup.plan/v1"
    assert report["read_only"] is True and report["write_performed"] is False
    assert report["coverage"] == "selected_roots"
    assert {"config", "data", "experiences", "methods"}.issubset(set(report["sources"]))
    for value in (str(installed_clean), str(outside), "invisible-test-secret"):
        assert value not in out.out + out.err
    assert dict(os.environ) == before
    assert not (installed_clean / "application-home").exists()


def test_backup_requires_explicit_cold_services_confirmation(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = installed_clean / "backups" / "first"
    assert cli.application_main(["backup", "--to", str(target)]) == 2
    out = capsys.readouterr()
    assert "--confirm-services-stopped" in out.out + out.err
    assert not target.parent.exists()


def test_backup_existing_destination_is_never_overwritten(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = installed_clean / "existing-backup"
    target.mkdir()
    (target / "sentinel").write_bytes(b"operator-file-unchanged\n")
    assert cli.application_main([
        "backup", "--to", str(target), "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert (target / "sentinel").read_bytes() == b"operator-file-unchanged\n"


def test_backup_symlink_destination_is_never_followed(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = installed_clean / "existing-data"
    outside.mkdir()
    dest = installed_clean / "backup-alias"
    dest.symlink_to(outside, target_is_directory=True)
    assert cli.application_main([
        "backup", "--to", str(dest), "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert dest.is_symlink() and list(outside.iterdir()) == []


def test_snapshot_verify_is_read_only_even_for_missing_snapshot(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = installed_clean / "snapshot-missing"
    assert cli.application_main([
        "backup", "verify", "--from", str(missing), "--json",
    ]) == 1
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["schema"] == "lfl.backup.verify/v1"
    assert report["valid"] is False
    assert report["read_only"] is True
    assert not missing.exists()


def test_rollback_refuses_mutation_without_cold_confirmation(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = installed_clean / "recovered"
    assert cli.application_main([
        "rollback", "--from", str(installed_clean / "snapshot"), "--into", str(target),
    ]) == 2
    out = capsys.readouterr()
    assert "--confirm-services-stopped" in out.out + out.err
    assert not target.exists()


def test_rollback_rejects_preexisting_target_without_touching_user_data(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = installed_clean / "existing-recovery-target"
    target.mkdir()
    (target / "sentinel").write_bytes(b"must-remain\n")
    assert cli.application_main([
        "rollback", "--from", str(installed_clean / "backup"), "--into", str(target),
        "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert (target / "sentinel").read_bytes() == b"must-remain\n"


def _cold_state(home: Path, *, secret: str = "dummy-secret-cold-test") -> dict[str, Path]:
    home.mkdir(mode=0o700)
    (home / ".env").write_bytes((
        'LLM_API_KEY="' + secret + '"\n'
        'LLM_BASE_URL="https://example.invalid/v1"\n'
    ).encode("utf-8"))
    session = home / "data" / "sessions"
    session.mkdir(parents=True)
    (session / "session.jsonl").write_bytes(b'{"id":"123", "completed":true}\n')
    (session / "empty-dir").mkdir()
    plugins = home / "data" / "extensions" / "instances" / "id" / "data"
    plugins.mkdir(parents=True)
    (plugins / "plugin.state").write_bytes(b"plugin-durable-state\n")
    exp = home / "experiences"
    exp.mkdir()
    (exp / "verified.jsonl").write_bytes(b"experience-one\n")
    methods = home / "data" / "methods"
    methods.mkdir()
    (methods / "active.jsonl").write_bytes(b"method-one\n")
    return {"config": home / ".env", "session": session / "session.jsonl",
            "plugin": plugins / "plugin.state", "experience": exp / "verified.jsonl",
            "method": methods / "active.jsonl"}


def test_cold_backup_verify_and_isolated_rollback_roundtrip(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _cold_state(installed_clean / "application-home", secret="dummy-a#key")
    snapshot = installed_clean / "private-backup"
    assert cli.application_main([
        "backup", "--to", str(snapshot), "--confirm-services-stopped", "--json",
    ]) == 0
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["schema"] == "lfl.backup.create/v1" and receipt["created"] is True
    assert receipt["coverage"] == "selected_roots"
    assert receipt["services_stopped"] == "operator_attested_not_verified"
    assert "dummy-a#key" not in output.out + output.err
    assert str(installed_clean) not in output.out + output.err
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    assert stat.S_IMODE((snapshot / "manifest.json").stat().st_mode) == 0o600
    for role in ("config", "data", "experiences"):
        assert (snapshot / "payload" / role).is_dir()
    assert not (snapshot / "payload" / "methods").exists()
    assert (snapshot / "payload" / "config" / "value").read_bytes() == state["config"].read_bytes()
    assert (snapshot / "payload" / "data" / "extensions" / "instances" / "id" / "data" / "plugin.state").read_bytes() == state["plugin"].read_bytes()
    assert (snapshot / "payload" / "data" / "sessions" / "empty-dir").is_dir()
    assert (snapshot / "payload" / "experiences" / "verified.jsonl").read_bytes() == state["experience"].read_bytes()
    assert (snapshot / "payload" / "data" / "methods" / "active.jsonl").read_bytes() == state["method"].read_bytes()
    capsys.readouterr()
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] is True and verified["read_only"] is True
    assert verified["manifest_sha256"] == receipt["manifest_sha256"]
    recovered = installed_clean / "cold-recovered"
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(recovered),
        "--confirm-services-stopped", "--json",
    ]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["restored"] is True and info["production_cutover"] is False
    assert info["code_downgrade"] is False
    assert (recovered / "payload" / "config" / "value").read_bytes() == state["config"].read_bytes()
    assert stat.S_IMODE((recovered / "payload" / "config" / "value").stat().st_mode) == 0o600
    assert cli.application_main(["backup", "verify", "--from", str(recovered), "--json"]) == 0
    capsys.readouterr()
    assert (state["session"]).read_bytes() == b'{"id":"123", "completed":true}\n'


def test_verifier_rejects_tampered_payload_and_denies_restore(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    changed = snapshot / "payload" / "data" / "sessions" / "session.jsonl"
    changed.write_bytes(b"ATTACK: changed same file contents\n")
    recovered = installed_clean / "target"
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is False
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(recovered),
        "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert not recovered.exists()


def test_verifier_rejects_extra_file_and_symlink(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    planted = snapshot / "payload" / "data" / "extra"
    planted.write_bytes(b"not in manifest")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()
    planted.unlink()
    planted.symlink_to(installed_clean / "application-home" / ".env")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()


def test_manifest_parent_traversal_is_refused_and_outside_is_untouched(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    manifest = snapshot / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"][0]["path"] = "config/../../private-owner-key"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()
    assert not (installed_clean / "private-owner-key").exists()


def test_source_symlink_results_in_incomplete_unusable_snapshot(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    external = installed_clean / "user-private-secret"
    external.write_bytes(b"do-not-follow")
    (installed_clean / "application-home" / "data" / "follow").symlink_to(external)
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 1
    out = capsys.readouterr()
    assert "do-not-follow" not in out.out + out.err
    assert not (snapshot / "manifest.json").exists()
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()
    assert external.read_bytes() == b"do-not-follow"


def test_interrupted_backup_cannot_be_verified_or_overwritten(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _cold_state(installed_clean / "application-home")
    original = install_recovery._copy_file

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated incomplete payload before manifest")

    monkeypatch.setattr(install_recovery, "_copy_file", interrupted)
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 1
    capsys.readouterr()
    assert not (snapshot / "manifest.json").exists()
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 1
    capsys.readouterr()


def test_two_concurrent_backup_creators_have_one_winner(tmp_path: Path) -> None:
    roots = {"config": tmp_path / "existing.env", "data": tmp_path / "data",
             "experiences": tmp_path / "experiences", "methods": tmp_path / "data" / "methods"}
    roots["config"].write_bytes(b"test-secret-safely-dummy")
    roots["data"].mkdir(exist_ok=True)
    dest = tmp_path / "snapshot"

    def copy():
        try:
            install_recovery.create_backup(str(dest), roots, bundle=None)
            return "created"
        except install_recovery.BackupRejectedError:
            return "occupied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: copy(), range(2)))
    assert sorted(results) == ["created", "occupied"]
    assert install_recovery.verify_backup(dest)["valid"] is True


def test_backup_target_inside_data_source_is_blocked_without_any_output(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    inside = installed_clean / "application-home" / "data" / "backup"
    assert cli.application_main([
        "backup", "--to", str(inside), "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert not inside.exists()


def test_config_source_as_directory_is_refused_and_not_backed_up(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = installed_clean / "application-home"
    home.mkdir()
    (home / ".env").mkdir()
    target = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--plan", "--json"]) == 1
    capsys.readouterr()
    assert cli.application_main([
        "backup", "--to", str(target), "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert not target.exists()


def test_hardlink_alias_source_is_rejected_without_manifest(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _cold_state(installed_clean / "application-home")
    alias = installed_clean / "config-hardlink"
    os.link(state["config"], alias)
    target = installed_clean / "snapshot"
    assert cli.application_main([
        "backup", "--to", str(target), "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert not (target / "manifest.json").exists()
    assert alias.read_bytes() == state["config"].read_bytes()


def test_manifest_changed_to_nonprivate_mode_is_not_accepted(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    target = installed_clean / "snapshot"
    assert cli.application_main([
        "backup", "--to", str(target), "--confirm-services-stopped",
    ]) == 0
    capsys.readouterr()
    (target / "manifest.json").chmod(0o644)
    assert cli.application_main(["backup", "verify", "--from", str(target), "--json"]) == 1
    capsys.readouterr()


def test_restore_refuses_staging_target_symlink(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    outside = installed_clean / "external"
    outside.mkdir()
    target = installed_clean / "restore-symlink"
    target.symlink_to(outside, target_is_directory=True)
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(target),
        "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert target.is_symlink() and list(outside.iterdir()) == []


def test_unrecognized_snapshot_kind_cannot_be_restored(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    manifest = snapshot / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sources"]["data"] = "unverified_unknown_kind"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()


def test_relative_env_config_data_paths_use_config_parent(
    installed_clean: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app_home = installed_clean / "application-home"
    _cold_state(app_home)
    extra_data = app_home / "outside-data"
    (extra_data / "sessions").mkdir(parents=True)
    (extra_data / "sessions" / "other.jsonl").write_bytes(b"external-state\n")
    existing = (app_home / ".env").read_bytes()
    (app_home / ".env").write_bytes(existing + b'DATA_DIR="outside-data"\n')
    monkeypatch.chdir(installed_clean)
    target = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(target), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    assert (target / "payload" / "data" / "sessions" / "other.jsonl").read_bytes() == b"external-state\n"


def test_default_nested_methods_is_captured_once_with_verified_role_alias(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """data/methods and methods must not be two physical snapshot copies."""
    home = installed_clean / "application-home"
    state = _cold_state(home, secret="dummy-overlap-secret")
    target = installed_clean / "once-only-snapshot"
    assert cli.application_main([
        "backup", "--to", str(target), "--json", "--confirm-services-stopped",
    ]) == 0
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["file_count"] == len(manifest["files"]) == 5
    assert manifest["sources"]["data"] == "directory"
    assert manifest["sources"]["methods"] == "alias"
    assert manifest["aliases"]["methods"] == {"under": "data", "relative": "methods"}
    assert (target / "payload" / "data" / "methods" / "active.jsonl").read_bytes() == state["method"].read_bytes()
    assert not (target / "payload" / "methods").exists()
    assert "dummy-overlap-secret" not in output.out + output.err
    assert cli.application_main(["backup", "verify", "--from", str(target), "--json"]) == 0
    capsys.readouterr()
    restore = installed_clean / "isolated-restored"
    assert cli.application_main([
        "rollback", "--from", str(target), "--into", str(restore),
        "--confirm-services-stopped", "--json",
    ]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["file_count"] == 5
    assert (restore / "payload" / "data" / "methods" / "active.jsonl").read_bytes() == state["method"].read_bytes()
    assert not (restore / "payload" / "methods").exists()
    assert cli.application_main(["backup", "verify", "--from", str(restore), "--json"]) == 0
    capsys.readouterr()


def test_backup_plan_marks_nested_methods_capture_without_exposing_paths(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = installed_clean / "application-home"
    _cold_state(home)
    assert cli.application_main(["backup", "--plan", "--json"]) == 0
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["sources"]["methods"]["captured_via"] == "data"
    assert report["sources"]["data"]["captured_via"] == "data"
    assert report["coverage"] == "selected_roots"
    assert str(installed_clean) not in out.out + out.err


def test_distinct_external_methods_root_remains_independently_captured(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = installed_clean / "application-home"
    _cold_state(home)
    external = installed_clean / "external-methods"
    external.mkdir()
    (external / "external.jsonl").write_bytes(b"external method unrelated to data\n")
    monkeypatch.setenv("METHODS_DIR", str(external))
    snapshot = installed_clean / "external-snapshot"
    assert cli.application_main(["backup", "--plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["sources"]["methods"]["captured_via"] == "methods"
    assert cli.application_main([
        "backup", "--to", str(snapshot), "--confirm-services-stopped", "--json",
    ]) == 0
    capsys.readouterr()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sources"]["methods"] == "directory"
    assert "methods" not in manifest.get("aliases", {})
    assert (snapshot / "payload" / "methods" / "external.jsonl").read_bytes() == b"external method unrelated to data\n"


def test_identical_data_and_methods_roots_snapshot_once(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = installed_clean / "application-home"
    state = _cold_state(home)
    monkeypatch.setenv("METHODS_DIR", str(home / "data"))
    snapshot = installed_clean / "same-root-snapshot"
    assert cli.application_main([
        "backup", "--to", str(snapshot), "--json", "--confirm-services-stopped",
    ]) == 0
    capsys.readouterr()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sources"]["methods"] == "alias"
    assert manifest["aliases"]["methods"] == {"under": "data", "relative": ""}
    assert not (snapshot / "payload" / "methods").exists()
    assert (snapshot / "payload" / "data" / "methods" / "active.jsonl").read_bytes() == state["method"].read_bytes()
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 0
    capsys.readouterr()


@pytest.mark.parametrize(
    ("under", "relative"),
    [
        ("data", "../secrets"),
        ("data", "methods/../../secrets"),
        ("data", "/etc/passwd"),
        ("data", "methods//nested"),
        ("data", "methods\\nested"),
        ("methods", ""),
        ("experiences", "missing"),
        ("data", "sessions/session.jsonl"),
    ],
)
def test_manifest_role_alias_fails_closed_if_forged_or_wrong_kind(
    installed_clean: Path, capsys: pytest.CaptureFixture[str],
    under: str, relative: str,
) -> None:
    home = installed_clean / "application-home"
    _cold_state(home)
    snapshot = installed_clean / "snapshot"
    assert cli.application_main([
        "backup", "--to", str(snapshot), "--confirm-services-stopped",
    ]) == 0
    capsys.readouterr()
    manifest = snapshot / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["sources"]["methods"] == "alias"
    payload["aliases"]["methods"] = {"under": under, "relative": relative}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["valid"] is False
    recovered = installed_clean / "denied-restore"
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(recovered),
        "--confirm-services-stopped",
    ]) == 1
    capsys.readouterr()
    assert not recovered.exists()


def test_manifest_alias_cannot_advertise_an_extra_duplicate_payload(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = installed_clean / "application-home"
    _cold_state(home)
    snapshot = installed_clean / "snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    manifest = snapshot / "manifest.json"
    physical = snapshot / "payload" / "methods"
    shutil.copytree(snapshot / "payload" / "data" / "methods", physical)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["dirs"].append("methods")
    copied = next(item for item in raw["files"] if item["path"] == "data/methods/active.jsonl")
    raw["files"].append({**copied, "path": "methods/active.jsonl"})
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 1
    capsys.readouterr()


def test_legacy_v1_manifest_with_two_physical_copies_remains_restorable(
    installed_clean: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Old manifest without aliases must not become unreadable after upgrade."""
    state = _cold_state(installed_clean / "application-home")
    snapshot = installed_clean / "legacy-snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    manifest = snapshot / "manifest.json"
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    assert raw["sources"]["methods"] == "alias"
    shutil.copytree(snapshot / "payload" / "data" / "methods", snapshot / "payload" / "methods")
    raw["sources"]["methods"] = "directory"
    raw.pop("aliases", None)  # old v1 shape
    raw["dirs"].append("methods")
    raw["files"].append({
        "path": "methods/active.jsonl",
        "size": state["method"].stat().st_size,
        "sha256": hashlib.sha256(state["method"].read_bytes()).hexdigest(),
    })
    raw["dirs"].sort()
    raw["files"].sort(key=lambda item: item["path"])
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 0
    capsys.readouterr()
    restore = installed_clean / "legacy-restored"
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(restore),
        "--confirm-services-stopped", "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["file_count"] == 6
    assert (restore / "payload" / "methods" / "active.jsonl").read_bytes() == state["method"].read_bytes()
    assert cli.application_main(["backup", "verify", "--from", str(restore), "--json"]) == 0
    capsys.readouterr()


def test_config_nested_in_data_uses_file_role_alias_not_secret_duplication(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = installed_clean / "application-home"
    state = _cold_state(home)
    nested_config = home / "data" / "private.env"
    state["config"].rename(nested_config)
    monkeypatch.setenv("LFL_ENV_FILE", str(nested_config))
    snapshot = installed_clean / "config-alias-snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    raw = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert raw["sources"]["config"] == "alias"
    assert raw["aliases"]["config"] == {"under": "data", "relative": "private.env"}
    assert not (snapshot / "payload" / "config").exists()
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 0
    capsys.readouterr()
    restore = installed_clean / "config-alias-restore"
    assert cli.application_main([
        "rollback", "--from", str(snapshot), "--into", str(restore),
        "--confirm-services-stopped",
    ]) == 0
    capsys.readouterr()
    assert (restore / "payload" / "data" / "private.env").read_bytes() == nested_config.read_bytes()


def test_outer_experiences_directory_contains_data_and_config_only_once(
    installed_clean: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = installed_clean / "application-home"
    _cold_state(home)
    monkeypatch.setenv("EXPERIENCES_DIR", str(home))
    snapshot = installed_clean / "outer-experiences-snapshot"
    assert cli.application_main(["backup", "--to", str(snapshot), "--confirm-services-stopped"]) == 0
    capsys.readouterr()
    raw = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert raw["sources"]["experiences"] == "directory"
    assert raw["sources"]["data"] == "alias"
    assert raw["sources"]["methods"] == "alias"
    assert raw["sources"]["config"] == "alias"
    assert raw["aliases"]["data"] == {"under": "experiences", "relative": "data"}
    assert raw["aliases"]["methods"] == {"under": "experiences", "relative": "data/methods"}
    assert raw["aliases"]["config"] == {"under": "experiences", "relative": ".env"}
    assert cli.application_main(["backup", "verify", "--from", str(snapshot), "--json"]) == 0
    capsys.readouterr()


# ── DESIGN-20261107 §4.1/§4.2：三服务 systemd user units 与 lfl-service launcher ──


def _render_unit(service: str, lfl_home: Path, home: Path) -> str:
    from llm_loop.runtime.installation import render_unit_text
    return render_unit_text(service, lfl_home, home=home)


def test_unit_default_root_uses_h_macro_in_three_consistent_places(tmp_path: Path) -> None:
    root = tmp_path / ".local/share/lfl"
    for svc in ("web", "feishu", "learning"):
        text = _render_unit(svc, root, home=tmp_path)
        assert "WorkingDirectory=%h/.local/share/lfl\n" in text
        assert "Environment=LFL_HOME=%h/.local/share/lfl\n" in text
        assert f"ExecStart=%h/.local/share/lfl/bin/lfl-service {svc}\n" in text
        # 默认根不得把绝对路径写死进 unit（%h 由 user manager 展开）。
        assert str(root) not in text
        assert "~" not in text
        # 版本目录不进 unit：版本唯一真值是 .LFL-active-version（§4.2）。
        assert "LFL-0." not in text and "releases/LFL-" not in text


def test_unit_custom_root_writes_absolute_paths_three_consistent_places(tmp_path: Path) -> None:
    root = tmp_path / "opt" / "lfl-root"
    text = _render_unit("web", root, home=tmp_path / "userhome")
    assert f"WorkingDirectory={root}\n" in text
    assert f"Environment=LFL_HOME={root}\n" in text
    assert f"ExecStart={root}/bin/lfl-service web\n" in text
    assert "%h" not in text and "~" not in text


def test_unit_hardening_and_unified_data_dir(tmp_path: Path) -> None:
    text = _render_unit("web", tmp_path / ".local/share/lfl", home=tmp_path)
    assert "Restart=always\n" in text
    assert "RestartSec=5s\n" in text
    assert "WantedBy=default.target" in text
    assert "StartLimitIntervalSec=60" in text and "StartLimitBurst=5" in text
    assert "KillMode=control-group" in text
    assert "Environment=DATA_DIR=%h/.local/share/lfl/data\n" in text
    assert "Environment=LFL_DATA_DIR=%h/.local/share/lfl/data\n" in text
    assert "Environment=LFL_ENV_FILE=%h/.local/share/lfl/.env\n" in text
    assert "Environment=PYTHONUNBUFFERED=1\n" in text


def test_unit_descriptions_per_service(tmp_path: Path) -> None:
    expect = {
        "web": "LFL Web service",
        "feishu": "LFL Feishu service",
        "learning": "LFL Learning service",
    }
    for svc, desc in expect.items():
        assert f"Description={desc}\n" in _render_unit(svc, tmp_path / ".local/share/lfl", home=tmp_path)


def test_validate_install_root_for_units_accepts_normal_and_rejects_unsafe(
    tmp_path: Path,
) -> None:
    from llm_loop.runtime.installation import validate_install_root_for_units
    ok = tmp_path / "share" / "lfl"
    validate_install_root_for_units(ok)  # 不存在也可先做形态校验
    link = tmp_path / "linkroot"
    link.symlink_to(tmp_path / "share" / "lfl", target_is_directory=True)
    bad_roots = [
        link,                       # symlink
        Path("/"), Path("/usr"), Path("/etc"), Path("/var"), Path("/home"),
        Path("/a/../b"),            # 含 ..
        Path("/has space/lfl"),     # 空格
        Path("/ctrl\x01lfl"),       # 控制字符
        Path("relative/lfl"),       # 非绝对
    ]
    for bad in bad_roots:
        with pytest.raises(ValueError):
            validate_install_root_for_units(bad)


def test_lfl_service_launcher_guards_and_exec_semantics(tmp_path: Path) -> None:
    from llm_loop.runtime.installation import render_lfl_service_launcher
    root = tmp_path / "lfl-home"
    text = render_lfl_service_launcher(root)
    assert text.startswith("#!/bin/sh")
    # 唯一版本真值是 .LFL-active-version；拒绝 symlink 指针。
    assert ".LFL-active-version" in text
    assert "-L " in text or "readlink" in text or "symlink" in text
    # 不完整 release（.installer-incomplete 存在）必须拒绝启动。
    assert ".installer-incomplete" in text
    # wheel 完整性复核（.installer-wheel.sha256）。
    assert ".installer-wheel.sha256" in text
    # exec 保留 systemd MainPID/cgroup 语义（exec 位于各 case 分支内）。
    assert 'exec "$APP/venv/bin/lfl" start' in text
    # feishu / learning 启动命令（§4.2）。
    assert '"$APP/venv/bin/python" -m llm_loop.runtime.launch feishu' in text
    assert '"$APP/venv/bin/python" -m llm_loop.runtime.launch learning' in text
    # launcher 绑定本安装根，拒绝其它 LFL_HOME 复用（与 install_linux.sh 惯例一致）。
    assert str(root) in text


def test_install_units_verifies_then_enables_and_writes_receipt(tmp_path: Path) -> None:
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    root.mkdir(parents=True)
    unit_dir = tmp_path / "user" / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        calls.append(list(argv))
        return _sp.CompletedProcess(argv, 0, "", "")

    receipt = installation.install_service_units(
        root, unit_dir=unit_dir, home=tmp_path / "user", runner=fake_runner
    )
    expected_units = ("lfl.service", "lfl-feishu.service", "lfl-learning.service")
    for name in expected_units:
        target = unit_dir / name
        assert target.is_file()
        assert len(receipt["units"][name]["sha256"]) == 64
    launcher = root / "bin" / "lfl-service"
    assert launcher.is_file()
    assert receipt["launcher"] == str(launcher)
    flat = [" ".join(c) for c in calls]
    # 生成后 systemd-analyze --user verify 每个单元。
    verify_calls = [f for f in flat if "systemd-analyze" in f and "verify" in f]
    assert len(verify_calls) >= 3
    # verify 全过后 daemon-reload，然后逐单元 enable --now。
    first_verify = flat.index(verify_calls[0])
    reload_idx = flat.index("systemctl --user daemon-reload")
    assert all(flat.index(v) < reload_idx for v in verify_calls)
    assert first_verify < reload_idx
    for name in expected_units:
        assert f"systemctl --user enable --now {name}" in flat
    # 单元内容变化才 try-restart：首次安装不做 try-restart。
    assert not any("try-restart" in f for f in flat)


def test_install_units_verify_failure_is_fail_closed(tmp_path: Path) -> None:
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    root.mkdir(parents=True)
    unit_dir = tmp_path / "user" / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    post_verify: list[list[str]] = []

    def fake_runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        if "verify" in argv:
            return _sp.CompletedProcess(argv, 1, "", "unit is invalid")
        post_verify.append(list(argv))
        return _sp.CompletedProcess(argv, 0, "", "")

    with pytest.raises(installation.UnitInstallError):
        installation.install_service_units(
            root, unit_dir=unit_dir, home=tmp_path / "user", runner=fake_runner
        )
    # verify 失败后不得 daemon-reload / enable / try-restart。
    flat = [" ".join(c) for c in post_verify]
    assert not any("daemon-reload" in f or "enable" in f or "try-restart" in f for f in flat)


def test_install_units_changed_unit_triggers_reload_and_try_restart(tmp_path: Path) -> None:
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    root.mkdir(parents=True)
    unit_dir = tmp_path / "user" / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    # 预置一个内容不同的旧 unit，模拟重装变化。
    (unit_dir / "lfl.service").write_text("# old unit text\n", encoding="utf-8")
    flat: list[str] = []

    def fake_runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        flat.append(" ".join(argv))
        return _sp.CompletedProcess(argv, 0, "", "")

    installation.install_service_units(
        root, unit_dir=unit_dir, home=tmp_path / "user", runner=fake_runner
    )
    # 内容变化的单元：daemon-reload 后 try-restart 恰好作用于该单元。
    assert "systemctl --user try-restart lfl.service" in flat
    assert flat.index("systemctl --user try-restart lfl.service") > flat.index(
        "systemctl --user daemon-reload"
    )
    flat.clear()

    # 第二次安装相同内容：不再 try-restart。
    installation.install_service_units(
        root, unit_dir=unit_dir, home=tmp_path / "user", runner=fake_runner
    )
    assert not any("try-restart" in f for f in flat)


# ── 父会话实现自检（2026-11-07）对应的加固契约 ─────────────────────────────


def _probe_runner(saw: dict[str, object], checks: dict[str, object]):
    """记录调用的同时，在指定 systemctl 阶段执行磁盘事实断言。"""
    import subprocess as _sp

    def runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        joined = " ".join(argv)
        for phase, predicate in checks.items():
            if phase in joined and phase not in saw:
                saw[phase] = predicate()
        return _sp.CompletedProcess(argv, 0, "", "")

    return runner


def test_launcher_exists_before_enable_and_units_verified_first(tmp_path: Path) -> None:
    """enable --now 触发前 launcher 必须已可执行（否则 ExecStart 起不来）。"""
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    unit_dir = tmp_path / "user/.config/systemd/user"
    unit_dir.mkdir(parents=True)
    saw: dict[str, object] = {}

    def runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        joined = " ".join(argv)
        if "enable" in joined and "enable" not in saw:
            saw["enable"] = (root / "bin" / "lfl-service").is_file()
        if "verify" in joined and "verify" not in saw:
            saw["verify"] = (root / "bin" / "lfl-service").is_file()
        return _sp.CompletedProcess(argv, 0, "", "")

    installation.install_service_units(
        root, unit_dir=unit_dir, home=tmp_path / "user", runner=runner
    )
    assert saw["verify"] is True
    assert saw["enable"] is True


def test_daemon_reload_failure_restores_units_and_raises(tmp_path: Path) -> None:
    """daemon-reload 失败：恢复原 unit 内容与 mode，抛 UnitInstallError。"""
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    unit_dir = tmp_path / "user/.config/systemd/user"
    unit_dir.mkdir(parents=True)
    old = unit_dir / "lfl.service"
    old.write_text("# previous unit text\n", encoding="utf-8")
    old.chmod(0o640)

    def runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        if "daemon-reload" in argv:
            return _sp.CompletedProcess(argv, 1, "", "reload refused")
        return _sp.CompletedProcess(argv, 0, "", "")

    with pytest.raises(installation.UnitInstallError):
        installation.install_service_units(
            root, unit_dir=unit_dir, home=tmp_path / "user", runner=runner
        )
    assert old.read_text(encoding="utf-8") == "# previous unit text\n"
    assert (old.stat().st_mode & 0o777) == 0o640


def test_enable_failure_yields_partial_receipt_not_success(tmp_path: Path) -> None:
    """enable 失败：unit 文件保留（可人工恢复），receipt 报 partial_failed。"""
    import json as _json
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"
    unit_dir = tmp_path / "user/.config/systemd/user"
    unit_dir.mkdir(parents=True)

    def runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        if "enable" in argv and "lfl-feishu.service" in argv:
            return _sp.CompletedProcess(argv, 1, "", "enable failed")
        return _sp.CompletedProcess(argv, 0, "", "")

    receipt = installation.install_service_units(
        root, unit_dir=unit_dir, home=tmp_path / "user", runner=runner
    )
    assert receipt["status"] == "partial_failed"
    assert (unit_dir / "lfl-feishu.service").is_file()  # 保留供人工恢复
    assert (root / "bin" / "lfl-service").is_file()
    failures = _json.loads(_json.dumps(receipt["failures"]))
    assert any(f["step"] == "enable" and f["unit"] == "lfl-feishu.service" for f in failures)


def test_data_dir_conflict_is_fail_closed(tmp_path: Path) -> None:
    """显式注入的 DATA_DIR 与 LFL_DATA_DIR 不一致：拒绝安装 unit。

    env 由调用方显式注入（one-way ratchet 后 install 侧不直取进程环境）；
    服务进程层的冲突由 lfl-service launcher 运行时门守护（§2.4 判定层）。
    """
    import subprocess as _sp

    from llm_loop.runtime import installation
    root = tmp_path / "lfl-home"

    def runner(argv: list[str], **_: object) -> _sp.CompletedProcess:
        return _sp.CompletedProcess(argv, 0, "", "")

    with pytest.raises(installation.UnitInstallError):
        installation.install_service_units(
            root, unit_dir=tmp_path / "units", home=tmp_path / "user", runner=runner,
            env={"DATA_DIR": str(tmp_path / "a"), "LFL_DATA_DIR": str(tmp_path / "b")},
        )
    assert not (tmp_path / "units" / "lfl.service").exists()


def test_validate_install_root_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    """路径任一父组件为 symlink 即拒绝（不只检查最后一段）。"""
    from llm_loop.runtime.installation import validate_install_root_for_units
    real = tmp_path / "realroot" / "lfl"
    real.mkdir(parents=True)
    link_dir = tmp_path / "linked"
    link_dir.symlink_to(tmp_path / "realroot", target_is_directory=True)
    with pytest.raises(ValueError):
        validate_install_root_for_units(link_dir / "lfl")


def test_recovery_unit_is_single_oneshot_gate_before_services(tmp_path: Path) -> None:
    """§4.4：lfl-recovery.service 是 oneshot 门；业务单元 Wants+After 它。"""
    from llm_loop.runtime import installation
    root = tmp_path / ".local/share/lfl"
    home = tmp_path
    recovery = installation.render_recovery_unit_text("recovery", root, home=home)
    assert "Type=oneshot" in recovery
    assert "RemainAfterExit=yes" in recovery
    assert "Restart=no" in recovery
    assert "TimeoutStartSec=120" in recovery
    assert "Before=lfl.service lfl-feishu.service lfl-learning.service" in recovery
    assert "ExecStart=%h/.local/share/lfl/bin/lfl-recovery" in recovery
    for svc in ("web", "feishu", "learning"):
        text = installation.render_unit_text(svc, root, home=home)
        assert "Wants=lfl-recovery.service" in text
        assert "After=lfl-recovery.service" in text


def test_lfl_service_launcher_requires_recovery_ok_marker(tmp_path: Path) -> None:
    """launcher 前置判定：recovery-ok 标记缺失即 fail-closed（recovery_incomplete）。"""
    from llm_loop.runtime.installation import render_lfl_service_launcher
    text = render_lfl_service_launcher(tmp_path / "lfl-home")
    assert "recovery-ok" in text
    assert "recovery_incomplete" in text


def test_lfl_recovery_launcher_writes_marker_when_no_pending_journal(tmp_path: Path) -> None:
    """recovery 启动器：无未完成事务 → 写 recovery-ok 放行；幂等。"""
    from llm_loop.runtime.installation import render_lfl_recovery_launcher
    text = render_lfl_recovery_launcher(tmp_path / "lfl-home")
    assert text.startswith("#!/bin/sh")
    assert "recovery-ok" in text
    assert "upgrade-transactions" in text  # 未完成事务检查（无 → 放行写标记）
    # 标记内容含判定摘要（journal_id/decision/ts）。
    assert "decision=" in text or "journal_id" in text


def test_scripts_systemd_samples_match_renderers() -> None:
    """scripts/systemd 参考样本与渲染器输出逐字节一致（防双真值漂移）。"""
    from llm_loop.runtime import installation
    repo = Path(__file__).resolve().parents[2]
    samples_dir = repo / "scripts" / "systemd"
    home = Path.home()
    root = home / ".local/share/lfl"
    for svc, name in installation._MANAGED_UNIT_NAMES.items():
        sample = (samples_dir / name).read_text(encoding="utf-8")
        assert sample == installation.render_unit_text(svc, root, home=home), name
    recovery = (samples_dir / "lfl-recovery.service").read_text(encoding="utf-8")
    assert recovery == installation.render_recovery_unit_text("recovery", root, home=home)


def test_launcher_gates_order_recovery_marker_before_checksum_before_exec(
    tmp_path: Path,
) -> None:
    """launcher 文本中 recovery-ok 门先于 wheel 校验、校验先于 exec。"""
    from llm_loop.runtime.installation import render_lfl_service_launcher
    text = render_lfl_service_launcher(tmp_path / "lfl-home")
    marker_idx = text.index("recovery-ok")
    checksum_idx = text.index("sha256sum --check")
    exec_idx = text.index('exec "$APP')
    assert marker_idx < checksum_idx < exec_idx


# ── P1-3（审查 b7691f4e）：recovery launcher 精确 JSON state 提取（真实 shell gate）──


def _run_launcher(
    script_text: str, run_dir: Path, args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    import subprocess

    script = run_dir / "gate-under-test.sh"
    script.write_text(script_text, encoding="utf-8")
    script.chmod(0o755)
    return subprocess.run(
        ["/bin/sh", str(script), *(args or [])], capture_output=True, text=True, timeout=30
    )


def _fake_lfl_home(tmp_path: Path) -> Path:
    root = tmp_path / "lfl-home"
    root.mkdir(parents=True)
    (root / ".LFL-active-version").write_text("0.6.40\n", encoding="utf-8")
    return root


def test_recovery_gate_real_shell_accepts_only_true_terminal_states(
    tmp_path: Path,
) -> None:
    """真实执行 recovery gate：三个真实终态放行；settled / observed+handover.phase=settled / 损坏 JSON 一律 fail-closed。"""
    import json

    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    def make_case(name: str, journal_payload: dict | None) -> tuple[Path, subprocess.CompletedProcess[str]]:
        case = tmp_path / name
        root = _fake_lfl_home(case)
        tx = root / "upgrade-transactions" / "tx0000000000000000000000ff"
        tx.mkdir(parents=True)
        if journal_payload is not None:
            (tx / "journal.json").write_text(
                json.dumps(journal_payload), encoding="utf-8"
            )
        result = _run_launcher(render_lfl_recovery_launcher(root), case)
        return root, result

    # 三个真实终态（upgrade_stage.TX_TERMINAL_STATES）→ 放行并写标记。
    for state in ("committed", "aborted_before_cutover", "rolled_back"):
        root, result = make_case(f"ok-{state}", {"state": state})
        assert result.returncode == 0, (state, result.stderr)
        assert (root / "state" / "recovery-ok").is_file()
    # settled 不是终态（审查 P1-3：禁止整行子串匹配放行 state=settled）。
    root, result = make_case("state-settled", {"state": "settled"})
    assert result.returncode != 0
    assert "recovery_incomplete" in result.stderr
    assert not (root / "state" / "recovery-ok").exists()
    # state=observed 且 handover.phase=settled：可 fail-open 的可达状态。
    root, result = make_case(
        "observed-handover-settled",
        {"state": "observed", "handover": {"phase": "settled"}},
    )
    assert result.returncode != 0
    assert "recovery_incomplete" in result.stderr
    assert not (root / "state" / "recovery-ok").exists()
    # 损坏 JSON（含 "committed" 字样的垃圾文本）→ fail-closed。
    case = tmp_path / "garbage"
    root = _fake_lfl_home(case)
    tx = root / "upgrade-transactions" / "tx0000000000000000000000ef"
    tx.mkdir(parents=True)
    (tx / "journal.json").write_text('{"state": "committed-garbage"', encoding="utf-8")
    result = _run_launcher(render_lfl_recovery_launcher(root), case)
    assert result.returncode != 0
    assert not (root / "state" / "recovery-ok").exists()


def test_service_launcher_real_shell_blocks_without_recovery_ok(
    tmp_path: Path,
) -> None:
    """真实执行 lfl-service gate：recovery-ok 缺失 → exit 1 且输出 recovery_incomplete。"""
    from llm_loop.runtime.installation import render_lfl_service_launcher

    case = tmp_path / "svc-gate"
    root = _fake_lfl_home(case)
    result = _run_launcher(render_lfl_service_launcher(root), case, args=["web"])
    assert result.returncode != 0
    assert "recovery_incomplete" in result.stderr
    # 绑定正确的 marker（Stage 3-C 语义）放行 recovery 门；无 release 目录
    # → 仍拒绝，但拒绝原因必须是 release 缺失而非 recovery 门。
    (root / "state").mkdir()
    (root / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n"
        "active_version=0.6.40\ntx_fingerprint=none\nts=2026-11-07T00:00:00Z\n",
        encoding="utf-8",
    )
    result = _run_launcher(render_lfl_service_launcher(root), case, args=["web"])
    # 无 release 目录 → 仍拒绝，但拒绝原因必须是 release 缺失而非 recovery 门。
    assert result.returncode != 0
    assert "recovery_incomplete" not in result.stderr


def test_recovery_launcher_terminal_states_match_python_single_source(
    tmp_path: Path,
) -> None:
    """launcher 的终态清单与 upgrade_stage.TX_TERMINAL_STATES 单一真值一致。

    未来 Python 侧新增/改名终态时，此测试强制同步 shell launcher，
    防止双源漂移造成 fail-open（审查 b7691f4e P1-3 的结构性防线）。
    """
    import re

    from llm_loop.runtime.installation import render_lfl_recovery_launcher
    from llm_loop.runtime.upgrade_stage import TX_TERMINAL_STATES

    text = render_lfl_recovery_launcher(tmp_path / "lfl-home")
    match = re.search(
        r"case \"\$state_value\" in\n\s+([a-z_|\n ]+)\) : ;;", text
    )
    assert match is not None, "terminal-state case clause not found in launcher"
    shell_states = {s.strip() for s in re.split(r"[|\n]", match.group(1)) if s.strip()}
    assert shell_states == set(TX_TERMINAL_STATES)


# ── Stage 3-C（2026-11-07）：recovery fail-open 最小修复的 RED→GREEN 契约 ──
# 背景矩阵（OrbStack Ubuntu22.04 真实 shell，7 组=5 fail-open+2 正确）：
#   ①no marker+observed→拒(对) ②stale marker+observed→放行(错) ③stale+settled非终态→放行(错)
#   ④stale+损坏JSON→放行(错) ⑤no marker+孤儿tx缺journal→放行+写marker(错)
#   ⑥no marker+TX_DIR symlink→放行+写marker(错) ⑦no marker+committed→放行(对)


def _stale_marker(root: Path) -> None:
    """构造一个'看起来合法'的旧 recovery-ok（绕过存在性检查的最强对手输入）。"""
    (root / "state").mkdir(exist_ok=True)
    (root / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n"
        "active_version=0.6.40\ntx_fingerprint=none\nts=2026-11-07T00:00:00Z\n",
        encoding="utf-8",
    )


def test_recovery_gate_stale_marker_does_not_bypass_journal_check(tmp_path: Path) -> None:
    """矩阵②③④：stale marker 存在时 recovery 仍必须真实核对 journal。"""
    import json

    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    for name, payload in (
        ("observed", {"state": "observed"}),
        ("settled-nonterminal", {"state": "settled"}),
        ("corrupt", None),  # 损坏 JSON 由下方单独写入
    ):
        case = tmp_path / name
        root = _fake_lfl_home(case)
        tx = root / "upgrade-transactions" / "tx0000000000000000000000aa"
        tx.mkdir(parents=True)
        if payload is None:
            (tx / "journal.json").write_text('{"state": "committed', encoding="utf-8")
        else:
            (tx / "journal.json").write_text(json.dumps(payload), encoding="utf-8")
        _stale_marker(root)
        result = _run_launcher(render_lfl_recovery_launcher(root), case)
        assert result.returncode != 0, (name, result.stderr)
        assert "recovery_incomplete" in result.stderr


def test_recovery_gate_reruns_full_validation_when_marker_present(tmp_path: Path) -> None:
    """marker 合法写入后 journal 被篡改为非终态：重跑 recovery 必须再 fail。"""
    import json

    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    case = tmp_path / "tamper"
    root = _fake_lfl_home(case)
    tx = root / "upgrade-transactions" / "tx0000000000000000000000bb"
    tx.mkdir(parents=True)
    (tx / "journal.json").write_text(json.dumps({"state": "committed"}), encoding="utf-8")
    first = _run_launcher(render_lfl_recovery_launcher(root), case)
    assert first.returncode == 0, first.stderr
    assert (root / "state" / "recovery-ok").is_file()
    # 篡改：终态 → 非终态。recovery 不允许凭既有 marker 短路放行。
    (tx / "journal.json").write_text(json.dumps({"state": "observed"}), encoding="utf-8")
    second = _run_launcher(render_lfl_recovery_launcher(root), case)
    assert second.returncode != 0, second.stderr
    assert "recovery_incomplete" in second.stderr


def test_recovery_gate_orphan_tx_dir_without_journal_fails_closed(tmp_path: Path) -> None:
    """矩阵⑤：tx 子目录存在但 journal.json 缺失 → fail-closed，不写 marker。"""
    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    case = tmp_path / "orphan"
    root = _fake_lfl_home(case)
    (root / "upgrade-transactions" / "tx0000000000000000000000cc").mkdir(parents=True)
    result = _run_launcher(render_lfl_recovery_launcher(root), case)
    assert result.returncode != 0, result.stderr
    assert not (root / "state" / "recovery-ok").exists()


def test_recovery_gate_txdir_symlink_fails_closed(tmp_path: Path) -> None:
    """矩阵⑥：upgrade-transactions 是 symlink → fail-closed（无论 marker）。"""
    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    real_tx = tmp_path / "real-tx"
    real_tx.mkdir()
    (real_tx / "tx0000000000000000000000dd").mkdir()
    (real_tx / "tx0000000000000000000000dd" / "journal.json").write_text(
        '{"state": "observed"}', encoding="utf-8"
    )
    for with_marker in (False, True):
        case = tmp_path / f"symlink-mk{int(with_marker)}"
        root = _fake_lfl_home(case)
        (root / "upgrade-transactions").symlink_to(real_tx, target_is_directory=True)
        if with_marker:
            _stale_marker(root)
        result = _run_launcher(render_lfl_recovery_launcher(root), case)
        assert result.returncode != 0, (with_marker, result.stderr)
        # fail-closed：不新写 marker。预置的 stale marker 由 service 侧绑定
        # 核对兜底拒绝（recovery 不做删除等破坏性动作）。
        if not with_marker:
            assert not (root / "state" / "recovery-ok").exists()


def test_recovery_marker_written_with_binding_fields(tmp_path: Path) -> None:
    """放行 marker 必须绑定 active_version 与 tx_fingerprint（供 service 侧核对）。"""
    from llm_loop.runtime.installation import render_lfl_recovery_launcher

    case = tmp_path / "binding"
    root = _fake_lfl_home(case)  # active=0.6.40，无事务目录
    result = _run_launcher(render_lfl_recovery_launcher(root), case)
    assert result.returncode == 0, result.stderr
    marker = (root / "state" / "recovery-ok").read_text(encoding="utf-8")
    assert "active_version=0.6.40" in marker
    assert "tx_fingerprint=none" in marker


def test_service_launcher_stale_marker_with_pending_journal_fails_closed(
    tmp_path: Path,
) -> None:
    """矩阵②的 service 面：marker 存在但存在未完成事务 → 拒绝启动。"""
    import json

    from llm_loop.runtime.installation import render_lfl_service_launcher

    case = tmp_path / "svc-stale"
    root = _fake_lfl_home(case)
    tx = root / "upgrade-transactions" / "tx0000000000000000000000ee"
    tx.mkdir(parents=True)
    (tx / "journal.json").write_text(json.dumps({"state": "observed"}), encoding="utf-8")
    _stale_marker(root)
    result = _run_launcher(render_lfl_service_launcher(root), case, args=["web"])
    assert result.returncode != 0, result.stderr
    assert "recovery_incomplete" in result.stderr


def test_service_launcher_marker_must_bind_current_state(tmp_path: Path) -> None:
    """marker 的 active_version / tx_fingerprint 必须与当前磁盘一致。"""
    from llm_loop.runtime.installation import render_lfl_service_launcher

    # active_version 不一致（marker 记 0.6.39，指针是 0.6.40；无事务→指纹 none）。
    case = tmp_path / "svc-bind-av"
    root = _fake_lfl_home(case)
    (root / "state").mkdir()
    (root / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n"
        "active_version=0.6.39\ntx_fingerprint=none\nts=2026-11-07T00:00:00Z\n",
        encoding="utf-8",
    )
    result = _run_launcher(render_lfl_service_launcher(root), case, args=["web"])
    assert result.returncode != 0
    assert "recovery_incomplete" in result.stderr

    # tx_fingerprint 不一致（磁盘出现新事务目录，marker 仍记 none）。
    import json

    case2 = tmp_path / "svc-bind-fp"
    root2 = _fake_lfl_home(case2)
    tx = root2 / "upgrade-transactions" / "tx0000000000000000000000fa"
    tx.mkdir(parents=True)
    (tx / "journal.json").write_text(json.dumps({"state": "observed"}), encoding="utf-8")
    _stale_marker(root2)
    result2 = _run_launcher(render_lfl_service_launcher(root2), case2, args=["web"])
    assert result2.returncode != 0
    assert "recovery_incomplete" in result2.stderr


def test_service_launcher_marker_without_binding_fields_fails_closed(
    tmp_path: Path,
) -> None:
    """无绑定字段的 marker（Stage2 旧格式/手工伪造）不得凭存在放行。"""
    from llm_loop.runtime.installation import render_lfl_service_launcher

    case = tmp_path / "svc-unbound"
    root = _fake_lfl_home(case)
    (root / "state").mkdir()
    (root / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n", encoding="utf-8"
    )
    result = _run_launcher(render_lfl_service_launcher(root), case, args=["web"])
    assert result.returncode != 0
    assert "recovery_incomplete" in result.stderr


def test_create_transaction_invalidates_recovery_marker(tmp_path: Path) -> None:
    """设计 §4.4：新事务创建前旧 recovery-ok 必须失效（升级侧接线）。"""
    from llm_loop.runtime import upgrade_stage

    home = tmp_path / "home"
    (home / "state").mkdir(parents=True)
    (home / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n", encoding="utf-8"
    )
    payload = upgrade_stage.create_transaction(
        home,
        idempotency_key="stage3c-red",
        old_version="0.6.40",
        candidate_version="0.6.41",
        wheel_sha256="a" * 64,
        expected_generation=1,
        target_generation=2,
    )
    assert payload["state"] == "observed"
    assert not (home / "state" / "recovery-ok").exists()


def test_advance_transaction_invalidates_recovery_marker(tmp_path: Path) -> None:
    """事务推进同样使旧判定失效：任何可达时序不残留有效旧标记。"""
    from llm_loop.runtime import upgrade_stage

    home = tmp_path / "home"
    payload = upgrade_stage.create_transaction(
        home,
        idempotency_key="stage3c-red-adv",
        old_version="0.6.40",
        candidate_version="0.6.41",
        wheel_sha256="a" * 64,
        expected_generation=1,
        target_generation=2,
    )
    # 模拟事务推进间隙被写入的 marker（例如 recovery 在 commit 前一瞬放行）。
    (home / "state").mkdir(parents=True, exist_ok=True)
    (home / "state" / "recovery-ok").write_text(
        "journal_id=none\ndecision=no_pending_transaction\n", encoding="utf-8"
    )
    advanced = upgrade_stage.advance_transaction(
        home,
        payload["transaction_id"],
        from_state="observed",
        to_state="candidate_resolved",
    )
    assert advanced["state"] == "candidate_resolved"
    assert not (home / "state" / "recovery-ok").exists()
