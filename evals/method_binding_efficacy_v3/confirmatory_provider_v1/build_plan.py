from __future__ import annotations
import hashlib,json,pathlib,random
H=pathlib.Path(__file__).resolve().parent; ROOT=H.parents[2]
LABEL=ROOT/'evals/method_binding_efficacy_v3/confirmatory_holdout_v1/LABEL-RESULT.json'
CANDS=ROOT/'evals/method_binding_efficacy_v3/confirmatory_holdout_v1/candidates.json'
DEV=ROOT/'evals/method_binding_efficacy_v3/behavior_protocol_v2/RESULT.json'
SPEC=H/'SPEC.md'; SEED=20261024
lab=json.loads(LABEL.read_text()); dev=json.loads(DEV.read_text()); cand=json.loads(CANDS.read_text())['cases']
assert lab['verdict']=='PASS' and dev['verdict']=='PASS'
ids=lab['certified_case_ids']; assert len(ids)==23 and len(set(ids))==23
cases={cid:{k:cand[cid][k] for k in ('case_id','kind','family','intended','subject_method_id','task','carrier','card','card_sha256')} for cid in ids}
assert sum(c['kind']=='challenge' for c in cases.values())==17
assert sum(c['kind']=='apply_reverse_risk' for c in cases.values())==6
blocks=[{'model':m,'case_id':cid} for cid in ids for m in ('strong','weak')]
random.Random(SEED).shuffle(blocks)
seen={'strong':0,'weak':0}; rows=[]; first={'strong':{'C0':0,'C1':0},'weak':{'C0':0,'C1':0}}
for bi,b in enumerate(blocks,1):
 m=b['model']; j=seen[m]; seen[m]+=1
 # strong: C0 first at even local indices => 12/11; weak opposite => 11/12
 c0first=(j%2==0) if m=='strong' else (j%2==1)
 arms=('C0','C1') if c0first else ('C1','C0'); first[m][arms[0]]+=1
 for arm in arms:
  ordinal=len(rows)+1; rid=f"{m}:{b['case_id']}:{arm}:natural-confirm-v1"
  rows.append({'ordinal':ordinal,'block':bi,'row_id':rid,'model':m,'case_id':b['case_id'],'arm':arm})
assert len(rows)==92 and len({r['row_id'] for r in rows})==92
for i in range(0,92,2): assert rows[i]['model']==rows[i+1]['model'] and rows[i]['case_id']==rows[i+1]['case_id'] and {rows[i]['arm'],rows[i+1]['arm']}=={'C0','C1'}
assert first=={'strong':{'C0':12,'C1':11},'weak':{'C0':11,'C1':12}}, first
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan={'schema':'subject-binding-v3-confirmatory-plan/v1','seed':SEED,'models':{'strong':{'bare':'deepseek-v4-flash','canonical':'deepseek/deepseek-v4-flash'},'weak':{'bare':'cognilocal/qwen3.8-flash-next','canonical':'cognilocal/qwen3.8-flash-next'}},'cases':cases,'rows':rows,'arm_first':first,'source_sha256':{'label_result':sha(LABEL),'candidates':sha(CANDS),'dev_result':sha(DEV),'spec':sha(SPEC)}}
(H/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=1)+'\n')
print(json.dumps({'cases':len(cases),'challenge':sum(c['kind']=='challenge' for c in cases.values()),'reverse':sum(c['kind']=='apply_reverse_risk' for c in cases.values()),'rows':len(rows),'arm_first':first},ensure_ascii=False))
