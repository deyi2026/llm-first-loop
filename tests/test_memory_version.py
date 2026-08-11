"""记忆版本化与去重测试（EVO-20260811-cbd6c52a）."""
from pathlib import Path

from llm_loop.memory.store import MemoryEntry, MemoryStore


def _mk_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


def test_same_fact_fingerprint_overwrite(tmp_path):
    store = _mk_store(tmp_path)
    e1 = store.save_entry(MemoryEntry(id="", type="fact", content="部署用 systemd", keywords=["部署"]))
    e2 = store.save_entry(MemoryEntry(id="", type="fact", content="部署用 systemd", keywords=["部署"]))
    assert e2.id == e1.id  # 同事实 → 覆盖不新增
    assert e2.version == 2
    assert store.count() == 1
    assert len(e2.version_history) == 1
    assert e2.version_history[0]["content"] == "部署用 systemd"


def test_keyword_fact_update(tmp_path):
    store = _mk_store(tmp_path)
    e1 = store.save_entry(MemoryEntry(id="", type="decision", content="旧决策A", keywords=["决策"]))
    e2 = store.save_entry(MemoryEntry(id="", type="decision", content="新决策A2", keywords=["决策"]))
    assert e2.id == e1.id and e2.version == 2
    assert e2.content == "新决策A2"
    assert e2.updated_at >= e2.created_at


def test_new_fact_appends(tmp_path):
    store = _mk_store(tmp_path)
    store.save_entry(MemoryEntry(id="", type="fact", content="事实X", keywords=["x"]))
    store.save_entry(MemoryEntry(id="", type="fact", content="事实Y", keywords=["y"]))
    assert store.count() == 2


def test_backward_compat_old_data(tmp_path):
    store = _mk_store(tmp_path)
    store._entries = [
        MemoryEntry(id="MEM-OLD", type="fact", content="旧", created_at="2026-01-01T00:00:00+00:00")
    ]
    store._save()
    store2 = MemoryStore(tmp_path)
    e = store2.all()[0]
    assert e.version == 1 and e.version_history == [] and e.updated_at == ""


def test_search_freshness_after_update(tmp_path):
    store = _mk_store(tmp_path)
    old = MemoryEntry(id="M1", type="fact", content="主题A 版本1", keywords=["主题"], created_at="2026-01-01T00:00:00+00:00")
    store._entries = [old]
    store.save_entry(MemoryEntry(id="", type="fact", content="主题A 版本2", keywords=["主题"]))
    hits = store.search(["主题"], top_k=5)
    assert len(hits) == 1  # 同事实更新不产生第二份
    assert "版本2" in hits[0].content
