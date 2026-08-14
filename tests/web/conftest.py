"""Web 测试共享辅助（T1 模块化拆分后 app.js 函数分散至 modules/*.js）。"""

from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "web" / "static"

_JS_FILES = [
    "modules/state.js",
    "modules/markdown-math.js",
    "modules/tool-render.js",
    "modules/message-render.js",
    "modules/stream-chat.js",
    "modules/app-core.js",
    "modules/responsive.js",
    "modules/session-list.js",
    "modules/command-upload-model.js",
    "app.js",
]


def read_all_js() -> str:
    """读取所有 JS 文件合并内容（T1 拆分后函数分散在各模块中，测试断言在合并内容中查找）。"""
    parts = []
    for f in _JS_FILES:
        p = STATIC_DIR / f
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.fixture(scope="module")
def app_js_src() -> str:
    """共享 fixture：读取所有 JS 文件合并内容。"""
    return read_all_js()
