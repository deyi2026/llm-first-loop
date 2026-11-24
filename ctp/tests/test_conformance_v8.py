"""B7 · V8 fail-closed：漏检类不输出且计数上报；伪造类如实标未演练；静默即违例。"""

from __future__ import annotations

import numpy as np
import pytest

from ctp_conformance import run_v8
from ctp_conformance.synth import FORGERY_TYPES, LEAK_TYPES, TIMESTAMP, render_tag, unreadable
from ctp_conformance.v8 import build_samples
from conformance_stubs import StubReader, UntypedErrorReader, always


def _violations(report: dict) -> set[str]:
    return {item["violation"] for item in report["failures"]}


def test_refusing_reader_leaves_forgery_unexercised():
    samples = build_samples(60, seed=0)
    report = run_v8(StubReader(samples, always("unknown_version")), samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "indeterminate"  # 伪造类未演练 → 不得判通过
    assert report["simulated"] is True
    assert report["failures"] == []
    assert counts["leak_total"] == 30 and counts["leak_refused"] == 30
    assert counts["refused_code_unknown_version"] == 30
    assert counts["forgery_total"] == 30 and counts["forgery_exercised"] == 0
    by_type = {item["fault_type"]: item["count"] for item in report["not_exercisable"]}
    assert by_type == {fault: 10 for fault in FORGERY_TYPES}
    assert counts["leak_silent"] == 0 and counts["leak_output"] == 0


def test_fault_types_are_dispatched_and_counted():
    samples = build_samples(60, seed=0)
    report = run_v8(StubReader(samples, always("unknown_version")), samples=samples)
    for fault in LEAK_TYPES:
        assert report["counts"][f"leak_{fault}_total"] == 10
    expected = {f"leak_{number:04d}" for number in range(30)}
    assert {sample["description"]["sample_id"] for sample in samples[:30]} == expected


def test_output_on_unreadable_sample_is_a_failure():
    """带错输出：对不可读样本给出了 ID——带错硬接 = 0 的断言被打破。"""
    samples = build_samples(60, seed=0)
    report = run_v8(StubReader(samples, always("output")), samples=samples)
    assert report["verdict"] == "fail"
    assert _violations(report) == {"output_on_unreadable"}
    assert report["counts"]["leak_output"] == report["counts"]["leak_total"]


def test_silent_reader_is_a_failure():
    """静默（不输出也不带码报错）本身即违例，即使没有带错输出。"""
    samples = build_samples(60, seed=0)
    report = run_v8(StubReader(samples, always("silent")), samples=samples)
    assert report["verdict"] == "fail"
    assert _violations(report) == {"silent"}
    assert report["counts"]["leak_silent"] == report["counts"]["leak_total"]


def test_untyped_exception_counts_as_silent():
    samples = build_samples(60, seed=0)
    report = run_v8(UntypedErrorReader(samples, always("unknown_version")), samples=samples)
    assert report["verdict"] == "fail"
    assert "silent" in _violations(report)
    assert report["counts"]["leak_silent"] == report["counts"]["leak_total"]


def test_forgery_excluded_allows_pass_for_leak_class_only():
    samples = build_samples(60, include_forgery=False, seed=0)
    report = run_v8(StubReader(samples, always("unknown_version")), samples=samples)
    assert report["verdict"] == "pass"
    assert report["counts"]["forgery_total"] == 0
    assert report["not_exercisable"] == []


def test_unreadable_sample_keeps_border_but_destroys_data():
    image = unreadable(render_tag(7), rng=np.random.default_rng(0))
    assert image.shape == render_tag(7).shape  # 只改内容、不改几何
    data = image[(4 + 2) * 12 : (4 + 8) * 12, (4 + 2) * 12 : (4 + 8) * 12]  # 6×6 数据区
    assert data.min() >= 125 and data.max() <= 131  # 数据区只剩均匀灰 ± 微噪声（含最后一列）
    border = image[(4 + 1) * 12 : (4 + 2) * 12, (4 + 1) * 12 : (4 + 8) * 12]  # 核边框上沿（核内 8 格）
    assert border.max() == 0  # 边框仍为黑（靶标可定位）
    quiet = image[: 4 * 12, :]  # 核外静区
    assert quiet.min() == 255  # 静区仍为白
    assert TIMESTAMP.endswith("+08:00")


def test_rejects_non_positive_n():
    with pytest.raises(ValueError):
        build_samples(0)
