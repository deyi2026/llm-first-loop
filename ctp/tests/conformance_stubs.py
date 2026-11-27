"""一致性 runner 测试用的读码器协议桩（按图像内容查表决定行为，不依赖 B3 是否就绪）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from ctp_contract import load_observation
from ctp_conformance.receipt import sha256_hex

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid" / "v01_minimal_code.json"
_OBSERVATION = load_observation(_FIXTURE)

Rule = Callable[[dict[str, Any]], str]


class StubError(Exception):
    """带稳定 code 的失败（对齐 ctp_reader.errors.ReaderError 的协议）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class StubReader:
    """rule(description) → "output"（返回一条合规观测）| "silent"（返回 None）| 错误码字符串。"""

    reader_id = "stub-reader"
    reader_version = "0.0.0"

    def __init__(self, samples: list[dict], rule: Rule) -> None:
        self._table = {
            sample["description"]["image_sha256"]: rule(sample["description"]) for sample in samples
        }

    def read(self, image: np.ndarray, *, timestamp: str, resolver: Any = None, degradation: str = "none"):
        key = sha256_hex(np.ascontiguousarray(image).tobytes())
        action = self._table.get(key, "no_tag_found")
        if action == "output":
            return _OBSERVATION
        if action == "silent":
            return None
        raise StubError(action)


def always(action: str) -> Rule:
    return lambda description: action


def refuse_foreign(description: dict[str, Any]) -> str:
    return "output" if description["kind"] == "known" else "unknown_version"


def gate_like(min_corners: int, min_ratio: float) -> Rule:
    return lambda description: (
        "output"
        if description["visible_corners"] >= min_corners
        and description["visible_data_ratio"] >= min_ratio
        else "below_min_readable"
    )


class UntypedErrorReader(StubReader):
    """抛不带 code 的异常——等价于协议上的"静默 / 无类型失败"。"""

    def read(self, image: np.ndarray, **kwargs: Any):
        raise RuntimeError("boom without code")
