"""Live CLI identity records, witnessed by a process-owned flock.

A stale file or reused PID is not live evidence. Readers never create files or
acquire a long-lived lock; the record disappears on normal close/exec.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llm_loop.runtime.cli_deployment_identity import (
    StartupArtifactIdentity,
    compare_startup_artifact,
)

if TYPE_CHECKING:
    from llm_loop.runtime.cli_admission import CliAdmissionBinding
    from llm_loop.runtime.service_control import ManagedServiceDeployment


def _root(data_dir: str | Path) -> Path:
    return Path(data_dir).resolve() / "runtime" / "cli-processes"


@contextmanager
def register_cli_process(binding: CliAdmissionBinding | None) -> Iterator[None]:
    if binding is None or binding.generation is None:
        yield
        return
    import fcntl

    root = _root(binding.data_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.resolve() != root or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError("CLI process registry must be private and owned by the current user")
    fd, name = tempfile.mkstemp(prefix=f"cli-{os.getpid()}-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                json.dump({"schema": "lfl.cli-process/v1", "binding": asdict(binding)}, handle)
                handle.flush()
                os.fsync(handle.fileno())
                yield
            finally:
                Path(name).unlink(missing_ok=True)
    finally:
        Path(name).unlink(missing_ok=True)


def cli_process_view(data_dir: str | Path, desired: ManagedServiceDeployment | None) -> dict[str, Any]:
    root = _root(data_dir)
    rows: list[dict[str, Any]] = []
    uncertain = 0
    try:
        import fcntl

        paths = sorted(path for path in root.iterdir() if path.match("cli-*.json"))
    except FileNotFoundError:
        paths = []
    except (ImportError, OSError):
        return {"state": "unverified", "processes": [], "uncertain": 1,
                "coverage": "registered_cli_processes_only"}
    for path in paths:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raw = json.load(handle)
                else:
                    # No live owner: crash residue, not a running CLI.
                    continue
            if not isinstance(raw, dict) or raw.get("schema") != "lfl.cli-process/v1":
                raise ValueError("invalid CLI process schema")
            binding = raw["binding"]
            startup = StartupArtifactIdentity(**binding["startup"])
            if binding["data_dir"] != str(Path(data_dir).resolve()):
                raise ValueError("wrong CLI data domain")
            view = compare_startup_artifact(startup, desired)
            if desired is not None and (binding["deployment_id"], binding["generation"]) != (
                desired.deployment_id, desired.generation,
            ):
                view["state"], view["reason"] = "update_required", "deployment_generation_changed"
            rows.append({"pid": startup.pid, "generation": binding["generation"],
                         "artifact_kind": startup.artifact_kind, "git_head": startup.git_head,
                         "version": startup.version, "wheel_sha256": startup.wheel_sha256,
                         "state": view["state"], "reason": view["reason"]})
        except FileNotFoundError:
            continue  # process closed during read
        except (OSError, ValueError, TypeError, KeyError):
            uncertain += 1
    state = "not_running"
    if uncertain or any(row["state"] == "unverified" for row in rows):
        state = "unverified"
    elif any(row["state"] == "update_required" for row in rows):
        state = "update_required"
    elif rows:
        state = "identity_matches_target"
    return {"state": state, "processes": rows, "uncertain": uncertain,
            "coverage": "registered_cli_processes_only"}
