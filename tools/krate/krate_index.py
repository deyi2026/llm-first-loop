#!/usr/bin/env python3
"""K-Rate layer 2+3+5: aggregate scores -> composite -> index (json+md) -> disposition advice.

Reads : data/knowledge_index/scores.jsonl, data/methods/*/METHOD.md,
        experiences/*.md, data/methods/usage.jsonl (self-reported benefit), docs/ai_rules.md
Writes: data/knowledge_index/index.json, index.md, dispositions.md  (atomic tmp+rename)

HARD BOUNDARY: this script never mutates data/methods/ or experiences/.
Disposition output is ADVICE with numeric-gate evidence; state changes go through
native tools (method_manage / refine_experience / submit_evolution) by a model.
"""
import json, sys, time, datetime, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import krate_common as K

REPO = Path(__file__).resolve().parents[2]
IDX = REPO / "data/knowledge_index"


def fm_of(path: Path) -> dict:
    fm, body = {}, path.read_text(encoding="utf-8")
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    kk, vv = line.split(":", 1)
                    fm[kk.strip()] = vv.strip().strip('"').strip("'")
    return fm


def parse_date(s):
    try:
        return datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def load_scores():
    by_ref = {}
    for ln in (IDX / "scores.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        by_ref.setdefault(r["record_ref"], []).append(r)
    return by_ref


def load_selfreports():
    sr = {}
    lp = REPO / "data/methods/usage.jsonl"
    if not lp.exists():
        return sr
    for ln in lp.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except Exception:
            continue
        ref = e.get("method_ref")
        if not ref:
            continue
        d = sr.setdefault(ref, {"hindered": 0, "neutral": 0, "events": 0, "last_ts": ""})
        d["events"] += 1
        if e.get("benefit") == "hindered":
            d["hindered"] += 1
        if e.get("benefit") == "neutral":
            d["neutral"] += 1
        if e.get("ts", "") > d["last_ts"]:
            d["last_ts"] = e["ts"]
    return sr


def aggregate(ref, meta, scores, selfrep, kind):
    now = datetime.datetime.now(datetime.timezone.utc)
    created = parse_date(meta.get("created_at") or meta.get("captured_at"))
    last_use = parse_date(selfrep.get("last_ts") if selfrep else None)
    anchor = max(x for x in [created, last_use] if x is not None) if (created or last_use) else None
    age_days = (now - anchor).days if anchor else None

    pairs, n_insuff, zeros = [], 0, 0
    for s in scores or []:
        if s["class"] == "insufficient":
            n_insuff += 1
            continue
        if s["top"] == 0:
            zeros += 1
        pairs.append((K.event_weight(s.get("ev_level", ""), s["class"]), s["expected"]))
    n_valid = len(pairs)
    e_shrunk = K.shrinkage(pairs) if pairs else None

    hindered = (selfrep or {}).get("hindered", 0)
    composite = None
    if e_shrunk is not None:
        composite = round(e_shrunk - 0.5 * hindered - K.age_decay(age_days or 0), 3)
    return {"ref": ref, "kind": kind, "name": meta.get("name", ref), "status": meta.get("status", "?"),
            "desc": (meta.get("description") or meta.get("summary") or "")[:160],
            "n_valid": n_valid, "n_insufficient": n_insuff, "e_shrunk": (round(e_shrunk, 3) if e_shrunk is not None else None),
            "zero_ratio": (round(zeros / n_valid, 2) if n_valid else None),
            "hindered_self": hindered, "last_use": selfrep.get("last_ts") if selfrep else None,
            "age_days": age_days, "composite": composite}


def gate(rec, last_use_recent_days):
    """Disposition ADVICE from numeric gates. rule kind is exempt from retire/invalidate."""
    g = K.GATE_QUALIFY
    if rec["kind"] == "rule":
        if rec["n_valid"]:
            return "RULE_INDEX_ONLY(低效规则->submit_evolution,不弃用)"
        return "RULE_INDEX_ONLY"
    if rec["hindered_self"] >= K.GATE_INVALIDATE_HINDERED or \
       (rec["hindered_self"] == 1 and rec["n_valid"] > 0):
        return "INVALIDATE_CANDIDATE"
    if rec["n_valid"] >= g["n_valid_min"] and rec["e_shrunk"] is not None:
        if rec["composite"] >= g["composite_min"] and rec["age_days"] is not None and rec["age_days"] <= g["recent_days"]:
            return "QUALIFY_CANDIDATE"
        if rec["e_shrunk"] < K.GATE_DEMOTE["e_shrunk_max"] and rec["hindered_self"] == 0:
            return "DEMOTE_HOLD_OR_ARCHIVE"
        if rec["zero_ratio"] is not None and rec["zero_ratio"] >= K.GATE_REFINE_ZERO_RATIO:
            return "REFINE_TRIGGER_RECALL_MISMATCH"
    if rec["n_valid"] == 0 and rec["age_days"] is not None and rec["age_days"] > K.GATE_STALE_DAYS:
        return "STALE_DEMOTE_OUT_OF_RECOMMENDED"
    n_all = rec["n_valid"] + rec["n_insufficient"]
    if n_all and rec["n_insufficient"] / n_all >= K.GATE_RECEIPT_BAD_RATIO:
        return "RECEIPT_QUALITY_FIX(改回执质量,不动条目)"
    if rec["status"] in ("hold", "archived", "invalidated") and rec["n_valid"] and rec.get("_last_top", 0) >= 3:
        return "REVIVE_CANDIDATE"
    return "MONITOR" if rec["n_valid"] else "UNRATED"


def last_top_of(scores):
    if not scores:
        return 0
    return max(s["top"] for s in scores)


def method_md_paths():
    """data/methods/ first; seed methods under .releases/*/methods/ (no hash suffix)."""
    seen, paths = set(), []
    for p in sorted((REPO / "data/methods").glob("*/METHOD.md")):
        seen.add(p.parent.name); paths.append(p)
    for rel in sorted(REPO.glob(".releases/*/methods"), reverse=True):
        for p in sorted(rel.glob("*/METHOD.md")):
            if p.parent.name not in seen:
                seen.add(p.parent.name); paths.append(p)
    return paths


def collect():
    by_ref = load_scores(); selfrep = load_selfreports()
    records = []
    for d in method_md_paths():
        fm = fm_of(d); ref = "method:" + d.parent.name
        rec = aggregate(ref, fm, by_ref.get(ref), selfrep.get(ref), "method")
        rec["_last_top"] = last_top_of(by_ref.get(ref)); records.append(rec)
    for d in sorted((REPO / "experiences").glob("EXPERIENCE-*.md")):
        fm = fm_of(d); ref = "experience:" + d.stem.replace("EXPERIENCE-", "").lower()
        rec = aggregate(ref, fm, by_ref.get(ref), selfrep.get(ref), "experience")
        rec["_last_top"] = last_top_of(by_ref.get(ref)); records.append(rec)
    rules_path = REPO / "docs/ai_rules.md"
    if rules_path.exists():
        for line in rules_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("### RULE-AI-"):
            # placeholder
                pass
    return records


def collect_rules():
    p = REPO / "docs/ai_rules.md"
    out = []
    if not p.exists():
        return out
    import re
    for m in re.finditer(r"^#{2,4}\s*([^\n]*RULE-AI-([0-9]+)[^\n]*)$", p.read_text(encoding="utf-8"), re.M):
        title = m.group(1).strip()
        rid = "RULE-AI-" + m.group(2)
        out.append({"ref": "rule:" + rid, "kind": "rule", "name": title[:100],
                    "status": "active", "desc": "", "n_valid": 0, "n_insufficient": 0,
                    "e_shrunk": None, "zero_ratio": None, "hindered_self": 0,
                    "last_use": None, "age_days": None, "composite": None, "_last_top": 0})
    return out


def atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main():
    recs = collect() + collect_rules()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rebuild = "python3 tools/krate/krate_score.py && python3 tools/krate/krate_index.py"
    header = {"generated_at": now_iso, "scorer": "27B-Instant-MLX-8bit @127.0.0.1:8091",
              "prompt_hash": K.prompt_hash(),
              "note": "scores are comparable only within the same prompt_hash; index is a RANKER not a RETRIEVER",
              "rebuild": rebuild,
              "counts": {"method": sum(1 for r in recs if r["kind"] == "method"),
                         "experience": sum(1 for r in recs if r["kind"] == "experience"),
                         "rule": sum(1 for r in recs if r["kind"] == "rule")}}
    for r in recs:
        r["disposition"] = gate(r, None)
    recs.sort(key=lambda r: (r["composite"] is None, -(r["composite"] or 0), r["age_days"] or 9999))

    atomic_write(IDX / "index.json", json.dumps({"header": header, "records": recs}, ensure_ascii=False, indent=1))

    lines = [f"# K-Rate 知识评分索引  (generated {now_iso}, prompt_hash={K.prompt_hash()})",
             f"> 排序器非检索器: search_records 命中后按此表定加载优先级; 执行前必读条目正文。",
             f"> 重建: `{rebuild}`  | 跨 prompt_hash 分数不可比较\n",
             "## 已评级 (按 composite 降序)\n",
             "| # | kind | ref | 名称 | composite | n | E_shrunk | 最近使用 | 处置建议 |",
             "|--:|:--|:--|:--|--:|--:|--:|:--|:--|"]
    n = 0
    for r in recs:
        if r["composite"] is None:
            continue
        n += 1
        lines.append(f"| {n} | {r['kind'][:4]} | `{r['ref'][:44]}` | {r['name'][:40]} | {r['composite']:.2f} | "
                     f"{r['n_valid']}(+{r['n_insufficient']}i) | {r['e_shrunk']:.2f} | {(r['last_use'] or '')[:10]} | {r['disposition']} |")
    lines.append("\n## 未评级 (按卡龄升序, n=0 无使用事件; 高卡龄=STALE 出推荐位)\n")
    lines.append("| kind | ref | 名称 | 卡龄d | 处置建议 |")
    lines.append("|:--|:--|:--|--:|:--|")
    for r in recs:
        if r["composite"] is not None:
            continue
        if r["kind"] == "rule":
            continue
        lines.append(f"| {r['kind'][:4]} | `{r['ref'][:44]}` | {r['name'][:40]} | {r['age_days'] if r['age_days'] is not None else '?'} | {r['disposition']} |")
    rules = [r for r in recs if r["kind"] == "rule"]
    lines.append(f"\n## 规则 ({len(rules)} 条, 仅索引效果, 处置只走 submit_evolution)\n")
    lines.append("; ".join(f"`{r['ref']}`" for r in rules[:40]))
    atomic_write(IDX / "index.md", "\n".join(lines) + "\n")

    disp = [f"# 处置建议清单 (advice only; 状态变更须由模型走原生工具)  {now_iso}\n"]
    for r in recs:
        if r["disposition"] in ("UNRATED", "MONITOR", "STALE_DEMOTE_OUT_OF_RECOMMENDED", "RULE_INDEX_ONLY") and r["n_valid"] == 0:
            continue
        disp.append(f"- **{r['disposition']}** `{r['ref']}` ({r['name'][:50]})  "
                    f"composite={r['composite']} E_shrunk={r['e_shrunk']} n_valid={r['n_valid']} "
                    f"n_insuff={r['n_insufficient']} hindered_self={r['hindered_self']} zero_ratio={r['zero_ratio']} age={r['age_days']}d")
    atomic_write(IDX / "dispositions.md", "\n".join(disp) + "\n")
    print(f"[krate-index] records={len(recs)} rated={sum(1 for r in recs if r['composite'] is not None)} "
          f"-> index.json / index.md / dispositions.md")


if __name__ == "__main__":
    main()
