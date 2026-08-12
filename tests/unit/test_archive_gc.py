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
