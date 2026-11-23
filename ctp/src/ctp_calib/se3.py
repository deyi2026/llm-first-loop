"""SE(3) 小工具：四元数→旋转矩阵、指数/对数映射、左扰动与 Adjoint。

约定（与 C-5 字段顺序一致，写死在代码里，不靠注释传递）：
- 切空间向量顺序 = [v(3), ω(3)]：先平移、后旋转；
- 扰动为**左扰动** T̃ = exp(ξ^) T；
- 角度一律 rad；C-5 声明里的 deg 只在 uncertainty.py 的边界处转换一次。

本模块只做数学，不含任何 CTP 门槛数值（K3：不确定度必须从几何/噪声推导）。
"""

from __future__ import annotations

import math

import numpy as np

_UNIT_TOL = 1e-3
_ANGLE_EPS = 1e-8


def skew(vector: np.ndarray) -> np.ndarray:
    x, y, z = vector
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], dtype=float)


def quaternion_to_matrix(quaternion: tuple[float, float, float, float]) -> np.ndarray:
    """(x, y, z, w) → 3×3 旋转矩阵；模长偏离 1 超过 1e-3 直接拒绝。"""
    x, y, z, w = (float(item) for item in quaternion)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if abs(norm - 1.0) > _UNIT_TOL:
        raise ValueError(f"quaternion norm {norm:.9f} is not unit")
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def pose_matrix(
    position: tuple[float, float, float],
    quaternion: tuple[float, float, float, float],
) -> np.ndarray:
    transform = np.eye(4)
    transform[:3, :3] = quaternion_to_matrix(quaternion)
    transform[:3, 3] = np.asarray(position, dtype=float)
    return transform


def exp_se3(xi: np.ndarray) -> np.ndarray:
    xi = np.asarray(xi, dtype=float).reshape(6)
    v, w = xi[:3], xi[3:]
    theta = float(np.linalg.norm(w))
    omega = skew(w)
    if theta < _ANGLE_EPS:
        rotation = np.eye(3) + omega + 0.5 * omega @ omega
        jacobian = np.eye(3) + 0.5 * omega + (1.0 / 6.0) * omega @ omega
    else:
        rotation = (
            np.eye(3)
            + (math.sin(theta) / theta) * omega
            + ((1.0 - math.cos(theta)) / theta**2) * omega @ omega
        )
        jacobian = (
            np.eye(3)
            + ((1.0 - math.cos(theta)) / theta**2) * omega
            + ((theta - math.sin(theta)) / theta**3) * omega @ omega
        )
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = jacobian @ v
    return transform


def log_se3(transform: np.ndarray) -> np.ndarray:
    rotation = np.asarray(transform, dtype=float)[:3, :3]
    translation = np.asarray(transform, dtype=float)[:3, 3]
    cos_theta = max(-1.0, min(1.0, (float(np.trace(rotation)) - 1.0) / 2.0))
    theta = math.acos(cos_theta)
    if theta < _ANGLE_EPS:
        w = 0.5 * np.array(
            [
                rotation[2, 1] - rotation[1, 2],
                rotation[0, 2] - rotation[2, 0],
                rotation[1, 0] - rotation[0, 1],
            ]
        )
        omega = skew(w)
        v_inverse = np.eye(3) - 0.5 * omega + (1.0 / 12.0) * omega @ omega
    else:
        w = (theta / (2.0 * math.sin(theta))) * np.array(
            [
                rotation[2, 1] - rotation[1, 2],
                rotation[0, 2] - rotation[2, 0],
                rotation[1, 0] - rotation[0, 1],
            ]
        )
        omega = skew(w)
        coefficient = (1.0 / theta**2) * (
            1.0 - (theta * math.sin(theta)) / (2.0 * (1.0 - math.cos(theta)))
        )
        v_inverse = np.eye(3) - 0.5 * omega + coefficient * omega @ omega
    return np.concatenate([v_inverse @ translation, w])


def adjoint(transform: np.ndarray) -> np.ndarray:
    """6×6 Adjoint（v/ω 顺序）；满足 T exp(ξ^) T⁻¹ = exp((Ad_T ξ)^)。"""
    transform = np.asarray(transform, dtype=float)
    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    result = np.zeros((6, 6))
    result[:3, :3] = rotation
    result[:3, 3:] = skew(translation) @ rotation
    result[3:, 3:] = rotation
    return result


def inverse(transform: np.ndarray) -> np.ndarray:
    transform = np.asarray(transform, dtype=float)
    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    result = np.eye(4)
    result[:3, :3] = rotation.T
    result[:3, 3] = -rotation.T @ translation
    return result
