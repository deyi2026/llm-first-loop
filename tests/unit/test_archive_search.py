"""单元测试: 压缩档案 ArchiveStore 与统一检索 search_records（T22/T23）."""

from __future__ import annotations

from llm_loop.introspection.search import RecordSearcher
from llm_loop.memory.archive import ArchiveStore, extract_key_info
from llm_loop.memory.store import MemoryEntry, MemoryStore


def test_extract_key_info_paths():
    """关键信息提取: 路径/URL 作为关键路径."""
    facts, paths, summary = extract_key_info(
        "读取 /srv/data/notes.txt 成功，访问 https://example.com"
    )
    assert any("notes.txt" in p for p in paths)
    assert any("example.com" in p for p in paths)


def test_extract_key_info_facts():
    """关键事实: 含状态信号的行被提取."""
    facts, _, _ = extract_key_info("命令执行成功\n文件读取失败: not found\n普通行")
    assert any("成功" in f for f in facts)
    assert any("失败" in f for f in facts)


def test_archive_roundtrip(tmp_path):
    """另存 + 检索找回（信息零丢失）."""
    store = ArchiveStore(tmp_path)
    store.archive(
        "s1", role="user", source="user", content="用户要求处理 data/report.txt，包含重要数据"
    )
    store.archive(
        "s1",
        role="tool",
        source="tool",
        content="工具结果内容 ABC123",
        tool_name="read_file",
        tool_call_id="c1",
    )
    hits = store.search("s1", "report.txt")
    assert len(hits) == 1
    assert hits[0]["role"] == "user"
    # 原文完整保留
    assert store.search("s1", "重要数据")[0]["content_preview"]
    # 超长结果另存检索
    store.archive(
        "s1", role="tool", source="tool", content="大结果" * 100, tool_name="execute_command"
    )
    assert store.search("s1", "大结果", tool_name="execute_command")


def test_archive_stats(tmp_path):
    store = ArchiveStore(tmp_path)
    store.archive("s1", role="user", source="user", content="内容A" * 10)
    st = store.stats("s1")
    assert st["archived_count"] == 1
    assert st["archived_chars"] > 0
    assert store.stats("nonexistent")["archived_count"] == 0


def test_search_records_memory(tmp_path):
    """search_records kind=memory."""
    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢蓝色", keywords=["蓝色"]))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", memory_store=mem)
    hits = searcher.search(kind="memory", query="蓝色")
    assert len(hits) == 1
    assert hits[0]["kind"] == "memory"


def test_search_records_archive(tmp_path):
    """search_records kind=archive 与 search_archive 行为一致（统一入口）."""
    arch = ArchiveStore(tmp_path / "archives")
    arch.archive("s1", role="user", source="user", content="关键信息 KEYWORD_XYZ")
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", archive_store=arch)
    hits = searcher.search(kind="archive", query="KEYWORD_XYZ", session_id="s1")
    assert len(hits) == 1
    assert hits[0]["kind"] == "archive"


def test_search_records_invalid_kind(tmp_path):
    """kind 不合法 → ValueError."""
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    try:
        searcher.search(kind="bad_kind", query="x")
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass


def test_search_records_jsonl(tmp_path):
    """search_records 检索 JSONL 运行记录（可溯源）."""
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "exception_log.jsonl").write_text(
        '{"ts": "t1", "phase": "tool_execute", "error_type": "FileNotFoundError", "error_message": "no such file REPORT_X"}\n',
        encoding="utf-8",
    )
    searcher = RecordSearcher(audit_dir=audit)
    hits = searcher.search(kind="exception_log", query="REPORT_X")
    assert len(hits) == 1
    assert hits[0]["file"].endswith("exception_log.jsonl")


def test_search_records_no_hit(tmp_path):
    """无命中返回空列表（不伪造）."""
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    assert searcher.search(kind="all", query="不存在的东西") == []


def test_search_records_kind_all_allocates_evenly(tmp_path):
    """P1-4: kind=all 各 kind 均匀分配 limit（后序 kind 不被前序挤掉）."""
    audit = tmp_path / "audit"
    audit.mkdir()
    # 前序 kind（action_trace）大量命中，后序 kind（self_eval）少量命中
    (audit / "action_trace.jsonl").write_text(
        "".join(
            f'{{"ts": "t{i}", "phase": "action", "action_type": "llm", "detail": "含关键词X"}}\n'
            for i in range(20)
        ),
        encoding="utf-8",
    )
    (audit / "self_eval_log.jsonl").write_text(
        '{"ts": "t1", "id": "SE-1", "trigger": "manual", "note": "含关键词X评估"}\n',
        encoding="utf-8",
    )
    searcher = RecordSearcher(audit_dir=audit)
    hits = searcher.search(kind="all", query="关键词X", limit=10)
    # 后序 kind（self_eval）结果必须出现（修复前被 results[:limit] 挤掉）
    assert any(h["kind"] == "self_eval" for h in hits)
    assert len(hits) <= 10


def test_search_records_new_kinds(tmp_path):
    """P2-6: 配置变更/进程版本/飞书审计三类可检索."""
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "change_log.jsonl").write_text(
        '{"ts": "t1", "key": "HISTORY_MAX_CHARS", "before": "80000", "after": "100000", "note": "调大"}\n',
        encoding="utf-8",
    )
    (audit / "proc_versions.jsonl").write_text(
        '{"ts": "t1", "process": "feishu", "version": "abc123", "started_at": "t0", "git_hash": "h1"}\n',
        encoding="utf-8",
    )
    (audit / "feishu_audit.jsonl").write_text(
        '{"ts": "t1", "message_id": "om_1", "sender_id": "ou_1", "action": "text", "note": "收到消息", "text": "含关键词Y"}\n',
        encoding="utf-8",
    )
    searcher = RecordSearcher(audit_dir=audit)
    assert len(searcher.search(kind="change_log", query="HISTORY_MAX_CHARS")) == 1
    assert len(searcher.search(kind="proc_versions", query="feishu")) == 1
    assert len(searcher.search(kind="feishu_audit", query="关键词Y")) == 1
    # all 也覆盖新 kind
    all_hits = searcher.search(kind="all", query="", limit=50)
    kinds = {h["kind"] for h in all_hits}
    assert {"change_log", "proc_versions", "feishu_audit"} <= kinds


def test_archive_session_prefix_does_not_cross_match_or_delete_neighbor(tmp_path):
    """sid前缀相同时，检索/物理删除都只能命中精确sid段，不能碰邻居会话。"""
    store = ArchiveStore(tmp_path)
    store.archive("sess", role="user", source="user", content="ONLY-SHORT-ALPHA")
    store.archive("sess-long", role="user", source="user", content="ONLY-LONG-BETA")

    assert store.search("sess", "BETA") == []
    assert store.search("sess-long", "BETA")

    assert store.delete_session("sess") >= 1
    assert store.search("sess", "ALPHA") == []
    assert store.search("sess-long", "BETA")


def test_archive_numeric_suffix_session_id_does_not_alias_legacy_segment(tmp_path):
    """`sess-1.jsonl`不能同时被解释为sess的segment1与sess-1的主档案。"""
    store = ArchiveStore(tmp_path)
    store.archive("sess", role="user", source="user", content="SHORT-ALPHA")
    store.archive("sess-1", role="user", source="user", content="NUMERIC-BETA")

    assert store.search("sess", "BETA") == []
    assert store.search("sess-1", "BETA")

    store.delete_session("sess")
    assert store.search("sess-1", "BETA")


def test_legacy_numeric_suffix_neighbor_uses_known_session_evidence(tmp_path):
    """旧flat段无session_id时，外部已知session证据必须阻止`sess`吞掉真实`sess-1`。"""
    import json

    short = {
        "id": "legacy-short",
        "ts": "2026-08-20T00:00:00+00:00",
        "role": "user",
        "source": "legacy",
        "content": "LEGACY-SHORT-ALPHA",
        "summary": "",
        "chars": 18,
    }
    neighbor = {
        "id": "legacy-neighbor",
        "ts": "2026-08-20T00:00:01+00:00",
        "role": "user",
        "source": "legacy",
        "content": "LEGACY-NEIGHBOR-BETA",
        "summary": "",
        "chars": 20,
    }
    (tmp_path / "sess.jsonl").write_text(
        json.dumps(short, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    neighbor_path = tmp_path / "sess-1.jsonl"
    neighbor_path.write_text(
        json.dumps(neighbor, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    store = ArchiveStore(
        tmp_path,
        known_session_id_fn=lambda sid: sid == "sess-1",
    )

    assert store.search("sess", "BETA") == []
    hits = store.search("sess-1", "BETA")
    assert len(hits) == 1 and hits[0]["id"] == "legacy-neighbor"

    store.delete_session("sess")
    assert neighbor_path.exists()
    hits_after = store.search("sess-1", "BETA")
    assert len(hits_after) == 1 and hits_after[0]["id"] == "legacy-neighbor"
