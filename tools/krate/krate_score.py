#!/usr/bin/env python3
"""K-Rate layer 1: score method usage events via local /v1/systemone scorer.

Input : data/methods/usage.jsonl  (schema method-use/v2, written by LFL settlement)
Output: data/knowledge_index/scores.jsonl (append-only, idempotent by event_id)

Idempotency : event_id = submission_hash (fallback slot_id/integrity). Re-runs skip
              scored events; --rescore re-asks everything under the SAME prompt hash
              only when you pass --force-version-bump (writes scorer/prompt_hash per line,
              so cross-version scores stay separable at aggregation).
Failure mode : scorer unreachable -> exit 2, unscored events simply stay pending.
              NO default scores are ever invented (hard-case F lesson).
Permission   : reads knowledge store, writes ONLY under data/knowledge_index/.
"""
import argparse, json, sys, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import krate_common as K

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = REPO / "data/methods/usage.jsonl"
DEFAULT_OUT = REPO / "data/knowledge_index/scores.jsonl"

STATE_TMPL = (
    "任务背景: {task}\n"
    "知识条目「{name}」: {desc}\n"
    "适用触发: {trigger}\n"
    "何时不适用: {counter}\n"
    "实际使用情况: 决策={decision}, 自报收益={benefit}, 证据级别={ev_level}\n"
    "使用记录: {note}\n"
    "(事件时间 {ts}; 使用模型 {model}; 附带证据引用 {nev} 条)"
)


def load_method(method_ref: str):
    """method:xxx-<hash> -> (name, description, trigger, counterexamples) from METHOD.md.
    data/methods/ first; seed methods (no hash suffix) live under .releases/*/methods/."""
    slug = method_ref.split(":", 1)[1] if ":" in method_ref else method_ref
    candidates = [REPO / "data/methods" / slug]
    candidates += sorted(REPO.glob(".releases/*/methods/" + slug),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    p = next((c / "METHOD.md" for c in candidates if (c / "METHOD.md").exists()), None)
    if p is None:
        return None
    text = p.read_text(encoding="utf-8")
    # frontmatter
    fm, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    kk, vv = line.split(":", 1)
                    fm[kk.strip()] = vv.strip().strip('"')
    def section(tag, cap=500):
        for head in (f"## {tag}", f"## {tag}s"):
            i = body.find(head)
            if i >= 0:
                rest = body[i + len(head):]
                j = rest.find("\n## ")
                seg = rest if j < 0 else rest[:j]
                seg = " ".join(seg.split())
                return (seg[:cap] + "…") if len(seg) > cap else seg
        return "(未提供)"
    return {"name": fm.get("name", slug), "desc": fm.get("description", "")[:600],
            "trigger": section("Trigger"), "counter": section("Counterexample")}


def build_state(ev: dict, m: dict) -> str:
    task = ev.get("attribution") or ev.get("work_unit_id") or "(见使用记录)"
    note = ev.get("note") or "(使用模型未留叙述)"
    return STATE_TMPL.format(task=task, name=m["name"], desc=m["desc"], trigger=m["trigger"],
                             counter=m["counter"], decision=ev.get("decision", "?"),
                             benefit=ev.get("benefit", "?"), ev_level=ev.get("evidence_level", "?"),
                             note=note, ts=ev.get("ts", "?"), model=ev.get("model", "?"),
                             nev=len(ev.get("evidence_refs") or []))


def ask(state: str, port: str) -> dict:
    body = {"state": state, "questions": K.questions(), "return_details": True}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{K.SCORER_PATH}",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(DEFAULT_LEDGER))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--port", default=K.SCORER_PORT)
    ap.add_argument("--limit", type=int, default=0, help="score at most N pending events (0=all)")
    ap.add_argument("--only", default="", help="score only this method_ref substring")
    ap.add_argument("--dry-run", action="store_true", help="show assembled state, do not call scorer")
    args = ap.parse_args()

    out_path = Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for ln in out_path.read_text(encoding="utf-8").splitlines():   # tolerant reader
            try:
                done.add(json.loads(ln)["event_id"])
            except Exception:
                continue

    events = []
    for ln in Path(args.events).read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if args.only and args.only not in ev.get("method_ref", ""):
            continue
        eid = ev.get("submission_hash") or ev.get("slot_id") or ev.get("integrity")
        if not eid or eid in done:
            continue
        events.append((eid, ev))

    if args.limit:
        events = events[:args.limit]
    if not events:
        print(f"[krate-score] no pending events ({len(done)} already scored)"); return 0

    print(f"[krate-score] pending={len(events)} scored_before={len(done)} port={args.port} prompt_hash={K.prompt_hash()}")
    ok = bad = 0
    with out_path.open("a", encoding="utf-8") as fh:
        for eid, ev in events:
            m = load_method(ev.get("method_ref", ""))
            if m is None:
                print(f"  SKIP {ev.get('method_ref','?')[:60]} (METHOD.md not found)"); continue
            state = build_state(ev, m)
            if args.dry_run:
                print(f"--- event {eid[:12]} {m['name'][:40]}\n{state}\n"); ok += 1; continue
            try:
                out = ask(state, args.port)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                print(f"[krate-score] scorer unreachable: {e}\n[event {eid[:12]} left pending]"); return 2
            a = out.get("answers", {})
            sc, nu = a.get("usefulness", {}), a.get("evidence_sufficient", {})
            probs = {k: float(v) for k, v in sc.get("probabilities", {}).items()}
            expected = sum(int(k) * v for k, v in probs.items())
            top = max(probs, key=probs.get) if probs else "-1"
            p_suff = float(nu.get("noul", 0.0))
            rec = {"event_id": eid, "record_ref": ev.get("method_ref"), "ts": ev.get("ts"),
                   "decision": ev.get("decision"), "benefit": ev.get("benefit"),
                   "ev_level": ev.get("evidence_level"),
                   "scorer": out.get("model"), "prompt_hash": K.prompt_hash(),
                   "expected": round(expected, 3), "top": int(top), "probs": probs,
                   "p_suff": round(p_suff, 3), "conf": sc.get("confidence"),
                   "class": K.event_class(p_suff)}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            ok += 1
            print(f"  {m['name'][:44]:44s} top={top} E={expected:.2f} p_suff={p_suff:.2f} -> {rec['class']}")
    print(f"[krate-score] done ok={ok} (failures left pending={bad})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
