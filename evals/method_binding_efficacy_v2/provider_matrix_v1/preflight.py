#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent; REPO=HERE.parents[2]; ROOT=REPO.parents[0] if False else None
sys.path.insert(0,str(HERE)); from protocol import MODELS,BINDING_ENV,BINDING_MARKER; from healthcheck import is_healthy
CANONICAL_RUNTIME=pathlib.Path(os.environ.get('LFL_CANONICAL_RUNTIME_ROOT',str(REPO))).resolve()
OUT=HERE/'preflight_v5.jsonl'
def env(model,arm,data):
 e=dict(os.environ); e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH',''); e['LFL_RUNTIME_ROOT']=str(CANONICAL_RUNTIME); e['LLM_MODEL']=MODELS[model]['bare']; e['DATA_DIR']=str(data.resolve()); e.pop(BINDING_ENV,None)
 if arm=='C1': e[BINDING_ENV]='1'
 return e
def call(model,arm,kind):
 data=HERE/'preflight_run_data_v5'/f'{kind}-{model}-{arm}'; data.mkdir(parents=True,exist_ok=False)
 cmd=[sys.executable,str(HERE/'worker.py'),'--model-key',model,'--arm',arm,'--out',str(OUT),'--data-dir',str(data),'--'+('surface-only' if kind=='surface' else 'preflight')]
 cp=subprocess.run(cmd,env=env(model,arm,data),cwd=str(REPO),capture_output=True,text=True,timeout=540); print(cp.stdout.strip()); assert cp.returncode==0
 return json.loads(OUT.read_text().splitlines()[-1])
# namespaces must be fresh
assert not OUT.exists(); assert not (HERE/'preflight_run_data_v5').exists()
surfaces={}
for m in ('strong','weak'):
 for a in ('C0','C1'): surfaces[(m,a)]=call(m,a,'surface')
 for a in ('C0','C1'): assert surfaces[(m,a)]['status']=='SURFACE_ONLY'
 s0,s1=surfaces[(m,'C0')]['surface'],surfaces[(m,'C1')]['surface']; assert set(s0)==set(s1); assert {k for k in s0 if s0[k]!=s1[k]}=={'save_experience'}
# provider identity/settlement: 4 non-scored calls
pre=[]
for m in ('strong','weak'):
 for a in ('C0','C1'):
  r=call(m,a,'preflight'); assert is_healthy(r),r; assert 'PREFLIGHT_OK' in r.get('final_answer',''); pre.append(r)
out={'surface_diff_only_save_experience':True,'provider_preflight_rows':4,'all_provider_preflight_healthy':True,'models':{m:MODELS[m] for m in MODELS},'deviations':['DEV-PREFLIGHT-ENVLOAD: initial provider-free surface probe used worktree-default load_env_file(), found no worktree .env, and failed before engine/provider construction; provider_calls=0.','DEV-PREFLIGHT-V2-IMPORT: first explicit-runtime-root retry failed provider-free with worker NameError(os) before engine/provider construction; provider_calls=0.','DEV-PREFLIGHT-V3-WEAK-ROUTING: non-scored Weak C0 used the bare model ref and was routed to DeepSeek, producing HTTP400; formal rows remained 0/84.','DEV-PREFLIGHT-V4-DATA-DIR-REGISTRY: fully-qualified Weak ref still fell through to DeepSeek because fresh DATA_DIR omitted providers.local.json/providers.json. Formal rows remained 0/84. v5 copies canonical provider registry snapshots read-only into each fresh namespace and records hashes.']}
(HERE/'PREFLIGHT-RESULT.json').write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n'); print(json.dumps(out,ensure_ascii=False))
