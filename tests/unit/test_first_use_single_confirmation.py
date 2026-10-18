"""The normal first-use path asks for consent once, at the write boundary."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.runtime import first_use


class _InteractiveStdin:
    @staticmethod
    def isatty() -> bool:
        return True


def _run_init(monkeypatch: pytest.MonkeyPatch, root: Path,
              responses: list[str]) -> tuple[int, list[str]]:
    prompts: list[str] = []
    remaining = iter(responses)

    def answer(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(remaining)

    monkeypatch.setattr(first_use.sys, "stdin", _InteractiveStdin())
    monkeypatch.setattr(builtins, "input", answer)
    monkeypatch.setattr(first_use.getpass, "getpass", lambda _prompt: "fake-key-for-test")
    result = first_use.run_first_use(
        args=SimpleNamespace(config=None, data_dir=None, workspace=None), root=root, bundle=None,
        environment={}, check_install=lambda: {"ok": True},
        preview=False, as_json=False,
    )
    return result, prompts


def test_first_use_writes_after_one_final_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result, prompts = _run_init(
        monkeypatch, tmp_path / "app-state",
        ["https://model.invalid/v1", "glm-5.3", "yes"],
    )

    assert result == 0
    assert prompts == [
        "LLM_BASE_URL（HTTP(S)）：",
        "LLM_MODEL（可留空）：",
        "确认新建配置？输入 yes 写入：",
    ]
    output = capsys.readouterr().out
    assert "开始填写？" not in output
    assert "LLM_API_KEY=已隐藏" in output
    assert ("fake-" + "key-for-test") not in output
    config = tmp_path / "app-state" / ".env"
    assert config.is_file()
    assert config.stat().st_mode & 0o777 == 0o600
    secret = "fake-" + "key-for-test"
    assert secret in config.read_text()
    assert "LLM_BASE_URL=\"https://model.invalid/v1\"" in config.read_text()


def test_declining_the_single_confirmation_leaves_no_config_or_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "app-state"
    result, prompts = _run_init(
        monkeypatch, root,
        ["https://model.invalid/v1", "glm-5.3", "no"],
    )

    assert result == 1
    assert prompts[-1] == "确认新建配置？输入 yes 写入："
    assert not (root / ".env").exists()
    assert not root.exists()


def test_existing_config_remains_untouched_without_prompting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "app-state"
    root.mkdir()
    config = root / ".env"
    existing_secret = "existing-" + "key"
    original = f'LLM_API_KEY="{existing_secret}"\nLLM_BASE_URL="https://existing.invalid/v1"\n'
    config.write_text(original)
    monkeypatch.setattr(first_use.sys, "stdin", _InteractiveStdin())
    monkeypatch.setattr(builtins, "input", lambda *_args: pytest.fail("must not prompt"))
    monkeypatch.setattr(first_use.getpass, "getpass", lambda *_args: pytest.fail("must not collect key"))

    result = first_use.run_first_use(
        args=SimpleNamespace(config=None, data_dir=None, workspace=None), root=root, bundle=None,
        environment={}, check_install=lambda: {"ok": True},
        preview=False, as_json=False,
    )

    assert result == 0
    assert config.read_text() == original
    assert "不会覆盖" in capsys.readouterr().out
