"""ctp_reader：36h11 读码器 v0（计划 B3 / B4）。

包根只导出读码器自身的符号；闸门与阈值配置从 ctp_reader.gate / ctp_reader.config 导入。
v0 只承诺合成图与近正对位形，见 ctp/docs/reader-v0-notes.md。
"""

from __future__ import annotations

from .decode36h11 import CORRECTION_CAPABILITY, DecodeResult
from .errors import ReaderError
from .reader import Reader

__all__ = [
    "CORRECTION_CAPABILITY",
    "DecodeResult",
    "Reader",
    "ReaderError",
]
