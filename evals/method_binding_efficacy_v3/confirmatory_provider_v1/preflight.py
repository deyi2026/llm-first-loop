#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys,shutil
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]; sys.path.insert(0,str(H)); from protocol import MODELS,BINDING_ENV; from healthcheck import is_healthy
raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT'); assert raw; ROOT=pathlib.Path(raw).resolve(); assert ROOT!=REPO.resolve(); assert (ROOT/'.env').is_file(); assert (ROOT/'data'/'providers.local.json').is_file(); assert (ROOT/'data'/'providers.json').is_file(); OUT=H/'preflight.jsonl'; BASE=pathlib.Path('/tmp/lfl-sb-v3-confirmatory-preflight-v1'); assert not OUT.exists() and not BASE.exists(); BASE.mkdir()
def call(m,a):
 st=BASE/f'{m}-{a}'; (st/'data').mkdir(parents=True); (st/'methods').mkdir(); (st/'experiences').mkdir(); e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(ROOT); e['LLM_MODEL']=MODELS[m]['bare']; e['DATA_DIR']=str((st/'data').resolve()); e['METHODS_DIR']=str((st/'methods').resolve()); e['EXPERIENCES_DIR']=str((st/'experiences').resolve()); e.pop(BINDING_ENV,None)
 if a=='C1':e[BINDING_ENV]='1'
 cmd=[sys.executable,str(H/'worker.py'),'--model-key',m,'--arm',a,'--attempt','0','--out',str(OUT),'--data-dir',str(st/'data'),'--preflight']; cp=subprocess.run(cmd,cwd=str(REPO),env=e,capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); assert cp.returncode==0; r=json.loads(OUT.read_text().splitlines()[-1]); assert is_healthy(r); assert r.get('final_answer','').strip()=='PREFLIGHT_OK'; return r
rows=[call(m,a) for m in ('strong','weak') for a in ('C0','C1')]; (H/'PREFLIGHT.json').write_text(json.dumps({'schema':'subject-binding-v3-confirmatory-preflight/v1','rows':4,'all_healthy':True,'identities':[{'model':r['model_key'],'arm':r['arm'],'model_used':r['model_used'],'binding':r['binding_asserted']} for r in rows]},ensure_ascii=False,indent=1)+'\n'); print('PREFLIGHT_PASS')
