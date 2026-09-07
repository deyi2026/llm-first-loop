#!/usr/bin/env python3
"""err1210 观测指标固定重算脚本（tasks 7.3；spec 5.4.1-3a"脚本随规格归档"）.

输入（新旧兼容）:
  <data-dir>/event_logs/**/*.jsonl        新 causal request.meta（优先；常态结构事实）
  <data-dir>/audit/payload_trace*.jsonl   历史/显式 deep-wire trace（兼容旧时期）
  <data-dir>/audit/exception_log.jsonl    （phase=llm_call, error_type=LLMHTTPError）
  <data-dir>/audit/defer_trace.jsonl      （五事件: stored/replayed/dropped/
                                          exhausted/lost_on_reinject）

重算四指标（spec 5.4.1-1a）:
  1. compact 首请求 1210 发生率 = 归因到 compact 首请求的 1210 数 / compact 首请求总数
     （基线 8/8=100%，附录 D.2）。compact 首请求识别 = 同会话相邻请求消息数骤降
     ≥30% 且 ≥8 条（spec 第 2 章术语，与 engine 辅助信号同口径）。
  2. P0 触发次数 = compact 首请求 1210 归因数（场景口径；P0 未上线时段由 --as-of 界定）。
  3. 重试成功率 = retry_success / retry_attempted；
     retry_attempted = 触发 − 无重试推断（无任何 defer 事件脚印的触发——剥离放弃/
     未上线/回存全败，均无重试）；retry_failed_1210 = defer_exhausted 事件数；
     retry_success = retry_attempted − retry_failed_1210。口径见模块内文档与报告
     caveats（defer 脚印成功但剥离放弃的边缘归入 success——如实披露）。
  4. defer 回放完整率 = defer_replayed / (defer_stored − defer_dropped)
     （spec 5.1.3-5d [r3-P2]）；defer_lost_on_reinject 单列不计入分子分母；
     未回放存量（含进程重启丢失候选，design 风险 3）单列不计入公式。

时区（spec 6.1/6.2）: EventStore/exception_log 为带偏移 ISO；payload_trace/defer_trace
为本地（Asia/Shanghai）；统一换算到本地 naive 比较，归因窗口 ±6 秒。
--as-of <ts>（[r3-P3] 时点过滤）: 三文件均只取 ≤as-of 的事件后重算——时点快照对账
（附录 D.1 统计时点 2026-08-27T20:01:20 本地 → 8/8=100% 可复算）；naive 视为本地。

用法:
  python scripts/err1210_metrics.py [--as-of 2026-08-27T20:01:20]
      [--data-dir <dir>] [--output <report.json>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# 固定重算语义: 解析逻辑自包含（镜像 llm/errors.parse_provider_error_code 两级策略），
# 不依赖运行时代码演变——脚本随规格归档（spec 5.4.1-3a"固定重算"）。
_CODE_RE = re.compile(r'"code"\s*:\s*"?(\d+)"?')


def _parse_provider_error_code(body: str) -> str | None:
    """从 LLMHTTPError.body/error_message 提取 provider 错误码（镜像 errors.py 语义）."""
    if not body:
        return None
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                code = err.get("code")
                if code is not None:
                    return str(code)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _CODE_RE.search(body)
    return m.group(1) if m else None


_LOCAL_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai（payload_trace 约定时区）
_ATTRIB_WINDOW_S = 6.0  # spec 6.1/6.2: ±6 秒归因窗口
_RETRY_FOOTPRINT_WINDOW_S = 10.0  # 触发 ↔ defer 事件脚印关联窗口
_SKIP_SESSIONS = {"__global__"}  # 守卫/后台通道干扰项（spec 6.2-2）


def _parse_as_of(ts: str | None) -> datetime | None:
    """--as-of 解析: aware → 转本地; naive → 视为本地（Asia/Shanghai）."""
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)


def _ex_local_naive(ts_iso: str) -> datetime:
    """exception_log ts（UTC aware）→ 本地 naive（+8）."""
    dt = datetime.fromisoformat(ts_iso)
    if dt.tzinfo is None:  # 防御: 无偏移按 UTC 处理
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)


def _local_naive(ts_str: str) -> datetime:
    """payload_trace/defer_trace ts（本地无偏移）."""
    return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")


def _event_local_naive(ts_iso: str) -> datetime:
    """EventStore ISO timestamp -> local naive for legacy metric correlation."""
    dt = datetime.fromisoformat(ts_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)


def _load_payload_rows(data_dir: Path, as_of: datetime | None) -> list[dict]:
    """payload_trace*.jsonl 通配聚合（活跃 + 历史分片，[r3-P1] 口径）."""
    audit = data_dir / "audit"
    rows: list[dict] = []
    for p in sorted(audit.glob("payload_trace*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "ts" not in row or "msgs" not in row:
                    continue
                row["_ts_local"] = _local_naive(row["ts"])
                row["_request_source"] = "payload_trace"
                if as_of is not None and row["_ts_local"] > as_of:
                    continue
                rows.append(row)
        except (OSError, json.JSONDecodeError, ValueError):
            continue  # 单文件损坏 fail-open（记录在案由调用方统计）
    rows.sort(key=lambda r: r["_ts_local"])
    return rows


def _load_causal_request_rows(data_dir: Path, as_of: datetime | None) -> list[dict]:
    """Load P1 causal primary request shape facts from EventStore files."""
    root = data_dir / "event_logs"
    rows: list[dict] = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.jsonl")):
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "request.meta":
                    continue
                payload = event.get("payload") or {}
                if not isinstance(payload.get("messages_count"), int):
                    # Pre-P1 request.meta lacks the exact structural count needed by this
                    # historical metric. Do not infer it from chars or unrelated fields.
                    continue
                ts = str(event.get("ts") or "")
                sid = str(event.get("session_id") or "")
                if not ts or not sid:
                    continue
                try:
                    local = _event_local_naive(ts)
                except (TypeError, ValueError):
                    continue
                if as_of is not None and local > as_of:
                    continue
                rows.append(
                    {
                        "ts": local.strftime("%Y-%m-%dT%H:%M:%S"),
                        "session_id": sid,
                        "provider": str(
                            (payload.get("generation_contract") or {}).get("provider") or ""
                        ),
                        "model": str(payload.get("model") or ""),
                        "messages_count": int(payload.get("messages_count") or 0),
                        "tail_user_run": int(payload.get("tail_user_run") or 0),
                        "_ts_local": local,
                        "_request_source": "causal_event",
                        "event_seq": int(event.get("seq", 0) or 0),
                    }
                )
    rows.sort(key=lambda row: row["_ts_local"])
    return rows


def _merge_request_rows(legacy: list[dict], causal: list[dict]) -> tuple[list[dict], int]:
    """Prefer causal rows per session once available; retain unrelated legacy history."""
    if not causal:
        return list(legacy), len(legacy)
    first_causal_by_session: dict[str, datetime] = {}
    for row in causal:
        sid = str(row.get("session_id") or "")
        current = first_causal_by_session.get(sid)
        ts = row["_ts_local"]
        if current is None or ts < current:
            first_causal_by_session[sid] = ts
    legacy_history = []
    for row in legacy:
        sid = str(row.get("session_id") or "")
        cutoff = first_causal_by_session.get(sid)
        # Legacy deep trace has second precision; EventStore has microseconds.
        # Treat the first causal second as authoritative to avoid transition duplicates.
        cutoff_second = cutoff.replace(microsecond=0) if cutoff is not None else None
        if cutoff_second is None or row["_ts_local"] < cutoff_second:
            legacy_history.append(row)
    rows = legacy_history + list(causal)
    rows.sort(key=lambda row: row["_ts_local"])
    return rows, len(legacy_history)


def _row_message_count(row: dict) -> int:
    count = row.get("messages_count")
    if isinstance(count, int):
        return count
    return len(row.get("msgs") or [])


def _row_tail_user_run(row: dict) -> int:
    value = row.get("tail_user_run")
    if isinstance(value, int):
        return value
    n = 0
    for message in reversed(row.get("msgs") or []):
        if message.get("role") != "user":
            break
        n += 1
    return n



def _load_exceptions(data_dir: Path, as_of: datetime | None) -> list[dict]:
    """exception_log.jsonl 中 code=1210 的 LLMHTTPError 记录（UTC → 本地）. """
    audit = data_dir / "audit"
    out: list[dict] = []
    p = audit / "exception_log.jsonl"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("error_type") != "LLMHTTPError":
            continue
        if _parse_provider_error_code(row.get("error_message") or "") != "1210":
            continue
        local = _ex_local_naive(row["ts"])
        if as_of is not None and local > as_of:
            continue
        row["_local"] = local
        out.append(row)
    return out


def _load_defer_rows(data_dir: Path, as_of: datetime | None) -> list[dict]:
    audit = data_dir / "audit"
    out: list[dict] = []
    p = audit / "defer_trace.jsonl"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "ts" not in row or "event" not in row:
            continue
        try:
            row["_local"] = _local_naive(row["ts"])
        except ValueError:
            continue
        if as_of is not None and row["_local"] > as_of:
            continue
        out.append(row)
    return out


def _aggregated_tail_user(payload_rows: list[dict]) -> dict:
    """P1 聚合观测（verdict_p1 B-3）: 尾部连续 user 重算（与指纹 _tail_digest 同口径）.

    aggregated_tail_user_max: 全轮次尾部连续 user 条数最大值（聚合目标 ≤1）
    aggregated_tail_user_fallback_rounds: 尾部连续 user >1 的轮计数（聚合未生效/fail-safe 回退）
    无 trace 数据（payload_rows 空）→ 两键 None（fail-open，不阻断其余指标）。
    """
    if not payload_rows:
        return {"aggregated_tail_user_max": None, "aggregated_tail_user_fallback_rounds": None}
    max_tail = 0
    fallback = 0
    for row in payload_rows:
        n = _row_tail_user_run(row)
        max_tail = max(max_tail, n)
        if n > 1:
            fallback += 1
    return {"aggregated_tail_user_max": max_tail, "aggregated_tail_user_fallback_rounds": fallback}


def _compact_first_rows(rows: list[dict]) -> list[dict]:
    """同会话相邻请求消息数骤降（≥30% 且 ≥8 条）→ compact 首请求（spec 术语）."""
    by_sess: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        sid: str = str(r.get("session_id") or "")
        if sid in _SKIP_SESSIONS:
            continue
        by_sess[sid].append(r)
    out: list[dict] = []
    for sid, srows in by_sess.items():
        prev_n: int | None = None
        for r in srows:
            n = _row_message_count(r)
            if prev_n is not None:
                drop = prev_n - n
                if drop >= 8 and drop >= prev_n * 0.30:
                    out.append(
                        {
                            "ts": r["ts"],
                            "session_id": sid,
                            "prev_n": prev_n,
                            "n": n,
                            "drop_pct": round(drop / prev_n * 100, 1),
                        }
                    )
            prev_n = n
    return out


def _attribute_1210(excs: list[dict], rows: list[dict], cf_rows: list[dict]) -> dict:
    """±6s 窗口归因: 1210 → compact 首请求/普通请求/不可归因（spec 6.1/6.2）."""
    cf_set = {(r["session_id"], r["ts"]) for r in cf_rows}
    attributed_cf: list[dict] = []
    attributed_plain: list[dict] = []
    unattributed: list[dict] = []
    for e in excs:
        cands = [
            r
            for r in rows
            if r.get("session_id") not in _SKIP_SESSIONS
            and abs((r["_ts_local"] - e["_local"]).total_seconds()) <= _ATTRIB_WINDOW_S
        ]
        cf_cands = [r for r in cands if (r["session_id"], r["ts"]) in cf_set]
        if cf_cands:
            r = cf_cands[0]
            attributed_cf.append(
                {
                    "ts": r["ts"],  # payload_trace 本地秒级 ts（归因锚点）
                    "exc_ts": e["ts"],  # exception_log UTC ts
                    "local_ts": e["_local"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "session_id": r["session_id"],
                    "n": _row_message_count(r),
                }
            )
        elif cands:
            r = cands[0]
            attributed_plain.append(
                {
                    "ts": r["ts"],
                    "exc_ts": e["ts"],
                    "local_ts": e["_local"].strftime("%Y-%m-%dT%H:%M:%S"),
                    "session_id": r["session_id"],
                    "n": _row_message_count(r),
                }
            )
        else:
            unattributed.append(
                {
                    "ts": e["ts"],
                    "local_ts": e["_local"].strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
    return {
        "attributed_cf": attributed_cf,
        "attributed_plain": attributed_plain,
        "unattributed": unattributed,
    }


def _retry_ledger(triggers: list[dict], defer_rows: list[dict]) -> dict:
    """重试成功率口径（三文件可观测集合，caveats 如实披露）.

    - 无重试推断 A: 触发在 ±10s 窗口内无任何 defer 事件脚印（P0 未上线/剥离放弃/
      defer 回存全败——后两者无重试；未上线亦无重试，推断口径保守一致）。
    - E: 有 defer_exhausted 脚印 → 重试仍 1210（明确失败）。
    - retry_success = (T − A) − E（defer 脚印成功但剥离放弃的边缘归入 success——
      三文件不可区分，报告 caveats 声明）。
    """
    triggers_by_sess = defaultdict(list)
    for t in triggers:
        triggers_by_sess[t["session_id"]].append(t)
    by_sess_event: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in defer_rows:
        by_sess_event[(d.get("session_id", ""), d.get("event", ""))].append(d)

    exhausted_sessions: set[tuple[str, str]] = set()
    for t in triggers:
        for d in by_sess_event.get((t["session_id"], "defer_exhausted"), []):
            if abs((d["_local"] - _local_naive(t["ts"])).total_seconds()) <= _RETRY_FOOTPRINT_WINDOW_S:
                exhausted_sessions.add((t["session_id"], t["ts"]))
                break
    no_retry = [
        t
        for t in triggers
        if (t["session_id"], t["ts"]) not in exhausted_sessions
        and not any(
            abs((d["_local"] - _local_naive(t["ts"])).total_seconds()) <= _RETRY_FOOTPRINT_WINDOW_S
            for d in defer_rows
            if d.get("session_id") == t["session_id"]
        )
    ]
    attempted = len(triggers) - len(no_retry)
    failed_1210 = len(exhausted_sessions)
    success = max(0, attempted - failed_1210)
    return {
        "triggers": len(triggers),
        "no_retry_inferred": len(no_retry),
        "retry_attempted": attempted,
        "retry_failed_1210": failed_1210,
        "retry_success": success,
        "retry_success_rate": round(success / attempted, 4) if attempted else None,
    }


def _defer_ledger(defer_rows: list[dict]) -> dict:
    """defer 回放完整率（spec 5.1.3-5d）+ 单列观测项."""
    counts: dict[str, int] = defaultdict(int)
    per_slot: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"defer_stored": 0, "defer_dropped": 0, "defer_replayed": 0}
    )
    for d in defer_rows:
        ev = d.get("event", "")
        slot = str(d.get("slot_kind", ""))
        payload = d.get("payload") or {}
        try:
            c = int(payload.get("count") or 1)
        except (TypeError, ValueError):
            c = 1
        counts[ev] += c
        if ev in ("defer_stored", "defer_dropped", "defer_replayed"):
            per_slot[(d.get("session_id", ""), slot)][ev] += c
    stored = counts["defer_stored"]
    dropped = counts["defer_dropped"]
    replayed = counts["defer_replayed"]
    denom = stored - dropped
    unreplayed = [
        {
            "session_id": sid,
            "slot_kind": slot,
            "unreplayed": max(
                0, v["defer_stored"] - v["defer_dropped"] - v["defer_replayed"]
            ),
        }
        for (sid, slot), v in per_slot.items()
        if v["defer_stored"] - v["defer_dropped"] - v["defer_replayed"] > 0
    ]
    return {
        "defer_stored_count": stored,
        "defer_dropped_count": dropped,
        "defer_replayed_count": replayed,
        "defer_replay_completeness": round(replayed / denom, 4) if denom > 0 else None,
        "defer_exhausted_count": counts["defer_exhausted"],
        "defer_lost_on_reinject_count": counts["defer_lost_on_reinject"],
        "defer_unreplayed_candidates": unreplayed,  # 含进程重启丢失候选，单列不计入公式
    }


def _action_trace_cross_check(data_dir: Path) -> dict | None:
    """可选交叉核对（非输入契约文件）: err1210.recovery 动作留痕（recovered/exhausted/
    aborted/retry_error）——三文件口径的独立验证源."""
    p = data_dir / "audit" / "action_trace.jsonl"
    if not p.exists():
        return None
    out = defaultdict(int)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("phase") == "err1210.recovery":
            out[row.get("action_type", "?")] += 1
    return dict(out)


def compute_metrics(data_dir: str | Path, as_of: str | None = None) -> dict:
    """四指标固定重算（输出验收报告 JSON 结构）."""
    base = Path(data_dir)
    as_of_dt = _parse_as_of(as_of)
    payload_rows = _load_payload_rows(base, as_of_dt)
    causal_rows = _load_causal_request_rows(base, as_of_dt)
    request_rows, legacy_rows_used = _merge_request_rows(payload_rows, causal_rows)
    excs = _load_exceptions(base, as_of_dt)
    defer_rows = _load_defer_rows(base, as_of_dt)
    cf_rows = _compact_first_rows(request_rows)
    attrib = _attribute_1210(excs, request_rows, cf_rows)
    triggers = attrib["attributed_cf"]
    retry = _retry_ledger(triggers, defer_rows)
    defer = _defer_ledger(defer_rows)
    cf_total = len(cf_rows)
    cf_1210 = len(triggers)
    agg = _aggregated_tail_user(request_rows)

    report = {
        "schema": "err1210_metrics_v1.1",
        "as_of": as_of or None,
        "generated_at": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone_note": "EventStore/exception_log 按 ISO offset→本地；payload_trace/defer_trace 本地；归因窗口±6s",
        "inputs": {
            "exception_log": {"rows_1210": len(excs), "unattributable": len(attrib["unattributed"])},
            "payload_trace_files": [str(p.relative_to(base)) for p in sorted((base / "audit").glob("payload_trace*.jsonl"))],
            "payload_trace_rows": len(payload_rows),
            "causal_request_rows": len(causal_rows),
            "legacy_payload_rows_used": legacy_rows_used,
            "request_rows_total": len(request_rows),
            "request_source_mode": (
                "hybrid" if causal_rows and legacy_rows_used else "causal" if causal_rows else "legacy"
            ),
            "defer_trace_rows": len(defer_rows),
        },
        "metrics": {
            # 1. compact 首请求 1210 发生率（基线 8/8=100%，附录 D.2）
            "compact_first_total": cf_total,
            "compact_first_1210_count": cf_1210,
            "compact_first_1210_rate": round(cf_1210 / cf_total, 4) if cf_total else None,
            # v1.1: 率值结构体（分子分母可复核）；裸数值键保留（既有消费者/测试零回归）
            "compact_first_1210_rate_detail": {
                "numerator": cf_1210,
                "denominator": cf_total,
                "rate": round(cf_1210 / cf_total, 4) if cf_total else None,
            },
            # 2. P0 触发次数（场景口径）
            "p0_trigger_count": cf_1210,
            # 3. 重试成功率
            **retry,
            # 4. defer 回放完整率（[r3-P2] 口径）
            **defer,
            # 5-6. P1 聚合观测（verdict_p1 B-3）。上线后验收口径: max ≤1 且
            # compact_first_1210_rate=0，观察期 ≥7 天且 compact 轮 ≥20（promotion 后生效）
            **agg,
        },
        "details": {
            "compact_first_rows": cf_rows,
            "attributed_1210_plain": attrib["attributed_plain"],
            "unattributed_1210": attrib["unattributed"],
            "caveats": [
                "P0 触发次数为场景口径（compact 首请求 1210 归因数）；P0 未上线时段的触发由 --as-of 界定",
                "重试成功率三文件口径: 无 defer 事件脚印的触发推断为无重试（P0 未上线/剥离放弃/defer 全败）",
                "defer 脚印存在但剥离放弃的边缘归入 retry_success（三文件不可区分，如实披露）",
                "defer_unreplayed_candidates 为未回放存量（含进程重启丢失候选），单列不计入分子分母（design 风险 3）",
                "defer_lost_on_reinject 单列观测不计入分子分母（spec 5.1.3-5d）",
                "P1 起优先使用 causal request.meta 的 messages_count/tail_user_run；payload_trace 仅保留早于首条 causal shape 记录的历史段，避免双计",
            ],
        },
    }
    cross = _action_trace_cross_check(base)
    if cross is not None:
        report["details"]["cross_check_action_trace"] = cross
    return report


def render_summary(report: dict) -> str:
    m = report["metrics"]
    lines = [
        "err1210 观测指标重算",
        f"  时点过滤: {report['as_of'] or '（无——全量）'}  生成: {report['generated_at']}",
        f"  输入: exception 1210={report['inputs']['exception_log']['rows_1210']} 条"
        f"（不可归因 {report['inputs']['exception_log']['unattributable']}） | payload_trace "
        f"{report['inputs']['payload_trace_rows']} 行 / {len(report['inputs']['payload_trace_files'])} 文件"
        f" | defer_trace {report['inputs']['defer_trace_rows']} 行",
        "  ── 四指标 ──",
        f"  ① compact 首请求 1210 发生率: {m['compact_first_1210_count']}/{m['compact_first_total']}"
        f" = {m['compact_first_1210_rate'] if m['compact_first_1210_rate'] is not None else 'n/a'}",
        f"  ② P0 触发次数: {m['p0_trigger_count']}",
        f"  ③ 重试成功率: {m['retry_success']}/{m['retry_attempted']}"
        f"（{m['retry_success_rate'] if m['retry_success_rate'] is not None else 'n/a'}）"
        f"  失败1210={m['retry_failed_1210']} 无重试推断={m['no_retry_inferred']}",
        f"  ④ defer 回放完整率: {m['defer_replayed_count']}/"
        f"({m['defer_stored_count']}-{m['defer_dropped_count']})"
        f" = {m['defer_replay_completeness'] if m['defer_replay_completeness'] is not None else 'n/a'}",
        f"     单列: lost_on_reinject={m['defer_lost_on_reinject_count']} "
        f"未回放候选={len(m['defer_unreplayed_candidates'])}",
        f"  ⑤ P1 聚合尾部 user 最大值: {m.get('aggregated_tail_user_max', 'n/a')}（目标 ≤1）",
        f"  ⑥ 聚合回退轮计数: {m.get('aggregated_tail_user_fallback_rounds', 'n/a')}"
        f"  率值结构: {m.get('compact_first_1210_rate_detail')}",
    ]
    if "cross_check_action_trace" in report["details"]:
        cc = report["details"]["cross_check_action_trace"]
        lines.append(
            "  交叉核对 action_trace(err1210.recovery): "
            + ", ".join(f"{k}={v}" for k, v in sorted(cc.items()))
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="err1210_metrics", description="err1210 四指标固定重算（spec 5.4.1-3a）"
    )
    p.add_argument(
        "--as-of",
        default="",
        help="时点过滤（ISO；naive 视为本地 Asia/Shanghai）——附录 D.1 统计时点快照对账",
    )
    p.add_argument(
        "--data-dir", default=os.environ.get("LFL_DATA_DIR", "data"), help="审计数据根目录"
    )
    p.add_argument("--output", default="", help="验收报告 JSON 归档路径（可选）")
    args = p.parse_args(argv)
    report = compute_metrics(args.data_dir, args.as_of or None)
    print(render_summary(report))
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"验收报告 JSON: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
