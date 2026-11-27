"""B7 合成样本（确定性）：由 ctp_gen 的位图真值渲染单靶灰度图并构造故障。

几何口径（与 B3 读码器证据定义一致）：图像按单元格组成，每格 SCALE 像素；
外圈 QUIET 格静区 + 10×10 核（核自带 1 格静区、8×8 黑边框、6×6 数据区）。
靶标外四角 = 核边框四角；"可见"= 完整落在图像内。
"""

from __future__ import annotations

import numpy as np

from ctp_gen import codes
from ctp_gen import tag36h11_table as table
from .receipt import sha256_hex

TIMESTAMP = "2026-11-24T12:00:00+08:00"  # 合成样本的采集时刻（固定；C-5 timestamp 字段）
SCALE = 12  # 每格像素（测试参数）
QUIET = 4  # 核外静区格数（测试参数；核内自带 1 格）
BLACK = 0
WHITE = 255
GRAY = 128

LEAK_TYPES = ("occlusion", "beyond_ec", "skew_unreadable")
FORGERY_TYPES = ("wrong_id", "copied_tag", "interlevel_pose_contradiction")
FORGERY_REASONS = {
    "wrong_id": "错 ID 依赖注册表语义绑定与 M-2b 几何互证，二者均未实现（状态机 F-1–F-5 亦未实现）",
    "copied_tag": "复制靶标依赖 M-2b 几何互证，未实现",
    "interlevel_pose_contradiction": "级间位姿矛盾依赖回退状态机 F-1–F-5 与 F-3 判定回路，未实现",
}


def render_grid(grid: list[list[bool]], scale: int = SCALE, quiet: int = QUIET) -> np.ndarray:
    """位图 → uint8 灰度图（True = 黑）。"""
    core = np.asarray(grid, dtype=bool)
    if core.shape != (table.TOTAL_WIDTH, table.TOTAL_WIDTH):
        raise ValueError("grid must be square with the family's total width")
    padded = np.pad(core, pad_width=quiet, constant_values=False)
    return np.where(padded, BLACK, WHITE).astype(np.uint8).repeat(scale, axis=0).repeat(scale, axis=1)


def render_tag(index: int) -> np.ndarray:
    return render_grid(codes.bit_matrix(index))


def word_of_grid(grid: list[list[bool]]) -> int:
    """按 ctp_gen 钉定的位序把 10×10 位图读回 36 位码字。"""
    word = 0
    for i in range(table.NBITS):
        bit = grid[table.BIT_Y[i] + 1][table.BIT_X[i] + 1]
        word |= (1 if bit else 0) << (table.NBITS - 1 - i)
    return word


def min_hamming(word: int) -> int:
    return min(bin(word ^ code).count("1") for code in table.CODES)


def min_hamming_rotations(grid: list[list[bool]]) -> int:
    """四个取向下与 587 个码字的最小汉明距离（读码器会尝试旋转， foreign 样本须四个取向都不可解码）。"""
    current = [list(row) for row in grid]
    best = 1 << 30
    for _ in range(4):
        best = min(best, min_hamming(word_of_grid(current)))
        current = np.rot90(np.asarray(current)).astype(bool).tolist()
    return best


def index_with_dark_data_columns(count: int) -> int:
    """前 count 列数据位每列都有暗格的合法码。

    裁剪后包围盒是否贴到左沿取决于剩余首列有没有暗格：选码时保证有，几何真值才成立。
    """
    for index in range(table.NCODES):
        grid = codes.bit_matrix(index)
        if all(any(grid[y][2 + column] for y in range(2, 8)) for column in range(count)):
            return index
    raise RuntimeError("no codeword with a dark cell in every requested data column")


def foreign_grid(index: int, *, n_flips: int = 6, rng: np.random.Generator | None = None) -> list[list[bool]]:
    """在合法码上翻转 ≥ n_flips 个数据位，直到四个取向下最小汉明距离都 > 纠错能力（5）。

    代表"其他版本族 / 被破坏到超出纠错能力"的码：按 C-2b 任何合规读码器都不得输出 ID。
    """
    generator = rng if rng is not None else np.random.default_rng(0)
    if n_flips <= table.MIN_HAMMING // 2:
        raise ValueError("n_flips must exceed the family's correction capability")
    for _ in range(10_000):
        grid = codes.bit_matrix(index)
        positions = generator.choice(table.NBITS, size=n_flips, replace=False)
        for i in positions:
            x = table.BIT_X[int(i)] + 1
            y = table.BIT_Y[int(i)] + 1
            grid[y][x] = not grid[y][x]
        if min_hamming_rotations(grid) > table.MIN_HAMMING // 2:
            return grid
    raise RuntimeError("could not construct a non-decodable foreign pattern")


def unrelated_grid(rng: np.random.Generator) -> list[list[bool]]:
    """与 36h11 无关的随机图案（黑边框保留、数据区随机，四取向均超出纠错能力）。"""
    for _ in range(10_000):
        grid = [[False] * table.TOTAL_WIDTH for _ in range(table.TOTAL_WIDTH)]
        for y in range(table.TOTAL_WIDTH):
            for x in range(table.TOTAL_WIDTH):
                on_ring = x in (1, table.WIDTH_AT_BORDER) or y in (1, table.WIDTH_AT_BORDER)
                if on_ring and 1 <= x <= table.WIDTH_AT_BORDER and 1 <= y <= table.WIDTH_AT_BORDER:
                    grid[y][x] = True
        for i in range(table.NBITS):
            grid[table.BIT_Y[i] + 1][table.BIT_X[i] + 1] = bool(rng.integers(0, 2))
        if min_hamming_rotations(grid) > table.MIN_HAMMING // 2:
            return grid
    raise RuntimeError("could not construct an unrelated non-decodable pattern")


def crop_corners(image: np.ndarray, remove: int, *, scale: int = SCALE, quiet: int = QUIET) -> np.ndarray:
    """裁掉靶标的 1–3 条边（外角落到图像之外）。remove ∈ {1, 2, 3} → 可见角点 1 / 2 / 0。

    矩形裁剪裁掉的是整条边而不是单个角：逐值几何见 geometry()，与 _VISIBLE_CORNERS 一致。
    """
    if remove not in (1, 2, 3):
        raise ValueError("remove must be 1, 2 or 3")
    cut = (quiet + 2) * scale  # 越过核内静区与边框各一格
    top = cut if remove in (1, 3) else 0
    left = cut if remove in (1, 2, 3) else 0
    right = image.shape[1] - cut if remove == 3 else image.shape[1]
    return image[top:, left:right]


def crop_data_column(image: np.ndarray, *, scale: int = SCALE, quiet: int = QUIET) -> np.ndarray:
    """再向内裁一格：左侧两个角点出界且数据区最左一列（6 个数据格）出界 → 可见比例 5/6。"""
    cut = (quiet + 3) * scale
    return image[:, cut:]


def unreadable(image: np.ndarray, *, rng: np.random.Generator, scale: int = SCALE, quiet: int = QUIET) -> np.ndarray:
    """信息被毁的靶标：黑边框与静区保留（靶标仍可定位），数据区置为均匀灰并加微噪声。

    任何对它输出的 ID 都是无依据的（对应 V8 漏检类"贴歪不可读 → 不输出 + 计数上报"）。
    """
    out = image.copy()
    # 数据区 = 核内第 2..7 格（含），即 [quiet+2, quiet+WIDTH_AT_BORDER) 个单元格
    first = (quiet + 2) * scale
    last = (quiet + table.WIDTH_AT_BORDER) * scale
    noise = rng.integers(-3, 4, size=(last - first, last - first)).astype(np.int16)
    out[first:last, first:last] = np.clip(GRAY + noise, 0, 255).astype(np.uint8)
    return out


_VISIBLE_CORNERS = {0: 4, 1: 1, 2: 2, 3: 0}


def geometry(remove: int, data_column_lost: bool = False) -> dict[str, float]:
    """样本的几何真值（runner 据此分组，不依赖读码器的自述）。

    角点可见 = 该角相邻的两段黑边框都完整。矩形裁剪裁掉的是整条边而不是单个角：
    - remove=2 只裁左边 → 左边框没了 → 左上、左下不完整 → 可见 2；
    - remove=1 裁上边和左边 → 上、左两条边框都没了 → 只剩右下完整 → 可见 1；
    - remove=3 裁左、上、右 → 三条边框没了 → 可见 0。
    """
    if remove not in (0, 1, 2, 3):
        raise ValueError("remove must be in 0..3")
    ratio = (6 - 1) / 6 if data_column_lost else 1.0
    return {"visible_corners": _VISIBLE_CORNERS[remove], "visible_data_ratio": ratio}


def make_sample(
    kind: str, sample_id: str, fault_type: str, expected: str, image: np.ndarray, **extra: object
) -> dict:
    """样本 = 描述（进哈希）+ 图像（不进哈希，但记录其内容 sha256）。"""
    description = {
        "sample_id": sample_id,
        "kind": kind,
        "fault_type": fault_type,
        "expected": expected,
        "image_sha256": sha256_hex(np.ascontiguousarray(image).tobytes()),
        "shape": [int(image.shape[0]), int(image.shape[1])],
    }
    description.update(extra)
    return {"description": description, "image": image}


def descriptions(samples: list[dict]) -> list[dict]:
    return [sample["description"] for sample in samples]
