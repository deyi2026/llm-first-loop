"""Mechanical shared-service lifecycle authority for LFL Web/Feishu.

This module deliberately separates three things:

* ``ManagedServiceDeployment`` is operator-published desired deployment identity.
  PID/process observations never create or change that authority.
* ``ManagedServiceMutationGuard`` is a narrow accident fence for generic shell
  execution.  It blocks known LFL shared-service lifecycle mutations and points
  callers at the dedicated ``service_control`` tool; it is not an OS sandbox.
* service-control actions are durable before a detached worker may execute the
  official restart script.  The worker derives code/runtime roots only from the
  desired deployment record, never from caller cwd or inherited business env.

The model still decides whether a restart is useful.  Program code owns only the
physical authority boundary and exact generation/root binding.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

_DEPLOYMENT_SCHEMA = "managed-service-deployment/v1"
_ACTION_SCHEMA = "service-control-action/v1"
_DEPLOYMENT_FIELDS = frozenset(
    {
        "schema",
        "deployment_id",
        "generation",
        "git_head",
        "code_root",
        "runtime_root",
        "webui_artifact_sha256",
    }
)
_ACTION_FIELDS = frozenset(
    {
        "schema",
        "action_id",
        "action",
        "target",
        "deployment_id",
        "deployment_generation",
        "requester_session_id",
        "status",
        "created_at",
        "updated_at",
        "detail",
    }
)
_MANAGED_SERVICES = ("web", "feishu")
_ACTION_TARGETS = ("web", "feishu", "all")


class DeploymentGenerationConflictError(RuntimeError):
    """Desired deployment changed since the caller observed it."""


@dataclass(frozen=True)
class ManagedServiceDeployment:
    schema: str
    deployment_id: str
    generation: int
    git_head: str
    code_root: str
    runtime_root: str
    webui_artifact_sha256: str

    def __post_init__(self) -> None:
        if self.schema != _DEPLOYMENT_SCHEMA:
            raise ValueError(f"unsupported deployment schema: {self.schema!r}")
        if not self.deployment_id.strip():
            raise ValueError("deployment_id must be non-empty")
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        if not re.fullmatch(r"[0-9a-f]{40}", self.git_head):
            raise ValueError("git_head must be an exact 40-char lowercase SHA")
        for label, raw in (("code_root", self.code_root), ("runtime_root", self.runtime_root)):
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise ValueError(f"{label} must be absolute")
        if not re.fullmatch(r"[0-9a-f]{64}", self.webui_artifact_sha256):
            raise ValueError("webui_artifact_sha256 must be sha256 hex")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ManagedServiceDeployment:
        keys = frozenset(raw)
        unknown = sorted(keys - _DEPLOYMENT_FIELDS)
        missing = sorted(_DEPLOYMENT_FIELDS - keys)
        if unknown:
            raise ValueError(f"deployment unknown fields: {unknown}")
        if missing:
            raise ValueError(f"deployment missing fields: {missing}")
        return cls(
            schema=str(raw["schema"]),
            deployment_id=str(raw["deployment_id"]),
            generation=int(raw["generation"]),
            git_head=str(raw["git_head"]),
            code_root=str(raw["code_root"]),
            runtime_root=str(raw["runtime_root"]),
            webui_artifact_sha256=str(raw["webui_artifact_sha256"]),
        )


@dataclass(frozen=True)
class ServiceControlAction:
    schema: str
    action_id: str
    action: Literal["restart"]
    target: Literal["web", "feishu", "all"]
    deployment_id: str
    deployment_generation: int
    requester_session_id: str
    status: Literal["accepted", "running", "succeeded", "failed"]
    created_at: str
    updated_at: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.schema != _ACTION_SCHEMA:
            raise ValueError(f"unsupported action schema: {self.schema!r}")
        if not self.action_id.strip():
            raise ValueError("action_id must be non-empty")
        if self.action != "restart":
            raise ValueError("P0-A only supports restart")
        if self.target not in _ACTION_TARGETS:
            raise ValueError(f"unsupported target: {self.target}")
        if self.deployment_generation < 1:
            raise ValueError("deployment_generation must be positive")
        if self.status not in {"accepted", "running", "succeeded", "failed"}:
            raise ValueError(f"invalid action status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ServiceControlAction:
        keys = frozenset(raw)
        unknown = sorted(keys - _ACTION_FIELDS)
        missing = sorted(_ACTION_FIELDS - keys)
        if unknown:
            raise ValueError(f"action unknown fields: {unknown}")
        if missing:
            raise ValueError(f"action missing fields: {missing}")
        return cls(
            schema=str(raw["schema"]),
            action_id=str(raw["action_id"]),
            action=str(raw["action"]),  # type: ignore[arg-type]
            target=str(raw["target"]),  # type: ignore[arg-type]
            deployment_id=str(raw["deployment_id"]),
            deployment_generation=int(raw["deployment_generation"]),
            requester_session_id=str(raw["requester_session_id"]),
            status=str(raw["status"]),  # type: ignore[arg-type]
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            detail=str(raw["detail"]),
        )


@dataclass(frozen=True)
class ManagedServiceGuardDecision:
    blocked: bool
    reason: str
    services: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestartPlan:
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class ManagedServiceDeploymentStore:
    """Closed-schema desired deployment + durable action receipts.

    ``service-control.lock`` is a cross-process mechanical lease.  It serializes
    desired-state CAS and action acceptance; observing a PID never grants this lease.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.runtime_dir = self.data_dir / "runtime"
        self.path = self.runtime_dir / "managed_service_deployment.json"
        self.lock_path = self.runtime_dir / "service-control-state.lock"
        self.lifecycle_lock_path = self.runtime_dir / "service-control.lock"
        self.actions_dir = self.runtime_dir / "service-control-actions"

    @contextmanager
    def lease(self) -> Iterator[None]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError as exc:  # pragma: no cover - production/CI are POSIX
                raise RuntimeError("service control requires POSIX fcntl locking") from exc
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def lifecycle_lease(self) -> Iterator[None]:
        """Serialize physical lifecycle execution against desired deployment publish."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with self.lifecycle_lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError as exc:  # pragma: no cover - production/CI are POSIX
                raise RuntimeError("service control requires POSIX fcntl locking") from exc
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> ManagedServiceDeployment | None:
        # Writers publish with tmp+rename, so readers can consume the immutable
        # snapshot without creating/acquiring a lock.  Missing-state observation
        # is therefore physically read-only.  A concurrent initial rename may
        # race the existence check; in that case report the same missing fact.
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        raw = json.loads(raw_text)
        if not isinstance(raw, dict):
            raise ValueError("managed service deployment must be a JSON object")
        return ManagedServiceDeployment.from_dict(raw)

    def read(self) -> ManagedServiceDeployment | None:
        return self._read_unlocked()

    def compare_and_swap(
        self,
        deployment: ManagedServiceDeployment,
        *,
        expected_generation: int,
    ) -> None:
        if expected_generation < 0:
            raise ValueError("expected_generation must be >= 0")
        # Publishing a new desired deployment must not race a physical restart.
        # Lock order is always lifecycle -> state.
        with self.lifecycle_lease(), self.lease():
            current = self._read_unlocked()
            current_generation = current.generation if current is not None else 0
            if current_generation != expected_generation:
                raise DeploymentGenerationConflictError(
                    f"deployment generation changed: expected={expected_generation} current={current_generation}"
                )
            if deployment.generation != expected_generation + 1:
                raise ValueError(
                    "next deployment generation must equal expected_generation + 1 "
                    f"(next={deployment.generation}, expected={expected_generation})"
                )
            _atomic_json(self.path, deployment.to_dict())

    def action_path(self, action_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", action_id):
            raise ValueError("invalid action_id")
        return self.actions_dir / f"{action_id}.json"

    def read_action(self, action_id: str) -> ServiceControlAction | None:
        path = self.action_path(action_id)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("service control action must be a JSON object")
        return ServiceControlAction.from_dict(raw)

    def _write_action_unlocked(self, action: ServiceControlAction) -> None:
        _atomic_json(self.action_path(action.action_id), action.to_dict())

    def update_action(
        self,
        action_id: str,
        *,
        status: Literal["accepted", "running", "succeeded", "failed"],
        detail: str = "",
    ) -> ServiceControlAction:
        with self.lease():
            action = self.read_action(action_id)
            if action is None:
                raise FileNotFoundError(action_id)
            updated = dataclasses.replace(
                action,
                status=status,
                updated_at=_utc_now(),
                detail=str(detail or "")[:2000],
            )
            self._write_action_unlocked(updated)
            return updated

    def accept_restart(
        self,
        *,
        target: str,
        expected_generation: int,
        requester_session_id: str,
    ) -> ServiceControlAction:
        if target not in _ACTION_TARGETS:
            raise ValueError(f"unsupported restart target: {target}")
        with self.lease():
            deployment = self._read_unlocked()
            if deployment is None:
                raise DeploymentGenerationConflictError("managed service deployment is not published")
            if deployment.generation != expected_generation:
                raise DeploymentGenerationConflictError(
                    f"deployment generation changed: expected={expected_generation} "
                    f"current={deployment.generation}"
                )
            now = _utc_now()
            action = ServiceControlAction(
                schema=_ACTION_SCHEMA,
                action_id=f"svc-{uuid.uuid4().hex}",
                action="restart",
                target=target,  # type: ignore[arg-type]
                deployment_id=deployment.deployment_id,
                deployment_generation=deployment.generation,
                requester_session_id=str(requester_session_id or ""),
                status="accepted",
                created_at=now,
                updated_at=now,
                detail="",
            )
            self._write_action_unlocked(action)
            return action


def _read_process_command(pid: int) -> str:
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _service_command_matches(service: str, command: str) -> bool:
    if not command:
        return False
    return (
        f"llm_loop.runtime.launch {service}" in command
        or f"-m llm_loop.{service}" in command
    )


def _shell_segments(command: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"&&|\|\||;|\|", command) if segment.strip()]


def _kill_signal_is_probe(tokens: list[str]) -> bool:
    # ``kill -0 PID`` / ``kill -s 0 PID`` are liveness observations, not mutation.
    if "-0" in tokens:
        return True
    for idx, token in enumerate(tokens[:-1]):
        if token in {"-s", "--signal"} and tokens[idx + 1] == "0":
            return True
    return False


class ManagedServiceMutationGuard:
    """Narrow tool-layer fence around LFL shared-service lifecycle mutations."""

    _PID_SOURCE_MARKERS = (
        "runtime_manifest.web.json",
        "runtime_manifest.feishu.json",
        "feishu_heartbeat.json",
    )

    def __init__(
        self,
        data_dir: str | Path,
        *,
        process_command_reader: Callable[[int], str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self._process_command_reader = process_command_reader or _read_process_command

    def _live_managed_pids(self) -> dict[int, str]:
        out: dict[int, str] = {}
        runtime = self.data_dir / "runtime"
        for service in _MANAGED_SERVICES:
            path = runtime / f"runtime_manifest.{service}.json"
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("service") != service:
                    continue
                pid = int(raw.get("pid") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if pid <= 0:
                continue
            command = str(self._process_command_reader(pid) or "")
            if _service_command_matches(service, command):
                out[pid] = service
        return out

    @staticmethod
    def _tokens(segment: str) -> list[str]:
        try:
            return shlex.split(segment, posix=True)
        except ValueError:
            return segment.split()

    @staticmethod
    def _core_tokens(tokens: list[str]) -> list[str]:
        """Strip leading env assignments without interpreting shell semantics."""
        if not tokens:
            return []
        idx = 0
        if Path(tokens[0]).name == "env":
            idx = 1
            while idx < len(tokens) and (tokens[idx].startswith("-") or "=" in tokens[idx]):
                idx += 1
        else:
            while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith("="):
                key, _, _value = tokens[idx].partition("=")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    break
                idx += 1
        return tokens[idx:]

    @staticmethod
    def _unwrap_process_prefix(core: list[str]) -> list[str]:
        """Remove non-semantic process wrappers used around an executable."""
        out = list(core)
        while out and Path(out[0]).name in {"nohup", "command"}:
            out = out[1:]
        return out

    @classmethod
    def _direct_launch_service(cls, core: list[str]) -> str:
        tokens = cls._unwrap_process_prefix(core)
        if len(tokens) < 4:
            return ""
        exe = Path(tokens[0]).name
        if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", exe):
            return ""
        if tokens[1:3] != ["-m", "llm_loop.runtime.launch"]:
            return ""
        service = tokens[3]
        return service if service in _MANAGED_SERVICES else ""

    @classmethod
    def _operator_control_cli(cls, core: list[str]) -> bool:
        tokens = cls._unwrap_process_prefix(core)
        if len(tokens) < 4:
            return False
        exe = Path(tokens[0]).name
        return (
            bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", exe))
            and tokens[1:3] == ["-m", "llm_loop.runtime.service_control"]
            and tokens[3] in {"publish", "worker"}
        )

    @staticmethod
    def _restart_script_mutation(core: list[str]) -> bool:
        if not core:
            return False
        exe = Path(core[0]).name
        script_idx = 0
        if exe in {"bash", "sh", "zsh"}:
            if len(core) < 2 or core[1] == "-c":
                return False
            script_idx = 1
        script = Path(core[script_idx]).name
        if script not in {"restart_mirror.sh", "restart_system.sh", "restart_feishu.sh"}:
            return False
        action_idx = script_idx + 1
        if action_idx >= len(core):
            # restart_mirror default is a real Web restart, so an omitted action mutates.
            return script == "restart_mirror.sh"
        return core[action_idx] in {"web", "feishu", "all", "restart", "start", "stop"}

    def _guard_text(
        self,
        text: str,
        managed: Mapping[int, str],
        *,
        depth: int,
    ) -> ManagedServiceGuardDecision | None:
        if depth > 2:
            return None
        segments = _shell_segments(text)
        for segment in segments:
            tokens = self._tokens(segment)
            core = self._core_tokens(tokens)
            if not core:
                continue
            exe = Path(core[0]).name

            if self._restart_script_mutation(core):
                return ManagedServiceGuardDecision(
                    True,
                    "shared Web/Feishu lifecycle must use service_control; generic shell restart is not authoritative",
                    _MANAGED_SERVICES,
                )

            launch_service = self._direct_launch_service(core)
            if launch_service and "--dry-run" not in core:
                return ManagedServiceGuardDecision(
                    True,
                    "direct shared-service launch is not authoritative; use service_control/official deployment",
                    (launch_service,),
                )
            if self._operator_control_cli(core):
                return ManagedServiceGuardDecision(
                    True,
                    "service-control publish/worker is operator control-plane only; model calls use service_control",
                    _MANAGED_SERVICES,
                )

            if exe in {"bash", "sh", "zsh"} and "-c" in core and depth < 2:
                idx = core.index("-c")
                if idx + 1 < len(core):
                    nested = self._guard_text(core[idx + 1], managed, depth=depth + 1)
                    if nested is not None:
                        return nested

            if not managed:
                continue
            hit: set[str] = set()
            if exe == "kill" and not _kill_signal_is_probe(core):
                for token in core[1:]:
                    if token.isdigit() and int(token) in managed:
                        hit.add(managed[int(token)])
                low = segment.lower()
                for marker in self._PID_SOURCE_MARKERS:
                    if marker in low:
                        if ".web." in marker:
                            hit.add("web")
                        elif ".feishu." in marker or "feishu_" in marker:
                            hit.add("feishu")
                if "lsof" in low and "8903" in low:
                    hit.add("web")
                # kill -SIGNAL -1 targets every process the caller may signal.
                if re.search(r"(?:^|\s)-1(?:\s|$)", segment):
                    hit.update(managed.values())
            elif exe in {"pkill", "killall"}:
                if _kill_signal_is_probe(core):
                    continue
                low = " ".join(core[1:]).lower()
                if "llm_loop.runtime.launch" in low and not any(
                    service in low for service in _MANAGED_SERVICES
                ):
                    hit.update(managed.values())
                for service in _MANAGED_SERVICES:
                    if ("llm_loop" in low or "runtime.launch" in low) and service in low:
                        hit.add(service)
                # Broad Python process kills necessarily include live managed Python services.
                if re.search(r"(?:^|\s)(?:python|python3|python3\.\d+)(?:\s|$)", low):
                    hit.update(managed.values())
            elif exe.startswith("python") and "os.kill" in segment:
                for pid, service in managed.items():
                    match = re.search(rf"os\.kill\(\s*{pid}\s*,\s*([^\)]+)\)", segment)
                    if match and match.group(1).strip() not in {"0", "signal.SIG_0"}:
                        hit.add(service)
            if hit:
                return ManagedServiceGuardDecision(
                    True,
                    "managed shared-service PID mutation is fenced; use service_control with observed deployment generation",
                    tuple(sorted(hit)),
                )
        return None

    def guard(self, command: str) -> ManagedServiceGuardDecision | None:
        text = str(command or "").strip()
        if not text:
            return None
        return self._guard_text(text, self._live_managed_pids(), depth=0)


def _control_subprocess_env(
    *,
    code_root: str,
    runtime_root: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a deterministic minimal environment for lifecycle-control children.

    Do not inherit the caller/Web process environment: provider keys, credentials,
    FORCE flags, stale config anchors, and sandbox HOME/TMPDIR are not lifecycle
    authority. The official restart script reconstructs service HOME/TMPDIR and
    business configuration from canonical roots.
    """
    account_home = pwd.getpwuid(os.getuid()).pw_dir
    env = {
        "HOME": account_home,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LFL_WORKSPACE_ROOT": code_root,
        "LFL_RUNTIME_ROOT": runtime_root,
        "PYTHONPATH": str(Path(code_root) / "src"),
    }
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def build_restart_plan(
    action: ServiceControlAction,
    deployment: ManagedServiceDeployment,
) -> RestartPlan:
    if action.action != "restart":
        raise ValueError(f"unsupported action: {action.action}")
    if action.deployment_id != deployment.deployment_id:
        raise DeploymentGenerationConflictError("action deployment_id no longer matches desired deployment")
    if action.deployment_generation != deployment.generation:
        raise DeploymentGenerationConflictError("action deployment generation is stale")
    script = Path(deployment.code_root) / "scripts" / "restart_mirror.sh"
    return RestartPlan(
        argv=("/bin/bash", str(script), action.target),
        cwd=deployment.runtime_root,
        env={
            "LFL_RESTART_CODE_ROOT": deployment.code_root,
            "LFL_RESTART_RUNTIME_ROOT": deployment.runtime_root,
            "RESTART_WAIT_IDLE": "1",
        },
    )


def _control_code_root() -> Path:
    """Return the code root that owns this controller implementation.

    The controller must survive a rollback to a pre-P0-A physical target.  Its
    import identity is therefore the currently executing control-plane code, not
    the desired deployment target that restart_mirror will later operate on.
    """
    return Path(__file__).resolve().parents[3]


def spawn_service_control_worker(store: ManagedServiceDeploymentStore, action_id: str) -> None:
    action = store.read_action(action_id)
    deployment = store.read()
    if action is None or deployment is None:
        raise RuntimeError("service-control action/deployment missing before worker spawn")
    build_restart_plan(action, deployment)  # stale binding fails before spawn
    log_path = Path(deployment.runtime_root) / "data" / "service-control-worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    controller_root = _control_code_root()
    env = _control_subprocess_env(
        code_root=str(controller_root),
        runtime_root=deployment.runtime_root,
    )
    stream = log_path.open("a", encoding="utf-8")
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "llm_loop.runtime.service_control",
                "worker",
                "--data-dir",
                str(store.data_dir),
                "--action-id",
                action_id,
            ],
            cwd=deployment.runtime_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        stream.close()


def _prepare_action_for_worker(
    store: ManagedServiceDeploymentStore,
    action_id: str,
) -> tuple[ServiceControlAction | None, RestartPlan | None, int]:
    """Under the short state lock, bind an accepted action to current desired state."""
    with store.lease():
        action = store.read_action(action_id)
        deployment = store._read_unlocked()
        if action is None or deployment is None:
            return None, None, 2
        try:
            plan = build_restart_plan(action, deployment)
        except (ValueError, DeploymentGenerationConflictError) as exc:
            failed = dataclasses.replace(
                action,
                status="failed",
                updated_at=_utc_now(),
                detail=str(exc),
            )
            store._write_action_unlocked(failed)
            return failed, None, 3
        running = dataclasses.replace(
            action, status="running", updated_at=_utc_now(), detail=""
        )
        store._write_action_unlocked(running)
        return running, plan, 0


def run_action_worker(store: ManagedServiceDeploymentStore, action_id: str) -> int:
    # Hold the global lifecycle lease through the physical restart. Desired-state
    # publication acquires the same lease, closing check->execute TOCTOU. The short
    # state-file lock is released before invoking restart_mirror so its read-only
    # binding preflight can inspect the atomic desired-state file.
    with store.lifecycle_lease():
        running, plan, prepare_rc = _prepare_action_for_worker(store, action_id)
        if prepare_rc != 0 or running is None or plan is None:
            return prepare_rc

        deployment = store.read()
        if deployment is None:
            store.update_action(
                action_id,
                status="failed",
                detail="deployment binding failed: desired deployment disappeared",
            )
            return 4
        problems = verify_deployment_binding(
            deployment,
            code_root=deployment.code_root,
            runtime_root=deployment.runtime_root,
            verify_webui=(running.target != "feishu"),
        )
        if problems:
            store.update_action(
                action_id,
                status="failed",
                detail="deployment binding failed: " + "; ".join(problems),
            )
            return 4

        env = _control_subprocess_env(
            code_root=plan.env["LFL_RESTART_CODE_ROOT"],
            runtime_root=plan.env["LFL_RESTART_RUNTIME_ROOT"],
            extra=plan.env,
        )
        proc = subprocess.run(  # noqa: S603 - desired-state-bound fixed argv, no shell
            list(plan.argv),
            cwd=plan.cwd,
            env=env,
            check=False,
        )
        with store.lease():
            terminal = dataclasses.replace(
                running,
                status="succeeded" if proc.returncode == 0 else "failed",
                updated_at=_utc_now(),
                detail=(
                    "restart_mirror rc=0"
                    if proc.returncode == 0
                    else f"restart_mirror rc={proc.returncode}"
                ),
            )
            store._write_action_unlocked(terminal)
        return 0 if proc.returncode == 0 else int(proc.returncode or 1)


def _tree_sha256(root: Path) -> str:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"WebUI artifact tree is empty: {root}")
    h = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        blob = path.read_bytes()
        h.update(len(rel).to_bytes(8, "big"))
        h.update(rel)
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    return h.hexdigest()


def verify_deployment_binding(
    deployment: ManagedServiceDeployment,
    *,
    code_root: str | Path,
    runtime_root: str | Path,
    verify_webui: bool = True,
) -> list[str]:
    """Return exact desired-vs-physical binding mismatches; empty means qualified."""
    code = Path(code_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    problems: list[str] = []
    if str(code) != deployment.code_root:
        problems.append(f"code_root mismatch desired={deployment.code_root} actual={code}")
    if str(runtime) != deployment.runtime_root:
        problems.append(f"runtime_root mismatch desired={deployment.runtime_root} actual={runtime}")
    try:
        head = subprocess.run(
            ["git", "-C", str(code), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"git_head unavailable: {type(exc).__name__}")
        head = ""
    if head and head != deployment.git_head:
        problems.append(f"git_head mismatch desired={deployment.git_head} actual={head}")
    try:
        dirty = subprocess.run(
            ["git", "-C", str(code), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if dirty:
            problems.append("code_root tracked worktree is dirty")
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"git_status unavailable: {type(exc).__name__}")
    if verify_webui:
        try:
            artifact = _tree_sha256(code / "webui" / "dist")
        except (OSError, ValueError) as exc:
            problems.append(f"webui artifact unavailable: {exc}")
        else:
            if artifact != deployment.webui_artifact_sha256:
                problems.append(
                    "webui artifact mismatch "
                    f"desired={deployment.webui_artifact_sha256} actual={artifact}"
                )
    return problems


def build_deployment(
    *,
    code_root: str | Path,
    runtime_root: str | Path,
    generation: int,
) -> ManagedServiceDeployment:
    code = Path(code_root).expanduser().resolve()
    runtime = Path(runtime_root).expanduser().resolve()
    if not code.is_dir() or not runtime.is_dir():
        raise ValueError("code_root/runtime_root must exist")
    head = subprocess.run(
        ["git", "-C", str(code), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(code), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    if dirty:
        raise ValueError("code_root tracked worktree must be clean before publish")
    artifact = _tree_sha256(code / "webui" / "dist")
    return ManagedServiceDeployment(
        schema=_DEPLOYMENT_SCHEMA,
        deployment_id=f"deploy-{uuid.uuid4().hex}",
        generation=generation,
        git_head=head,
        code_root=str(code),
        runtime_root=str(runtime),
        webui_artifact_sha256=artifact,
    )


def _default_data_dir(runtime_root: Path) -> Path:
    return runtime_root / "data"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_loop.runtime.service_control")
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish")
    publish.add_argument("--expected-generation", type=int, required=True)
    publish.add_argument("--code-root", required=True)
    publish.add_argument("--runtime-root", required=True)
    publish.add_argument("--data-dir")

    show = sub.add_parser("show")
    show.add_argument("--data-dir", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--data-dir", required=True)
    verify.add_argument("--code-root", required=True)
    verify.add_argument("--runtime-root", required=True)
    verify.add_argument("--skip-webui", action="store_true")

    worker = sub.add_parser("worker")
    worker.add_argument("--data-dir", required=True)
    worker.add_argument("--action-id", required=True)

    args = parser.parse_args(argv)
    if args.command == "publish":
        runtime = Path(args.runtime_root).expanduser().resolve()
        data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else _default_data_dir(runtime)
        store = ManagedServiceDeploymentStore(data_dir)
        deployment = build_deployment(
            code_root=args.code_root,
            runtime_root=runtime,
            generation=args.expected_generation + 1,
        )
        store.compare_and_swap(deployment, expected_generation=args.expected_generation)
        print(json.dumps(deployment.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "show":
        deployment = ManagedServiceDeploymentStore(args.data_dir).read()
        print(json.dumps(deployment.to_dict() if deployment else {}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "verify":
        deployment = ManagedServiceDeploymentStore(args.data_dir).read()
        if deployment is None:
            print("managed service deployment is not published", file=sys.stderr)
            return 4
        problems = verify_deployment_binding(
            deployment,
            code_root=args.code_root,
            runtime_root=args.runtime_root,
            verify_webui=not bool(args.skip_webui),
        )
        if problems:
            print(json.dumps({"ok": False, "problems": problems}, ensure_ascii=False), file=sys.stderr)
            return 5
        print(json.dumps({"ok": True, "generation": deployment.generation}, ensure_ascii=False))
        return 0
    if args.command == "worker":
        return run_action_worker(ManagedServiceDeploymentStore(args.data_dir), args.action_id)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
