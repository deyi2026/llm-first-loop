"""渲染：位图矩阵（确定性真值）+ 打印 PDF + 清单。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import tag36h11_table as table
from .codes import bit_matrix, code_at
from .layout import Layout
from .manifest import (
    GENERATOR_VERSION,
    LAYOUT_NAME,
    MATRICES_NAME,
    PDF_NAME,
    build_manifest,
)


def _grid_to_rows(grid: list[list[bool]]) -> list[str]:
    return ["".join("#" if cell else "." for cell in row) for row in grid]


def matrices_payload(layouts: list[Layout]) -> dict[str, Any]:
    """B3 消费的确定性真值：布局摘要 + 每靶位图 + 码字。"""
    return {
        "generator": GENERATOR_VERSION,
        "family": table.FAMILY,
        "codes_source": {
            "file": "ctp/docs/upstream/apriltag-tag36h11.c",
            "license": "BSD-2-Clause (Univ. of Michigan Regents, 2013-2016)",
            "ncodes": table.NCODES,
            "declared_min_hamming": table.MIN_HAMMING,
        },
        "boards": [
            {
                "board_index": layout.board_index,
                "rows": layout.rows,
                "cols": layout.cols,
                "tags": [
                    {
                        "slot": slot,
                        "target_index": index,
                        "code_hex": f"{code_at(index):09x}",
                        "grid": _grid_to_rows(bit_matrix(index)),
                    }
                    for slot, index in enumerate(layout.target_indices)
                ],
            }
            for layout in layouts
        ],
    }


def _render_pdf(layouts: list[Layout], path: Path) -> None:
    import reportlab.rl_config as rl_config

    rl_config.invariant = 1  # 关掉时间戳等易变元数据，尽力保证字节级可复现
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    distinct_pages = {
        (layout.page.width_mm, layout.page.height_mm) for layout in layouts
    }
    if len(distinct_pages) > 1:
        # P2-3（wave-2 审查）：混页会被第一页尺寸裁剪——fail-closed 拒绝，不静默渲染
        raise ValueError(
            "mixed page sizes in one document are not supported (later boards would "
            "be clipped to the first page); render one document per page size"
        )
    page_w_pt = layouts[0].page.width_mm * mm
    page_h_pt = layouts[0].page.height_mm * mm
    canvas_writer = canvas.Canvas(str(path), pagesize=(page_w_pt, page_h_pt))
    for layout in layouts:
        cell = layout.tag.size_mm * mm / table.TOTAL_WIDTH
        for slot, index in enumerate(layout.target_indices):
            origin_x, origin_y_top = layout.position_mm(slot)
            origin_x *= mm
            origin_y = (layout.page.height_mm - origin_y_top - layout.tag.size_mm) * mm
            grid = bit_matrix(index)
            for y, row in enumerate(grid):
                for x, black in enumerate(row):
                    if not black:
                        continue
                    canvas_writer.rect(
                        origin_x + x * cell,
                        origin_y + (table.TOTAL_WIDTH - 1 - y) * cell,
                        cell,
                        cell,
                        stroke=0,
                        fill=1,
                    )
        canvas_writer.showPage()
    canvas_writer.save()


def generate(layouts: list[Layout], outdir: str | Path) -> dict[str, Any]:
    """生成 layout.json / board-matrices.json / target-board.pdf / manifest.json。"""
    if not layouts:
        raise ValueError("at least one layout is required")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    layout_payload = {"boards": [layout.as_dict() for layout in layouts]}
    (out / LAYOUT_NAME).write_text(
        json.dumps(layout_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    matrices = matrices_payload(layouts)
    (out / MATRICES_NAME).write_text(
        json.dumps(matrices, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _render_pdf(layouts, out / PDF_NAME)
    manifest = build_manifest(out, layouts)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
