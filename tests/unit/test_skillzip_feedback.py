"""SkillZip 借鉴落地测试: 执行感知反馈环 + 渐进水合展示.

验证:
- 点1: 命中 procedure 记录 guidance_used_at；risk>=2 时附带风险提示
- 点2: search_records 对 procedure 渐进水合返回已验解法段
"""
from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.introspection.search import _memory_progressive_summary
from llm_loop.memory.store import MemoryEntry
from llm_loop.tools.registry import ToolRegistry


def _proc(content, risk=0, used_at=""):
    return MemoryEntry(
        id="exp_proc", type="procedure", content=content, keywords=["已验解法", "测试"],
        created_at="2026-08-12T00:00:00Z", guidance_risk=risk, guidance_used_at=used_at,
    )


class _FakeMemory:
    def __init__(self, entries):
        self._entries = entries

    def search(self, keywords, top_k=5):
        return self._entries[:top_k]


def _fail_call():
    return ToolCall(id="c1", name="read_file", arguments={"path": "/nonexistent/x"})


def test_guidance_records_used_at():
    """命中后记录 guidance_used_at（执行感知）."""
    proc = _proc("触发标签: [测试]\n已验解法: ①先确认路径②重试\n实证: 6/6")
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert r.guidance_extra != ""
    assert proc.guidance_used_at != ""  # 记录使用时间
    assert "[经验参考]" in r.guidance_extra


def test_guidance_risk_prompt():
    """risk>=2 → 附带风险提示（执行感知反馈环标记）."""
    proc = _proc("触发标签: [测试]\n已验解法: ①先确认路径\n实证: 6/6", risk=3)
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert "[经验风险]" in r.guidance_extra
    assert "谨慎参考" in r.guidance_extra


def test_guidance_low_risk_no_prompt():
    """risk<2 → 无风险提示."""
    proc = _proc("触发标签: [测试]\n已验解法: ①先确认路径\n实证: 6/6", risk=1)
    reg = ToolRegistry(memory_store=_FakeMemory([proc]))
    r = reg._result(ToolResultStatus.FAILURE, _fail_call(), "[文件不存在] /x", duration_ms=1.0)
    assert "[经验风险]" not in r.guidance_extra


def test_progressive_summary_procedure():
    """procedure 渐进水合: 返回已验解法段（契约级）而非整条."""
    proc = _proc("触发标签: [测试]\n场景: 读文件失败\n已验解法: ①先确认路径②用 read_file 重试\n实证: 6/6\n反例: 盲猜")
    summary = _memory_progressive_summary(proc)
    assert "[已验解法]" in summary
    assert "先确认路径" in summary
    assert "触发标签" not in summary  # 不返回整条前300字


def test_progressive_summary_non_procedure_fallback():
    """非 procedure 回退整条前 300 字（零回归）."""
    fact = MemoryEntry(id="f1", type="fact", content="这是一条普通事实陈述" * 30, keywords=[], created_at="2026-08-12T00:00:00Z")
    summary = _memory_progressive_summary(fact)
    assert "[已验解法]" not in summary
    assert "普通事实" in summary


def test_progressive_summary_proc_no_solution():
    """procedure 无已验解法 → 回退整条."""
    proc = _proc("只是一条描述")
    summary = _memory_progressive_summary(proc)
    assert "[已验解法]" not in summary
    assert "描述" in summary
