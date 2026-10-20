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
    session_rows,
    transcript,
    workspace_lookup,
)

READ_COMMANDS = {"session", "sessions", "model", "models", "identity", "status", "config", "keys", "help"}
HELP = """lfl [--config FILE] [--data-dir DIR] [--workspace DIR] COMMAND
Workspace resolves as: --workspace > cwd-upward pyproject.toml > LFL_WORKSPACE_ROOT (deployment binding, warned) > cwd; ambiguous deployment binding exits 3
chat [MESSAGE | --stdin | --message-file FILE] [--session ID] [--model REF]
     [--interactive] [--output text|json|jsonl] [--plain] [--no-stream] [--theme THEME]
sessions list [--archived] [--json]
sessions show ID [--raw] [--json]
sessions search QUERY [--json]
sessions export ID --to FILE [--format json|markdown]
models [--json] | identity [--session ID] [--json] | config show [--json] | keys
Installed workflows: start [--plan] [--json], extensions, init, doctor, paths,
check-install, upgrade --plan, backup, rollback, web
Legacy management: list, search, delete, archive, unarchive, extract, fork, rename,
evolve-list/review/complete/verify, export-distill, export-serve-mcp,
archive-index, event-inventory/migrate/verify/rollback/retire/retire-rollback/
rotate-status/hooks, session-fork, faults.
Queries/help do not start Engine or call a model. Use chat --help for chat options.
See docs/cli.md for command contracts and full legacy usage."""


def _default_query_home() -> Path:
    """Use the source root in a checkout and the caller's cwd for installed wheels."""
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "llm_loop" / "__init__.py"
        ).is_file():
            return candidate
    return Path.cwd()


_CONFIG_SOURCE_LABELS = {
    "cli", "shell_override", "runtime_toml", "dotenv", "launch_default",
    "secret_env", "dotenv_secret", "service_scope:disabled", "environment",
    "explicit_config_file", "env_file", "unset_or_default", "cli_option",
    "workspace_default", "environment:DATA_DIR", "environment:LFL_DATA_DIR",
    "explicit_config_file:DATA_DIR", "env_file:DATA_DIR",
    "explicit_config_file:LFL_DATA_DIR", "env_file:LFL_DATA_DIR",
}


def _safe_config_source_label(value: Any) -> str:
    """Allow source identifiers only; never echo arbitrary manifest strings."""
    if not isinstance(value, str):
        return "unknown"
    if value in _CONFIG_SOURCE_LABELS:
        return value
    prefix = "runtime_toml_service:"
    if value.startswith(prefix) and value[len(prefix):] in {"cli", "web", "feishu", "learning"}:
        return value
    return "unknown"


class WorkspaceAmbiguityError(Exception):
    """cwd-derived and deployment-bound workspace candidates coincide; refuse to guess."""

    def __init__(self, cwd_candidate: Path, bound_candidate: Path):
        super().__init__(f"cwd-derived={cwd_candidate} deployment-bound={bound_candidate}")
        self.cwd_candidate = cwd_candidate
        self.bound_candidate = bound_candidate


def _normalize_workspace_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _cwd_project_root() -> Path | None:
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def _resolve_query_workspace(supplied: Any, values: dict) -> Path:
    # Priority: --workspace > cwd-upward pyproject.toml > deployment binding (warn) > bare cwd.
    raw_explicit = getattr(supplied, "workspace", None)
    explicit = _normalize_workspace_value(raw_explicit)
    if raw_explicit is not None and explicit is None:
        print("warning: blank --workspace value ignored", file=sys.stderr)
    if explicit is not None:
        return Path(explicit).expanduser()
    bound = _normalize_workspace_value(values.get("LFL_WORKSPACE_ROOT"))
    cwd_root = _cwd_project_root()
    if cwd_root is None:
        if bound is None:
            return Path.cwd()
        print(
            "warning: LFL_WORKSPACE_ROOT is a deployment binding; "
            "pass --workspace PATH to be explicit",
            file=sys.stderr,
        )
        return Path(bound).expanduser()
    if bound is not None and cwd_root.resolve() == Path(bound).expanduser().resolve():
        # cwd sits inside a deployed release tree: both candidates collapse onto the
        # deployment root and prove nothing about user intent (B1 leak signature).
        raise WorkspaceAmbiguityError(cwd_root, Path(bound).expanduser())
    return cwd_root


def query_context(options: Any = None) -> tuple[Path, Path, dict]:
    supplied = options or argparse.Namespace(config=None, data_dir=None, workspace=None)
    environment = legacy_env_snapshot()
    root = Path(getattr(supplied, "_query_home", None) or _default_query_home())
    config = Path(supplied.config or environment.get("LFL_ENV_FILE") or root / ".env").expanduser()
    values = read_env_file_values(config) if config.is_file() else {}
    values.update(environment)
    raw = supplied.data_dir or values.get("DATA_DIR") or values.get("LFL_DATA_DIR") or str(root / "data")
    data = Path(raw).expanduser()
    if not data.is_absolute():
        base = Path.cwd() if supplied.data_dir or environment.get("DATA_DIR") or environment.get("LFL_DATA_DIR") else config.parent
        data = base / data
    workspace = _resolve_query_workspace(supplied, values)
    return data.resolve(), workspace.resolve(), values


def _config_source_report(options: Any, values: dict) -> dict[str, Any]:
    """Describe the exact read-only query inputs without exposing their values."""
    environment = legacy_env_snapshot()
    root = Path(getattr(options, "_query_home", None) or _default_query_home())
    explicit_config = getattr(options, "config", None)
    config_path = Path(
        explicit_config or environment.get("LFL_ENV_FILE") or root / ".env"
    ).expanduser()
    file_values = read_env_file_values(config_path) if config_path.is_file() else {}

    def source(key: str) -> str:
        if key in environment:
            return "environment"
        if key in file_values:
            return "explicit_config_file" if explicit_config else "env_file"
        return "unset_or_default"

    if getattr(options, "data_dir", None):
        data_source = "cli_option"
    elif values.get("DATA_DIR"):
        if environment.get("DATA_DIR"):
            data_source = "environment:DATA_DIR"
        else:
            data_source = "explicit_config_file:DATA_DIR" if explicit_config else "env_file:DATA_DIR"
    elif values.get("LFL_DATA_DIR"):
        if environment.get("LFL_DATA_DIR"):
            data_source = "environment:LFL_DATA_DIR"
        else:
            data_source = "explicit_config_file:LFL_DATA_DIR" if explicit_config else "env_file:LFL_DATA_DIR"
    else:
        data_source = "workspace_default"

    sources = {
        "LLM_MODEL": source("LLM_MODEL"),
        "MODEL_PROVIDERS": source("MODEL_PROVIDERS"),
        "LLM_BASE_URL": source("LLM_BASE_URL"),
        "READ_PATH_SOURCE": source("READ_PATH_SOURCE"),
        "DATA_DIR": data_source,
    }
    runtime_root = Path(
        environment.get("LFL_RUNTIME_ROOT")
        or environment.get("LFL_WORKSPACE_ROOT")
        or getattr(options, "workspace", None)
        or Path.cwd()
    ).expanduser().resolve()
    try:
        from llm_loop.runtime.resolver import resolve_effective

        effective = resolve_effective("cli", env=environment, workspace_root=runtime_root)
        runtime_effective = {
            "available": True,
            "service": "cli",
            "runtime_root": effective.runtime_root,
            "config_file": effective.config_file,
            "runtime_toml_present": Path(effective.toml_file).is_file(),
            "env_file_present": Path(effective.env_file).is_file(),
            "configured_model": effective.values.get("LLM_MODEL", ""),
            "configured_model_source": effective.sources.get("LLM_MODEL", "unset_or_default"),
            "sources": {
                key: effective.sources.get(key, "unset_or_default")
                for key in ("LLM_MODEL", "MODEL_PROVIDERS", "LLM_BASE_URL", "READ_PATH_SOURCE")
            },
        }
    except Exception as exc:  # read-only diagnostics must report malformed config, not crash the CLI
        runtime_effective = {"available": False, "error": type(exc).__name__}
    return {
        "config_file": str(config_path.resolve()),
        "config_file_exists": config_path.is_file(),
        "config_file_selection": (
            "cli_option" if explicit_config else
            "LFL_ENV_FILE" if environment.get("LFL_ENV_FILE") else "workspace_default"
        ),
        "sources": sources,
        "runtime_effective": runtime_effective,
        "configured_model_source": sources["LLM_MODEL"],
        "provider_registry_source": sources["MODEL_PROVIDERS"],
        "base_url_source": sources["LLM_BASE_URL"],
        "read_path_source": sources["READ_PATH_SOURCE"],
        "data_dir_source": data_source,
        "configured_model_present": bool(str(values.get("LLM_MODEL") or "").strip()),
    }


def _runtime_identity_report(workspace: Path) -> dict[str, Any]:
    """Project mechanical install/source identity; never mistake workspace for package."""
    from llm_loop.runtime.build_identity import compute_build_identity
    from llm_loop.runtime.identity import compute_identity

    report = compute_identity(workspace_root=workspace)
    module_path = Path(report.llm_loop_module).resolve()
    installed = report.detail.get("installed_distribution")
    source_root = (workspace / "src").resolve()
    if module_path == source_root or source_root in module_path.parents:
        kind = "source_checkout"
        build = compute_build_identity(workspace)
    elif isinstance(installed, dict):
        kind = "installed_distribution"
        build = None
    else:
        kind = "external_or_unverified"
        build = None
    return {
        "kind": kind,
        "distribution": installed if isinstance(installed, dict) else None,
        "module_path": str(module_path),
        "python_executable": report.python_executable,
        "venv_root": report.venv_root,
        "workspace_root": report.workspace_root,
        "runtime_root": str(report.detail.get("runtime_root") or workspace),
        "git_head": report.git_head if kind == "source_checkout" else None,
        "build_identity": build,
        "identity_ok": report.ok,
    }


def _service_identity_report(data: Path) -> dict[str, Any]:
    """Read the existing managed-service identity view; never start/repair services."""
    if not (data / "runtime").is_dir():
        return {"available": False, "read_only": True, "services": {}}
    try:
        from llm_loop.runtime.service_control import (
            ManagedServiceDeploymentStore,
            compose_service_identity_view,
        )

        view = compose_service_identity_view(ManagedServiceDeploymentStore(data))
    except Exception as exc:  # malformed local runtime state must not crash a read-only query
        return {
            "available": False,
            "read_only": True,
            "error": type(exc).__name__,
            "services": {},
        }
    if not isinstance(view, dict) or not isinstance(view.get("services"), dict):
        return {"available": False, "read_only": True, "error": "InvalidServiceIdentityView", "services": {}}
    deployment = view.get("deployment") or {}
    if not isinstance(deployment, dict):
        deployment = {}
    services: dict[str, Any] = {}
    for name, item in (view.get("services") or {}).items():
        if not isinstance(item, dict):
            services[str(name)] = {"error": "InvalidServiceIdentityEntry", "live": {}}
            continue
        live = item.get("live") or {}
        stable = item.get("stable") or {}
        live = live if isinstance(live, dict) else {}
        stable = stable if isinstance(stable, dict) else {}
        live_projection = {
                key: live.get(key)
                for key in (
                    "manifest_present", "pid", "pid_alive", "started_at", "git_head",
                    "build", "model_ref", "provider_id", "config_hash", "manifest_error",
                )
                if key in live
            }
        manifest_path = data / "runtime" / f"runtime_manifest.{name}.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_sources = manifest.get("config_sources") if isinstance(manifest, dict) else None
            if isinstance(raw_sources, dict):
                live_projection["config_sources"] = {
                    key: _safe_config_source_label(raw_sources[key])
                    for key in ("LLM_MODEL", "MODEL_PROVIDERS", "LLM_BASE_URL", "READ_PATH_SOURCE")
                    if isinstance(raw_sources.get(key), str)
                }
        except (OSError, ValueError, TypeError):
            pass
        services[str(name)] = {
            "live": live_projection,
            "stable_generation": stable.get("generation"),
            "stable_git_head": stable.get("git_head"),
            "stable_matches_desired_generation": stable.get("matches_desired_generation"),
            "restart_required": bool(item.get("restart_required")),
            "reasons": [str(reason) for reason in item.get("reasons", [])]
            if isinstance(item.get("reasons"), list) else [],
        }
    return {
        "available": True,
        "read_only": True,
        "desired_generation": deployment.get("generation"),
        "desired_git_head": deployment.get("git_head"),
        "services": services,
    }


def _last_actual_model(raw: dict) -> str | None:
    """Return the last persisted LoopResult.model_used, never a configured fallback."""
    messages = raw.get("messages", [])
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        model = str(message.get("model_used") or "").strip()
        if model:
            return model
    return None


def dispatch_query(argv: list[str], options: Any = None) -> int | None:
    if not argv or argv[0] not in READ_COMMANDS | {"list", "search"}:
        return None
    invoked_as = argv[0]
    cmd, rest = argv[0], argv[1:]
    cmd = {"session": "sessions", "model": "models", "status": "identity"}.get(cmd, cmd)
    if cmd == "models" and rest[:1] in (["list"], ["show"]):
        rest = rest[1:]
    if cmd in {"help", "keys"}:
        help_parser = argparse.ArgumentParser(prog=f"lfl {invoked_as}")
        try:
            help_parser.parse_args(rest)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 2
        print(HELP if cmd == "help" else KEY_HELP)
        return 0
    parser = argparse.ArgumentParser(prog=f"lfl {invoked_as}")
    parser.add_argument("--json", action="store_true")
    if cmd == "list":
        cmd, rest = "sessions", ["list", *rest]
    elif cmd == "search":
        cmd, rest = "sessions", ["search", *rest]
    if cmd == "sessions" and rest[:1] == ["search"]:
        # The old `search` command treated all remaining words as query text.
        # Preserve dash-leading terms while still recognizing supported flags
        # such as --json/--archived that appear before the free-text tail.
        known_flags = {"--json", "--archived", "--help", "-h"}
        for index, token in enumerate(rest[1:], start=1):
            if token == "--":
                break
            if token.startswith("-") and token not in known_flags:
                rest = [*rest[:index], "--", *rest[index:]]
                break
    if cmd == "sessions":
        parser.add_argument("action", choices=("list", "show", "search", "export"))
        # `search` historically accepted unquoted multi-word terms. Keep that
        # behavior for both `search ...` and the canonical `sessions search ...`.
        parser.add_argument("value", nargs="*")
        parser.add_argument("--archived", action="store_true")
        parser.add_argument("--raw", action="store_true")
        parser.add_argument("--to")
        parser.add_argument("--format", choices=("json", "markdown"), default=None)
    elif cmd == "identity":
        parser.add_argument("--session", help="Read the last actual model from this session's persisted LoopResult")
    elif cmd == "config":
        parser.add_argument("action", choices=("show",))
    try:
        ns = parser.parse_args(rest)
        if cmd == "sessions":
            values = ns.value if isinstance(ns.value, list) else ([ns.value] if ns.value else [])
            if ns.action == "list" and values:
                parser.error("sessions list does not accept a positional value")
            if ns.action in {"show", "export"} and len(values) != 1:
                parser.error(f"sessions {ns.action} requires exactly one session ID")
            if ns.action == "search" and not " ".join(values).strip():
                parser.error("sessions search requires a query")
            if ns.action == "export" and not ns.to:
                parser.error("sessions export requires --to FILE")
            if ns.action != "export" and ns.to:
                parser.error("--to is only valid with sessions export")
            if ns.action != "show" and ns.raw:
                parser.error("--raw is only valid with sessions show")
            if ns.action not in {"list", "search"} and ns.archived:
                parser.error("--archived is only valid with sessions list/search")
            if ns.action != "export" and ns.format is not None:
                parser.error("--format is only valid with sessions export")
        data, workspace, values = query_context(options)
        workspace_explicit = _normalize_workspace_value(getattr(options, "workspace", None)) is not None
        return _execute_query(cmd, ns, data, workspace, values, options=options,
                              workspace_explicit=workspace_explicit)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except WorkspaceAmbiguityError as exc:
        print(safe_text(
            f"workspace ambiguous: cwd-derived={exc.cwd_candidate} "
            f"deployment-bound={exc.bound_candidate}; "
            "pass --workspace PATH to choose one explicitly"
        ), file=sys.stderr)
        return 3
    except (OSError, ValueError, TypeError) as exc:
        print(safe_text(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1


def _execute_query(cmd: str, ns: Any, data: Path, workspace: Path, values: dict, *,
                   options: Any = None, workspace_explicit: bool = False) -> int:
    if cmd == "sessions":
        return _sessions(ns, data, workspace, values, workspace_explicit=workspace_explicit)
    if cmd in {"identity", "config"}:
        # Whitelist fields, never serialize Settings/env dictionaries or URL credentials.
        selected_session = getattr(ns, "session", None) if cmd == "identity" else None
        actual_model = None
        if selected_session:
            # Review fix P2-1 (T8 consistency): do not swallow workspace_lookup refusals
            # here. The multi-registry rejection message also contains the
            # "Workspace is not registered" substring, so the former base-root fallback
            # let identity --session through where sessions show/list refused. The
            # single-registry degradation already returns base from workspace_lookup
            # itself; multi-registry refusals propagate and exit 1 via dispatch_query,
            # matching the sessions branch.
            root = workspace_lookup(data, workspace, require_registered=workspace_explicit)[0]
            raw_session = read_session(
                data, selected_session, values.get("READ_PATH_SOURCE", "session_json"), root
            )
            actual_model = _last_actual_model(raw_session)
        config_sources = _config_source_report(options, values)
        runtime_identity = _runtime_identity_report(workspace)
        report = {
            "schema": "lfl.cli-identity/v2",
            "data_dir": str(data),
            "workspace": str(workspace),
            "configured_model": values.get("LLM_MODEL", ""),
            "configured_model_source": config_sources["configured_model_source"],
            "configuration": config_sources,
            "actual_model": actual_model,
            "actual_model_session": selected_session if actual_model else None,
            "actual_model_source": "LoopResult.model_used" if actual_model else None,
            "actual_model_note": (
                "Observed from persisted LoopResult.model_used for the selected session"
                if actual_model else
                f"No persisted assistant model_used was found for session {selected_session}"
                if selected_session else
                "Not observed: pass identity --session ID to inspect a persisted run; this query never runs a model"
            ),
            "read_path_source": values.get("READ_PATH_SOURCE", "session_json"),
            "runtime_identity": runtime_identity,
            "service_identity": _service_identity_report(data),
        }
    else:
        settings = Settings(llm_api_key="", llm_model=values.get("LLM_MODEL", ""),
                            llm_base_url=values.get("LLM_BASE_URL", ""),
                            model_providers_raw=values.get("MODEL_PROVIDERS", ""), data_dir=str(data))
        registry = load_registry(settings)
        report = {"schema": "lfl.cli-models/v1", "degraded": registry.degraded,
                  "configured_model": values.get("LLM_MODEL", ""),
                  "configured_model_source": _config_source_report(options, values)["configured_model_source"],
                  "models": [{"provider": pid, "model": mid, "context": model.context,
                              "multimodal": model.multimodal, "reasoning_capable": model.reasoning_capable}
                             for pid, provider in registry.providers.items()
                             for mid, model in provider.models.items()]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if ns.json else safe_text(json.dumps(report, ensure_ascii=False, indent=2)))
    return 0


def _sessions(ns: Any, data: Path, workspace: Path, values: dict, *,
              workspace_explicit: bool = False) -> int:
    root, degraded = workspace_lookup(data, workspace, require_registered=workspace_explicit)
    source = values.get("READ_PATH_SOURCE", "session_json")
    if ns.action in {"list", "search"}:
        if ns.action == "list" and ns.value:
            raise ValueError("sessions list does not accept a positional value")
        query = " ".join(ns.value) if isinstance(ns.value, list) else str(ns.value or "")
        if ns.action == "search" and not query.strip():
            raise ValueError("sessions search requires a query")
        rows = session_rows(data, archived=ns.archived, query=query if ns.action == "search" else "", root=root, source=source)
        print(json.dumps({"schema": "lfl.cli-sessions/v1", "degraded": degraded, "sessions": rows}, ensure_ascii=False, indent=2) if ns.json else safe_text("\n".join(
            f"{row['session_id']}  {row.get('title') or '(untitled)'}  "
            f"{row.get('message_count', '?')} messages {row.get('error', '')}" for row in rows)))
        return int(any("error" in row for row in rows))
    values_list = ns.value if isinstance(ns.value, list) else ([ns.value] if ns.value else [])
    if len(values_list) != 1 or not values_list[0]:
        raise ValueError("Session ID required")
    raw = read_session(data, values_list[0], source, root)
    if ns.action == "export":
        if not ns.to:
            raise ValueError("sessions export requires --to FILE")
        export_record(raw, Path(ns.to).expanduser(), ns.format or "json")
        return 0
    content = json.dumps(raw, ensure_ascii=False, indent=2) if ns.raw or ns.json else transcript(raw)
    print(content if ns.json else safe_text(content))
    return 0
