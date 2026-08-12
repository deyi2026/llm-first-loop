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


def test_shared_generic_keyword_no_overwrite(tmp_path):
    """修复(2026-08-13): 共享泛用词（adjust_strategy）不触发同事实覆盖.

    借鉴 playbook 资产化时实证: 动作链条目与必调整场景条目共享 keyword
    'adjust_strategy'，原交集>=1 弱匹配误判同主题并覆盖（version+1 合并）。
    """
    store = _mk_store(tmp_path)
    e1 = store.save_entry(MemoryEntry(
        id="", type="procedure",
        content="【触发标签】自查后/动作链。场景: 调用架构自查后。已验解法: adjust_strategy 落地。",
        keywords=["动作链", "自查后", "adjust_strategy"],
    ))
    e2 = store.save_entry(MemoryEntry(
        id="", type="procedure",
        content="【触发标签】必调整场景/信号规模。场景: 调整策略参数。已验解法: 信号 2 条 FAILURE 基线。",
        keywords=["必调整场景", "信号规模", "adjust_strategy"],
    ))
    assert e1.id != e2.id  # 各自独立，不覆盖
    assert e2.version == 1
    hits = store.search(["动作链"], top_k=5)
    assert any("动作链" in h.keywords[0] for h in hits)  # 动作链条目仍在
