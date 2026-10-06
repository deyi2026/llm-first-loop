#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
PLAN=json.loads((H/'plan.json').read_text()); OUT=H/'matrix.jsonl'; STATUS=H/'status'; BASE=pathlib.Path('/tmp/lfl-sb-v3-confirmatory-v1')
def root_preflight():
 raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw,'LFL_CANONICAL_RUNTIME_ROOT must be explicit before reservation'; root=pathlib.Path(raw).resolve(); assert root!=REPO.resolve(); assert (root/'.env').is_file(); assert (root/'data'/'providers.local.json').is_file(); assert (root/'data'/'providers.json').is_file(); return root
def env(row,state,root):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(root); e['LLM_MODEL']=MODELS[row['model']]['bare']; e['DATA_DIR']=str((state/'data').resolve()); e['METHODS_DIR']=str((state/'methods').resolve()); e['EXPERIENCES_DIR']=str((state/'experiences').resolve()); e.pop(BINDING_ENV,None)
 if row['arm']=='C1': e[BINDING_ENV]='1'
 return e
def invoke(row,a,root):
 state=BASE/f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}-a{a}"; assert not state.exists(); (state/'data').mkdir(parents=True); (state/'methods').mkdir(); (state/'experiences').mkdir(); cmd=[sys.executable,str(H/'worker.py'),'--model-key',row['model'],'--arm',row['arm'],'--case-id',row['case_id'],'--attempt',str(a),'--out',str(OUT),'--data-dir',str(state/'data')]; cp=subprocess.run(cmd,cwd=str(REPO),env=env(row,state,root),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); return cp.returncode,json.loads(OUT.read_text().splitlines()[-1])
root=root_preflight(); STATUS.mkdir(exist_ok=True); BASE.mkdir(parents=True,exist_ok=True); terminal=sorted(STATUS.glob('*.json')); idx=len(terminal); assert idx<len(PLAN['rows']); row=PLAN['rows'][idx]; assert row['ordinal']==idx+1; sp=STATUS/f"{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}.json"; assert not sp.exists(); prefix=f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}"; assert not any(BASE.glob(prefix+'-*'))
fd=os.open(sp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644); os.write(fd,json.dumps({'state':'reserved','row':row}).encode()); os.close(fd); ats=[]
rc,r=invoke(row,0,root); ats.append({'attempt':0,'rc':rc,'healthy':is_healthy(r)})
if not is_healthy(r): rc,r=invoke(row,1,root); ats.append({'attempt':1,'rc':rc,'healthy':is_healthy(r)})
sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':ats,'mechanically_healthy':ats[-1]['healthy']},ensure_ascii=False,indent=1)+'\n'); print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'row_id':row['row_id'],'attempts':ats},ensure_ascii=False))
