"""B3 · 图像层与解码：正确解码、旋转、纠错边界、超纠错必拒、裁剪证据、输入校验。"""

from __future__ import annotations

import numpy as np
import pytest

from ctp_conformance.synth import SCALE, foreign_grid, render_grid, render_tag, unrelated_grid
from ctp_gen import tag36h11_table as table
from ctp_reader.decode36h11 import (
    CORRECTION_CAPABILITY,
    MAX_ERASURES,
    MIN_KNOWN_BITS,
    decode,
    sample_cells,
)
from ctp_reader.errors import INVALID_INPUT, NO_TAG_FOUND, UNKNOWN_VERSION, ReaderError
from ctp_reader.image import CellGrid, _verify_border, locate_tag, validate, visible_corners, visible_data_ratio
from reader_testkit import crop_left, crop_top_left, flip_data_bits, index_with_dark_data_columns, noisy_and_blurred, translate


def _decode(image: np.ndarray):
    grid = locate_tag(image)
    dark, known = sample_cells(image, grid)
    return decode(dark, known), grid


def test_corrections_capability_matches_the_family():
    assert CORRECTION_CAPABILITY == 5  # 36h11 最小汉明距离 11 → 无未知位时可纠正 ≤5 位（码族事实）
    assert MAX_ERASURES == table.MIN_HAMMING - 1 == 10  # 2t + e ≤ d − 1
    assert MIN_KNOWN_BITS == table.NBITS - MAX_ERASURES == 26


@pytest.mark.parametrize(
    "unknown, errors, decodes",
    [
        (0, 5, True),  # 无未知位：5 位错误仍在预算内
        (0, 6, False),  # 无未知位：6 位错误超预算
        (6, 2, True),  # 6 个未知位：预算收紧到 ⌊(10−6)/2⌋ = 2
        (6, 3, False),  # 6 个未知位：3 位错误即超预算
        (10, 0, True),  # 10 个未知位：只接受已知位完全吻合
        (11, 0, False),  # 超过 10 个未知位：无法保证唯一，直接拒解
    ],
)
def test_erasure_budget_tightens_with_unknown_bits(unknown, errors, decodes):
    """唯一解码条件 2t + e ≤ 10：未知位越多，允许的已知位错误越少（应拦输入落在边界外）。"""
    grid = locate_tag(render_tag(100))
    dark, known = sample_cells(render_tag(100), grid)
    positions = list(range(table.NBITS))
    for index in positions[:unknown]:  # 标记未知位（数据不可见）
        x, y = table.BIT_X[index] + 1, table.BIT_Y[index] + 1
        known[y, x] = False
        dark[y, x] = False
    for index in positions[unknown : unknown + errors]:  # 在已知位上制造真实错误
        x, y = table.BIT_X[index] + 1, table.BIT_Y[index] + 1
        dark[y, x] = not dark[y, x]
    if decodes:
        result = decode(dark, known)
        assert (result.target_index, result.hamming_distance, result.known_bits) == (100, errors, table.NBITS - unknown)
    else:
        with pytest.raises(ReaderError) as excinfo:
            decode(dark, known)
        assert excinfo.value.code == UNKNOWN_VERSION


@pytest.mark.parametrize("index", [0, 1, 7, 100, 586])
def test_decodes_without_error(index):
    result, grid = _decode(render_tag(index))
    assert result.target_index == index
    assert result.hamming_distance == 0
    assert result.quarter_turns == 0
    assert result.known_bits == table.NBITS
    assert grid.cell == pytest.approx(SCALE)


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_rotated_image_decodes_to_the_same_index(turns):
    result, _ = _decode(np.rot90(render_tag(7), turns))
    assert result.target_index == 7
    assert result.hamming_distance == 0
    assert result.quarter_turns == (4 - turns) % 4


@pytest.mark.parametrize("flips", [1, 3, 5])
def test_corrects_up_to_five_bit_errors(flips):
    """纠错能力内：翻转 ≤5 个数据位仍解出原码，汉明距离如实等于翻转数。"""
    result, _ = _decode(flip_data_bits(render_tag(100), range(flips)))
    assert result.target_index == 100
    assert result.hamming_distance == flips


def test_patterns_beyond_correction_are_unknown_version():
    """应拦输入：超出纠错能力的图案一律 unknown_version，异常上不带任何索引。"""
    rng = np.random.default_rng(0)
    images = [render_grid(foreign_grid(index, n_flips=6, rng=rng)) for index in (0, 7, 586)]
    images.append(render_grid(unrelated_grid(rng)))
    for image in images:
        with pytest.raises(ReaderError) as excinfo:
            _decode(image)
        assert excinfo.value.code == UNKNOWN_VERSION
        assert not hasattr(excinfo.value, "target_index")


def test_too_few_known_bits_refuses_to_decode():
    """应拦输入：已知位不足 26 个时不解码（保证候选唯一），即使剩余位恰好能对上某个码。"""
    grid = locate_tag(render_tag(7))
    dark, known = sample_cells(render_tag(7), grid)
    dropped = 0
    for index in range(table.NBITS):
        if dropped > table.NBITS - MIN_KNOWN_BITS:
            break
        x, y = table.BIT_X[index] + 1, table.BIT_Y[index] + 1
        if known[y, x]:
            known[y, x] = False
            dropped += 1

    with pytest.raises(ReaderError) as excinfo:
        decode(dark, known)
    assert excinfo.value.code == UNKNOWN_VERSION


def test_partial_data_still_decodes_when_enough_bits_are_known():
    """裁掉最左一列数据位（6 格出界）后仍有 30 个已知位：按已知位解码，结果正确且如实报告已知位数。"""
    index = index_with_dark_data_columns(2)
    image = crop_left(render_tag(index), 7)  # 4 静区 + 核静区 1 + 边框 1 + 数据列 1
    grid = locate_tag(image)
    assert visible_data_ratio(grid) == pytest.approx(30 / 36)
    dark, known = sample_cells(image, grid)
    result = decode(dark, known)
    assert result.target_index == index
    assert result.known_bits == 30


def test_translation_noise_and_blur_keep_it_decodable():
    image = noisy_and_blurred(translate(render_tag(586), 40, 60), sigma=15.0, seed=3)
    result, _ = _decode(image)
    assert result.target_index == 586


def test_blank_and_non_square_regions_are_no_tag_found():
    with pytest.raises(ReaderError) as excinfo:
        locate_tag(np.full((216, 216), 255, dtype=np.uint8))
    assert excinfo.value.code == NO_TAG_FOUND
    rectangle = np.full((216, 216), 255, dtype=np.uint8)
    rectangle[80:100, 60:150] = 0
    with pytest.raises(ReaderError) as excinfo:
        locate_tag(rectangle)
    assert excinfo.value.code == NO_TAG_FOUND
    with pytest.raises(ReaderError) as excinfo:
        locate_tag(np.zeros((216, 216), dtype=np.uint8))
    assert excinfo.value.code == NO_TAG_FOUND


def test_invalid_inputs_are_rejected_without_coercion():
    bad_inputs = (
        np.zeros((216, 216), dtype=np.float64),
        np.zeros((3, 216, 216), dtype=np.uint8),
        [[1, 2], [3, 4]],
        np.zeros((4, 4), dtype=np.uint8),
    )
    for bad in bad_inputs:
        with pytest.raises(ReaderError) as excinfo:
            validate(bad)
        assert excinfo.value.code == INVALID_INPUT


def test_crop_evidence_counts_only_corners_with_both_border_edges():
    """矩形裁剪裁掉整条边：裁左边 → 左上、左下不完整（可见 2）；裁数据列 → 可见 2 且比例 5/6；
    上 + 左同时裁 → 双向截断，v0 无法估格宽 → no_tag_found。"""
    index = index_with_dark_data_columns(2)
    intact = locate_tag(render_tag(index))
    assert visible_corners(render_tag(index), intact) == 4
    assert visible_data_ratio(intact) == 1.0

    left_cut = crop_left(render_tag(index), 6)
    grid = locate_tag(left_cut)
    assert visible_corners(left_cut, grid) == 2
    assert visible_data_ratio(grid) == 1.0

    deeper = crop_left(render_tag(index), 7)
    grid = locate_tag(deeper)
    assert visible_corners(deeper, grid) == 2
    assert visible_data_ratio(grid) == pytest.approx(30 / 36)

    with pytest.raises(ReaderError) as excinfo:
        locate_tag(crop_top_left(render_tag(index), 6))
    assert excinfo.value.code == NO_TAG_FOUND


def test_border_check_rejects_misaligned_grid():
    """应拦输入：格阵原点横移 2 格后，边框列的采样落到白色静区——边框校验必须拦下（fail-closed）。"""
    image = render_tag(7)
    good = locate_tag(image)
    misaligned = CellGrid(good.x0 + 2 * good.cell, good.y0, good.cell, good.width, good.height, good.threshold)
    with pytest.raises(ReaderError) as excinfo:
        _verify_border(image, misaligned)
    assert excinfo.value.code == NO_TAG_FOUND
    assert excinfo.value.path == "border"
