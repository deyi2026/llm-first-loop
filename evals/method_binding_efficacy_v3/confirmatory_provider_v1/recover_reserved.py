#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
PLAN=json.loads((H/'plan.json').read_text()); OUT=H/'matrix.jsonl'; STATUS=H/'status'; BASE=pathlib.Path('/tmp/lfl-sb-v3-confirmatory-v1')
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw; ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file()
res=[]
for p in sorted(STATUS.glob('*.json')):
 d=json.loads(p.read_text())
 if d.get('state')=='reserved':res.append((p,d))
assert len(res)==1,res; sp,state=res[0]; row=state['row']; prefix=f"formal-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-{row['arm']}"; a0=BASE/f'{prefix}-a0'; a1=BASE/f'{prefix}-a1'; assert a0.is_dir() and not a1.exists(); attempts=[{'attempt':0,'rc':-15,'healthy':False,'recovery_reason':'outer_command_interrupted_before_terminal_status'}]
def env(st):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[row['model']]['bare']; e['DATA_DIR']=str((st/'data').resolve()); e['METHODS_DIR']=str((st/'methods').resolve()); e['EXPERIENCES_DIR']=str((st/'experiences').resolve()); e.pop(BINDING_ENV,None)
 if row['arm']=='C1':e[BINDING_ENV]='1'
 return e
a1.mkdir(parents=True); (a1/'data').mkdir(); (a1/'methods').mkdir(); (a1/'experiences').mkdir(); cmd=[sys.executable,str(H/'worker.py'),'--model-key',row['model'],'--arm',row['arm'],'--case-id',row['case_id'],'--attempt','1','--out',str(OUT),'--data-dir',str(a1/'data')]; cp=subprocess.run(cmd,cwd=str(REPO),env=env(a1),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); r=json.loads(OUT.read_text().splitlines()[-1]); attempts.append({'attempt':1,'rc':cp.returncode,'healthy':is_healthy(r)}); sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':attempts,'mechanically_healthy':attempts[-1]['healthy'],'recovered_reserved_identity':True},ensure_ascii=False,indent=1)+'\n'); print(json.dumps({'ordinal':row['ordinal'],'attempts':attempts},ensure_ascii=False))
