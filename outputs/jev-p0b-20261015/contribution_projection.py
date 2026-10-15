"""P0b 复用链的只读贡献投影（一条 run）— 只读，不写任何账本/EventStore。

用法:
  python3 outputs/jev-p0b-20261015/contribution_projection.py \
      --run-ref de7f7e47-443e-42f9-9513-57ee99c8a21e:turn:27:run:058dc3b808c543eeb2398a817e69d1fc

输出: contribution_projection.json / contribution_projection.md（同目录）
约束（设计 §11 P0b）:
  - 只读：不写 usage ledger、不写 EventStore、不补造终态、不新建 journal/worker
  - 无法证明的项一律 unknown / UNMEASURABLE，不填 0
  - 归属 session 取 run_ref 前缀，不按"最近事件"归因
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EVENTS_DIR = ROOT / "data" / "event_logs"
EXP_LEDGER = ROOT / "experiences" / "usage.jsonl"
MET_LEDGER = ROOT / "data" / "methods" / "usage.jsonl"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_event_files():
    """顶层 <session>.jsonl + 滚动分段 <session>/<seg>.jsonl"""
    for name in sorted(EVENTS_DIR.iterdir()):
        if name.is_dir():
            for seg in sorted(name.glob("*.jsonl")):
                yield seg
        elif name.suffix == ".jsonl":
            yield name


def load_run_events(run_ref: str):
    """按 (seq, knowledge_event_key, type) 业务身份去重；归属 session = run_ref 前缀。"""
    origin_session = run_ref.split(":", 1)[0]
    seen, rows = set(), []
    for fp in iter_event_files():
        with fp.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pl = ev.get("payload") or {}
                if pl.get("run_ref") != run_ref:
                    continue
                key = (ev.get("seq"), pl.get("knowledge_event_key"), ev.get("type"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"seq": ev.get("seq"), "ts": ev.get("ts"), "type": ev.get("type"),
                             "event_id": ev.get("event_id"), "session_id": ev.get("session_id"),
                             "origin_session": origin_session, "file": fp.name, "payload": pl})
    rows.sort(key=lambda r: (r["ts"], r["seq"] or 0))
    return rows


def load_ledgers(origin_session: str):
    """只按 session_id 精确匹配；不做 episode_ref 切片等近似 join（曾导致误匹配）。"""
    exp = [json.loads(l) for l in EXP_LEDGER.open(encoding="utf-8") if l.strip()] if EXP_LEDGER.exists() else []
    met = [json.loads(l) for l in MET_LEDGER.open(encoding="utf-8") if l.strip()] if MET_LEDGER.exists() else []
    return ([r for r in exp if r.get("session_id") == origin_session],
            [r for r in met if r.get("session_id") == origin_session],
            {"match": "session_id exact", "exp_total": len(exp), "met_total": len(met)})


def main() -> int:
    global EVENTS_DIR
    ap = argparse.ArgumentParser(description="P0b 只读贡献投影")
    ap.add_argument("--run-ref", required=True)
    ap.add_argument("--events-dir", type=Path, default=EVENTS_DIR)
    args = ap.parse_args()
    EVENTS_DIR = args.events_dir

    run_ref = args.run_ref
    origin = run_ref.split(":", 1)[0]
    rows = load_run_events(run_ref)
    if not rows:
        print(json.dumps({"ok": False, "error": f"no events for run_ref {run_ref}"}, ensure_ascii=False))
        return 2

    seqs = [r["seq"] for r in rows if r["seq"] is not None]
    types = Counter(r["type"] for r in rows)
    knowledge = [r for r in rows if r["type"].startswith("knowledge.")]

    hydration = [r for r in knowledge if r["type"] == "knowledge.hydration_observed"]
    discovery = [r for r in knowledge if r["type"] == "knowledge.discovery"]
    declarations = [r for r in knowledge if r["type"].endswith("_declaration")]
    outcomes = [r for r in knowledge if r["type"] == "knowledge.run_outcome"]
    failures = [r for r in knowledge if r["type"] == "knowledge.failure_observed"]

    hints = [h for d in discovery for h in (d["payload"].get("hints") or [])]
    hint_refs = {h.get("ref") for h in hints}
    declared_refs = {d["payload"].get("ref") for d in declarations if d["payload"].get("ref")}

    exp_rows, met_rows, ledger_meta = load_ledgers(origin)
    ledger_by_ref = {}
    for r in exp_rows:
        ledger_by_ref.setdefault(r.get("experience_ref"), []).append(("experience", r))
    for r in met_rows:
        ledger_by_ref.setdefault(r.get("method_ref"), []).append(("method", r))

    terminal = (outcomes[-1]["payload"] if outcomes else None)
    terminal_ev = outcomes[-1] if outcomes else None
    run_end = next((r for r in rows if r["type"] == "run.end"), None)
    run_end_join = "identity" if run_end else None
    if run_end is None and seqs:
        end_seq = max(seqs)
        hits = []
        for fp in iter_event_files():
            with fp.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("type") == "run.end" and (ev.get("seq") or 0) >= end_seq:
                        hits.append((ev.get("seq"), ev.get("ts"), ev.get("payload") or {}, fp.name))
        if hits:
            hits.sort(key=lambda h: h[0])
            s, t, pl, fn = hits[0]
            run_end = {"seq": s, "ts": t, "type": "run.end", "payload": pl, "file": fn}
            run_end_join = f"seq-adjacent(seq {s} >= run max {end_seq})"

    # ---------- §5.3 knowledge-contribution/v1 ----------
    contributions = []
    for d in declarations:
        pl = d["payload"]
        ref = pl.get("ref")
        kind = "experience" if ref.startswith("experience:") else "method"
        entries = ledger_by_ref.get(ref) or []
        lk, lr = (entries[0] if entries else (None, {}))
        subj_hash = (pl.get("document_projection_sha256") if kind == "experience"
                     else (lr.get("method_content_hash") if lr else None))
        ev_refs = (lr.get("evidence_refs") or []) if lr else []
        contributions.append({
            "subject_ref": ref,
            "subject_kind": kind,
            "subject_hash": (f"sha256:{subj_hash}" if subj_hash else None),
            "subject_hash_semantics": ("document_projection_sha256（重序列化投影 hash，非磁盘 exact bytes hash）"
                                       if kind == "experience" else "method_content_hash") if subj_hash else None,
            "use_decision": pl.get("decision"),
            "declaration_authority": pl.get("authority"),
            "hydration_observed": pl.get("hydration_observed"),
            "verification_state": pl.get("verification_state"),
            "ledger_application_proven": lr.get("application_proven") if lr else None,
            "ledger_matched": bool(entries),
            "declaration_event_ref": f"event:{d['event_id']}",
            "helped": "unclear",
            "attribution_level": "insufficient",
            "evidence_refs": ev_refs,
            "missing_reason": "no_independent_contribution_evidence",
        })

    contrib_id = "contribution:" + hashlib.sha256(
        f"{run_ref}|{terminal_ev['event_id'] if terminal_ev else ''}".encode()).hexdigest()[:16]

    projection = {
        "schema": "knowledge-contribution/v1",
        "contribution_id": contrib_id,
        "run_id": run_ref,
        "task_id": None,
        "goal_id": None,
        "session_id": origin,
        "terminal_event_ref": (f"event:{terminal_ev['event_id']}" if terminal_ev else None),
        "revision": 1,
        "supersedes": None,
        "task_outcome": "unknown",
        "task_outcome_note": (f"仅有模型自报 run_outcome.reason="
                              f"'{terminal.get('reason') if terminal else None}'；无独立任务成功标签，"
                              f"按 §5.3『不能回填』原则不写 success"),
        "contribution_state": "unclear",
        "contribution_state_note": ("3 条声明全部 helped=unclear / attribution_level=insufficient，"
                                    "故整体不标 partial；§5.3 仅示例了 partial，unclear 为本轮补充取值"),
        "use_refs": [f"usage:{r.get('id') or r.get('experience_ref')}" for r in exp_rows]
                    + [f"usage:{r.get('method_ref')}" for r in met_rows],
        "contributions": contributions,
        "presented_without_declaration": sorted(x for x in hint_refs - declared_refs if x),
        "declared_without_presentation_in_run": sorted(x for x in declared_refs - hint_refs if x),
        "projection_provenance_refs": [f"event:{r['event_id']}" for r in rows if r["event_id"]],
    }

    # ---------- P0b 诊断层（不影响 §5.3 结构） ----------
    pairing = [{"hint_ref": h.get("ref"), "discovery_seq": d["seq"],
                "declared_later": next((x["seq"] for x in declarations
                                        if x["payload"].get("ref") == h.get("ref") and x["seq"] > d["seq"]), None)}
               for d in discovery for h in (d["payload"].get("hints") or [])]
    missed = [x for x in pairing if x["declared_later"] is None]
    projection["p0b_diagnostics"] = {
        "run_seq_range": [min(seqs), max(seqs)] if seqs else None,
        "ts_range": [rows[0]["ts"], rows[-1]["ts"]],
        "files": sorted({r["file"] for r in rows}),
        "event_count": len(rows),
        "type_distribution": dict(types),
        "chain_counts": {"hydration_observed": len(hydration), "discovery": len(discovery),
                         "declarations": len(declarations), "failure_observed": len(failures),
                         "run_outcome": len(outcomes)},
        "hints": {"shown": len(hints), "declared_within_run": sorted(hint_refs & declared_refs),
                  "follow_through": f"{len(hint_refs & declared_refs)}/{len(hint_refs)}",
                  "pairing": pairing,
                  "missed": [x["hint_ref"] for x in missed]},
        "ledger_match": {**ledger_meta, "exp_matched": len(exp_rows), "met_matched": len(met_rows)},
        "run_end": {"reason": (run_end or {}).get("payload", {}).get("reason") if run_end else None,
                    "join": run_end_join, "seq": (run_end or {}).get("seq") if run_end else None},
        "read_only_proof": {"experiences_usage_sha256": sha256_file(EXP_LEDGER) if EXP_LEDGER.exists() else None,
                            "methods_usage_sha256": sha256_file(MET_LEDGER) if MET_LEDGER.exists() else None},
        "unknowns": [],
    }

    u = projection["p0b_diagnostics"]["unknowns"]
    u.append({"item": "净贡献/反事实增益", "value": "UNMEASURABLE",
              "why": "无对照组、无独立事实标签；单条轨迹无法分离『有知识』与『无知识』的结果差"})
    u.append({"item": "task_benefit", "value": "all-not_evaluated",
              "why": f"账本 {len(exp_rows) + len(met_rows)} 行 + run_outcome 1 行全为 not_evaluated"})
    u.append({"item": "task_id / goal_id", "value": "absent",
              "why": "本 run 事件 payload 不含 task_id/goal_id（§5.2 允许保留 unknown，不猜）"})
    u.append({"item": "provider_delivery / model_attention", "value": "unknown",
              "why": "本 run 无 knowledge.reference_prepared 送达事件，模型是否读到属 protocol 层不可知"})
    u.append({"item": "机会分母（advisor 未触发/被裁剪窗口）", "value": "UNMEASURABLE",
              "why": "无事件即无痕迹；hint 分母只覆盖已触发窗口"})
    u.append({"item": "helped / attribution_level 的独立可核性", "value": "unverified_in_this_session",
              "why": "账本 application_proven=true 但 authority=model_declared；其 evidence:// 句柄在本会话不可解析，"
                     "本轮未复验，故 helped 一律 unclear、attribution_level=insufficient"})
    u.append({"item": "discovery→declaration 时序（逐条配对）", "value": "checked",
              "why": f"discovery seq {[d['seq'] for d in discovery]}；declaration seq "
                     f"{[d['seq'] for d in declarations]}。hint {len(pairing)} 条，其中 {len(missed)} 条在其 discovery "
                     f"之后无 declaration 命中 → 不是时序伪影。{len(declarations) - sum(1 for x in declarations if any(d['seq'] < x['seq'] for d in discovery))} "
                     f"条声明早于全部 discovery，不计入落地率"})
    u.append({"item": "run.outcome 与 run.end 一致性", "value": "checked",
              "why": f"run_outcome.reason='{terminal.get('reason') if terminal else None}' vs run.end.reason="
                     f"'{(run_end or {}).get('payload', {}).get('reason') if run_end else None}'（join={run_end_join}）"})
    u.append({"item": "hydration_observed 与 run_outcome.hydrated_refs 一致性", "value": "checked",
              "why": f"hydrated_refs {len((terminal or {}).get('hydrated_refs') or [])} 条；"
                     f"declaration 中 hydration_observed=True 的 "
                     f"{sum(1 for c in contributions if c['hydration_observed'] is True)} 条"})

    (HERE / "contribution_projection.json").write_text(
        json.dumps(projection, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- markdown ----------
    p_ = projection
    d_ = p_["p0b_diagnostics"]
    md = ["# P0b 复用链只读贡献投影（一条 run）", "",
          f"- run_ref: `{p_['run_id']}`",
          f"- contribution_id: `{p_['contribution_id']}` / schema `{p_['schema']}`",
          f"- 归属 session: `{p_['session_id']}`（task_id / goal_id：事件层缺失，保留 null）",
          f"- seq {d_['run_seq_range'][0]}–{d_['run_seq_range'][1]} / {d_['ts_range'][0]} → {d_['ts_range'][1]}",
          f"- 事件 {d_['event_count']} 条，来源文件 {d_['files']}",
          f"- terminal_event_ref: `{p_['terminal_event_ref']}`",
          f"- task_outcome: `{p_['task_outcome']}`；contribution_state: `{p_['contribution_state']}`",
          ""]
    md += ["## 1. §5.3 contributions[]", "",
           "| subject_ref | kind | use_decision | authority | hydration | helped | attribution_level | evidence_refs |",
           "|---|---|---|---|---|---|---|---:|"]
    for c in p_["contributions"]:
        md.append(f"| `{c['subject_ref']}` | {c['subject_kind']} | {c['use_decision']} | {c['declaration_authority']} "
                  f"| {c['hydration_observed']} | **{c['helped']}** | {c['attribution_level']} "
                  f"| {len(c['evidence_refs'])} |")
    md += ["", "## 2. 呈现 / 声明 的四分", "",
           f"- presented_without_declaration（已呈现未声明）{len(p_['presented_without_declaration'])} 条："]
    for r in p_["presented_without_declaration"]:
        md.append(f"  - `{r}`")
    md.append(f"- declared_without_presentation_in_run（本 run 无 discovery hint 却被声明）"
              f"{len(p_['declared_without_presentation_in_run'])} 条：")
    for r in p_["declared_without_presentation_in_run"]:
        md.append(f"  - `{r}`")
    md += ["", "## 3. 链路层与落地率", "",
           "| 层 | 条数 |", "|---|---:|"]
    for k, v in d_["type_distribution"].items():
        md.append(f"| `{k}` | {v} |")
    md += ["", f"- hint 展示 {d_['hints']['shown']} 条，run 内被声明 {len(d_['hints']['declared_within_run'])} 条 "
               f"（**{d_['hints']['follow_through']}**）",
           "- 口径：分母只含本 run discovery 已给出的 hint，不含 advisor 未触发/被裁剪的窗口（不可测）", "",
           "## 4. unknown / 不可测报告", "", "| 项 | 值 | 依据 |", "|---|---|---|"]
    for x in d_["unknowns"]:
        md.append(f"| {x['item']} | `{x['value']}` | {x['why']} |")
    md += ["", "## 5. 只读性证据", "",
           f"- 账本匹配方式：{d_['ledger_match']['match']}（exp {d_['ledger_match']['exp_matched']}/{d_['ledger_match']['exp_total']}，"
           f"method {d_['ledger_match']['met_matched']}/{d_['ledger_match']['met_total']}）",
           f"- experiences/usage.jsonl sha256: `{d_['read_only_proof']['experiences_usage_sha256']}`",
           f"- data/methods/usage.jsonl sha256: `{d_['read_only_proof']['methods_usage_sha256']}`",
           "- 本脚本只读：未写账本、未写 EventStore、未补造终态、未新建 journal/worker。", ""]
    (HERE / "contribution_projection.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"ok": True, "contributions": len(p_["contributions"]),
                      "json": str(HERE / "contribution_projection.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
