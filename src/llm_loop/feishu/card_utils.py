"""飞书卡片构造与表格转换（M45，纯函数）.

Card 2.0（interactive）结构对齐 本地既有实现 ws_reply.py:58-62（引用非改写）；
表格转 bullet 列表对齐 本地既有实现 markdown_chunker.py 表格处理算法思路（自实现，引用非改写）。
纯函数、无外部依赖（仅标准库 json/re），独立可单测。
"""

import json
import re

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
# P2-4: 行内 $...$ 与块级 $$...$$（fence 感知由调用方/函数内状态机处理）
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
_BLOCK_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)

# G3: 错误状态标记检测（大小写不敏感；对齐 Web M52 错误醒目的标记集合）
_ERROR_STATUS_RE = re.compile(
    r"\[状态:\s*(?:error|failure|参数错误|安全硬阻断|程序异常)\]",
    re.IGNORECASE,
)


def detect_error_status(text: str) -> bool:
    """G3: 检测文本是否含错误状态标记（`[状态: error/failure/参数错误/安全硬阻断/程序异常]`）.

    Web 端 M52 已实现 ⚠️+红色样式；飞书卡片 markdown 无颜色能力，调用方据此
    追加 `⚠️` + 首行加粗（对齐醒目化语义）。大小写不敏感，无标记返回 False。

    Args:
        text: 回复文本.

    Returns:
        True 命中错误状态标记；False 无标记（正常内容）.
    """
    return bool(text and _ERROR_STATUS_RE.search(text))


def build_summary_card(text: str, max_chars: int = 200) -> str:
    """G4: 构造长回复摘要卡（首段截断 + 折叠标注 + 取全文引导）.

    截断前 `max_chars` 字符（字符边界不切碎多字节），追加折叠标注与
    `原文已存，可回复'展开全文'` 引导。`max_chars` 取正数下限（防御）。

    Args:
        text: 完整回复文本.
        max_chars: 摘要最大字符数（默认 200）.

    Returns:
        摘要卡文本（含折叠标注与引导；完整内容由调用方另行全量推送）.
    """
    max_chars = max(1, int(max_chars))
    summary = text[:max_chars]
    return f"{summary}…（内容过长已折叠）\n原文已存，可回复'展开全文'"


def sanitize_html_tags(text: str) -> str:
    """P2-1: 剥离 HTML 标签，白名单保留 `<br>`（换行语义），fence 内原样保留.

    飞书卡片 markdown 元素不支持 HTML 标签渲染；发送前剥离 `<[^>]+>` 完整标签。
    代码 fence（``` 内）内容原样保留，避免破坏代码示例中的 `<...>`。
    无标签文本原样返回（零改动）。

    Args:
        text: 原始 markdown 文本（可能含 HTML 标签）.

    Returns:
        已剥离标签的文本（`<br>` 保留，fence 内原样，无标签零改动）.
    """
    if not text or "<" not in text:
        return text
    out: list[str] = []
    in_fence = False
    fence_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.strip().startswith("```"):
            if in_fence:
                fence_lines.append(line)
                out.append("".join(fence_lines))
                fence_lines = []
                in_fence = False
            else:
                in_fence = True
                fence_lines = [line]
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        # fence 外: 用占位符保护 <br>，剥离其余标签后恢复
        line = _BR_RE.sub("\x00BR\x00", line)
        line = _HTML_TAG_RE.sub("", line)
        line = line.replace("\x00BR\x00", "<br>")
        out.append(line)
    if fence_lines:
        out.append("".join(fence_lines))
    return "".join(out)


def detect_math_formula(text: str) -> bool:
    """P2-4: 检测 markdown 文本是否含 LaTeX 公式（`$...$`/`$$...$$`），fence 内不误判.

    飞书卡片不支持 KaTeX/LaTeX 渲染，命中时调用方追加降级提示。
    代码 fence（``` 内）的 `$...$` 视为代码不检测；无公式返回 False。

    Args:
        text: 原始 markdown 文本.

    Returns:
        True 命中公式；False 无公式或仅 fence 内出现.
    """
    if not text or "$" not in text:
        return False
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _BLOCK_MATH_RE.search(line):
            return True
        # 行内公式: 剥离块级命中后的残留避免误判（块级优先）
        rest = _BLOCK_MATH_RE.sub("", line)
        if _INLINE_MATH_RE.search(rest):
            return True
    return False


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
        "body": {"elements": [{"tag": "markdown", "content": sanitize_html_tags(text)}]},
    }
    return json.dumps(card, ensure_ascii=False)


def convert_tables_to_bullets(text: str) -> str:
    """markdown 表格转 bullet 列表（单元格内容不丢失，PREFERENCE_3；G2 列语义增强）.

    转换规则（逐行扫描）：
    ① fence 感知：``` 内内容原样保留不转换；
    ② 非表格行（不以 | 开头）→ 原样输出，重置表格状态；
    ③ 表头行（进入表格后的第一个数据行）→ `- **列名1 | 列名2**`（bullet 锚点 + 加粗列名，保留列顺序）；
    ④ 分隔行（`|---|---|` 等）→ 丢弃；
    ⑤ 数据行 → `  - 列名1: 值1；列名2: 值2`（缩进子 bullet + 列名-值键值对映射，多列分号连接）；
    ⑥ 无表格文本原样透传。

    Args:
        text: 原始 markdown 文本（可能含表格）.

    Returns:
        表格已转 bullet 列表的文本（无表格则原样返回）.
    """
    lines_out: list[str] = []
    in_fence = False
    in_table = False
    headers: list[str] = []
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
            headers = []
            lines_out.append(line)
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        cells = [c for c in cells if c]
        if not cells:
            in_table = False
            headers = []
            lines_out.append(line)
            continue
        if in_table and _TABLE_SEPARATOR_RE.match(stripped):
            continue  # 分隔行丢弃（表头后）
        if not in_table:
            headers = cells
            lines_out.append("- **" + " | ".join(cells) + "**")
            in_table = True
        else:
            if headers:
                pairs = [f"{h}: {c}" for h, c in zip(headers, cells, strict=False)]
                lines_out.append("  - " + "；".join(pairs))
            else:
                lines_out.append("- " + "；".join(cells))
    return "\n".join(lines_out)
