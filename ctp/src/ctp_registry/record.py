"""R-1 注册表记录与签名基元（SPEC-20261123-CTP-0.9.2 §6 R-1 / R-5）。

设计边界（对齐 ctp_calib 的"写死模型边界"纪律）：
- 只承载 SPEC R-1 列举的最小字段集；ID 的位长 / 前缀格式细则属 C-1 [TBD-G]（G1 提案），
  本层只要求非空字符串，不做位长裁决（TODO-G2：位长随 G1 决议补格式校验）；
- 确定性 JSON = 键排序 + 无空白 + ensure_ascii（D-08 执行期暂定值：Ed25519 + 确定性 JSON，
  偏离原"确定性 CBOR"建议；确认时点 = B5 原型完成、对外签发格式定稿前，见 PLAN §13.1）；
- 签名载荷 = 无 signature 字段的记录确定性 JSON 之 sha256 摘要；Ed25519 对摘要签名；
- fail-closed：缺字段 / 类型不符 / 非正周期 / 无时区时间戳一律抛 RegistryError（稳定 code +
  path + detail），无默认值填充；
- 本层不裁决"复验周期应是多少天"——revalidate_period_days 是必填参数；任何门槛数值属
  SPEC 11.2 实测与工作组决议，实现层禁止发明（SPEC 前言 0.2）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ---- 错误码清单（风格对齐 ctp_contract.errors；新增码必须同步 ctp/docs/registry-notes.md 与 ctp/tests/test_registry.py）----
MISSING_FIELD = "missing_field"
TYPE_ERROR = "type_error"
UNKNOWN_FIELD = "unknown_field"
FORMAT_ERROR = "format_error"
VALUE_OUT_OF_RANGE = "value_out_of_range"
TIMESTAMP_MISSING_TIMEZONE = "timestamp_missing_timezone"
MISSING_SIGNATURE = "missing_signature"
SIGNATURE_INVALID = "signature_invalid"
SIGNATURE_FORMAT_ERROR = "signature_format_error"
NO_SIGNED_RECORD = "no_signed_record"
TOMBSTONE_REUSE = "tombstone_reuse"
TOMBSTONED_ID = "tombstoned_id"
CHAIN_BROKEN = "chain_broken"
PAYLOAD_TAMPERED = "payload_tampered"
VERSION_REGRESSION = "version_regression"
UNKNOWN_ID = "unknown_id"
ALREADY_TOMBSTONED = "already_tombstoned"
SNAPSHOT_INVALID = "snapshot_invalid"
QUARANTINED_RECORD = "quarantined_record"

_SIGNATURE_BYTES = 64  # Ed25519 签名固定长度（RFC 8032）


@dataclass(eq=True)
class RegistryError(Exception):
    """一次注册表违规：code 稳定、path 指向具体字段或行号。"""
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


def canonical_json(obj: Any) -> str:
    """确定性 JSON：键排序、无空白、ASCII 转义（D-08 暂定序列化，见模块 docstring）。"""
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _require_nonempty_str(value: Any, path: str) -> None:
    if not isinstance(value, str) or isinstance(value, bool):
        raise RegistryError(TYPE_ERROR, path, f"{path!r} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise RegistryError(FORMAT_ERROR, path, f"{path!r} must be a non-empty, non-blank string")


def _parse_tz_datetime(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError(FORMAT_ERROR, path, f"{path!r} is not ISO 8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegistryError(TIMESTAMP_MISSING_TIMEZONE, path, f"{path!r} must carry a timezone offset")
    return parsed


def _require_signature_hex(value: Any, path: str) -> None:
    if not isinstance(value, str) or isinstance(value, bool):
        raise RegistryError(TYPE_ERROR, path, "signature must be a hex str or null")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise RegistryError(SIGNATURE_FORMAT_ERROR, path, "signature is not valid hex") from exc
    if len(raw) != _SIGNATURE_BYTES:
        raise RegistryError(
            SIGNATURE_FORMAT_ERROR, path, f"signature must be {_SIGNATURE_BYTES} bytes, got {len(raw)}"
        )


_RECORD_FIELDS = (
    "target_id",
    "object_ref",
    "frame_ref",
    "installed_on",
    "last_verified",
    "revalidate_period_days",
    "record_version",
    "signature",
)


@dataclass(frozen=True)
class RegistryRecord:
    """R-1 注册表记录：ID、所属对象、参考系定义、安装日期、上次验证时间、复验周期、记录版本、签名。

    - target_id：逻辑 ID（C-1）；本层不解析前缀 / 位长（TODO-G2，随 G1 决议补）；
    - frame_ref：参考系定义的引用（引用本体属 M-2 几何登记，不在此层）；
    - revalidate_period_days：复验周期（天）。必填、无默认——数值裁决权属健康档案与工作组；
    - signature：Ed25519 对 payload_digest() 的签名（hex）；None = 未签名（不得用于语义绑定，R-5）。
    """

    target_id: str
    object_ref: str
    frame_ref: str
    installed_on: str
    last_verified: str
    revalidate_period_days: float
    record_version: int
    signature: str | None = None

    def __post_init__(self) -> None:
        for name in ("target_id", "object_ref", "frame_ref"):
            _require_nonempty_str(getattr(self, name), name)
        _require_nonempty_str(self.installed_on, "installed_on")
        try:
            date.fromisoformat(self.installed_on)
        except ValueError as exc:
            raise RegistryError(
                FORMAT_ERROR, "installed_on", f"installed_on must be YYYY-MM-DD, got {self.installed_on!r}"
            ) from exc
        _require_nonempty_str(self.last_verified, "last_verified")
        _parse_tz_datetime(self.last_verified, "last_verified")

        period = self.revalidate_period_days
        if isinstance(period, bool) or not isinstance(period, (int, float)):
            raise RegistryError(TYPE_ERROR, "revalidate_period_days", "must be a number (days)")
        if period <= 0:
            raise RegistryError(VALUE_OUT_OF_RANGE, "revalidate_period_days", f"must be > 0, got {period}")
        object.__setattr__(self, "revalidate_period_days", float(period))

        version = self.record_version
        if isinstance(version, bool) or not isinstance(version, int):
            raise RegistryError(TYPE_ERROR, "record_version", "must be an int")
        if version < 1:
            raise RegistryError(VALUE_OUT_OF_RANGE, "record_version", f"must be >= 1, got {version}")

        if self.signature is not None:
            _require_signature_hex(self.signature, "signature")
            object.__setattr__(self, "signature", self.signature.lower())

    # ---- 确定性序列化 ----

    def payload_dict(self) -> dict[str, Any]:
        """签名载荷：R-1 字段除 signature 外（R-5 验签对象）。"""
        return {
            "target_id": self.target_id,
            "object_ref": self.object_ref,
            "frame_ref": self.frame_ref,
            "installed_on": self.installed_on,
            "last_verified": self.last_verified,
            "revalidate_period_days": self.revalidate_period_days,
            "record_version": self.record_version,
        }

    def payload_canonical(self) -> str:
        return canonical_json(self.payload_dict())

    def payload_digest(self) -> bytes:
        """签名载荷摘要 = 确定性 JSON 的 sha256（D-08 暂定：换序列化器不改此结构）。"""
        return hashlib.sha256(self.payload_canonical().encode("utf-8")).digest()

    def to_dict(self) -> dict[str, Any]:
        out = self.payload_dict()
        out["signature"] = self.signature
        return out

    def to_json_line(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, obj: Any) -> "RegistryRecord":
        if not isinstance(obj, dict):
            raise RegistryError(TYPE_ERROR, "<root>", f"record must be a JSON object, got {type(obj).__name__}")
        missing = [name for name in _RECORD_FIELDS if name not in obj]
        if missing:
            raise RegistryError(MISSING_FIELD, "<root>", f"missing record fields: {sorted(missing)}")
        unknown = [key for key in obj if key not in _RECORD_FIELDS]
        if unknown:
            raise RegistryError(UNKNOWN_FIELD, "<root>", f"unknown record fields: {sorted(unknown)}")
        return cls(**{name: obj[name] for name in _RECORD_FIELDS})

    @classmethod
    def from_json_line(cls, line: str) -> "RegistryRecord":
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RegistryError(FORMAT_ERROR, "<root>", f"line is not valid JSON: {line[:80]!r}") from exc
        return cls.from_dict(obj)


# ---- 签名基元（R-5 的记录级实现；快照级见 snapshot.py）----


def sign_record(record: RegistryRecord, private_key: Ed25519PrivateKey) -> RegistryRecord:
    """用权威私钥对未签名记录签名，返回带 signature 的新记录（frozen，不原地改写）。"""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RegistryError(TYPE_ERROR, "private_key", "must be an Ed25519PrivateKey")
    signature = private_key.sign(record.payload_digest()).hex()
    return replace(record, signature=signature)


def verify_signature(record: RegistryRecord, public_key: Ed25519PublicKey) -> None:
    """验签：无签名抛 MISSING_SIGNATURE；不匹配抛 SIGNATURE_INVALID。通过则静默返回。"""
    if not isinstance(public_key, Ed25519PublicKey):
        raise RegistryError(TYPE_ERROR, "public_key", "must be an Ed25519PublicKey")
    if record.signature is None:
        raise RegistryError(
            MISSING_SIGNATURE, "signature", f"record {record.target_id!r} carries no signature (R-5)"
        )
    try:
        public_key.verify(bytes.fromhex(record.signature), record.payload_digest())
    except InvalidSignature as exc:
        raise RegistryError(
            SIGNATURE_INVALID, "signature", f"signature does not match payload of {record.target_id!r}"
        ) from exc
    except ValueError as exc:  # 防御：hex 损坏（post_init 已拦，双保险）
        raise RegistryError(SIGNATURE_FORMAT_ERROR, "signature", "signature is not valid hex") from exc
