"""Enhanced inline composer using prompt_toolkit, with an explicit plain fallback."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from llm_loop.runtime.resolver import legacy_env_snapshot
from llm_loop.terminal.presentation import safe_text
from llm_loop.terminal.settings import ACTIONS, UISettings
from llm_loop.terminal.state import saved_terminal

COMMANDS = {
    "/help": "Commands and input help", "/keys": "Keyboard and focus help",
    "/new": "New session; old history retained", "/sessions": "List sessions",
    "/resume": "Resume an exact session ID", "/model": "Model catalog or selection",
    "/tasks": "Read-only tasks and child states", "/input": "single or multiline",
    "/theme": "auto/dark/light/high-contrast/mono", "/settings": "Display settings",
    "/transcript": "Readable session transcript", "/raw": "Exact session JSON",
    "/details": "Tool/result detail by message index", "/diff": "Stored diff text",
    "/export": "Export JSON or Markdown to a new file", "/copy": "Copy last answer",
    "/draft": "Stash/restore draft", "/history": "Input history", "/editor": "External editor for local draft", "/render": "Render last answer as Markdown",
    "/redraw": "Repaint composer", "/palette": "Discover commands", "/exit": "Exit",
}

KEY_HELP = """Enter submit (completion menu consumes Enter first); Ctrl+J / Alt+Enter newline
Ctrl+X s submit multiline; trailing backslash + Enter newline
Ctrl+A/E line edges; Ctrl+U/K cut; Ctrl+W/Y word cut/yank; Ctrl+_ undo
Ctrl+P/N history; Ctrl+R search; arrows edit/history; Tab/Shift+Tab completion
Ctrl+X e external editor; Ctrl+X p commands; Ctrl+X n new; Ctrl+X l sessions
Ctrl+X m model; Ctrl+X t tasks; Ctrl+X o details; Ctrl+X y copy; Ctrl+X b draft
F1 / Ctrl+X ? help; Ctrl+L redraw; Esc closes completion/search
Ctrl+C running: cancel this generation; composing: stash and clear
Ctrl+D empty composer: exit. Terminal selection/copy, tmux Ctrl+B and Ctrl+S/Q/Z stay native.
Use /input multiline where the terminal cannot distinguish modified Enter.
IME composition depends on the terminal: explicit multiline mode prevents Enter from submitting."""


def palette_text() -> str:
    return "\n".join(f"{name:14} {description}" for name, description in COMMANDS.items())


def editor_style(theme: str) -> dict[str, str]:
    palettes = {
        "dark": ("ansicyan", "bg:#20232b #e6e6e6"),
        "light": ("#005f87", "bg:#eeeeee #202020"),
        "high-contrast": ("bold ansiyellow", "reverse bold"),
        "mono": ("", ""),
        "auto": ("ansicyan", "reverse"),
    }
    prompt, toolbar = palettes[theme]
    return {"prompt": prompt, "bottom-toolbar": toolbar}


class Composer:
    def __init__(self, ui: UISettings, workspace: Path):
        self.ui, self.workspace = ui, workspace
        self.draft = ""
        self.stashed = ""
        self.saved_theme = ui.theme
        self.sessions = {}
        self.history = {}
        self.enhanced = not ui.plain and legacy_env_snapshot().get("TERM") != "dumb"

    def read(self, sid: str, model: str = "") -> str:
        with saved_terminal():
            return self._read(sid, model)

    def _read(self, sid: str, model: str = "") -> str:
        if not self.enhanced:
            return self._plain_read()
        # Optional import is intentional: installed plain mode remains usable when a
        # terminal dependency is unavailable, with a visible degraded status.
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            from prompt_toolkit.styles import Style
        except ImportError:
            print("[plain] prompt_toolkit unavailable; use /input multiline or /editor fallback.")
            self.enhanced = False
            return self._plain_read()
        if sid not in self.sessions:
            self.history[sid] = InMemoryHistory()
            self.sessions[sid] = PromptSession(
                history=self.history[sid], completer=self._completer(),
                key_bindings=self._bindings(), multiline=True, enable_history_search=True,
                complete_while_typing=False, mouse_support=False,
                include_default_pygments_style=False, enable_suspend=True,
            )
        session = self.sessions[sid]
        width, height = shutil.get_terminal_size((80, 24))
        toolbar = None if height < 16 else lambda: self._toolbar(sid, model, width)
        current, self.draft = self.draft, ""
        try:
            with saved_terminal():
                return session.prompt(
                    [("class:prompt", "你 > ")], default=current, bottom_toolbar=toolbar,
                    style=Style.from_dict(editor_style(self.ui.theme)),
                    reserve_space_for_menu=4 if height >= 16 else 0,
                    color_depth=None,
                )
        except KeyboardInterrupt:
            self.stashed = session.default_buffer.text or current
            print("[draft stashed] Ctrl+D exits an empty composer; /draft restores.")
            return ""

    def _toolbar(self, sid: str, model: str, width: int) -> str:
        mode = "MULTILINE · C-x s send" if self.ui.multiline else "Enter send · C-j newline"
        short = f" {safe_text(sid[:8])} · {mode} · F1 keys "
        if width < 80:
            return short
        return short + f"· {safe_text(model or 'model: unreported')} · {self.ui.theme} "

    def _plain_read(self) -> str:
        if not self.ui.multiline:
            return input("\n你> ")
        print("[multiline] Enter inserts lines; a single '.' sends, '..' inserts '.'.")
        lines = []
        while True:
            line = input("... ")
            if line == ".":
                return "\n".join(lines)
            lines.append("." if line == ".." else line)

    def _completer(self):
        from prompt_toolkit.completion import Completer, Completion

        workspace = self.workspace

        class LocalCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if text.startswith("/") and " " not in text:
                    for name, description in COMMANDS.items():
                        if name.startswith(text):
                            yield Completion(name, start_position=-len(text), display_meta=description)
                token = text.rsplit(maxsplit=1)[-1] if text.strip() else ""
                if not token.startswith("@"):
                    return
                prefix = token[1:]
                path = Path(prefix).expanduser()
                folder = path if prefix.endswith("/") else path.parent
                root = folder if folder.is_absolute() else workspace / folder
                try:
                    for entry in sorted(root.iterdir()):
                        candidate = str(folder / entry.name)
                        if candidate.startswith("./"):
                            candidate = candidate[2:]
                        if candidate.startswith(prefix):
                            value = "@" + candidate + ("/" if entry.is_dir() else "")
                            yield Completion(value, start_position=-len(token), display_meta="file reference (not attached)")
                except OSError:
                    return

        return LocalCompleter()

    def _bindings(self):
        from prompt_toolkit.key_binding import KeyBindings

        kb = KeyBindings()

        @kb.add("enter")
        def enter(event):
            buffer = event.current_buffer
            if buffer.complete_state:
                if buffer.complete_state.current_completion:
                    buffer.apply_completion(buffer.complete_state.current_completion)
                else:
                    buffer.cancel_completion()
                return
            if self.ui.multiline:
                buffer.insert_text("\n")
            elif buffer.document.current_line_before_cursor.endswith("\\"):
                buffer.delete_before_cursor(1)
                buffer.insert_text("\n")
            else:
                buffer.validate_and_handle()

        @kb.add("escape", "enter")
        def meta_newline(event):
            event.current_buffer.insert_text("\n")

        @kb.add("escape")
        def close(event):
            event.current_buffer.cancel_completion()

        @kb.add("c-x", "?")
        def help_key(event):
            self.draft = event.current_buffer.text
            event.app.exit(result="/keys")

        commands = {
            "view.palette": "/palette", "view.sessions": "/sessions", "session.new": "/new",
            "view.model": "/model", "view.tasks": "/tasks", "view.details": "/details",
            "view.keys": "/keys", "view.copy": "/copy", "editor.draft": "/draft",
        }
        for action, keys in (ACTIONS | self.ui.keybindings).items():
            if not keys:
                continue

            def callback(event, action=action):
                if action == "editor.newline":
                    event.current_buffer.insert_text("\n")
                elif action == "editor.submit":
                    event.current_buffer.validate_and_handle()
                elif action == "editor.external":
                    event.current_buffer.open_in_editor()
                else:
                    self.draft = event.current_buffer.text
                    event.app.exit(result=commands[action])

            kb.add(*keys)(callback)
        return kb

    def swap_draft(self) -> None:
        self.draft, self.stashed = self.stashed, self.draft


    def external_edit(self) -> None:
        terminal_env = legacy_env_snapshot()
        command = shlex.split(terminal_env.get("VISUAL") or terminal_env.get("EDITOR") or "vi")
        with tempfile.TemporaryDirectory(prefix="lfl-draft-") as folder:
            path = Path(folder) / "draft.txt"
            path.write_text(self.draft, encoding="utf-8")
            try:
                subprocess.run([*command, str(path)], check=True)
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"External editor exited {exc.returncode}; draft unchanged") from exc
            except OSError as exc:
                raise ValueError(
                    f"Cannot start external editor {command[0]!r}; draft unchanged"
                ) from exc
            with path.open(encoding="utf-8", newline="") as edited:
                self.draft = edited.read()
