from __future__ import annotations
import hashlib,json,os,pathlib,subprocess,sys
H=pathlib.Path(__file__).resolve().parent; REPO=H.parents[2]
SCRIPT='''import json,os,sys;sys.path.insert(0,{src!r});from llm_loop.introspection import registry_experience as r;defs=r.tool_defs();print(json.dumps(defs,sort_keys=True,ensure_ascii=False))'''
def defs(arm):
 e=dict(os.environ); e.pop('LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL',None)
 if arm=='C1':e['LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL']='1'
 cp=subprocess.run([sys.executable,'-c',SCRIPT.format(src=str(REPO/'src'))],env=e,capture_output=True,text=True,check=True); return json.loads(cp.stdout)
a,b=defs('C0'),defs('C1'); da={x['name']:x for x in a}; db={x['name']:x for x in b}; assert set(da)==set(db); changed=[]
for n in sorted(da):
 if da[n]!=db[n]:changed.append(n)
assert changed==['save_experience'],changed; d0=da['save_experience']['description']; d1=db['save_experience']['description']; assert 'lfl-method-applicability-subject-binding/v1' not in d0 and 'lfl-method-applicability-subject-binding/v1' in d1
res={'tool_names_same':True,'changed_tools':changed,'marker_c0':False,'marker_c1':True,'c0_sha256':hashlib.sha256(json.dumps(a,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'c1_sha256':hashlib.sha256(json.dumps(b,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}; (H/'SURFACE-PROBE.json').write_text(json.dumps(res,indent=1)+'\n'); print(json.dumps(res))
