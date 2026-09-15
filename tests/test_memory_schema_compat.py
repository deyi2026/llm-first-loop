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
