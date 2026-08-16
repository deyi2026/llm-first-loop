"""EVO-20260816-fcdbe2e9: memory 命中计数事实源（升格判据量化）.

核心语义：
- inject_count 只计"实际注入上下文"（build_memory_messages 最终 top_k），
  与 access_count（search 检索命中，含未进 top_k 的噪音）区分；
- 计数内存态更新，flush 后持久；旧 JSON 无新字段 → 加载默认 0（向后兼容）；
- architecture_status.memory.top_injected 为升格判断量化事实源。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.memory.retrieve import build_memory_messages
from llm_loop.memory.store import MemoryEntry, MemoryStore


def _entry(content: str, keywords: list[str] | None = None) -> MemoryEntry:
    return MemoryEntry(id="", type="fact", content=content, keywords=keywords or [])


def _store(tmp_path: Path, entries: list[MemoryEntry]) -> MemoryStore:
    store = MemoryStore(tmp_path / "mem")
    for e in entries:
        store.save_entry(e)
    return store


class TestMarkInjected:
    def test_inject_count_increment(self, tmp_path):
        store = _store(tmp_path, [_entry("长回答先写文件再发摘要", ["长回答", "写文件"])])
        hits = store.search(["长回答"], top_k=5)
        assert hits[0].inject_count == 0  # 检索命中不计 inject
        store.mark_injected(hits)
        assert hits[0].inject_count == 1
        assert hits[0].last_inject_at  # 时间戳已刷新
        store.mark_injected(hits)
        assert hits[0].inject_count == 2

    def test_empty_noop(self, tmp_path):
        store = _store(tmp_path, [_entry("x")])
        store.mark_injected([])  # 空列表幂等不抛

    def test_persist_after_flush(self, tmp_path):
        store = _store(tmp_path, [_entry("技巧A", ["技巧"])])
        store.mark_injected(store.search(["技巧"], top_k=5))
        store.mark_injected(store.search(["技巧"], top_k=5))
        store.mark_injected(store.search(["技巧"], top_k=5))
        store.flush()
        # 重新加载 → 计数持久
        store2 = MemoryStore(tmp_path / "mem")
        assert store2.all()[0].inject_count == 3

    def test_backward_compat_old_json(self, tmp_path):
        """旧 index.json（无 inject_count/last_inject_at）→ 加载默认 0，不报错."""
        d = tmp_path / "mem"
        d.mkdir(parents=True)
        old = {
            "id": "e1", "type": "fact", "content": "旧条目", "keywords": ["旧"],
            "source_session_id": "", "source_message_id": "", "created_at": "",
        }
        (d / "index.json").write_text(json.dumps([old]), encoding="utf-8")
        store = MemoryStore(d)
        e = store.all()[0]
        assert e.inject_count == 0
        assert e.last_inject_at == ""


class TestBuildMemoryMessagesCounting:
    def test_only_injected_counted_not_search_noise(self, tmp_path):
        """top_k 收窄时：只有进入注入消息的条目计数，被截掉的检索命中不计."""
        # 注：条目内容/关键词须充分相异，避免 save_entry 同事实合并（版本化去重）
        entries = [
            _entry("alpha 长回答", ["alpha"]),
            _entry("beta 技巧", ["beta"]),
            _entry("gamma 回答", ["gamma"]),
            _entry("delta 长回", ["delta"]),
        ]
        store = _store(tmp_path, entries)
        assert store.count() == 4  # 确认无同事实合并
        msgs = build_memory_messages("长回答 技巧", store, top_k=2)
        assert len(msgs) == 1
        injected = [e for e in store.all() if e.inject_count > 0]
        assert len(injected) == 2  # 仅 top_k=2 被计数（其余 search 命中未注入不计）

    def test_semantic_path_counts_final_entries(self, tmp_path):
        """语义检索路径：计数作用于最终 entries（语义结果），非关键词中间结果."""
        store = _store(tmp_path, [_entry("语义相关记忆", ["语义"])])

        class _FakeSemantic:
            def semantic_available(self):
                return True

            def search(self, text, *, top_k, scope, memory, keyword_results):
                from llm_loop.memory.retriever import SearchResult
                eid = store.all()[0].id
                return SearchResult(entries=[{"kind": "memory", "id": eid}], mode="semantic")

        msgs = build_memory_messages("语义", store, top_k=5, semantic_retriever=_FakeSemantic())
        assert len(msgs) == 1
        assert store.all()[0].inject_count == 1

    def test_no_hit_no_count(self, tmp_path):
        store = _store(tmp_path, [_entry("无关记忆", ["无关"])])
        msgs = build_memory_messages("完全不相关的查询词", store, top_k=5)
        assert msgs == []
        assert store.all()[0].inject_count == 0


class TestTopInjected:
    def test_sorted_desc_with_fields(self, tmp_path):
        store = _store(tmp_path, [
            _entry("技巧低频", ["低频"]),
            _entry("技巧高频", ["高频"]),
        ])
        for _ in range(3):
            store.mark_injected(store.search(["高频"], top_k=5))
        store.mark_injected(store.search(["低频"], top_k=5))
        top = store.top_injected(limit=5)
        assert len(top) == 2
        assert top[0]["content"] == "技巧高频" and top[0]["inject_count"] == 3
        assert top[1]["inject_count"] == 1
        assert {"id", "type", "inject_count", "last_inject_at", "content"} <= set(top[0])

    def test_empty_when_no_injection(self, tmp_path):
        store = _store(tmp_path, [_entry("只检索未注入", ["检索"])])
        store.search(["检索"], top_k=5)  # access_count+1 但 inject_count=0
        assert store.top_injected() == []  # 如实空列表（升格判据零命中）
