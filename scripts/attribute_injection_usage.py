#!/usr/bin/env python3
"""EVO-20260917-abdb3247 P1: A 级注入归因 + per-ref/per-surface 报告（只读，fail-open）.

A 级口径（DESIGN-20260917-knowledge-injection-layering §三.1）：
  注入 ref 字面出现在水合之后的 assistant tool args / 答案文本。
窗口策略：同一 session（ledger 行 session_id）+ 锚点（水合回执消息，ts 容差 ±5s）之后的消息。
已知低估：用而不引 ref 不计（报告如实标注；决策取保守方向，宁高估帮助不误杀）。
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path

ANCHOR_TOLERANCE_S = 5.0


def _day(ts: float) -> str:
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def load_ledger(path: str | Path) -> list[dict]:
    p = Path(path)
    rows: list[dict] = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def _find_session_file(sessions_dir: Path, sid: str) -> Path | None:
    if not sid:
        return None
    direct = sessions_dir / f"{sid}.json"
    if direct.exists():
        return direct
    for p in sessions_dir.rglob(f"{sid}.json"):
        return p
    return None


def _assistant_texts_after_anchor(messages: list[dict], anchor_ts: float) -> list[tuple[str, str]]:
    """锚点之后的 assistant 侧证据：("text", 正文/参数串) 或 ("skill_call", skill_load 参数串)."""
    out: list[tuple[str, str]] = []
    started = False
    for m in messages:
        try:
            ts = float(m.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if not started:
            if m.get("role") == "tool" and ts and ts >= anchor_ts - ANCHOR_TOLERANCE_S:
                started = True
            continue
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            name = str(fn.get("name") or "")
            args_str = str(fn.get("arguments") or "")
            if name == "skill_load":
                out.append(("skill_call", args_str))
            else:
                out.append(("text", args_str))
        out.append(("text", str(m.get("content") or "")))
    return out


def build_report(ledger_rows: list[dict], sessions_dir: str | Path) -> dict:
    sessions = Path(sessions_dir)
    hydration = [r for r in ledger_rows if r.get("kind") == "hydration"]
    receipt = [r for r in ledger_rows if r.get("kind") == "receipt_pointer"]

    events: list[dict] = []
    for r in hydration:
        refs = r.get("refs") if isinstance(r.get("refs"), list) else []
        # (display_ref, scope, match_str)：text 类字面匹配 ref 本体；
        # skill 类 display 带前缀，匹配用裸名对 skill_load 调用参数（防闲聊误报）
        cand = [(str(x)[:120], "text", str(x)[:120]) for x in refs if str(x).strip()]
        if not cand and r.get("skill"):
            cand = [(f"skill:{str(r['skill'])[:64]}", "skill_call", str(r["skill"])[:64])]
        events.append({
            "sid": str(r.get("session_id") or ""),
            "ts": float(r.get("ts") or 0),
            "cand": cand,
            "tool": str(r.get("tool") or ""),
            "row": r,
        })

    cache: dict[str, list[dict] | None] = {}

    def msgs_of(sid: str) -> list[dict] | None:
        if sid in cache:
            return cache[sid]
        f = _find_session_file(sessions, sid)
        if f is None:
            cache[sid] = None
            return None
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            cache[sid] = d.get("messages") or []
        except (OSError, json.JSONDecodeError):
            cache[sid] = None
        return cache[sid]

    per_ref: dict[str, dict] = {}
    by_day_h = collections.Counter()
    by_day_a = collections.Counter()
    attributed_events = 0
    windowed_events = 0

    def _entry(ref: str) -> dict:
        return per_ref.setdefault(
            ref, {"hydrations": 0, "attributed": 0, "tools": collections.Counter(), "last_day": ""}
        )

    for ev in events:
        day = _day(ev["ts"])
        if day:
            by_day_h[day] += 1
        for ref, _scope, _match in ev["cand"]:
            e = _entry(ref)
            e["hydrations"] += 1
            e["tools"][ev["tool"]] += 1
            if day and day > e["last_day"]:
                e["last_day"] = day
        msgs = msgs_of(ev["sid"]) if ev["sid"] else None
        if msgs is None or not ev["cand"]:
            continue  # 无 session 归属（旧格式行）或无候选 ref：计入 hydrations，不做 A 级
        windowed_events += 1
        evidences = _assistant_texts_after_anchor(msgs, ev["ts"])
        hit_any = False
        for ref, scope, match in ev["cand"]:
            pool = "\n".join(t for kind, t in evidences if kind == scope)
            if match and match in pool:
                _entry(ref)["attributed"] += 1
                hit_any = True
        if hit_any:
            attributed_events += 1
            if day:
                by_day_a[day] += 1

    surface = {
        "hydration_by_tool": dict(collections.Counter(str(r.get("tool", "-")) for r in hydration)),
        "hydration_by_record_kind": dict(
            collections.Counter(str(r.get("record_kind", "-")) for r in hydration if r.get("record_kind"))
        ),
        "hydration_by_skill": dict(
            collections.Counter(str(r.get("skill")) for r in hydration if r.get("skill"))
        ),
        "receipt_pointer_by_source": dict(
            collections.Counter(str(r.get("source", "-")) for r in receipt)
        ),
        "receipt_pointer_by_tool": dict(
            collections.Counter(str(r.get("tool", "-")) for r in receipt)
        ),
        "receipt_pointer_with_session": sum(1 for r in receipt if r.get("session_id")),
    }

    candidate_ref_events = sum(len(ev["cand"]) for ev in events)
    attributed_refs = sum(1 for e in per_ref.values() if e["attributed"] > 0)
    summary = {
        "ledger_rows": len(ledger_rows),
        "hydration_rows": len(hydration),
        "receipt_pointer_rows": len(receipt),
        "candidate_ref_events": candidate_ref_events,
        "windowed_events": windowed_events,
        "attributed_events": attributed_events,
        "distinct_refs": len(per_ref),
        "attributed_refs": attributed_refs,
        "a_rate_events": round(attributed_events / windowed_events, 4) if windowed_events else None,
    }
    return {
        "summary": summary,
        "per_ref": {
            ref: {**{k: v for k, v in e.items() if k != "tools"}, "tools": dict(e["tools"])}
            for ref, e in sorted(per_ref.items(), key=lambda kv: (-kv[1]["attributed"], -kv[1]["hydrations"]))
        },
        "surface": surface,
        "per_day": {"hydration": dict(sorted(by_day_h.items())), "attributed": dict(sorted(by_day_a.items()))},
        "window_policy": {
            "anchor": "tool receipt message ts (tolerance ±5s)",
            "scope": "same session (ledger row session_id); assistant tool_calls arguments + content after anchor",
            "known_undercount": "refs used without literal citation are not counted (A-level is a lower bound)",
        },
    }


def render_markdown(report: dict, *, ledger: str, top: int = 20) -> str:
    s = report["summary"]
    lines = [
        "# 注入使用归因报告（A 级机械归因）",
        "",
        f"- ledger: `{ledger}` | 生成: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"- 窗口: {report['window_policy']['scope']}",
        f"- 低估声明: {report['window_policy']['known_undercount']}",
        "",
        "## 摘要",
        "",
        f"- hydration 行: {s['hydration_rows']} | receipt_pointer 行: {s['receipt_pointer_rows']}",
        f"- 候选 ref 事件: {s['candidate_ref_events']} | 有窗口事件: {s['windowed_events']} | A 级命中事件: {s['attributed_events']}",
        f"- 命中率（事件口径）: {s['a_rate_events'] if s['a_rate_events'] is not None else 'n/a（无窗口事件）'}",
        f"- distinct ref: {s['distinct_refs']} | 至少命中一次: {s['attributed_refs']}",
        "",
        "## per-ref top",
        "",
        "| ref | hydrations | attributed | tools | last_day |",
        "|---|---|---|---|---|",
    ]
    for ref, e in list(report["per_ref"].items())[:top]:
        lines.append(f"| `{ref}` | {e['hydrations']} | {e['attributed']} | {','.join(e['tools'])} | {e['last_day']} |")
    lines += ["", "## surface 分布", ""]
    for k, v in report["surface"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## per-day", "", f"- hydration: {report['per_day']['hydration']}", f"- attributed: {report['per_day']['attributed']}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default="data/audit/injection_ledger.jsonl")
    ap.add_argument("--sessions-dir", default="data/sessions")
    ap.add_argument("--out-dir", default="data/audit")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    rows = load_ledger(args.ledger)
    report = build_report(rows, args.sessions_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "injection_attribution_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "injection_attribution_report.md").write_text(
        render_markdown(report, ledger=args.ledger, top=args.top), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"报告落盘: {out / 'injection_attribution_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
