"""位姿层（B3 v0）：靶标黑边框外四角 → PnP（复用 ctp_calib.pixel）→ 协方差 → C-5 姿态与不确定度声明。

约定：
- tag_size_m = 靶标黑边框外沿边长（8 格）。注意 B6 布局里的 size_mm 覆盖含静区的 10 格，两者相差 1.25 倍；
- 图像角点顺序 = 左上、右上、右下、左下；靶标系 x 向右、y 向下、z 垂直靶面向里（与相机系同向），
  摆正（未旋转）的靶标姿态为单位旋转；
- 四元数把靶标系向量旋转到相机系（v_cam = q ⊗ v_tag ⊗ q*）；
- 协方差顺序 [tx, ty, tz, rx, ry, rz]，单位 m / rad（ctp_calib 约定）；C-5 的旋转 1σ 用 deg，
  只在生成声明时换算一次。旋转分量是相机系左扰动切空间里的量，见 reader-v0-notes.md。
- v0 用 4 个外角点做平面 PnP：SPEC G7 讨论的平面位姿二义性未在此消解。
"""

from __future__ import annotations

import math

import numpy as np

from ctp_calib import pixel as pixel_model
from ctp_calib.uncertainty import UncertaintyTemplate
from ctp_contract import Uncertainty, Vector3

from .image import BORDER_CELLS, CellGrid

UNCERTAINTY_MODEL = "reader-v0-pixel-first-order"


def _z_rotation(angle: float) -> np.ndarray:
    cos, sin = math.cos(angle), math.sin(angle)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def target_corners(tag_size_m: float, quarter_turns: int) -> np.ndarray:
    """靶标系里与图像角点顺序（左上、右上、右下、左下）对应的四个外角点。

    码字需转 r 次 90° 才摆正 ⇒ 靶标在图像里逆时针转了 (4−r)·90° ⇒ 姿态 P = Rz(r·90°)，
    图像左上角对应靶标点 P⁻¹·B0，以此类推。
    """
    half = tag_size_m / 2.0
    base = np.array(
        [[-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0]]
    )
    rotation = _z_rotation(-quarter_turns * math.pi / 2.0)
    return base @ rotation.T


def image_corners(grid: CellGrid) -> np.ndarray:
    """靶标黑边框外沿四角的像素坐标（左上、右上、右下、左下）。外沿占核坐标 1..9。"""
    left = grid.x0 + grid.cell
    top = grid.y0 + grid.cell
    right = grid.x0 + (BORDER_CELLS + 1) * grid.cell
    bottom = grid.y0 + (BORDER_CELLS + 1) * grid.cell
    return np.array([[left, top], [right, top], [right, bottom], [left, bottom]])


def solve_pose(
    camera: pixel_model.PinholeCamera,
    grid: CellGrid,
    *,
    tag_size_m: float,
    quarter_turns: int,
    sigma_px: float,
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (4×4 位姿, 6×6 协方差)。初值：姿态取 90° 整数倍旋转，位置取靶心反投影。"""
    corners_target = target_corners(tag_size_m, quarter_turns)
    corners_image = image_corners(grid)
    side_px = grid.cell * BORDER_CELLS
    depth = camera.fx * tag_size_m / side_px
    center_u = float(corners_image[:, 0].mean())
    center_v = float(corners_image[:, 1].mean())
    initial = np.eye(4)
    initial[:3, :3] = _z_rotation(quarter_turns * math.pi / 2.0)
    initial[0, 3] = (center_u - camera.cx) * depth / camera.fx
    initial[1, 3] = (center_v - camera.cy) * depth / camera.fy
    initial[2, 3] = depth
    pose = pixel_model.solve_pose_gauss_newton(camera, corners_target, corners_image, initial)
    covariance = pixel_model.covariance_from_pixel_noise(camera, corners_target, pose, sigma_px)
    return pose, covariance


def rotation_to_quaternion(rotation: np.ndarray) -> tuple[float, float, float, float]:
    """旋转矩阵 → 单位四元数 (x, y, z, w)（Shepperd 法，数值稳定）。"""
    m = np.asarray(rotation, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quat = (
            (m[2, 1] - m[1, 2]) / scale,
            (m[0, 2] - m[2, 0]) / scale,
            (m[1, 0] - m[0, 1]) / scale,
            0.25 * scale,
        )
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        scale = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        quat = (
            0.25 * scale,
            (m[0, 1] + m[1, 0]) / scale,
            (m[0, 2] + m[2, 0]) / scale,
            (m[2, 1] - m[1, 2]) / scale,
        )
    elif m[1, 1] > m[2, 2]:
        scale = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        quat = (
            (m[0, 1] + m[1, 0]) / scale,
            0.25 * scale,
            (m[1, 2] + m[2, 1]) / scale,
            (m[0, 2] - m[2, 0]) / scale,
        )
    else:
        scale = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        quat = (
            (m[0, 2] + m[2, 0]) / scale,
            (m[1, 2] + m[2, 1]) / scale,
            0.25 * scale,
            (m[1, 0] - m[0, 1]) / scale,
        )
    norm = math.sqrt(sum(component * component for component in quat))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("rotation matrix is not a proper rotation; cannot convert to quaternion")
    return quat[0] / norm, quat[1] / norm, quat[2] / norm, quat[3] / norm


def declaration(coverage_factor_k: float, covariance: np.ndarray) -> Uncertainty:
    """协方差对角（m / rad）→ C-5 不确定度声明（平移 m、旋转 deg，k 原样带出）。

    先过 ctp_calib.UncertaintyTemplate 的校验（k > 0、σ 非负且不全零），再转成 C-5 的 Uncertainty。
    """
    diagonal = np.diag(np.asarray(covariance, dtype=float))
    translation = tuple(math.sqrt(max(float(value), 0.0)) for value in diagonal[:3])
    rotation_deg = tuple(math.degrees(math.sqrt(max(float(value), 0.0))) for value in diagonal[3:])
    template = UncertaintyTemplate(
        model=UNCERTAINTY_MODEL,
        k=coverage_factor_k,
        translation_sigma_m=translation,  # type: ignore[arg-type]
        rotation_sigma_deg=rotation_deg,  # type: ignore[arg-type]
    )
    return Uncertainty(
        k=template.k,
        model=template.model,
        translation_1sigma_m=Vector3(*template.translation_sigma_m),
        rotation_1sigma_deg=Vector3(*template.rotation_sigma_deg),
        covariance_6x6=None,
    )
