"""B7 · V4 双向降级：错读侧必须为 0；"永不输出"判不通过；未配置上限只能 indeterminate。"""

from __future__ import annotations

import pytest

from ctp_conformance import run_v4
from ctp_conformance.receipt import NOT_CONFIGURED, sample_set_sha256
from ctp_conformance.synth import descriptions
from ctp_conformance.v4 import build_samples
from conformance_stubs import StubReader, always, gate_like

CONFIGURED = {
    "min_visible_corners": 4,
    "min_visible_data_ratio": 1.0,
    "miss_rate_limit": 0.0,
    "min_sample_size": 1,
}


def _violations(report: dict) -> set[str]:
    return {item["violation"] for item in report["failures"]}


def test_pass_with_gate_like_reader_and_configured_limits():
    samples = build_samples(0)
    report = run_v4(StubReader(samples, gate_like(4, 1.0)), config=CONFIGURED, samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "pass", report
    assert report["simulated"] is True
    assert report["sample_set_sha256"] == sample_set_sha256(descriptions(samples))
    assert counts["below_misread"] == 0
    assert counts["below_suppressed_by_gate"] == counts["below_total"] == 4
    assert counts["at_detected"] == counts["at_total"] == 5
    assert report["measured"]["miss_rate"] == 0.0
    assert report["failures"] == [] and report["not_exercisable"] == []


def test_never_outputs_is_a_failure():
    """SPEC 11.2-V4：'永不输出'必须判为不通过。"""
    samples = build_samples(0)
    report = run_v4(StubReader(samples, always("below_min_readable")), config=CONFIGURED, samples=samples)
    assert report["verdict"] == "fail"
    assert "never_outputs" in _violations(report)
    assert report["counts"]["below_misread"] == 0  # 错读侧确实为 0，但漏检侧 100%


def test_output_below_threshold_is_a_misread():
    samples = build_samples(0)
    report = run_v4(StubReader(samples, always("output")), config=CONFIGURED, samples=samples)
    assert report["verdict"] == "fail"
    assert "misread_below_threshold" in _violations(report)
    assert report["counts"]["below_misread"] == report["counts"]["below_total"]


def test_silent_reader_is_a_protocol_failure():
    samples = build_samples(0)
    report = run_v4(StubReader(samples, always("silent")), config=CONFIGURED, samples=samples)
    assert report["verdict"] == "fail"
    assert "silent" in _violations(report)


def test_unconfigured_limits_yield_indeterminate():
    config = {"min_visible_corners": 4, "min_visible_data_ratio": 1.0}
    samples = build_samples(0)
    report = run_v4(StubReader(samples, gate_like(4, 1.0)), config=config, samples=samples)
    assert report["verdict"] == "indeterminate"
    assert report["thresholds_used"]["miss_rate_limit ([TBD-V4c])"] == NOT_CONFIGURED
    assert report["thresholds_used"]["min_sample_size ([TBD-V4d])"] == NOT_CONFIGURED


def test_exceeding_configured_miss_limit_fails():
    samples = build_samples(0)
    config = dict(CONFIGURED, miss_rate_limit=0.5)
    # 5 个达标样本里漏掉 3 个 → 漏检率 0.6 > 0.5
    rule = lambda description: (  # noqa: E731
        "below_min_readable"
        if description["sample_id"] in {"intact_000", "intact_001", "intact_007"}
        else "output"
    )
    report = run_v4(StubReader(samples, rule), config=config, samples=samples)
    assert report["verdict"] == "fail"
    assert "miss_rate_exceeds_limit" in _violations(report)
    assert report["measured"]["miss_rate"] == pytest.approx(0.6)


def test_insufficient_sample_size_is_not_exercisable_not_pass():
    samples = build_samples(0)
    report = run_v4(
        StubReader(samples, gate_like(4, 1.0)),
        config=dict(CONFIGURED, min_sample_size=1000),
        samples=samples,
    )
    assert report["verdict"] == "indeterminate"
    assert any(item["dimension"] == "sample_size" for item in report["not_exercisable"])


def test_grouping_follows_the_configured_threshold():
    """阈值降到 3 个角点：样本集里没有任何样本恰好落在 [3, 4) 区间（矩形裁剪只能得到 4 / 2 / 1 / 0 个完整角点），
    所以达标组仍是 5 个完整样本，低于阈值组仍是 4 个——分组随阈值变化这一点由比例阈值用例覆盖。"""
    samples = build_samples(0)
    config = dict(CONFIGURED, min_visible_corners=3)
    report = run_v4(StubReader(samples, gate_like(3, 1.0)), config=config, samples=samples)
    assert report["verdict"] == "pass", report
    assert report["counts"]["at_total"] == 5
    assert report["counts"]["below_total"] == 4


def test_grouping_moves_samples_when_threshold_admits_them():
    """阈值设为 2 个角点：裁左边（完整角点 2）的样本移入达标组；裁数据列的样本因比例 5/6 < 1.0 仍留在低于阈值组。"""
    samples = build_samples(0)
    config = dict(CONFIGURED, min_visible_corners=2)
    report = run_v4(StubReader(samples, gate_like(2, 1.0)), config=config, samples=samples)
    assert report["verdict"] == "pass", report
    assert report["counts"]["at_total"] == 6
    assert report["counts"]["below_total"] == 3


def test_ratio_threshold_below_one_discloses_unexercisable_dimension():
    samples = build_samples(0)
    config = dict(CONFIGURED, min_visible_data_ratio=0.9)
    report = run_v4(StubReader(samples, gate_like(4, 0.9)), config=config, samples=samples)
    assert report["verdict"] == "indeterminate"
    assert any(item["dimension"] == "visible_data_ratio_only" for item in report["not_exercisable"])


def test_requires_thresholds_in_config():
    with pytest.raises(ValueError):
        run_v4(StubReader(build_samples(0), always("output")), config={})


@pytest.mark.parametrize(
    "key, unusable",
    [
        ("miss_rate_limit", None),
        ("miss_rate_limit", float("nan")),
        ("miss_rate_limit", True),
        ("miss_rate_limit", "0.1"),
        ("miss_rate_limit", 2.0),
        ("miss_rate_limit", float("inf")),
        ("min_sample_size", None),
        ("min_sample_size", float("nan")),
        ("min_sample_size", True),
        ("min_sample_size", "100"),
        ("min_sample_size", 0),
        ("min_sample_size", -5),
    ],
)
def test_unusable_optional_limits_are_unconfigured_never_pass(key, unusable):
    """提供了但不可用的上限值不得当作"已配置"：否则上限检查被跳过，回执会在一个无法使用的上限下判 pass。"""
    samples = build_samples(0)
    report = run_v4(
        StubReader(samples, gate_like(4, 1.0)), config=dict(CONFIGURED, **{key: unusable}), samples=samples
    )
    assert report["verdict"] == "indeterminate", report
    recorded = {name.split(" ")[0]: value for name, value in report["thresholds_used"].items()}
    assert recorded[key] == NOT_CONFIGURED
    assert any(key in note and repr(unusable) in note for note in report["notes"])


@pytest.mark.parametrize(
    "key, unusable",
    [
        ("min_visible_corners", None),
        ("min_visible_corners", float("nan")),
        ("min_visible_corners", True),
        ("min_visible_corners", "4"),
        ("min_visible_corners", -1),
        ("min_visible_data_ratio", None),
        ("min_visible_data_ratio", float("nan")),
        ("min_visible_data_ratio", False),
        ("min_visible_data_ratio", "1.0"),
        ("min_visible_data_ratio", 1.5),
    ],
)
def test_unusable_grouping_thresholds_are_rejected(key, unusable):
    """分组阈值不可用就无法分组（NaN 比较恒假会让全部样本落到达标组）：拒绝运行，不产出回执。"""
    with pytest.raises(ValueError, match=key):
        run_v4(StubReader(build_samples(0), always("output")), config=dict(CONFIGURED, **{key: unusable}))
