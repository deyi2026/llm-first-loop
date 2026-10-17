"""P1 install upgrade/backup/rollback safety contract: Stage-A RED to GREEN."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
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
