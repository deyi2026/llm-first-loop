from __future__ import annotations
import hashlib,json,pathlib,random,re
H=pathlib.Path(__file__).resolve().parent; ROOT=H.parents[2]; D=ROOT/'evals/method_binding_efficacy_v3/dev_calibration_v1'
lab=json.loads((D/'LABEL-RESULT.json').read_text()); cand=json.loads((D/'dev_candidates.json').read_text())['rows']
def trigger(card):
 m=re.search(r'## Trigger\s*\n(.*?)(?=\n## |\Z)',card,re.S); assert m; return m.group(1).strip()
cases={}
for rr in lab['rows']:
 if rr['kind']=='challenge' and rr['dual_certified']:
  c=cand[rr['case_id']]; cases[c['case_id']]={k:c[k] for k in ['case_id','family','task','intended','subject_method_id','card','card_sha256']}; cases[c['case_id']]['carrier']='RESULT.md 摘要：'+trigger(c['card'])
assert len(cases)==22
seed=20261006; ids=list(cases); random.Random(seed+17).shuffle(ids); rows=[]; o=1
for i,cid in enumerate(ids):
 order=('strong','weak') if i%2==0 else ('weak','strong')
 for m in order: rows.append({'ordinal':o,'row_id':f'{m}:{cid}:C0:natural-v1','model':m,'arm':'C0','case_id':cid,'family':cases[cid]['family']});o+=1
plan={'schema':'subject-binding-v3-natural-dev-plan/v1','seed':seed+17,'models':{'strong':{'bare':'deepseek-v4-flash','canonical':'deepseek/deepseek-v4-flash'},'weak':{'bare':'cognilocal/qwen3.8-flash-next','canonical':'cognilocal/qwen3.8-flash-next'}},'cases':cases,'rows':rows}
(H/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=1)+'\n')
freeze={'schema':'subject-binding-v3-natural-dev-freeze/v1','provider_calls_at_freeze':0,'formal_cells':44,'files':{p:hashlib.sha256((H/p).read_bytes()).hexdigest() for p in ['PREREG.md','plan.json']},'source_dev_result_sha256':hashlib.sha256((D/'DEV-RESULT.json').read_bytes()).hexdigest()}
(H/'FREEZE.json').write_text(json.dumps(freeze,ensure_ascii=False,sort_keys=True,indent=1)+'\n'); print(json.dumps({'cells':44,'cases':22,'freeze':freeze},indent=2))
