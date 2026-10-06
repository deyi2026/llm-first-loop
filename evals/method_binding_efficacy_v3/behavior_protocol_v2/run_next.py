#!/usr/bin/env python3
from __future__ import annotations
import json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent;REPO=H.parents[2];sys.path.insert(0,str(H));from protocol import MODELS,BINDING_ENV
PLAN=json.loads((H/'plan.json').read_text());OUT=H/'matrix.jsonl';STATUS=H/'status';BASE=pathlib.Path('/tmp/lfl-sb-v3-natural-v2-e347fe3fa')
def healthy(r):return r.get('status')=='RUN_OK' and r.get('model_used')==MODELS[r['model_key']]['canonical'] and not r.get('fallback_used') and not r.get('truncated') and r.get('settlement_ok') is True and r.get('run_end_completed') is True
def root_preflight():
 raw=os.environ.get('LFL_CANONICAL_RUNTIME_ROOT');assert raw;root=pathlib.Path(raw).resolve();assert root!=REPO.resolve();assert (root/'.env').is_file();assert (root/'data'/'providers.local.json').is_file();assert (root/'data'/'providers.json').is_file();return root
def env(row,state,root):
 e=dict(os.environ);e['PYTHONPATH']=str(REPO/'src')+os.pathsep+e.get('PYTHONPATH','');e['LFL_RUNTIME_ROOT']=str(root);e['LLM_MODEL']=MODELS[row['model']]['bare'];e['DATA_DIR']=str((state/'data').resolve());e['METHODS_DIR']=str((state/'methods').resolve());e['EXPERIENCES_DIR']=str((state/'experiences').resolve());e.pop(BINDING_ENV,None);return e
def invoke(row,a,root):
 state=BASE/f"nat2-{row['ordinal']:03d}-{row['model']}-{row['case_id']}-a{a}";assert not state.exists();(state/'data').mkdir(parents=True);cmd=[sys.executable,str(H/'worker.py'),'--model-key',row['model'],'--arm','C0','--case-id',row['case_id'],'--attempt',str(a),'--out',str(OUT),'--data-dir',str(state/'data')];cp=subprocess.run(cmd,cwd=str(REPO),env=env(row,state,root),capture_output=True,text=True,timeout=540);print(cp.stdout.strip());return cp.returncode,json.loads(OUT.read_text().splitlines()[-1])
root=root_preflight();STATUS.mkdir(exist_ok=True);BASE.mkdir(parents=True,exist_ok=True);idx=len(list(STATUS.glob('*.json')));assert idx<len(PLAN['rows']);row=PLAN['rows'][idx];assert row['ordinal']==idx+1;sp=STATUS/f"{row['ordinal']:03d}-{row['model']}-{row['case_id']}.json";assert not sp.exists();fd=os.open(sp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644);os.write(fd,json.dumps({'state':'reserved','row':row}).encode());os.close(fd);ats=[];rc,r=invoke(row,0,root);ats.append({'attempt':0,'rc':rc,'healthy':healthy(r)});
if not healthy(r):rc,r=invoke(row,1,root);ats.append({'attempt':1,'rc':rc,'healthy':healthy(r)})
sp.write_text(json.dumps({'state':'terminal','row':row,'attempts':ats,'mechanically_healthy':ats[-1]['healthy']},ensure_ascii=False,indent=1)+'\n');print(json.dumps({'terminal':True,'ordinal':row['ordinal'],'attempts':ats},ensure_ascii=False))
