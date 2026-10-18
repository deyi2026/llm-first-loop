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
        if seq[0] in {"c-c", "c-d", "c-s", "c-q", "c-z", "enter", "c-m"}:
            raise ValueError("Reserved terminal/editing key")
        used[seq] = action
    return value


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
