"""JS 语法完整性守护（T1 拆分回归防线）。

T1 模块化拆分时曾出现函数体劈裂（showCmdSuggest 前半残留 command-upload-model.js、
后半误入 app.js），静态字符串匹配无法捕获，导致浏览器端 SyntaxError 全站失效。
本测试用 node --check 逐文件校验语法，发现即失败。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"

_JS_FILES = [
    "app.js",
    "modules/state.js",
    "modules/markdown-math.js",
    "modules/tool-render.js",
    "modules/message-render.js",
    "modules/stream-chat.js",
    "modules/app-core.js",
    "modules/responsive.js",
    "modules/session-list.js",
    "modules/command-upload-model.js",
]


def test_js_syntax_all_files() -> None:
    """所有前端 JS 文件必须通过 node --check（防拆分劈裂/残留残缺代码）。"""
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node 不可用，跳过 JS 语法校验")
    for rel in _JS_FILES:
        p = STATIC_DIR / rel
        assert p.exists(), f"缺少 JS 文件: {rel}"
        proc = subprocess.run(
            [node, "--check", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"{rel} 语法错误:\n{proc.stderr}"


def test_js_balanced_braces() -> None:
    """快速结构体检：每个文件花括号平衡（无需 node 的兜底）。"""
    for rel in _JS_FILES:
        p = STATIC_DIR / rel
        text = p.read_text(encoding="utf-8")
        opens = text.count("{")
        closes = text.count("}")
        assert opens == closes, f"{rel}: 花括号不平衡 (open={opens} close={closes})"