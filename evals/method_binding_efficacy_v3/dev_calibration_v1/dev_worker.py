#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,shutil,sys,time
H=pathlib.Path(__file__).resolve().parent; ROOT=H.parents[2]
for p in (str(H),str(ROOT/'src'),str(ROOT)): sys.path.insert(0,p)
from dev_protocol import MODELS,BINDING_ENV,BINDING_MARKER,FORMAL_PROMPT,PREFLIGHT_PROMPT

def sha_obj(o):return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def events_for(data_dir,sid):
 p=pathlib.Path(data_dir)/'event_logs'/f'{sid}.jsonl'; out=[]
 if p.exists():
  for line in p.read_text().splitlines():
   try:out.append(json.loads(line))
   except:pass
 return out
def settle(ev):
 po=[e for e in ev if e.get('type')=='provider.call.opened']; ps=[e for e in ev if e.get('type')=='provider.call.settled']; to=[e for e in ev if e.get('type')=='provider.transport.opened']; ts=[e for e in ev if e.get('type')=='provider.transport.settled']; ends=[e for e in ev if e.get('type')=='run.end']; metas=[e for e in ev if e.get('type')=='request.meta']
 ok=(len(po)==len(ps)>0 and len(to)==len(ts)>0 and all((e.get('payload') or {}).get('outcome')=='success' for e in ps) and all((e.get('payload') or {}).get('outcome')=='success' and (e.get('payload') or {}).get('status_code')==200 for e in ts))
 end=(ends[-1].get('payload') or {}) if ends else {}; meta=(metas[-1].get('payload') or {}) if metas else {}
 return {'settlement_ok':ok,'provider_calls_opened':len(po),'provider_calls_settled':len(ps),'transports_opened':len(to),'transports_settled':len(ts),'run_end_completed':end.get('reason')=='completed','request_meta_tools_fp':(meta.get('run_integrity_receipt') or {}).get('tools_fp') or meta.get('tools_fp')}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--model-key',choices=['strong','weak'],required=True); ap.add_argument('--case-id'); ap.add_argument('--attempt',type=int,default=0); ap.add_argument('--out',required=True); ap.add_argument('--data-dir',required=True); ap.add_argument('--preflight',action='store_true'); args=ap.parse_args()
 started=time.monotonic(); row={'kind':'preflight' if args.preflight else 'formal','model_key':args.model_key,'arm':'C0','case_id':args.case_id or 'preflight','attempt':args.attempt,'started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')}; engine=None
 try:
  from llm_loop.config import load_env_file,load_settings
  from llm_loop.factory import build_engine
  from llm_loop.introspection import registry_experience as reg
  from llm_loop.core.trace_leak.ingress_token import issue_ingress
  runtime_root=pathlib.Path(os.environ['LFL_RUNTIME_ROOT']).resolve(); data_dir=pathlib.Path(args.data_dir).resolve(); snaps={}
  for name in ('providers.local.json','providers.json'):
   src=runtime_root/'data'/name
   if src.is_file(): dst=data_dir/name; shutil.copy2(src,dst); snaps[name]=hashlib.sha256(dst.read_bytes()).hexdigest()
  load_env_file(runtime_root/'.env'); settings=load_settings(); exp=MODELS[args.model_key]; assert settings.llm_model==exp['bare']; assert pathlib.Path(settings.data_dir).resolve()==data_dir
  desc=next(x for x in reg.tool_defs() if x['name']=='save_experience')['description']; assert BINDING_MARKER not in desc,'C0 unexpectedly binding-on'
  engine=build_engine(settings); schemas=engine.registry.schemas(lazy=True); surface={x['name']:sha_obj(x) for x in schemas}; row.update({'surface':surface,'surface_sha256':sha_obj(surface),'model_registered':exp['canonical'],'provider_registry_snapshot_sha256':snaps})
  if args.preflight: prompt=PREFLIGHT_PROMPT
  else:
   plan=json.loads((H/'dev_plan.json').read_text()); c=plan['cases'][args.case_id]; row.update({'family':c['family'],'expected':c['intended'],'row_id':f"{args.model_key}:{args.case_id}:C0"}); prompt=FORMAL_PROMPT.format(task=c['task'],card=c['card'])
  sid=engine.session.create(); result=engine.run(sid,prompt,ingress=issue_ingress('cli')); ev=events_for(settings.data_dir,sid); row.update(settle(ev)); row.update({'status':'RUN_OK','model_used':result.model_used,'fallback_used':bool(result.fallback_receipt),'truncated':bool(result.truncated),'rounds':result.rounds,'tokens_in':result.tokens_in,'tokens_out':result.tokens_out,'tool_call_count':len(result.tool_calls or []),'final_answer':result.final_answer or '','wall_s':round(time.monotonic()-started,3)})
 except Exception as e: row.update({'status':'WORKER_ERROR','error_type':type(e).__name__,'error':str(e)[:400],'wall_s':round(time.monotonic()-started,3)})
 finally:
  try:
   if engine is not None:engine.close()
  except:pass
 with open(args.out,'a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 print(json.dumps({k:row.get(k) for k in ('status','model_key','case_id','attempt','model_used','settlement_ok','run_end_completed','wall_s')},ensure_ascii=False))
if __name__=='__main__':main()
