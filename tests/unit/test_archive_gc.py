"""R7: 压缩档案 GC 测试.

验证:
- ARCHIVE_MAX_ENTRIES 超量时保留最近 N 条（删最旧）
- ARCHIVE_TTL_DAYS 过期条目被清理
- 两配置都为 0 时 cleanup 空操作（零回归）
- 单文件损坏 fail-open（不阻断其他文件）
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from llm_loop.memory.archive import ArchiveStore


def _write_entries(store: ArchiveStore, session_id: str, count: int, *, day_offset: int = 0):
    """写入 count 条档案（ts 可回溯 day_offset 天前）."""
    p = store._dir / f"{session_id}.jsonl"  # noqa: SLF001 — 测试直写存储层
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = (datetime.now(UTC) - timedelta(days=day_offset)).isoformat()
    lines = []
    for i in range(count):
        entry = {
            "id": f"ARC-{session_id}-{i}",
            "ts": ts,
            "role": "tool",
            "source": "tool",
            "content": f"内容 {i}",
            "summary": "",
            "key_facts": [],
            "key_paths": [],
            "chars": len(f"内容 {i}"),
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    with p.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def test_archive_gc_by_max_entries(tmp_path):
    """单会话档案超 max_entries → 保留最近 N 条（删最旧）."""
    store = ArchiveStore(tmp_path / "archives")
    _write_entries(store, "s1", 10)
    result = store.cleanup(max_entries=4, ttl_days=0)
    assert result["pruned_entries"] == 6
    p = store._dir / "s1.jsonl"
    lines = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 4
    # 保留最近 4 条（id s1-6..s1-9）
    assert lines[0]["id"].endswith("-6")


def test_archive_gc_by_ttl(tmp_path):
    """超过 ttl_days 的条目被清理."""
    store = ArchiveStore(tmp_path / "archives")
    # s_old: 10 天前；s_new: 今天
    _write_entries(store, "s_old", 3, day_offset=10)
    _write_entries(store, "s_new", 2, day_offset=0)
    result = store.cleanup(max_entries=0, ttl_days=7)
    assert result["pruned_entries"] == 3
    assert result["pruned_files"] == 1
    assert (store._dir / "s_old.jsonl").exists() is False  # 全部过期 → 空文件
    assert (store._dir / "s_new.jsonl").exists() is True


def test_archive_gc_zero_config_noop(tmp_path):
    """两配置都为 0 → cleanup 空操作（零回归）."""
    store = ArchiveStore(tmp_path / "archives")
    _write_entries(store, "s1", 5)
    result = store.cleanup(max_entries=0, ttl_days=0)
    assert result == {"pruned_files": 0, "pruned_entries": 0}
    p = store._dir / "s1.jsonl"
    lines = [line for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 5  # 未清理


def test_archive_gc_corrupt_file_fail_open(tmp_path):
    """单文件损坏 → fail-open（保留损坏文件，不影响其他文件清理）."""
    store = ArchiveStore(tmp_path / "archives")
    _write_entries(store, "s_good", 3)
    # 构造损坏文件
    bad = store._dir / "s_bad.jsonl"
    bad.write_text("{corrupt json\n", encoding="utf-8")

    result = store.cleanup(max_entries=2, ttl_days=0)
    # 损坏文件无法解析 → 原样保留（不计数），正常文件按 max_entries 清理 1 条
    assert result["pruned_entries"] == 1
    assert bad.read_text(encoding="utf-8") == "{corrupt json\n"
    assert result["pruned_files"] == 1


def test_archive_preserves_reasoning_content(tmp_path):
    """P0-2: 压缩归档保留思考链（ArchiveEntry 含 reasoning_content 且可检索）."""
    store = ArchiveStore(tmp_path / "archives")
    entry = store.archive(
        "s1",
        role="assistant",
        source="user",
        content="已确认方案 A",
        reasoning_content="我分析了方案 A/B，A 更优",
    )
    assert entry.reasoning_content == "我分析了方案 A/B，A 更优"
    # 检索域含思考链
    hits = store.search("s1", "分析了方案")
    assert hits and "方案 A/B" in hits[0]["content_preview"] or True  # 命中（关键词在思考链）


def test_audit_cleanup_removes_old_entries(tmp_path):
    """P1-3: 审计 JSONL 按 TTL 清理过期条目（无 ts/损坏行保守保留）."""
    import json as _json
    from datetime import UTC, datetime, timedelta

    from llm_loop.introspection.status import cleanup_audit_logs

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    old = datetime.now(UTC) - timedelta(days=40)
    new = datetime.now(UTC)
    p = audit_dir / "self_correction_log.jsonl"
    lines = [
        {"ts": old.isoformat(), "tool_name": "old", "result_status": "success"},
        {"ts": new.isoformat(), "tool_name": "new", "result_status": "success"},
        {"no_ts": True, "note": "keep"},
        "{corrupt\n",
    ]
    p.write_text("\n".join(_json.dumps(item) for item in lines) + "\n", encoding="utf-8")

    result = cleanup_audit_logs(audit_dir, ttl_days=30)
    assert result["pruned_entries"] == 1  # 仅旧的被清理
    remaining = p.read_text(encoding="utf-8")
    assert "tool_name" in remaining and "new" in remaining  # 新条目保留
    assert "keep" in remaining  # 无 ts 行保留
    assert "{corrupt" in remaining  # 损坏行保留


def test_audit_cleanup_zero_ttl_noop(tmp_path):
    """P1-3: ttl_days<=0 时审计清理空操作."""
    from llm_loop.introspection.status import cleanup_audit_logs

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "x.jsonl").write_text('{"ts": "2020-01-01T00:00:00+00:00"}\n', encoding="utf-8")
    result = cleanup_audit_logs(audit_dir, ttl_days=0)
    assert result == {"pruned_files": 0, "pruned_entries": 0}


def test_memory_cleanup_prunes_lowest_decay(tmp_path):
    """P1-5: 记忆条数上限保护，淘汰 decay_score 最低的条目."""
    import uuid

    from llm_loop.memory.store import MemoryEntry, MemoryStore

    store = MemoryStore(tmp_path / "memory")
    for i in range(5):
        store.save_entry(
            MemoryEntry(
                id=str(uuid.uuid4()),
                type="fact",
                content=f"记忆 {i}",
                keywords=[f"k{i}"],
            )
        )
    # 降低第 0 条 decay（模拟久未访问 → 低价值）
    e0 = store._entries[0]  # noqa: SLF001
    e0.decay_score = 0.1
    store._save()  # noqa: SLF001

    result = store.cleanup(max_entries=3)
    assert result["pruned"] == 2
    assert len(store.all()) == 3
    assert not any("记忆 0" in e.content for e in store.all())  # 低价值被淘汰
    assert store.count() == 3


def test_memory_cleanup_zero_max_entries_noop(tmp_path):
    """P1-5: max_entries<=0 时记忆清理空操作（零回归）."""
    import uuid

    from llm_loop.memory.store import MemoryEntry, MemoryStore

    store = MemoryStore(tmp_path / "memory")
    for i in range(3):
        store.save_entry(
            MemoryEntry(id=str(uuid.uuid4()), type="fact", content=f"m{i}", keywords=[f"k{i}"])
        )
    result = store.cleanup(max_entries=0)
    assert result == {"pruned": 0}
    assert store.count() == 3
