#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[2]
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
PLAN=json.loads((HERE/'matrix_plan.json').read_text()); OUT=HERE/'matrix.jsonl'; STATUS=HERE/'status'; CANONICAL_RUNTIME=pathlib.Path(os.environ.get('LFL_CANONICAL_RUNTIME_ROOT',str(REPO))).resolve()
def child_env(model,arm,data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(CANONICAL_RUNTIME); e['LLM_MODEL']=MODELS[model]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None)
 if arm=='C1': e[BINDING_ENV]='1'
 return e
def matrix_rows(): return [json.loads(x) for x in OUT.read_text().splitlines()] if OUT.exists() else []
def invoke(row,attempt):
 data=HERE/'run_data'/f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}-a{attempt}"
 data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',row['model'],'--arm',row['arm'],'--case-id',row['case_id'],'--attempt',str(attempt),'--out',str(OUT),'--data-dir',str(data)]
 cp=subprocess.run(cmd,env=child_env(row['model'],row['arm'],data),cwd=str(REPO),capture_output=True,text=True,timeout=540)
 print(cp.stdout.strip()); return cp.returncode,json.loads(OUT.read_text().splitlines()[-1])
STATUS.mkdir(exist_ok=True)
terminal=sorted(STATUS.glob('*.json'))
idx=len(terminal)
assert idx < len(PLAN['formal_rows']),'all formal rows already terminal'
row=PLAN['formal_rows'][idx]
assert row['ordinal']==idx+1
sp=STATUS/f"{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}.json"
# irreversible reservation: no preexisting row-specific namespace/status
assert not sp.exists(); prefix=f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}"
assert not any((HERE/'run_data').glob(prefix+'-*'))
fd=os.open(sp,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.write(fd,json.dumps({'state':'reserved','row':row}).encode()); os.close(fd)
attempts=[]
try:
 rc,r=invoke(row,0); attempts.append({'attempt':0,'rc':rc,'healthy':is_healthy(r)})
 if not is_healthy(r):
  rc,r=invoke(row,1); attempts.append({'attempt':1,'rc':rc,'healthy':is_healthy(r)})
 terminal={'state':'terminal','row':row,'attempts':attempts,'mechanically_healthy':attempts[-1]['healthy']}
 sp.write_text(json.dumps(terminal,ensure_ascii=False,indent=1)+'\n')
 print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'row_id':row['row_id'],'attempts':attempts},ensure_ascii=False))
except BaseException:
 # keep reserved file for recovery; never auto-delete/relaunch identity
 raise
