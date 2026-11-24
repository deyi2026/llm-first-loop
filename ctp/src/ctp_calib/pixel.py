"""角点像素噪声 → 6DoF 位姿协方差（B2 验收项：雅可比 + 协方差 + MC 对比）。

模型边界（写死，不外推）：
- 针孔相机，无畸变（畸变属于 B3 的图像处理，不进此处）；
- 平面靶标上 6 个角点（3×2 栅格），角点在靶标系的坐标已知——这是"由几何推导"的前提（K3）；
- 位姿用左扰动 ξ=(v, ω)，顺序与 uncertainty.py 一致；
- 角点像素噪声独立同分布 N(0, σ_px²)。

已知能力边界（不许外推）：**正对镜头的平面靶标**在 (tx, ωy) / (ty, ωx) 上近乎退化，条件数可达
10²–10³ 量级；此时 0.5 px 噪声可以让 tx 的 1σ 达到厘米级。这不是实现缺陷，而是几何事实——
`check_first_order_pixel` 在退化位形上会判 ok=False，读码器应避免正对位形或改用有深度差的角点
（与 SPEC G7 讨论的平面 PnP 二义性同源）。

一阶结果 Σ_pose = J⁺ Σ_px J⁺ᵀ，J⁺ = pinv(∂uv/∂ξ)；非线性校验用高斯-牛顿真解算，
即"用同一组角点重新求解位姿"，而不是把线性式反代一遍——后者是循环论证。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import se3


@dataclass(frozen=True)
class PinholeCamera:
    fx: float
    fy: float
    cx: float
    cy: float

    def __post_init__(self) -> None:
        if not (self.fx > 0 and self.fy > 0):
            raise ValueError("fx / fy must be > 0")

    def project(self, points_camera: np.ndarray) -> np.ndarray:
        points = np.asarray(points_camera, dtype=float)
        if np.any(points[:, 2] <= 0):
            raise ValueError("all corners must be in front of the camera (z > 0)")
        u = self.fx * points[:, 0] / points[:, 2] + self.cx
        v = self.fy * points[:, 1] / points[:, 2] + self.cy
        return np.stack([u, v], axis=1)

    def jacobian(self, points_camera: np.ndarray) -> np.ndarray:
        """∂(u,v)/∂p 的 2×3 块，按角点堆叠成 (2N, 3N) 稀疏块拼装由调用方完成。"""
        points = np.asarray(points_camera, dtype=float)
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        jacobian = np.zeros((points.shape[0], 2, 3))
        jacobian[:, 0, 0] = self.fx / z
        jacobian[:, 0, 2] = -self.fx * x / z**2
        jacobian[:, 1, 1] = self.fy / z
        jacobian[:, 1, 2] = -self.fy * y / z**2
        return jacobian


def planar_grid_corners(width_m: float, height_m: float) -> np.ndarray:
    """3×2 六角点栅格（z=0 平面），顺序按行优先。"""
    if not (width_m > 0 and height_m > 0):
        raise ValueError("grid dimensions must be > 0")
    xs = np.linspace(-width_m / 2.0, width_m / 2.0, 3)
    ys = np.linspace(-height_m / 2.0, height_m / 2.0, 2)
    return np.array([[x, y, 0.0] for y in ys for x in xs], dtype=float)


def _transform_points(pose: np.ndarray, points: np.ndarray) -> np.ndarray:
    return points @ pose[:3, :3].T + pose[:3, 3]


def pose_jacobian(camera: PinholeCamera, corners_target: np.ndarray, pose: np.ndarray) -> np.ndarray:
    """∂(u,v)/∂ξ，形状 (2N, 6)；ξ=(v, ω) 左扰动。"""
    points_camera = _transform_points(pose, corners_target)
    per_point = camera.jacobian(points_camera)
    count = corners_target.shape[0]
    jacobian = np.zeros((2 * count, 6))
    for index in range(count):
        # ∂p/∂v = I，∂p/∂ω = -[p]×
        rotation_part = -se3.skew(points_camera[index])
        jacobian[2 * index : 2 * index + 2, :3] = per_point[index] @ np.eye(3)
        jacobian[2 * index : 2 * index + 2, 3:] = per_point[index] @ rotation_part
    return jacobian


def covariance_from_pixel_noise(
    camera: PinholeCamera,
    corners_target: np.ndarray,
    pose: np.ndarray,
    sigma_px: float,
) -> np.ndarray:
    """J⁺ Σ_px J⁺ᵀ：一阶位姿协方差（m / rad）。"""
    if not (sigma_px > 0):
        raise ValueError("sigma_px must be > 0")
    jacobian = pose_jacobian(camera, corners_target, pose)
    pseudo_inverse = np.linalg.pinv(jacobian)
    return (sigma_px**2) * (pseudo_inverse @ pseudo_inverse.T)


def solve_pose_gauss_newton(
    camera: PinholeCamera,
    corners_target: np.ndarray,
    observed_uv: np.ndarray,
    pose_initial: np.ndarray,
    iterations: int = 20,
) -> np.ndarray:
    """非线性最小二乘（重投影误差），返回位姿；用于 MC 的"真解算"。"""
    pose = np.asarray(pose_initial, dtype=float).copy()
    for _ in range(iterations):
        jacobian = pose_jacobian(camera, corners_target, pose)
        residual = (camera.project(_transform_points(pose, corners_target)) - observed_uv).reshape(-1)
        step = np.linalg.pinv(jacobian) @ residual
        pose = se3.exp_se3(-step) @ pose
        if float(np.linalg.norm(step)) < 1e-12:
            break
    return pose


def monte_carlo_pose_from_pixels(
    camera: PinholeCamera,
    corners_target: np.ndarray,
    pose: np.ndarray,
    sigma_px: float,
    samples: int = 4000,
    seed: int = 0,
) -> dict:
    """对像素加噪后逐个做真解算，返回残差经验协方差与被排除的样本数。

    噪声大到解算跑飞（角点跑到相机背后）、或残差命中 θ→π 对数奇异（log_se3 显式拒绝）时，
    该样本被排除并计数——排除率非零即说明
    一阶模型已出域，`check_first_order_pixel` 会据此判 ok=False，不会静默丢样本。
    """
    if samples < 100:
        raise ValueError("samples must be >= 100")
    rng = np.random.default_rng(seed)
    nominal_uv = camera.project(_transform_points(pose, corners_target))
    inverse_nominal = se3.inverse(pose)
    residuals: list[np.ndarray] = []
    excluded = 0
    for _ in range(samples):
        observed = nominal_uv + rng.normal(0.0, sigma_px, nominal_uv.shape)
        # 左扰动约定：solved = exp(ξ) pose ⇒ ξ = log(solved · pose⁻¹)。
        # 写成 log(pose⁻¹ · solved) 会落到靶标系，与 J 的相机系相差一个 Ad，平移/旋转会串味。
        # 解算跑飞或残差命中 θ→π 奇异都算模型出域：排除并计数（P2-2，wave-2 审查），
        # excluded>0 → check_first_order_pixel 判 ok=False，不静默丢样本。
        try:
            solved = solve_pose_gauss_newton(camera, corners_target, observed, pose)
            residuals.append(se3.log_se3(solved @ inverse_nominal))
        except ValueError:
            excluded += 1
            continue
    if len(residuals) < 100:
        raise ValueError(f"too many diverged samples: excluded={excluded}/{samples}")
    matrix = np.array(residuals)
    return {
        "covariance": np.cov(matrix, rowvar=False),
        "samples": len(residuals),
        "excluded": excluded,
    }


def check_first_order_pixel(
    camera: PinholeCamera,
    corners_target: np.ndarray,
    pose: np.ndarray,
    sigma_px: float,
    tolerance: float = 0.05,
    samples: int = 4000,
    seed: int = 0,
) -> dict:
    from .uncertainty import compare_covariance

    linear = covariance_from_pixel_noise(camera, corners_target, pose, sigma_px)
    simulated = monte_carlo_pose_from_pixels(
        camera, corners_target, pose, sigma_px, samples=samples, seed=seed
    )
    comparison = compare_covariance(linear, simulated["covariance"])
    comparison["excluded"] = simulated["excluded"]
    comparison["ok"] = (
        comparison["max_axis_relative_error"] <= tolerance and simulated["excluded"] == 0
    )
    comparison["tolerance"] = tolerance
    comparison["samples"] = simulated["samples"]
    return comparison
