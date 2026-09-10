"""Live local-runtime resource observations for Resource Governor RG-2.

The adapter is intentionally narrow: it only recognizes a loopback HTTP client
whose listening process can be mechanically proven to be ``mlx_lm.server`` and
whose prompt/decode concurrency are both explicit in that live process command.
Unknown, ambiguous, remote, or implicit-default cases return ``None``; no
provider name, model family, or stale registry metadata is used to guess
capacity.
"""

from __future__ import annotations

import ipaddress
import shlex
import subprocess
import time
from collections.abc import Callable
from urllib.parse import urlparse

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    ObservedResourceState,
    ResourceKey,
    ResourceScopeKind,
    RuntimeType,
)

ListenerPidResolver = Callable[[int], tuple[int, ...]]
ProcessCommandResolver = Callable[[int], str]


def _default_listener_pids(port: int) -> tuple[int, ...]:
    """Return exact local TCP listener PIDs for ``port``; failure means unknown."""
    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if proc.returncode != 0:
        return ()
    pids: list[int] = []
    for raw in proc.stdout.splitlines():
        try:
            pid = int(raw.strip())
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return tuple(pids)


def _default_process_command(pid: int) -> str:
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _loopback_port(base_url: str) -> int | None:
    try:
        parsed = urlparse(str(base_url or ""))
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return None
        is_loopback = host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            return None
        if parsed.port is not None:
            return parsed.port
        if parsed.scheme == "http":
            return 80
        if parsed.scheme == "https":
            return 443
    except (TypeError, ValueError):
        return None
    return None


def _flag_value(argv: list[str], name: str) -> str | None:
    prefix = name + "="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            value = item[len(prefix) :]
            return value if value else None
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _positive_int_flag(argv: list[str], name: str) -> int | None:
    raw = _flag_value(argv, name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


class LocalRuntimeConcurrencyAdapter:
    """Observe an explicit MLX loopback concurrency fact from the live listener.

    ``max_concurrency`` is a conservative full-request coordination bound:
    ``min(prompt_concurrency, decode_concurrency)``. This is deliberately not a
    claim about the server's internal pipeline overlap; it is the maximum number
    of complete provider requests RG-2 will admit concurrently without exceeding
    either explicit live stage limit.
    """

    def __init__(
        self,
        *,
        listener_pids: ListenerPidResolver = _default_listener_pids,
        process_command: ProcessCommandResolver = _default_process_command,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._listener_pids = listener_pids
        self._process_command = process_command
        self._clock = clock

    def observe(
        self,
        client: object,
        *,
        provider_id: str,
        model_id: str,
    ) -> ObservedResourceState | None:
        del model_id  # identity is already carried by AdmissionRequest; capacity is endpoint-scoped
        provider = str(provider_id or "").strip()
        if not provider:
            return None
        port = _loopback_port(str(getattr(client, "base_url", "") or ""))
        if port is None:
            return None
        try:
            pids = tuple(self._listener_pids(port))
        except Exception:  # noqa: BLE001 - observation failure means unknown, never guessed
            return None
        if len(pids) != 1:
            return None
        pid = pids[0]
        try:
            command = str(self._process_command(pid) or "").strip()
            argv = shlex.split(command)
        except (Exception, ValueError):  # noqa: BLE001 - malformed process facts are unknown
            return None
        if not argv or "mlx_lm.server" not in argv:
            return None
        observed_port = _positive_int_flag(argv, "--port")
        prompt_concurrency = _positive_int_flag(argv, "--prompt-concurrency")
        decode_concurrency = _positive_int_flag(argv, "--decode-concurrency")
        if observed_port != port or prompt_concurrency is None or decode_concurrency is None:
            return None
        coordination_limit = min(prompt_concurrency, decode_concurrency)
        return ObservedResourceState(
            key=ResourceKey(
                provider_id=provider,
                scope_kind=ResourceScopeKind.RUNTIME,
                scope_id=f"mlx-loopback:{port}",
            ),
            provenance=FactProvenance(
                source=FactSource.RUNTIME_PROBE,
                source_ref=f"local-listener:{port}:pid:{pid}",
                recorded_at=float(self._clock()),
            ),
            runtime_type=RuntimeType.LOCAL,
            max_concurrency=coordination_limit,
        )
