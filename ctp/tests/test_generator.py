"""B6 图案生成工具链：码表来源、位图结构、布局校验、确定性、清单防篡改。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ctp_gen import (  # noqa: E402
    Layout,
    PageSpec,
    TagSpec,
    bit_matrix,
    code_at,
    family_invariants,
    generate,
    layout_from_dict,
    verify_manifest,
)
from ctp_gen import tag36h11_table as table  # noqa: E402

WT = Path(__file__).resolve().parents[2]
UPSTREAM = WT / "ctp/docs/upstream/apriltag-tag36h11.c"


def _layout(**over):
    payload = dict(
        board_index=0,
        rows=2,
        cols=3,
        target_indices=(0, 1, 2, 3, 4, 5),
        page=PageSpec(width_mm=297.0, height_mm=210.0, margin_mm=10.0),
        tag=TagSpec(size_mm=40.0, gap_mm=6.0),
    )
    payload.update(over)
    return Layout(**payload)


def test_table_regenerates_from_upstream_source():
    """K4 溯源：数据模块必须与 BSD-2 上游源逐字一致（漂移即失败）。"""
    text = UPSTREAM.read_text(encoding="utf-8")
    codes = [int(m, 16) for m in re.findall(r"0x([0-9a-fA-F]+)UL", text)]
    bit_x = [int(m[1]) for m in re.findall(r"bit_x\[(\d+)\] = (\d+);", text)]
    bit_y = [int(m[1]) for m in re.findall(r"bit_y\[(\d+)\] = (\d+);", text)]
    assert codes == list(table.CODES)
    assert bit_x == list(table.BIT_X)
    assert bit_y == list(table.BIT_Y)


def test_family_invariants_hold():
    invariants = family_invariants()
    assert invariants["invariant_ok"], invariants
    assert invariants["ncodes"] == 587
    assert invariants["min_pairwise_hamming"] >= 11


def test_bit_matrix_structure_matches_convention():
    """quiet zone 白、核外圈黑边、数据位 = 码字 MSB-first 映射。"""
    grid = bit_matrix(0)
    assert len(grid) == 10 and all(len(row) == 10 for row in grid)
    for edge in range(10):
        assert grid[0][edge] is False and grid[9][edge] is False
        assert grid[edge][0] is False and grid[edge][9] is False
    for x in (1, 8):
        for y in range(1, 9):
            assert grid[y][x] is True and grid[x][y] is True
    code = table.CODES[0]
    for i in range(36):
        expected = bool((code >> (35 - i)) & 1)
        assert grid[table.BIT_Y[i] + 1][table.BIT_X[i] + 1] is expected


@pytest.mark.parametrize("index", [-1, 587, 10**6])
def test_code_at_rejects_out_of_range(index):
    with pytest.raises(ValueError):
        code_at(index)


def test_layout_validation_rejects_bad_payloads():
    with pytest.raises(ValueError):
        _layout(target_indices=(0, 0, 1, 2, 3, 4))  # 重复索引
    with pytest.raises(ValueError):
        _layout(target_indices=(0, 1, 2, 586, 587, 5))  # 越界
    with pytest.raises(ValueError):
        _layout(rows=4, target_indices=tuple(range(6)))  # 数量不符
    with pytest.raises(ValueError):
        _layout(tag=TagSpec(size_mm=150.0, gap_mm=6.0))  # 物理放不下
    with pytest.raises(ValueError):
        _layout(family="42h7")  # v0 只支持 36h11


def test_layout_roundtrip_through_json():
    layout = _layout(logical_mapping={"resolution": "code"})
    restored = layout_from_dict(json.loads(json.dumps(layout.as_dict())))
    assert restored == layout


def test_generate_is_deterministic(tmp_path):
    layout = _layout()
    first, second = tmp_path / "a", tmp_path / "b"
    generate([layout], first)
    generate([layout], second)
    for name in ("layout.json", "board-matrices.json", "target-board.pdf"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    assert verify_manifest(first)["ok"]
    assert verify_manifest(second)["ok"]


def test_generate_pdf_is_valid_and_paged(tmp_path):
    out = tmp_path / "out"
    generate([_layout(), _layout(board_index=1, target_indices=(100, *range(101, 106)))], out)
    from pypdf import PdfReader

    reader = PdfReader(str(out / "target-board.pdf"))
    assert len(reader.pages) == 2
    width_pt = float(reader.pages[0].mediabox.width)
    assert 800 < width_pt < 850  # A4 横放 297mm ≈ 842pt（单位换算钉）


def test_manifest_detects_tampering(tmp_path):
    out = tmp_path / "out"
    generate([_layout()], out)
    matrices = out / "board-matrices.json"
    payload = json.loads(matrices.read_text(encoding="utf-8"))
    payload["boards"][0]["tags"][0]["target_index"] = 999
    matrices.write_text(json.dumps(payload), encoding="utf-8")
    verdict = verify_manifest(out)
    assert verdict["ok"] is False
    assert any("board-matrices.json" in error for error in verdict["errors"])
