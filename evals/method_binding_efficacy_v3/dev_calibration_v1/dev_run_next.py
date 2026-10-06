#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H))
from dev_protocol import MODELS,BINDING_ENV
from healthcheck import is_healthy
PLAN=json.loads((H/'dev_plan.json').read_text()); OUT=H/'dev_matrix.jsonl'; STATUS=H/'dev_status'; DATA=H/'dev_run_data'
def root_preflight():
 raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw,'explicit LFL_CANONICAL_RUNTIME_ROOT required before reservation'; root=pathlib.Path(raw).resolve(); assert root!=REPO.resolve(); assert (root/'.env').is_file(); assert (root/'data'/'providers.local.json').is_file(); assert (root/'data'/'providers.json').is_file(); return root
def env(row,data,root):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(root); e['LLM_MODEL']=MODELS[row['model']]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None); return e
def invoke(row,attempt,root):
 data=DATA/f"dev-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-a{attempt}"; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(H/'dev_worker.py'),'--model-key',row['model'],'--case-id',row['case_id'],'--attempt',str(attempt),'--out',str(OUT),'--data-dir',str(data)]
 cp=subprocess.run(cmd,env=env(row,data,root),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); return cp.returncode,json.loads(OUT.read_text().splitlines()[-1])
root=root_preflight(); STATUS.mkdir(exist_ok=True); DATA.mkdir(exist_ok=True); idx=len(list(STATUS.glob('*.json'))); assert idx<len(PLAN['formal_rows']); row=PLAN['formal_rows'][idx]; assert row['ordinal']==idx+1
sp=STATUS/f"{row['ordinal']:03d}-{row['model']}-{row['case_id']}.json"; assert not sp.exists(); prefix=f"dev-{row['ordinal']:03d}-{row['model']}-{row['case_id']}"; assert not any(DATA.glob(prefix+'-*'))
fd=os.open(sp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644); os.write(fd,json.dumps({'state':'reserved','row':row}).encode()); os.close(fd)
at=[]; rc,r=invoke(row,0,root); at.append({'attempt':0,'rc':rc,'healthy':is_healthy(r)})
if not is_healthy(r): rc,r=invoke(row,1,root); at.append({'attempt':1,'rc':rc,'healthy':is_healthy(r)})
sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':at,'mechanically_healthy':at[-1]['healthy']},ensure_ascii=False,indent=1)+'\n'); print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'row_id':row['row_id'],'attempts':at},ensure_ascii=False))
