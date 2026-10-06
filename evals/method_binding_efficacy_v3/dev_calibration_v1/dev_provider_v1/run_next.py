#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[3]
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
PLAN=json.loads((HERE/'matrix_plan.json').read_text()); OUT=HERE/'matrix.jsonl'; STATUS=HERE/'status'; DATA=HERE/'run_data'
def root_preflight():
 raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw,'LFL_CANONICAL_RUNTIME_ROOT must be explicit before reservation'
 root=pathlib.Path(raw).resolve(); assert root!=REPO.resolve(),'canonical runtime root must differ from isolated worktree'
 assert (root/'.env').is_file(); assert (root/'data'/'providers.local.json').is_file(); assert (root/'data'/'providers.json').is_file(); return root
def env_for(row,data,root):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(root); e['LLM_MODEL']=MODELS[row['model']]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None); return e
def invoke(row,a,root):
 data=DATA/f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-C0-a{a}"; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',row['model'],'--arm','C0','--case-id',row['case_id'],'--attempt',str(a),'--out',str(OUT),'--data-dir',str(data)]
 cp=subprocess.run(cmd,env=env_for(row,data,root),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip())
 r=json.loads(OUT.read_text().splitlines()[-1]); return cp.returncode,r
root=root_preflight(); STATUS.mkdir(exist_ok=True); DATA.mkdir(exist_ok=True)
terminal=sorted(STATUS.glob('*.json')); idx=len(terminal); assert idx < len(PLAN['formal_rows'])
row=PLAN['formal_rows'][idx]; assert row['ordinal']==idx+1 and row['arm']=='C0'
sp=STATUS/f"{row['ordinal']:03d}-{row['model']}-{row['case_id']}-C0.json"; assert not sp.exists()
prefix=f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-C0"; assert not any(DATA.glob(prefix+'-*'))
fd=os.open(sp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644); os.write(fd,json.dumps({'state':'reserved','row':row}).encode()); os.close(fd)
attempts=[]
rc,r=invoke(row,0,root); attempts.append({'attempt':0,'rc':rc,'healthy':is_healthy(r)})
if not is_healthy(r):
 rc,r=invoke(row,1,root); attempts.append({'attempt':1,'rc':rc,'healthy':is_healthy(r)})
sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':attempts,'mechanically_healthy':attempts[-1]['healthy']},ensure_ascii=False,indent=1)+'\n')
print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'row_id':row['row_id'],'attempts':attempts},ensure_ascii=False))
