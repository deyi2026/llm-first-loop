"""飞书卡片构造与表格转换单测（M45，纯函数）.

_build_card_content：Card 2.0 JSON 字符串结构断言（schema/config/body.elements[markdown]）。
convert_tables_to_bullets：表头加粗/分隔行丢弃/数据行 bullets/fence 内不转换/单元格 strip 去空/无表格原样。
P2-1 sanitize_html_tags / P2-4 detect_math_formula：HTML 清洗与公式检测纯函数。
"""

import json

from llm_loop.feishu.card_utils import (
    _build_card_content,
    convert_tables_to_bullets,
    detect_math_formula,
    sanitize_html_tags,
)


def test_build_card_content_structure():
    """用例 9：Card 2.0 JSON 字符串结构断言（schema/config/body.elements[markdown]）."""
    text = "# 标题\n```python\nprint(1)\n```"
    card = json.loads(_build_card_content(text))
    assert card["schema"] == "2.0"
    assert card["config"]["width_mode"] == "fill"
    element = card["body"]["elements"][0]
    assert element["tag"] == "markdown"
    assert element["content"] == text  # 无标签文本清洗后原样透传（零改动）


def test_build_card_content_ensure_ascii_false():
    """Card JSON ensure_ascii=False（中文原文可读，非 unicode 转义序列）."""
    raw = _build_card_content("你好世界")
    assert "你好世界" in raw  # 中文原文在 JSON 字符串中可读


def test_convert_tables_basic():
    """用例 8：表头加粗 bullet + 分隔行丢弃 + 数据行缩进子 bullet（G2 列语义增强）."""
    md = "| 列A | 列B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    out = convert_tables_to_bullets(md)
    lines = out.splitlines()
    assert lines[0] == "- **列A | 列B**"  # 表头 bullet + 加粗列名
    assert "  - 列A: 1；列B: 2" in lines  # 数据行缩进子 bullet（列名映射）
    assert "  - 列A: 3；列B: 4" in lines
    assert len(lines) == 4  # 分隔行被丢弃 + F2 来源标注
    assert "已转为键值列表" in lines[-1]  # F2: 降级增强标注


def test_convert_tables_cell_strip():
    """单元格 strip + 去空（空单元格丢弃；G2 列名映射下键值对保留）."""
    md = "| A | B |\n|---|---|\n| x  |   |\n|  | y |"
    out = convert_tables_to_bullets(md)
    assert "  - A: x" in out  # 空单元格去空，仅保留 x（带列名）
    assert "  - A: y" in out  # 空单元格去空，仅保留 y（带列名）


def test_convert_tables_multi_column_readable():
    """G2: 超长多列表格转 bullets 后可读性——列名全保留、每值关联列名."""
    md = "| 姓名 | 年龄 | 城市 | 职业 |\n|---|---|---|---|\n| 张三 | 28 | 北京 | 工程师 |\n| 李四 | 32 | 上海 | 设计师 |"
    out = convert_tables_to_bullets(md)
    assert "- **姓名 | 年龄 | 城市 | 职业**" in out
    assert "  - 姓名: 张三；年龄: 28；城市: 北京；职业: 工程师" in out
    assert "  - 姓名: 李四；年龄: 32；城市: 上海；职业: 设计师" in out
    # 无值丢失（PREFERENCE_3）：所有单元格内容均在输出中
    for token in ("张三", "28", "北京", "工程师", "李四", "32", "上海", "设计师"):
        assert token in out


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


# ── P2-1 HTML 清洗 / P2-4 公式检测 ──

def test_sanitize_html_strips_tags_keeps_br():
    """P2-1: `<b>/<a>/<div>` 剥离、`<br>` 保留、无标签零改动."""
    assert sanitize_html_tags("<b>加粗</b> 文本 <a href='x'>链接</a>") == "加粗 文本 链接"
    assert sanitize_html_tags("第一行<br>第二行") == "第一行<br>第二行"
    assert sanitize_html_tags("普通文本无标签") == "普通文本无标签"


def test_sanitize_html_fence_ignored():
    """P2-1: fence 内 `<...>` 原样保留（不破坏代码示例）."""
    text = "```python\nprint('<div>html</div>')\n```\n<div>外部标签</div>"
    out = sanitize_html_tags(text)
    assert "print('<div>html</div>')" in out
    assert "<div>外部标签</div>" not in out


def test_detect_math_inline_and_block():
    """P2-4: `$...$`/`$$...$$` 命中、无公式 False."""
    assert detect_math_formula("公式 $E=mc^2$ 内联") is True
    assert detect_math_formula("块级\n$$\\int_0^1 x dx$$") is True
    assert detect_math_formula("无公式普通文本") is False


def test_detect_math_fence_ignored():
    """P2-4: fence 内 `$...$` 不误判."""
    text = "```python\nx = '$not_math$'\n```\n后面 $真公式$"
    assert detect_math_formula(text) is True
    assert detect_math_formula("```\n只含代码 $a+b$\n```") is False


# ── G3 错误醒目化 ──

def test_detect_error_status_variants():
    """G3: `[状态: error/failure]`/`[参数错误]`/`[安全硬阻断]`/`[程序异常]` 命中、大小写不敏感、正常文本 False."""
    from llm_loop.feishu.card_utils import detect_error_status

    for marker in (
        "[状态: error]",
        "[状态: failure]",
        "[状态: 参数错误]",
        "[状态: 安全硬阻断]",
        "[状态: 程序异常]",
        "[状态: ERROR]",
    ):
        assert detect_error_status(f"前缀 {marker} 后缀") is True, marker
    assert detect_error_status("正常回答内容") is False
    assert detect_error_status("") is False


# ── G4 长回执折叠 ──

def test_build_summary_card_truncate():
    """G4: 摘要卡截断 ≤200 字符、含折叠标注与引导、不切碎多字节字符."""
    from llm_loop.feishu.card_utils import build_summary_card

    long_text = "数据" * 200  # 400 字符（中文多字节）
    card = build_summary_card(long_text)
    assert "内容过长已折叠" in card
    assert "原文已存，可回复'展开全文'" in card
    # 截断部分 ≤ max_chars（默认 200），且不切碎多字节（'数据' 是完整字符对）
    head = card.split("…")[0]
    assert head.endswith("数据")
    assert len(head) <= 200

    short = build_summary_card("简短", max_chars=2)
    assert short.startswith("简")  # max_chars 正数下限 + 不切碎

    tiny = build_summary_card("abc", max_chars=0)
    assert tiny.startswith("a")  # max_chars=0 → 下限 1


# ── F1: 超长行折行（零宽空格软折行）──


def test_fold_long_url():
    """长 URL 无断点 → 每 limit 字符插零宽空格."""
    from llm_loop.feishu.card_utils import fold_long_lines

    url = "https://example.com/" + "a" * 150
    out = fold_long_lines(url, limit=50)
    parts = out.split("\u200b")
    assert all(len(p) <= 50 for p in parts)
    assert "".join(parts) == url  # 内容无损


def test_fold_short_line_unchanged():
    from llm_loop.feishu.card_utils import fold_long_lines

    assert fold_long_lines("短行", limit=50) == "短行"
    assert fold_long_lines("", limit=50) == ""


def test_fold_line_with_spaces_unchanged():
    """有空白断点的行不折（自然换行可用）."""
    from llm_loop.feishu.card_utils import fold_long_lines

    line = "word " * 60  # 有空格
    assert fold_long_lines(line, limit=50) == line


def test_fold_skips_code_fence():
    """fence 内代码行不折（保留可复制性）."""
    from llm_loop.feishu.card_utils import fold_long_lines

    code = "x" * 200
    text = f"```python\n{code}\n```"
    assert fold_long_lines(text, limit=50) == text


def test_fold_multiline_mixed():
    from llm_loop.feishu.card_utils import fold_long_lines

    long = "y" * 120
    code_long = "z" * 300
    text = f"正常行\n{long}\n```\n{code_long}\n```\n尾部"
    out = fold_long_lines(text, limit=100)
    assert "\u200b" in out  # 非 fence 长行被折
    # fence 内容仍在原样
    assert f"```\n{code_long}\n```" in out
    assert "正常行" in out and "尾部" in out


# ── F2: 表格降级增强（来源标注 + 列数提示）──


def test_convert_tables_no_table_no_note():
    """无表格文本 → 原样返回（不加 F2 标注）."""
    from llm_loop.feishu.card_utils import convert_tables_to_bullets

    text = "纯文本\n没有表格"
    assert convert_tables_to_bullets(text) == text


def test_convert_tables_many_columns_note():
    """列数 >6 → 列数过多提示."""
    from llm_loop.feishu.card_utils import convert_tables_to_bullets

    cols = "| " + " | ".join(f"列{i}" for i in range(1, 8)) + " |"
    sep = "|" + "---|" * 7
    row = "| " + " | ".join(str(i) for i in range(1, 8)) + " |"
    out = convert_tables_to_bullets(f"{cols}\n{sep}\n{row}")
    assert "列数较多" in out
    assert "7 列" in out
