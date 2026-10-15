#!/usr/bin/env python3
"""P0a-3 退出分层与 fail-open 覆盖边界。只读。"""
from __future__ import annotations
import json, os, collections

ROOT="data/event_logs"; BOUND="2026-10-15T00:08:59.999999+08:00"
def iter_files():
    for name in sorted(os.listdir(ROOT)):
        p=os.path.join(ROOT,name)
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                if fn.endswith(".jsonl"): yield name,os.path.join(p,fn)
        elif name.endswith(".jsonl"): yield name[:-6],p

runend=[]; kruns=set(); sessions_with_k=set()
runend_by_session=collections.Counter()
reason_c=collections.Counter()
runend_payload_keys=set()
incomplete=0
for sid,fp in iter_files():
    for ln in open(fp,encoding="utf-8"):
        ln=ln.strip()
        if not ln: continue
        try: ev=json.loads(ln)
        except Exception: continue
        t=ev.get("type") or ""; ts=ev.get("ts") or ""
        if ts>BOUND: continue
        pl=ev.get("payload") or {}
        if t=="run.end":
            runend.append(ev); runend_by_session[ev.get("session_id")]+=1
            reason_c[pl.get("reason")]+=1
            runend_payload_keys|=set(pl.keys())
            if pl.get("run_incomplete"): incomplete+=1
        elif t.startswith("knowledge."):
            rr=pl.get("run_ref")
            if rr: kruns.add(rr)
            sessions_with_k.add(ev.get("session_id"))

# knowledge run 是否有 run_outcome
outc_runs=set()
for sid,fp in iter_files():
    for ln in open(fp,encoding="utf-8"):
        ln=ln.strip()
        if not ln: continue
        try: ev=json.loads(ln)
        except Exception: continue
        if ev.get("type")=="knowledge.run_outcome" and (ev.get("ts") or "")<=BOUND:
            rr=(ev.get("payload") or {}).get("run_ref")
            if rr: outc_runs.add(rr)

sessions_with_runend=set(runend_by_session)
sessions_open = sessions_with_k - sessions_with_runend
out={
 "run_end_total":len(runend),
 "run_end_sessions":len(sessions_with_runend),
 "run_end_reasons":dict(reason_c),
 "run_end_run_incomplete_true":incomplete,
 "run_end_payload_keys":sorted(runend_payload_keys),
 "knowledge_sessions":len(sessions_with_k),
 "knowledge_runs_total":len(kruns),
 "knowledge_runs_with_outcome":len(outc_runs),
 "knowledge_runs_without_outcome":len(kruns-outc_runs),
 "knowledge_sessions_without_any_run_end":len(sessions_open),
 "knowledge_sessions_without_any_run_end_sample":sorted(sessions_open)[:10],
 "UNMEASURABLE":[
   "无 run.end 也无 run_outcome 的运行是否被 kill/fail-open 丢失：EventStore 无该 run 的任何痕迹，不可测",
   "provider 是否真实送达模型（model_attention）：protocol 层永远 unknown",
   "未产生 discovery 的机会窗口（advisor 未触发/被裁剪）：无事件即无痕迹，不可测",
 ],
}
print(json.dumps(out,ensure_ascii=False,indent=2))
