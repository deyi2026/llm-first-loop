"""Installed application paths, configuration precedence and resource integrity."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import pytest

from llm_loop import cli as application


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    for key in (
        "LFL_HOME", "LFL_ENV_FILE", "LFL_WORKSPACE_ROOT", "LFL_RUNTIME_ROOT",
        "DATA_DIR", "LFL_DATA_DIR", "EXPERIENCES_DIR", "METHODS_DIR", "SKILLS_DIR", "METHOD_SEED_DIR", "DOCS_DIR", "UI_V2_DIR",
    ):
        # Register undo even when bootstrap creates a previously absent key.
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "immutable-package"
    root.mkdir()
    monkeypatch.setattr(application, "bundle_root", lambda: root)
    monkeypatch.setenv("LFL_HOME", str(tmp_path / "application-state"))
    return tmp_path, root


def _args(**kwargs):
    return argparse.Namespace(config=None, data_dir=None, workspace=None) if not kwargs else argparse.Namespace(
        **({"config": None, "data_dir": None, "workspace": None} | kwargs)
    )


def test_installed_paths_are_independent_of_cwd_and_read_only_package(isolated, monkeypatch):
    tmp_path, bundle = isolated
    other = tmp_path / "unrelated-directory"
    other.mkdir()
    monkeypatch.chdir(other)
    bindings = application.prepare_environment(_args())
    assert Path(bindings["DATA_DIR"]) == tmp_path / "application-state/data"
    assert Path(bindings["LFL_WORKSPACE_ROOT"]) == other
    assert Path(bindings["SKILLS_DIR"]) == bundle / "skills"
    assert Path(bindings["DOCS_DIR"]) == bundle / "docs"
    assert not (bundle / "data").exists()
    assert not (other / "data").exists()


def test_explicit_config_and_paths_override_defaults_without_leaking_secrets(isolated, capsys):
    tmp_path, _ = isolated
    config = tmp_path / "chosen.env"
    config.write_text("DATA_DIR=" + str(tmp_path / "from-config") + "\nTEST_LFL_SECRET=hidden\n")
    assert application.application_main(["--config", str(config), "--data-dir", str(tmp_path / "explicit"), "paths"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["DATA_DIR"] == str(tmp_path / "explicit")
    assert result["LFL_DATA_DIR"] == result["DATA_DIR"]
    assert "hidden" not in json.dumps(result)
    os.environ.pop("TEST_LFL_SECRET", None)


def test_installed_entry_does_not_load_unrelated_cwd_dotenv(isolated):
    tmp_path, _ = isolated
    (tmp_path / ".env").write_text("DATA_DIR=/unrelated-data\n")
    bindings = application.prepare_environment(_args())
    assert bindings["DATA_DIR"] != "/unrelated-data"


def test_environment_resources_keep_explicit_override(isolated, monkeypatch):
    tmp_path, _ = isolated
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "custom-skills"))
    result = application.prepare_environment(_args())
    assert result["SKILLS_DIR"] == str(tmp_path / "custom-skills")


def test_help_does_not_load_config_or_create_runtime_state(isolated, capsys):
    tmp_path, _ = isolated
    assert application.application_main(["--help"]) == 0
    assert "check-install" in capsys.readouterr().out
    assert not (tmp_path / "application-state").exists()


def test_resource_integrity_detects_tampering_and_path_escape(isolated, monkeypatch):
    tmp_path, root = isolated
    monkeypatch.setattr(application, "version", lambda _: "0.6.32")
    contents = {"docs/ai_rules.md": b"rules", "webui/dist/index.html": b"ui"}
    for name, content in contents.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    manifest = {"schema": "lfl.application-bundle/v1", "version": "0.6.32",
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert application.check_install()["ok"] is True
    (root / "docs/ai_rules.md").write_text("modified")
    assert application.check_install()["ok"] is False
    outside = tmp_path / "outside"
    outside.write_text("must not read")
    manifest["files"]["../outside"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    assert "../outside" in application.check_install()["failed_files"]


def test_storage_command_uses_bound_data_dir(isolated, capsys):
    tmp_path, _ = isolated
    previous = set((tmp_path / "data").rglob("*"))
    assert application.application_main(["event-inventory"]) == 0
    capsys.readouterr()
    # The repository's autouse fixture pre-creates cwd/data; no new state goes there.
    assert set((tmp_path / "data").rglob("*")) == previous
    assert Path(os.environ["DATA_DIR"]) == tmp_path / "application-state/data"


def test_installed_identity_requires_distribution_ownership(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from llm_loop.runtime import installation

    bundle = tmp_path / "package/_bundled"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "schema": "lfl.application-bundle/v1", "version": "0.6.32",
    }))
    module = tmp_path / "package/__init__.py"
    fake = SimpleNamespace(version="0.6.32",
        files=["llm_loop/_bundled/manifest.json"],
        locate_file=lambda _: module)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    monkeypatch.setattr(installation, "distribution", lambda _: fake)
    assert installation.installed_identity(module)["version"] == "0.6.32"
    assert installation.installed_identity(tmp_path / "wrong/__init__.py") is None
    fake.version = "0.6.33"
    assert installation.installed_identity(module) is None


def test_config_relative_data_is_anchored_to_config_file(isolated):
    tmp_path, _ = isolated
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    config = config_dir / "lfl.env"
    config.write_text("DATA_DIR=./persistent-data\n")
    paths = application.prepare_environment(_args(config=str(config)))
    assert Path(paths["DATA_DIR"]) == config_dir / "persistent-data"


def test_explicit_missing_config_reports_error(isolated, capsys):
    tmp_path, _ = isolated
    assert application.application_main(["--config", str(tmp_path / "missing"), "paths"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_config_relative_knowledge_dirs_are_anchored_to_config(isolated):
    tmp_path, _ = isolated
    config = tmp_path / "configuration/lfl.env"
    config.parent.mkdir()
    config.write_text("EXPERIENCES_DIR=./experiences\nMETHODS_DIR=./methods\n")
    application.prepare_environment(_args(config=str(config)))
    assert Path(os.environ["EXPERIENCES_DIR"]) == config.parent / "experiences"
    assert Path(os.environ["METHODS_DIR"]) == config.parent / "methods"


def test_existing_environment_data_alias_precedes_file_data(isolated, monkeypatch):
    tmp_path, _ = isolated
    config = tmp_path / "lfl.env"
    config.write_text("DATA_DIR=./from-file\n")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "from-shell"))
    paths = application.prepare_environment(_args(config=str(config)))
    assert Path(paths["DATA_DIR"]) == tmp_path / "from-shell"


def test_subcommand_data_option_is_preserved(isolated, monkeypatch):
    tmp_path, _ = isolated
    seen = []
    monkeypatch.setattr(application, "main", lambda argv, **kwargs: seen.append(argv) or 0)
    assert application.application_main(["faults", "--data-dir", str(tmp_path / "audit")]) == 0
    assert seen == [["faults", "--data-dir", str(tmp_path / "audit")]]


def test_export_defaults_follow_bound_data_and_explicit_paths_survive(isolated, monkeypatch, capsys):
    from types import SimpleNamespace

    from llm_loop.introspection import export_distill

    tmp_path, _ = isolated
    seen = []
    monkeypatch.setattr(export_distill, "run_export",
        lambda *args, **kwargs: seen.append(args) or SimpleNamespace(render_text=lambda: "ok"))
    data = tmp_path / "bound"
    assert application.application_main(["--data-dir", str(data), "export-distill"]) == 0
    assert Path(seen[0][0]) == data / "sessions"
    assert Path(seen[0][1]).parent == data / "export_distill"
    assert Path(seen[0][2]).parent == data / "export_distill"
    assert application.application_main(["export-distill", "--input-dir", "chosen", "--output", "out", "--report", "report"]) == 0
    assert seen[1] == ("chosen", "out", "report")
    capsys.readouterr()


@pytest.mark.parametrize("command", ["chat", "list", "web"])
def test_selected_workspace_reaches_entry_assembly(isolated, monkeypatch, command):
    from llm_loop import factory, web

    tmp_path, _ = isolated
    selected = tmp_path / "selected"
    selected.mkdir()
    seen = []
    class CapturedError(Exception):
        pass
    if command == "web":
        def web_main(**kwargs):
            seen.append(kwargs)
        monkeypatch.setattr(web, "main", web_main)
        assert application.application_main(["--workspace", str(selected), command]) == 0
    else:
        monkeypatch.setattr(application, "load_settings", lambda: object())
        def capture(settings, **kwargs):
            seen.append(kwargs)
            raise CapturedError
        monkeypatch.setattr(factory, "build_engine", capture)
        with pytest.raises(CapturedError):
            application.application_main(["--workspace", str(selected), command, *(["hello"] if command == "chat" else [])])
    assert seen == [{"workspace_root": str(selected)}]


def test_explicit_workspace_activation_overrides_saved_current(isolated):
    from types import SimpleNamespace

    from llm_loop.factory import _activate_default_workspace
    from llm_loop.workspace.store import WorkspaceStore

    tmp_path, _ = isolated
    data = tmp_path / "isolated-data"
    saved = tmp_path / "saved"
    selected = tmp_path / "selected"
    saved.mkdir()
    selected.mkdir()
    store = WorkspaceStore(str(data))
    old = store.register(str(saved))
    store.switch(old.id)
    activated = []
    engine = SimpleNamespace(set_workspace=lambda path, workspace_id: activated.append((path, workspace_id)))
    _activate_default_workspace(engine, SimpleNamespace(data_dir=str(data)), workspace_root=str(selected))
    assert Path(activated[-1][0]) == selected
    assert Path(engine.workspace_store.get_current().path) == selected


def test_bootstrap_snapshot_supports_explicit_environment_without_mutation():
    from llm_loop.runtime.resolver import legacy_env_snapshot

    before = {"LFL_HOME": "/chosen", "UNRELATED": "unchanged"}
    snapshot = legacy_env_snapshot(base_env=before)
    snapshot["LFL_HOME"] = "/other"
    assert before == {"LFL_HOME": "/chosen", "UNRELATED": "unchanged"}


def test_bootstrap_adapter_applies_only_explicit_path_bindings(monkeypatch):
    from llm_loop.runtime.resolver import apply_to_environ

    monkeypatch.setenv("TEST_BOOTSTRAP_KEEP", "keep")
    monkeypatch.setenv("LFL_ENV_FILE", "before")
    apply_to_environ({"LFL_ENV_FILE": "/chosen/config.env"})
    assert os.environ["LFL_ENV_FILE"] == "/chosen/config.env"
    assert os.environ["TEST_BOOTSTRAP_KEEP"] == "keep"
