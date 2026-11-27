"""把 ctp/src 与测试目录追加到 sys.path，使 tests 可在未安装状态下直接跑（src 布局）。

测试目录入 path 是为了测试专用的辅助模块（如 conformance_stubs.py：一致性 runner 的读码器协议桩）。

取舍（仅测试作用域）：一律 append 而不 insert——标准库、第三方包与 ctp/src 都排在前面，这里的目录只在
前面都找不到同名模块时才会被命中；两个辅助模块名带用途前缀（conformance_stubs、reader_testkit），
不与标准库 / 第三方包同名。不把 ctp/ 本身放进 path：那会引入一个顶层名 tests，可能遮蔽仓库自身的 tests。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.append(str(_TESTS))
