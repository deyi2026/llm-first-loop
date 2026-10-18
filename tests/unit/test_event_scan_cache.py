"""event_scan_cache 单测：与全量直读逐字对拍 + 增量/损坏/禁用路径。"""
import fcntl
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.introspection import event_scan_cache as esc  # noqa: E402

KEEP = {"rule.feedback", "knowledge.read"}


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _row(seq, ts, typ):
    return {"seq": seq, "ts": ts, "type": typ, "payload": {"ref": "RULE-AI-1"}}


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "sessA").mkdir()
    _write(tmp_path / "sessA" / "1.jsonl", [_row(1, "2026-10-16T01:00:00Z", "rule.feedback")])
    _write(tmp_path / "sessA" / "2.jsonl", [_row(2, "2026-10-16T02:00:00Z", "knowledge.read")])
    _write(tmp_path / "top.jsonl", [_row(3, "2026-10-16T03:00:00Z", "message.appended")])
    return tmp_path


def test_full_equivalence_and_ordering(root):
    rows, wm = esc.scan_event_files(root, keep_types=KEEP)
    assert [r["seq"] for r in rows] == [1, 2]  # 过滤行不出现，行序=文件序
    assert wm == "2026-10-16T03:00:00Z"  # 水位覆盖被过滤行
    again, wm2 = esc.scan_event_files(root, keep_types=KEEP)
    assert again == rows and wm2 == wm  # 第二次命中缓存，结果一致
    # 缓存目录自身不被扫
    assert not any(".scan_cache" in str(r) for r in rows)


def test_incremental_append_and_new_file(root):
    esc.scan_event_files(root, keep_types=KEEP)
    _write(root / "sessA" / "1.jsonl", [_row(4, "2026-10-16T04:00:00Z", "rule.feedback")])
    _write(root / "sessB" / "9.jsonl", [_row(9, "2026-10-16T09:00:00Z", "rule.feedback")])
    rows, wm = esc.scan_event_files(root, keep_types=KEEP)
    assert [r["seq"] for r in rows] == [1, 4, 2, 9]
    assert wm == "2026-10-16T09:00:00Z"


def test_truncate_rewrites_file(root):
    esc.scan_event_files(root, keep_types=KEEP)
    p = root / "sessA" / "1.jsonl"
    p.unlink()
    _write(p, [_row(5, "2026-10-16T05:00:00Z", "rule.feedback")])
    rows, _ = esc.scan_event_files(root, keep_types=KEEP)
    assert 1 not in [r["seq"] for r in rows] and 5 in [r["seq"] for r in rows]


def test_corrupt_cache_rebuilds(root):
    esc.scan_event_files(root, keep_types=KEEP)
    cache = list((root / ".scan_cache").glob("events_*.json"))[0]
    cache.write_text("{ not-json", encoding="utf-8")
    rows, wm = esc.scan_event_files(root, keep_types=KEEP)
    assert [r["seq"] for r in rows] == [1, 2] and wm == "2026-10-16T03:00:00Z"


def test_keep_buckets_do_not_pollute(root):
    a, _ = esc.scan_event_files(root, keep_types=KEEP)
    b, _ = esc.scan_event_files(root, keep_types={"rule.feedback"})
    assert [r["seq"] for r in b] == [1]
    c, _ = esc.scan_event_files(root, keep_types=KEEP)
    assert [r["seq"] for r in c] == [r["seq"] for r in a]


def test_missing_root_returns_empty(tmp_path):
    rows, wm = esc.scan_event_files(tmp_path / "nope", keep_types=KEEP)
    assert rows == [] and wm == ""


def test_lock_timeout_with_cold_cache_falls_back_to_full_scan(tmp_path, monkeypatch):
    root = tmp_path
    _write(root / "a.jsonl", [_row(1, "2026-10-17T01:00:00Z", "rule.feedback")])
    _write(root / "b.jsonl", [_row(2, "2026-10-17T02:00:00Z", "rule.feedback")])
    lock = root / ".scan_cache" / f"events_{esc._keep_hash({'rule.feedback'})}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd2 = os.open(str(lock), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd2, fcntl.LOCK_EX)  # 他方持锁不放
        monkeypatch.setattr(esc, "_LOCK_WAIT_SECONDS", 0.2)
        rows, wm = esc.scan_event_files(root, keep_types=("rule.feedback",))
        assert [r["seq"] for r in rows] == [1, 2]  # 空快照回退全量直读，非空集
        assert wm == "2026-10-17T02:00:00Z"
    finally:
        fcntl.flock(fd2, fcntl.LOCK_UN)
        os.close(fd2)


def test_torn_tail_line_recovered_after_completion(tmp_path):
    f = tmp_path / "a.jsonl"
    _write(f, [_row(1, "2026-10-17T01:00:00Z", "rule.feedback")])
    esc.scan_event_files(tmp_path, keep_types=KEEP)
    with f.open("a", encoding="utf-8") as fh:  # 末尾撕裂半行（无换行）
        fh.write('{"ts": "9999-01-01T00:00:00", "type":')
    rows, wm = esc.scan_event_files(tmp_path, keep_types=KEEP)
    assert [r["seq"] for r in rows] == [1]  # 半行不出现
    assert wm == "2026-10-17T01:00:00Z"  # 半行的 ts 也不进水位
    with f.open("a", encoding="utf-8") as fh:  # 补全成完整合法行 + 换行
        fh.write(' "rule.feedback", "seq": 2}\n')
    rows, wm = esc.scan_event_files(tmp_path, keep_types=KEEP)
    assert [r["seq"] for r in rows] == [1, 2]  # 补全的行被续读重拿
    assert wm == "9999-01-01T00:00:00"


def test_corrupted_rows_by_file_value_rejected(tmp_path):
    _write(tmp_path / "a.jsonl", [_row(1, "2026-10-17T01:00:00Z", "rule.feedback")])
    cdir = tmp_path / ".scan_cache"
    cdir.mkdir()
    (cdir / f"events_{esc._keep_hash({'rule.feedback'})}.json").write_text(
        json.dumps(
            {
                "version": esc.CACHE_VERSION,
                "keep": ["rule.feedback"],
                "files": {"a.jsonl": [0, 0, 0]},
                "rows_by_file": {"a.jsonl": "garbage-string"},
                "indexed_watermark": "",
            }
        ),
        encoding="utf-8",
    )
    rows, _wm = esc.scan_event_files(tmp_path, keep_types=("rule.feedback",))
    assert [r["seq"] for r in rows] == [1]  # 值损坏 → 视为不可用 → 全量重建
    assert all(isinstance(r, dict) for r in rows)  # 垃圾行不穿透
