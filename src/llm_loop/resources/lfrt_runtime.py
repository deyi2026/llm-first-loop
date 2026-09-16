"""Read-only LFRT observation boundary.

R1 intentionally does not participate in Resource Governor admission yet.  It
invokes exactly one fixed LFRT command (``status --json``), validates the
mechanical runtime facts, and projects them into an immutable snapshot.  Any
execution, JSON, identity, or required-field uncertainty returns ``None``;
callers must never infer capacity from a partial observation.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.resources.contracts import ObservedResourceState, RuntimeType
from llm_loop.resources.local_runtime import LocalRuntimeIdentityObservation

CommandRunner = Callable[[tuple[str, ...], float], tuple[int, str, str]]


@dataclass(frozen=True)
class LFRTStatusSnapshot:
    """Mechanically validated facts from one LFRT ``status --json`` sample."""

    observed_at: float
    source_ref: str
    listener_pid: int
    process_pid: int
    launchd_pid: int
    launchd_state: str
    port: int
    model_identity: str
    model_path: str
    live_prompt_concurrency: int
    live_decode_concurrency: int
    configured_prompt_concurrency: int
    configured_decode_concurrency: int
    endpoint_healthy: bool
    aliases: tuple[str, ...]
    drift: bool

    @property
    def max_concurrency(self) -> int:
        """Conservative capacity from live process flags, never config intent."""

        return min(self.live_prompt_concurrency, self.live_decode_concurrency)


@dataclass(frozen=True)
class LFRTShadowParityReport:
    """Read-only comparison with the existing RG-2 observer."""

    status: str
    mismatches: tuple[str, ...]
    lfrt_source_ref: str | None
    legacy_source_ref: str | None


def compare_lfrt_with_legacy(
    lfrt: LFRTStatusSnapshot | None,
    legacy_state: ObservedResourceState | None,
    legacy_identity: LocalRuntimeIdentityObservation | None,
) -> LFRTShadowParityReport:
    """Compare observers without granting LFRT any admission authority."""

    if lfrt is None or legacy_state is None or legacy_identity is None:
        return LFRTShadowParityReport(
            status="unknown",
            mismatches=(),
            lfrt_source_ref=lfrt.source_ref if lfrt is not None else None,
            legacy_source_ref=(
                legacy_state.provenance.source_ref if legacy_state is not None else None
            ),
        )

    mismatches: list[str] = []
    expected_scope = f"mlx-loopback:{lfrt.port}"
    expected_legacy_source = f"local-listener:{lfrt.port}:pid:{lfrt.listener_pid}"
    expected_identity = f"mlx_lm.server/{lfrt.model_identity}"
    if legacy_state.runtime_type is not RuntimeType.LOCAL:
        mismatches.append("runtime_type")
    if legacy_state.key.scope_id != expected_scope:
        mismatches.append("scope_id")
    if legacy_state.provenance.source_ref != expected_legacy_source:
        mismatches.append("listener_pid")
    if legacy_state.max_concurrency != lfrt.max_concurrency:
        mismatches.append("max_concurrency")
    if legacy_identity.identity != expected_identity:
        mismatches.append("runtime_identity")
    if legacy_identity.source_ref != expected_legacy_source:
        mismatches.append("identity_source")
    return LFRTShadowParityReport(
        status="match" if not mismatches else "mismatch",
        mismatches=tuple(mismatches),
        lfrt_source_ref=lfrt.source_ref,
        legacy_source_ref=legacy_state.provenance.source_ref,
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dict(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def parse_lfrt_status(payload: object, *, observed_at: float) -> LFRTStatusSnapshot | None:
    """Validate one LFRT status payload; uncertainty is represented as ``None``."""

    root = _dict(payload)
    if root is None or root.get("ok") is not True or root.get("cmd") != "status":
        return None
    data = _dict(root.get("data"))
    if data is None:
        return None
    launchd = _dict(data.get("launchd"))
    process = _dict(data.get("process"))
    server = _dict(data.get("server"))
    config = _dict(data.get("config"))
    if None in (launchd, process, server, config):
        return None
    assert launchd is not None and process is not None and server is not None and config is not None

    listener = _dict(server.get("listener"))
    live_flags = _dict(process.get("flags"))
    configured_concurrency = _dict(config.get("concurrency"))
    if listener is None or live_flags is None or configured_concurrency is None:
        return None

    if launchd.get("known") is not True or launchd.get("registered") is not True:
        return None
    if listener.get("known") is not True:
        return None
    launchd_state = str(launchd.get("state") or "").strip()
    if launchd_state != "running":
        return None

    launchd_pid = _positive_int(launchd.get("pid"))
    listener_pid = _positive_int(listener.get("pid"))
    process_pid = _positive_int(process.get("pid"))
    if None in (launchd_pid, listener_pid, process_pid):
        return None
    if len({launchd_pid, listener_pid, process_pid}) != 1:
        return None
    assert launchd_pid is not None and listener_pid is not None and process_pid is not None

    port = _positive_int(config.get("port"))
    live_port = _positive_int(live_flags.get("port"))
    live_prompt = _positive_int(live_flags.get("prompt-concurrency"))
    live_decode = _positive_int(live_flags.get("decode-concurrency"))
    configured_prompt = _positive_int(configured_concurrency.get("prompt"))
    configured_decode = _positive_int(configured_concurrency.get("decode"))
    if None in (
        port,
        live_port,
        live_prompt,
        live_decode,
        configured_prompt,
        configured_decode,
    ):
        return None
    if live_port != port:
        return None
    assert port is not None
    assert live_prompt is not None and live_decode is not None
    assert configured_prompt is not None and configured_decode is not None

    model_path = str(live_flags.get("model") or "").strip()
    configured_model = str(config.get("model_path") or "").strip()
    if not model_path or not configured_model:
        return None
    model_identity = Path(model_path).name
    if not model_identity:
        return None

    aliases_raw = config.get("aliases")
    if not isinstance(aliases_raw, list) or not all(
        isinstance(alias, str) and alias.strip() for alias in aliases_raw
    ):
        return None
    aliases = tuple(alias.strip() for alias in aliases_raw)

    endpoint_healthy = server.get("health")
    if not isinstance(endpoint_healthy, bool):
        return None

    drift = (
        model_path != configured_model
        or live_prompt != configured_prompt
        or live_decode != configured_decode
    )
    return LFRTStatusSnapshot(
        observed_at=float(observed_at),
        source_ref=f"lfrt-status:{port}:pid:{listener_pid}",
        listener_pid=listener_pid,
        process_pid=process_pid,
        launchd_pid=launchd_pid,
        launchd_state=launchd_state,
        port=port,
        model_identity=model_identity,
        model_path=model_path,
        live_prompt_concurrency=live_prompt,
        live_decode_concurrency=live_decode,
        configured_prompt_concurrency=configured_prompt,
        configured_decode_concurrency=configured_decode,
        endpoint_healthy=endpoint_healthy,
        aliases=aliases,
        drift=drift,
    )


def _run_status(argv: tuple[str, ...], timeout_s: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return -1, "", "observer execution failed"
    return completed.returncode, completed.stdout, completed.stderr


class LFRTStatusObserver:
    """Execute only LFRT ``status --json`` and fail unknown on any ambiguity."""

    def __init__(
        self,
        executable: str | Path,
        *,
        runner: CommandRunner = _run_status,
        clock: Callable[[], float] = time.time,
        timeout_s: float = 2.0,
    ) -> None:
        path = Path(executable)
        if not path.is_absolute():
            raise ValueError("LFRT executable path must be absolute")
        if timeout_s <= 0:
            raise ValueError("LFRT observer timeout must be positive")
        self._executable = str(path)
        self._runner = runner
        self._clock = clock
        self._timeout_s = float(timeout_s)

    def observe(self) -> LFRTStatusSnapshot | None:
        argv = (self._executable, "status", "--json")
        try:
            rc, stdout, stderr = self._runner(argv, self._timeout_s)
        except Exception:  # noqa: BLE001 - observation failure is explicit unknown
            return None
        if rc != 0 or stderr.strip() or not stdout.strip():
            return None
        try:
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            return None
        return parse_lfrt_status(payload, observed_at=float(self._clock()))
