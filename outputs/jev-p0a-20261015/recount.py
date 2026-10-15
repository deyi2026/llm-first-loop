#!/usr/bin/env python3
"""P0a-1 只读复算：枚举 EventStore 全部分段（顶层单文件 + <session_id>/<seg>.jsonl），
复算 v0.5 §1.3.1 口径。只读；不写 EventStore/usage；不调用外部 Provider。"""
from __future__ import annotations
import json, os, collections, hashlib, sys

ROOT = "data/event_logs"
BOUND = "2026-10-15T00:08:59.999999+08:00"

def iter_files():
    """顶层单文件会话 + 滚动分段目录。不把 .lock 或其它项计入。"""
    for name in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, name)
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.endswith(".jsonl"):
                    yield ("segment", name, os.path.join(p, fn))
        elif name.endswith(".jsonl"):
            yield ("top", name[:-len(".jsonl")], p)

def norm_ts(ts):
    # ts 形如 2026-09-12T05:39:31.160276+00:00
    return ts

def main():
    n_top = n_seg = 0
    lines = bad = 0
    types = collections.Counter()
    ktop = kseg = 0
    k_sessions, runend_sessions = set(), set()
    run_refs = set()
    k_first, k_last = None, None
    daily = collections.Counter()
    top_files, seg_files = [], []
    for kind, sid, fp in iter_files():
        if kind == "top":
            n_top += 1; top_files.append((os.path.basename(fp), os.path.getsize(fp)))
        else:
            n_seg += 1; seg_files.append((os.path.join(sid, os.path.basename(fp)), os.path.getsize(fp)))
        with open(fp, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln: continue
                lines += 1
                try: ev = json.loads(ln)
                except Exception:
                    bad += 1; continue
                t = ev.get("type") or ""
                ts = ev.get("ts") or ""
                if BOUND and ts and ts > BOUND:
                    continue  # 固定上界：越界不计入任何计数
                types[t] += 1
                if t.startswith("knowledge."):
                    if kind == "top": ktop += 1
                    else: kseg += 1
                    k_sessions.add(ev.get("session_id") or sid)
                    rr = (ev.get("payload") or {}).get("run_ref")
                    if rr: run_refs.add(rr)
                    ts = ev.get("ts") or ""
                    if ts:
                        if k_first is None or ts < k_first: k_first = ts
                        if k_last is None or ts > k_last: k_last = ts
                        daily[ts[:10]] += 1
                elif t == "run.end":
                    runend_sessions.add(ev.get("session_id") or sid)
    out = {
        "root": ROOT,
        "bound": BOUND,
        "files_top": n_top, "files_segment": n_seg, "files_total": n_top + n_seg,
        "lines_parsed": lines, "parse_bad": bad,
        "knowledge_top": ktop, "knowledge_segment": kseg, "knowledge_total": ktop + kseg,
        "knowledge_sessions": len(k_sessions),
        "knowledge_run_refs": len(run_refs),
        "knowledge_first_ts": k_first, "knowledge_last_ts": k_last,
        "knowledge_daily": dict(sorted(daily.items())),
        "run_end_total": types.get("run.end", 0),
        "run_end_sessions": len(runend_sessions),
        "knowledge_types": {k[10:]: v for k, v in sorted(types.items(), key=lambda x: -x[1]) if k.startswith("knowledge.")},
        "top50_types": types.most_common(50),
    }
    manifest = "\n".join(f"{n}\t{s}" for n, s in sorted(top_files + seg_files))
    out["file_manifest_sha256"] = hashlib.sha256(manifest.encode()).hexdigest()
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
