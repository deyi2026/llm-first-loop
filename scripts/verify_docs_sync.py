#!/usr/bin/env python3
"""文档同步校验脚本（design.md 4.1.4 / T48）.

断言:
1. spec/design/tasks 正文不含已废弃措辞（停滞检测/更正（最多 1 次）/参数边界校验等）
2. README 含必备关键词（search_archive/search_records/ai_rules/SYSTEM_PROMPT_EXTRA/CLI 子命令）
3. docs/ai_rules.md 规则同步（委托 tests/unit/test_ai_rules_sync.py——单一真相源，防双契约漂移）

用法: python scripts/verify_docs_sync.py（需可 import pytest 的解释器，推荐仓库 .venv）
退出码: 0=通过, 1=漂移（含委托测试失败）
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / ".codeartsdoer" / "specs" / "llm_first_loop"

_DEPRECATED_PHRASES = ["更正（最多 1 次）", "参数边界校验", "前置类型拦截"]
_M11_START = {"spec.md": 610, "design.md": 2028, "tasks.md": 668}
_README_KEYWORDS = [
    "search_archive", "search_records", "ai_rules", "SYSTEM_PROMPT_EXTRA",
    "list", "delete", "archive", "extract", "--session",
]
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_rules_sync_test() -> tuple[int, str]:
    """委托 pytest 运行规则同步测试（单一真相源），返回 (退出码, 输出尾部)。

    旧实现钉死 RULE-AI-01..05 并断言其存在于 core/prompt.py；规则体系已按
    agency-first 迁出通用提示词（见 test_universal_prompt_does_not_mirror_rule_playbook），
    双契约漂移造成假红（2026-09-17 实证）。规则同步性以该测试为准，本脚本不再复制契约。
    """
    if importlib.util.find_spec("pytest") is None:
        return 125, "pytest 不可用：请用仓库 .venv 解释器运行本脚本"
    cmd = [
        sys.executable, "-m", "pytest",
        str(ROOT / "tests" / "unit" / "test_ai_rules_sync.py"), "-q",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 124, "pytest 运行超时（120s）"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out[-1500:]


def main() -> int:
    errors: list[str] = []

    # 1. 废弃措辞检查（specs 为本地开发文档；开源仓库不含时跳过该步）
    if SPEC_DIR.is_dir():
        for fname, m11_line in _M11_START.items():
            body = _read(SPEC_DIR / fname).splitlines()[: m11_line - 1]
            for i, line in enumerate(body, 1):
                for phrase in _DEPRECATED_PHRASES:
                    if phrase in line and "已移除" not in line and "不再" not in line and "移交" not in line:
                        errors.append(f"{fname}:{i} 含废弃措辞 '{phrase}'")
    else:
        print("（specs 为本地开发文档，仓库不含——跳过废弃措辞检查）")

    # 2. README 关键词
    readme = _read(ROOT / "README.md")
    for kw in _README_KEYWORDS:
        if kw not in readme:
            errors.append(f"README 缺关键词: {kw}")

    # 3. 规则编号一致性——委托 tests/unit/test_ai_rules_sync.py（单一真相源）
    rules_rc, rules_out = _run_rules_sync_test()
    if rules_rc != 0:
        errors.append(f"ai_rules 同步测试失败（exit={rules_rc}）")
        print(rules_out.rstrip())

    if errors:
        print("❌ 文档同步校验失败:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ 文档同步校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
