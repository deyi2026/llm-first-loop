"""布局模型：一页 N 靶，target_index → 物理位置（分层映射的板内层）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import tag36h11_table as table

LAYOUT_VERSION = 1


@dataclass(frozen=True)
class PageSpec:
    width_mm: float
    height_mm: float
    margin_mm: float


@dataclass(frozen=True)
class TagSpec:
    size_mm: float
    gap_mm: float  # 靶间留白（必填；工程取值见 ctp/docs/generator-notes.md，不是规范数值）


@dataclass(frozen=True)
class Layout:
    board_index: int
    rows: int
    cols: int
    target_indices: tuple[int, ...]
    page: PageSpec
    tag: TagSpec
    layout_version: int = LAYOUT_VERSION
    family: str = table.FAMILY
    logical_mapping: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.family != table.FAMILY:
            raise ValueError(f"unsupported family {self.family!r} (only 36h11 in v0)")
        if self.layout_version != LAYOUT_VERSION:
            raise ValueError(f"unsupported layout_version {self.layout_version}")
        if self.board_index < 0 or self.rows < 1 or self.cols < 1:
            raise ValueError("board_index/rows/cols must be positive")
        if len(self.target_indices) != self.rows * self.cols:
            raise ValueError("target_indices count must equal rows*cols")
        if len(set(self.target_indices)) != len(self.target_indices):
            raise ValueError("target_indices must be unique within a board")
        for index in self.target_indices:
            if not 0 <= index < table.NCODES:
                raise ValueError(f"target_index {index} out of range")
        span_x = self.page.margin_mm * 2 + self.cols * self.tag.size_mm + (self.cols - 1) * self.tag.gap_mm
        span_y = self.page.margin_mm * 2 + self.rows * self.tag.size_mm + (self.rows - 1) * self.tag.gap_mm
        if span_x > self.page.width_mm + 1e-9 or span_y > self.page.height_mm + 1e-9:
            raise ValueError(
                f"layout does not fit page: need {span_x:.1f}x{span_y:.1f} mm, "
                f"page {self.page.width_mm:.0f}x{self.page.height_mm:.0f} mm"
            )

    def position_mm(self, slot: int) -> tuple[float, float]:
        """槽位（行优先）→ 左上角毫米坐标。"""
        if not 0 <= slot < self.rows * self.cols:
            raise ValueError("slot out of range")
        row, col = divmod(slot, self.cols)
        x = self.page.margin_mm + col * (self.tag.size_mm + self.tag.gap_mm)
        y = self.page.margin_mm + row * (self.tag.size_mm + self.tag.gap_mm)
        return x, y

    def as_dict(self) -> dict[str, Any]:
        return {
            "layout_version": self.layout_version,
            "family": self.family,
            "board_index": self.board_index,
            "rows": self.rows,
            "cols": self.cols,
            "target_indices": list(self.target_indices),
            "page": {
                "width_mm": self.page.width_mm,
                "height_mm": self.page.height_mm,
                "margin_mm": self.page.margin_mm,
            },
            "tag": {"size_mm": self.tag.size_mm, "gap_mm": self.tag.gap_mm},
            "logical_mapping": self.logical_mapping,
        }


def layout_from_dict(payload: dict[str, Any]) -> Layout:
    page = PageSpec(
        width_mm=float(payload["page"]["width_mm"]),
        height_mm=float(payload["page"]["height_mm"]),
        margin_mm=float(payload["page"]["margin_mm"]),
    )
    tag = TagSpec(size_mm=float(payload["tag"]["size_mm"]), gap_mm=float(payload["tag"]["gap_mm"]))
    return Layout(
        board_index=int(payload["board_index"]),
        rows=int(payload["rows"]),
        cols=int(payload["cols"]),
        target_indices=tuple(int(v) for v in payload["target_indices"]),
        page=page,
        tag=tag,
        layout_version=int(payload.get("layout_version", LAYOUT_VERSION)),
        family=str(payload.get("family", table.FAMILY)),
        logical_mapping=dict(payload.get("logical_mapping", {})),
    )


def load_layout(path: str | Path) -> Layout:
    return layout_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
