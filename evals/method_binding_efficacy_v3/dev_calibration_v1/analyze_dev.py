from __future__ import annotations
import json,pathlib,hashlib,collections
H=pathlib.Path(__file__).resolve().parent
from dev_protocol import parse_verdict
plan=json.loads((H/'dev_plan.json').read_text()); rows=[json.loads(x) for x in (H/'dev_matrix.jsonl').read_text().splitlines() if x.strip()]
assert len(rows)==44
status=list((H/'dev_status').glob('*.json')); assert len(status)==44 and all(json.loads(p.read_text()).get('mechanically_healthy') is True for p in status)
latest={(r['model_key'],r['case_id']):r for r in rows if r.get('kind')=='formal'}; assert len(latest)==44
outrows=[]
for (model,cid),r in latest.items():
 v=parse_verdict(r.get('final_answer','')); c=plan['cases'][cid]; outrows.append({'model':model,'case_id':cid,'family':c['family'],'verdict':v,'expected':'SKIP','correct':v=='SKIP','final_answer':r.get('final_answer',''),'healthy':True})
fams={}
for fam in sorted({x['family'] for x in outrows}):
 fams[fam]={}
 for model in ('strong','weak'):
  rr=[x for x in outrows if x['family']==fam and x['model']==model]; acc=sum(x['correct'] for x in rr)/len(rr); fams[fam][model]={'n':len(rr),'correct':sum(x['correct'] for x in rr),'accuracy':acc,'errors':[x['case_id'] for x in rr if not x['correct']]}
 weak=fams[fam]['weak']['accuracy']; strong=fams[fam]['strong']['accuracy']; fams[fam]['viable']=(0.45<=weak<=0.80 and not(strong==1.0 and weak==1.0))
viable=[f for f,v in fams.items() if v['viable']]
res={'schema':'subject-binding-v3-dev-difficulty-result/v1','verdict':'PASS' if viable else 'HOLD','formal_cells':44,'all_healthy':True,'families':fams,'viable_families':viable,'rows':outrows,'inputs':{p:hashlib.sha256((H/p).read_bytes()).hexdigest() for p in ['DEV-PREREG.md','DEV-FREEZE.json','dev_plan.json','dev_matrix.jsonl']}}
(H/'DEV-RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n')
print(json.dumps({k:res[k] for k in ['verdict','families','viable_families']},ensure_ascii=False,indent=2))
