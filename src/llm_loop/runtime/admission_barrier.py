"""File-based per-service admission barriers for managed service restarts.

Design v1.2 §8.2/§8.3: an accepted restart operation must block NEW run
creation on its target services for the whole waiting window.  Otherwise a
newly arriving message keeps creating active dependencies and the restart is
postponed indefinitely (the §2.2 gap: no message admission barrier).

Why process-level machinery (admission asymmetry rule): a restart accepted by
a model run cannot stop an HTTP/websocket message from spawning a new run in
another process — the model has no tool that reaches cross-process admission.
Enforcement therefore lives at the admission boundary itself; the model keeps
the veto via the terminal-status releases and the operator keeps an explicit
override CLI (`service_control.py barriers` / `barrier-release`).

Semantics:
- Barriers live under <data_dir>/runtime/service-control-barriers/<service>.json
  (sibling of service-control-actions/, same data_dir as the deployment store).
- Established atomically with acceptance: if establishment fails, acceptance
  must fail too (no "accepted but barrierless" operations).
- One barrier per service, owned by exactly one operation_id.  Another
  operation's release never clears it (§8.3 multi-operation ownership).
- Release is per-service by the owning operation, or by explicit operator
  override.  A barrier whose owner is unknown/corrupt is only clearable via
  the override, never via timeouts.
- blocked()/snapshot() are read-only and never create directories, so
  admission hot paths (web chat/stream/queue dispatch, scheduler wake, feishu
  worker) can poll them cheaply.  A physically unreadable barrier (OSError)
  does not block admission; a present-but-corrupt one does (fail-closed for
  admission, explicit override for recovery).
"""

from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_BARRIER_SCHEMA = "service-admission-barrier/v1"
_BARRIER_DIR = Path("runtime") / "service-control-barriers"

logger = logging.getLogger(__name__)


class AdmissionBarrierError(RuntimeError):
    """Base error for admission barrier operations."""


class BarrierConflictError(AdmissionBarrierError):
    """Another operation already owns this service's barrier."""


@dataclass(frozen=True)
class ServiceAdmissionBarrier:
    service: str
    operation_id: str
    reason: str
    created_at: str
    created_by: str
    corrupt: bool = False

    def to_view(self) -> dict[str, str | bool]:
        return {
            "service": self.service,
            "operation_id": self.operation_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "corrupt": self.corrupt,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _created_by() -> str:
    return f"pid={os.getpid()} host={socket.gethostname()}"


class AdmissionBarrierRegistry:
    """Per-service admission barriers; file-per-service, single owner each."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self._data_dir = Path(data_dir).expanduser()
        self.root = self._data_dir / _BARRIER_DIR

    def barrier_path(self, service: str) -> Path:
        return self.root / f"{service}.json"

    def _load(self, path: Path, service: str) -> ServiceAdmissionBarrier | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:  # physically unreadable: do not block admission
            logger.warning("admission barrier for %s unreadable (%s); treating as absent", service, exc)
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ServiceAdmissionBarrier(
                service=service,
                operation_id="",
                reason="corrupt",
                created_at="",
                created_by="",
                corrupt=True,
            )
        if not isinstance(data, dict) or data.get("schema") != _BARRIER_SCHEMA:
            return ServiceAdmissionBarrier(
                service=service,
                operation_id="",
                reason="schema-mismatch",
                created_at="",
                created_by="",
                corrupt=True,
            )
        return ServiceAdmissionBarrier(
            service=service,
            operation_id=str(data.get("operation_id") or ""),
            reason=str(data.get("reason") or ""),
            created_at=str(data.get("created_at") or ""),
            created_by=str(data.get("created_by") or ""),
        )

    def blocked(self, service: str) -> ServiceAdmissionBarrier | None:
        """Read-only admission check; never creates directories or files."""
        return self._load(self.barrier_path(service), service)

    def establish(
        self,
        service: str,
        *,
        operation_id: str,
        reason: str = "restart",
    ) -> ServiceAdmissionBarrier:
        """Claim the service barrier for one operation (exclusive, atomic).

        Idempotent for the same owner; raises BarrierConflictError when another
        owner (or an unknown/corrupt barrier) already holds the service.
        """
        if not operation_id.strip():
            raise AdmissionBarrierError("operation_id must be non-empty")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.barrier_path(service)
        payload = json.dumps(
            {
                "schema": _BARRIER_SCHEMA,
                "service": service,
                "operation_id": operation_id,
                "reason": reason,
                "created_at": _utc_now(),
                "created_by": _created_by(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        tmp = self.root / f".{service}.{operation_id}.tmp"
        tmp.write_bytes(payload)
        try:
            # os.link is exclusive: if path already exists this fails without
            # touching the existing barrier.  The final file only ever appears
            # whole, so readers never observe partial JSON.
            os.link(tmp, path)
        except FileExistsError as exc:
            current = self.blocked(service)
            if (
                current is not None
                and not current.corrupt
                and current.operation_id == operation_id
            ):
                return current
            owner = current.operation_id if current is not None else "<unknown>"
            raise BarrierConflictError(
                f"admission barrier for service {service!r} already held by operation {owner}"
            ) from exc
        finally:
            tmp.unlink(missing_ok=True)
        try:
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:  # pragma: no cover - directory fsync is best-effort
            pass
        barrier = self.blocked(service)
        assert barrier is not None
        return barrier

    def release(self, service: str, *, operation_id: str) -> bool:
        """Release the barrier, but only when owned by operation_id."""
        path = self.barrier_path(service)
        current = self._load(path, service)
        if current is None or current.corrupt or current.operation_id != operation_id:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def force_release(self, service: str, *, reason: str) -> bool:
        """Operator override: remove a barrier regardless of owner.

        Only reachable from the explicit CLI (audited reason required); never
        from timeouts (§8.3: a barrier must not be cleared by any caller just
        because time passed).
        """
        if not reason.strip():
            raise AdmissionBarrierError("force release requires a reason")
        path = self.barrier_path(service)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        logger.warning("admission barrier for %s force-released: %s", service, reason)
        return True

    def snapshot(self) -> list[ServiceAdmissionBarrier]:
        """List every active barrier (for status views and the CLI)."""
        try:
            names = sorted(p.name for p in self.root.glob("*.json"))
        except OSError:
            return []
        barriers = []
        for name in names:
            service = name[: -len(".json")]
            barrier = self._load(self.root / name, service)
            if barrier is not None:
                barriers.append(barrier)
        return barriers


def service_restart_barrier(data_dir: str | os.PathLike[str], service: str) -> ServiceAdmissionBarrier | None:
    """Convenience read for admission hot paths (web/scheduler/feishu)."""
    return AdmissionBarrierRegistry(data_dir).blocked(service)


# --------------------------------------------------------------------------
# 任务注册表（缺口②·依赖范围准入）
#
# 任务种类 → 声明依赖的受管服务。准入按声明范围检查屏障：未被声明的
# 服务重启不阻塞该任务（learning 不依赖 web/feishu 进程，web 屏障不
# 得让 Reflection 停摆；反之亦然）。闭表——新增入口必须先登记依赖，
# 调用点不允许临时指定服务名，防止准入范围在散落调用点漂移。
# --------------------------------------------------------------------------
TASK_ADMISSION_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "web_chat": ("web",),
    "web_chat_stream": ("web",),
    "web_queue_dispatch": ("web",),
    "web_schedule_wake": ("web",),
    "feishu_message": ("feishu",),
    "learning_job": ("learning",),
}


def task_admission_barrier(
    data_dir: str | os.PathLike[str], task_kind: str
) -> ServiceAdmissionBarrier | None:
    """First active barrier among the task's declared dependency services.

    未登记的任务种类直接抛 ``KeyError``——准入范围是声明事实，不是调用
    点的自选参数。
    """
    services = TASK_ADMISSION_DEPENDENCIES.get(task_kind)
    if services is None:
        raise KeyError(f"unregistered task kind for admission: {task_kind!r}")
    registry = AdmissionBarrierRegistry(data_dir)
    for service in services:
        barrier = registry.blocked(service)
        if barrier is not None:
            return barrier
    return None
