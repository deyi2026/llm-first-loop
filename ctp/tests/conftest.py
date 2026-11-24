"""把 ctp/src 追加到 sys.path，使 tests 可在未安装状态下直接跑（src 布局，只有 ctp_contract 可导入）。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))
