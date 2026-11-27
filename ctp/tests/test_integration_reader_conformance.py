"""集成（B3 真读码器 + B4 真闸门 → B7 三个 runner 的合成样本）。

全部为合成样本：simulated，不构成任何门槛实测证据。这里验证的是三方拼起来后的行为，
不是门槛数值。
"""

from __future__ import annotations

import pytest

from ctp_calib.pixel import PinholeCamera
from ctp_conformance import run_v4, run_v7, run_v8
from ctp_conformance.synth import QUIET, SCALE
from ctp_conformance.v4 import build_samples as v4_samples
from ctp_conformance.v7 import build_samples as v7_samples
from ctp_conformance.v8 import build_samples as v8_samples
from ctp_gen import tag36h11_table as table
from ctp_reader.config import ThresholdConfig
from ctp_reader.errors import ReaderError
from ctp_reader.gate import ReadGate
from ctp_reader.image import locate_tag, visible_corners, visible_data_ratio
from ctp_reader.reader import Reader

READER_ID = "reader-v0-integration"
TIMESTAMP = "2026-11-24T12:00:00+08:00"
STRICT = {"min_visible_corners": 4, "min_visible_data_ratio": 1.0, "miss_rate_limit": 0.0, "min_sample_size": 1}
LENIENT = {"min_visible_corners": 2, "min_visible_data_ratio": 0.9, "miss_rate_limit": 0.0, "min_sample_size": 1}


def make_reader(*, min_corners: int = 4, min_ratio: float = 1.0) -> Reader:
    side = (table.TOTAL_WIDTH + 2 * QUIET) * SCALE
    return Reader(
        gate=ReadGate(ThresholdConfig(min_visible_corners=min_corners, min_visible_data_ratio=min_ratio)),
        camera=PinholeCamera(fx=800.0, fy=800.0, cx=side / 2.0, cy=side / 2.0),
        tag_size_m=0.05,
        sigma_px=0.3,
        coverage_factor_k=2.0,
        reader_id=READER_ID,
        reader_version="0.0.1",
        frame_ref="frame:integration/tag",
    )


def _sample(samples: list[dict], sample_id: str) -> dict:
    return next(item for item in samples if item["description"]["sample_id"] == sample_id)


def test_v7_passes_with_the_real_reader():
    samples = v7_samples(0)
    report = run_v7(make_reader(), samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "pass", report
    assert report["simulated"] is True
    assert counts["misread"] == 0
    assert counts["foreign_refused_unknown_version"] == counts["foreign_total"]
    assert counts["known_decoded"] == counts["known_total"]
    assert report["reader"] == {"reader_id": READER_ID, "reader_version": "0.0.1"}


def test_v4_with_strict_thresholds_suppresses_and_never_misreads():
    """阈值 4 角 / 比例 1.0：4 个裁剪样本全部不输出（2 个被闸门抑制、2 个双向截断无法定位），5 个完整样本全部读出。"""
    samples = v4_samples(0)
    report = run_v4(make_reader(), config=STRICT, samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "pass", report
    assert counts["below_misread"] == 0
    assert counts["below_suppressed_by_gate"] == 2
    assert counts["below_refused_other"] == 2
    assert counts["at_detected"] == counts["at_total"] == 5
    assert report["measured"]["miss_rate"] == 0.0


def test_v4_with_lenient_thresholds_reads_the_two_corner_sample_and_stays_honest():
    """阈值 2 角 / 比例 0.9：裁左边的样本（2 个完整角点、数据完整）被读出；比例维度无法单独演练 → indeterminate，但零误读。"""
    samples = v4_samples(0)
    report = run_v4(make_reader(min_corners=2, min_ratio=0.9), config=LENIENT, samples=samples)
    counts = report["counts"]
    assert report["failures"] == []
    assert report["verdict"] == "indeterminate"
    assert any(item["dimension"] == "visible_data_ratio_only" for item in report["not_exercisable"])
    assert counts["below_misread"] == 0
    assert counts["at_detected"] == counts["at_total"] == 6


def test_v8_real_reader_refuses_every_leak_sample():
    samples = v8_samples(60, include_forgery=False, seed=0)
    report = run_v8(make_reader(), config={"include_forgery": False}, samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "pass", report
    assert counts["leak_output"] == 0 and counts["leak_silent"] == 0
    assert counts["leak_refused"] == counts["leak_total"] == 60
    assert counts["refused_code_unknown_version"] == 40  # 超纠错 20 + 不可读 20
    # 遮挡 20：裁上+左 7 例与裁三边 6 例无法定位（no_tag_found），裁左边 7 例被闸门抑制
    assert counts.get("refused_code_no_tag_found", 0) + counts.get("refused_code_below_min_readable", 0) == 20
    assert counts.get("refused_code_below_min_readable", 0) > 0  # 至少有一例是闸门抑制而不是定位失败


def test_v8_with_forgery_samples_is_indeterminate_not_pass():
    samples = v8_samples(60, seed=0)
    report = run_v8(make_reader(), config={}, samples=samples)
    assert report["verdict"] == "indeterminate"
    assert report["failures"] == []
    assert {item["fault_type"] for item in report["not_exercisable"]} == {
        "wrong_id",
        "copied_tag",
        "interlevel_pose_contradiction",
    }


def test_synthetic_geometry_truth_matches_the_reader_evidence():
    """合成几何真值与读码器证据口径逐样本一致（角点数与数据位比例），裁剪样本的索引可被宽松阈值读出。"""
    for sample in v4_samples(0):
        description = sample["description"]
        if description["visible_corners"] in (0, 1):
            continue  # 双向截断：读码器无法定位（no_tag_found），没有证据可比
        image = sample["image"]
        grid = locate_tag(image)
        assert visible_corners(image, grid) == description["visible_corners"], description["sample_id"]
        assert visible_data_ratio(grid) == pytest.approx(description["visible_data_ratio"]), description["sample_id"]


def test_cropped_sample_decodes_to_its_recorded_index_under_lenient_thresholds():
    sample = _sample(v4_samples(0), "crop_corners_2")
    strict = make_reader(min_corners=3)
    with pytest.raises(ReaderError) as excinfo:
        strict.read(sample["image"], timestamp=TIMESTAMP)
    assert excinfo.value.code == "below_min_readable"
    observation = make_reader(min_corners=2).read(sample["image"], timestamp=TIMESTAMP)
    assert observation.target_index == sample["description"]["target_index"]  # 期望值来自样本真值，不来自读码器
