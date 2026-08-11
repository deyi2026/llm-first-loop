"""工具输出分层注入测试（EVO-20260811-22a7d3e1）.

> summary_threshold → 默认注入首/尾摘要（原文另存可检索）
≤ summary_threshold → 原文注入
> max_output_chars   → 既有硬截断仍生效
"""
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry


class _BigTool:
    name = "big_out"
    description = "返回大输出"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, size: int):
        self._size = size

    def execute(self, **kwargs):
        # 首部/尾部打上可辨识标记
        body = "x" * max(0, self._size - 20)
        return f"HEAD_MARK:{body}:TAIL_MARK"


class _ArchiveFake:
    def __init__(self):
        self.items = []

    def archive(self, session_id, **kw):
        self.items.append(kw)
        from types import SimpleNamespace
        return SimpleNamespace(id="ARC-x", to_dict=lambda: {})


def _call(name: str) -> ToolCall:
    return ToolCall(id=f"c1-{name}", name=name, arguments={})


def test_below_threshold_full_injected():
    reg = ToolRegistry(summary_threshold=5000)
    reg.register(_BigTool(size=200))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "HEAD_MARK" in r.content and "TAIL_MARK" in r.content
    assert "输出摘要" not in r.content


def test_above_threshold_summary_injected_and_archived():
    arc = _ArchiveFake()
    reg = ToolRegistry(summary_threshold=500, archive_store=arc)
    reg.set_session_id("s1")
    reg.register(_BigTool(size=2000))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS  # 信息零丢失，状态如实
    assert "输出摘要" in r.content
    assert "HEAD_MARK" in r.content and "TAIL_MARK" in r.content  # 首/尾都在
    assert "search_archive" in r.content
    assert len(arc.items) == 1 and len(arc.items[0]["content"]) == 2000  # 原文完整另存


def test_above_hard_limit_still_truncates():
    arc = _ArchiveFake()
    reg = ToolRegistry(summary_threshold=500, max_output_chars=1000, archive_store=arc)
    reg.set_session_id("s1")
    reg.register(_BigTool(size=5000))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "输出摘要" in r.content  # 先分层摘要
    assert len(arc.items) == 1  # 全文另存（5000 字符完整）
    # 摘要内容本身不超过硬上限
    assert len(r.content) <= 1000 + 200


def test_summary_no_archive_store_fail_open():
    # 无 archive_store → 摘要注入仍工作，只是无法另存（不抛异常）
    reg = ToolRegistry(summary_threshold=100)
    reg.register(_BigTool(size=500))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "输出摘要" in r.content
