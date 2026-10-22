"""The gate is a page-filler filter, never a page-shortener.

Review P0 (2026-10-23): the first implementation capped the backfill at `max(strict, 5)`,
so a caller asking for 20 (the semantic leg calls with limit=max(limit*4,20)) could get 5
back and silently rewrite the RRF fusion downstream. The contract pinned here is:
returned length == min(limit, number of cards the query actually matched), whether those
cards cleared the gate or were re-admitted to fill the page.
"""

from __future__ import annotations

from llm_loop.methods.store import MethodStore


def _card(store: MethodStore, name: str, description: str) -> None:
    store.save_candidate(name=name, description=description, body=f"## Trigger\n{name}\n")


def test_backfill_fills_the_page_instead_of_returning_five(tmp_path):
    store = MethodStore(tmp_path)
    # 2 cards cover the whole query; 10 cards share only the ubiquitous first term.
    for i in range(10):
        _card(store, f"共享词卡{i:02d}", f"共享词 描述 {i:02d}")
    for i in range(2):
        _card(store, f"完整卡{i}", f"共享词 稀有一 稀有二 稀有{i}")
    hits = store.list("共享词 稀有一 稀有二", limit=20)
    assert len(hits) == 12, "every matched card must fit on the page when limit allows"


def test_broad_query_still_stops_at_limit(tmp_path):
    store = MethodStore(tmp_path)
    for i in range(12):
        _card(store, f"宽泛卡{i:02d}", f"宽泛 描述 {i:02d}")
    assert len(store.list("宽泛 卡", limit=5)) == 5


def test_empty_query_is_the_inventory_view(tmp_path):
    store = MethodStore(tmp_path)
    for i in range(3):
        _card(store, f"清单卡{i}", f"清单 描述 {i}")
    assert len(store.list("", limit=50)) == 3
    assert len(store.list("   ", limit=50)) == 3


def test_equal_score_ties_keep_id_descending(tmp_path):
    store = MethodStore(tmp_path)
    for i in range(6):
        _card(store, f"平手卡{i}", f"平手 描述 {i}")
    ids = [row["id"] for row in store.list("平手 卡", limit=6)]
    assert ids == sorted(ids, reverse=True)


def test_alias_with_separator_is_rejected(tmp_path):
    store = MethodStore(tmp_path)
    record = store.save_candidate(
        name="分隔符卡", description="分隔符卡的描述", body="## Trigger\n分隔符\n"
    )
    kept, dropped = store.annotate_aliases(
        record.method_ref, ["合法别名甲", "逗号,后截断", "井号#注释"], mode="merge"
    )
    assert list(kept.aliases) == ["合法别名甲"]
    assert {d["reason"] for d in dropped} == {"unsafe_chars"}
