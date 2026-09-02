"""B2-P2 存量回填单元测试（EVO-20260902-251f059a）.

覆盖：collect 过滤与排序 / 回填写行字段（llm_error digest 提取、cancelled→user_stop、
rounds/run_end_seq/ref）/ 幂等重跑 / 与在线路径同键互斥 / dry-run 零写入 /
检索面验收形态（search_truncated state=truncated + hydrate compact 记录）。
诚实边界：B1 上线前半截产物不可恢复 → 回填行尾段如实为空。
"""

from __future__ import annotations

from llm_loop.event_log.backfill_truncated import (
    backfill_truncated_runs,
    collect_interrupted_runs,
)
from llm_loop.event_log.store import EventStore
from llm_loop.memory.episode import EpisodeStore

SID = "1f0e3a44-9c2b-4d5e-8a71-0b6c2f4d9e01"
_ERR_PREVIEW = (
    "[LLM 调用异常] 事实: LLM 调用失败。\n"
    '原因: LLMHTTPError: HTTP 400: Bad Request | {"error":{"code":"1214",'
    '"message":"messages 参数非法"}}'
)


def _make_stores(tmp_path):
    return EventStore(tmp_path / "events"), EpisodeStore(tmp_path / "episodes")


def _seed_events(es, payloads):
    for etype, payload in payloads:
        es.append(SID, etype, payload)


def _run_end(reason, *, cancel_reason="", rounds=7, preview=""):
    payload = {
        "session_id": SID, "reason": reason, "cancel_reason": cancel_reason,
        "rounds": rounds, "duration_ms": 123.0, "model_used": "m", "truncated": True,
    }
    if preview:
        payload["answer_preview"] = preview
    return payload


def test_collect_filters_completed_and_keeps_seq_order(tmp_path):
    es, _ = _make_stores(tmp_path)
    _seed_events(es, [
        ("run.start", {"session_id": SID}),
        ("run.end", _run_end("completed")),
        ("run.end", _run_end("llm_error", preview=_ERR_PREVIEW)),
        ("run.end", _run_end("cancelled", cancel_reason="user_stop", rounds=17)),
    ])
    runs = collect_interrupted_runs(es.read(SID))
    assert [r["reason"] for r in runs] == ["llm_error", "cancelled"]
    seqs = [r["seq"] for r in runs]
    assert seqs == sorted(seqs) and all(s > 0 for s in seqs)
    assert runs[1]["payload"]["cancel_reason"] == "user_stop"


def test_backfill_writes_rows_with_recovered_fields(tmp_path):
    es, eps = _make_stores(tmp_path)
    _seed_events(es, [
        ("run.end", _run_end("llm_error", rounds=48, preview=_ERR_PREVIEW)),
        ("run.end", _run_end(
            "cancelled", cancel_reason="user_stop", rounds=17,
            preview="（已停止——用户点击停止按钮，本轮回答终止）")),
    ])
    report = backfill_truncated_runs(eps, es, [SID])
    assert report["written"] == 2 and report["deduped"] == 0 and report["errors"] == 0

    rows = eps._iter_truncated(SID)
    by_reason = {r["run_end_reason"]: r for r in rows}
    llm = by_reason["llm_error"]
    assert llm["error_digest"].startswith("LLMHTTPError: HTTP 400")
    assert '"code":"1214"' in llm["error_digest"]
    assert llm["last_round"] == 48
    assert llm["ref"] == f"truncated:{llm['run_end_seq']}"
    # 诚实边界：B1 前半截产物未落盘、不可恢复 → 尾段如实为空（不伪造）
    assert llm["text_tail"] == "" and llm["reasoning_tail"] == ""
    assert llm["partial_chars"] == 0 and llm["partial_sha256"] == ""
    can = by_reason["cancelled"]
    assert can["error_digest"] == "user_stop"
    assert can["last_round"] == 17


def test_backfill_idempotent_rerun(tmp_path):
    es, eps = _make_stores(tmp_path)
    _seed_events(es, [("run.end", _run_end("llm_error", rounds=3, preview=_ERR_PREVIEW))])
    assert backfill_truncated_runs(eps, es, [SID])["written"] == 1
    before = len(eps._iter_truncated(SID))
    second = backfill_truncated_runs(eps, es, [SID])
    assert second["written"] == 0 and second["deduped"] == 1
    assert len(eps._iter_truncated(SID)) == before


def test_backfill_dedups_against_live_path_rows(tmp_path):
    """在线路径（B1/B2）已写的 (sid, run_end_seq) 键 → 回填幂等命中不双写."""
    es, eps = _make_stores(tmp_path)
    _seed_events(es, [("run.end", _run_end("cancelled", cancel_reason="user_stop", rounds=17))])
    seq = es.read(SID)[-1].seq
    assert eps.index_truncated_run(
        SID, ts="T", run_end_reason="cancelled", run_end_seq=seq
    ) is True
    report = backfill_truncated_runs(eps, es, [SID])
    assert report["written"] == 0 and report["deduped"] == 1


def test_backfill_dry_run_writes_nothing(tmp_path):
    es, eps = _make_stores(tmp_path)
    _seed_events(es, [("run.end", _run_end("guard_blocked", rounds=5, preview="[缓存守卫拦截] x"))])
    report = backfill_truncated_runs(eps, es, [SID], dry_run=True)
    assert report["would_write"] == 1 and report["written"] == 0
    assert eps._iter_truncated(SID) == []


def test_search_and_hydrate_acceptance_shape(tmp_path):
    es, eps = _make_stores(tmp_path)
    _seed_events(es, [
        ("run.end", _run_end("llm_error", rounds=24, preview=_ERR_PREVIEW)),
        ("run.end", _run_end("cancelled", cancel_reason="user_stop", rounds=17)),
    ])
    backfill_truncated_runs(eps, es, [SID])
    hits = eps.search_truncated(SID, limit=10)
    assert len(hits) == 2
    assert all(h["state"] == "truncated" for h in hits)
    assert {h["run_end_reason"] for h in hits} == {"llm_error", "cancelled"}
    rec = eps.hydrate_truncated(SID, hits[0]["ref"])
    assert rec is not None and rec["complete"] is True
    assert rec["run_end_reason"] in {"llm_error", "cancelled"}
