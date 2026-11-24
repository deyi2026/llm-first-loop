"""码字封装：索引 → 36h11 码字 → 10×10 单元格位图（确定性）。"""

from __future__ import annotations

from . import tag36h11_table as table


def code_at(index: int) -> int:
    """板内索引 → 码字；越界即报错（fail-closed，无默认值）。"""
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError("target_index must be an integer")
    if not 0 <= index < table.NCODES:
        raise ValueError(f"target_index {index} out of range 0..{table.NCODES - 1}")
    return table.CODES[index]


def bit_matrix(index: int) -> list[list[bool]]:
    """索引 → 10×10 位图（行 = y，列 = x；True = 黑）。

    结构：外圈 1 单元格 quiet zone（白）；8×8 核外圈黑边；内部 6×6 数据区。
    位序：bit i（0 起，MSB 在前，bit 0 = 码字第 35 位）落在 (BIT_X[i]+1, BIT_Y[i]+1)
    ——上游表坐标 1..6 平移到核内 2..7。此映射为本参考实现的钉定口径，
    B3 必须一致；与官方检测器的互操作在 V6 前复核。
    """
    code = code_at(index)
    grid = [[False] * table.TOTAL_WIDTH for _ in range(table.TOTAL_WIDTH)]
    for y in range(table.TOTAL_WIDTH):
        for x in range(table.TOTAL_WIDTH):
            if x in (0, table.TOTAL_WIDTH - 1) or y in (0, table.TOTAL_WIDTH - 1):
                continue  # quiet zone，保持白
            if x in (1, table.WIDTH_AT_BORDER) or y in (1, table.WIDTH_AT_BORDER):
                grid[y][x] = True  # 核外圈黑边
    for i in range(table.NBITS):
        x = table.BIT_X[i] + 1
        y = table.BIT_Y[i] + 1
        grid[y][x] = bool((code >> (table.NBITS - 1 - i)) & 1)
    return grid


def family_invariants() -> dict:
    """码族自检：数量、成对最小汉明距离、位映射覆盖。"""
    codes = table.CODES
    worst = min(
        bin(codes[i] ^ codes[j]).count("1")
        for i in range(len(codes))
        for j in range(i + 1, len(codes))
    )
    cells = {(table.BIT_X[i], table.BIT_Y[i]) for i in range(table.NBITS)}
    return {
        "family": table.FAMILY,
        "ncodes": len(codes),
        "nbits": table.NBITS,
        "min_pairwise_hamming": worst,
        "declared_min_hamming": table.MIN_HAMMING,
        "bit_cells_distinct": len(cells) == table.NBITS,
        "invariant_ok": (
            len(codes) == table.NCODES
            and worst >= table.MIN_HAMMING
            and len(cells) == table.NBITS
        ),
    }
