"""英文文档对等化守护测试（P3-2，2026-08-15）.

docs/api.en.md / docs/ai_rules.en.md / README.en.md 与中文版结构对等：
- api.en 与 api.md 章节数一致（防漏译）
- ai_rules.en 含 RULE-AI-00~11 全部编号（规则真相源对等）
- README.en 版本号与中文一致（防陈旧）
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _ROOT / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_api_en_has_same_section_count():
    zh = _read(_DOCS / "api.md")
    en = _read(_DOCS / "api.en.md")
    zh_heads = [l for l in zh.splitlines() if l.startswith(("# ", "## "))]
    en_heads = [l for l in en.splitlines() if l.startswith(("# ", "## "))]
    assert len(en_heads) == len(zh_heads), f"章节数不一致: zh={len(zh_heads)} en={len(en_heads)}"


def test_ai_rules_en_has_all_rule_numbers():
    en = _read(_DOCS / "ai_rules.en.md")
    for i in range(12):
        assert f"RULE-AI-{i:02d}" in en, f"ai_rules.en.md 缺 RULE-AI-{i:02d}"


def test_readme_en_parity_basics():
    en = _read(_ROOT / "README.en.md")
    zh = _read(_ROOT / "README.md")
    # 版本一致（防陈旧）
    m_zh = re.search(r"\*\*Version\*\*: ([0-9.]+)", zh)
    m_en = re.search(r"\*\*Version\*\*: ([0-9.]+)", en)
    assert m_zh and m_en, "README 缺 Version 行"
    assert m_zh.group(1) == m_en.group(1), f"版本不一致: zh={m_zh.group(1)} en={m_en.group(1)}"
    # 关键架构句对等存在
    assert "message in" in en and "answer honestly" in en
    assert "ai_rules.md" in en  # 规则真相源链接
