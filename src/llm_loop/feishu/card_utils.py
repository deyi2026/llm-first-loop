"""飞书卡片构造与表格转换（M45，纯函数）.

Card 2.0（interactive）结构对齐 本地既有实现 ws_reply.py:58-62（引用非改写）；
表格转 bullet 列表对齐 本地既有实现 markdown_chunker.py 表格处理算法思路（自实现，引用非改写）。
纯函数、无外部依赖（仅标准库 json/re），独立可单测。
"""

import json
import re

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


def _build_card_content(text: str) -> str:
    """构造 Card 2.0 JSON 字符串（markdown 元素，内容如实透传）.

    Args:
        text: 回复 markdown 原文（不截断不篡改不转义）.

    Returns:
        Card 2.0 JSON 字符串（json.dumps ensure_ascii=False，中文原文可读）.
    """
    card = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "body": {"elements": [{"tag": "markdown", "content": text}]},
    }
    return json.dumps(card, ensure_ascii=False)


def convert_tables_to_bullets(text: str) -> str:
    """markdown 表格转 bullet 列表（单元格内容不丢失，PREFERENCE_3）.

    转换规则（逐行扫描）：
    ① fence 感知：``` 内内容原样保留不转换；
    ② 非表格行（不以 | 开头）→ 原样输出，重置表格状态；
    ③ 表头行（进入表格后的第一个数据行）→ 加粗 `**单元格1 | 单元格2**`；
    ④ 分隔行（`|---|---|` 等）→ 丢弃；
    ⑤ 数据行 → `- 单元格1；单元格2`（分号连接，单元格 strip + 去空）；
    ⑥ 无表格文本原样透传。

    Args:
        text: 原始 markdown 文本（可能含表格）.

    Returns:
        表格已转 bullet 列表的文本（无表格则原样返回）.
    """
    lines_out: list[str] = []
    in_fence = False
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            lines_out.append(line)
            continue
        if in_fence:
            lines_out.append(line)
            continue
        if not stripped.startswith("|"):
            in_table = False
            lines_out.append(line)
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        cells = [c for c in cells if c]
        if not cells:
            in_table = False
            lines_out.append(line)
            continue
        if in_table and _TABLE_SEPARATOR_RE.match(stripped):
            continue  # 分隔行丢弃（表头后）
        if not in_table:
            lines_out.append("**" + " | ".join(cells) + "**")
            in_table = True
        else:
            lines_out.append("- " + "；".join(cells))
    return "\n".join(lines_out)
