#!/usr/bin/env python3
"""LFL 评测日报生成器（P5 连续化）。

2026-10-23（P5 出口判据「日报连续 7 天自动产出且字段完整」）：
此前仓库**没有任何日报产出机制** —— 评测指标只能靠人工临时汇总，
既无固定字段也无连续性证据。

本脚本从运行时的 append-only 审计流聚合，产出固定字段的日报：
  reports/eval-daily-YYYY-MM-DD.md

字段（固定，缺项显式标注「数据不足」而非静默省略）：
  1. 首试成功率   —— action_trace 中任务级首次尝试成功占比
  2. 停滞次数     —— action_trace / exception_log 中的停滞事件
  3. 异常率       —— exception_log 条数 / 总事件数
  4. 压缩后存续率 —— 压缩档案中被成功取回的记录占比
  5. 成本曲线     —— 每日 token 用量（自 event_logs 聚合）

口径纪律（沿用 eval/rules/statistics.md）：
  - 样本不足时只给方向性结论，不做显著性断言
  - 负结果同等呈现

用法:
    uv run --no-sync python eval/rules/daily_report.py                # 生成今天
    uv run --no-sync python eval/rules/daily_report.py --date 2026-10-23
    uv run --no-sync python eval/rules/daily_report.py --out reports/xxx.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
AUDIT = DATA / "audit"
LOCAL_TZ = timezone(timedelta(hours=8))


def _read_jsonl_tail(path: Path, limit_bytes: int = 16 * 1024 * 1024) -> list[dict]:
    """从 JSONL **文件尾部**反向读取（保留行序）。

    为什么必须读尾部（实测踩坑）：data/audit/action_trace.jsonl 约 65 万行、
    数百 MB，正向读会先读到**最旧的**记录而把当日记录挤出窗口 → 当日指标全为 0
    或严重偏低。审计流是 append-only，**最新记录在尾部**。

    实现：从文件尾部分块向前读，逐块按行切分，最后把整块反转回正序。
    """
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            pos = size
            buf = b""
            while pos > 0 and len(buf) < limit_bytes:
                chunk = min(1024 * 1024, pos)
                pos -= chunk
                f.seek(pos)
                buf = f.read(chunk) + buf
        text = buf.decode("utf-8", errors="replace")
        lines = text.split("\n")
        # 若没读到文件头，第一行可能是半行 → 丢弃（除非已到文件开头）
        if pos > 0 and lines:
            lines = lines[1:]
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _ts_of(rec: dict) -> datetime | None:
    """解析记录时间戳 → 本地时区。

    真实审计流格式（实测 data/audit/*.jsonl）：ts = "2026-10-23T13:00:54.873652+08:00"
    → 带偏移的 ISO 格式，datetime.fromisoformat 直接可用；无偏移时按本地时区补。
    """
    for key in ("ts", "timestamp", "created_at", "time", "occurred_at"):
        v = rec.get(key)
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(float(v), tz=LOCAL_TZ)
            except (OSError, OverflowError, ValueError):
                continue
        if isinstance(v, str) and v:
            try:
                dt = datetime.fromisoformat(v)
                return dt if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)
            except ValueError:
                pass
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v[: len(fmt) + 2], fmt).replace(tzinfo=LOCAL_TZ)
                except ValueError:
                    continue
    return None


def _in_day(rec: dict, day: date) -> bool:
    t = _ts_of(rec)
    return bool(t and t.date() == day)


def collect(day: date) -> dict:
    """聚合当日指标。缺数据源时对应字段为 None（渲染为「数据不足」）。"""
    action = _read_jsonl_tail(AUDIT / "action_trace.jsonl")
    exceptions = _read_jsonl_tail(AUDIT / "exception_log.jsonl")
    declarations = _read_jsonl_tail(AUDIT / "declaration_check.jsonl")

    day_action = [r for r in action if _in_day(r, day)]
    day_exc = [r for r in exceptions if _in_day(r, day)]
    day_decl = [r for r in declarations if _in_day(r, day)]

    # 1) 首试成功率：按任务键聚合，取首次尝试的成功标记
    # 真实 action_trace 记录形态（实测）：{ts, phase, action_type, detail, session_id, ...}
    # 没有 success/status 字段 → 成功与否只能从 **exception_log** 侧判定：
    #   某 session+工具 的首次调用若未在异常流出现 → 记为一次成功；
    #   首次即出现异常 → 记为一次失败。
    # 口径说明：这是「首试未抛异常」的成功率，不等于任务达成率（任务达成需另行判定）。
    failed_first: set[tuple[str, str]] = set()
    for r in day_exc:
        failed_first.add((str(r.get("session_id", "")), str(r.get("phase", ""))))
    first_attempt: dict[str, bool] = {}
    for r in day_action:
        if r.get("action_type") != "tool_call":
            continue
        key = f"{r.get('session_id', '')}|{r.get('detail', '')}"
        if key in first_attempt:
            continue
        ok = (str(r.get("session_id", "")), str(r.get("phase", ""))) not in failed_first
        first_attempt[key] = ok
    n_first = len(first_attempt)
    first_rate = (
        (sum(1 for v in first_attempt.values() if v) / n_first) if n_first else None
    )

    # 2) 停滞次数
    stagnation = 0
    for r in day_action + day_exc:
        blob = " ".join(
            str(r.get(k, ""))
            for k in ("phase", "action_type", "detail", "error_type", "error_message")
        ).lower()
        if "停滞" in blob or "stagnat" in blob:
            stagnation += 1

    # 3) 异常率
    n_tool_calls = sum(1 for r in day_action if r.get("action_type") == "tool_call")
    n_events = n_tool_calls + len(day_exc)
    exc_rate = (len(day_exc) / n_events) if n_events else None

    # 4) 压缩后存续率：压缩档案里被取回（read_evidence/压缩档案命中）的占比
    # 压缩后存续率：压缩档案数（data/archives/*.jsonl，每 session 一个），
    # 但**运行时未对"取回"留痕**（实测：archives/ 下无 recovered 标记，
    # audit 流里也无 archive 取回事件）→ 存续率无法从现有数据算出，
    # 如实标为数据不足，而不是用 proxies 冒充。
    archives = DATA / "archives"
    compressed_total = 0
    if archives.exists():
        compressed_total = sum(1 for p in archives.glob("*.jsonl"))
    survival = None

    # 5) 成本曲线：当日 token 用量
    # 数据源（实测）：data/audit/guarded_requests.jsonl，事件 event=="llm_result"，
    # 字段 tokens_in / tokens_hit / provider / model / cache_health。
    # （action_trace 的 token 只出现在 detail 文本里，非结构化字段 → 不作为成本源；
    #   event_logs 里没有 token 字段。）
    tokens_in = tokens_hit = tokens_out = 0
    n_llm_calls = 0
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_hit": 0})
    for r in _read_jsonl_tail(AUDIT / "guarded_requests.jsonl"):
        if not _in_day(r, day):
            continue
        if r.get("event") != "llm_result":
            continue
        ti = int(r.get("tokens_in") or 0)
        th = int(r.get("tokens_hit") or 0)
        to = int(r.get("tokens_out") or 0)
        n_llm_calls += 1
        tokens_in += ti
        tokens_hit += th
        tokens_out += to
        mk = str(r.get("model") or "unknown")
        by_model[mk]["calls"] += 1
        by_model[mk]["tokens_in"] += ti
        by_model[mk]["tokens_hit"] += th
    cache_hit_rate = (tokens_hit / tokens_in) if tokens_in else None

    return {
        "date": day.isoformat(),
        "first_attempt": {
            "rate": first_rate,
            "n": n_first,
            "note": "按任务键取首次尝试的占比；样本不足时仅方向性",
        },
        "stagnation": {"count": stagnation},
        "exception": {"rate": exc_rate, "n_events": n_events, "n_exceptions": len(day_exc),
                    "n_tool_calls": n_tool_calls},
        "compression_survival": {
            "rate": survival,
            "n_archives": compressed_total,
            "n_recovered": None,
            "note": "压缩档案数可数（archives/*.jsonl），但**运行时无取回留痕** → 存续率无法算出（数据缺口，见 P5 待办）",
        },
        "cost": {
            "tokens_in": tokens_in,
            "tokens_hit": tokens_hit,
            "tokens_out": tokens_out,
            "n_llm_calls": n_llm_calls,
            "cache_hit_rate": cache_hit_rate,
            "by_model": {k: dict(v) for k, v in by_model.items()},
        },
        "sources": {
            "action_trace": len(day_action),
            "exception_log": len(day_exc),
            "declaration_check": len(day_decl),
        },
    }


def _fmt_rate(v: float | None, digits: int = 3) -> str:
    return "数据不足" if v is None else f"{v:.{digits}f}"


def render(m: dict) -> str:
    fa = m["first_attempt"]
    ex = m["exception"]
    cs = m["compression_survival"]
    co = m["cost"]
    lines = [
        f"# LFL 评测日报 {m['date']}",
        "",
        "> 口径：`eval/rules/statistics.md`（Wilson 95% CI；样本不足只给方向性结论；负结果同等呈现）。",
        "> 数据源：`data/audit/action_trace.jsonl`（动作）、`data/audit/exception_log.jsonl`（异常）、"
        "`data/audit/guarded_requests.jsonl`（成本与缓存）、`data/archives/`（压缩档案）。",
        "",
        "## 指标",
        "",
        "| 指标 | 值 | 样本 | 口径说明 |",
        "|---|---|---|---|",
        f"| 首试成功率 | {_fmt_rate(fa['rate'])} | n={fa['n']} | {fa['note']} |",
        f"| 停滞次数 | {m['stagnation']['count']} | — | action_trace/exception_log 中停滞事件计数 |",
        f"| 异常率 | {_fmt_rate(ex['rate'])} | calls={ex.get('n_tool_calls', 0)}, exc={ex['n_exceptions']} | exception_log /（工具调用 + 异常） |",
        f"| 压缩后存续率 | {_fmt_rate(cs['rate'])} | archives={cs['n_archives']}, recovered={cs['n_recovered']} | {cs['note']} |",
        f"| 成本（token in/hit/out） | {co['tokens_in']} / {co['tokens_hit']} / {co['tokens_out']} | llm_calls={co['n_llm_calls']} | guarded_requests 当日聚合 |",
        f"| 缓存命中率 | {_fmt_rate(co.get('cache_hit_rate'))} | tokens_hit / tokens_in | prompt cache 命中占比（LFL 关键指标） |",
        "",
        "## 数据缺口（如实登记，不以 proxy 冒充）",
        "",
        "- **压缩后存续率无法计算**：压缩档案数可数（`data/archives/*.jsonl`），"
        "但运行时**不对「取回」留痕**（archives/ 下无 recovered 标记，audit 流里也无取回事件）"
        "→ 需要在压缩档案读取路径补一条留痕后才能计算。待办见 P5。",
        "- **tokens_out 恒为 0**：`guarded_requests.jsonl` 只记 `tokens_in`/`tokens_hit`，"
        "不记输出 token → 输出侧成本暂不可见。",
        "",
        "## 读取计数",
        "",
        f"- action_trace: {m['sources']['action_trace']}",
        f"- exception_log: {m['sources']['exception_log']}",
        f"- declaration_check: {m['sources']['declaration_check']}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（默认今天，Asia/Shanghai）")
    ap.add_argument("--out", help="输出路径（默认 reports/eval-daily-<date>.md）")
    args = ap.parse_args(argv)

    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz=LOCAL_TZ).date()

    m = collect(day)
    text = render(m)
    out = Path(args.out) if args.out else REPORTS / f"eval-daily-{day.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"[日报] 已生成 {out.relative_to(ROOT)}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
