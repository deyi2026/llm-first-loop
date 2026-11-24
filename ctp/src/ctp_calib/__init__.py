"""CTP 标定数学：不确定度声明与一阶协方差传播（计划 B2）。"""

from __future__ import annotations

from .pixel import (
    PinholeCamera,
    covariance_from_pixel_noise,
    planar_grid_corners,
    pose_jacobian,
    solve_pose_gauss_newton,
)
from .se3 import adjoint, exp_se3, inverse, log_se3, pose_matrix, quaternion_to_matrix, skew
from .uncertainty import (
    UncertaintyTemplate,
    check_first_order_validity,
    compare_covariance,
    monte_carlo_relative,
    propagate,
    relative_covariance,
)

__all__ = [
    "PinholeCamera",
    "UncertaintyTemplate",
    "covariance_from_pixel_noise",
    "adjoint",
    "check_first_order_validity",
    "compare_covariance",
    "exp_se3",
    "inverse",
    "log_se3",
    "monte_carlo_relative",
    "planar_grid_corners",
    "pose_jacobian",
    "pose_matrix",
    "propagate",
    "quaternion_to_matrix",
    "relative_covariance",
    "skew",
    "solve_pose_gauss_newton",
]
