"""C-5 不确定度声明（SPEC 11.1-c）与一阶协方差传播（计划 B2）。

两条纪律：

- **K3**：不确定度必须由几何/噪声推导，不允许手填常数。本模块只负责"把声明变成可传播的
  协方差"和"把协方差传播到派生量"，不产生任何门槛数值。
- **一阶传播有适用域**：只在扰动足够小时成立。适用与否由蒙特卡洛自检给出，不靠断言或经验
  判断——`compare_covariance` 返回逐轴相对误差，超过容差即视为一阶近似失效。

单位约定（写死）：协方差顺序 ``[tx, ty, tz, rx, ry, rz]``，平移用 m、旋转用 **rad**；
C-5 声明里的 ``rotation_1sigma_deg`` 在 `covariance()` 中一次性换算。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import se3

_SYMMETRY_TOL = 1e-9


@dataclass(frozen=True)
class UncertaintyTemplate:
    """实现方填 11.1-c 声明用的模板；`declaration()` 直接产出 C-5 的 uncertainty 块。"""

    model: str
    k: float
    translation_sigma_m: tuple[float, float, float]
    rotation_sigma_deg: tuple[float, float, float]
    covariance_6x6: tuple[tuple[float, ...], ...] | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be a non-empty identifier")
        if not (self.k > 0.0) or not math.isfinite(self.k):
            raise ValueError("coverage factor k must be a finite value > 0")
        for name, triple in (
            ("translation_sigma_m", self.translation_sigma_m),
            ("rotation_sigma_deg", self.rotation_sigma_deg),
        ):
            if len(triple) != 3:
                raise ValueError(f"{name} must have exactly 3 components")
            for value in triple:
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError(f"{name} components must be finite and >= 0")
        if self.covariance_6x6 is None:
            if all(value == 0.0 for value in (*self.translation_sigma_m, *self.rotation_sigma_deg)):
                raise ValueError("all 1σ values are zero: that is not a measurement declaration")
        else:
            matrix = np.asarray(self.covariance_6x6, dtype=float)
            if matrix.shape != (6, 6):
                raise ValueError("covariance_6x6 must be 6x6")
            if not np.allclose(matrix, matrix.T, atol=_SYMMETRY_TOL):
                raise ValueError("covariance_6x6 must be symmetric")
            if np.any(np.diag(matrix) < 0.0):
                raise ValueError("covariance_6x6 diagonal must be >= 0")

    def covariance(self) -> np.ndarray:
        """声明 → 6×6 协方差（m / rad）。"""
        if self.covariance_6x6 is not None:
            return np.asarray(self.covariance_6x6, dtype=float)
        diagonal = [
            *(float(value) ** 2 for value in self.translation_sigma_m),
            *(math.radians(float(value)) ** 2 for value in self.rotation_sigma_deg),
        ]
        return np.diag(diagonal)

    def declaration(self) -> dict:
        """C-5 `uncertainty` 字段（可直接塞进观测）。"""
        block = {
            "k": self.k,
            "model": self.model,
            "translation_1sigma_m": dict(
                zip(("x", "y", "z"), (float(value) for value in self.translation_sigma_m), strict=True)
            ),
            "rotation_1sigma_deg": dict(
                zip(("x", "y", "z"), (float(value) for value in self.rotation_sigma_deg), strict=True)
            ),
        }
        if self.covariance_6x6 is not None:
            block["covariance_6x6"] = [list(row) for row in self.covariance_6x6]
        return block


def propagate(covariance: np.ndarray, jacobian: np.ndarray) -> np.ndarray:
    """一阶传播：Σ_out = J Σ Jᵀ。"""
    covariance = np.asarray(covariance, dtype=float)
    jacobian = np.asarray(jacobian, dtype=float)
    if covariance.shape != (6, 6) or jacobian.shape[1] != 6:
        raise ValueError("expected 6x6 covariance and J with 6 columns")
    return jacobian @ covariance @ jacobian.T


def relative_covariance(
    covariance_a: np.ndarray, covariance_b: np.ndarray, pose_b: np.ndarray
) -> np.ndarray:
    """两个独立观测的相对位姿 T_ba = T_a⁻¹ T_b 的一阶协方差。

    左扰动下残差为 Ad(T_b⁻¹)(ξ_b − ξ_a)，故 Σ = Ad (Σ_a + Σ_b) Adᵀ。
    """
    adjoint_b = se3.adjoint(se3.inverse(pose_b))
    return adjoint_b @ (np.asarray(covariance_a) + np.asarray(covariance_b)) @ adjoint_b.T


def monte_carlo_relative(
    pose_a: np.ndarray,
    pose_b: np.ndarray,
    covariance_a: np.ndarray,
    covariance_b: np.ndarray,
    samples: int = 20000,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """对两个观测各做左扰动采样，返回相对位姿残差的经验协方差与残差样本。"""
    if samples < 100:
        raise ValueError("samples must be >= 100 to estimate a covariance")
    rng = np.random.default_rng(seed)
    chol_a = np.linalg.cholesky(np.asarray(covariance_a, dtype=float))
    chol_b = np.linalg.cholesky(np.asarray(covariance_b, dtype=float))
    nominal = se3.inverse(pose_a) @ pose_b
    nominal_inverse = se3.inverse(nominal)
    residuals = np.empty((samples, 6))
    for index in range(samples):
        xi_a = chol_a @ rng.standard_normal(6)
        xi_b = chol_b @ rng.standard_normal(6)
        perturbed = se3.inverse(se3.exp_se3(xi_a) @ pose_a) @ (se3.exp_se3(xi_b) @ pose_b)
        residuals[index] = se3.log_se3(nominal_inverse @ perturbed)
    return np.cov(residuals, rowvar=False), residuals


def compare_covariance(linear: np.ndarray, empirical: np.ndarray) -> dict:
    """逐轴比较一阶与蒙特卡洛标准差；返回相对误差与是否在容差内。"""
    linear = np.asarray(linear, dtype=float)
    empirical = np.asarray(empirical, dtype=float)
    linear_sigma = np.sqrt(np.clip(np.diag(linear), 0.0, None))
    empirical_sigma = np.sqrt(np.clip(np.diag(empirical), 0.0, None))
    scale = np.maximum(linear_sigma, 1e-12)
    relative = np.abs(empirical_sigma - linear_sigma) / scale
    frobenius = float(
        np.linalg.norm(empirical - linear) / max(float(np.linalg.norm(linear)), 1e-12)
    )
    return {
        "per_axis_relative_error": [float(value) for value in relative],
        "max_axis_relative_error": float(relative.max()),
        "frobenius_relative_error": frobenius,
        "linear_sigma": [float(value) for value in linear_sigma],
        "empirical_sigma": [float(value) for value in empirical_sigma],
    }


def check_first_order_validity(
    pose_a: np.ndarray,
    pose_b: np.ndarray,
    covariance_a: np.ndarray,
    covariance_b: np.ndarray,
    tolerance: float = 0.05,
    samples: int = 20000,
    seed: int = 0,
) -> dict:
    """一阶近似是否成立；`ok=False` 表示必须改用 MC 或缩小适用域，不得照抄线性结果。"""
    linear = relative_covariance(covariance_a, covariance_b, pose_b)
    empirical, residuals = monte_carlo_relative(
        pose_a, pose_b, covariance_a, covariance_b, samples=samples, seed=seed
    )
    comparison = compare_covariance(linear, empirical)
    comparison["ok"] = comparison["max_axis_relative_error"] <= tolerance
    comparison["tolerance"] = tolerance
    comparison["samples"] = samples
    comparison["residual_mean"] = [float(value) for value in np.mean(residuals, axis=0)]
    return comparison
