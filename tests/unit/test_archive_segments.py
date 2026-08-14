"""T3b(2026-08-14) 压缩档案分片测试（零真实数据，tmp_path 隔离）.

覆盖: 段枚举排序 / 超阈值开新段 / 跨段检索（最近段优先）/ 旧单文件兼容 /
get_by_tool_call_id 跨段 / stats 跨段累加 / update_summary 跨段定位 /
cleanup 跨段全局保留最近 N 条 + ttl / 损坏段 fail-open。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.memory.archive import ArchiveStore

_SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0000"


def _mk(store: ArchiveStore, session_id: str, content: str, role: str = "user") -> str:
    e = store.archive(session_id=session_id, role=role, source="test", content=content)
    return e.id


def _seg_files(store: ArchiveStore, session_id: str) -> list[Path]:
    return store._segment_paths(session_id)


def test_legacy_single_file_is_seq0(tmp_path):
    """旧存储单文件 <sid>.jsonl 视为 seq 0，枚举/读写兼容."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "旧内容 alpha")
    segs = _seg_files(store, _SID)
    assert [s.name for s in segs] == [f"{_SID}.jsonl"]
    assert store._segment_seq(segs[0]) == (_SID, 0)
    # 直接构造旧式文件也能被识别
    p = tmp_path / f"{_SID}-3.jsonl"
    p.write_text('{"id": "x", "ts": "t"}\n', encoding="utf-8")
    assert store._segment_seq(p) == (_SID, 3)


def test_segment_sort_order(tmp_path):
    """段枚举按 seq 升序（乱序创建也正确排序；主文件在前）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    for n in (3, 1, 2):
        (tmp_path / f"{_SID}-{n}.jsonl").write_text('{"id": "x"}\n', encoding="utf-8")
    (tmp_path / f"{_SID}.jsonl").write_text('{"id": "x"}\n', encoding="utf-8")
    names = [s.name for s in _seg_files(store, _SID)]
    assert names == [f"{_SID}.jsonl", f"{_SID}-1.jsonl", f"{_SID}-2.jsonl", f"{_SID}-3.jsonl"]


def test_new_segment_when_exceeding_threshold(tmp_path):
    """单文件达到阈值 → 下次写入开新段，旧文件不再增长（确定性构造）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "x" * 100)  # 主段 1 条（< 200B）
    # 手动把主段撑过阈值（模拟历史大文件，不依赖 JSON 序列化大小）
    with open(tmp_path / f"{_SID}.jsonl", "a", encoding="utf-8") as f:
        f.write("x" * 300 + "\n")
    _mk(store, _SID, "y" * 100)  # 主段已 ≥200B → 开新段 -1
    segs = _seg_files(store, _SID)
    assert [s.name for s in segs] == [f"{_SID}.jsonl", f"{_SID}-1.jsonl"]
    seg1 = segs[1].read_text(encoding="utf-8")
    assert "y" * 100 in seg1
    # 再写：-1 段 JSON 已超 200B → 继续开新段（每段 1 条，旧文件不再增长）
    _mk(store, _SID, "z" * 100)
    segs = _seg_files(store, _SID)
    assert [s.name for s in segs] == [f"{_SID}.jsonl", f"{_SID}-1.jsonl", f"{_SID}-2.jsonl"]
    assert "z" * 100 in segs[2].read_text(encoding="utf-8")


def test_segment_bytes_zero_no_split(tmp_path):
    """segment_bytes=0（不分片）→ 全部写同一文件（旧行为）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    for i in range(5):
        _mk(store, _SID, f"内容{i}")
    assert len(_seg_files(store, _SID)) == 1


def test_search_across_segments_newest_first(tmp_path):
    """跨段检索：命中合并，最近段条目先返回."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "早段关键词 apple")
    _mk(store, _SID, "早段二")  # 触发分片
    _mk(store, _SID, "新段关键词 apple")
    hits = store.search(_SID, "apple", limit=10)
    assert len(hits) == 2
    # 最近段条目在前（每条 JSON 超阈值 → 每段 1 条，最新在 -2.jsonl）
    assert "新段关键词" in hits[0]["content_preview"]
    assert "早段关键词" in hits[1]["content_preview"]
    assert Path(hits[0]["file"]).stem != _SID  # 来自段文件而非主文件
    assert Path(hits[0]["file"]).name == f"{_SID}-2.jsonl"


def test_search_limit_stops_at_newest_segments(tmp_path):
    """limit 命中即停：只搜最近段足够时不再读旧段（大文件性能）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "旧 apple")
    _mk(store, _SID, "旧二")
    _mk(store, _SID, "新 apple")
    _mk(store, _SID, "新二")
    hits = store.search(_SID, "apple", limit=1)
    assert len(hits) == 1
    assert Path(hits[0]["file"]).name == f"{_SID}-2.jsonl"  # "新 apple" 所在段（每段 1 条）


def test_get_by_tool_call_id_across_segments(tmp_path):
    """tool_call_id 定位跨段（最近段优先）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "早段")
    store.archive(
        session_id=_SID, role="tool", source="test", content="旧回执", tool_call_id="tc-old"
    )
    _mk(store, _SID, "触发分片")
    store.archive(
        session_id=_SID, role="tool", source="test", content="新回执", tool_call_id="tc-new"
    )
    hit = store.get_by_tool_call_id(_SID, "tc-old")
    assert hit is not None and hit["content"] == "旧回执"
    hit = store.get_by_tool_call_id(_SID, "tc-new")
    assert hit is not None and hit["content"] == "新回执"
    assert store.get_by_tool_call_id(_SID, "tc-missing") is None


def test_stats_across_segments(tmp_path):
    """stats 跨段累加."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "a" * 50)
    _mk(store, _SID, "b" * 50)
    _mk(store, _SID, "c" * 50)
    st = store.stats(_SID)
    assert st["archived_count"] == 3
    assert st["archived_chars"] == 150


def test_update_summary_across_segments(tmp_path):
    """update_summary 定位到正确段（分片后不回写错文件）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    eid_old = _mk(store, _SID, "早段内容")
    _mk(store, _SID, "早段二")
    eid_new = _mk(store, _SID, "新段内容")
    assert store.update_summary(eid_old, "旧摘要", "llm") is True
    assert store.update_summary(eid_new, "新摘要", "llm") is True
    hits = store.search(_SID, "旧摘要", limit=10)
    assert any(h["id"] == eid_old for h in hits)
    hits = store.search(_SID, "新摘要", limit=10)
    assert any(h["id"] == eid_new for h in hits)


def test_cleanup_cross_segment_keeps_newest(tmp_path):
    """cleanup max_entries 跨段全局保留最近 N 条（旧段整段删除优先）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    for i in range(8):
        _mk(store, _SID, f"内容{i}")  # 分 2-3 段
    segs_before = len(_seg_files(store, _SID))
    assert segs_before >= 2
    result = store.cleanup(max_entries=3, ttl_days=0)
    assert result["pruned_entries"] == 5
    total = store.stats(_SID)["archived_count"]
    assert total == 3
    remaining = [
        json.loads(line)["content"]
        for p in _seg_files(store, _SID)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 保留的是最近 3 条（最后写入的内容编号最大）
    assert remaining == ["内容5", "内容6", "内容7"]


def test_cleanup_ttl_across_segments(tmp_path):
    """cleanup ttl 跨段逐条清理."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    import datetime

    old_ts = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
    e_old = store.archive(session_id=_SID, role="user", source="test", content="过期内容")
    # 手动改写 ts 为 40 天前
    p = store._entry_session_path(e_old.id)
    assert p is not None
    lines = [
        json.loads(raw_line)
        for raw_line in p.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    lines[0]["ts"] = old_ts
    p.write_text(
        "\n".join(json.dumps(rec, ensure_ascii=False) for rec in lines) + "\n",
        encoding="utf-8",
    )
    _mk(store, _SID, "新内容")
    result = store.cleanup(max_entries=0, ttl_days=30)
    assert result["pruned_entries"] == 1
    hits = store.search(_SID, "过期内容", limit=10)
    assert hits == []


def test_corrupt_segment_fail_open(tmp_path):
    """损坏段文件 → 检索跳过不中断（fail-open），正常段仍可命中."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "新段关键词 banana")
    _mk(store, _SID, "触发")
    _mk(store, _SID, "第二段 banana")
    # 把第一段写坏（非 JSON 行）；每条 JSON 均超 200B 阈值 → 每段 1 条
    seg0 = tmp_path / f"{_SID}.jsonl"
    seg0.write_text("{broken json line\n", encoding="utf-8")
    hits = store.search(_SID, "banana", limit=10)
    assert len(hits) == 1  # 最后段（-2.jsonl）仍命中
    assert hits[0]["content_preview"] == "第二段 banana"
    assert Path(hits[0]["file"]).name == f"{_SID}-2.jsonl"
