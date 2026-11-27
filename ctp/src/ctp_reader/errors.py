"""ctp_reader 稳定错误码（SPEC-20261123-CTP-0.9.2 §5 C-3 / C-4；风格对齐 ctp_contract.errors）。

本文件是 Wave-3 共享接口契约的一部分（B3 读码器 / B4 门控 / B7 一致性 runner 共用）。
新增错误码必须同步 ctp/docs/reader-v0-notes.md、gate-notes.md 与对应测试。
"""

from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_VERSION = "unknown_version"  # C-3：不可解码 / 超出纠错能力 / 未知版本——绝不输出 ID
BELOW_MIN_READABLE = "below_min_readable"  # C-4b：低于最小可读条件，门控抑制（宁可漏检不可错读）
NO_TAG_FOUND = "no_tag_found"  # 图中未定位到靶标
INVALID_INPUT = "invalid_input"  # 输入类型 / 形状 / 时间戳等非法
CONFIG_INVALID = "config_invalid"  # 配置缺失 / 越界 / 类型不符


@dataclass(eq=True)
class ReaderError(Exception):
    """一次读取失败：code 稳定、path 指向具体字段或阶段，fail-closed。"""
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
