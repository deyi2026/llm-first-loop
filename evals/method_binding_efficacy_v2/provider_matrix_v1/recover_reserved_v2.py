#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[2]
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
PLAN=json.loads((HERE/'matrix_plan.json').read_text()); OUT=HERE/'run2_matrix.jsonl'; STATUS=HERE/'run2_status'; DATA=HERE/'run2_data'
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw,'LFL_CANONICAL_RUNTIME_ROOT must be explicit'
ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file()
reserved=[]
for p in sorted(STATUS.glob('*.json')):
 d=json.loads(p.read_text());
 if d.get('state')=='reserved': reserved.append((p,d))
assert len(reserved)==1,reserved
sp,state=reserved[0]; row=state['row']; assert row['ordinal']==len(list(STATUS.glob('*.json')))
prefix=f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}"
a0=DATA/f'{prefix}-a0'; a1=DATA/f'{prefix}-a1'
assert a0.is_dir(),'attempt0 namespace missing'; assert not a1.exists(),'attempt1 already exists'
# attempt0 was externally interrupted before worker append; preserve as explicit unhealthy mechanical evidence.
attempts=[{'attempt':0,'rc':-15,'healthy':False,'recovery_reason':'outer_command_timeout_interrupted_worker_before_settlement'}]

def child_env(data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[row['model']]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None)
 if row['arm']=='C1': e[BINDING_ENV]='1'
 return e

a1.mkdir(parents=True,exist_ok=False)
cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',row['model'],'--arm',row['arm'],'--case-id',row['case_id'],'--attempt','1','--out',str(OUT),'--data-dir',str(a1)]
cp=subprocess.run(cmd,env=child_env(a1),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip())
r=json.loads(OUT.read_text().splitlines()[-1]); attempts.append({'attempt':1,'rc':cp.returncode,'healthy':is_healthy(r)})
sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':attempts,'mechanically_healthy':attempts[-1]['healthy'],'recovered_reserved_identity':True},ensure_ascii=False,indent=1)+'\n')
print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'row_id':row['row_id'],'attempts':attempts},ensure_ascii=False))
