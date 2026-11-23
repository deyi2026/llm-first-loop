"""C-5 契约错误类型。

错误码是契约的一部分：实现方据此给出可复核的拒绝理由（K6 fail-closed），
不得用"默认值 + 静默通过"替代报错。
"""

from __future__ import annotations

from dataclasses import dataclass

# 错误码清单（新增码必须同步 ctp/README.md 与 ctp/tests/test_contract_invalid.py）
MISSING_FIELD = "missing_field"
TYPE_ERROR = "type_error"
UNKNOWN_FIELD = "unknown_field"
ENUM_ERROR = "enum_error"
RANGE_ERROR = "range_error"
LINKAGE_ERROR = "linkage_error"
FORMAT_ERROR = "format_error"
QUATERNION_NOT_UNIT = "quaternion_not_unit"
TIMESTAMP_MISSING_TIMEZONE = "timestamp_missing_timezone"
COVARIANCE_NOT_SYMMETRIC = "covariance_not_symmetric"
DEGENERATE_UNCERTAINTY = "degenerate_uncertainty"


@dataclass(frozen=True)
class ContractError(Exception):
    """一次契约违规：code 稳定、path 指向具体字段。"""

    code: str
    path: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - 仅用于诊断输出
        where = self.path or "<root>"
        return f"{self.code} @ {where}: {self.detail}"
