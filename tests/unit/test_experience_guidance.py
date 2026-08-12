"""EVO-d78b270c: M41 失败回执→经验驱动注入测试.

验证:
- 有经验库且命中 procedure 已验解法 → 注入 [经验参考] 段
- 有经验库未命中 → 默认模板（零回归）
- 无经验库（memory_store=None）→ 默认模板（零回归）
- procedure 无已验解法 → 不注入
- 检索异常 → fail-open 默认模板
- tool_result_to_message 带出 guidance_extra
"""
from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.registry import ToolRegistry, tool_result_to_message


def _fail_call():
    return ToolCall(id="c1", name="read_file", arguments={"path": "/nonexistent/x"})


class _FakeMemory:
    """极简 MemoryStore 桩（search 返回预设条目）. """

    def __init__(self, entries):
        self._entries = entries

    def search(self, keywords, top_k=5):
        return self._entries[:top_k]


def _proc(content, kws):
    from llm_loop.memory.store import MemoryEntry
    return MemoryEntry(
        id="exp1", type="procedure", content=content, keywords=kws, created_at="2026-08-12T00:00:00Z"
    )


def test_no_memory_store_default_template():
    """无经验库 → 默认模板（零回归）."""
    reg = ToolRegistry()  # memory_store=None
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert r.guidance_extra == ""  # 无经验注入
    msg = tool_result_to_message(r)
    assert "[经验参考]" not in msg.content
    assert "检查参数/路径" in msg.content  # 默认模板仍在


def test_hit_procedure_injects_solution():
    """命中 procedure 已验解法 → 注入 [经验参考] 段."""
    proc = _proc(
        "触发标签: [文件不存在]\n场景: 读文件失败\n已验解法: ①先确认路径②用 read_file 重试\n实证: 6/6\n反例: 盲猜路径",
        ["文件不存在", "read_file"],
    )
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /nonexistent/x", duration_ms=1.0)
    assert r.guidance_extra != ""
    assert "经验参考" in r.guidance_extra
    assert "先确认路径" in r.guidance_extra
    msg = tool_result_to_message(r)
    assert "[经验参考]" in msg.content
    assert "先确认路径" in msg.content


def test_no_hit_default_template():
    """经验库存在但未命中 → 默认模板（零回归）."""
    reg = ToolRegistry(memory_store=_FakeMemory([]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert r.guidance_extra == ""
    msg = tool_result_to_message(r)
    assert "[经验参考]" not in msg.content


def test_proc_without_solution_not_injected():
    """procedure 无已验解法 → 不注入."""
    proc = _proc("只是一条普通描述", ["文件不存在"])
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert r.guidance_extra == ""


def test_search_exception_fail_open():
    """检索异常 → fail-open 默认模板."""
    class _Boom:
        def search(self, keywords, top_k=5):
            raise RuntimeError("检索挂了")

    reg = ToolRegistry(memory_store=_Boom())
    r = reg._result(ToolResultStatus.ERROR, _fail_call(), "boom", duration_ms=1.0)
    assert r.guidance_extra == ""
    msg = tool_result_to_message(r)
    assert "[经验参考]" not in msg.content


def test_guidance_disabled_no_extra():
    """failure_guidance_enabled=False（子代理路径）→ 不带经验段."""
    proc = _proc(
        "触发标签: [文件不存在]\n已验解法: ①先确认路径\n实证: 6/6",
        ["文件不存在", "read_file"],
    )
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert r.guidance_extra != ""  # registry 注入仍发生（数据层）
    msg = tool_result_to_message(r, failure_guidance_enabled=False)
    assert "[经验参考]" not in msg.content  # 消息层关闭引导则不带出


def test_success_no_injection():
    """成功状态不注入经验."""
    reg = ToolRegistry(memory_store=_FakeMemory([_proc("触发标签: [文件]\n已验解法: x", ["read_file"])]))
    r = reg._result(ToolResultStatus.SUCCESS, _fail_call(), "正常内容", duration_ms=1.0)
    assert r.guidance_extra == ""
