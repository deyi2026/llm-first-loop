"""单元测试: 声明-回执校验 + 记忆（T18 / FR-FBK / FR-MEM）."""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.feedback.validator import DeclarationValidator
from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries
from llm_loop.memory.retrieve import build_memory_messages, extract_keywords
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _tool_msg(content: str, status=ToolResultStatus.SUCCESS) -> Message:
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id="c1",
        status=status,
        tool_name="read_file",
    )


def test_validator_consistent():
    """FR-FBK-01: 声明与回执一致 → consistent."""
    v = DeclarationValidator()
    result = v.check("我已读取文件 data/notes.txt 并总结", [_tool_msg("读取 data/notes.txt 成功")])
    assert result.consistent


def test_validator_discrepancy():
    """声明"已写入"但无对应回执 → 不一致 + 差异说明."""
    v = DeclarationValidator()
    result = v.check("我已写入文件 output.txt", [_tool_msg("读取 data/notes.txt 成功")])
    assert not result.consistent
    assert result.discrepancies


def test_validator_no_declaration():
    """无完成声明 → 一致."""
    v = DeclarationValidator()
    result = v.check("文件内容是 hello", [_tool_msg("读取 data/notes.txt 成功")])
    assert result.consistent


def test_discrepancy_feedback():
    from llm_loop.feedback.validator import DeclarationCheckResult, build_discrepancy_feedback

    r = DeclarationCheckResult(
        consistent=False,
        declarations=["我已写入文件 output.txt"],
        discrepancies=["声明: 我已写入文件 output.txt — 但本轮工具回执中未见对应成功记录"],
    )
    text = build_discrepancy_feedback(r)
    assert "不符" in text
    assert "output.txt" in text


# ── 记忆 ──
def test_extract_memory_blocks():
    answer = '我记住了。\n[[memory]] {"type": "fact", "content": "用户喜欢数字 7", "keywords": ["数字"]} [[/memory]]'
    blocks = extract_memory_blocks(answer)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "用户喜欢数字 7"


def test_extract_memory_blocks_invalid():
    answer = "[[memory]] {bad json [[/memory]]"
    blocks = extract_memory_blocks(answer)
    assert "_parse_error" in blocks[0]


def test_memory_blocks_to_entries(tmp_path):
    store = MemoryStore(tmp_path)
    entries, failures = memory_blocks_to_entries(
        [{"type": "fact", "content": "记住这件事", "keywords": ["事"]}],
        session_id="s1",
        message_id="m1",
    )
    assert len(entries) == 1
    assert failures == []
    saved = store.save_entry(entries[0])
    assert saved.id.startswith("MEM-")
    assert store.count() == 1


def test_memory_search(tmp_path):
    store = MemoryStore(tmp_path)
    e = MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["颜色"])
    store.save_entry(e)
    hits = store.search(["蓝色"], top_k=5)
    assert len(hits) == 1
    hits2 = store.search(["红色"], top_k=5)
    assert hits2 == []


def test_retrieve_keywords():
    kws = extract_keywords("请记住 用户 喜欢 蓝色 这个 颜色", limit=12)
    assert "蓝色" in kws
    assert "的" not in kws  # 停用词过滤


def test_build_memory_messages(tmp_path):
    store = MemoryStore(tmp_path)
    e = MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"])
    store.save_entry(e)
    msgs = build_memory_messages("帮我记住蓝色", store, top_k=5)
    assert len(msgs) == 1
    assert msgs[0].source == MessageSource.MEMORY
    assert "蓝色" in msgs[0].content
