"""布局模型：一页 N 靶，target_index → 物理位置（分层映射的板内层）。

布局 JSON 自描述（B6 验收项，2026-11-24 补齐）：
- ``frame_ref``：本板坐标系的参考系定义引用（SPEC §2「参考系定义」；与 R-1 记录、C-5 pose 的
  frame_ref 同口径）。生成器只承载并校验非空，不解析——解析属 R-1 / B5；
- ``coordinate_frame`` + ``tags``：逐码显式物理坐标（左上角供渲染、中心供 B3 位姿解算），mm；
- ``tolerance``：公差标注，字段对应 SPEC P-2a / P-2b / P-2c，数值恒为 TBD 占位——工作组回填前
  不得填经验值（SPEC §0.2）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import tag36h11_table as table

LAYOUT_VERSION = 1  # v0 未发布、无存量消费者：frame_ref / tags / tolerance 并入首版，不另升位

# 坐标口径（钉定）：原点 = 页面左上角，x 向右、y 向下，单位 mm——与渲染所用 position_mm 一致
COORDINATE_FRAME = {
    "origin": "page_top_left",
    "x_axis": "right",
    "y_axis": "down",
    "length_unit": "mm",
}

# 公差标注：键对应 SPEC P-2 子条；值是 SPEC 现行的 TBD 占位编号，不是数值
TOLERANCE_PLACEHOLDERS = {"P-2a": "[TBD-P2a]", "P-2b": "[TBD-P2b]", "P-2c": "[TBD-P2c]"}
TOLERANCE_UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class PageSpec:
    width_mm: float
    height_mm: float
    margin_mm: float


@dataclass(frozen=True)
class TagSpec:
    size_mm: float
    gap_mm: float  # 靶间留白（必填；工程取值见 ctp/docs/generator-notes.md，不是规范数值）


def _require_label(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


@dataclass(frozen=True)
class Layout:
    board_index: int
    rows: int
    cols: int
    target_indices: tuple[int, ...]
    page: PageSpec
    tag: TagSpec
    frame_ref: str
    layout_version: int = LAYOUT_VERSION
    family: str = table.FAMILY
    logical_mapping: dict[str, Any] = field(default_factory=dict)
    tolerance_grade: str | None = None

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
        _require_label(self.frame_ref, "frame_ref")  # 必填：参考系定义引用不做默认值填充
        if self.tolerance_grade is not None:
            _require_label(self.tolerance_grade, "tolerance_grade")
        span_x = self.page.margin_mm * 2 + self.cols * self.tag.size_mm + (self.cols - 1) * self.tag.gap_mm
        span_y = self.page.margin_mm * 2 + self.rows * self.tag.size_mm + (self.rows - 1) * self.tag.gap_mm
        if span_x > self.page.width_mm + 1e-9 or span_y > self.page.height_mm + 1e-9:
            raise ValueError(
                f"layout does not fit page: need {span_x:.1f}x{span_y:.1f} mm, "
                f"page {self.page.width_mm:.0f}x{self.page.height_mm:.0f} mm"
            )

    def position_mm(self, slot: int) -> tuple[float, float]:
        """槽位（行优先）→ 靶标左上角毫米坐标（页面左上角为原点，y 向下）。"""
        if not 0 <= slot < self.rows * self.cols:
            raise ValueError("slot out of range")
        row, col = divmod(slot, self.cols)
        x = self.page.margin_mm + col * (self.tag.size_mm + self.tag.gap_mm)
        y = self.page.margin_mm + row * (self.tag.size_mm + self.tag.gap_mm)
        return x, y

    def tags_payload(self) -> list[dict[str, Any]]:
        """逐码物理坐标：左上角（渲染口径）与中心（B3 位姿解算用），mm。"""
        half = self.tag.size_mm / 2.0
        tags: list[dict[str, Any]] = []
        for slot, index in enumerate(self.target_indices):
            x, y = self.position_mm(slot)
            tags.append(
                {
                    "slot": slot,
                    "target_index": index,
                    "x_mm": x,
                    "y_mm": y,
                    "center_x_mm": x + half,
                    "center_y_mm": y + half,
                }
            )
        return tags

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
            "frame_ref": self.frame_ref,
            "coordinate_frame": dict(COORDINATE_FRAME),
            "tags": self.tags_payload(),
            "tolerance": {
                "grade": self.tolerance_grade if self.tolerance_grade is not None else TOLERANCE_UNSPECIFIED,
                **TOLERANCE_PLACEHOLDERS,
            },
            "logical_mapping": self.logical_mapping,
        }


def layout_from_dict(payload: dict[str, Any]) -> Layout:
    page = PageSpec(
        width_mm=float(payload["page"]["width_mm"]),
        height_mm=float(payload["page"]["height_mm"]),
        margin_mm=float(payload["page"]["margin_mm"]),
    )
    tag = TagSpec(size_mm=float(payload["tag"]["size_mm"]), gap_mm=float(payload["tag"]["gap_mm"]))
    if "frame_ref" not in payload:
        raise ValueError("layout payload lacks frame_ref (reference-frame reference is mandatory)")
    tolerance_grade: str | None = None
    declared = payload.get("tolerance")
    if isinstance(declared, dict) and declared.get("grade") not in (None, TOLERANCE_UNSPECIFIED):
        tolerance_grade = declared["grade"]
    layout = Layout(
        board_index=int(payload["board_index"]),
        rows=int(payload["rows"]),
        cols=int(payload["cols"]),
        target_indices=tuple(int(v) for v in payload["target_indices"]),
        page=page,
        tag=tag,
        frame_ref=payload["frame_ref"],
        layout_version=int(payload.get("layout_version", LAYOUT_VERSION)),
        family=str(payload.get("family", table.FAMILY)),
        logical_mapping=dict(payload.get("logical_mapping", {})),
        tolerance_grade=tolerance_grade,
    )
    # tags 是几何的派生块：随文件给出时必须与网格几何一致（手改坐标即拒绝）
    if "tags" in payload and payload["tags"] != layout.tags_payload():
        raise ValueError("tags block disagrees with grid geometry (tampered or stale layout)")
    return layout


def load_layout(path: str | Path) -> Layout:
    return layout_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
