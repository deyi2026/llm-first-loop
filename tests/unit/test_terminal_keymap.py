"""CLI R14: text-discoverable action matrix and safe local binding controls."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.terminal.editor import Composer
from llm_loop.terminal.settings import (
    ACTIONS,
    KEYMAP_MATRIX,
    UISettings,
    keymap_report,
    load_ui,
    save_ui,
    validate_ui,
)
from llm_loop.terminal.shell import _dispatch_local


def test_r14_matrix_is_exact_and_rebindable_actions_are_named() -> None:
    names = [row[0] for row in KEYMAP_MATRIX]
    assert len(names) == len(set(names)) == 29
    assert len(ACTIONS) == 12
    assert set(ACTIONS) <= set(names)
    text = keymap_report(UISettings())
    assert text.count("\n") == 31
    for important in ("Ctrl+X", "Ctrl+C", "Ctrl+D", "Alt+B/F", "IME", "/sessions"):
        assert important in text or important == "IME"
    assert "Native/terminal actions cannot be remapped" in text


def test_r14_override_disable_save_and_restore_defaults(tmp_path: Path) -> None:
    changed = validate_ui({
        "theme": "high-contrast",
        "keybindings": {"view.palette": ["c-x", "g"], "view.copy": []},
    })
    text = keymap_report(changed)
    assert "view.palette" in text and "Ctrl+X g" in text
    assert any("view.copy" in row and "disabled" in row for row in text.splitlines())
    path = tmp_path / "display.json"
    save_ui(changed, path)
    assert load_ui(path) == changed
    defaults = validate_ui({**changed.__dict__, "keybindings": {}})
    assert defaults.theme == "high-contrast"
    assert defaults.keybindings == {}
    assert "Ctrl+X p" in keymap_report(defaults)


@pytest.mark.parametrize(
    "keys",
    [["escape"], ["escape", "x"], ["tab"], ["s-tab"], ["c-x", "?"]],
)
def test_r14_reserved_terminal_and_help_shortcuts_cannot_be_stolen(keys: list[str]) -> None:
    with pytest.raises(ValueError, match="Reserved"):
        validate_ui({"keybindings": {"view.copy": keys}})


def test_r14_leader_hint_never_inserts_or_submits_a_draft(tmp_path: Path) -> None:
    from prompt_toolkit.keys import Keys

    composer = Composer(UISettings(), tmp_path)
    composer.draft = "do not send"
    presses = [SimpleNamespace(key=Keys.ControlX)]
    composer.sessions["sid"] = SimpleNamespace(
        app=SimpleNamespace(key_processor=SimpleNamespace(key_buffer=presses))
    )
    assert "Ctrl+X: waiting for action key" in composer._toolbar("sid", "glm", 100)
    assert composer.draft == "do not send"
    presses.clear()
    assert "waiting for action key" not in composer._toolbar("sid", "glm", 100)
    assert composer.draft == "do not send"


def test_r14_keymap_command_and_rebind_controls_preserve_theme(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    composer = Composer(UISettings(theme="mono"), tmp_path)
    session = SimpleNamespace(session_id="test")
    engine = object()
    assert _dispatch_local(engine, session, "/keymap", [], composer)
    assert "CLI keymap: 29 actions" in capsys.readouterr().out
    assert _dispatch_local(engine, session, "/settings", ["bind", "view.copy", "c-x", "v"], composer)
    assert composer.ui.keybindings["view.copy"] == ["c-x", "v"]
    assert _dispatch_local(engine, session, "/settings", ["unbind", "view.copy"], composer)
    assert composer.ui.keybindings["view.copy"] == []
    assert _dispatch_local(engine, session, "/settings", ["keymap-reset"], composer)
    assert composer.ui.keybindings == {}
    assert composer.ui.theme == "mono"
