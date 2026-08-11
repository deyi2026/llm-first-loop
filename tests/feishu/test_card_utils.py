"""飞书卡片构造与表格转换单测（M45，纯函数）.

_build_card_content：Card 2.0 JSON 字符串结构断言（schema/config/body.elements[markdown]）。
convert_tables_to_bullets：表头加粗/分隔行丢弃/数据行 bullets/fence 内不转换/单元格 strip 去空/无表格原样。
"""

import json

from llm_loop.feishu.card_utils import _build_card_content, convert_tables_to_bullets


def test_build_card_content_structure():
    """用例 9：Card 2.0 JSON 字符串结构断言（schema/config/body.elements[markdown].content==原文）."""
    text = "# 标题\n```python\nprint(1)\n```"
    card = json.loads(_build_card_content(text))
    assert card["schema"] == "2.0"
    assert card["config"]["width_mode"] == "fill"
    element = card["body"]["elements"][0]
    assert element["tag"] == "markdown"
    assert element["content"] == text  # 内容如实透传不截断不篡改


def test_build_card_content_ensure_ascii_false():
    """Card JSON ensure_ascii=False（中文原文可读，非 unicode 转义序列）."""
    raw = _build_card_content("你好世界")
    assert "你好世界" in raw  # 中文原文在 JSON 字符串中可读


def test_convert_tables_basic():
    """用例 8：表头加粗 + 分隔行丢弃 + 数据行 bullets."""
    md = "| 列A | 列B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    out = convert_tables_to_bullets(md)
    lines = out.splitlines()
    assert lines[0] == "**列A | 列B**"  # 表头加粗
    assert "- 1；2" in lines  # 数据行 bullets（分号连接）
    assert "- 3；4" in lines
    assert len(lines) == 3  # 分隔行被丢弃


def test_convert_tables_cell_strip():
    """单元格 strip + 去空（空格单元格丢弃）."""
    md = "| A | B |\n|---|---|\n| x  |   |\n|  | y |"
    out = convert_tables_to_bullets(md)
    assert "- x" in out  # 空格单元格去空后仅保留 x
    assert "- y" in out


def test_convert_tables_fence_ignored():
    """fence 内表格不转换（原样保留）."""
    md = "```\n| A | B |\n|---|---|\n| 1 | 2 |\n```"
    out = convert_tables_to_bullets(md)
    assert "| A | B |" in out  # fence 内原样
    assert "**" not in out  # 无加粗转换


def test_convert_tables_no_table_passthrough():
    """无表格文本原样透传（零改动）."""
    text = "# 标题\n普通段落\n- 列表项"
    assert convert_tables_to_bullets(text) == text
