import json, threading, time, requests
BASE="http://127.0.0.1:8903"; MODEL="glm/glm-5.3-flash"
OUT="reports/observability-real-samples"
TAG=time.strftime("%Y%m%d-%H%M%S")+"C4"
def jget(p):
    r=requests.get(BASE+p,timeout=15); r.raise_for_status(); return r.json()
def jpost(p,b):
    r=requests.post(BASE+p,json=b,timeout=15); r.raise_for_status(); return r.json()

def attempt(idx,topic):
    st={"fired":False,"deltas":0,"last_delta_t":None,"done":False,"sid":None,"gen":None,"result":None}
    def fire(sid,gen):
        st["fired"]=True
        t_req=time.time()
        try:
            q=jpost("/api/v1/chat/queue",{"session_id":sid,"message":"【看板样本·插话C】收到请直接回复：收到插话C。"})
            qid=q.get("queue_id")
            ij=None
            try:
                ij=jpost("/api/v1/chat/queue/interject",{"session_id":sid,"queue_id":qid,"run_generation":gen or ""})
            except requests.HTTPError as e:
                ij={"http":e.response.status_code,"err":e.response.text[:100]}
            st["result"]={"qid":qid,"ij":ij,"t_req":t_req}
        except Exception as e:
            st["result"]={"fire_error":str(e)[:150]}
    def run():
        try:
            with requests.post(BASE+"/api/v1/chat/stream",json={"new_session":True,"model":MODEL,
                "message":f"请写一篇约 2500 字的综述，主题：{topic}。直接输出全文正文，不要调用任何工具。"},
                stream=True,timeout=(15,900)) as r:
                if r.status_code!=200:
                    st["result"]={"http":r.status_code}; st["done"]=True; return
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw: continue
                    line=raw.strip()
                    if not line.startswith("data:"): continue
                    try: msg=json.loads(line.split(":",1)[1].strip())
                    except Exception: continue
                    t=msg.get("type"); d=msg.get("data") or {}
                    if t=="run_started":
                        st["sid"]=d.get("session_id"); st["gen"]=d.get("run_generation")
                    elif t=="answer_delta":
                        st["deltas"]+=1; st["last_delta_t"]=time.monotonic()
                    elif t in ("done","error"):
                        st["done"]=True; break
        except Exception as e:
            st["result"]=st["result"] or {"exc":str(e)[:150]}
    th=threading.Thread(target=run,daemon=True); th.start()
    t0=time.monotonic()
    while time.monotonic()-t0<300 and not st["done"]:
        if (not st["fired"] and st["sid"] and st["deltas"]>=250
                and st["last_delta_t"] and time.monotonic()-st["last_delta_t"]>0.15):
            fire(st["sid"],st["gen"])
        time.sleep(0.02)
    time.sleep(3)  # 让回执/结算落库
    rec={"idx":idx,"sid":st["sid"],"deltas":st["deltas"],"fired":st["fired"],
         "fire_result":st["result"]}
    if st["result"] and "qid" in st["result"]:
        snap={}
        t3=time.monotonic()
        while time.monotonic()-t3<45:
            try:
                it=jget(f"/api/v1/chat/queue/item?session_id={st['sid']}&queue_id={st['result']['qid']}")
                snap=it.get("item",it)
                if snap.get("status") in ("interject_received","completed","failed"): break
            except Exception: pass
            time.sleep(1.5)
        rec["terminal"]={k:snap.get(k) for k in ("status","consumed_via","interrupt_receipt",
            "interject_requested_at","received_at","applied_at") if k in snap}
    print(f"[C3-{idx}] deltas={st['deltas']} fired={st['fired']} terminal={rec.get('terminal')} fire={st['result']}",flush=True)
    return rec

log={"scenarios":[attempt(i,t) for i,t in enumerate([
    "编译器寄存器分配算法的演进","分布式共识协议的工程权衡史","向量数据库索引结构综述"],1)]}
g=jget("/api/v1/chat/queue/metrics/global")
log["global_after"]=g
json.dump(log,open(f"{OUT}/DRIVER_{TAG}.json","w"),ensure_ascii=False,indent=1)
print("AFTER:",json.dumps({k:v.get("n") for k,v in g.get("buckets",{}).items()},ensure_ascii=False),flush=True)
print("C3_DONE",flush=True)
