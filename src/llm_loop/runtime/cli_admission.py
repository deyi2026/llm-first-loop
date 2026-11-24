"""Bind CLI mutation admission to the existing deployment state lease.

The state lease covers only the check and acquisition of a whole-run lease
(or a short local mutation). Never hold it during a model call or user input.
The existing restart barrier is established under the same state lease.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.runtime.cli_deployment_identity import (
    StartupArtifactIdentity,
    compare_startup_artifact,
)


class CliDeploymentAdmissionError(RuntimeError):
    """The operation was refused before acquiring Run ownership."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"CLI deployment admission refused: {reason}; no new Run was admitted")


@dataclass(frozen=True)
class CliAdmissionBinding:
    data_dir: str
    startup: StartupArtifactIdentity
    deployment_id: str | None
    generation: int | None


def bind_cli_startup(data_dir: str | Path, startup: StartupArtifactIdentity) -> CliAdmissionBinding:
    from llm_loop.runtime.service_control import ManagedServiceDeploymentStore

    store = ManagedServiceDeploymentStore(data_dir)
    try:
        desired = store.read()
    except (OSError, ValueError, TypeError) as exc:
        raise CliDeploymentAdmissionError("deployment_record_unreadable") from exc
    return CliAdmissionBinding(str(store.data_dir), startup,
                               desired.deployment_id if desired else None,
                               desired.generation if desired else None)


def cli_deployment_identity_view(
    data_dir: str | Path, startup: StartupArtifactIdentity | None = None,
) -> dict[str, Any]:
    """Read the existing deployment Store; never create a lock or state file.

    Lives beside bind_cli_startup (the other Store reader) so that
    cli_deployment_identity stays a leaf module: R9-P2-06a forbids a runtime
    import cycle between service_control, cli_processes and cli_deployment_identity.
    """
    from llm_loop.runtime.cli_deployment_identity import capture_startup_artifact
    from llm_loop.runtime.service_control import ManagedServiceDeploymentStore

    startup = startup if startup is not None else capture_startup_artifact()
    try:
        desired = ManagedServiceDeploymentStore(data_dir).read()
    except (OSError, ValueError, TypeError):
        result = compare_startup_artifact(startup, None)
        result["reason"] = "deployment_record_unreadable"
        return result
    return compare_startup_artifact(startup, desired)


@contextmanager
def cli_state_admission(binding: CliAdmissionBinding | None) -> Iterator[None]:
    """Check under the same lock as publish/restart acceptance.

    No binding is used by non-CLI engines and injected test adapters. An
    explicitly bound independent data domain without a deployment is allowed,
    but a later publication invalidates that process's startup binding.
    """
    if binding is None:
        yield
        return
    from llm_loop.runtime.service_control import ManagedServiceDeploymentStore

    store = ManagedServiceDeploymentStore(binding.data_dir)
    with ExitStack() as stack:
        try:
            stack.enter_context(store.lease())
            desired = store.read()
            if desired is None:
                if binding.generation is not None:
                    raise CliDeploymentAdmissionError("deployment_record_disappeared")
            else:
                if (desired.deployment_id, desired.generation) != (binding.deployment_id, binding.generation):
                    raise CliDeploymentAdmissionError("deployment_generation_changed")
                expected_data = Path(desired.data_dir or (Path(desired.runtime_root) / "data")).resolve()
                if expected_data != store.data_dir:
                    raise CliDeploymentAdmissionError("deployment_data_domain_mismatch")
                identity = compare_startup_artifact(binding.startup, desired)
                if identity["state"] != "identity_matches_target":
                    raise CliDeploymentAdmissionError(str(identity["reason"]))
                # Existing all-restart establishes all four service barriers.
                # A single-service restart also fences CLI writes conservatively
                # while it may share the managed data and code domain.
                for service in ("web", "feishu", "learning", "wecom"):
                    try:
                        store.barriers.barrier_path(service).stat()
                    except FileNotFoundError:
                        continue
                    # A present but unreadable barrier is not permission.
                    raise CliDeploymentAdmissionError(f"service_restart_barrier:{service}")
        except (OSError, ValueError, TypeError) as exc:
            raise CliDeploymentAdmissionError("deployment_admission_unavailable") from exc
        yield


def engine_cli_binding(engine: Any) -> CliAdmissionBinding | None:
    binding = getattr(engine, "_cli_admission_binding", None)
    return binding if isinstance(binding, CliAdmissionBinding) else None


@contextmanager
def cli_mutation_lease(binding: CliAdmissionBinding | None) -> Iterator[None]:
    """Long legacy mutations own a drain-visible lease, not the state lock."""
    if binding is None:
        yield
        return
    import fcntl
    import os
    import tempfile

    with ExitStack() as stack:
        with cli_state_admission(binding):
            root = Path(binding.data_dir) / "runtime" / "cli-mutations"
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if root.resolve() != root or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
                raise CliDeploymentAdmissionError("mutation_registry_unavailable")
            fd, name = tempfile.mkstemp(prefix="cli-", suffix=".run.lock", dir=root)
            handle = stack.enter_context(os.fdopen(fd, "w"))
            stack.callback(Path(name).unlink, missing_ok=True)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
