"""R-3 墓碑：报废 ID 的终态记录（SPEC-20261123-CTP-0.9.2 §6 R-3，Q12 裁决）。

语义边界：
- 墓碑是注册表事件流中的 retire 事件载荷；一旦进入墓碑，该 ID 即终态，禁止复用——
  "复用登记抛错"由 store.RegistryStore.append 强制（唯一写入路径，code=tombstone_reuse）；
- 墓碑本事件不携带签名：SPEC R-3 未要求墓碑签名，本原型不发明该要求（TODO-G2：工作组
  若裁决墓碑需权威签名，在本结构上加字段并纳入链与快照）；
- reason 是人读审计线索，机器不解析其内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .record import FORMAT_ERROR, MISSING_FIELD, TYPE_ERROR, UNKNOWN_FIELD, RegistryError, _parse_tz_datetime, _require_nonempty_str

_TOMBSTONE_FIELDS = ("target_id", "retired_at", "reason")


@dataclass(frozen=True)
class Tombstone:
    """一条墓碑：target_id 已报废，终态、不可复用（R-3）。"""

    target_id: str
    retired_at: str
    reason: str

    def __post_init__(self) -> None:
        _require_nonempty_str(self.target_id, "target_id")
        _require_nonempty_str(self.retired_at, "retired_at")
        _parse_tz_datetime(self.retired_at, "retired_at")
        _require_nonempty_str(self.reason, "reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "retired_at": self.retired_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, obj: Any) -> "Tombstone":
        if not isinstance(obj, dict):
            raise RegistryError(TYPE_ERROR, "<root>", f"tombstone must be a JSON object, got {type(obj).__name__}")
        missing = [name for name in _TOMBSTONE_FIELDS if name not in obj]
        if missing:
            raise RegistryError(MISSING_FIELD, "<root>", f"missing tombstone fields: {sorted(missing)}")
        unknown = [key for key in obj if key not in _TOMBSTONE_FIELDS]
        if unknown:
            raise RegistryError(UNKNOWN_FIELD, "<root>", f"unknown tombstone fields: {sorted(unknown)}")
        return cls(**{name: obj[name] for name in _TOMBSTONE_FIELDS})
