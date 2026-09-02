"""B2-P2 存量回填（EVO-20260902-251f059a）：历史中断 run 补写 truncated episode 行.

B1/B2（EVO-20260902-41898b20）上线前的历史 run 中断在 episode 检索面结构性不可见
（动机案例：a100a752 会话 2026-09-02T04:40Z user_stop / 04:34Z llm_error(HTTP 400)，
resolved episode 索引止于完成态）。本模块从事件日志扫历史非 completed run.end 边界，
复用已实现的 EpisodeStore.index_truncated_run（幂等键=(session_id, run_end_seq)）
补写 {sid}.truncated.jsonl 行。

诚实边界（P1-6 精神）：B1 上线前流式半截产物未落盘、不可恢复——回填行 text_tail /
reasoning_tail 如实为空，恢复的是"结构性可见性"（何时/何因/第几轮被打断），
不伪造未持久化的内容。永不参与退休、不动 wire（与 B2 主路径同一独立索引文件）。

一次性离线运行：不触碰会话存储、不改事件日志；与运行中实例并发安全
（append + flush + fsync 单行写入，幂等键防重）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["collect_interrupted_runs", "backfill_truncated_runs"]


def collect_interrupted_runs(events: Sequence[Any]) -> list[dict[str, Any]]:
    """提取单会话事件流中一切非 completed 的 run.end 边界（保持 seq 升序）.

    Args:
        events: EventStore.read(sid) 返回的事件序列（Event.seq/.ts/.type/.payload）。

    Returns:
        [{"seq", "ts", "reason", "payload"}, ...]（seq 升序；completed/缺 reason 不收）。
    """
    out: list[dict[str, Any]] = []
    for ev in events:
        if getattr(ev, "type", "") != "run.end":
            continue
        payload = getattr(ev, "payload", None)
        if not isinstance(payload, dict):
            continue
        reason = str(payload.get("reason") or "")
        if not reason or reason == "completed":
            continue
        out.append(
            {
                "seq": int(getattr(ev, "seq", 0) or 0),
                "ts": str(getattr(ev, "ts", "") or ""),
                "reason": reason,
                "payload": payload,
            }
        )
    return out


def _digest_from_payload(reason: str, payload: dict[str, Any]) -> str:
    """尽最大努力从 run.end payload 恢复 error_digest（store 侧再统一截 200）.

    - cancelled → cancel_reason（"user_stop" 等；归因信息进 summary 一眼可见）；
    - 其余（llm_error/guard_blocked/…）→ answer_preview 中"原因: "行内容
      （如 "LLMHTTPError: HTTP 400: Bad Request | {...}"），缺该行用 preview 头。
    """
    if reason == "cancelled":
        return str(payload.get("cancel_reason") or "").strip()
    preview = str(payload.get("answer_preview") or "")
    for line in preview.splitlines():
        if line.startswith("原因: "):
            return line[len("原因: "):].strip()
    return preview.strip()


def backfill_truncated_runs(
    episode_store: Any,
    event_store: Any,
    session_ids: Sequence[str],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """对给定会话执行存量回填（幂等；可 dry_run 只报告不写）.

    Args:
        episode_store: 具有 index_truncated_run 的存储（鸭子引用，不 import memory 层）。
        event_store: 具有 read(sid) 的事件日志存储（跨段合并由其自身负责）。
        session_ids: 要回填的会话 ID 列表（由调用方枚举）。
        dry_run: True 时只统计不写行。

    Returns:
        {"sessions", "runs_seen", "written", "deduped", "would_write", "errors",
         "details": [{session_id, seen, written, deduped}, ...]}
    """
    if not hasattr(episode_store, "index_truncated_run"):
        raise TypeError("episode_store 缺少 index_truncated_run（非 B2 存储实现）")
    report: dict[str, Any] = {
        "sessions": 0,
        "runs_seen": 0,
        "written": 0,
        "deduped": 0,
        "would_write": 0,
        "errors": 0,
        "details": [],
    }
    for sid in session_ids:
        try:
            events = event_store.read(sid)
        except Exception:  # noqa: BLE001 — 单会话读取失败不阻断整体回填
            logger.warning("回填读事件日志失败（跳过）: sid=%s", sid, exc_info=True)
            report["errors"] += 1
            continue
        runs = collect_interrupted_runs(events)
        if not runs:
            continue
        detail: dict[str, Any] = {"session_id": sid, "seen": len(runs), "written": 0, "deduped": 0}
        report["sessions"] += 1
        for run in runs:
            report["runs_seen"] += 1
            payload = run["payload"]
            if dry_run:
                report["would_write"] += 1
                continue
            try:
                written = episode_store.index_truncated_run(
                    sid,
                    ts=run["ts"],
                    run_end_reason=run["reason"],
                    error_digest=_digest_from_payload(run["reason"], payload),
                    last_round=int(payload.get("rounds") or 0),
                    run_end_seq=int(run["seq"] or 0),
                )
            except Exception:  # noqa: BLE001 — 单行失败不阻断（幂等键可安全重跑）
                logger.warning(
                    "回填写行失败: sid=%s seq=%s", sid, run["seq"], exc_info=True
                )
                report["errors"] += 1
                continue
            if written:
                detail["written"] += 1
                report["written"] += 1
            else:
                detail["deduped"] += 1
                report["deduped"] += 1
        report["details"].append(detail)
    return report
