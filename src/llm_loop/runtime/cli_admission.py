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
