"""36h11 解码（B3 v0）：按 ctp_gen 钉定的位序取 36 个数据位，四个取向取最小汉明距离。

纠错纪律（SPEC §5 C-2b、C-3b）：只有在纠错能力内且候选唯一时才输出 ID；
否则一律 unknown_version，绝不输出"最近的那个"。不完整落在图像内的数据位当未知位（erasure）处理：
设未知位 e、已知位上的错误 t，码字最小距离 d = 11，唯一解码要求 2t + e ≤ d − 1 = 10，
因此纠错预算 t = ⌊(10 − e) / 2⌋；e > 10 时直接拒解。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ctp_gen import tag36h11_table as table

from .errors import UNKNOWN_VERSION, ReaderError
from .image import CellGrid

CORRECTION_CAPABILITY = table.MIN_HAMMING // 2  # 36h11：无未知位时可纠正 ≤5 位（码族事实）
MAX_ERASURES = table.MIN_HAMMING - 1  # 10：2t + e ≤ d − 1 的右端
MIN_KNOWN_BITS = table.NBITS - MAX_ERASURES  # 26：未知位超过 10 个就无法保证唯一解码


@dataclass(frozen=True)
class DecodeResult:
    target_index: int
    hamming_distance: int
    quarter_turns: int  # 为把码字摆正而对格阵施加的 90° 旋转次数
    known_bits: int


def sample_cells(image: np.ndarray, grid: CellGrid) -> tuple[np.ndarray, np.ndarray]:
    """返回 10×10 的（是否为暗, 是否已知）。未知 = 单元格不完整落在图像内。"""
    dark = np.zeros((table.TOTAL_WIDTH, table.TOTAL_WIDTH), dtype=bool)
    known = np.zeros((table.TOTAL_WIDTH, table.TOTAL_WIDTH), dtype=bool)
    for cy in range(table.TOTAL_WIDTH):
        for cx in range(table.TOTAL_WIDTH):
            value = grid.median(image, cx, cy)
            if value is None:
                continue
            known[cy, cx] = True
            dark[cy, cx] = value <= grid.threshold
    return dark, known


def _word_and_mask(dark: np.ndarray, known: np.ndarray) -> tuple[int, int]:
    word = 0
    mask = 0
    for index in range(table.NBITS):
        x = table.BIT_X[index] + 1
        y = table.BIT_Y[index] + 1
        word |= (1 if dark[y, x] else 0) << (table.NBITS - 1 - index)
        mask |= (1 if known[y, x] else 0) << (table.NBITS - 1 - index)
    return word, mask


def decode(dark: np.ndarray, known: np.ndarray) -> DecodeResult:
    """四取向解码。成功返回 DecodeResult；否则抛 unknown_version。"""
    best: DecodeResult | None = None
    for turns in range(4):
        turned_dark = np.rot90(dark, turns)
        turned_known = np.rot90(known, turns)
        word, mask = _word_and_mask(turned_dark, turned_known)
        known_bits = bin(mask).count("1")
        budget = (MAX_ERASURES - (table.NBITS - known_bits)) // 2  # 2t + e ≤ d − 1
        if known_bits < MIN_KNOWN_BITS or budget < 0:
            continue
        distances = [bin((word ^ code) & mask).count("1") for code in table.CODES]
        minimum = min(distances)
        candidates = [index for index, distance in enumerate(distances) if distance == minimum]
        if minimum <= budget and len(candidates) == 1:
            if best is None or minimum < best.hamming_distance:
                best = DecodeResult(candidates[0], minimum, turns, known_bits)
    if best is None:
        raise ReaderError(
            UNKNOWN_VERSION,
            "data_bits",
            "no unique 36h11 codeword within the correction budget "
            f"(2t + e <= {MAX_ERASURES}; t = errors over known bits, e = unknown bits; 4 orientations)",
        )
    return best
