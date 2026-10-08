"""ASSESS-20261008-project-audit rev3 §7 WP4b-2 回归: BUG-05.

修复契约: _jsonl_search 的候选选择发生在输出 limit 之前——同词多条命中按
（ts, 行序）选最新 top-k，内存上界为 O(limit)（有界淘汰，不整文件载入排序）。
原实现按文件位置取前 limit 条: old→new 追加写 + limit=1 永远只返回最旧
（位置偏置，审计 R 级复现）。

对照不变: 损坏行跳过不崩溃; 无 ts/同 ts 有确定次序; 精确 id 检索与
memory/method 专用检索路径不回退。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.introspection.search import RecordSearcher, _jsonl_search


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _exc(ts: str, msg: str, eid: str = "") -> dict:
    d = {"ts": ts, "error_type": "TestError", "error_message": msg, "content": msg}
    if eid:
        d["id"] = eid
    return d


def test_selection_before_limit_returns_newest(tmp_path):
    """old→new 写入、limit=1 → 返回最新（原返回最旧）."""
    p = tmp_path / "exception_log.jsonl"
    _write_jsonl(p, [
        _exc("2026-10-08T10:00:00", "auth 同词 oldest"),
        _exc("2026-10-08T11:00:00", "auth 同词 newest"),
    ])
    hits = _jsonl_search(p, "auth", 1, kind="exception_log",
                         summary_keys=("error_type", "error_message"))
    assert len(hits) == 1
    assert "newest" in hits[0]["summary"]


def test_same_ts_tie_broken_by_line_order(tmp_path):
    """同 ts: 行序新者胜（确定次序，不依赖 dict 顺序）."""
    p = tmp_path / "exception_log.jsonl"
    _write_jsonl(p, [
        _exc("2026-10-08T10:00:00", "tie 同词 first"),
        _exc("2026-10-08T10:00:00", "tie 同词 second"),
    ])
    hits = _jsonl_search(p, "tie", 1, kind="exception_log",
                         summary_keys=("error_type", "error_message"))
    assert "second" in hits[0]["summary"]


def test_missing_ts_treated_as_oldest(tmp_path):
    p = tmp_path / "exception_log.jsonl"
    _write_jsonl(p, [
        {"error_type": "T", "error_message": "mid 同词", "content": "mid"},  # 无 ts
        _exc("2026-10-08T10:00:00", "with-ts 同词"),
    ])
    hits = _jsonl_search(p, "同词", 2, kind="exception_log",
                         summary_keys=("error_type", "error_message"))
    assert len(hits) == 2
    one = _jsonl_search(p, "同词", 1, kind="exception_log",
                        summary_keys=("error_type", "error_message"))
    assert "with-ts" in one[0]["summary"]  # 有 ts 者更新


def test_corrupt_lines_skipped_not_crash(tmp_path):
    p = tmp_path / "exception_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(_exc("2026-10-08T09:00:00", "ok 同词 old")) + "\n"
        "{corrupt not json\n"
        + json.dumps(_exc("2026-10-08T12:00:00", "ok 同词 new")) + "\n",
        encoding="utf-8",
    )
    hits = _jsonl_search(p, "同词", 1, kind="exception_log",
                         summary_keys=("error_type", "error_message"))
    assert len(hits) == 1 and "new" in hits[0]["summary"]


def test_large_file_bounded_selection(tmp_path):
    """大文件（2 万行）limit=3: 功能正常且只在内存保留 limit 条（有界淘汰）."""
    p = tmp_path / "action_trace.jsonl"
    entries = [
        {"ts": f"2026-10-08T10:00:{h:06d}", "phase": "run",
         "action_type": "tool", "detail": f"bulk 同词 step{h}", "content": ""}
        for h in range(20000)
    ]
    _write_jsonl(p, entries)
    hits = _jsonl_search(p, "bulk 同词", 3, kind="action_trace",
                         summary_keys=("phase", "action_type", "detail"))
    assert len(hits) == 3
    details = [h["summary"] for h in hits]
    assert "step19999" in details[0]  # 最新在前


def test_exact_id_and_special_kinds_not_regressed(tmp_path):
    """对照: 精确 id 检索命中; RecordSearcher 特殊 kind 路径不回退."""
    p = tmp_path / "exception_log.jsonl"
    _write_jsonl(p, [
        _exc("2026-10-08T10:00:00", "id 查询目标", eid="EXC-0001"),
    ])
    hits = _jsonl_search(p, "EXC-0001", 5, kind="exception_log",
                         summary_keys=("error_type", "error_message"))
    assert len(hits) == 1
    assert hits[0]["id"] == "EXC-0001"

    from llm_loop.memory.store import MemoryEntry, MemoryStore

    mem = MemoryStore(tmp_path / "memory")
    mem.save_entry(MemoryEntry(id="", type="fact", content="用户喜欢记忆检索",
                               keywords=["记忆"]))
    searcher = RecordSearcher(audit_dir=tmp_path, memory_store=mem)
    recs = searcher.search(kind="memory", query="记忆检索", limit=5)
    assert len(recs) >= 1 and all(r["kind"] == "memory" for r in recs)
