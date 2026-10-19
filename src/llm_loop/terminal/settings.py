"""User-owned display preferences; never change Provider or execution policy."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from llm_loop.runtime.resolver import legacy_env_snapshot

THEMES = ("auto", "dark", "light", "high-contrast", "mono")
ACTIONS = {
    "editor.submit": ["c-x", "s"], "editor.newline": ["c-j"],
    "editor.external": ["c-x", "e"], "view.palette": ["c-x", "p"],
    "view.sessions": ["c-x", "l"], "session.new": ["c-x", "n"],
    "view.model": ["c-x", "m"], "view.tasks": ["c-x", "t"],
    "view.details": ["c-x", "o"], "view.keys": ["f1"],
    "view.copy": ["c-x", "y"], "editor.draft": ["c-x", "b"],
}

# User-facing action matrix. Prompt-toolkit owns the native editing bindings;
# only entries in ACTIONS are rebindable by LFL. Reporting them separately
# avoids claiming that an application hotkey can override terminal/IME keys.
# Each entry is (action, native/default keys, active focus, text alternative).
KEYMAP_MATRIX = (
    ("editor.send", "Enter", "composer", "explicit send"),
    ("editor.newline", "Ctrl+J", "composer", "/input multiline"),
    ("editor.submit", "Ctrl+X s", "composer", "Enter in single-line mode"),
    ("editor.move_character", "Left/Right, Ctrl+B/F", "composer", "native editor"),
    ("editor.line_edges", "Ctrl+A/E", "composer", "native editor"),
    ("editor.word_motion", "Alt+B/F", "composer (Meta only)", "character movement"),
    ("editor.cut_line", "Ctrl+U/K", "composer", "native editor"),
    ("editor.word_cut_yank", "Ctrl+W/Y", "composer", "native editor"),
    ("editor.undo", "Ctrl+_", "composer", "native editor"),
    ("history.step", "Ctrl+P/N", "composer", "/history"),
    ("history.search", "Ctrl+R", "composer", "/history"),
    ("completion.accept", "Tab", "completion", "select candidate"),
    ("completion.previous", "Shift+Tab", "completion", "list navigation"),
    ("view.palette", "Ctrl+X p", "composer", "/palette"),
    ("editor.external", "Ctrl+X e", "composer", "/editor"),
    ("session.new", "Ctrl+X n", "composer", "/new"),
    ("view.sessions", "Ctrl+X l", "composer", "/sessions"),
    ("view.model", "Ctrl+X m", "composer", "/model"),
    ("view.tasks", "Ctrl+X t", "composer", "/tasks"),
    ("view.details", "Ctrl+X o", "composer", "/details"),
    ("view.keys", "F1", "composer", "/keys"),
    ("view.redraw", "Ctrl+L", "composer", "/redraw"),
    ("run.cancel", "Ctrl+C", "run", "/stop (owned run only)"),
    ("view.close", "Esc", "popup/completion", "return"),
    ("session.exit", "Ctrl+D (empty input)", "composer", "/exit"),
    ("view.page", "PageUp/Down", "viewer", "/transcript"),
    ("view.latest", "End (viewer only)", "viewer", "/transcript"),
    ("view.copy", "Ctrl+X y", "composer", "/copy"),
    ("editor.draft", "Ctrl+X b", "composer", "/draft"),
)


@dataclass
class UISettings:
    theme: str = "auto"
    plain: bool = False
    multiline: bool = False
    width: int = 100
    keybindings: dict[str, list[str]] = field(default_factory=dict)


def settings_path() -> Path:
    base = Path(legacy_env_snapshot().get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "lfl" / "terminal.json"


def validate_ui(raw: dict) -> UISettings:
    unknown = set(raw) - {"theme", "plain", "multiline", "width", "keybindings"}
    if unknown:
        raise ValueError("Unknown display setting: " + ", ".join(sorted(unknown)))
    value = UISettings(**raw)
    if value.theme not in THEMES or type(value.width) is not int or not 40 <= value.width <= 240:
        raise ValueError("theme/width outside supported display values")
    if type(value.plain) is not bool or type(value.multiline) is not bool:
        raise ValueError("plain/multiline must be booleans")
    if not isinstance(value.keybindings, dict):
        raise ValueError("keybindings must map action names to key sequences")
    try:
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:
        key_parser = None
    else:
        key_parser = KeyBindings()
    merged = ACTIONS | value.keybindings
    used = {}
    for action, keys in merged.items():
        if action not in ACTIONS or not isinstance(keys, list) or len(keys) > 3:
            raise ValueError(f"Invalid keybinding action/sequence: {action}")
        if not keys:
            continue  # explicitly disabled; slash command remains available
        if not all(isinstance(key, str) and key for key in keys):
            raise ValueError(f"Invalid key sequence: {action}")
        if key_parser is not None:
            key_parser.add(*keys)(lambda event: None)
        seq = tuple(keys)
        if any(seq[:len(other)] == other or other[:len(seq)] == seq for other in used):
            raise ValueError(f"Key sequence conflicts with an existing prefix: {action}")
        if seq in used:
            raise ValueError(f"Key conflict: {action} and {used[seq]}")
        if seq[0] in {
            "c-c", "c-d", "c-s", "c-q", "c-z", "enter", "c-m",
            "escape", "tab", "s-tab",
        } or seq == ("c-x", "?"):
            raise ValueError("Reserved terminal/editing key")
        used[seq] = action
    return value


def keymap_report(ui: UISettings) -> str:
    """Complete 29-action focus/keyboard contract, including real overrides."""
    names = {row[0] for row in KEYMAP_MATRIX}
    if len(KEYMAP_MATRIX) != 29 or len(names) != 29 or not set(ACTIONS) <= names:
        raise ValueError("CLI action matrix is incomplete")

    def display(keys: list[str]) -> str:
        def label(key: str) -> str:
            if key.startswith("c-"):
                return "Ctrl+" + key[2:].upper()
            if key.startswith("f") and key[1:].isdigit():
                return key.upper()
            return {"escape": "Esc", "s-tab": "Shift+Tab"}.get(key, key)
        return " ".join(label(key) for key in keys)

    lines = [
        "CLI keymap: 29 actions. Editable actions use /settings bind ACTION KEY...",
        "Use /settings unbind ACTION to disable, /settings keymap-reset to restore.",
        "Native/terminal actions cannot be remapped by the LFL UI settings.",
    ]
    for action, native, focus, alternative in KEYMAP_MATRIX:
        if action in ACTIONS:
            keys = ui.keybindings.get(action, ACTIONS[action])
            binding = display(keys) if keys else "disabled"
        else:
            binding = native
        lines.append(f"{action:25} {binding:22} [{focus}] {alternative}")
    return "\n".join(lines)


def load_ui(path: Path | None = None) -> UISettings:
    target = path or settings_path()
    if not target.exists():
        return UISettings()
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Display settings must be an object")
    return validate_ui(raw)


def save_ui(value: UISettings, path: Path | None = None) -> None:
    target = path or settings_path()
    validate_ui(asdict(value))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".terminal-", dir=target.parent)
    try:
        with open(fd, "w", encoding="utf-8") as output:
            json.dump(asdict(value), output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
