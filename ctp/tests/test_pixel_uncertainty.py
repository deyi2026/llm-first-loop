"""B2 验收项：角点像素噪声 → 6DoF 位姿协方差（雅可比 + 一阶 + 蒙特卡洛）。

判据分两类，缺一不可：
- **能力成立**：良态位形（带俯仰的非共面角点）上一阶与 MC 逐轴误差 ≤ 5%；
- **边界成立**：退化位形（正对镜头的平面靶标）必须被判 ok=False——1σ 达到厘米级是几何事实，
  不是实现缺陷；极端噪声必须被排除计数并判失败。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import ctp_calib as calib  # noqa: E402
import ctp_calib.pixel as pixel  # noqa: E402

CAMERA = pixel.PinholeCamera(800.0, 800.0, 640.0, 360.0)
SIGMA_PX = 0.5
TOL = 0.05


def _nonplanar_corners() -> np.ndarray:
    corners = pixel.planar_grid_corners(0.3, 0.2).copy()
    corners[1::2, 2] = 0.06
    return corners


def _tilted_pose() -> np.ndarray:
    half = math.radians(20.0)
    return calib.pose_matrix((0.15, -0.05, 1.5), (0.0, math.sin(half), 0.0, math.cos(half)))


def _front_pose() -> np.ndarray:
    return calib.pose_matrix((0.0, 0.0, 1.5), (0.0, 0.0, 0.0, 1.0))


def test_jacobian_matches_numeric_differentiation():
    corners = pixel.planar_grid_corners(0.3, 0.2)
    pose = _front_pose()
    analytic = pixel.pose_jacobian(CAMERA, corners, pose)
    step = 1e-7
    numeric = np.zeros_like(analytic)
    for axis in range(6):
        xi = np.zeros(6)
        xi[axis] = step
        plus = CAMERA.project(pixel._transform_points(calib.exp_se3(xi) @ pose, corners)).reshape(-1)
        minus = CAMERA.project(pixel._transform_points(calib.exp_se3(-xi) @ pose, corners)).reshape(-1)
        numeric[:, axis] = (plus - minus) / (2 * step)
    assert np.abs(numeric - analytic).max() < 1e-5


def test_well_conditioned_geometry_agrees_with_monte_carlo():
    result = pixel.check_first_order_pixel(
        CAMERA, _nonplanar_corners(), _tilted_pose(), SIGMA_PX, tolerance=TOL, samples=400, seed=3
    )
    assert result["ok"], result
    assert result["max_axis_relative_error"] <= TOL, result
    assert result["excluded"] == 0


def test_fronto_parallel_geometry_is_flagged_degenerate():
    """正对镜头的平面靶标：(tx, ωy) 近乎不可分，一阶与 MC 不一致必须被如实判失败。"""
    result = pixel.check_first_order_pixel(
        CAMERA,
        pixel.planar_grid_corners(0.3, 0.2),
        _front_pose(),
        SIGMA_PX,
        tolerance=TOL,
        samples=400,
        seed=3,
    )
    assert result["ok"] is False, result
    assert result["linear_sigma"][0] > 0.01, "退化位形上 tx 的 1σ 应在厘米级"


def test_extreme_noise_exceeds_model_domain():
    result = pixel.check_first_order_pixel(
        CAMERA,
        pixel.planar_grid_corners(0.3, 0.2),
        _front_pose(),
        30.0,
        tolerance=TOL,
        samples=200,
        seed=3,
    )
    assert result["ok"] is False, result
    assert result["max_axis_relative_error"] > 0.2, result


def test_covariance_scales_with_sigma_squared():
    corners = _nonplanar_corners()
    pose = _tilted_pose()
    small = pixel.covariance_from_pixel_noise(CAMERA, corners, pose, 0.5)
    large = pixel.covariance_from_pixel_noise(CAMERA, corners, pose, 1.0)
    assert np.allclose(large, small * 4.0)


def test_noise_free_solve_returns_nominal_pose():
    corners = _nonplanar_corners()
    pose = _tilted_pose()
    observed = CAMERA.project(pixel._transform_points(pose, corners))
    solved = pixel.solve_pose_gauss_newton(CAMERA, corners, observed, pose)
    assert np.allclose(solved, pose, atol=1e-9)


def test_camera_rejects_points_behind():
    try:
        CAMERA.project(np.array([[0.0, 0.0, -1.0]]))
    except ValueError:
        return
    raise AssertionError("相机背后的点未被拒绝")


def _run_all() -> int:
    failures = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print(f"PASS {name}")
            except Exception as error:  # noqa: BLE001 - 手工 runner 需要打印所有失败
                failures += 1
                print(f"FAIL {name}: {type(error).__name__}: {error}")
    print(f"failures={failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
