from __future__ import annotations
import json,math,pathlib,collections,hashlib
H=pathlib.Path(__file__).resolve().parent

def load(p):
 d={}
 for line in p.read_text().splitlines():
  if line.strip():
   x=json.loads(line); assert x['opaque_id'] not in d; d[x['opaque_id']]=x
 return d

def kappa(a,b):
 n=len(a); po=sum(x==y for x,y in zip(a,b))/n
 ca,cb=collections.Counter(a),collections.Counter(b)
 pe=sum((ca[v]/n)*(cb[v]/n) for v in ('APPLY','SKIP'))
 return 1.0 if po==1 and pe==1 else (po-pe)/(1-pe)
sealed=json.loads((H/'dev_sealed.json').read_text())
r1=load(H/'R1.jsonl'); r2=load(H/'R2.jsonl'); ids=sealed['present_order']
assert set(r1)==set(r2)==set(ids)
a=[r1[i]['verdict'] for i in ids]; b=[r2[i]['verdict'] for i in ids]
po=sum(x==y for x,y in zip(a,b))/len(ids); kap=kappa(a,b)
rows=[]
for oid in ids:
 m=sealed['cases'][oid]; intended=m['intended']; x1=r1[oid]['verdict']; x2=r2[oid]['verdict']
 rows.append({'opaque_id':oid,**m,'r1':x1,'r2':x2,'agree':x1==x2,'r1_correct':x1==intended,'r2_correct':x2==intended,'dual_certified':x1==intended and x2==intended})
r1acc=sum(x['r1_correct'] for x in rows)/32; r2acc=sum(x['r2_correct'] for x in rows)/32
families=['same_object_different_action','same_evidence_different_claim','same_workflow_different_phase','same_infra_different_decision']
byfam={f:{'certified':sum(x['dual_certified'] for x in rows if x['family']==f),'n':sum(x['family']==f for x in rows)} for f in families}
challenge_cert=sum(x['dual_certified'] for x in rows if x['kind']=='challenge')
apply_cert=sum(x['dual_certified'] for x in rows if x['kind']=='apply_control')
candidates=json.loads((H/'dev_candidates.json').read_text())['rows']
anti={x['case_id']:candidates[x['case_id']]['anti_leak_hits'] for x in rows if x['kind']=='challenge'}
unresolved=sum(bool(v) for v in anti.values())
gates={'raw_agreement':po>=.85,'kappa':kap>=.70,'r1_intended_accuracy':r1acc>=.90,'r2_intended_accuracy':r2acc>=.90,'challenge_dual_certified':challenge_cert>=20,'each_family':all(v['certified']>=5 for v in byfam.values()),'apply_controls':apply_cert>=7,'anti_leak':unresolved==0}
res={'schema':'subject-binding-v3-dev-label-qualification/v1','verdict':'PASS' if all(gates.values()) else 'HOLD','raw_agreement':po,'kappa':kap,'r1_accuracy':r1acc,'r2_accuracy':r2acc,'challenge_dual_certified':challenge_cert,'apply_dual_certified':apply_cert,'families':byfam,'anti_leak_unresolved':unresolved,'gates':gates,'disagreements':[x for x in rows if not x['agree']],'uncertified':[x for x in rows if not x['dual_certified']],'certified_challenge_case_ids':[x['case_id'] for x in rows if x['kind']=='challenge' and x['dual_certified']],'input_sha256':{n:hashlib.sha256((H/n).read_bytes()).hexdigest() for n in ('DEV-PREREG.md','dev_candidates.json','dev_sealed.json','R1.jsonl','R2.jsonl')}}
(H/'LABEL-RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n')
print(json.dumps(res,ensure_ascii=False,indent=2))
