"""R-2 append-only 存储：JSONL 事件日志 + 哈希链（SPEC-20261123-CTP-0.9.2 §6 R-2）。

机制边界（如实声明，防误用）：
- 物理删除 / 原地改写一律拒绝——实现层不给接口：RegistryStore 只暴露 append / replay /
  只读查询方法，没有 delete / update / overwrite 类成员；
- 链完整性：每条事件 entry_hash = sha256(prev_hash + canonical_json({kind, payload}))，首条
  prev_hash = GENESIS_HASH。replay 逐行重算：行内容与 entry_hash 不符 → payload_tampered；
  prev_hash 与上一条 entry_hash 不衔接（删行 / 重排 / 截断）→ chain_broken；
- 能力边界：哈希链防意外损坏与非特权篡改；**不防**能重写文件并重算全链的特权攻击者——
  防伪第一级是 Ed25519 记录签名（T-4a，私钥离线），两层分工见 verify.py；
- append 的写前语义检查（单进程原型假设）：墓碑 ID 复用登记 → tombstone_reuse；同 ID 新
  record_version 必须 strictly greater → version_regression；入库记录必须带签名字段 →
  missing_signature（实现层收紧：SPEC 未规定，防无签名记录直接入档，见 registry-notes.md）；
- 并发写未做锁：多进程同时 append 会交错破坏链（留给部署层单写者约束，原型不发明锁协议）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .record import (
    ALREADY_TOMBSTONED,
    CHAIN_BROKEN,
    FORMAT_ERROR,
    MISSING_FIELD,
    MISSING_SIGNATURE,
    PAYLOAD_TAMPERED,
    RegistryError,
    RegistryRecord,
    TOMBSTONE_REUSE,
    TYPE_ERROR,
    UNKNOWN_FIELD,
    UNKNOWN_ID,
    VERSION_REGRESSION,
    canonical_json,
)
from .tombstone import Tombstone
import hashlib

GENESIS_HASH = "0" * 64  # 链锚：全零占位（结构常量，非门槛数值）
KIND_REGISTER = "register"
KIND_RETIRE = "retire"
_KINDS = (KIND_REGISTER, KIND_RETIRE)

_EVENT_FIELDS = ("kind", "payload", "prev_hash", "entry_hash")


def compute_entry_hash(prev_hash: str, kind: str, payload: dict[str, Any]) -> str:
    body = canonical_json({"kind": kind, "payload": payload})
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def _require_hash_hex(value: Any, path: str) -> None:
    if not isinstance(value, str) or isinstance(value, bool):
        raise RegistryError(TYPE_ERROR, path, f"{path} must be a hex str")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise RegistryError(FORMAT_ERROR, path, f"{path} is not valid hex") from exc
    if len(raw) != 32:
        raise RegistryError(FORMAT_ERROR, path, f"{path} must be 32 bytes (sha256), got {len(raw)}")


@dataclass(frozen=True)
class StoreEvent:
    """一条 append-only 事件：register（R-1 记录入档）或 retire（R-3 墓碑）。"""

    kind: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise RegistryError(FORMAT_ERROR, "kind", f"kind must be one of {_KINDS}, got {self.kind!r}")
        if not isinstance(self.payload, dict):
            raise RegistryError(TYPE_ERROR, "payload", "payload must be a JSON object")
        _require_hash_hex(self.prev_hash, "prev_hash")
        _require_hash_hex(self.entry_hash, "entry_hash")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    def to_json_line(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, obj: Any, *, path: str = "<root>") -> "StoreEvent":
        if not isinstance(obj, dict):
            raise RegistryError(TYPE_ERROR, path, f"event must be a JSON object, got {type(obj).__name__}")
        missing = [name for name in _EVENT_FIELDS if name not in obj]
        if missing:
            raise RegistryError(MISSING_FIELD, path, f"missing event fields: {sorted(missing)}")
        unknown = [key for key in obj if key not in _EVENT_FIELDS]
        if unknown:
            raise RegistryError(UNKNOWN_FIELD, path, f"unknown event fields: {sorted(unknown)}")
        return cls(
            kind=obj["kind"],
            payload=obj["payload"],
            prev_hash=obj["prev_hash"],
            entry_hash=obj["entry_hash"],
        )


class RegistryStore:
    """单文件 JSONL 注册表存储。只允许追加与重放；无删除 / 改写接口（R-2）。"""

    def __init__(
        self, path: Path | str, *, retire_verifier: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self._path = Path(path)
        # P2-1（wave-2 审查）：SPEC R-3 未要求墓碑权威签名，本层不发明规范要求；
        # 但任何能写 JSONL 的写者都可追加 retire（哈希链不拦合法追加），是对语义
        # 绑定可用性的 DoS 面。retire_verifier 钩子供有权威方的部署强制校验 retire
        # 载荷（如 Ed25519 签名）；默认 None = SPEC 最小语义（TODO-G2 #1）。
        self._retire_verifier = retire_verifier

    @property
    def path(self) -> Path:
        return self._path

    # ---- 写（唯一变更入口）----

    def append(self, kind: str, payload: dict[str, Any]) -> StoreEvent:
        """追加一条事件并返回。写前先 replay 做语义检查（墓碑复用 / 版本递增 / 签名在场）。"""
        if kind not in _KINDS:
            raise RegistryError(FORMAT_ERROR, "kind", f"kind must be one of {_KINDS}, got {kind!r}")
        events, head = self.replay()
        latest = self._latest_records(events)
        tombstoned = self._tombstones(events)

        if kind == KIND_REGISTER:
            record = RegistryRecord.from_dict(payload)  # 结构校验，失败显式抛错
            if record.signature is None:
                raise RegistryError(
                    MISSING_SIGNATURE, "signature", f"record {record.target_id!r} cannot enter store unsigned"
                )
            if record.target_id in tombstoned:
                raise RegistryError(
                    TOMBSTONE_REUSE,
                    "target_id",
                    f"id {record.target_id!r} is tombstoned (terminal, R-3); registering it again is forbidden",
                )
            if record.target_id in latest and record.record_version <= latest[record.target_id].record_version:
                raise RegistryError(
                    VERSION_REGRESSION,
                    "record_version",
                    f"new version {record.record_version} must be > stored {latest[record.target_id].record_version}",
                )
        else:  # KIND_RETIRE
            tombstone = Tombstone.from_dict(payload)
            if tombstone.target_id in tombstoned:  # 终态判定先于存在性（墓碑后 latest 已无该 ID）
                raise RegistryError(
                    ALREADY_TOMBSTONED,
                    "target_id",
                    f"id {tombstone.target_id!r} is already tombstoned (terminal, R-3)",
                )
            if tombstone.target_id not in latest:
                raise RegistryError(
                    UNKNOWN_ID, "target_id", f"cannot retire unknown id {tombstone.target_id!r}"
                )
            if self._retire_verifier is not None:
                self._retire_verifier(payload)

        event = StoreEvent(kind, payload, head, compute_entry_hash(head, kind, payload))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.to_json_line() + "\n")
        return event

    # ---- 读 ----

    def replay(self) -> tuple[list[StoreEvent], str]:
        """重放并校验链完整性；返回 (events, head_hash)。文件不存在视为空链。"""
        if not self._path.exists():
            return [], GENESIS_HASH
        events: list[StoreEvent] = []
        prev = GENESIS_HASH
        with open(self._path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                where = f"line:{lineno}"
                if not line.strip():
                    raise RegistryError(FORMAT_ERROR, where, "blank line in store file")
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise RegistryError(FORMAT_ERROR, where, f"line is not valid JSON") from exc
                event = StoreEvent.from_dict(obj, path=where)
                recomputed = compute_entry_hash(event.prev_hash, event.kind, event.payload)
                if recomputed != event.entry_hash:
                    raise RegistryError(
                        PAYLOAD_TAMPERED,
                        where,
                        f"entry_hash does not match kind/payload content (stored {event.entry_hash[:12]}..., recomputed {recomputed[:12]}...)",
                    )
                if event.prev_hash != prev:
                    raise RegistryError(
                        CHAIN_BROKEN,
                        where,
                        f"prev_hash does not link to previous entry (expected {prev[:12]}..., got {event.prev_hash[:12]}...)",
                    )
                prev = event.entry_hash
                events.append(event)
        return events, prev

    def latest_records(self) -> dict[str, RegistryRecord]:
        """每个未墓碑 ID 的最新 register 记录。"""
        return self._latest_records(self.replay()[0])

    def tombstones(self) -> dict[str, Tombstone]:
        """全部墓碑（ID → Tombstone）。"""
        return self._tombstones(self.replay()[0])

    # ---- 内部 ----

    @staticmethod
    def _latest_records(events: list[StoreEvent]) -> dict[str, RegistryRecord]:
        latest: dict[str, RegistryRecord] = {}
        tombstoned: set[str] = set()
        for event in events:
            if event.kind == KIND_REGISTER:
                record = RegistryRecord.from_dict(event.payload)
                latest[record.target_id] = record
            else:
                tombstone = Tombstone.from_dict(event.payload)
                tombstoned.add(tombstone.target_id)
                latest.pop(tombstone.target_id, None)  # 墓碑后该 ID 无"最新记录"
        return {tid: rec for tid, rec in latest.items() if tid not in tombstoned}

    @staticmethod
    def _tombstones(events: list[StoreEvent]) -> dict[str, Tombstone]:
        out: dict[str, Tombstone] = {}
        for event in events:
            if event.kind == KIND_RETIRE:
                tombstone = Tombstone.from_dict(event.payload)
                out[tombstone.target_id] = tombstone
        return out
