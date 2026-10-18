"""Single-command first-use workflow, backed by existing init/doctor/web."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from llm_loop import cli


@pytest.fixture
def first_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LFL_HOME", "LFL_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "bundle_root", lambda: tmp_path / "installed-bundle")
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path / "app-state")
    monkeypatch.setattr(cli, "check_install", lambda: {"ok": True})
    monkeypatch.setattr(cli, "prepare_environment", lambda *_: pytest.fail("setup started engine"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("setup used network"))
    return tmp_path


def test_start_plan_is_offline_read_only(first_user: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = dict(os.environ)
    assert cli.application_main(["start", "--plan", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "lfl.start.plan/v1"
    assert data["configuration"] == "needs_setup"
    assert data["read_only"] is True and data["will_start_web"] is False
    assert "lfl start" in data["next_step"]
    assert not (first_user / "app-state").exists()
    assert os.environ == env


def test_start_noninteractive_missing_configuration_is_safe(
    first_user: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli.application_main(["start"]) == 2
    assert "lfl init --plan" in capsys.readouterr().err + capsys.readouterr().out
    assert not (first_user / "app-state").exists()


def test_start_configured_invokes_existing_web_without_engine_bootstrap(
    first_user: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://model.invalid/v1")
    started = []
    def fake_launch(*_args):
        started.append("web")
        return 0
    from llm_loop.runtime import onboarding
    monkeypatch.setattr(onboarding, "_launch_web", fake_launch)
    assert cli.application_main(["start"]) == 0
    assert started == ["web"]


def test_start_unready_never_runs_web(first_user: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://model.invalid/v1")
    monkeypatch.setattr(cli, "check_install", lambda: {"ok": False})
    from llm_loop.runtime import onboarding
    monkeypatch.setattr(onboarding, "_launch_web", lambda: pytest.fail("web was launched"))
    assert cli.application_main(["start"]) == 1


def test_start_json_cannot_implicitly_launch(first_user: Path) -> None:
    assert cli.application_main(["start", "--json"]) == 2
    assert not (first_user / "app-state").exists()
