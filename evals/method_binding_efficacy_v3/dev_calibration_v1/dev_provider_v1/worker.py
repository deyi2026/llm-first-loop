#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,shutil,sys,time
HERE=pathlib.Path(__file__).resolve().parent
REPO=HERE.parents[2]
for p in (str(HERE),str(REPO/'src'),str(REPO)): sys.path.insert(0,p)
from protocol import MODELS,BINDING_MARKER,FORMAL_PROMPT,PREFLIGHT_PROMPT

def sha_obj(o): return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def tool_entry(tc):
 name=getattr(tc,'name',None) or (tc.get('name') if isinstance(tc,dict) else None) or '?'
 return str(name)
def events_for(data_dir,sid):
 p=pathlib.Path(data_dir)/'event_logs'/f'{sid}.jsonl'
 if not p.exists(): return []
 out=[]
 for line in p.read_text(encoding='utf-8').splitlines():
  try: out.append(json.loads(line))
  except Exception: pass
 return out
def settle(events):
 t=[e.get('type') for e in events]
 po=[e for e in events if e.get('type')=='provider.call.opened']; ps=[e for e in events if e.get('type')=='provider.call.settled']
 to=[e for e in events if e.get('type')=='provider.transport.opened']; ts=[e for e in events if e.get('type')=='provider.transport.settled']
 metas=[e for e in events if e.get('type')=='request.meta']; ends=[e for e in events if e.get('type')=='run.end']
 success_calls=all((e.get('payload') or {}).get('outcome')=='success' for e in ps)
 success_trans=all((e.get('payload') or {}).get('outcome')=='success' and (e.get('payload') or {}).get('status_code')==200 for e in ts)
 prepared=all(bool(((e.get('payload') or {}).get('prepared') or {}).get('payload_hmac')) and int(((e.get('payload') or {}).get('prepared') or {}).get('projected_bytes') or 0)>0 for e in to)
 ok=(len(po)==len(ps)>0 and len(to)==len(ts)>0 and success_calls and success_trans and prepared)
 meta=(metas[-1].get('payload') or {}) if metas else {}
 end=(ends[-1].get('payload') or {}) if ends else {}
 return {'settlement_ok':ok,'provider_calls_opened':len(po),'provider_calls_settled':len(ps),'transports_opened':len(to),'transports_settled':len(ts),'prepared_complete':prepared,'request_meta_tools_fp':meta.get('run_integrity_receipt',{}).get('tools_fp') or meta.get('tools_fp'),'request_meta_system_fp':meta.get('run_integrity_receipt',{}).get('system_fp') or meta.get('system_fp'),'projected_bytes':[int(((e.get('payload') or {}).get('prepared') or {}).get('projected_bytes') or 0) for e in to],'run_end_completed':end.get('reason')=='completed','run_end_rounds':end.get('rounds')}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--model-key',required=True,choices=['strong','weak']); ap.add_argument('--arm',required=True,choices=['C0','C1']); ap.add_argument('--out',required=True); ap.add_argument('--data-dir',required=True); ap.add_argument('--case-id'); ap.add_argument('--attempt',type=int,default=0); ap.add_argument('--preflight',action='store_true'); ap.add_argument('--surface-only',action='store_true'); args=ap.parse_args()
 started=time.monotonic(); kind='surface' if args.surface_only else ('preflight' if args.preflight else 'formal')
 row={'kind':kind,'model_key':args.model_key,'arm':args.arm,'case_id':args.case_id or kind,'attempt':args.attempt,'started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
 engine=None
 try:
  from llm_loop.config import load_env_file,load_settings
  from llm_loop.factory import build_engine
  from llm_loop.introspection import registry_experience as reg
  from llm_loop.core.trace_leak.ingress_token import issue_ingress
  runtime_root=pathlib.Path(os.environ['LFL_RUNTIME_ROOT']).resolve()
  data_dir=pathlib.Path(args.data_dir).resolve()
  registry_snapshot={}
  for name in ('providers.local.json','providers.json'):
   src=runtime_root/'data'/name
   if src.is_file():
    dst=data_dir/name; shutil.copy2(src,dst)
    registry_snapshot[name]=hashlib.sha256(dst.read_bytes()).hexdigest()
  load_env_file(runtime_root/'.env'); settings=load_settings(); expected=MODELS[args.model_key]
  assert settings.llm_model==expected['bare'],(settings.llm_model,expected['bare'])
  assert pathlib.Path(settings.data_dir).resolve()==pathlib.Path(args.data_dir).resolve(),(settings.data_dir,args.data_dir)
  desc=next(x for x in reg.tool_defs() if x['name']=='save_experience')['description']; binding=BINDING_MARKER in desc
  assert binding==(args.arm=='C1'),f'binding mismatch {binding} {args.arm}'
  engine=build_engine(settings); schemas=engine.registry.schemas(lazy=True); surface={x['name']:sha_obj(x) for x in schemas}
  row.update({'binding_asserted':binding,'surface':surface,'surface_tool_count':len(surface),'surface_sha256':sha_obj(surface),'model_registered':expected['canonical'],'provider_registry_snapshot_sha256':registry_snapshot})
  if args.surface_only:
   row['status']='SURFACE_ONLY'
  else:
   if args.preflight: prompt=PREFLIGHT_PROMPT
   else:
    plan=json.loads((HERE/'matrix_plan.json').read_text(encoding='utf-8')); c=plan['cases'][args.case_id]
    row.update({'cell':c['cell'],'expected':c['intended'],'row_id':f"{args.model_key}:{args.case_id}:{args.arm}"})
    prompt=FORMAL_PROMPT.format(task=c['task'],card=c['card'])
   sid=engine.session.create(); result=engine.run(sid,prompt,ingress=issue_ingress('cli')); ev=events_for(settings.data_dir,sid); row.update(settle(ev))
   row.update({'status':'RUN_OK','session_sha256':hashlib.sha256(sid.encode()).hexdigest()[:16],'wall_s':round(time.monotonic()-started,3),'rounds':result.rounds,'tokens_in':result.tokens_in,'tokens_out':result.tokens_out,'cache_hit_tokens':result.tokens_cache_hit,'truncated':bool(result.truncated),'model_used':result.model_used,'fallback_used':bool(result.fallback_receipt),'tool_calls':[tool_entry(x) for x in (result.tool_calls or [])],'tool_call_count':len(result.tool_calls or []),'final_answer':result.final_answer or '','final_answer_sha256':hashlib.sha256((result.final_answer or '').encode()).hexdigest()[:16]})
 except Exception as e:
  row.update({'status':'WORKER_ERROR','error_type':type(e).__name__,'error':str(e)[:400],'wall_s':round(time.monotonic()-started,3)})
 finally:
  try:
   if engine is not None: engine.close()
  except Exception: pass
 pathlib.Path(args.out).parent.mkdir(parents=True,exist_ok=True)
 with open(args.out,'a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
 print(json.dumps({k:row.get(k) for k in ('status','kind','model_key','arm','case_id','attempt','wall_s','model_used','settlement_ok','run_end_completed')},ensure_ascii=False))
if __name__=='__main__': main()
