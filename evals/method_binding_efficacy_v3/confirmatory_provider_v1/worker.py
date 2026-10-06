#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,pathlib,shutil,sys,time
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H)); sys.path.insert(0,str(REPO/'src'))
from protocol import MODELS,BINDING_ENV,BINDING_MARKER,PROMPT,PREFLIGHT_PROMPT

def events(data,sid):
 p=pathlib.Path(data)/'event_logs'/f'{sid}.jsonl'; out=[]
 if p.exists():
  for x in p.read_text().splitlines():
   try:out.append(json.loads(x))
   except:pass
 return out
def settlement(ev):
 po=[e for e in ev if e.get('type')=='provider.call.opened']; ps=[e for e in ev if e.get('type')=='provider.call.settled']; to=[e for e in ev if e.get('type')=='provider.transport.opened']; ts=[e for e in ev if e.get('type')=='provider.transport.settled']; ends=[e for e in ev if e.get('type')=='run.end']
 ok=len(po)==len(ps)>0 and len(to)==len(ts)>0 and all((e.get('payload')or{}).get('outcome')=='success' for e in ps) and all((e.get('payload')or{}).get('outcome')=='success' and (e.get('payload')or{}).get('status_code')==200 for e in ts); end=(ends[-1].get('payload')or{}) if ends else {}
 return {'settlement_ok':ok,'provider_calls_opened':len(po),'provider_calls_settled':len(ps),'transports_opened':len(to),'transports_settled':len(ts),'run_end_completed':end.get('reason')=='completed'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--model-key',required=True,choices=['strong','weak']); ap.add_argument('--arm',required=True,choices=['C0','C1']); ap.add_argument('--case-id'); ap.add_argument('--attempt',type=int,default=0); ap.add_argument('--out',required=True); ap.add_argument('--data-dir',required=True); ap.add_argument('--preflight',action='store_true'); args=ap.parse_args(); started=time.monotonic(); row={'kind':'preflight' if args.preflight else 'formal','model_key':args.model_key,'arm':args.arm,'case_id':args.case_id,'attempt':args.attempt}; engine=None
 try:
  from llm_loop.config import load_env_file,load_settings
  from llm_loop.factory import build_engine
  from llm_loop.introspection import registry_experience as reg
  from llm_loop.core.trace_leak.ingress_token import issue_ingress
  runtime=pathlib.Path(os.environ['LFL_RUNTIME_ROOT']).resolve(); data=pathlib.Path(args.data_dir).resolve(); methods=pathlib.Path(os.environ['METHODS_DIR']).resolve(); experiences=pathlib.Path(os.environ['EXPERIENCES_DIR']).resolve(); exp=MODELS[args.model_key]
  for n in ('providers.local.json','providers.json'):
   s=runtime/'data'/n
   if s.is_file(): shutil.copy2(s,data/n)
  load_env_file(runtime/'.env'); settings=load_settings(); assert settings.llm_model==exp['bare']; assert pathlib.Path(settings.data_dir).resolve()==data; assert pathlib.Path(settings.methods_dir).resolve()==methods; assert pathlib.Path(settings.experiences_dir).resolve()==experiences
  desc=next(x for x in reg.tool_defs() if x['name']=='save_experience')['description']; binding=BINDING_MARKER in desc; assert binding==(args.arm=='C1'); engine=build_engine(settings); sid=engine.session.create()
  if args.preflight: prompt=PREFLIGHT_PROMPT; c=None
  else:
   plan=json.loads((H/'plan.json').read_text()); c=plan['cases'][args.case_id]; methods.mkdir(parents=True,exist_ok=True); experiences.mkdir(parents=True,exist_ok=True); shutil.copytree(REPO/'data'/'methods'/c['subject_method_id'],methods/c['subject_method_id']); prompt=PROMPT.format(task=c['task'],carrier=c['carrier'],card=c['card'],method_ref='method:'+c['subject_method_id'])
  result=engine.run(sid,prompt,ingress=issue_ingress('cli')); row.update(settlement(events(data,sid))); calls=[getattr(x,'name',None) or (x.get('name') if isinstance(x,dict) else '?') for x in (result.tool_calls or [])]
  row.update({'status':'RUN_OK','binding_asserted':binding,'model_used':result.model_used,'fallback_used':bool(result.fallback_receipt),'truncated':bool(result.truncated),'rounds':result.rounds,'tokens_in':result.tokens_in,'tokens_out':result.tokens_out,'tool_calls':calls,'tool_call_count':len(calls),'final_answer':result.final_answer or '','wall_s':round(time.monotonic()-started,3)})
  if c is not None:
   usage=[]; up=methods/'usage.jsonl'
   if up.exists():
    for x in up.read_text().splitlines():
     try:usage.append(json.loads(x))
     except:pass
   own=[x for x in usage if x.get('method_ref')=='method:'+c['subject_method_id']]; decs=[str(x.get('decision')or'') for x in own]
   row.update({'row_id':f"{args.model_key}:{args.case_id}:{args.arm}:natural-confirm-v1",'family':c['family'],'intended':c['intended'],'case_kind':c['kind'],'method_manage_calls':calls.count('method_manage'),'save_experience_calls':calls.count('save_experience'),'record_use_decisions':decs,'record_use_count':len(decs),'experience_file_count':len(list(experiences.glob('EXPERIENCE-*.md')))})
 except Exception as e: row.update({'status':'WORKER_ERROR','error_type':type(e).__name__,'error':str(e)[:500],'wall_s':round(time.monotonic()-started,3)})
 finally:
  try:
   if engine is not None: engine.close()
  except:pass
 with open(args.out,'a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 print(json.dumps({k:row.get(k) for k in ('status','model_key','arm','case_id','attempt','model_used','binding_asserted','settlement_ok','run_end_completed','record_use_decisions','experience_file_count','wall_s')},ensure_ascii=False))
if __name__=='__main__':main()
