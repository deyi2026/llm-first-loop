"""图像层（B3 v0）：输入校验、Otsu 二值化、单靶外框定位、单元格采样与几何证据。

v0 能力边界（如实，不外推）：
- 只支持轴对齐的单枚 36h11 靶标：平移、90° 整数倍旋转、整数格放大、中等噪声 / 模糊；
- 靶标外框 = 暗像素包围盒（= 黑边框外沿，8 格见方）；背景或静区出现大面积暗斑会破坏定位；
- 靶标两个方向同时被图像边界截断 → 无法估计格宽 → no_tag_found；
- 格宽估计出错时由"边框环必须全黑"的校验兜底（fail-closed，不会带着错格宽往下解码）；
- "角点可见" = 该角相邻的两段黑边框单元格都完整落在图像内且为暗；
  "数据位可见" = 该数据格完整落在图像内。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ctp_gen import tag36h11_table as table

from .errors import INVALID_INPUT, NO_TAG_FOUND, ReaderError

BORDER_CELLS = table.WIDTH_AT_BORDER  # 靶标黑边框外沿边长 = 8 格（1 黑边 + 6 数据 + 1 黑边）
SQUARE_TOLERANCE_PX = 2  # 轴对齐正方形外框的宽高差容差（像素级工程常量，不是门槛数值）
CENTRAL_FRACTION = 0.5  # 单元格取中位灰度时使用中心区域的比例（工程常量，不是门槛数值）

# 每个角相邻的三个边框单元格（核坐标，x 向右、y 向下；边框在第 1 与第 8 格）
_CORNER_CELLS = (
    ((1, 1), (2, 1), (1, 2)),  # 左上
    ((8, 1), (7, 1), (8, 2)),  # 右上
    ((8, 8), (7, 8), (8, 7)),  # 右下
    ((1, 8), (2, 8), (1, 7)),  # 左下
)


def validate(image: object) -> np.ndarray:
    """输入校验：2 维 uint8 灰度图；其余一律 invalid_input（不做类型强转）。"""
    if not isinstance(image, np.ndarray) or image.ndim != 2 or image.dtype != np.uint8:
        raise ReaderError(INVALID_INPUT, "image", "expected a 2-D uint8 grayscale ndarray")
    if image.shape[0] < BORDER_CELLS or image.shape[1] < BORDER_CELLS:
        raise ReaderError(INVALID_INPUT, "image", f"image too small for one tag: {image.shape}")
    return image


def otsu_threshold(image: np.ndarray) -> int:
    """Otsu 阈值：暗 = 像素值 ≤ 阈值。全黑 / 全白图像下夹到 [1, 254]，不产生退化阈值。"""
    histogram = np.bincount(image.ravel(), minlength=256).astype(np.float64)
    levels = np.arange(256, dtype=np.float64)
    weight_dark = np.cumsum(histogram)
    sum_dark = np.cumsum(histogram * levels)
    weight_light = weight_dark[-1] - weight_dark
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_dark = sum_dark / weight_dark
        mean_light = (sum_dark[-1] - sum_dark) / weight_light
    between = weight_dark * weight_light * (mean_dark - mean_light) ** 2
    between[~np.isfinite(between)] = -1.0
    threshold = int(np.argmax(between))
    return min(max(threshold, 1), 254)


@dataclass(frozen=True)
class CellGrid:
    """靶标核的格阵：左上角像素坐标、格宽、图像尺寸、二值化阈值。核坐标 (0..9, 0..9)。"""

    x0: float
    y0: float
    cell: float
    width: int
    height: int
    threshold: int

    def block(self, cx: int, cy: int) -> tuple[float, float, float, float]:
        left = self.x0 + cx * self.cell
        top = self.y0 + cy * self.cell
        return left, top, left + self.cell, top + self.cell

    def inside(self, cx: int, cy: int) -> bool:
        """单元格是否完整落在图像内。"""
        left, top, right, bottom = self.block(cx, cy)
        slack = 1e-6
        return left >= -slack and top >= -slack and right <= self.width + slack and bottom <= self.height + slack

    def median(self, image: np.ndarray, cx: int, cy: int) -> float | None:
        """单元格中心区域的灰度中位数；单元格不完整落在图像内时返回 None（未知）。"""
        if not self.inside(cx, cy):
            return None
        left, top, right, bottom = self.block(cx, cy)
        margin = self.cell * (1.0 - CENTRAL_FRACTION) / 2.0
        x_lo = min(int(math.ceil(left + margin)), self.width - 1)
        y_lo = min(int(math.ceil(top + margin)), self.height - 1)
        x_hi = max(int(math.floor(right - margin)), x_lo + 1)
        y_hi = max(int(math.floor(bottom - margin)), y_lo + 1)
        patch = image[y_lo:y_hi, x_lo:x_hi]
        return float(np.median(patch))


def locate_tag(image: np.ndarray) -> CellGrid:
    """定位单枚靶标并估计格阵。找不到 / 非正方形 / 双向截断 / 边框校验不过 → no_tag_found。"""
    threshold = otsu_threshold(image)
    dark = image <= threshold
    rows = np.flatnonzero(dark.any(axis=1))
    cols = np.flatnonzero(dark.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        raise ReaderError(NO_TAG_FOUND, "image", "no dark region: tag not found")
    x0, x1 = int(cols[0]), int(cols[-1])
    y0, y1 = int(rows[0]), int(rows[-1])
    height_px = y1 - y0 + 1
    width_px = x1 - x0 + 1
    cut_x = x0 == 0 or x1 == image.shape[1] - 1
    cut_y = y0 == 0 or y1 == image.shape[0] - 1
    if cut_x and cut_y:
        raise ReaderError(
            NO_TAG_FOUND, "image", "tag is cut on both axes; cell size cannot be estimated in v0"
        )
    if not cut_x and not cut_y:
        if abs(width_px - height_px) > SQUARE_TOLERANCE_PX:
            raise ReaderError(
                NO_TAG_FOUND,
                "image",
                f"dark region is not square ({width_px}x{height_px}px): non-axis-aligned or not a tag",
            )
        cell = (width_px + height_px) / (2.0 * BORDER_CELLS)
        # 包围盒左沿 = 黑边框外沿 = 核坐标 1；格阵原点取核坐标 0，故回退一格
        origin_x, origin_y = float(x0) - cell, float(y0) - cell
    elif cut_x:
        # 高度完整：用高度定格宽，再用完整的右沿反推左上角
        cell = height_px / BORDER_CELLS
        origin_x = x1 - (BORDER_CELLS + 1) * cell + 1.0  # 右沿 = 核坐标 9 的外侧
        origin_y = float(y0) - cell
    else:
        cell = width_px / BORDER_CELLS
        origin_x = float(x0) - cell
        origin_y = y1 - (BORDER_CELLS + 1) * cell + 1.0  # 下沿 = 核坐标 9 的外侧
    if cell < 1.0:
        raise ReaderError(NO_TAG_FOUND, "image", f"estimated cell size {cell:.2f}px is below one pixel")
    grid = CellGrid(origin_x, origin_y, cell, int(image.shape[1]), int(image.shape[0]), threshold)
    _verify_border(image, grid)
    return grid


def _verify_border(image: np.ndarray, grid: CellGrid) -> None:
    """边框环（第 1、8 行列）上完整落在图像内的单元格必须全为暗——格宽估错或图案无框都在这里被拦。"""
    last = table.WIDTH_AT_BORDER
    checked = 0
    for cy in range(table.TOTAL_WIDTH):
        for cx in range(table.TOTAL_WIDTH):
            on_border = (cx in (1, last) and 1 <= cy <= last) or (cy in (1, last) and 1 <= cx <= last)
            if not on_border or not grid.inside(cx, cy):
                continue
            checked += 1
            if grid.median(image, cx, cy) > grid.threshold:
                raise ReaderError(
                    NO_TAG_FOUND, "border", f"border cell ({cx},{cy}) is not dark: not a tag or grid misaligned"
                )
    if checked == 0:
        raise ReaderError(NO_TAG_FOUND, "border", "no border cell lies inside the image")


def visible_corners(image: np.ndarray, grid: CellGrid) -> int:
    """完整角点数：该角相邻的三个边框单元格都完整落在图像内且为暗。"""
    count = 0
    for cells in _CORNER_CELLS:
        if all(
            grid.inside(cx, cy) and grid.median(image, cx, cy) <= grid.threshold for cx, cy in cells
        ):
            count += 1
    return count


def visible_data_ratio(grid: CellGrid) -> float:
    """数据位可见比例：36 个数据格里完整落在图像内的比例（几何口径，不识别遮挡）。"""
    visible = sum(
        1 for index in range(table.NBITS) if grid.inside(table.BIT_X[index] + 1, table.BIT_Y[index] + 1)
    )
    return visible / table.NBITS
