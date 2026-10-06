from __future__ import annotations
import hashlib,json,pathlib,random
H=pathlib.Path(__file__).resolve().parent
lab=json.loads((H/'LABEL-RESULT.json').read_text())
cands=json.loads((H/'dev_candidates.json').read_text())['rows']
assert lab['verdict']=='PASS'
selected=[]
for row in lab['rows']:
 if row['kind']=='challenge' and row['dual_certified']:
  c=cands[row['case_id']]
  selected.append({k:c[k] for k in ['case_id','family','task','intended','subject_method_id','source_method_id','shared_surface','purpose_divergence','card','card_sha256']})
assert len(selected)==22
seed=20261006
rnd=random.Random(seed); rnd.shuffle(selected)
formal=[]; ordinal=1
for i,c in enumerate(selected):
 order=('strong','weak') if i%2==0 else ('weak','strong')
 for model in order:
  formal.append({'ordinal':ordinal,'row_id':f"{model}:{c['case_id']}:C0",'model':model,'arm':'C0','case_id':c['case_id'],'family':c['family']}); ordinal+=1
assert len(formal)==44
plan={'schema':'subject-binding-v3-dev-c0-plan/v1','seed':seed,'source_label_result_sha256':hashlib.sha256((H/'LABEL-RESULT.json').read_bytes()).hexdigest(),'models':{'strong':{'bare':'deepseek-v4-flash','canonical':'deepseek/deepseek-v4-flash'},'weak':{'bare':'cognilocal/qwen3.8-flash-next','canonical':'cognilocal/qwen3.8-flash-next'}},'cases':{c['case_id']:c for c in selected},'formal_rows':formal}
(H/'dev_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=1)+'\n')
freeze={'schema':'subject-binding-v3-dev-freeze/v1','provider_calls_at_freeze':0,'selected_challenges':22,'formal_cells':44,'files':{p:hashlib.sha256((H/p).read_bytes()).hexdigest() for p in ['DEV-PREREG.md','dev_candidates.json','dev_sealed.json','R1.jsonl','R2.jsonl','LABEL-RESULT.json','dev_plan.json']}}
(H/'DEV-FREEZE.json').write_text(json.dumps(freeze,ensure_ascii=False,sort_keys=True,indent=1)+'\n')
print(json.dumps({'selected':len(selected),'families':{f:sum(c['family']==f for c in selected) for f in sorted({c['family'] for c in selected})},'formal_cells':len(formal),'freeze':freeze},ensure_ascii=False,indent=2))
