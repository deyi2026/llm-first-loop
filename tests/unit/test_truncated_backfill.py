"""B2-P2 存量回填单元测试（EVO-20260902-251f059a）.

覆盖：collect 过滤/排序、digest 恢复（llm_error 原因行 / cancelled→user_stop）、
幂等重跑、与在线路径同键互斥、dry_run 零写入、检索面验收形态。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.event_log.backfill_truncated import (
    backfill_truncated_runs,
    collect_interrupted_runs,
)
from llm_loop.event_log.store import EventStore
from llm_loop.memory.episode import EpisodeStore

SID = "01234567-89ab-cdef-0123-456789abcdef"

_LL_ERROR_PREVIEW = (
    "[LLM 调用异常] 事实: LLM 调用失败。\n"
    '原因: LLMHTTPError: HTTP 400: Bad Request | {"error":{"code":"1214",'
    '"message":"messages 参数非法"}}'
)


def _make_stores(tmp_path: Path) -> tuple[EventStore, EpisodeStore]:
    es = EventStore(tmp_path / "events")
    ep = EpisodeStore(tmp_path / "episodes")
    return es, ep


def _seed_history(es: EventStore) -> None:
    """合成 4 个历史 run 边界：completed / llm_error / cancelled / guard_blocked."""
    es.append(SID, "run.start", {"rounds": 0})
    es.append(SID, "run.end", {"reason": "completed", "rounds": 3})
    es.append(SID, "run.end", {
        "reason": "llm_error", "rounds": 48, "cancel_reason": "",
        "answer_preview": _LL_ERROR_PREVIEW,
    })
    es.append(SID, "run.end", {
        "reason": "cancelled", "rounds": 17, "cancel_reason": "user_stop",
        "answer_preview": "（已停止——用户点击停止按钮，本轮回答终止）",
    })
    es.append(SID, "run.end", {
        "reason": "guard_blocked", "rounds": 2, "cancel_reason": "",
        "answer_preview": "[缓存守卫拦截] 上下文超限",
    })


def test_collect_filters_completed_keeps_order(tmp_path):
    es, _ = _make_stores(tmp_path)
    _seed_history(es)
    runs = collect_interrupted_runs(es.read(SID))
    assert [r["reason"] for r in runs] == ["llm_error", "cancelled", "guard_blocked"]
    assert [r["seq"] for r in runs] == sorted(r["seq"] for r in runs)
    assert all(r["seq"] > 0 and r["ts"] for r in runs)


def test_backfill_writes_rows_with_recovered_fields(tmp_path):
    es, ep = _make_stores(tmp_path)
    _seed_history(es)
    report = backfill_truncated_runs(ep, es, [SID])
    assert report["sessions"] == 1 and report["written"] == 3 and report["errors"] == 0

    rows = [json.loads(line) for line in (tmp_path / "episodes" / f"{SID}.truncated.jsonl").read_text().splitlines() if line]
    by_reason = {r["run_end_reason"]: r for r in rows}
    assert set(by_reason) == {"llm_error", "cancelled", "guard_blocked"}

    err = by_reason["llm_error"]
    assert err["error_digest"].startswith("LLMHTTPError: HTTP 400")
    assert err["last_round"] == 48 and err["partial_chars"] == 0
    assert err["text_tail"] == "" and err["reasoning_tail"] == ""  # 诚实边界：历史半截不可恢复

    cancel = by_reason["cancelled"]
    assert cancel["error_digest"] == "user_stop" and cancel["last_round"] == 17
    assert all(r["ref"] == f"truncated:{r['run_end_seq']}" for r in rows)


def test_backfill_idempotent_rerun_and_live_path_key(tmp_path):
    es, ep = _make_stores(tmp_path)
    _seed_history(es)
    first = backfill_truncated_runs(ep, es, [SID])
    assert first["written"] == 3
    path = tmp_path / "episodes" / f"{SID}.truncated.jsonl"
    before = path.read_text()

    rerun = backfill_truncated_runs(ep, es, [SID])
    assert rerun["written"] == 0 and rerun["deduped"] == 3
    assert path.read_text() == before  # 文件字节级不变

    # 与在线路径同键互斥：主路径已写的 seq 不回填双写
    events = [e for e in es.read(SID) if e.type == "run.end" and e.payload["reason"] == "completed"]
    seq = events[0].seq
    ep.index_truncated_run(SID, run_end_reason="completed?", run_end_seq=seq)  # 模拟占位
    final = backfill_truncated_runs(ep, es, [SID])
    assert final["written"] == 0


def test_dry_run_writes_nothing(tmp_path):
    es, ep = _make_stores(tmp_path)
    _seed_history(es)
    report = backfill_truncated_runs(ep, es, [SID], dry_run=True)
    assert report["would_write"] == 3 and report["written"] == 0
    assert not (tmp_path / "episodes" / f"{SID}.truncated.jsonl").exists()


def test_search_and_hydrate_acceptance_shape(tmp_path):
    """验收形态（对齐 EVO 251f059a）：空查询可见 state=truncated 行，compact hydrate 可回."""
    es, ep = _make_stores(tmp_path)
    _seed_history(es)
    backfill_truncated_runs(ep, es, [SID])
    hits = ep.search_truncated(SID, query="", limit=10)
    assert {h["state"] for h in hits} == {"truncated"}
    reasons = {h["run_end_reason"] for h in hits}
    assert {"llm_error", "cancelled", "guard_blocked"} <= reasons

    seq = [r for r in collect_interrupted_runs(es.read(SID)) if r["reason"] == "cancelled"][0]["seq"]
    rec = ep.hydrate_truncated(SID, f"truncated:{seq}")
    assert rec is not None
    assert rec["run_end_reason"] == "cancelled" and rec["complete"] is True
    assert rec["error_digest"] == "user_stop"
