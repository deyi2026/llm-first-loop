"""CTP 注册表原型（计划 B5 / TASK-e9f14fe1-009）：SPEC-20261123-CTP-0.9.2 §6 R-1..R-6。

模块地图：
- record.py    R-1 记录 dataclass + Ed25519 签名基元（D-08 暂定：确定性 JSON 载荷）；
- store.py     R-2 append-only JSONL + 哈希链，重放校验完整性，无删除 / 改写接口；
- tombstone.py R-3 墓碑终态数据结构（复用拒绝由 store.append 强制）；
- snapshot.py  R-4 带版本与签名的离线快照，无网络独立校验；
- verify.py    R-5 语义绑定前必验签，查无签名记录拒绝绑定；
- expiry.py    R-6 两级时效处置（按 PROP G5 提案实现，待 WG-RES 追认）。

设计边界与留给工作组的项见 ctp/docs/registry-notes.md。
"""

from __future__ import annotations

from .expiry import G5_QUARANTINE_PERIODS, ExpiryStatus, classify_expiry
from .record import (
    RegistryError,
    RegistryRecord,
    canonical_json,
    sign_record,
    verify_signature,
)
from .snapshot import (
    Snapshot,
    build_snapshot,
    load_snapshot,
    sign_snapshot,
    verify_offline,
    verify_snapshot,
    write_snapshot,
)
from .store import (
    GENESIS_HASH,
    KIND_REGISTER,
    KIND_RETIRE,
    RegistryStore,
    StoreEvent,
    compute_entry_hash,
)
from .tombstone import Tombstone
from .verify import bind_semantics

__all__ = [
    "ExpiryStatus",
    "GENESIS_HASH",
    "G5_QUARANTINE_PERIODS",
    "KIND_REGISTER",
    "KIND_RETIRE",
    "RegistryError",
    "RegistryRecord",
    "RegistryStore",
    "Snapshot",
    "StoreEvent",
    "Tombstone",
    "bind_semantics",
    "build_snapshot",
    "canonical_json",
    "classify_expiry",
    "compute_entry_hash",
    "load_snapshot",
    "sign_record",
    "sign_snapshot",
    "verify_offline",
    "verify_signature",
    "verify_snapshot",
    "write_snapshot",
]
