#!/usr/bin/env python3
"""测试副作用审计（EVO-20260811-f1e43351 落地）.

扫描 tests/ 中未 Mock 的真实副作用调用，pytest 运行前自动检查并告警：
  - 真实系统副作用: osascript / 系统通知 / 弹窗类
  - 真实网络: httpx/requests 直接请求（未 Mock 且非只读校验）
  - 真实 LLM 调用: client.chat(...) 等真实 API 调用（非仅构造对象）
  - 真实 data 目录写盘: data_dir="./data" 硬编码（M64 兜底之外的显式风险）

豁免规则（避免误报）:
  1. 文件含 mock/patch/monkeypatch/Fake/tmp_path 标记 → 已隔离，跳过
  2. 子进程只读校验（bash -n / node --check / git check-ignore 等）→ 无副作用，跳过
  3. LLMClient 仅构造不调用（无 .chat( 实际调用）→ 纯逻辑测试，跳过
  4. @pytest.mark.real_llm 标记 → 有意真实冒烟（无 key 会 skip），豁免
  5. 行内注释 audit-skip → 显式豁免

告警不阻断（exit 0）；--strict 时存在告警 exit 1。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"

# 真实副作用模式（更精确）
RISK_PATTERNS = [
    # 系统弹窗/通知（真实副作用）
    (r"osascript", "系统弹窗", "AppleScript 真实弹窗"),
    (r"\bnotify\w*\s*\(|notify\.(send|post)|os\.system\(['\"]osascript", "系统通知", "真实通知/系统调用"),
    # 真实网络请求（排除只读校验）
    (r"httpx\.(get|post|put|delete|request|stream)\s*\(", "网络", "httpx 直接请求"),
    (r"requests\.(get|post|put|delete|request)\s*\(", "网络", "requests 直接请求"),
    # 真实 LLM 调用（仅构造不算——需有 .chat( 等实际调用）
    (r"\.chat\s*\(|\.complete\s*\(|\.generate\s*\(", "LLM API", "真实 LLM API 调用"),
    # 显式写真实 data 目录
    (r"data_dir\s*=\s*[\"']\.?/?data[\"']", "数据污染", "硬编码真实 data 目录"),
    (r"SessionStore\([^)]*[\"'](\./data|data)[\"']", "数据污染", "SessionStore 指向真实 data"),
]

# 只读校验子进程模式（bash -n / node --check 等 → 无副作用）
READONLY_SUBPROCESS = re.compile(
    r"(bash\s+-n|--check|check-ignore|--syntax-check|ruff\s+check|shutil\.which)"
)
SUBPROCESS_CALL = re.compile(r"subprocess\.(run|Popen|call|check_call|check_output)\s*\(")

# 已隔离标记（出现任一即跳过整个文件）
ISOLATED_MARKERS = ["unittest.mock", "from unittest import mock", "mock", "Mock", "patch", "monkeypatch",
                    "Fake", "tmp_path", "MagicMock", "real_llm", "audit-skip"]


_SUBPROCESS_CALL_RE = re.compile(
    r"subprocess\.(run|Popen|call|check_call|check_output)\s*\([^)]*\)",
    re.DOTALL,
)


def _is_readonly_subprocess(line: str) -> bool:
    """子进程调用（跨行）是否只读校验（无真实副作用）。"""
    for m in _SUBPROCESS_CALL_RE.finditer(line):
        if READONLY_SUBPROCESS.search(m.group(0)):
            return True
    return False


def audit_file(path: Path) -> list[tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if any(m in text for m in ISOLATED_MARKERS):
        return []
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines, 1):
        # 行内显式豁免
        if "audit-skip" in line:
            continue
        # 子进程：跨行合并检查（run( 与 --check 可能异行）；只读校验跳过
        if SUBPROCESS_CALL.search(line):
            block = "\n".join(lines[i - 1 : min(i + 3, len(lines))])
            if _is_readonly_subprocess(block):
                continue
            hits.append(("子进程", "非只读子进程执行", f"{path.relative_to(PROJECT_ROOT)}:{i}"))
            continue
        for pat, cat, desc in RISK_PATTERNS:
            if re.search(pat, line):
                hits.append((cat, desc, f"{path.relative_to(PROJECT_ROOT)}:{i}"))
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="测试副作用审计（告警不阻断；--strict 时告警 exit 1）")
    ap.add_argument("--strict", action="store_true", help="存在告警时退出码 1")
    ap.add_argument("--root", default=str(TESTS_DIR), help="扫描目录（默认 tests/）")
    args = ap.parse_args()

    root = Path(args.root)
    py_files = sorted(root.rglob("*.py"))
    total_hits: list[tuple[str, str, str]] = []
    for f in py_files:
        total_hits.extend(audit_file(f))

    if total_hits:
        print(f"[测试副作用审计] ⚠️ 发现 {len(total_hits)} 处疑似真实副作用（共 {len(py_files)} 个测试文件）:")
        for cat, desc, loc in total_hits[:40]:
            print(f"  - [{cat}] {desc} @ {loc}")
        if len(total_hits) > 40:
            print(f"  … 其余 {len(total_hits) - 40} 处省略")
        print("[测试副作用审计] 注: 命中不含 mock/patch/Fake/real_llm 标记；如确属有意真实调用请加行内 audit-skip。")
        return 1 if args.strict else 0
    print(f"[测试副作用审计] ✅ 未发现未 Mock 的真实副作用（扫描 {len(py_files)} 个测试文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
