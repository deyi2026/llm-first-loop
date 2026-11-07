"""lfl.peer.v1 领域模型（薄层）。

形状以 ``docs/schemas/lfl.peer.v1/*.schema.json`` 为准；本模块只做 dataclass 往返与
最少不变量，不做授权判断（授权在 ``peer.policy`` / ``peer.auth``，闸门在路由层）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA = "lfl.peer.v1"

NODE_STATES: tuple[str, ...] = ("paired", "revoked")
GRANT_STATES: tuple[str, ...] = ("active", "expired", "exhausted", "revoked")
IDEMPOTENCY_CLASSES: tuple[str, ...] = ("idempotent", "non_idempotent")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {raw}")
    return parsed.astimezone(UTC)


def _drop_none(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if v is not None}


@dataclass(frozen=True)
class NodeRecord:
    """已配对节点。共享密钥不在此：单独 0600 落在 data/peer/secrets/<node_id>.key。"""

    node_id: str
    display_name: str
    role: str
    base_url: str
    display_protocol: str
    state: str
    paired_at: str
    last_seen_at: str | None = None
    manifest_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(asdict(self))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NodeRecord:
        return cls(
            node_id=raw["node_id"],
            display_name=raw["display_name"],
            role=raw["role"],
            base_url=raw["base_url"],
            display_protocol=raw["display_protocol"],
            state=raw["state"],
            paired_at=raw["paired_at"],
            last_seen_at=raw.get("last_seen_at"),
            manifest_digest=raw.get("manifest_digest"),
        )


@dataclass(frozen=True)
class GrantRecord:
    """有界租约。expires_at 与 max_tasks_total 必填（grant.schema.json）。"""

    grant_id: str
    node_id: str
    issued_by: dict[str, Any]
    issued_at: str
    expires_at: str
    state: str
    allowed_kinds: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    max_concurrency: int
    max_tasks_total: int
    tasks_used: int = 0
    revoked_at: str | None = None
    revoked_by: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["schema"] = SCHEMA
        raw["allowed_kinds"] = list(self.allowed_kinds)
        raw["allowed_paths"] = list(self.allowed_paths)
        return _drop_none(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GrantRecord:
        return cls(
            grant_id=raw["grant_id"],
            node_id=raw["node_id"],
            issued_by=dict(raw["issued_by"]),
            issued_at=raw["issued_at"],
            expires_at=raw["expires_at"],
            state=raw["state"],
            allowed_kinds=tuple(raw["allowed_kinds"]),
            allowed_paths=tuple(raw["allowed_paths"]),
            max_concurrency=int(raw["max_concurrency"]),
            max_tasks_total=int(raw["max_tasks_total"]),
            tasks_used=int(raw.get("tasks_used", 0)),
            revoked_at=raw.get("revoked_at"),
            revoked_by=raw.get("revoked_by"),
            note=raw.get("note"),
        )

    def with_tasks_used(self, value: int) -> GrantRecord:
        if value < self.tasks_used:
            raise ValueError("tasks_used 只能递增")
        return replace_grant(self, tasks_used=value, state="exhausted" if value >= self.max_tasks_total else self.state)

    def revoked(self, by: str, at: str) -> GrantRecord:
        return replace_grant(self, state="revoked", revoked_at=at, revoked_by=by)


def replace_grant(grant: GrantRecord, **changes: Any) -> GrantRecord:
    data = asdict(grant)
    data.update(changes)
    return GrantRecord.from_dict(data)


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    effect_id: str
    node_id: str
    kind: str
    params: dict[str, Any]
    expect: tuple[str, ...]
    deadline_s: int
    state: str
    idempotency_class: str
    supervised_only: bool
    created_at: str
    updated_at: str
    attempt: int = 1
    admission_id: str | None = None
    grant_id: str | None = None
    reason_code: str | None = None
    blocked_reason: str | None = None
    result: dict[str, Any] | None = None
    requested_by: str | None = None
    params_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        return _drop_none(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskRecord:
        return cls(
            task_id=raw["task_id"],
            effect_id=raw["effect_id"],
            node_id=raw["node_id"],
            kind=raw["kind"],
            params=dict(raw.get("params") or {}),
            expect=tuple(raw.get("expect") or ()),
            deadline_s=int(raw["deadline_s"]),
            state=raw["state"],
            idempotency_class=raw["idempotency_class"],
            supervised_only=bool(raw["supervised_only"]),
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            attempt=int(raw.get("attempt", 1)),
            admission_id=raw.get("admission_id"),
            grant_id=raw.get("grant_id"),
            reason_code=raw.get("reason_code"),
            blocked_reason=raw.get("blocked_reason"),
            result=raw.get("result"),
            requested_by=raw.get("requested_by"),
            params_digest=raw.get("params_digest"),
        )

    def with_updates(self, **changes: Any) -> TaskRecord:
        data = asdict(self)
        data.update(changes)
        return TaskRecord.from_dict(data)


@dataclass(frozen=True)
class AdmissionRecord:
    """副作用前落盘的不可变准入结论（对齐 A2A admission 的 CAS 语义）。"""

    admission_id: str
    task_id: str
    node_id: str
    kind: str
    effect_id: str
    verdict: str  # admitted | denied
    decided_at: str
    params_digest: str
    grant_id: str | None = None
    reason_code: str | None = None
    decided_by: str = "peer_admission"

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(asdict(self))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AdmissionRecord:
        return cls(
            admission_id=raw["admission_id"],
            task_id=raw["task_id"],
            node_id=raw["node_id"],
            kind=raw["kind"],
            effect_id=raw["effect_id"],
            verdict=raw["verdict"],
            decided_at=raw["decided_at"],
            params_digest=raw["params_digest"],
            grant_id=raw.get("grant_id"),
            reason_code=raw.get("reason_code"),
            decided_by=raw.get("decided_by", "peer_admission"),
        )
