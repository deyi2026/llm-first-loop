"""B3 · 读码器端到端：C-5 全字段、姿态、闸门先于解码、解析状态、配置必填、自检失败不返回。"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from ctp_contract import DegradationFlag, Resolution, parse_observation

from ctp_conformance.synth import foreign_grid, render_grid, render_tag
from ctp_reader import Reader
from ctp_reader import pose as pose_module
from ctp_reader import reader as reader_module
from ctp_reader.errors import BELOW_MIN_READABLE, CONFIG_INVALID, INVALID_INPUT, UNKNOWN_VERSION, ReaderError
from reader_testkit import (
    COVERAGE_K,
    FX,
    TIMESTAMP,
    crop_left,
    expected_depth,
    index_with_dark_data_columns,
    make_reader,
    quaternion_to_matrix,
    translate,
)


def test_read_returns_a_conforming_c5_observation():
    reader = make_reader()
    observation = reader.read(render_tag(7), timestamp=TIMESTAMP)
    assert observation.target_index == 7
    assert observation.resolution is Resolution.UNRESOLVED  # 36h11 板内索引不等于全局 ID（C-1d）
    assert observation.logical_id is None
    assert observation.degradation_flag is DegradationFlag.NONE
    assert observation.timestamp == TIMESTAMP
    assert (observation.reader_id, observation.reader_version) == ("reader-v0-test", "0.0.1")
    assert observation.pose.frame_ref == "frame:test/tag"
    assert observation.uncertainty.k == COVERAGE_K
    assert observation.uncertainty.model == pose_module.UNCERTAINTY_MODEL
    assert all(value > 0 for value in observation.uncertainty.translation_1sigma_m.as_dict().values())
    assert all(value > 0 for value in observation.uncertainty.rotation_1sigma_deg.as_dict().values())
    assert parse_observation(observation.as_dict()) == observation  # 产出自身就是合规 C-5


def test_pose_is_fronto_parallel_at_the_expected_depth():
    observation = make_reader().read(render_tag(0), timestamp=TIMESTAMP)
    position = observation.pose.position_m
    depth = expected_depth()
    assert position.z == pytest.approx(depth, abs=1e-6)
    assert position.x == pytest.approx(0.0, abs=1e-6)
    assert position.y == pytest.approx(0.0, abs=1e-6)
    quaternion = observation.pose.quaternion
    assert (quaternion.x, quaternion.y, quaternion.z, quaternion.w) == pytest.approx((0.0, 0.0, 0.0, 1.0), abs=1e-6)


def test_translation_moves_the_position_by_back_projection():
    reader = make_reader(width=300, height=340)
    observation = reader.read(translate(render_tag(7), 20, 50), timestamp=TIMESTAMP)
    depth = expected_depth()
    center_u, center_v = 20 + 108, 50 + 108  # 靶心像素（216×216 的图放在 (20, 50) 处）
    assert observation.pose.position_m.x == pytest.approx((center_u - 150.0) * depth / FX, abs=1e-6)
    assert observation.pose.position_m.y == pytest.approx((center_v - 170.0) * depth / FX, abs=1e-6)
    assert observation.pose.position_m.z == pytest.approx(depth, abs=1e-6)


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_rotated_image_gives_the_matching_quarter_turn_pose(turns):
    """码字需转 r 次 90° 才摆正 ⇒ 姿态 = Rz(r·90°)（相机系 x 右、y 下、z 向前）；位置不变。"""
    observation = make_reader().read(np.rot90(render_tag(7), turns), timestamp=TIMESTAMP)
    r = (4 - turns) % 4
    angle = r * math.pi / 2.0
    expected = np.array(
        [[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]]
    )
    assert np.allclose(quaternion_to_matrix(observation.pose.quaternion), expected, atol=1e-6)
    assert observation.pose.position_m.z == pytest.approx(expected_depth(), abs=1e-6)


def test_tag_size_scales_the_estimated_depth():
    reader = make_reader(tag_size_m=0.1)
    observation = reader.read(render_tag(7), timestamp=TIMESTAMP)
    assert observation.pose.position_m.z == pytest.approx(2.0 * expected_depth(), abs=1e-6)


def test_gate_suppresses_before_decoding_and_counts_it():
    """C-4b：闸门不过就不解码、不输出；抑制被计数。用外来图案做被裁的图，证明没有偷偷解码。"""
    reader = make_reader(min_corners=4)
    index = index_with_dark_data_columns(1)
    with pytest.raises(ReaderError) as excinfo:
        reader.read(crop_left(render_tag(index), 6), timestamp=TIMESTAMP)
    assert excinfo.value.code == BELOW_MIN_READABLE
    assert "below_min_corners" in excinfo.value.detail
    assert reader._gate.suppressed_count == 1
    # 同一张图把阈值放到 2 个角点即可读通，说明抑制来自闸门而不是解码失败
    lenient = make_reader(min_corners=2)
    assert lenient.read(crop_left(render_tag(index), 6), timestamp=TIMESTAMP).target_index == index


def test_unknown_version_is_refused_without_an_index():
    with pytest.raises(ReaderError) as excinfo:
        make_reader().read(render_grid(foreign_grid(7, n_flips=6)), timestamp=TIMESTAMP)
    assert excinfo.value.code == UNKNOWN_VERSION
    assert not hasattr(excinfo.value, "target_index")


def test_resolver_and_degradation_flag_are_passed_through():
    reader = make_reader()
    resolved = reader.read(render_tag(7), timestamp=TIMESTAMP, resolver=lambda index: f"ORG-0001:{index:08d}", degradation="coarse")
    assert resolved.resolution is Resolution.RESOLVED
    assert resolved.logical_id == "ORG-0001:00000007"
    assert resolved.degradation_flag is DegradationFlag.COARSE
    empty = reader.read(render_tag(7), timestamp=TIMESTAMP, resolver=lambda index: "   ")
    assert empty.resolution is Resolution.UNRESOLVED and empty.logical_id is None


def test_invalid_timestamp_and_degradation_are_rejected():
    reader = make_reader()
    with pytest.raises(ReaderError) as excinfo:
        reader.read(render_tag(7), timestamp="2026-11-24T12:00:00")
    assert (excinfo.value.code, excinfo.value.path) == (INVALID_INPUT, "timestamp")
    with pytest.raises(ReaderError) as excinfo:
        reader.read(render_tag(7), timestamp="not-a-date")
    assert excinfo.value.code == INVALID_INPUT
    with pytest.raises(ReaderError) as excinfo:
        reader.read(render_tag(7), timestamp=TIMESTAMP, degradation="coarse ")
    assert (excinfo.value.code, excinfo.value.path) == (INVALID_INPUT, "degradation")


def test_constructor_requires_valid_configuration():
    """全部参数必填且合法：缺参数是 TypeError，非法值是 config_invalid（不做默认值填充）。"""
    parameters = inspect.signature(Reader.__init__).parameters
    for name in (
        "gate",
        "camera",
        "tag_size_m",
        "sigma_px",
        "coverage_factor_k",
        "reader_id",
        "reader_version",
        "frame_ref",
    ):
        assert parameters[name].default is inspect.Parameter.empty  # 无默认值
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    for overrides in (
        dict(tag_size_m=0.0),
        dict(sigma_px=-1.0),
        dict(coverage_factor_k=0.0),
        dict(reader_id="   "),
        dict(reader_version=""),
        dict(frame_ref=""),
        dict(camera=object()),
        dict(gate=object()),
    ):
        with pytest.raises(ReaderError) as excinfo:
            make_reader(**overrides)
        assert excinfo.value.code == CONFIG_INVALID, overrides


def test_self_check_failure_never_returns_a_half_product(monkeypatch):
    """自检（parse_observation）失败时必须抛错，不得返回观测。"""
    reader = make_reader()

    def _boom(payload):  # noqa: ANN001
        raise RuntimeError("self-check failed")

    monkeypatch.setattr(reader_module, "parse_observation", _boom)
    with pytest.raises(RuntimeError, match="self-check failed"):
        reader.read(render_tag(7), timestamp=TIMESTAMP)


def test_float_image_is_rejected_end_to_end():
    with pytest.raises(ReaderError) as excinfo:
        make_reader().read(render_tag(7).astype(np.float64), timestamp=TIMESTAMP)
    assert excinfo.value.code == INVALID_INPUT
