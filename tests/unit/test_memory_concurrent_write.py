"""2026-08-20（d8a76517, 镜像）: MemoryStore 跨进程/线程并发写防护——写前合并磁盘最新态.

事故复现: 进程 A 加载 index → 进程 B 写入新条目 → 进程 A 再 save → A 的 stale
内存覆盖 B 的写入（MEM-20260820-bad62330 丢失）。修复: _save 写前 _merge_remote_changes
把磁盘独有条目并入内存, 同 id 以内存为准。
"""

from __future__ import annotations

import json
import threading

from llm_loop.memory.store import MemoryEntry, MemoryStore


def _mk_entry(content: str) -> MemoryEntry:
    return MemoryEntry(
        id="",
        type="fact",
        content=content,
        keywords=[content],  # 全 content 作关键词, 保证组内也唯一(避免弱匹配合并)
    )


def test_remote_write_not_lost_on_save(tmp_path):
    """模拟两进程共享目录: B 写入 → A 再 save → B 的条目不丢."""
    a = MemoryStore(tmp_path)
    b = MemoryStore(tmp_path)
    # 进程 B 写入
    b.save_entry(_mk_entry("B 的记忆内容"))
    assert len(b.all()) == 1
    # 进程 A（stale 内存）写入——修复前会覆盖 B 的条目
    a.save_entry(_mk_entry("A 的记忆内容"))
    ids = {e.content for e in a.all()}
    assert "B 的记忆内容" in ids, "A 的 save 覆盖了 B 的写入（并发写丢失）"
    assert "A 的记忆内容" in ids
    assert len(a.all()) == 2


def test_same_id_keeps_local_override(tmp_path):
    """同 id 条目: 本进程内存版优先（不重复合并旧版）."""
    a = MemoryStore(tmp_path)
    e = a.save_entry(_mk_entry("原始内容"))
    # 模拟磁盘被其他进程更新为同 id 新版
    disk = json.loads((tmp_path / "index.json").read_text())
    disk[0]["content"] = "磁盘新版"
    (tmp_path / "index.json").write_text(json.dumps(disk))
    # 本进程再次 save（内存仍是原始内容, 同 id 以内存为准）
    a.save_entry(_mk_entry("另一条"))
    out = json.loads((tmp_path / "index.json").read_text())
    contents = {x["content"] for x in out}
    assert "原始内容" in contents  # 本进程版保留
    assert "另一条" in contents
    # 同 id 不重复: 该 id 只出现一次
    ids = [x["id"] for x in out]
    assert len(ids) == len(set(ids)), "同 id 重复出现"


def test_thread_safety_concurrent_saves(tmp_path):
    """同进程多线程并发 save_entry 不丢条目（线程锁）."""
    store = MemoryStore(tmp_path)
    results: list[Exception | None] = []
    errors: list[Exception] = []

    def worker(n: int):
        try:
            for i in range(5):
                store.save_entry(_mk_entry(f"thread{n}-{i}"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发写异常: {errors}"
    assert len(store.all()) == 20  # 4 线程 × 5 条全部保留
