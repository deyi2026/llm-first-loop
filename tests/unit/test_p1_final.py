"""T37 覆盖收尾: config P1 变量 / search all kind / registry 边界."""

from __future__ import annotations

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.introspection.search import RecordSearcher
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.store import MemoryEntry, MemoryStore
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.registry import ToolRegistry


def test_config_p1_defaults_and_env(monkeypatch):
    """P1 环境变量默认值与 env 覆盖（T36）."""
    from llm_loop.config import load_settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.delenv("DATA_DIR", raising=False)
    s = load_settings()
    # 默认值
    assert s.summary_mode == "off"
    assert s.embedding_provider == "none"
    assert s.extract_enabled is True
    assert s.validate_semantic is False
    # env 覆盖
    monkeypatch.setenv("SUMMARY_MODE", "async")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("VALIDATE_SEMANTIC", "1")
    monkeypatch.setenv("EXTRACT_ENABLED", "0")
    s2 = load_settings()
    assert s2.summary_mode == "async"
    assert s2.embedding_provider == "hash"
    assert s2.validate_semantic is True
    assert s2.extract_enabled is False
    # 状态摘要不含密钥
    st = s2.to_status_dict()
    assert "embedding_api_key" not in st
    assert "llm_api_key" not in st
    assert st["embedding_provider"] == "hash"


def test_search_records_all_kinds(tmp_path):
    """search_records kind=all: JSONL + 记忆 + 档案 全检索."""
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "action_trace.jsonl").write_text(
        '{"ts": "t1", "phase": "tool", "action_type": "call", "detail": "read_file XFILE"}\n',
        encoding="utf-8",
    )
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="XFILE 相关内容", keywords=["XFILE"]))
    arch = ArchiveStore(tmp_path / "archives")
    arch.archive("s1", role="user", source="user", content="XFILE 档案内容")
    searcher = RecordSearcher(audit_dir=audit, memory_store=mem, archive_store=arch)
    hits = searcher.search(kind="all", query="XFILE", session_id="s1")
    kinds = {h["kind"] for h in hits}
    assert "action_trace" in kinds
    assert "memory" in kinds
    assert "archive" in kinds


def test_registry_param_error_and_unknown_tool(tmp_path):
    """registry: 参数错误 + 未知工具 + 空 id（边界覆盖）."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    # 缺必填参数
    r = reg.execute(ToolCall(id="c1", name="read_file", arguments={}))
    assert r.status == ToolResultStatus.FAILURE
    # 空 id
    r2 = reg.execute(ToolCall(id="", name="read_file", arguments={"path": "/x"}))
    assert r2.status == ToolResultStatus.FAILURE
    assert "tool_call_id" in r2.content
    # 未知工具
    r3 = reg.execute(ToolCall(id="c3", name="nope_tool", arguments={}))
    assert r3.status == ToolResultStatus.FAILURE
    assert "不存在" in r3.content


def test_archive_search_empty_query(tmp_path):
    """archive.search 空 query → 返回全部（候选生成用）."""
    arch = ArchiveStore(tmp_path / "archives")
    arch.archive("s1", role="user", source="user", content="第一条")
    arch.archive("s1", role="tool", source="tool", content="第二条", tool_name="x")
    hits = arch.search("s1", "", limit=10)
    assert len(hits) == 2
    # 按 role 过滤
    tool_hits = arch.search("s1", "", limit=10, role="tool")
    assert len(tool_hits) == 1
