"""R-5 语义绑定验签（SPEC-20261123-CTP-0.9.2 §6 R-5，防伪第一级 T-4a）。

绑定检查顺序（前一步失败即拒绝，fail-closed）：
1. store 重放 + 链完整性校验（R-2；chain_broken / payload_tampered）；
2. 查无该 ID 的记录 → no_signed_record（R-5 文本：查无对应签名记录的 ID 必须拒绝绑定）；
3. ID 已墓碑 → tombstoned_id（R-3 终态）；
4. 记录无签名字段 → missing_signature；记录验签不通过 → signature_invalid；
5. 按 PROP G5 二级（提案，待 WG-RES 追认）：时效为 quarantine → quarantined_record，拒绝
   绑定；pending_revalidation 不拒绝绑定（一级是"可用但禁入高精度"，由读码器 C-5 标记）。

now 必填（显式时钟，无隐式 datetime.now()——测试与审计可复现）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .expiry import G5_QUARANTINE_PERIODS, ExpiryStatus, classify_expiry
from .record import (
    NO_SIGNED_RECORD,
    QUARANTINED_RECORD,
    RegistryError,
    RegistryRecord,
    TOMBSTONED_ID,
    verify_signature,
)
from .store import RegistryStore

_G5_NOTE = "quarantine per PROP-20261123-CTP-TBDG-0.2 G5 (proposal, pending WG-RES ratification)"


def bind_semantics(
    target_id: str,
    store_path: Path | str,
    public_key: Ed25519PublicKey,
    *,
    now: datetime,
) -> RegistryRecord:
    """语义绑定入口：全部检查通过返回该 ID 的最新记录；任一失败显式抛 RegistryError。"""
    store = RegistryStore(store_path)
    store.replay()  # 1) 链完整性（失败在此抛错）
    latest = store.latest_records()
    tombstones = store.tombstones()

    if target_id not in latest and target_id not in tombstones:  # 2) 查无记录
        raise RegistryError(
            NO_SIGNED_RECORD, "target_id", f"no registry record for id {target_id!r}; binding refused (R-5)"
        )
    if target_id in tombstones:  # 3) 墓碑终态
        raise RegistryError(
            TOMBSTONED_ID, "target_id", f"id {target_id!r} is tombstoned (terminal, R-3); binding refused"
        )

    record = latest[target_id]
    verify_signature(record, public_key)  # 4) 无签名 / 验签失败在此抛错

    status = classify_expiry(record, now)  # 5) G5 二级隔离
    if status is ExpiryStatus.QUARANTINE:
        raise RegistryError(
            QUARANTINED_RECORD,
            "last_verified",
            f"id {target_id!r} overdue >= {G5_QUARANTINE_PERIODS:.0f}x period; {_G5_NOTE}",
        )
    return record
