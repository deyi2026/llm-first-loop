"""User-facing local extension management, reusing ExtensionStore CAS and data retention."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from llm_loop import cli


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key in ("DATA_DIR", "LFL_DATA_DIR", "LFL_ENV_FILE", "LFL_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "bundle_root", lambda: tmp_path / "installed-bundle")
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path / "state")
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("extension loaded engine"))
    monkeypatch.setattr(cli, "main", lambda *_a, **_kw: pytest.fail("extension ran chat"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_kw: pytest.fail("extension reached network"))
    return tmp_path


def package(root: Path, version: str = "0.1.0") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin", "schema_version": "1.0.0", "version": version,
    }))
    skill = root / "skills" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Local test skill\n---\n# Skill\n")
    return root


def call_json(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict]:
    code = cli.application_main(["extensions", *args, "--json"])
    output = capsys.readouterr()
    return code, json.loads(output.out)


def test_list_empty_never_creates_user_state(setup: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, report = call_json(capsys, "list")
    assert rc == 0
    assert report["schema"] == "lfl.extensions/v1"
    assert report["installs"] == [] and report["revision"] == 0
    assert not (setup / "state").exists()


def test_inspect_local_package_without_installing(
    setup: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    item = package(setup / "pkg")
    rc, result = call_json(capsys, "inspect", str(item))
    assert rc == 0
    assert result["plugin_name"] == "demo-plugin"
    assert result["overall"] == "ready"
    assert not (setup / "state").exists()
    assert str(setup) not in json.dumps(result)


def test_install_disable_update_enable_remove_preserves_state_and_data(
    setup: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    item = package(setup / "pkg")
    rc, report = call_json(capsys, "install", str(item), "--yes")
    assert rc == 0 and report["status"] == "installed"
    assert report["install_id"] == "demo-plugin"
    rc, result = call_json(capsys, "list")
    assert rc == 0 and result["revision"] == 1
    assert result["installs"][0]["components"][0]["enabled"] is True
    instance_data = setup / "state" / "data" / "extensions" / "instances" / "demo-plugin" / "data"
    assert instance_data.exists()
    (instance_data / "keep.txt").write_text("unchanged")
    rc, result = call_json(capsys, "disable", "demo-plugin", "--yes")
    assert rc == 0 and result["status"] == "disabled"
    package(item, "0.2.0")  # new version, same authenticated local source identity
    rc, result = call_json(capsys, "install", str(item), "--yes")
    assert rc == 0 and result["status"] == "updated"
    rc, result = call_json(capsys, "list")
    assert rc == 0 and result["installs"][0]["version"] == "0.2.0"
    assert result["installs"][0]["components"][0]["enabled"] is False
    assert (instance_data / "keep.txt").read_text() == "unchanged"
    rc, result = call_json(capsys, "enable", "demo-plugin", "--yes")
    assert rc == 0 and result["status"] == "enabled"
    rc, result = call_json(capsys, "remove", "demo-plugin", "--yes")
    assert rc == 0 and result["status"] == "removed"
    rc, result = call_json(capsys, "list")
    assert rc == 0 and not result["installs"]
    assert (instance_data / "keep.txt").read_text() == "unchanged"


def test_mutations_require_explicit_yes_in_non_tty(
    setup: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    item = package(setup / "pkg")
    assert cli.application_main(["extensions", "install", str(item)]) == 2
    capsys.readouterr()
    assert not (setup / "state").exists()


def test_unknown_and_malicious_package_do_not_modify_user_state(
    setup: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = setup / "bad"
    invalid.mkdir()
    (invalid / "plugin.json").write_bytes(b"{bad-json")
    rc, report = call_json(capsys, "install", str(invalid), "--yes")
    assert rc == 1 and report["status"] == "rejected"
    assert not (setup / "state" / "data" / "extensions" / "installed.json").exists()


def test_missing_component_is_rejected_without_changing_revision(
    setup: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    item = package(setup / "pkg")
    assert call_json(capsys, "install", str(item), "--yes")[0] == 0
    before = call_json(capsys, "list")[1]
    rc, report = call_json(capsys, "disable", "demo-plugin", "--component", "missing", "--yes")
    assert rc == 1 and report["status"] == "rejected"
    assert call_json(capsys, "list")[1] == before


def test_explicit_data_dir_overrides_default_home(
    setup: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    item = package(setup / "pkg")
    external = setup / "separate-data"
    rc = cli.application_main(["--data-dir", str(external), "extensions", "install",
                               str(item), "--yes", "--json"])
    assert rc == 0
    capsys.readouterr()
    assert (external / "extensions" / "installed.json").exists()
    assert not (setup / "state" / "data" / "extensions" / "installed.json").exists()
