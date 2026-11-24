"""读码器测试公用件：合成图、相机、读码器构造、四元数回算。数字只作测试参数。"""

from __future__ import annotations

import numpy as np

from ctp_calib.pixel import PinholeCamera
from ctp_conformance.synth import QUIET, SCALE, render_tag
from ctp_gen import codes
from ctp_gen import tag36h11_table as table
from ctp_reader.config import ThresholdConfig
from ctp_reader.gate import ReadGate
from ctp_reader.reader import Reader

TIMESTAMP = "2026-11-24T12:00:00+08:00"
TAG_SIZE_M = 0.05  # 靶标黑边框外沿边长（测试参数）
SIGMA_PX = 0.3
COVERAGE_K = 2.0
FX = FY = 800.0


def camera(width: int, height: int) -> PinholeCamera:
    return PinholeCamera(fx=FX, fy=FY, cx=width / 2.0, cy=height / 2.0)


def make_reader(*, min_corners: int = 4, min_ratio: float = 1.0, width: int = 216, height: int = 216, **overrides) -> Reader:
    fields = dict(
        gate=ReadGate(ThresholdConfig(min_visible_corners=min_corners, min_visible_data_ratio=min_ratio)),
        camera=camera(width, height),
        tag_size_m=TAG_SIZE_M,
        sigma_px=SIGMA_PX,
        coverage_factor_k=COVERAGE_K,
        reader_id="reader-v0-test",
        reader_version="0.0.1",
        frame_ref="frame:test/tag",
    )
    fields.update(overrides)
    return Reader(**fields)


def expected_depth() -> float:
    return FX * TAG_SIZE_M / (table.WIDTH_AT_BORDER * SCALE)


def translate(image: np.ndarray, dx: int, dy: int, canvas: tuple[int, int] = (300, 340)) -> np.ndarray:
    out = np.full(canvas, 255, dtype=np.uint8)
    height, width = image.shape
    out[dy : dy + height, dx : dx + width] = image
    return out


def cell_block(image: np.ndarray, cx: int, cy: int) -> tuple[slice, slice]:
    first_y = (QUIET + cy) * SCALE
    first_x = (QUIET + cx) * SCALE
    return slice(first_y, first_y + SCALE), slice(first_x, first_x + SCALE)


def flip_data_bits(image: np.ndarray, positions) -> np.ndarray:
    """把指定数据位（按码字位序）的整格像素反色。"""
    out = image.copy()
    for index in positions:
        rows, cols = cell_block(out, table.BIT_X[index] + 1, table.BIT_Y[index] + 1)
        out[rows, cols] = 255 - out[rows, cols]
    return out


def noisy_and_blurred(image: np.ndarray, sigma: float, seed: int) -> np.ndarray:
    padded = np.pad(image.astype(np.float64), pad_width=1, mode="edge")  # uint8 相加会溢出
    blurred = sum(padded[dy : dy + image.shape[0], dx : dx + image.shape[1]] for dy in range(3) for dx in range(3)) / 9.0
    rng = np.random.default_rng(seed)
    return np.clip(blurred + rng.normal(0.0, sigma, image.shape), 0, 255).astype(np.uint8)


def crop_left(image: np.ndarray, cells: int) -> np.ndarray:
    return image[:, cells * SCALE :]


def crop_top_left(image: np.ndarray, cells: int) -> np.ndarray:
    return image[cells * SCALE :, cells * SCALE :]


def index_with_dark_data_columns(count: int) -> int:
    """找一个前 count 列数据位里每列都有暗格的合法码（裁剪后包围盒仍贴到左沿）。"""
    for index in range(table.NCODES):
        grid = codes.bit_matrix(index)
        if all(any(grid[y][2 + column] for y in range(2, 8)) for column in range(count)):
            return index
    raise RuntimeError("no suitable index")


def quaternion_to_matrix(quaternion) -> np.ndarray:
    x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
