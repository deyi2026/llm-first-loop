"""T47: 文档同步校验（FR-AUD-DOC-08）.

spec/design/tasks 不含已废弃措辞（M10/M11 移除项）；README 含必备关键词。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC_DIR = Path("<外部项目路径>/.codeartsdoer/specs/llm_first_loop")

# 已废弃措辞（M10/M11 移除，正文不得再出现——M11 审计章节的历史引用除外）
_DEPRECATED_PHRASES = [
    "更正（最多 1 次）",
    "参数边界校验",
    "前置类型拦截",
]
# M11 章节行号起始（spec.md 第 8 章 / design.md §四 / tasks.md M11 段）
_M11_START = {
    "spec.md": 610,
    "design.md": 2028,
    "tasks.md": 668,
}


def _read(path: str) -> str:
    if path.startswith(("spec.md", "design.md", "tasks.md")):
        return (_SPEC_DIR / path).read_text(encoding="utf-8")
    return (_ROOT / path).read_text(encoding="utf-8")


def test_docs_no_deprecated_phrases():
    """spec/design/tasks 正文不含已废弃措辞（M11 章节历史引用豁免）."""
    for fname, m11_line in _M11_START.items():
        full = _read(fname)
        # M11 章节前的主体部分
        body = full.splitlines()[: m11_line - 1]
        for phrase in _DEPRECATED_PHRASES:
            for i, line in enumerate(body, 1):
                if (
                    phrase in line
                    and "M10" not in line
                    and "M11" not in line
                    and "已移除" not in line
                    and "不再" not in line
                    and "已移交" not in line
                    and "移除" not in line
                ):
                    raise AssertionError(f"{fname}:{i} 含废弃措辞 '{phrase}': {line.strip()[:80]}")


def test_readme_has_required_keywords():
    """README 含必备关键词（P1 能力/检索/AI 规则/CLI）."""
    readme = _read("README.md")
    for kw in [
        "search_archive",
        "search_records",
        "ai_rules",
        "SYSTEM_PROMPT_EXTRA",
        "list",
        "--session",
        "extract",
        "submit_evolution",
        "self_evaluate",
        "evolve-review",
    ]:
        assert kw in readme, f"README 缺关键词: {kw}"


def test_readme_has_no_clear_state():
    """README 不含已移除的 clear_state（避免误导）."""
    readme = _read("README.md")
    assert "clear_state" not in readme
