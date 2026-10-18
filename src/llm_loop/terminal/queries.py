"""Credential-free CLI queries: no Engine, provider client, mkdir or env mutation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llm_loop.config import Settings, read_env_file_values
from llm_loop.llm.providers import load_registry
from llm_loop.runtime.resolver import legacy_env_snapshot
from llm_loop.terminal.editor import KEY_HELP
from llm_loop.terminal.presentation import safe_text
from llm_loop.terminal.records import (
    export_record,
    read_session,
    session_root,
    session_rows,
    transcript,
)

READ_COMMANDS = {"session", "sessions", "model", "models", "identity", "status", "config", "keys", "help"}
HELP = """lfl [--config FILE] [--data-dir DIR] [--workspace DIR] COMMAND
chat [MESSAGE | --stdin | --message-file FILE] [--session ID] [--model REF]
     [--interactive] [--output text|json|jsonl] [--plain] [--no-stream] [--theme THEME]
sessions list [--archived] [--json]
sessions show ID [--raw] [--json]
sessions search QUERY [--json]
sessions export ID --to FILE [--format json|markdown]
models [--json] | identity [--json] | config show [--json] | keys
Installed workflows: start [--plan] [--json], extensions, init, doctor, paths,
check-install, upgrade --plan, backup, rollback, web
Legacy management: list, search, delete, archive, unarchive, extract, fork, rename,
evolve-list/review/complete/verify, export-distill, export-serve-mcp,
archive-index, event-inventory/migrate/verify/rollback/retire/retire-rollback/
rotate-status/hooks, session-fork, faults.
Queries/help do not start Engine or call a model. Use chat --help for chat options.
See docs/cli.md for command contracts and full legacy usage."""


def query_context(options: Any = None) -> tuple[Path, Path, dict]:
    supplied = options or argparse.Namespace(config=None, data_dir=None, workspace=None)
    environment = legacy_env_snapshot()
    root = Path(getattr(supplied, "_query_home", Path(__file__).resolve().parents[3]))
    config = Path(supplied.config or environment.get("LFL_ENV_FILE") or root / ".env").expanduser()
    values = read_env_file_values(config) if config.is_file() else {}
    values.update(environment)
    raw = supplied.data_dir or values.get("DATA_DIR") or values.get("LFL_DATA_DIR") or str(root / "data")
    data = Path(raw).expanduser()
    if not data.is_absolute():
        base = Path.cwd() if supplied.data_dir or environment.get("DATA_DIR") or environment.get("LFL_DATA_DIR") else config.parent
        data = base / data
    workspace = Path(supplied.workspace or values.get("LFL_WORKSPACE_ROOT") or Path.cwd()).expanduser()
    return data.resolve(), workspace.resolve(), values


def dispatch_query(argv: list[str], options: Any = None) -> int | None:
    if not argv or argv[0] not in READ_COMMANDS | {"list", "search"}:
        return None
    cmd, rest = argv[0], argv[1:]
    cmd = {"session": "sessions", "model": "models", "status": "identity"}.get(cmd, cmd)
    if cmd == "models" and rest[:1] in (["list"], ["show"]):
        rest = rest[1:]
    if cmd == "help":
        print(HELP)
        return 0
    if cmd == "keys":
        print(KEY_HELP)
        return 0
    parser = argparse.ArgumentParser(prog=f"lfl {cmd}")
    parser.add_argument("--json", action="store_true")
    if cmd == "list":
        cmd, rest = "sessions", ["list", *rest]
    elif cmd == "search":
        cmd, rest = "sessions", ["search", *rest]
    if cmd == "sessions":
        parser.add_argument("action", choices=("list", "show", "search", "export"))
        parser.add_argument("value", nargs="?")
        parser.add_argument("--archived", action="store_true")
        parser.add_argument("--raw", action="store_true")
        parser.add_argument("--to")
        parser.add_argument("--format", choices=("json", "markdown"), default="json")
    elif cmd == "config":
        parser.add_argument("action", choices=("show",))
    try:
        ns = parser.parse_args(rest)
        data, workspace, values = query_context(options)
        return _execute_query(cmd, ns, data, workspace, values)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except (OSError, ValueError, TypeError) as exc:
        print(safe_text(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1


def _execute_query(cmd: str, ns: Any, data: Path, workspace: Path, values: dict) -> int:
    if cmd == "sessions":
        return _sessions(ns, data, workspace, values)
    if cmd in {"identity", "config"}:
        # Whitelist fields, never serialize Settings/env dictionaries or URL credentials.
        report = {"schema": "lfl.cli-identity/v1", "data_dir": str(data),
                  "workspace": str(workspace), "configured_model": values.get("LLM_MODEL", ""),
                  "actual_model": None, "actual_model_note": "Not observed: query performs no run",
                  "read_path_source": values.get("READ_PATH_SOURCE", "session_json")}
    else:
        settings = Settings(llm_api_key="", llm_model=values.get("LLM_MODEL", ""),
                            llm_base_url=values.get("LLM_BASE_URL", ""),
                            model_providers_raw=values.get("MODEL_PROVIDERS", ""), data_dir=str(data))
        registry = load_registry(settings)
        report = {"schema": "lfl.cli-models/v1", "degraded": registry.degraded,
                  "models": [{"provider": pid, "model": mid, "context": model.context,
                              "multimodal": model.multimodal, "reasoning_capable": model.reasoning_capable}
                             for pid, provider in registry.providers.items()
                             for mid, model in provider.models.items()]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if ns.json else safe_text(json.dumps(report, ensure_ascii=False, indent=2)))
    return 0


def _sessions(ns: Any, data: Path, workspace: Path, values: dict) -> int:
    root = session_root(data, workspace)
    source = values.get("READ_PATH_SOURCE", "session_json")
    if ns.action in {"list", "search"}:
        if ns.action == "search" and not ns.value:
            raise ValueError("sessions search requires a query")
        rows = session_rows(data, archived=ns.archived, query=ns.value if ns.action == "search" else "", root=root, source=source)
        print(json.dumps(rows, ensure_ascii=False, indent=2) if ns.json else safe_text("\n".join(
            f"{row['session_id']}  {row.get('title') or '(untitled)'}  "
            f"{row.get('message_count', '?')} messages {row.get('error', '')}" for row in rows)))
        return int(any("error" in row for row in rows))
    if not ns.value:
        raise ValueError("Session ID required")
    raw = read_session(data, ns.value, source, root)
    if ns.action == "export":
        if not ns.to:
            raise ValueError("sessions export requires --to FILE")
        export_record(raw, Path(ns.to).expanduser(), ns.format)
        return 0
    content = json.dumps(raw, ensure_ascii=False, indent=2) if ns.raw or ns.json else transcript(raw)
    print(content if ns.json else safe_text(content))
    return 0
