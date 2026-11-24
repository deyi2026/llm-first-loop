"""R-6 复验周期时效判定（SPEC-20261123-CTP-0.9.2 §6 R-6）。

两级处置（按 PROP-20261123-CTP-TBDG-0.2 §G5 提案实现，待 WG-RES 追认）：
- 一级：age >= revalidate_period_days → 待复验（pending_revalidation）——观测可用但禁入高
  精度决策（读码器侧以 C-5 degradation_flag 表达）；
- 二级：age >= G5_QUARANTINE_PERIODS × period → 强制隔离（quarantine）——按提案：禁止语义
  绑定（verify.py 以 quarantined_record 拒绝）、禁止参与几何互证（M-2），注册表标记"墓碑
  候选"。

数值纪律：
- 周期本身是记录必填字段（R-1），本模块不提供任何默认周期——"多少天该复验"属健康档案与
  工作组（SPEC R-6：超期处置的强制等级 [TBD-G]）；
- G5_QUARANTINE_PERIODS = 2 是提案文本中的结构倍数（"超期持续 ≥ 2 × 复验周期"），不是
  实现层发明的门槛；提案取得 WG-RES 决议编号前，所有输出按"提案实现"标注；
- 边界取 >=（到期当日即算超期）：保守侧选择，宁可多标待复验，不让过期数据静默进入高精度
  通道；SPEC 未定义边界，此选择记录在 registry-notes.md；
- now 必填且必须带时区（无隐式时钟、无本地时区歧义）；age 为负（时钟早于 last_verified）
  时按 OK 处理——时钟回拨检测不属本层。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .record import RegistryError, RegistryRecord, TIMESTAMP_MISSING_TIMEZONE, TYPE_ERROR

G5_QUARANTINE_PERIODS = 2.0  # 来源：PROP-20261123-CTP-TBDG-0.2 §G5（提案，非决议，待 WG-RES 追认）


class ExpiryStatus(StrEnum):
    """R-6 时效状态（与 C-5 degradation_flag 的对齐关系见 registry-notes.md）。"""

    OK = "ok"
    PENDING_REVALIDATION = "pending_revalidation"
    QUARANTINE = "quarantine"


def classify_expiry(record: RegistryRecord, now: datetime) -> ExpiryStatus:
    """判定记录在 now 时刻的时效状态。周期来自记录字段；倍数 2 来自 PROP G5（待追认）。"""
    if not isinstance(now, datetime):
        raise RegistryError(TYPE_ERROR, "now", "now must be a datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise RegistryError(TIMESTAMP_MISSING_TIMEZONE, "now", "now must carry a timezone offset")
    last_verified = datetime.fromisoformat(record.last_verified)  # post_init 已保证可解析且带时区
    age_days = (now - last_verified).total_seconds() / 86400.0
    period = float(record.revalidate_period_days)
    if age_days >= G5_QUARANTINE_PERIODS * period:
        return ExpiryStatus.QUARANTINE
    if age_days >= period:
        return ExpiryStatus.PENDING_REVALIDATION
    return ExpiryStatus.OK
