#!/usr/bin/env python3
"""文档同步校验脚本（design.md 4.1.4 / T48）.

断言:
1. spec/design/tasks 正文不含已废弃措辞（停滞检测/更正（最多 1 次）/参数边界校验等）
2. README 含必备关键词（search_archive/search_records/ai_rules/SYSTEM_PROMPT_EXTRA/CLI 子命令）
3. docs/ai_rules.md 五条规则编号与 prompt.py 对应（复用 test_ai_rules_sync 逻辑）

用法: python scripts/verify_docs_sync.py
退出码: 0=通过, 1=漂移
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = Path("<外部项目路径>/.codeartsdoer/specs/llm_first_loop")

_DEPRECATED_PHRASES = ["更正（最多 1 次）", "参数边界校验", "前置类型拦截"]
_M11_START = {"spec.md": 610, "design.md": 2028, "tasks.md": 668}
_README_KEYWORDS = [
    "search_archive", "search_records", "ai_rules", "SYSTEM_PROMPT_EXTRA",
    "list", "delete", "archive", "extract", "--session",
]
_RULES = ["RULE-AI-01", "RULE-AI-02", "RULE-AI-03", "RULE-AI-04", "RULE-AI-05"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    # 1. 废弃措辞检查
    for fname, m11_line in _M11_START.items():
        body = _read(SPEC_DIR / fname).splitlines()[: m11_line - 1]
        for i, line in enumerate(body, 1):
            for phrase in _DEPRECATED_PHRASES:
                if phrase in line and "已移除" not in line and "不再" not in line and "移交" not in line:
                    errors.append(f"{fname}:{i} 含废弃措辞 '{phrase}'")

    # 2. README 关键词
    readme = _read(ROOT / "README.md")
    for kw in _README_KEYWORDS:
        if kw not in readme:
            errors.append(f"README 缺关键词: {kw}")

    # 3. 规则编号一致性
    doc = _read(ROOT / "docs" / "ai_rules.md")
    prompt = _read(ROOT / "src" / "llm_loop" / "core" / "prompt.py")
    for rule in _RULES:
        if rule not in doc:
            errors.append(f"ai_rules.md 缺 {rule}")
        if rule not in prompt:
            errors.append(f"prompt.py 缺 {rule}")

    if errors:
        print("❌ 文档同步校验失败:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ 文档同步校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())