"""B2-P2 存量回填（EVO-20260902-251f059a）单元测试.

覆盖：collect 过滤非 completed run.end、回填写行字段（digest/rounds/seq/ref）、
幂等（重跑/与在线路径同键互斥）、dry-run 零写入、search/hydrate 验收形态、
单会话失败隔离与错误 episode_store 类型拒绝。
诚实边界断言：回填行尾段如实为空（B1 前半截产物未落盘，不伪造）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.event_log.backfill_truncated import (
    backfill_truncated_runs,
    collect_interrupted_runs,
)
from llm_loop.event_log.store import EventStore
from llm_loop.memory.episode import EpisodeStore

_SID = "6e1f9c2a-3b4d-4e5f-8a9b-1c2d3e4f5a6b"

_LLM_ERROR_PREVIEW = (
    '[LLM 调用异常] 事实: LLM 调用失败。\n原因: LLMHTTPError: HTTP 400: Bad Request'
    ' | {"error":{"code":"1214","message":"messages 参数非法。请检查文档'
)


def _seed_runs(es: EventStore, sid: str) -> tuple[int, int]:
    """种三段 run 边界：completed / llm_error / cancelled；返回两个中断 run 的 seq."""
    es.append(sid, "session.created", {"session_id": sid})
    es.append(sid, "run.start", {"reason": "user"})
    es.append(sid, "run.end", {"reason": "completed", "rounds": 3, "answer_preview": "done"})
    es.append(sid, "run.start", {"reason": "user"})
    ev_llm_err = es.append(
        sid,
        "run.end",
        {
            "reason": "llm_error",
            "cancel_reason": "",
            "rounds": 48,
            "answer_preview": _LLM_ERROR_PREVIEW,
        },
    )
    es.append(sid, "run.start", {"reason": "user"})
    ev_cancel = es.append(
        sid,
        "run.end",
        {
            "reason": "cancelled",
            "cancel_reason": "user_stop",
            "rounds": 17,
            "answer_preview": "（已停止——用户点击停止按钮，本轮回答终止）",
        },
    )
    assert ev_llm_err is not None and ev_cancel is not None
    return ev_llm_err.seq, ev_cancel.seq


@pytest.fixture()
def stores(tmp_path: Path) -> tuple[EpisodeStore, EventStore]:
    return EpisodeStore(tmp_path / "episodes"), EventStore(tmp_path / "events")


def test_collect_keeps_only_interrupted_in_seq_order(stores):
    ep, es = stores
    seq_err, seq_cancel = _seed_runs(es, _SID)
    runs = collect_interrupted_runs(es.read(_SID))
    assert [r["seq"] for r in runs] == [seq_err, seq_cancel]
    assert [r["reason"] for r in runs] == ["llm_error", "cancelled"]


def test_backfill_writes_rows_with_honest_fields(stores):
    ep, es = stores
    seq_err, seq_cancel = _seed_runs(es, _SID)
    report = backfill_truncated_runs(ep, es, [_SID])
    assert report["written"] == 2 and report["deduped"] == 0 and report["errors"] == 0
    lines = (ep._root / f"{_SID}.truncated.jsonl").read_text().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    assert [r["run_end_seq"] for r in rows] == [seq_err, seq_cancel]
    by_seq = {r["run_end_seq"]: r for r in rows}
    # llm_error：digest 取"原因: "行内容（状态码+provider+消息头）；尾段如实为空
    err_row = by_seq[seq_err]
    assert err_row["error_digest"].startswith("LLMHTTPError: HTTP 400: Bad Request")
    assert err_row["last_round"] == 48
    assert err_row["entry_kind"] == "truncated" and err_row["ref"] == f"truncated:{seq_err}"
    assert err_row["text_tail"] == "" and err_row["reasoning_tail"] == ""
    assert err_row["partial_chars"] == 0 and err_row["partial_sha256"] == ""
    # cancelled：digest=cancel_reason（归因进 summary 一眼可见）
    cancel_row = by_seq[seq_cancel]
    assert cancel_row["error_digest"] == "user_stop" and cancel_row["last_round"] == 17


def test_backfill_idempotent_rerun_writes_nothing(stores):
    ep, es = stores
    _seed_runs(es, _SID)
    backfill_truncated_runs(ep, es, [_SID])
    path = ep._root / f"{_SID}.truncated.jsonl"
    before = path.read_text()
    report = backfill_truncated_runs(ep, es, [_SID])
    assert report["written"] == 0 and report["deduped"] == 2
    assert path.read_text() == before


def test_backfill_no_double_write_with_live_path_row(stores):
    """与 B1/B2 在线路径同键互斥：同一 (sid, run_end_seq) 不双写."""
    ep, es = stores
    seq_err, _ = _seed_runs(es, _SID)
    ep.index_truncated_run(_SID, run_end_reason="llm_error", run_end_seq=seq_err)
    report = backfill_truncated_runs(ep, es, [_SID])
    assert report["written"] == 1 and report["deduped"] == 1
    path = ep._root / f"{_SID}.truncated.jsonl"
    assert len([x for x in path.read_text().splitlines() if x.strip()]) == 2


def test_backfill_dry_run_writes_nothing(stores):
    ep, es = stores
    _seed_runs(es, _SID)
    report = backfill_truncated_runs(ep, es, [_SID], dry_run=True)
    assert report["would_write"] == 2 and report["written"] == 0
    assert not (ep._root / f"{_SID}.truncated.jsonl").exists()


def test_backfill_acceptance_search_and_hydrate(stores):
    """验收形态（镜像 EVO 251f059a）：空查询可见 truncated 行；hydrate 返回 compact 记录."""
    ep, es = stores
    _, seq_cancel = _seed_runs(es, _SID)
    backfill_truncated_runs(ep, es, [_SID])
    hits = ep.search_truncated(_SID, query="")
    assert len(hits) == 2
    assert all(h["state"] == "truncated" and h["kind"] == "episode" for h in hits)
    reasons = {h["run_end_reason"] for h in hits}
    assert reasons == {"llm_error", "cancelled"}
    rec = ep.hydrate_truncated(_SID, f"truncated:{seq_cancel}")
    assert rec is not None and rec["complete"] is True
    assert rec["run_end_reason"] == "cancelled" and rec["error_digest"] == "user_stop"
    assert rec["last_round"] == 17


def test_backfill_skips_session_without_interrupted_runs(stores):
    ep, es = stores
    es.append(_SID, "session.created", {"session_id": _SID})
    es.append(_SID, "run.end", {"reason": "completed", "rounds": 1, "answer_preview": "ok"})
    report = backfill_truncated_runs(ep, es, [_SID])
    assert report["sessions"] == 0 and report["runs_seen"] == 0


def test_backfill_rejects_wrong_episode_store(tmp_path):
    class _Noop:
        pass

    with pytest.raises(TypeError):
        backfill_truncated_runs(_Noop(), EventStore(tmp_path / "events"), [_SID])
