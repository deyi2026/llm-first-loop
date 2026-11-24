"""CTP 图案生成工具链 v0（B6）：布局 → 码字 → PDF + 清单。

边界：
- 只负责"生成已知真值的靶标图案"；读取与位姿解算是 B3；
- 码字来自 BSD-2 上游（见 tag36h11_table.py 头注），不自造码族（K4）；
- 公差、最小可读条件等门槛数值一律不在此设定（[TBD-*] 归 SPEC）。
"""

from __future__ import annotations

from .codes import bit_matrix, code_at, family_invariants
from .layout import Layout, PageSpec, TagSpec, layout_from_dict, load_layout
from .manifest import verify_manifest
from .render import generate

__all__ = [
    "Layout",
    "PageSpec",
    "TagSpec",
    "bit_matrix",
    "code_at",
    "family_invariants",
    "generate",
    "layout_from_dict",
    "load_layout",
    "verify_manifest",
]
