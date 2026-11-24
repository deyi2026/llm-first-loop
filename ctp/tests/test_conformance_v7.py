"""B7 · V7 混合版本墙：外来码字确实不可解码；误读=0 才通过；样本集确定。"""

from __future__ import annotations

import numpy as np
import pytest

from ctp_conformance import run_v7
from ctp_conformance.receipt import sample_set_sha256
from ctp_conformance.synth import (
    descriptions,
    foreign_grid,
    min_hamming_rotations,
    render_tag,
    unrelated_grid,
)
from ctp_conformance.v7 import build_samples
from ctp_gen import codes
from ctp_gen import tag36h11_table as table
from conformance_stubs import StubReader, always, refuse_foreign

CORRECTION = table.MIN_HAMMING // 2  # 36h11 可纠正 ≤5 位


def test_foreign_and_unrelated_patterns_are_beyond_correction():
    """样本构造自检：外来码字 / 无关图案在四个取向下都超出纠错能力；对照组合法码距离为 0。"""
    rng = np.random.default_rng(0)
    for index in (0, 7, 586):
        assert min_hamming_rotations(codes.bit_matrix(index)) == 0
        grid = foreign_grid(index, n_flips=6, rng=rng)
        assert min_hamming_rotations(grid) > CORRECTION
    assert min_hamming_rotations(unrelated_grid(rng)) > CORRECTION
    with pytest.raises(ValueError):
        foreign_grid(0, n_flips=5, rng=rng)  # 应拦输入：翻转数不超过纠错能力时构不成"外来码"


def test_samples_are_deterministic_and_seed_sensitive():
    first, second = build_samples(0), build_samples(0)
    assert sample_set_sha256(descriptions(first)) == sample_set_sha256(descriptions(second))
    for left, right in zip(first, second, strict=True):
        assert np.array_equal(left["image"], right["image"])
    assert sample_set_sha256(descriptions(build_samples(1))) != sample_set_sha256(descriptions(first))
    kinds = {sample["description"]["kind"] for sample in first}
    assert kinds == {"known", "foreign"}


def test_pass_when_every_foreign_sample_is_refused():
    samples = build_samples(0)
    report = run_v7(StubReader(samples, refuse_foreign), samples=samples)
    counts = report["counts"]
    assert report["verdict"] == "pass"
    assert report["simulated"] is True
    assert report["sample_set_sha256"] == sample_set_sha256(descriptions(samples))
    assert counts["misread"] == 0
    assert counts["foreign_refused_unknown_version"] == counts["foreign_total"]
    assert counts["known_decoded"] == counts["known_total"]
    assert report["failures"] == []
    assert report["reader"] == {"reader_id": "stub-reader", "reader_version": "0.0.0"}


def test_fail_when_foreign_sample_outputs_any_id():
    """应拦输入：读码器对外来码字输出了 ID（哪怕碰巧是合法索引）即误读，判不通过。"""
    samples = build_samples(0)
    report = run_v7(StubReader(samples, always("output")), samples=samples)
    assert report["verdict"] == "fail"
    assert report["counts"]["misread"] == report["counts"]["foreign_total"]
    assert {item["violation"] for item in report["failures"]} == {"misread"}


def test_silent_refusal_is_not_a_misread_but_is_counted():
    """V7 只判误读；对外来样本静默（无输出）不计误读，但单独计数，供 V8 侧追责。"""
    samples = build_samples(0)
    rule = lambda description: "output" if description["kind"] == "known" else "silent"  # noqa: E731
    report = run_v7(StubReader(samples, rule), samples=samples)
    assert report["verdict"] == "pass"
    assert report["counts"]["foreign_silent"] == report["counts"]["foreign_total"]
    assert report["counts"]["misread"] == 0


def test_rendered_tag_round_trips_through_the_generator_layout():
    """渲染自检：合成已知族图像缩回 10×10 后与生成器位图一致（保证样本确实是 36h11 码）。"""
    image = render_tag(7)
    cells = image.reshape(image.shape[0] // 12, 12, image.shape[1] // 12, 12).mean(axis=(1, 3))
    core = cells[4:14, 4:14] < 128
    expected = np.asarray(codes.bit_matrix(7), dtype=bool)
    assert np.array_equal(core, expected)
