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
    # 摘要内容本身不超过硬上限（截断段 + 截断标注 + 指引；指引长度随版本演进，用 len() 动态容差）
    assert len(r.content) <= 1000 + len(ToolRegistry._DISTILL_GUIDANCE) + 200


def test_summary_no_archive_store_fail_open():
    # 无 archive_store → 摘要注入仍工作，只是无法另存（不抛异常）
    reg = ToolRegistry(summary_threshold=100)
    reg.register(_BigTool(size=500))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "输出摘要" in r.content


class _RichTool:
    """输出含路径/URL/动作信号词的大结果（用于 extract_key_info 摘要优先路径）."""

    name = "rich_out"
    description = "返回含关键信息的大输出"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return (
            "/srv/data/notes.txt 读取成功\n"
            "任务完成，结果返回正常\n"
            "访问 https://example.com/api/v1 返回 200\n"
            + "x" * 3000
            + "\n尾部标记:TAIL_MARK"
        )


def test_summary_extract_key_info_priority():
    """EVO-20260823: 摘要方式升级——有路径/URL/信号词时 extract_key_info 摘要优先于首尾截断.

    关键事实+关键路径内联（前缀稳定、体积小），原文仍完整另存（信息零丢失）。
    """
    arc = _ArchiveFake()
    reg = ToolRegistry(summary_threshold=500, archive_store=arc)
    reg.set_session_id("s1")
    reg.register(_RichTool())
    r = reg.execute(_call("rich_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "关键事实" in r.content
    assert "关键路径" in r.content
    assert "notes.txt" in r.content and "example.com" in r.content
    assert "search_archive" in r.content  # 检索指引保留
    assert len(arc.items) == 1  # 原文完整另存（信息零丢失）


def test_summary_extract_fallback_head_tail():
    """EVO-20260823: 无路径/URL/信号词时回退首尾截断兜底（行为与旧版一致）."""
    arc = _ArchiveFake()
    reg = ToolRegistry(summary_threshold=500, archive_store=arc)
    reg.set_session_id("s1")
    reg.register(_BigTool(size=2000))
    r = reg.execute(_call("big_out"))
    assert r.status == ToolResultStatus.SUCCESS
    assert "关键事实" not in r.content  # 无提取内容 → 走首尾兜底
    assert "HEAD_MARK" in r.content and "TAIL_MARK" in r.content
    assert len(arc.items) == 1
