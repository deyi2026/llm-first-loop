"""R-4 离线快照：带版本与签名，无网络独立校验（SPEC-20261123-CTP-0.9.2 §6 R-4）。

机制边界：
- 快照 = 某时刻事件流的物化视图：每个未墓碑 ID 的最新 register 记录 + 全部墓碑 + 生成时的
  store 链头 head_hash（审计锚，供与在线侧比对）；墓碑 ID 的 register 记录不进快照 records
  （终态语义，防离线方误用——绑定侧另由 R-3 检查兜底）；
- 两级签名缺一不可：快照级签名覆盖整个快照（防投毒，对 D2）；记录级签名随记录内嵌（R-5，
  离线等价物）。verify_offline 同时校验两级；
- 签名载荷 = 无快照级 signature 字段的确定性 JSON 之 sha256（D-08 暂定，同 record.py）；
- snapshot_version 是快照格式版本（必填参数，无默认；它是序列化协议版本，不是门槛数值，
  格式演进走显式版本号，不静默兼容）；
- 离线校验不含 R-6 时效判定：classify_expiry 需要调用方显式时钟（见 expiry.py），离线快照
  只承诺"数据可信"，不承诺"数据未过期"。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .record import (
    MISSING_FIELD,
    MISSING_SIGNATURE,
    RegistryError,
    RegistryRecord,
    SIGNATURE_INVALID,
    SNAPSHOT_INVALID,
    TYPE_ERROR,
    UNKNOWN_FIELD,
    canonical_json,
    verify_signature,
)
from .store import KIND_REGISTER, KIND_RETIRE, GENESIS_HASH, StoreEvent
from .tombstone import Tombstone

_SNAPSHOT_FIELDS = (
    "snapshot_version",
    "created_at",
    "records",
    "tombstones",
    "head_hash",
    "signature",
)


@dataclass(frozen=True)
class Snapshot:
    """R-4 离线快照。records / tombstones 按 target_id 排序（确定性序列化）。"""

    snapshot_version: int
    created_at: str
    records: tuple[RegistryRecord, ...]
    tombstones: tuple[Tombstone, ...]
    head_hash: str
    signature: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.snapshot_version, bool) or not isinstance(self.snapshot_version, int):
            raise RegistryError(TYPE_ERROR, "snapshot_version", "must be an int")
        if self.snapshot_version < 1:
            raise RegistryError(SNAPSHOT_INVALID, "snapshot_version", f"must be >= 1, got {self.snapshot_version}")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise RegistryError(TYPE_ERROR, "created_at", "must be an ISO 8601 string with timezone")
        if not isinstance(self.records, tuple) or not all(isinstance(rec, RegistryRecord) for rec in self.records):
            raise RegistryError(TYPE_ERROR, "records", "must be a tuple of RegistryRecord")
        if not isinstance(self.tombstones, tuple) or not all(isinstance(ts, Tombstone) for ts in self.tombstones):
            raise RegistryError(TYPE_ERROR, "tombstones", "must be a tuple of Tombstone")
        if not isinstance(self.head_hash, str) or isinstance(self.head_hash, bool):
            raise RegistryError(TYPE_ERROR, "head_hash", "head_hash must be a hex str")
        try:
            head_raw = bytes.fromhex(self.head_hash)
        except ValueError as exc:
            raise RegistryError(SNAPSHOT_INVALID, "head_hash", "head_hash is not valid hex") from exc
        if len(head_raw) != 32:
            raise RegistryError(SNAPSHOT_INVALID, "head_hash", "head_hash must be 64-char hex (sha256)")
        if self.signature is not None:
            try:
                raw = bytes.fromhex(self.signature)
            except ValueError as exc:
                raise RegistryError(SNAPSHOT_INVALID, "signature", "snapshot signature is not valid hex") from exc
            if len(raw) != 64:
                raise RegistryError(SNAPSHOT_INVALID, "signature", "snapshot signature must be 64 bytes")
            object.__setattr__(self, "signature", self.signature.lower())

    # ---- 确定性序列化 ----

    def payload_dict(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version,
            "created_at": self.created_at,
            "records": [rec.to_dict() for rec in self.records],
            "tombstones": [ts.to_dict() for ts in self.tombstones],
            "head_hash": self.head_hash,
        }

    def payload_canonical(self) -> str:
        return canonical_json(self.payload_dict())

    def payload_digest(self) -> bytes:
        return hashlib.sha256(self.payload_canonical().encode("utf-8")).digest()

    def to_dict(self) -> dict[str, Any]:
        out = self.payload_dict()
        out["signature"] = self.signature
        return out

    @classmethod
    def from_dict(cls, obj: Any) -> "Snapshot":
        if not isinstance(obj, dict):
            raise RegistryError(SNAPSHOT_INVALID, "<root>", f"snapshot must be a JSON object, got {type(obj).__name__}")
        missing = [name for name in _SNAPSHOT_FIELDS if name not in obj]
        if missing:
            raise RegistryError(MISSING_FIELD, "<root>", f"missing snapshot fields: {sorted(missing)}")
        unknown = [key for key in obj if key not in _SNAPSHOT_FIELDS]
        if unknown:
            raise RegistryError(UNKNOWN_FIELD, "<root>", f"unknown snapshot fields: {sorted(unknown)}")
        if not isinstance(obj["records"], list) or not isinstance(obj["tombstones"], list):
            raise RegistryError(TYPE_ERROR, "records", "records / tombstones must be JSON arrays")
        return cls(
            snapshot_version=obj["snapshot_version"],
            created_at=obj["created_at"],
            records=tuple(RegistryRecord.from_dict(rec) for rec in obj["records"]),
            tombstones=tuple(Tombstone.from_dict(ts) for ts in obj["tombstones"]),
            head_hash=obj["head_hash"],
            signature=obj["signature"],
        )


def build_snapshot(
    events: list[StoreEvent],
    *,
    snapshot_version: int,
    created_at: str,
) -> Snapshot:
    """从事件流物化快照（确定性：记录与墓碑按 target_id 排序）。不签名——签名是独立动作。"""
    latest: dict[str, RegistryRecord] = {}
    tombstones: dict[str, Tombstone] = {}
    for event in events:
        if event.kind == KIND_REGISTER:
            record = RegistryRecord.from_dict(event.payload)
            latest[record.target_id] = record
        elif event.kind == KIND_RETIRE:
            tombstone = Tombstone.from_dict(event.payload)
            tombstones[tombstone.target_id] = tombstone
            latest.pop(tombstone.target_id, None)
    head = events[-1].entry_hash if events else GENESIS_HASH
    return Snapshot(
        snapshot_version=snapshot_version,
        created_at=created_at,
        records=tuple(latest[tid] for tid in sorted(latest)),
        tombstones=tuple(tombstones[tid] for tid in sorted(tombstones)),
        head_hash=head,
    )


def sign_snapshot(snapshot: Snapshot, private_key: Ed25519PrivateKey) -> Snapshot:
    """快照级签名（返回新对象，不改原快照）。"""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RegistryError(TYPE_ERROR, "private_key", "must be an Ed25519PrivateKey")
    signature = private_key.sign(snapshot.payload_digest()).hex()
    return replace(snapshot, signature=signature)


def write_snapshot(path: Path | str, snapshot: Snapshot) -> None:
    """快照落盘：整个快照一份确定性 JSON（单文件 = 离线分发单元）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(snapshot.to_dict()), encoding="utf-8")


def load_snapshot(path: Path | str) -> Snapshot:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(SNAPSHOT_INVALID, str(target), f"cannot read snapshot file: {exc}") from exc
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RegistryError(SNAPSHOT_INVALID, str(target), "snapshot file is not valid JSON") from exc
    return Snapshot.from_dict(obj)


def verify_snapshot(snapshot: Snapshot, public_key: Ed25519PublicKey) -> None:
    """离线校验：快照级签名 + 逐条记录级签名（R-5 离线等价物）。失败显式抛错。"""
    if not isinstance(public_key, Ed25519PublicKey):
        raise RegistryError(TYPE_ERROR, "public_key", "must be an Ed25519PublicKey")
    if snapshot.signature is None:
        raise RegistryError(MISSING_SIGNATURE, "signature", "snapshot carries no snapshot-level signature (R-4)")
    try:
        public_key.verify(bytes.fromhex(snapshot.signature), snapshot.payload_digest())
    except ValueError as exc:
        raise RegistryError(SNAPSHOT_INVALID, "signature", "snapshot signature is not valid hex") from exc
    except InvalidSignature as exc:
        raise RegistryError(
            SIGNATURE_INVALID, "signature", "snapshot signature does not match snapshot payload"
        ) from exc
    for record in snapshot.records:
        verify_signature(record, public_key)  # 记录级：MISSING_SIGNATURE / SIGNATURE_INVALID


def verify_offline(path: Path | str, public_key: Ed25519PublicKey) -> Snapshot:
    """无网络独立校验入口：只凭快照文件 + 公钥。通过返回已验快照。"""
    snapshot = load_snapshot(path)
    verify_snapshot(snapshot, public_key)
    return snapshot
