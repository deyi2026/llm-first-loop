"""一致性 runner 回执（B7）：机器可读、simulated 恒真、样本集哈希稳定、三值判定。

verdict 规则（写死，不随 runner 变）：
- 任一硬断言失败（failures 非空）→ fail；
- 无硬断言失败，但存在无法演练的样本（not_exercisable 非空）或阈值 / 上限未配置 → indeterminate；
- 否则 pass。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASS = "pass"
FAIL = "fail"
INDETERMINATE = "indeterminate"

SIMULATED_NOTE = (
    "simulated：合成 / 数值样本，不构成门槛实测证据；实测前禁止对外宣称任何性能数字（SPEC §0.2、§11.2）"
)
NOT_CONFIGURED = "not_configured"


def canonical_json(obj: Any) -> str:
    """确定性 JSON：键排序、无空白、ASCII。"""
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sample_set_sha256(descriptions: list[dict[str, Any]]) -> str:
    """样本集哈希：对规范化样本描述列表（不含图像本体）的确定性 JSON 做 sha256。"""
    if not isinstance(descriptions, list) or not all(isinstance(item, dict) for item in descriptions):
        raise ValueError("descriptions must be a list of dicts")
    return sha256_hex(canonical_json(descriptions).encode("utf-8"))


def _is_limit(value: Any) -> bool:
    """上限 / 样本量是否为已配置的有限数值（None、[TBD-*] 字符串都算未配置）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


@dataclass
class Receipt:
    """一次 runner 运行的回执。finalize() 依据 failures / not_exercisable / 未配置项重算 verdict。"""

    suite: str
    simulated: bool
    sample_set_sha256: str
    thresholds_used: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    not_exercisable: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reader: dict[str, Any] = field(default_factory=dict)
    verdict: str = INDETERMINATE

    def __post_init__(self) -> None:
        if self.simulated is not True:
            # v0 只有合成数据：拒绝生成一份"非 simulated"的回执（不得冒充实测）
            raise ValueError("v0 runners only produce simulated receipts; simulated must be True")
        self.notes.append(SIMULATED_NOTE)

    def finalize(self) -> "Receipt":
        unconfigured = [
            key
            for key, value in self.thresholds_used.items()
            if value == NOT_CONFIGURED or (isinstance(value, str) and value.startswith("[TBD-"))
        ]
        if self.failures:
            self.verdict = FAIL
        elif self.not_exercisable or unconfigured:
            self.verdict = INDETERMINATE
        else:
            self.verdict = PASS
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "simulated": self.simulated,
            "sample_set_sha256": self.sample_set_sha256,
            "thresholds_used": dict(self.thresholds_used),
            "counts": dict(self.counts),
            "verdict": self.verdict,
            "failures": list(self.failures),
            "not_exercisable": list(self.not_exercisable),
            "notes": list(self.notes),
            "reader": dict(self.reader),
        }

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


def reader_identity(reader: Any) -> dict[str, Any]:
    """记录被测读码器身份（取得到就记，取不到标 unknown——不猜）。"""
    identity = {}
    for key in ("reader_id", "reader_version"):
        value = getattr(reader, key, None)
        identity[key] = value if isinstance(value, str) and value else "unknown"
    return identity


def error_code(error: BaseException) -> str | None:
    """协议：读码器失败必须抛带稳定 code 的异常；取不到 code 视为静默 / 无类型失败。"""
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else None


def is_limit(value: Any) -> bool:
    return _is_limit(value)
