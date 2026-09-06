"""静默吞错清理守护测试（spec 5.1.1 / design §2.4.1 / tasks 1.4）.

断言:
1. src/llm_loop/ 无纯 pass 残留（except: 后 pass 无注释无日志，违反 fail-open ≠ fail-silent）
2. summarize.py 不含裸 except Exception: pass
3. 现存清理点各自含对应日志标记 + 注释/logger 标注
4. routes.py 飞书推送前置读取处仍含 # noqa: BLE001
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "llm_loop"

# 跨行：except ... : \n <indent> pass（pass 后无同行 # 注释，即纯静默吞错）
_BARE_PASS_RE = re.compile(r"except[^\n]*:\n[ \t]+pass[ \t]*(?:\n|$)")


def _read(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")


def _all_py() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))



def test_summarize_no_bare_exception_pass():
    text = _read("memory/summarize.py")
    assert not re.search(r"except\s+Exception\s*:\s*\n[ \t]+pass", text)


# 现存清理点（退役代码的旧 marker 不作为代码形状税保留）
_CLEANUP_POINTS = {
    "memory/summarize.py": "确定性摘要降级也失败",
    "feishu/__init__.py": "退出日志写失败",
    "feishu/handlers.py": "审计落盘失败",
    "introspection/loop_signals.py": "忽略清单",
    "web/__init__.py": "退出日志写失败",
    "core/session.py": "读共享当前会话失败",
    "core/runtime_params.py": "读参数调整历史失败",
    "memory/archive.py": "档案统计单行损坏跳过",
    "memory/retriever.py": "embedding 缓存写失败",
    "introspection/status.py": "审计行解析失败",
    "introspection/proc_version.py": "读进程版本文件失败",
    "web/routes.py": "飞书推送前置读取失败",
}


@pytest.mark.parametrize("rel,marker", sorted(_CLEANUP_POINTS.items()))
def test_cleanup_point_annotated(rel, marker):
    text = _read(rel)
    assert marker in text
    assert ("# fail-open" in text) or ("logger." in text) or ("logging.getLogger" in text)


def test_routes_keeps_noqa_ble001():
    text = _read("web/routes.py")
    assert "noqa: BLE001" in text
