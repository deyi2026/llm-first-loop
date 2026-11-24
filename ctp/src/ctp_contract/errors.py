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


@dataclass(eq=True)
class ContractError(Exception):
    """一次契约违规：code 稳定、path 指向具体字段。"""
    # 不用 frozen=True：冻结 dataclass 生成的 __setattr__ 会拦下 __traceback__ 的赋值，
    # 异常一旦穿过 contextlib 类上下文管理器（含 pytest 内部）就会被 FrozenInstanceError 顶替，
    # fail-closed 的稳定错误码随之丢失。字段只读与可哈希由下面的方法保持。

    code: str
    path: str
    detail: str

    def __setattr__(self, name: str, value: object) -> None:
        # 字段构造后只读；其余属性（__traceback__ / __cause__ 等）正常可写
        if name in ("code", "path", "detail") and name in self.__dict__:
            raise AttributeError(f"cannot assign to field {name!r}")
        object.__setattr__(self, name, value)

    def __hash__(self) -> int:
        return hash((self.code, self.path, self.detail))

    def __str__(self) -> str:  # pragma: no cover - 仅用于诊断输出
        where = self.path or "<root>"
        return f"{self.code} @ {where}: {self.detail}"
