"""Exact transcript access, explicit export and clipboard, without mutating history."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from llm_loop.core.session import _validate_session_id
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.store import EventStore
from llm_loop.terminal.presentation import safe_text
from llm_loop.workspace.store import WorkspaceStore


def session_root(data: Path, workspace: Path | None = None, *, require_registered: bool = False) -> Path:
    base = data / "sessions"
    if workspace is None:
        return base
    if not (data / "workspaces.json").exists():
        if require_registered:
            raise ValueError("Workspace is not registered; read-only queries do not register it")
        return base
    store = WorkspaceStore(data)  # data already exists; constructor only reads registry
    store._load(strict=True)
    selected = store.get_by_path(workspace)
    if selected is None:
        raise ValueError("Workspace is not registered; read-only queries do not register it")
    return base / selected.id


def _check_owner(data: Path, root: Path, sid: str) -> bytes | None:
    base = (data / "sessions").resolve()
    if not root.resolve().is_relative_to(base):
        raise ValueError("Session root escaped its identity root")
    expected = root.resolve().relative_to(base).as_posix()
    identity = base / ".identity" / f"{sid}.json"
    if identity.exists():
        content = identity.read_bytes()
        record = json.loads(content)
        if not isinstance(record, dict):
            raise ValueError("Invalid session identity record")
        if record.get("deleted_at") or record.get("owner") != expected:
            raise ValueError("Session is deleted or owned by another workspace")
        return content
    candidates = [base / f"{sid}.json", *(
        child / f"{sid}.json" for child in base.iterdir()
        if child.is_dir() and child.name != ".identity"
    )] if base.is_dir() else []
    owners = [path.parent.resolve() for path in candidates if path.is_file()]
    if len(owners) != 1 or owners[0] != root.resolve():
        raise ValueError("Session workspace ownership cannot be established without claiming it")
    return None


def read_session(data: Path, sid: str, source: str = "session_json",
                 root: Path | None = None) -> dict:
    _validate_session_id(sid)
    selected = root or data / "sessions"
    path = selected / f"{sid}.json"
    if source != "event_log" and not path.is_file():
        raise FileNotFoundError(f"Session not found: {sid}")
    if path.is_symlink():
        raise ValueError("Symlink session files are not read")
    before = _check_owner(data, selected, sid)
    if source == "event_log":
        store = EventStore(data / "event_logs")
        if not store.exists(sid):
            raise FileNotFoundError(f"Session not found: {sid}")
        value = replay_session(store.read(sid))
        if store.last_read_skipped:
            raise ValueError(f"Event source contains {store.last_read_skipped} unreadable records")
        if not value or value.get("exists") is False:
            raise FileNotFoundError(f"Session not found: {sid}")
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("messages", []), list):
        raise ValueError("Invalid session document")
    if _check_owner(data, selected, sid) != before:
        raise ValueError("Session identity changed while reading; retry the query")
    return value


def session_rows(data: Path, *, archived: bool = False, query: str = "",
                 root: Path | None = None, source: str = "session_json") -> list[dict]:
    selected = root or data / "sessions"
    if source == "event_log":
        event_dir = data / "event_logs"
        ids = {path.stem for path in event_dir.glob("*.jsonl")} | {
            path.name for path in event_dir.iterdir() if path.is_dir()
        } if event_dir.is_dir() else set()
    else:
        ids = {path.stem for path in selected.glob("*.json")}
    rows = []
    for sid in ids:
        try:
            # Global event logs must not enumerate another workspace's session.
            if source == "event_log":
                try:
                    _check_owner(data, selected, sid)
                except ValueError:
                    continue
            raw = read_session(data, sid, source, selected)
            if not archived and raw.get("status") == "archived":
                continue
            if query.casefold() not in json.dumps(raw, ensure_ascii=False).casefold():
                continue
            rows.append({k: raw.get(k) for k in (
                "session_id", "title", "updated_at", "status", "model_override", "parent_id",
            )} | {"message_count": len(raw.get("messages", []))})
        except (OSError, ValueError, TypeError) as exc:
            rows.append({"session_id": sid, "error": type(exc).__name__})
    return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)


def transcript(raw: dict) -> str:
    lines = [f"# {raw.get('title') or raw.get('session_id', 'Session')}"]
    for index, message in enumerate(raw.get("messages", [])):
        role = message.get("role") or message.get("source") or "unknown"
        lines.extend((f"\n## {index}: {role}", str(message.get("content") or "")))
    return "\n".join(lines) + "\n"


def message_detail(raw: dict, index: int | None = None) -> str:
    messages = raw.get("messages", [])
    if not messages:
        return "No stored messages."
    selected = len(messages) - 1 if index is None else index
    if not 0 <= selected < len(messages):
        raise ValueError("Message index outside transcript")
    return json.dumps({"index": selected, **messages[selected]}, ensure_ascii=False, indent=2)


def export_record(raw: dict, path: Path, fmt: str) -> None:
    content = json.dumps(raw, ensure_ascii=False, indent=2) + "\n" if fmt == "json" else transcript(raw)
    # Exclusive create: a user export must never silently overwrite another file.
    with path.open("x", encoding="utf-8", newline="") as output:
        output.write(content)


def copy_answer(raw: dict) -> bool:
    answer = next((str(item.get("content") or "") for item in reversed(raw.get("messages", []))
                   if item.get("role") == "assistant"), "")
    if not answer:
        print("No stored assistant answer.", file=sys.stderr)
        return False
    commands = (["pbcopy"],) if sys.platform == "darwin" else (
        ["wl-copy"], ["xclip", "-selection", "clipboard"],
    )
    for command in commands:
        if shutil.which(command[0]):
            try:
                subprocess.run(command, input=answer, text=True, check=True, timeout=5)
                print("Copied the latest stored assistant answer.", file=sys.stderr)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    print("[clipboard unavailable] Select the following raw text; export preserves exact bytes.", file=sys.stderr)
    print(safe_text(answer))
    return False
