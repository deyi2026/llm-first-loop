"""Private, explicit-draft handoff for a CLI refused before Run admission.

A handoff is not a Run retry. The next process restores the draft to its
composer, and only a new human submit may turn it into a message.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.runtime.cli_admission import CliAdmissionBinding


@dataclass(frozen=True)
class CliReentry:
    session_id: str | None
    draft_path: Path | None
    workspace: str
    plain: bool = False
    theme: str | None = None
    model: str = ""


def _draft_root(data_dir: str | Path) -> Path:
    return Path(data_dir).resolve() / "runtime" / "cli-drafts"


def _check_private_dir(root: Path) -> None:
    info = root.lstat()
    if root.resolve() != root:
        raise ValueError("CLI draft directory must not cross a symbolic link")
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("CLI draft directory must be private and owned by the current user")


def save_cli_draft(data_dir: str | Path, session_id: str, draft: str, stashed: str) -> Path:
    root = _draft_root(data_dir)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    _check_private_dir(root)
    fd, name = tempfile.mkstemp(prefix="draft-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": "lfl.cli-draft/v1", "session_id": session_id,
                       "draft": draft, "stashed": stashed}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def load_cli_draft(data_dir: str | Path, path: str | Path, session_id: str) -> tuple[str, str]:
    root = _draft_root(data_dir)
    _check_private_dir(root)
    target = Path(path).expanduser()
    if target.parent.resolve() != root or not target.name.startswith("draft-") or target.suffix != ".json":
        raise ValueError("CLI draft path is outside its private data domain")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("CLI draft is not a private regular file")
        raw = json.load(handle)
    if (not isinstance(raw, dict) or raw.get("schema") != "lfl.cli-draft/v1"
            or raw.get("session_id") != session_id
            or not isinstance(raw.get("draft"), str) or not isinstance(raw.get("stashed"), str)):
        raise ValueError("CLI draft session or schema mismatch")
    return raw["draft"], raw["stashed"]


def reentry_argv(binding: CliAdmissionBinding, request: CliReentry) -> tuple[list[str], dict[str, str]]:
    """Plan only against a verified fixed release; new process rechecks admission."""
    from llm_loop.runtime.service_control import (
        ManagedServiceDeploymentStore,
        verify_deployment_binding,
    )

    store = ManagedServiceDeploymentStore(binding.data_dir)
    desired = store.read()
    if desired is None:
        raise ValueError("no managed target is published")
    # Do not loop or try to jump through an in-progress restart barrier.
    marker = f"{desired.deployment_id}:{desired.generation}"
    if os.environ.get("LFL_CLI_REENTRY_ATTEMPT") == marker:
        raise ValueError("automatic reentry already attempted for this generation")
    for service in ("web", "feishu", "learning", "wecom"):
        try:
            store.barriers.barrier_path(service).stat()
        except FileNotFoundError:
            continue
        raise ValueError("managed restart is still in progress")
    runtime = Path(desired.runtime_root).resolve()
    if Path(desired.data_dir or runtime / "data").resolve() != store.data_dir:
        raise ValueError("target data domain differs")
    if desired.artifact_kind == "source_checkout":
        code = Path(desired.code_root).resolve()
        if code != runtime / ".releases" / desired.git_head:
            raise ValueError("target is not a fixed release checkout")
        if not (code / "src/llm_loop/runtime/cli_reentry.py").is_file():
            raise ValueError("target does not support draft handoff")
        python = runtime / ".venv/bin/python"
        argv = [str(python), "-I", "-c",
                "import sys; sys.path.insert(0, sys.argv.pop(1)); from llm_loop.cli import application_main; raise SystemExit(application_main())",
                str(code / "src")]
    elif desired.artifact_kind == "wheel_release":
        code = runtime
        python = Path(desired.release_dir) / "venv/bin/python"
        argv = [str(python), "-I", "-c",
                "from llm_loop.cli import application_main; raise SystemExit(application_main())"]
    else:
        raise ValueError("unsupported managed artifact")
    if verify_deployment_binding(desired, code_root=code, runtime_root=runtime, verify_webui=False):
        raise ValueError("target artifact binding is not verified")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("target interpreter unavailable")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["LFL_RUNTIME_ROOT"] = str(runtime)
    env["LFL_CLI_REENTRY_ATTEMPT"] = marker
    argv.extend(["--data-dir", binding.data_dir, "--workspace", request.workspace])
    if env.get("LFL_ENV_FILE"):
        argv.extend(["--config", env["LFL_ENV_FILE"]])
    argv.extend(["chat", "--interactive"])
    if request.session_id:
        argv.extend(["--session", request.session_id])
    if request.draft_path is not None:
        if not request.session_id:
            raise ValueError("draft handoff requires the original session")
        load_cli_draft(binding.data_dir, request.draft_path, request.session_id)
        argv.extend(["--resume-draft", str(request.draft_path)])
    if request.model:
        argv.extend(["--model", request.model])
    if request.plain:
        argv.append("--plain")
    if request.theme:
        argv.extend(["--theme", request.theme])
    return argv, env


def attempt_cli_reentry(binding: CliAdmissionBinding, request: CliReentry) -> int:
    """Called only after Engine.close; a failed exec leaves the private draft intact."""
    try:
        argv, env = reentry_argv(binding, request)
        print("[CLI upgrade] Reopening the same session; draft requires explicit submit.", file=sys.stderr, flush=True)
        os.execve(argv[0], argv, env)
    except (OSError, ValueError, TypeError) as exc:
        detail = f". Draft retained: {request.draft_path}" if request.draft_path is not None else ""
        print(f"[CLI upgrade] Deferred ({type(exc).__name__}: {exc}){detail}", file=sys.stderr)
    return 75


def prepare_cli_reentry(engine: Any, session_id: str, draft: str, stashed: str) -> bool:
    from llm_loop.runtime.cli_admission import engine_cli_binding

    binding = engine_cli_binding(engine)
    if binding is None:
        return False
    path = save_cli_draft(binding.data_dir, session_id, draft, stashed)
    engine._cli_reentry = CliReentry(session_id, path, str(engine._cli_workspace),
                                     bool(engine._cli_plain), engine._cli_theme)
    return True
