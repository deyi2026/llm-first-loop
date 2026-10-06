#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[3]
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw
ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file()
OUT=HERE/'preflight.jsonl'; DATA=HERE/'preflight_run_data'
def env(model,data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[model]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None); return e
def call(model):
 data=DATA/f'preflight-{model}-C0'; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',model,'--arm','C0','--out',str(OUT),'--data-dir',str(data),'--preflight']
 cp=subprocess.run(cmd,env=env(model,data),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); assert cp.returncode==0
 r=json.loads(OUT.read_text().splitlines()[-1]); assert is_healthy(r),r; assert 'PREFLIGHT_OK' in r.get('final_answer',''); return r
assert not OUT.exists() and not DATA.exists(); rows=[call('strong'),call('weak')]
(HERE/'PREFLIGHT.json').write_text(json.dumps({'schema':'subject-binding-v3-dev-c0-preflight/v1','rows':2,'all_healthy':True,'models':{m:MODELS[m] for m in MODELS}},ensure_ascii=False,indent=1)+'\n')
