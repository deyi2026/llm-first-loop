#!/usr/bin/env python3
"""P0a-2 稀薄链路身份/覆盖审计 v2。只读。

判据：
- run_ref 形如 <origin_session_id>:turn:<n>:run:<hash>，前缀即原始归属 session。
- 同一 run 的事件可能被复制到 fork/branch session（同 seq/ts/key，不同 event_id）。
  因此以 (run_ref, seq, knowledge_event_key) 为业务身份做跨 session 去重，
  归属 session 取 run_ref 前缀。不按"最近事件"强 join。
"""
from __future__ import annotations
import json, os, collections

ROOT="data/event_logs"; BOUND="2026-10-15T00:08:59.999999+08:00"
THIN={"knowledge.reference_prepared","knowledge.hydration_observed","knowledge.method_declaration",
      "knowledge.experience_declaration","knowledge.learning_saved","knowledge.learning_unconfirmed"}

def iter_files():
    for name in sorted(os.listdir(ROOT)):
        p=os.path.join(ROOT,name)
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.endswith(".jsonl"): yield name,os.path.join(p,fn)
        elif name.endswith(".jsonl"): yield name[:-6],p

raw=[]                       # 全部 knowledge 事件（上界内）
for sid,fp in iter_files():
    for ln in open(fp,encoding="utf-8"):
        ln=ln.strip()
        if not ln: continue
        try: ev=json.loads(ln)
        except Exception: continue
        t=ev.get("type") or ""; ts=ev.get("ts") or ""
        if not t.startswith("knowledge."): continue
        if ts>BOUND: continue
        raw.append({"t":t,"sid":ev.get("session_id"),"seq":ev.get("seq"),"ts":ts,
                    "pl":ev.get("payload") or {},"eid":ev.get("event_id")})

# 业务身份 = (run_ref, seq, knowledge_event_key)；归属 session = run_ref 前缀
def origin(pl, sid):
    rr=pl.get("run_ref")
    return (rr.split(":")[0] if rr else sid)

by_ident={}
dup_cross_session=0
for e in raw:
    pl=e["pl"]; rr=pl.get("run_ref")
    if not rr:
        ident=("NO_RUN_REF", e["sid"], e["seq"], pl.get("knowledge_event_key"))
    else:
        ident=(rr, e["seq"], pl.get("knowledge_event_key"))
    if ident in by_ident:
        prev=by_ident[ident]
        if prev["sid"]!=e["sid"]: dup_cross_session+=1
        continue
    e["origin"]=origin(pl,e["sid"]); e["run_ref"]=rr
    by_ident[ident]=e

evs=list(by_ident.values())
disc=collections.Counter(); outc=collections.Counter()
for e in evs:
    rr=e["run_ref"]
    if e["t"]=="knowledge.discovery" and rr: disc[rr]+=1
    if e["t"]=="knowledge.run_outcome" and rr: outc[rr]+=1

thin=[e for e in evs if e["t"] in THIN]
for e in thin:
    rr=e["run_ref"]
    if not rr:
        e["link"]="NO_RUN_REF"
    else:
        e["has_discovery"]=disc.get(rr,0); e["has_outcome"]=outc.get(rr,0)
        e["link"]="UNIQUE"
    e["type"]=e["t"][10:]; e["session_origin"]=e["origin"]
    e["copied_from_fork"]= (e["sid"]!=e["origin"])
    pl=e["pl"]
    e["ref"]=pl.get("ref"); e["decision"]=pl.get("decision")
    e["call_id"]=pl.get("call_id"); e["kind"]=pl.get("kind")
    e["task_benefit"]=pl.get("task_benefit"); e["hydration_observed"]=pl.get("hydration_observed")
    e["authority"]=pl.get("authority"); e["verification_state"]=pl.get("verification_state")

out={
 "raw_knowledge_events":len(raw),
 "after_identity_dedup":len(evs),
 "cross_session_duplicate_rows":dup_cross_session,
 "distinct_run_ref_discovery":len(disc),
 "distinct_run_ref_outcome":len(outc),
 "thin_total":len(thin),
 "thin_by_type":dict(collections.Counter(e["type"] for e in thin)),
 "thin_link":dict(collections.Counter(e["link"] for e in thin)),
 "thin_with_discovery":sum(1 for e in thin if e.get("has_discovery",0)>0),
 "thin_with_outcome":sum(1 for e in thin if e.get("has_outcome",0)>0),
 "thin_from_fork_copy":sum(1 for e in thin if e["copied_from_fork"]),
 "rows":[{k:e[k] for k in ("type","session_origin","sid","seq","ts","run_ref","ref","decision","kind","task_benefit","hydration_observed","authority","verification_state","link","has_discovery","has_outcome","copied_from_fork")} for e in sorted(thin,key=lambda x:(x["type"],x["ts"]))],
}
print(json.dumps(out,ensure_ascii=False,indent=2))
