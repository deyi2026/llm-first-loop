"""Upgrade handoff preserves private draft data, never resubmits it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from llm_loop.runtime.cli_admission import bind_cli_startup
from llm_loop.runtime.cli_deployment_identity import StartupArtifactIdentity
from llm_loop.runtime.cli_reentry import (
    CliReentry,
    attempt_cli_reentry,
    load_cli_draft,
    reentry_argv,
    save_cli_draft,
)
from llm_loop.runtime.service_control import ManagedServiceDeployment, ManagedServiceDeploymentStore


def test_private_draft_round_trip_and_wrong_session_refused(tmp_path):
    data = tmp_path / "private-domain"
    path = save_cli_draft(data, "original-session", "draft\n第二行", "next draft")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert load_cli_draft(data, path, "original-session") == ("draft\n第二行", "next draft")
    with pytest.raises(ValueError, match="session or schema mismatch"):
        load_cli_draft(data, path, "different-session")
    outside = tmp_path / "draft-outside.json"
    outside.write_text("{}")
    with pytest.raises(ValueError, match="outside"):
        load_cli_draft(data, outside, "original-session")
    symlink = path.parent / "draft-link.json"
    symlink.symlink_to(path)
    with pytest.raises(OSError):
        load_cli_draft(data, symlink, "original-session")
    assert path.is_file()


def _target(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    head = "a" * 40
    code = tmp_path / ".releases" / head
    feature = code / "src/llm_loop/runtime/cli_reentry.py"
    feature.parent.mkdir(parents=True)
    feature.touch()
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    desired = ManagedServiceDeployment(
        schema="managed-service-deployment/v1", deployment_id="upgrade", generation=1,
        git_head=head, code_root=str(code), runtime_root=str(tmp_path), webui_artifact_sha256="c" * 64,
    )
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(desired, expected_generation=0)
    startup = StartupArtifactIdentity(42, "source_checkout", "/old/src/llm_loop/__init__.py",
                                      "/old/python", code_root="/old", git_head="b" * 40)
    binding = bind_cli_startup(data, startup)
    path = save_cli_draft(data, "same-session", "DO NOT AUTO SEND", "next")
    request = CliReentry("same-session", path, str(tmp_path / "task-workspace"), True)
    monkeypatch.setattr("llm_loop.runtime.service_control.verify_deployment_binding", lambda *_a, **_k: [])
    monkeypatch.delenv("LFL_CLI_REENTRY_ATTEMPT", raising=False)
    return store, desired, binding, request


def test_reentry_uses_fixed_artifact_and_interactive_draft_only(tmp_path, monkeypatch):
    _store, desired, binding, request = _target(tmp_path, monkeypatch)
    monkeypatch.setenv("PYTHONPATH", "/mutable/dev")
    argv, env = reentry_argv(binding, request)
    assert argv[0] == str(tmp_path / ".venv/bin/python")
    assert str(Path(desired.code_root) / "src") in argv
    assert "-I" in argv and "--interactive" in argv
    assert argv[argv.index("--session") + 1] == "same-session"
    assert argv[argv.index("--resume-draft") + 1] == str(request.draft_path)
    assert "DO NOT AUTO SEND" not in " ".join(argv)
    assert "--message-file" not in argv and "--stdin" not in argv
    assert "PYTHONPATH" not in env
    monkeypatch.setenv("LFL_CLI_REENTRY_ATTEMPT", env["LFL_CLI_REENTRY_ATTEMPT"])
    with pytest.raises(ValueError, match="already attempted"):
        reentry_argv(binding, request)


def test_barrier_or_failed_exec_keeps_draft(tmp_path, monkeypatch):
    store, desired, binding, request = _target(tmp_path, monkeypatch)
    action = store.accept_restart(target="web", expected_generation=desired.generation,
                                  requester_session_id="test")
    with pytest.raises(ValueError, match="restart is still in progress"):
        reentry_argv(binding, request)
    assert store.barriers.release("web", operation_id=action.action_id)
    calls = []

    def exec_failure(path, argv, env):
        calls.append((path, argv, env))
        raise OSError("test exec failure")

    monkeypatch.setattr(os, "execve", exec_failure)
    assert attempt_cli_reentry(binding, request) == 75
    assert len(calls) == 1
    assert load_cli_draft(binding.data_dir, request.draft_path, request.session_id) == ("DO NOT AUTO SEND", "next")


def test_plain_composer_requires_explicit_send(tmp_path, monkeypatch):
    from llm_loop.terminal.editor import Composer
    from llm_loop.terminal.settings import validate_ui

    composer = Composer(validate_ui({"plain": True}), tmp_path)
    composer.draft = "restored draft"
    monkeypatch.setattr("builtins.input", lambda *_a: "/discard")
    assert composer._plain_read() == ""
    composer.draft = "restored draft"
    monkeypatch.setattr("builtins.input", lambda *_a: "/send")
    assert composer._plain_read() == "restored draft"


def test_real_shell_refused_run_preserves_original_session_and_text(tmp_path, monkeypatch, build_test_engine):
    from dataclasses import replace

    from llm_loop.terminal.settings import UISettings
    from llm_loop.terminal.shell import interactive_session

    engine, _fake = build_test_engine([])
    data = Path(engine.settings.data_dir).resolve()
    root = data.parent / "release"
    desired = ManagedServiceDeployment(
        schema="lfl.managed-service-deployment/v2", deployment_id="shell-upgrade",
        generation=1, git_head="a" * 40, code_root=str(root), runtime_root=str(data.parent),
        data_dir=str(data), artifact_kind="source_checkout", webui_artifact_sha256="c" * 64,
    )
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(desired, expected_generation=0)
    startup = StartupArtifactIdentity(42, "source_checkout", str(root / "src/llm_loop/__init__.py"),
                                      "/python", code_root=str(root), git_head=desired.git_head)
    engine._cli_admission_binding = bind_cli_startup(data, startup)
    engine._cli_workspace = str(tmp_path)
    engine._cli_plain = True
    engine._cli_theme = None
    sid = engine.session.create()
    monkeypatch.setattr("llm_loop.terminal.shell.load_ui", lambda: UISettings(plain=True))

    def read(composer, *_args):
        composer.stashed = "other draft"
        store.compare_and_swap(replace(desired, generation=2), expected_generation=1)
        return "do not replay"

    monkeypatch.setattr("llm_loop.terminal.shell.Composer.read", read)
    assert interactive_session(engine, sid) == 75
    assert not engine.session.load(sid).messages
    request = engine._cli_reentry
    assert request.session_id == sid
    assert load_cli_draft(data, request.draft_path, sid) == ("do not replay", "other draft")


def test_single_input_retained_exactly_without_replay(tmp_path, monkeypatch, capsys):
    from llm_loop.runtime.cli_reentry import retain_single_input

    _store, _desired, binding, _request = _target(tmp_path, monkeypatch)
    text = "first\r\nsecond\n\n"
    path = retain_single_input(binding, "same-session", text)
    assert path is not None
    assert path.read_bytes() == text.encode("utf-8")
    assert path.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert not output.out
    assert "--session same-session" in output.err and "--message-file" in output.err
    assert "first" not in output.err


def test_draft_cleanup_validates_session_before_unlink(tmp_path):
    from llm_loop.runtime.cli_reentry import retire_cli_draft

    data = tmp_path / "private-domain"
    path = save_cli_draft(data, "original", "draft", "")
    with pytest.raises(ValueError, match="session or schema mismatch"):
        retire_cli_draft(data, path, "wrong")
    assert path.exists()
    retire_cli_draft(data, path, "original")
    assert not path.exists()
