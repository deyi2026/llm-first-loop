"""T47: 文档同步校验（FR-AUD-DOC-08）.

spec/design/tasks 不含已废弃措辞（M10/M11 移除项）；README 含必备关键词。

开源说明（2026-08-14）: `.codeartsdoer/specs/` 为本地开发过程文档（CodeArts 工作流），
开源仓库不含——三件套校验在 specs 存在时（本地开发环境）生效，缺失时（公开仓库/CI）跳过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC_DIR = _ROOT / ".codeartsdoer" / "specs" / "llm_first_loop"

_SPECS_AVAILABLE = _SPEC_DIR.is_dir()

# 已废弃措辞（M10/M11 移除，正文不得再出现——M11 审计章节的历史引用除外）
_DEPRECATED_PHRASES = [
    "更正（最多 1 次）",
    "参数边界校验",
    "前置类型拦截",
]
# M11 章节行号起始（spec.md 第 8 章 / design.md §四 / tasks.md M11 段）。
# P1-1: 本项目文档较短（spec.md ~92 行），旧值（610/2028/668）为外部大项目行号，
# 改为动态取文档总行数（=全量检查），确保废弃措辞检查对本项目文档实际生效。
_M11_START = {
    "spec.md": 10_000,
    "design.md": 10_000,
    "tasks.md": 10_000,
}


def _read(path: str) -> str:
    if path.startswith(("spec.md", "design.md", "tasks.md")):
        return (_SPEC_DIR / path).read_text(encoding="utf-8")
    return (_ROOT / path).read_text(encoding="utf-8")


@pytest.mark.skipif(not _SPECS_AVAILABLE, reason="specs 为本地开发文档，开源仓库不含")
def test_docs_no_deprecated_phrases():
    """spec/design/tasks 正文不含已废弃措辞（M11 章节历史引用豁免）."""
    for fname, m11_line in _M11_START.items():
        full = _read(fname)
        # M11 章节前的主体部分（P1-1: 本项目文档无 M11 历史章节，全量检查）
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


@pytest.mark.skipif(not _SPECS_AVAILABLE, reason="specs 为本地开发文档，开源仓库不含")
def test_spec_design_tasks_exist():
    """P1-1: `.codeartsdoer/specs/llm_first_loop/` 下三文档均存在且非空."""
    for fname in ("spec.md", "design.md", "tasks.md"):
        path = _SPEC_DIR / fname
        assert path.exists(), f"缺少文档: {path}"
        assert path.stat().st_size > 0, f"文档为空: {path}"


@pytest.mark.skipif(not _SPECS_AVAILABLE, reason="specs 为本地开发文档，开源仓库不含")
def test_spec_dir_points_to_project():
    """P1-1: `_SPEC_DIR` 指向本项目 `.codeartsdoer/specs/llm_first_loop` 且目录存在."""
    assert _SPEC_DIR.is_dir(), f"目录不存在: {_SPEC_DIR}"
    # 目录确实位于本项目根下（开源脱敏：不引用任何外部个人路径）
    assert str(_SPEC_DIR).startswith(str(_ROOT))
