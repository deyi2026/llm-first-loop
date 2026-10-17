"""P1 first-use diagnostics: local facts only, no bootstrap side effects."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from llm_loop import cli


@pytest.fixture()
def doctor_home(monkeypatch, tmp_path):
    for key in (
        "LFL_HOME", "LFL_ENV_FILE", "LFL_WORKSPACE_ROOT", "LFL_RUNTIME_ROOT",
        "DATA_DIR", "LFL_DATA_DIR", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        "SKILLS_DIR", "DOCS_DIR", "UI_V2_DIR", "METHOD_SEED_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "bundle_root", lambda: None)
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path / "lfl-home")
    # Source installs resolve the default .env relative to cli.__file__, not
    # cwd. Isolate that origin as well so a developer's real .env cannot turn
    # an intentionally unconfigured first-use case into a configured one.
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "isolated-source" / "src" / "llm_loop" / "cli.py"))
    # This command must never follow the stateful application/Engine entrypoints.
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("mutating bootstrap"))
    monkeypatch.setattr(cli, "main", lambda *_a, **_kw: pytest.fail("engine bootstrap"))
    return tmp_path


def _run_json(argv, capsys):
    rc = cli.application_main([*argv, "doctor", "--json"])
    return rc, json.loads(capsys.readouterr().out)


def _checks(report):
    return {check["id"]: check for check in report["checks"]}


def test_doctor_fixture_does_not_use_real_checkout_env(doctor_home, capsys):
    """The simulated first install must not see the developer checkout .env."""
    source_root = doctor_home / "isolated-source"
    assert Path(cli.__file__).resolve().parents[2] == source_root
    assert not (source_root / ".env").exists()
    rc, report = _run_json([], capsys)
    assert rc == 1
    assert _checks(report)["config"]["status"] == "warn"


def test_unconfigured_doctor_is_read_only_and_actionable(doctor_home, capsys):
    root = doctor_home
    before = dict(os.environ)
    rc, report = _run_json([], capsys)
    assert rc == 1
    assert report["schema"] == "lfl.doctor/v1"
    assert report["ready"] is False
    assert _checks(report)["config"]["status"] == "warn"
    assert _checks(report)["model"]["status"] == "warn"
    assert _checks(report)["installation"]["status"] == "pass"  # source checkout
    assert all(check["action"] for check in report["checks"] if check["status"] != "pass")
    assert dict(os.environ) == before
    assert not (root / "lfl-home").exists()


def test_config_sources_and_shell_precedence_without_leaking_values(doctor_home, capsys, monkeypatch):
    root = doctor_home
    cfg_dir = root / "configuration"
    cfg_dir.mkdir()
    config = cfg_dir / "custom.env"
    config.write_text(
        'LLM_API_KEY=file-top-secret\n'
        'LLM_BASE_URL="https://example.invalid/path # retained"\n'
        'LLM_MODEL=test-model\nDATA_DIR="./state # retained"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_API_KEY", "shell-top-secret")
    before = dict(os.environ)
    rc, report = _run_json(["--config", str(config)], capsys)
    assert rc == 0
    assert report["ready"] is True
    assert report["sources"]["LLM_API_KEY"] == "environment"
    assert report["sources"]["LLM_BASE_URL"] == "config_file"
    assert report["sources"]["LLM_MODEL"] == "config_file"
    assert report["sources"]["DATA_DIR"] == "config_file"
    assert _checks(report)["model"]["status"] == "pass"
    assert "top-secret" not in json.dumps(report)
    assert "example.invalid" not in json.dumps(report)
    assert "test-model" not in json.dumps(report)
    assert dict(os.environ) == before
    assert not (cfg_dir / "state # retained").exists()


def test_explicit_missing_config_and_bad_paths_fail_closed(doctor_home, capsys):
    root = doctor_home
    no_file = root / "secret-name-missing.env"
    rc, report = _run_json(["--config", str(no_file)], capsys)
    assert rc == 1
    assert _checks(report)["config"]["status"] == "fail"
    assert "secret-name" not in json.dumps(report)
    data_file = root / "existing-file"
    data_file.write_text("unchanged", encoding="utf-8")
    rc, report = _run_json([
        "--data-dir", str(data_file), "--workspace", str(root / "nonexistent-workspace")
    ], capsys)
    assert rc == 1
    assert _checks(report)["data_dir"]["status"] == "fail"
    assert _checks(report)["workspace"]["status"] == "fail"
    assert data_file.read_text(encoding="utf-8") == "unchanged"
    assert not (root / "nonexistent-workspace").exists()


def test_installed_integrity_failure_does_not_echo_manifest_or_secret(doctor_home, capsys, monkeypatch):
    bundle = doctor_home / "package"
    bundle.mkdir()
    monkeypatch.setattr(cli, "bundle_root", lambda: bundle)
    monkeypatch.setattr(cli, "check_install", lambda: {
        "ok": False, "error": "password=secret-value", "failed_files": ["secret-value"],
    })
    rc, report = _run_json([], capsys)
    assert rc == 1
    assert _checks(report)["installation"]["status"] == "fail"
    assert "secret-value" not in json.dumps(report)


def test_doctor_help_is_stateless_and_human_output_has_fixes(doctor_home, capsys):
    before = dict(os.environ)
    assert cli.application_main(["doctor", "--help"]) == 0
    assert "--json" in capsys.readouterr().out
    assert cli.application_main(["doctor"]) == 1
    text = capsys.readouterr().out
    assert "配置" in text and "LLM_API_KEY" in text
    assert dict(os.environ) == before
    assert not (doctor_home / "lfl-home").exists()


def test_doctor_cannot_open_network_connections(doctor_home, capsys, monkeypatch):
    def no_network(*_args, **_kwargs):
        pytest.fail("doctor attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setenv("LLM_API_KEY", "fake-local-only")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    rc, report = _run_json([], capsys)
    assert rc == 0 and report["read_only"] is True


def test_explicit_configuration_decoding_failure_is_bounded(doctor_home, capsys):
    file = doctor_home / "private-config.env"
    file.write_bytes(b"LLM_API_KEY=secret-value\n\xff")
    rc, report = _run_json(["--config", str(file)], capsys)
    assert rc == 1
    assert _checks(report)["config"]["status"] == "fail"
    assert "secret-value" not in json.dumps(report)
    assert "private-config" not in json.dumps(report)


def test_installed_data_inside_bundle_is_invalid(doctor_home, capsys, monkeypatch):
    bundle = doctor_home / "readonly-bundle"
    bundle.mkdir()
    monkeypatch.setattr(cli, "bundle_root", lambda: bundle)
    monkeypatch.setattr(cli, "check_install", lambda: {"ok": True})
    rc, report = _run_json(["--data-dir", str(bundle / "state")], capsys)
    assert rc == 1
    assert _checks(report)["data_dir"]["status"] == "fail"
    assert not (bundle / "state").exists()


def test_config_relative_workspace_is_checked_at_config_location(doctor_home, capsys):
    cfg = doctor_home / "config"
    cfg.mkdir()
    (cfg / "workspace").mkdir()
    file = cfg / "runtime.env"
    file.write_text("LFL_WORKSPACE_ROOT=./workspace\nLLM_API_KEY=fake\nLLM_BASE_URL=http://local.invalid/v1\n")
    rc, report = _run_json(["--config", str(file)], capsys)
    assert rc == 0
    assert _checks(report)["workspace"]["status"] == "pass"
    assert report["sources"]["LFL_WORKSPACE_ROOT"] == "config_file"


def test_doctor_parser_preserves_cli_quoted_inline_comment_and_first_duplicate(doctor_home, monkeypatch):
    from llm_loop.config import load_env_file, read_env_file_values

    cfg = doctor_home / "same-syntax.env"
    cfg.write_text('LFL_DATA_DIR="./first # kept" # outer comment\nLFL_DATA_DIR=./later\n')
    parsed = read_env_file_values(cfg)
    assert parsed["LFL_DATA_DIR"] == "./first # kept"
    monkeypatch.delenv("LFL_DATA_DIR", raising=False)
    load_env_file(cfg)
    assert os.environ["LFL_DATA_DIR"] == parsed["LFL_DATA_DIR"]
