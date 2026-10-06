#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H))
from dev_protocol import MODELS,BINDING_ENV
from healthcheck import is_healthy
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw; ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file()
OUT=H/'dev_preflight.jsonl'; DATA=H/'dev_preflight_data'
def env(model,data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[model]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None); return e
assert not OUT.exists() and not DATA.exists(); rows=[]
for model in ('strong','weak'):
 data=DATA/model; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(H/'dev_worker.py'),'--model-key',model,'--preflight','--out',str(OUT),'--data-dir',str(data)]
 cp=subprocess.run(cmd,env=env(model,data),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); assert cp.returncode==0
 row=json.loads(OUT.read_text().splitlines()[-1]); assert is_healthy(row),row; assert row['model_used']==MODELS[model]['canonical']; assert 'PREFLIGHT_OK' in row['final_answer']; rows.append(row)
res={'schema':'subject-binding-v3-dev-preflight/v1','rows':2,'all_healthy':True,'models':{m:MODELS[m] for m in MODELS}}
(H/'DEV-PREFLIGHT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n'); print(json.dumps(res,ensure_ascii=False))
