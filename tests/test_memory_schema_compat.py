"""M1 schema bridge: MemoryEntry 必须兼容 main 3a95ed46 引入的 observation_history 持久化字段.

背景（2026-09-15 事故）: 旧 M1 reader + 新 schema 共享 index.json → MemoryEntry(**e)
遇未知字段 TypeError → _load() 误判 corruption → 内存索引清空。本测试锁定读写兼容
（仅持久化字段，不带 main 的 promotion/observation-fence 运行时语义）。
"""
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _entry(**extra):
    base = {"id": "MEM-TEST-0001", "type": "fact", "content": "hello"}
    base.update(extra)
    return base


def test_old_format_without_field_loads_with_default():
    e = MemoryEntry(**_entry())
    assert e.observation_history == []


def test_new_format_with_field_loads():
    oh = [{"disposition": "late_observation_not_promoted", "content": "x"}]
    e = MemoryEntry(**_entry(observation_history=oh))
    assert e.observation_history == oh


def test_nonempty_observation_history_roundtrip(tmp_path):
    oh = [{"disposition": "late_observation_not_promoted", "content": "old fact"}]
    store = MemoryStore(tmp_path)
    store.save_entry(MemoryEntry(**_entry(id="MEM-RT-1", observation_history=oh)))
    store2 = MemoryStore(tmp_path)  # 新实例=新进程语义，重新从磁盘加载
    got = [e for e in store2.all() if e.id == "MEM-RT-1"]
    assert len(got) == 1
    assert got[0].observation_history == oh


def test_cross_process_merge_preserves_disk_entry_with_field(tmp_path):
    # 进程A写入带字段条目 → 进程B写入另一条目（写前合并磁盘）→ 进程C读：
    # 磁盘上 A 的 observation_history 必须原样保留，不得被旧 reader 吞掉。
    oh = [{"disposition": "late_observation_not_promoted", "content": "m"}]
    MemoryStore(tmp_path).save_entry(
        MemoryEntry(**_entry(id="MEM-A", observation_history=oh))
    )
    s2 = MemoryStore(tmp_path)
    s2.save_entry(MemoryEntry(**_entry(id="MEM-B", content="another fact")))
    s3 = MemoryStore(tmp_path)
    a = [e for e in s3.all() if e.id == "MEM-A"]
    assert a and a[0].observation_history == oh
    assert {e.id for e in s3.all()} >= {"MEM-A", "MEM-B"}


# ── 第二层根治: _load 错误分类（schema mismatch ≠ corruption）──
import json

import pytest

from llm_loop.memory.store import MemorySchemaMismatch


def test_unknown_field_fail_closed_not_corrupt(tmp_path):
    # 新 schema 未知字段: 不当 corruption 处理——不备份、文件一字节不动、禁写并抛 MemorySchemaMismatch
    idx = tmp_path / "index.json"
    idx.write_text(
        json.dumps([{"id": "X1", "type": "fact", "content": "c",
                     "future_field": [{"a": 1}]}]),
        encoding="utf-8",
    )
    before = idx.read_bytes()
    store = MemoryStore(tmp_path)
    assert idx.read_bytes() == before                       # 原文件未动
    assert not (tmp_path / "index.corrupt.json").exists()   # 不误备份（不是损坏）
    assert store.all() == []                                # 读侧 fail-open(空)，已记 error 日志
    with pytest.raises(MemorySchemaMismatch):
        store.save_entry(MemoryEntry(id="X2", type="fact", content="never written"))
    assert idx.read_bytes() == before                       # 写被拒，文件仍原样


def test_broken_json_still_corruption_path(tmp_path):
    # JSON 语法破损: 保持原 corruption 路径（备份+空+fail-open 可继续写）
    idx = tmp_path / "index.json"
    idx.write_text("{ not json", encoding="utf-8")
    store = MemoryStore(tmp_path)
    assert (tmp_path / "index.corrupt.json").exists()
    assert store.all() == []
    store.save_entry(MemoryEntry(id="N1", type="fact", content="recovered"))
    assert {e.id for e in MemoryStore(tmp_path).all()} == {"N1"}


def test_runtime_disk_schema_upgrade_locks_old_writer(tmp_path):
    # 进程A(旧)已加载正常 index → 磁盘被新 schema 进程升级 → A 再写必须 fail-closed，
    # 不得用旧 reader 的内存态覆盖磁盘新 schema 数据
    MemoryStore(tmp_path).save_entry(MemoryEntry(id="A1", type="fact", content="a"))
    idx = tmp_path / "index.json"
    data = json.loads(idx.read_text(encoding="utf-8"))
    data[0]["future_field"] = [{"v": 2}]
    idx.write_text(json.dumps(data), encoding="utf-8")
    s_old = MemoryStore(tmp_path)  # 加载时还是旧 schema（无 future_field）→ 正常
    with pytest.raises(MemorySchemaMismatch):
        s_old.save_entry(MemoryEntry(id="A2", type="fact", content="must not overwrite"))
    data_after = json.loads(idx.read_text(encoding="utf-8"))
    assert data_after[0]["future_field"] == [{"v": 2}]      # 磁盘新 schema 未被旧进程破坏
    assert len(data_after) == 1                             # A2 未被写入
