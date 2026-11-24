"""B2：不确定度声明 + 一阶协方差传播 + 蒙特卡洛自检。

验收口径（计划 §4.2 B2）：与 MC 误差 ≤ 5%；声明可直接填 C-5。
另有"检测器有效性"用例：构造应被判定失效的输入，验证 check_first_order_validity 会拒绝
（门槛类实现必须实测"应拦输入"，不能只测"能过"）。
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
from ctp_contract import parse_observation  # noqa: E402

TOL = 0.05


def _diag(translation_m: float, rotation_deg: float) -> np.ndarray:
    return np.diag([translation_m**2] * 3 + [math.radians(rotation_deg) ** 2] * 3)


def _scenario():
    pose_a = calib.pose_matrix((0.0, 0.0, 1.2), (0.0, 0.0, 0.0, 1.0))
    half = math.radians(15.0)
    pose_b = calib.pose_matrix((1.0, 0.5, 1.5), (0.0, 0.0, math.sin(half), math.cos(half)))
    return pose_a, pose_b


def test_template_declaration_is_accepted_by_c5():
    template = calib.UncertaintyTemplate(
        model="iso-gum-linear-v0",
        k=2.0,
        translation_sigma_m=(0.0007, 0.0007, 0.0009),
        rotation_sigma_deg=(0.17, 0.17, 0.2),
    )
    observation = {
        "target_index": 3,
        "logical_id": "0x03",
        "resolution": "code",
        "pose": {
            "position_m": {"x": 0.0, "y": 0.0, "z": 1.2},
            "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "frame_ref": "REG-FRAME-0001",
        },
        "uncertainty": template.declaration(),
        "degradation_flag": "none",
        "timestamp": "2026-11-23T10:00:00+08:00",
        "reader_id": "unit",
        "reader_version": "0.0.1",
    }
    parsed = parse_observation(observation)
    assert parsed.uncertainty.k == 2.0
    assert parsed.uncertainty.model == "iso-gum-linear-v0"


def test_rotation_sigma_is_converted_from_degrees():
    template = calib.UncertaintyTemplate("m", 2.0, (0.001, 0.001, 0.001), (1.0, 1.0, 1.0))
    diagonal = np.diag(template.covariance())
    assert np.isclose(diagonal[0], 1e-6)
    assert np.isclose(diagonal[3], math.radians(1.0) ** 2)
    assert diagonal[3] < 1e-3


def test_template_rejects_degenerate_or_invalid_declarations():
    bad: list[dict] = [
        {"model": "", "k": 2.0, "translation_sigma_m": (1e-3, 1e-3, 1e-3), "rotation_sigma_deg": (0.1,) * 3},
        {"model": "m", "k": 0.0, "translation_sigma_m": (1e-3, 1e-3, 1e-3), "rotation_sigma_deg": (0.1,) * 3},
        {"model": "m", "k": 2.0, "translation_sigma_m": (-1e-3, 1e-3, 1e-3), "rotation_sigma_deg": (0.1,) * 3},
        {"model": "m", "k": 2.0, "translation_sigma_m": (0.0, 0.0, 0.0), "rotation_sigma_deg": (0.0, 0.0, 0.0)},
        {"model": "m", "k": 2.0, "translation_sigma_m": (1e-3, 1e-3), "rotation_sigma_deg": (0.1,) * 3},
    ]
    for payload in bad:
        try:
            calib.UncertaintyTemplate(**payload)
        except ValueError:
            continue
        raise AssertionError(f"非法声明被接受: {payload}")


def test_relative_covariance_agrees_with_monte_carlo():
    pose_a, pose_b = _scenario()
    covariance = _diag(0.0007, 0.17)
    result = calib.check_first_order_validity(
        pose_a, pose_b, covariance, covariance, tolerance=TOL, samples=20000, seed=7
    )
    assert result["ok"], result
    assert result["max_axis_relative_error"] <= TOL, result
    assert result["frobenius_relative_error"] <= TOL, result


def test_detector_rejects_input_that_breaks_first_order():
    """应拦输入：60° 的位姿 1σ 已远超一阶近似的适用域。"""
    pose_a, pose_b = _scenario()
    covariance = _diag(0.0007, 60.0)
    result = calib.check_first_order_validity(
        pose_a, pose_b, covariance, covariance, tolerance=TOL, samples=20000, seed=7
    )
    assert result["ok"] is False, result
    if result.get("reason") == "pi_singularity":
        return  # σ 过大命中 θ→π 奇异：同样判不通过（fail-closed）
    assert result["max_axis_relative_error"] > TOL


def test_monte_carlo_is_reproducible():
    pose_a, pose_b = _scenario()
    covariance = _diag(0.0007, 0.17)
    first, _ = calib.monte_carlo_relative(pose_a, pose_b, covariance, covariance, samples=4000, seed=3)
    second, _ = calib.monte_carlo_relative(pose_a, pose_b, covariance, covariance, samples=4000, seed=3)
    assert np.allclose(first, second)


def test_propagate_rejects_wrong_shapes():
    covariance = np.eye(6)
    try:
        calib.propagate(covariance, np.eye(3))
    except ValueError:
        return
    raise AssertionError("形状不匹配未被拒绝")


def test_se3_exp_log_roundtrip():
    for xi in (
        np.array([0.001, -0.002, 0.003, 1e-4, -2e-4, 3e-4]),
        np.array([0.2, 0.1, -0.3, 0.4, -0.5, 0.6]),
        np.zeros(6),
    ):
        assert np.allclose(calib.log_se3(calib.exp_se3(xi)), xi, atol=1e-9)


def test_adjoint_matches_pure_translation_form():
    transform = calib.pose_matrix((0.3, -0.2, 1.1), (0.0, 0.0, 0.0, 1.0))
    expected = np.eye(6)
    expected[:3, 3:] = calib.skew(np.array([0.3, -0.2, 1.1]))
    assert np.allclose(calib.adjoint(transform), expected)


def test_rotation_only_uncertainty_couples_only_through_force_arm():
    """纯旋转不确定度：零力臂处不产生平移方差；非零力臂处必产生（钉住 Adjoint 结构）。"""
    covariance = _diag(0.0, 0.17)
    zero_arm = calib.relative_covariance(covariance, covariance, np.eye(4))
    assert np.allclose(zero_arm[:3, :3], 0.0)

    pose_b = calib.pose_matrix((0.3, -0.2, 1.1), (0.0, 0.0, 0.0, 1.0))
    nonzero_arm = calib.relative_covariance(covariance, covariance, pose_b)
    assert np.any(np.abs(nonzero_arm[:3, :3]) > 1e-6)


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


def test_log_se3_rejects_pi_rotation():
    """应拦输入：180° 旋转的对数映射奇异（轴符号不可定），必须显式报错而非返回垃圾。"""
    half_pi_pose = calib.pose_matrix((0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 0.0))
    try:
        calib.log_se3(half_pi_pose)
    except ValueError:
        return
    raise AssertionError("180° 旋转未被 log_se3 拒绝")


def test_template_rejects_zero_sigma_even_with_covariance():
    """应拦输入：1σ 全零即使附带协方差也要拒绝（与 C-5 validator 对齐）。"""
    zeros = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    covariance = [[0.0] * 6 for _ in range(6)]
    covariance[3][3] = 1e-4
    try:
        calib.UncertaintyTemplate("m", 2.0, *zeros, covariance_6x6=tuple(tuple(r) for r in covariance))
    except ValueError:
        return
    raise AssertionError("全零 1σ + 非零协方差被接受")


def test_singular_covariance_is_typed_failure():
    """应拦输入（wave-2 r4 P2-3）：某轴方差为 0 的奇异协方差过 PSD 容差，MC 必须类型化失败而非裸 LinAlgError。"""
    pose_a, pose_b = _scenario()
    singular = _diag(0.0007, 0.17)
    singular[5, 5] = 0.0  # 半正定但不可 Cholesky
    try:
        calib.monte_carlo_relative(pose_a, pose_b, singular, singular, samples=200, seed=1)
    except ValueError as error:
        assert "singular" in str(error)
    else:
        raise AssertionError("奇异协方差未被 monte_carlo_relative 拒绝")
    result = calib.check_first_order_validity(pose_a, pose_b, singular, singular, samples=200, seed=1)
    assert result["ok"] is False, result
    assert result["reason"] == "invalid_covariance"


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
