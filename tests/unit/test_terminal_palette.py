"""R15 interactive discovery: selecting a command never runs a model or tool."""
from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings, KeyBindingsBase

from llm_loop.terminal.editor import COMMANDS, Composer
from llm_loop.terminal.settings import UISettings
from llm_loop.terminal.shell import _dispatch_local


@pytest.mark.parametrize("existing_bindings", [False, True])
def test_command_palette_optional_key_bindings_preserve_escape_and_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_bindings: bool,
) -> None:
    """CI parity: prompt_toolkit Application.key_bindings may be None."""
    import llm_loop.terminal.editor as editor

    initial = KeyBindings() if existing_bindings else None
    if initial is not None:
        @initial.add("f1")
        def old_binding(_event):
            pass

    dialog = SimpleNamespace(key_bindings=initial, run=lambda: "/sessions")
    monkeypatch.setattr("prompt_toolkit.shortcuts.radiolist_dialog", lambda **_kwargs: dialog)
    monkeypatch.setattr(editor, "saved_terminal", nullcontext)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: True))

    composer = Composer(UISettings(), tmp_path)
    composer.enhanced = True
    assert composer.select_command() == "/sessions"
    assert isinstance(dialog.key_bindings, KeyBindingsBase)
    assert dialog.key_bindings.get_bindings_for_keys(("escape",))
    if existing_bindings:
        assert dialog.key_bindings.get_bindings_for_keys(("f1",))


def test_palette_populates_only_a_draft(tmp_path: Path, monkeypatch, capsys) -> None:
    composer = Composer(UISettings(), tmp_path)
    engine = object()  # no model/registry/tool API exists here
    session = SimpleNamespace(session_id="s")
    monkeypatch.setattr(composer, "select_command", lambda: "/sessions")
    assert _dispatch_local(engine, session, "/commands", [], composer)
    assert composer.draft == "/sessions "
    assert "explicitly submit" in capsys.readouterr().out


def test_palette_preserves_existing_draft_and_plain_fallback(tmp_path: Path, monkeypatch, capsys) -> None:
    composer = Composer(UISettings(plain=True), tmp_path)
    composer.draft = "exact user text\n中文"
    monkeypatch.setattr(composer, "select_command", lambda: "/new")
    assert _dispatch_local(object(), object(), "/palette", [], composer)
    assert composer.draft == "exact user text\n中文"
    assert "preserved your existing draft" in capsys.readouterr().out
    monkeypatch.setattr(composer, "select_command", lambda: None)
    assert _dispatch_local(object(), object(), "/palette", [], composer)
    assert "/sessions" in capsys.readouterr().out
    assert "/commands" in COMMANDS


def _completions(composer: Composer, text: str) -> list:
    return list(composer._completer().get_completions(
        Document(text, cursor_position=len(text)), CompleteEvent(completion_requested=True)
    ))


def test_local_path_completion_has_type_size_and_never_reads_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "hello.txt").write_text("hello\n世界", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    composer = Composer(UISettings(), tmp_path)
    values = _completions(composer, "@")
    by_name = {row.text: str(row.display_meta) for row in values}
    assert "file, 12 bytes; not attached" in by_name["@hello.txt"]
    assert "directory; not attached" in by_name["@folder/"]
    assert _completions(composer, "user@example.com") == []
    assert not any(row.text.startswith("@hello") for row in _completions(composer, "ordinary text"))


def test_completion_refuses_directory_escape_and_external_symlinks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "creds.txt").write_text("never enumerate", encoding="utf-8")
    (workspace / "outside").symlink_to(outside, target_is_directory=True)
    composer = Composer(UISettings(), workspace)
    assert _completions(composer, "@../secret/") == []
    assert _completions(composer, f"@{outside}/") == []
    assert _completions(composer, "@outside/") == []
    assert "@outside/" not in [c.text for c in _completions(composer, "@")]


def test_completer_is_bounded_and_does_not_auto_submit(tmp_path: Path) -> None:
    for i in range(120):
        (tmp_path / f"src{i:03}.py").write_text("", encoding="utf-8")
    composer = Composer(UISettings(), tmp_path)
    composer.draft = "original message"
    matches = _completions(composer, "@src")
    assert len(matches) == 50
    assert all(item.text.startswith("@src") for item in matches)
    assert composer.draft == "original message"
