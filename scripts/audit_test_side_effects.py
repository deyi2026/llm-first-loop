#!/usr/bin/env python3
"""测试副作用审计（EVO-20260811-f1e43351）: 扫描 tests/ 未 Mock 的真实副作用高风险特征.

检测（高置信、docstring/注释感知、防误报）:
1. 硬编码真实 data 目录（data_dir=./data / data/sessions → 写真实数据）
2. base_url 指向真实 provider（非 localhost/fake/example/.local/embed → 触网）
3. 裸真实网络调用（requests/httpx/urllib 直接调用且文件无 mock/fake 痕迹）
用法: python scripts/audit_test_side_effects.py [tests 目录]
仅告警不阻断（fail-open）: 异常/无结果返回 0，绝不改变 pytest 行为。
2026-08-23 落地审查: 61→14→8→3 处（排除 docstring/注释/短 fake 值/本地地址/测试数据字符串）。
已知低风险项（人工复核，非误报）: 测试配置真实 provider base_url 但经 FakeLLM 隔离不触网。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REAL_DATA = re.compile(r'data_dir\s*=\s*["\'](\./)?data(?:/|["\']|$)', re.IGNORECASE)
_REAL_DATA_SESSIONS = re.compile(r'["\'](?:\./)?data/sessions["\']')
_REAL_BASE_URL = re.compile(r'base_url\s*=\s*["\'](https?://[^"\']+)["\']', re.IGNORECASE)
_RAW_NET = re.compile(r"(?<!\.)\b(requests|httpx|urllib|aiohttp)\.(get|post|put|delete|request|Client)\(")
_LOCALHOST = ("localhost", "127.0.0.1")
_LOWRISK_URL_MARK = ("fake", "example", ".local", "embed")


def _scan_file(py: Path) -> list[str]:
    hits: list[str] = []
    try:
        lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    text = "\n".join(lines).lower()
    in_doc = False
    for i, line in enumerate(lines, 1):
        s = line.lstrip()
        if '"""' in s or "'''" in s:
            in_doc = not in_doc
            continue
        if in_doc or s.startswith(("#", '"', "'", "//", "<", "*")):
            continue
        rel = f"{py.relative_to(py.parent.parent.parent) if False else py}"
        if _REAL_DATA.search(line) or _REAL_DATA_SESSIONS.search(line):
            hits.append(f"{py}:{i} 真实data写入: {line.strip()[:80]}")
        m = _REAL_BASE_URL.search(line)
        if m:
            url = m.group(1)
            if not any(t in url for t in _LOCALHOST) and len(url) >= 15 and not any(t in url for t in _LOWRISK_URL_MARK):
                hits.append(f"{py}:{i} 真实provider base_url（低风险-隔离不触网则忽略）: {line.strip()[:80]}")
        if _RAW_NET.search(line) and "mock" not in text and "fake" not in text:
            hits.append(f"{py}:{i} 裸真实网络调用: {line.strip()[:80]}")
    return hits


def scan(test_root: Path) -> list[str]:
    hits: list[str] = []
    for py in sorted(test_root.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        hits.extend(_scan_file(py))
    return hits


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "tests"
    if not root.is_dir():
        print(f"[audit_test_side_effects] 目录不存在: {root}（跳过，fail-open）")
        return 0
    hits = scan(root)
    if not hits:
        print(f"[audit_test_side_effects] ✅ {root} 无高风险真实副作用特征（{len(list(root.rglob('*.py')))} 文件）")
        return 0
    print(f"[audit_test_side_effects] ⚠️ {len(hits)} 处待人工复核（仅告警不阻断）:")
    for h in hits[:40]:
        print(f"  - {h}")
    if len(hits) > 40:
        print(f"  … 共 {len(hits)} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
