"""First-use `lfl init` behavioral and security contract (RED before Stage B)."""

from __future__ import annotations

import io
import json
import os
import socket
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from llm_loop import cli
from llm_loop.config import read_env_file_values
from llm_loop.runtime import first_use


@pytest.fixture()
def clean_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in (
        "LFL_HOME", "LFL_ENV_FILE", "LFL_RUNTIME_ROOT", "LFL_WORKSPACE_ROOT",
        "DATA_DIR", "LFL_DATA_DIR", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        "SKILLS_DIR", "DOCS_DIR", "METHOD_SEED_DIR", "UI_V2_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "immutable-package"
    bundle.mkdir()
    monkeypatch.setattr(cli, "bundle_root", lambda: bundle)
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path / "lfl-home")
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("init used mutating bootstrap"))
    monkeypatch.setattr(cli, "main", lambda *_a, **_kw: pytest.fail("init booted Engine"))
    monkeypatch.setattr(cli, "check_install", lambda: {"ok": True})

    def no_network(*_args, **_kw):
        pytest.fail("init tried network access outside the injected live check")

    monkeypatch.setattr(socket.socket, "connect", no_network)

    from llm_loop.runtime import model_check

    monkeypatch.setattr(
        model_check,
        "check_model_config",
        lambda *_a, **_k: {
            "status": "ok",
            "ok": True,
            "latency_ms": 1,
            "message": "模型可用（测试替身）。",
            "action": "",
            "http_status": 200,
        },
    )
    return tmp_path


def _plan(capsys: pytest.CaptureFixture[str], *global_args: str):
    rc = cli.application_main([*global_args, "init", "--plan", "--json"])
    output = capsys.readouterr()
    return rc, json.loads(output.out), output


def test_init_help_is_side_effect_free(clean_install: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = dict(os.environ)
    assert cli.application_main(["init", "--help"]) == 0
    output = capsys.readouterr()
    assert "--plan" in output.out and "--json" in output.out
    assert "LLM_API_KEY=" not in output.out
    assert dict(os.environ) == before
    assert not (clean_install / "lfl-home").exists()


def test_init_plan_is_noninteractive_offline_and_zero_write(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = dict(os.environ)
    rc, plan, _ = _plan(capsys)
    assert rc == 0
    assert plan["schema"] == "lfl.init.plan/v1"
    assert plan["status"] == "needs_setup"
    assert plan["read_only"] is True and plan["write_performed"] is False
    assert plan["requires_confirmation"] is True
    assert plan["target"]["source"] == "default"
    assert plan["target"]["exists"] is False and plan["target"]["can_create"] is True
    assert {"LLM_API_KEY", "LLM_BASE_URL"}.issubset(set(plan["required_keys"]))
    assert "lfl init" in " ".join(plan["next_steps"])
    assert dict(os.environ) == before
    assert not (clean_install / "lfl-home").exists()


def test_plan_never_echoes_credentials_or_urls(
    clean_install: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "invisible-api-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://private.example.invalid/v1?token=never")
    monkeypatch.setenv("LLM_MODEL", "sensitive-model-id")
    before = dict(os.environ)
    rc, plan, output = _plan(capsys)
    assert rc == 0
    assert plan["target"]["can_create"] is False  # environment is already sufficient
    assert plan["status"] == "already_configured"
    assert plan["sources"]["LLM_API_KEY"] == "environment"
    assert plan["sources"]["LLM_BASE_URL"] == "environment"
    for forbidden in ("invisible-api-key", "private.example.invalid", "token=never", "sensitive-model-id", str(clean_install)):
        assert forbidden not in output.out + output.err
    assert dict(os.environ) == before
    assert not (clean_install / "lfl-home").exists()


def test_explicit_existing_config_is_never_overwritten(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = clean_install / "private-existing.env"
    original = b"LLM_API_KEY=original-secret\nLLM_BASE_URL=https://example.invalid/v1\n"
    path.write_bytes(original)
    original_mode = path.stat().st_mode
    rc, plan, output = _plan(capsys, "--config", str(path))
    assert rc == 0
    assert plan["target"]["source"] == "command_line"
    assert plan["target"]["exists"] is True
    assert plan["target"]["can_create"] is False
    assert path.read_bytes() == original and path.stat().st_mode == original_mode
    assert "original-secret" not in output.out + output.err
    assert str(path) not in output.out + output.err


def test_explicit_symlink_target_is_blocked_without_following(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original = clean_install / "victim.env"
    original.write_text("SENTINEL=do-not-touch\n", encoding="utf-8")
    alias = clean_install / "linked.env"
    alias.symlink_to(original)
    rc, plan, output = _plan(capsys, "--config", str(alias))
    assert rc == 1
    assert plan["status"] == "blocked"
    assert plan["target"]["can_create"] is False
    assert original.read_text(encoding="utf-8") == "SENTINEL=do-not-touch\n"
    assert alias.is_symlink()
    assert "SENTINEL" not in output.out + output.err


def test_non_tty_init_refuses_to_write(
    clean_install: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("yes\n"))
    assert cli.application_main(["init"]) == 2
    output = capsys.readouterr()
    assert "--plan" in output.out + output.err
    assert not (clean_install / "lfl-home").exists()


def test_json_without_plan_is_not_a_write_bypass(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.application_main(["init", "--json"]) == 2
    capsys.readouterr()
    assert not (clean_install / "lfl-home").exists()


def test_init_cancel_preserves_other_configuration(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = clean_install / "some-other.env"
    existing.write_bytes(b"LLM_API_KEY=must-remain\n")
    monkeypatch.setattr(cli.sys, "stdin", type("TTY", (io.StringIO,), {"isatty": lambda self: True})(""))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert cli.application_main(["--config", str(clean_install / "new.env"), "init"]) == 1
    assert existing.read_bytes() == b"LLM_API_KEY=must-remain\n"
    assert not (clean_install / "new.env").exists()
    assert not (clean_install / "lfl-home").exists()


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _interactive(monkeypatch: pytest.MonkeyPatch, *, key: str, responses: list[str]) -> None:
    answers = iter(responses)
    monkeypatch.setattr(cli.sys, "stdin", _TTY())
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(first_use.getpass, "getpass", lambda _prompt="": key)


def test_confirmed_setup_creates_exactly_one_private_config(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = "test-token # with literal tag"
    _interactive(monkeypatch, key=key, responses=["https://example.invalid/v1?q=a#frag", "glm/glm-5.3", "yes"])
    before_env = dict(os.environ)
    rc = cli.application_main(["init"])
    output = capsys.readouterr()
    assert rc == 0, output.out + output.err
    config = clean_install / "lfl-home" / ".env"
    assert config.is_file()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.parent.stat().st_mode) == 0o700
    assert read_env_file_values(config) == {
        "LLM_API_KEY": key,
        "LLM_BASE_URL": "https://example.invalid/v1?q=a#frag",
        "LLM_MODEL": "glm/glm-5.3",
    }
    assert not list(config.parent.glob(".env.new.*"))
    assert not (clean_install / "lfl-home" / "data").exists()
    assert "ready" in output.out
    for forbidden in (key, "example.invalid", "?q=a", "glm/glm-5.3"):
        assert forbidden not in output.out + output.err
    assert dict(os.environ) == before_env


def test_final_confirmation_rejection_creates_nothing(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interactive(monkeypatch, key="hidden-value", responses=["https://example.invalid/v1", "", "no"])
    assert cli.application_main(["init"]) == 1
    assert not (clean_install / "lfl-home").exists()


def test_existing_file_cannot_be_overridden_in_interactive_mode(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = clean_install / "already.env"
    config.write_bytes(b"API_KEY=keep-exact-original\n")
    _interactive(monkeypatch, key="new-secret", responses=["https://example.invalid/v1", "", "yes"])
    assert cli.application_main(["--config", str(config), "init"]) == 0
    assert config.read_bytes() == b"API_KEY=keep-exact-original\n"


def test_new_config_rejects_injected_newline_or_control_character(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    injected = "a\nLLM_BASE_URL=http://malicious.invalid/v1"
    _interactive(monkeypatch, key=injected, responses=["https://example.invalid/v1", "", "yes"])
    assert cli.application_main(["init"]) == 1
    out = capsys.readouterr()
    assert injected not in out.out + out.err
    assert not (clean_install / "lfl-home").exists()


def test_missing_explicit_parent_is_blocked_without_directory_creation(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = clean_install / "missing-parent" / "setup.env"
    rc, plan, _ = _plan(capsys, "--config", str(target))
    assert rc == 1
    assert plan["status"] == "blocked" and plan["target"]["can_create"] is False
    assert not target.parent.exists()


def test_empty_environment_key_cannot_be_silently_overridden_by_new_file(
    clean_install: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    rc, plan, _ = _plan(capsys)
    assert rc == 1
    assert plan["status"] == "blocked"
    assert plan["target"]["can_create"] is False
    assert not (clean_install / "lfl-home").exists()


def test_last_moment_config_race_never_clobbers_existing_file(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = clean_install / "race.env"
    responses = iter(["https://example.invalid/v1", "", "yes"])

    def create_racing_config(_prompt: str = "") -> str:
        answer = next(responses)
        # The single final write confirmation races.
        if answer == "yes" and config.parent.exists() and not config.exists() and ("race" in _prompt or "写入" in _prompt):
            config.write_bytes(b"RACE_WINNER=untouched\n")
        return answer

    monkeypatch.setattr(cli.sys, "stdin", _TTY())
    monkeypatch.setattr("builtins.input", create_racing_config)
    monkeypatch.setattr(first_use.getpass, "getpass", lambda _prompt="": "credential")
    assert cli.application_main(["--config", str(config), "init"]) == 1
    assert config.read_bytes() == b"RACE_WINNER=untouched\n"


def test_atomic_file_create_never_replaces_concurrent_winner(tmp_path: Path) -> None:
    target = tmp_path / "race.env"

    def attempt(payload: bytes) -> str:
        try:
            first_use._exclusive_create(target, payload)
            return "created"
        except FileExistsError:
            return "existing"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [b"one\n", b"two\n"]))
    assert sorted(results) == ["created", "existing"]
    assert target.read_bytes() in (b"one\n", b"two\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".race.env.new.*"))


def test_explicit_parent_symlink_is_canonicalized_before_consent(
    clean_install: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = clean_install / "existing-outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"untouched")
    alias = clean_install / "alias-parent"
    alias.symlink_to(outside, target_is_directory=True)
    rc, plan, _ = _plan(capsys, "--config", str(alias / "setup.env"))
    assert rc == 0 and plan["status"] == "needs_setup"
    assert plan["target"]["can_create"] is True
    assert not (outside / "setup.env").exists()
    _interactive(monkeypatch, key="dummy-value", responses=["https://example.invalid/v1", "", "yes"])
    assert cli.application_main(["--config", str(alias / "setup.env"), "init"]) == 0
    output = capsys.readouterr()
    assert str(outside / "setup.env") in output.out  # canonical destination shown for consent
    assert (outside / "setup.env").exists()
    assert "dummy-value" not in output.out + output.err
    assert (outside / "keep").read_bytes() == b"untouched"


def test_reject_config_path_parent_traversal_without_writing(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, plan, output = _plan(capsys, "--config", str(clean_install / "subdir" / ".." / "redirect.env"))
    assert rc == 1 and plan["status"] == "blocked"
    assert plan["write_performed"] is False
    assert not (clean_install / "redirect.env").exists()
    assert str(clean_install) not in output.out + output.err


def test_atomic_writer_rejects_symlink_parent_even_if_preflight_was_stale(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "moved"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        first_use._exclusive_create(alias / "new.env", b"SECRET=must-not-land-outside\n")
    assert not (outside / "new.env").exists()


def test_atomic_writer_rejects_intermediate_ancestor_symlink(tmp_path: Path) -> None:
    """O_NOFOLLOW must inspect lexical ancestors, not a pre-resolved realpath."""
    outside = tmp_path / "outside"
    nested = outside / "nested"
    nested.mkdir(parents=True)
    alias = tmp_path / "swapped-ancestor"
    alias.symlink_to(outside, target_is_directory=True)
    # The symlink is NOT the immediate parent component of new.env.
    with pytest.raises(OSError):
        first_use._exclusive_create(alias / "nested" / "new.env", b"SECRET=must-not-land-outside\n")
    assert not (nested / "new.env").exists()


def test_atomic_writer_uses_bounded_temp_name_for_long_config_name(tmp_path: Path) -> None:
    target = tmp_path / ("c" * 250 + ".env")
    first_use._exclusive_create(target, b"LLM_MODEL=test\n")
    assert target.read_bytes() == b"LLM_MODEL=test\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".lfl-init-*.tmp"))


def test_resolved_config_path_inside_immutable_bundle_still_blocked(
    clean_install: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = clean_install / "immutable-package"
    alias = clean_install / "alias-bundle"
    alias.symlink_to(bundle, target_is_directory=True)
    rc, plan, _ = _plan(capsys, "--config", str(alias / "secret.env"))
    assert rc == 1 and plan["status"] == "blocked"
    assert not (bundle / "secret.env").exists()


def test_default_home_via_symlink_parent_is_usable(
    clean_install: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parent = clean_install / "real-parent"
    real_parent.mkdir()
    alias = clean_install / "linked-parent"
    alias.symlink_to(real_parent, target_is_directory=True)
    monkeypatch.setattr(cli, "default_home", lambda: alias / "state")
    rc, plan, output = _plan(capsys)
    assert rc == 0 and plan["target"]["can_create"] is True
    assert str(real_parent) not in output.out + output.err
    _interactive(monkeypatch, key="test-token", responses=["https://example.invalid/v1", "", "yes"])
    assert cli.application_main(["init"]) == 0
    capsys.readouterr()
    assert (real_parent / "state" / ".env").is_file()


def test_confirmed_setup_with_existing_environment_does_not_write(
    clean_install: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "already-in-shell")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    _interactive(monkeypatch, key="unused-new-key", responses=[])
    assert cli.application_main(["init"]) == 0
    assert not (clean_install / "lfl-home").exists()
