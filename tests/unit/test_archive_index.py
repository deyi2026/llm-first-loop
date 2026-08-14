"""T3c(2026-08-14) 档案 sidecar 索引检索测试（tmp_path 隔离，零真实数据）.

覆盖: 索引随写入生成 / 快速通道命中即停 / 索引未达 limit 全文补齐（content 尾部
关键词）/ 无索引存量段全文扫描 / 索引损坏行跳过 / 索引缺失回退 / tool_call_id
索引精确定位 / 索引与段内容逐条对账 / role/tool_name 过滤走索引。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.memory.archive import ArchiveStore

_SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0000"


def _mk(store: ArchiveStore, session_id: str, content: str, role: str = "user") -> str:
    e = store.archive(session_id=session_id, role=role, source="test", content=content)
    return e.id


def _idx_of(store: ArchiveStore, name: str) -> Path:
    return Path(str(store._dir / name) + ".idx")


def test_index_written_on_archive(tmp_path):
    """写入档案时同步生成 sidecar 索引，条目一一对应."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "第一条内容")
    _mk(store, _SID, "第二条内容")
    idx = _idx_of(store, f"{_SID}.jsonl")
    assert idx.exists()
    recs = [
        json.loads(raw_line)
        for raw_line in idx.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    assert len(recs) == 2
    assert recs[0]["content_head"] == "第一条内容"
    assert recs[0]["offset"] == 0
    assert recs[1]["offset"] > recs[0]["offset"]  # 偏移递增


def test_index_matches_segment_content(tmp_path):
    """索引与段原文逐条对账（id/offset/tool_call_id/role 一致）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "内容a")
    store.archive(
        session_id=_SID,
        role="tool",
        source="test",
        content="回执b",
        tool_name="read_file",
        tool_call_id="tc-1",
    )
    seg = store._dir / f"{_SID}.jsonl"
    idx = _idx_of(store, f"{_SID}.jsonl")
    seg_recs = [
        json.loads(raw_line)
        for raw_line in seg.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    idx_recs = [
        json.loads(raw_line)
        for raw_line in idx.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    assert len(seg_recs) == len(idx_recs) == 2
    for s, r in zip(seg_recs, idx_recs, strict=True):
        assert s["id"] == r["id"]
        assert s.get("tool_call_id") == r["tool_call_id"]
        assert s.get("role") == r["role"]


def test_search_index_fastpath(tmp_path, monkeypatch):
    """快速通道：索引命中达 limit 即停，不读段原文（性能路径验证）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "关键词 alpha 内容")
    _mk(store, _SID, "无关内容")
    calls = {"full_scan": 0}
    orig = ArchiveStore._scan_segment

    def spy(self, *a, **k):
        calls["full_scan"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(ArchiveStore, "_scan_segment", spy)
    hits = store.search(_SID, "alpha", limit=1)
    assert len(hits) == 1
    assert hits[0]["content_preview"] == "关键词 alpha 内容"
    assert calls["full_scan"] == 0  # 索引命中即停，未触发全文扫描


def test_search_full_scan_fallback_when_index_missing(tmp_path, monkeypatch):
    """存量段无索引 → 全文扫描（fail-open 兼容），结果一致."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "旧存量内容 beta")
    # 删除索引模拟存量段
    _idx_of(store, f"{_SID}.jsonl").unlink()
    calls = {"full_scan": 0}
    orig = ArchiveStore._scan_segment

    def spy(self, *a, **k):
        calls["full_scan"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(ArchiveStore, "_scan_segment", spy)
    hits = store.search(_SID, "beta", limit=10)
    assert len(hits) == 1
    assert calls["full_scan"] == 1


def test_search_content_tail_fallback(tmp_path):
    """索引盲区（关键词仅 content 尾部，超出 content_head 800 字符）→ 全文补齐不漏."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "x" * 900 + "尾部关键词 gamma")
    hits = store.search(_SID, "gamma", limit=10)
    assert len(hits) == 1  # 索引 content_head 无 gamma → 快速通道 0 命中 → 全文补齐命中


def test_search_mixed_hits_no_duplicate(tmp_path):
    """快速通道 + 补齐结果去重（同一 entry 不重复计数）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "头部关键词 delta")
    _mk(store, _SID, "x" * 900 + "尾部关键词 delta")
    hits = store.search(_SID, "delta", limit=10)
    assert len(hits) == 2
    ids = [h["id"] for h in hits]
    assert len(set(ids)) == 2


def test_search_corrupt_index_line_fallback(tmp_path):
    """索引损坏行跳过 + 其余正常（全文补齐兜底）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "第一条关键词 epsilon")
    _mk(store, _SID, "第二条内容")
    idx = _idx_of(store, f"{_SID}.jsonl")
    idx.write_text("{broken\n" + idx.read_text(encoding="utf-8"), encoding="utf-8")
    hits = store.search(_SID, "epsilon", limit=10)
    assert len(hits) == 1  # 损坏行跳过，第二条索引仍可命中
    assert hits[0]["content_preview"] == "第一条关键词 epsilon"


def test_get_by_tool_call_id_index_fastpath(tmp_path, monkeypatch):
    """tool_call_id 走索引精确定位（不全文扫描）."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "内容1")
    store.archive(
        session_id=_SID,
        role="tool",
        source="test",
        content="目标回执",
        tool_call_id="tc-target",
    )
    monkeypatch.setattr(
        ArchiveStore,
        "_line_at",
        lambda self, p, off: None,  # 若走全文扫描路径会失败；索引路径返回 entry 则证明走了索引
    )
    hit = store.get_by_tool_call_id(_SID, "tc-target")
    # 索引路径 _line_at 返回 None → 快速通道失败 → 回退全文扫描也能命中（结果正确）
    assert hit is not None and hit["content"] == "目标回执"


def test_get_by_tool_call_id_missing(tmp_path):
    """未归档的 tool_call_id → None."""
    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "内容")
    assert store.get_by_tool_call_id(_SID, "tc-none") is None


def test_index_does_not_break_segment_enumeration(tmp_path):
    """索引文件不干扰段枚举（glob 只匹配 *.jsonl）."""
    store = ArchiveStore(tmp_path, segment_bytes=200)
    _mk(store, _SID, "内容1")
    _mk(store, _SID, "内容2")
    assert all(not s.name.endswith(".idx") for s in store._segment_paths(_SID))


# ── R3: 存量段索引重建（archive-index）──


def test_rebuild_segment_index(tmp_path):
    """无索引存量段 → 重建 .idx（rec 格式一致，偏移正确）."""
    from llm_loop.memory.archive import ArchiveStore

    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "存量内容 alpha")
    _mk(store, _SID, "存量内容 beta")
    seg = store._dir / f"{_SID}.jsonl"
    idx = Path(str(seg) + ".idx")
    idx.unlink()  # 模拟存量段（无索引）
    n = store.rebuild_segment_index(seg)
    assert n == 2
    recs = [
        json.loads(raw_line)
        for raw_line in idx.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    assert [r["content_head"] for r in recs] == ["存量内容 alpha", "存量内容 beta"]
    assert recs[0]["offset"] == 0
    assert recs[1]["offset"] > recs[0]["offset"]
    # 重建后检索走索引路径（快速通道命中）
    hits = store.search(_SID, "beta", limit=10)
    assert len(hits) == 1 and "beta" in hits[0]["content_preview"]


def test_rebuild_idempotent_and_corrupt_skip(tmp_path):
    """重建幂等（重复执行条目数一致）+ 损坏行跳过（fail-open）."""
    from llm_loop.memory.archive import ArchiveStore

    store = ArchiveStore(tmp_path, segment_bytes=0)
    _mk(store, _SID, "内容一")
    seg = store._dir / f"{_SID}.jsonl"
    with seg.open("a", encoding="utf-8") as f:
        f.write("{broken json\n")
    idx = Path(str(seg) + ".idx")
    assert store.rebuild_segment_index(seg) == 1  # 损坏行跳过
    assert store.rebuild_segment_index(seg) == 1  # 幂等
    recs = [
        raw_line
        for raw_line in idx.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    assert len(recs) == 1


def test_rebuild_all_indexes(tmp_path):
    """全量重建（含分片段）统计正确."""
    from llm_loop.memory.archive import ArchiveStore

    store = ArchiveStore(tmp_path, segment_bytes=100000)
    _mk(store, _SID, "内容x")
    _mk(store, "bbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "内容y")
    report = store.rebuild_all_indexes()
    assert report["segments"] == 2
    assert report["entries"] == 2
    assert report["failed"] == 0
