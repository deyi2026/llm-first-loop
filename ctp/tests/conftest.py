"""把 ctp/src 与测试目录追加到 sys.path，使 tests 可在未安装状态下直接跑（src 布局）。

测试目录入 path 是为了测试专用的辅助模块（如 conformance_stubs.py：一致性 runner 的读码器协议桩）。
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
