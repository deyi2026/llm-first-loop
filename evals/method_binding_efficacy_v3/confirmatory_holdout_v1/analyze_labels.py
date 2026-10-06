from __future__ import annotations
import collections,hashlib,json,pathlib
H=pathlib.Path(__file__).resolve().parent

def load(p):
 d={}
 for line in p.read_text().splitlines():
  if not line.strip(): continue
  x=json.loads(line); assert x['opaque_id'] not in d; assert x['verdict'] in {'APPLY','SKIP'}; assert str(x.get('reason','')).strip(); d[x['opaque_id']]=x
 return d

def kappa(a,b):
 n=len(a); po=sum(x==y for x,y in zip(a,b))/n
 ca,cb=collections.Counter(a),collections.Counter(b)
 pe=sum((ca[v]/n)*(cb[v]/n) for v in ('APPLY','SKIP'))
 return 1.0 if po==1 and pe==1 else (po-pe)/(1-pe)

sealed=json.loads((H/'sealed.json').read_text()); ids=sealed['present_order']
r1=load(H/'R1.jsonl'); r2=load(H/'R2.jsonl')
assert set(r1)==set(r2)==set(ids)
a=[r1[i]['verdict'] for i in ids]; b=[r2[i]['verdict'] for i in ids]
po=sum(x==y for x,y in zip(a,b))/len(ids); kap=kappa(a,b)
rows=[]
for oid in ids:
 m=sealed['cases'][oid]; intended=m['intended']; x1=r1[oid]['verdict']; x2=r2[oid]['verdict']
 rows.append({'opaque_id':oid,**m,'r1':x1,'r2':x2,'agree':x1==x2,'r1_correct':x1==intended,'r2_correct':x2==intended,'dual_certified':x1==intended and x2==intended})
r1acc=sum(x['r1_correct'] for x in rows)/len(rows); r2acc=sum(x['r2_correct'] for x in rows)/len(rows)
families=['same_object_different_action','same_evidence_different_claim','same_workflow_different_phase']
byfam={f:{'certified':sum(x['dual_certified'] for x in rows if x['family']==f),'n':sum(x['family']==f for x in rows)} for f in families}
challenge_cert=sum(x['dual_certified'] for x in rows if x['kind']=='challenge')
apply_cert=sum(x['dual_certified'] for x in rows if x['kind']=='apply_reverse_risk')
cands=json.loads((H/'candidates.json').read_text())['cases']
unresolved=sum(bool(cands[x['case_id']]['anti_leak_hits']) for x in rows if x['kind']=='challenge' and x['dual_certified'])
gates={
 'raw_agreement':po>=.85,
 'kappa':kap>=.70,
 'r1_intended_accuracy':r1acc>=.90,
 'r2_intended_accuracy':r2acc>=.90,
 'challenge_dual_certified':challenge_cert>=15,
 'each_family':all(v['certified']>=5 for v in byfam.values()),
 'reverse_risk_apply':apply_cert>=5,
 'anti_leak':unresolved==0,
}
res={
 'schema':'subject-binding-v3-confirmatory-label-qualification/v1',
 'verdict':'PASS' if all(gates.values()) else 'HOLD',
 'raw_agreement':po,'kappa':kap,'r1_accuracy':r1acc,'r2_accuracy':r2acc,
 'challenge_dual_certified':challenge_cert,'reverse_risk_apply_dual_certified':apply_cert,
 'families':byfam,'anti_leak_unresolved':unresolved,'gates':gates,
 'disagreements':[x for x in rows if not x['agree']],
 'uncertified':[x for x in rows if not x['dual_certified']],
 'certified_case_ids':[x['case_id'] for x in rows if x['dual_certified']],
 'certified_challenge_case_ids':[x['case_id'] for x in rows if x['kind']=='challenge' and x['dual_certified']],
 'certified_reverse_risk_case_ids':[x['case_id'] for x in rows if x['kind']=='apply_reverse_risk' and x['dual_certified']],
 'input_sha256':{n:hashlib.sha256((H/n).read_bytes()).hexdigest() for n in ('PREREG.md','candidates.json','sealed.json','R1.jsonl','R2.jsonl')}
}
(H/'LABEL-RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n')
print(json.dumps({k:res[k] for k in ('verdict','raw_agreement','kappa','r1_accuracy','r2_accuracy','challenge_dual_certified','reverse_risk_apply_dual_certified','families','anti_leak_unresolved','gates')},ensure_ascii=False,indent=2))
