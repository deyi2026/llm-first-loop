from __future__ import annotations
import hashlib,json,math,pathlib
from collections import Counter

H=pathlib.Path(__file__).resolve().parent

def h(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def scores(p):
 d={}
 for line in p.read_text(encoding='utf-8').splitlines():
  if not line.strip(): continue
  o=json.loads(line); assert o['verdict'] in {'APPLY','SKIP'}; assert o['opaque_id'] not in d; assert str(o.get('reason','')).strip(); d[o['opaque_id']]=o
 return d

def kappa(a,b):
 n=len(a); po=sum(x==y for x,y in zip(a,b))/n; ca,cb=Counter(a),Counter(b); pe=sum((ca[v]/n)*(cb[v]/n) for v in ('APPLY','SKIP'))
 return 1.0 if pe==1.0 and po==1.0 else (po-pe)/(1-pe)

sealed=json.loads((H/'goldset_sealed.json').read_text(encoding='utf-8'))
r1=scores(H/'R1.jsonl'); r2=scores(H/'R2.jsonl'); ids=sealed['present_order']
assert set(ids)==set(r1)==set(r2) and len(ids)==40
A=[r1[i]['verdict'] for i in ids]; B=[r2[i]['verdict'] for i in ids]
raw=sum(x==y for x,y in zip(A,B))/40; kap=kappa(A,B)
per=[]
for oid in ids:
 m=sealed['cases'][oid]; ok=r1[oid]['verdict']==m['intended'] and r2[oid]['verdict']==m['intended']
 per.append({'opaque_id':oid,'case_id':m['case_id'],'cell':m['cell'],'intended':m['intended'],'r1':r1[oid]['verdict'],'r2':r2[oid]['verdict'],'r1_reason':r1[oid]['reason'],'r2_reason':r2[oid]['reason'],'certified':ok,'subject_method_id':m['subject_method_id'],'construction_source':m['construction_source'],'purpose_divergence':m['purpose_divergence']})
cell={}
for c in 'ABCD':
 rows=[x for x in per if x['cell']==c]; cell[c]={'certified':sum(x['certified'] for x in rows),'n':len(rows),'failures':[x['case_id'] for x in rows if not x['certified']]}
hp=cell['B']['certified']; hm=cell['C']['certified']; need=math.ceil(.20*16)
gates={'raw_agreement':raw>=.85,'kappa':kap>=.70,'A':cell['A']['certified']>=7,'B_H_plus':hp>=12,'C_H_minus':hm>=6,'D':cell['D']['certified']>=7,'freshness':True,'B_purpose_metadata':True,'structural_reachability':hp>=2*need and hm>=6}
verdict='PASS' if all(gates.values()) else 'HOLD'
res={'schema':'subject-binding-efficacy-v2-goldset-result/v1','verdict':verdict,'devs':['DEV-RATER: R1 and R2 are independent fresh web-gpt proxy sessions, each split into four 10-case blind batches; this is model-by-model agreement, not human inter-rater evidence.','DEV-TRANSPORT: initial single 40-case R1 message produced no readable score artifact and was excluded; prereg labels were never opened; scoring was restarted as frozen 4x10 blind batches before any result analysis.'],'inputs':{'prereg_sha256':h(H/'GOLDSET-PREREG.md'),'builder_sha256':h(H/'goldset_build.py'),'sealed_sha256':h(H/'goldset_sealed.json'),'sheet_sha256':h(H/'GOLDSET-SHEET.md'),'r1_sha256':h(H/'R1.jsonl'),'r2_sha256':h(H/'R2.jsonl')},'raw_agreement':raw,'kappa':kap,'disagreement_count':sum(x!=y for x,y in zip(A,B)),'cells':cell,'H_plus':hp,'H_minus':hm,'provisional_future_challenge_effect':.20,'net_flip_need':need,'reachability_margin_H_plus':hp-need,'gates':gates,'per_case':per}
(H/'GOLDSET-RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
md=['# Subject-Binding Efficacy v2 - Fresh Goldset Qualification','',f'**Verdict: {verdict}**','',f'- raw agreement: {raw:.3f}',f'- Cohen kappa: {kap:.3f}',f'- disagreements: {res["disagreement_count"]}/40',f'- A ceiling: {cell["A"]["certified"]}/8',f'- B / H+: {hp}/16',f'- C / H-: {hm}/8',f'- D floor: {cell["D"]["certified"]}/8',f'- structural reachability: future provisional challenge effect +0.20 => need={need}; certified H+={hp}; H-={hm}; gate={gates["structural_reachability"]}','','## Deviations','',*['- '+x for x in res['devs']], '', 'This result qualifies only the fresh measurement goldset. It does not run or qualify subject-binding efficacy.']
(H/'GOLDSET-RESULT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
print(json.dumps({k:res[k] for k in ('verdict','raw_agreement','kappa','disagreement_count','cells','H_plus','H_minus','net_flip_need','gates')},ensure_ascii=False,indent=2))
print('RESULT_SHA',h(H/'GOLDSET-RESULT.json'))
print('MD_SHA',h(H/'GOLDSET-RESULT.md'))
