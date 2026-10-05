#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[2]
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw,'LFL_CANONICAL_RUNTIME_ROOT must be explicit'
ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file()
OUT=HERE/'preflight_v6.jsonl'; DATA=HERE/'preflight_run_data_v6'
def env(model,arm,data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[model]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None)
 if arm=='C1': e[BINDING_ENV]='1'
 return e
def call(model,arm):
 data=DATA/f'preflight-{model}-{arm}'; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',model,'--arm',arm,'--out',str(OUT),'--data-dir',str(data),'--preflight']
 cp=subprocess.run(cmd,env=env(model,arm,data),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); assert cp.returncode==0
 r=json.loads(OUT.read_text().splitlines()[-1]); assert is_healthy(r),r; assert 'PREFLIGHT_OK' in r.get('final_answer',''); return r
assert not OUT.exists(); assert not DATA.exists()
rows=[]
for m in ('strong','weak'):
 for a in ('C0','C1'): rows.append(call(m,a))
result={'schema':'subject-binding-efficacy-v2-run2-preflight/v1','rows':4,'all_healthy':True,'runtime_root_explicit':True,'models':{m:MODELS[m] for m in MODELS}}
(HERE/'PREFLIGHT-RUN2.json').write_text(json.dumps(result,ensure_ascii=False,indent=1)+'\n'); print(json.dumps(result,ensure_ascii=False))
