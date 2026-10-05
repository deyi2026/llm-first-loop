from __future__ import annotations
import hashlib,json,math,pathlib,random
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[3]
G=HERE.parent
SEED=20261006
MODELS={
 'strong':{'bare':'deepseek-v4-flash','canonical':'deepseek/deepseek-v4-flash'},
 'weak':{'bare':'cognilocal/qwen3.8-flash-next','canonical':'cognilocal/qwen3.8-flash-next'},
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
res=json.loads((G/'GOLDSET-RESULT.json').read_text())
cand=json.loads((G/'goldset_candidates.json').read_text())
assert res['verdict']=='PASS'
selected=[x['case_id'] for x in res['per_case'] if x['certified'] and x['cell'] in {'B','C'}]
selected=sorted(selected)
assert len(selected)==21
assert sum(x.startswith('sb2-B') for x in selected)==13
assert sum(x.startswith('sb2-C') for x in selected)==8
cases={cid:cand['cases'][cid] for cid in selected}
blocks=[]
for mi,m in enumerate(('strong','weak')):
    mids=selected[:]
    random.Random(SEED+mi).shuffle(mids)
    for j,cid in enumerate(mids):
        # global exact balance: strong starts C0 (11/10), weak starts C1 (10/11)
        first='C0' if ((j+mi)%2==0) else 'C1'
        order=[first,'C1' if first=='C0' else 'C0']
        blocks.append({'block_id':f'{m}:{cid}','model':m,'case_id':cid,'arm_order':order})
random.Random(SEED).shuffle(blocks)
rows=[]
for bi,b in enumerate(blocks,1):
    for ai,arm in enumerate(b['arm_order']):
        rows.append({'ordinal':len(rows)+1,'block_ordinal':bi,'model':b['model'],'case_id':b['case_id'],'arm':arm,'row_id':f"{b['model']}:{b['case_id']}:{arm}"})
assert len(rows)==84 and len({x['row_id'] for x in rows})==84
assert sum(b['arm_order'][0]=='C0' for b in blocks)==21
plan={'schema':'subject-binding-efficacy-v2-provider-plan/v1','seed':SEED,'source_commit':'738aaed6ae1ca733bb323c43a130f7f877e667d9','goldset_result_sha256':sha(G/'GOLDSET-RESULT.json'),'goldset_freeze_sha256':sha(G/'FREEZE.json'),'spec_sha256':sha(HERE/'SPEC.md'),'models':MODELS,'selected_case_ids':selected,'cases':cases,'blocks':blocks,'formal_rows':rows,'counts':{'cases':21,'B':13,'C':8,'blocks':42,'formal_cells':84,'c0_first_blocks':21,'c1_first_blocks':21}}
(HERE/'matrix_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=1)+'\n')
freeze={'plan_sha256':sha(HERE/'matrix_plan.json'),'spec_sha256':plan['spec_sha256'],'goldset_result_sha256':plan['goldset_result_sha256'],'provider_execution_authorized':True,'formal_cells':84}
(HERE/'PLAN-FREEZE.json').write_text(json.dumps(freeze,indent=1)+'\n')
print(json.dumps({'plan_sha256':freeze['plan_sha256'],'counts':plan['counts'],'first_rows':rows[:4]},ensure_ascii=False,indent=2))
