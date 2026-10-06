from __future__ import annotations
import collections,hashlib,json,pathlib,math
H=pathlib.Path(__file__).resolve().parent; plan=json.loads((H/'plan.json').read_text()); rows=[json.loads(x) for x in (H/'matrix.jsonl').read_text().splitlines() if x.strip()]; assert len(rows)>=92
# exactly one latest successful row per formal row identity after optional technical retries
latest={}
for r in rows:
 if r.get('kind')=='formal': latest[(r['model_key'],r['case_id'],r['arm'])]=r
assert len(latest)==92
sts=sorted((H/'status').glob('*.json')); assert len(sts)==92
allhealthy=all(json.loads(p.read_text()).get('state')=='terminal' and json.loads(p.read_text()).get('mechanically_healthy') is True for p in sts)
valid={'applied','adapted','not_applicable','rejected'}; pos={'applied','adapted'}; neg={'not_applicable','rejected'}
def dec(r):
 ds=r.get('record_use_decisions') or []
 return ds[0] if len(ds)==1 and ds[0] in valid else 'OTHER'
def correct(r):
 d=dec(r); return d in (neg if r['intended']=='SKIP' else pos)
def retries(model,arm):
 return sum(max(0,len(json.loads(p.read_text()).get('attempts') or [])-1) for p in sts if (json.loads(p.read_text()).get('row') or {}).get('model')==model and (json.loads(p.read_text()).get('row') or {}).get('arm')==arm)
models={}; guard_all=True
for m in ('strong','weak'):
 challenge=[c for c in plan['cases'].values() if c['kind']=='challenge']; rev=[c for c in plan['cases'].values() if c['kind']=='apply_reverse_risk']
 cpair=[]; rpair=[]
 for c in challenge:
  r0=latest[(m,c['case_id'],'C0')]; r1=latest[(m,c['case_id'],'C1')]; cpair.append((c,r0,r1))
 for c in rev:
  r0=latest[(m,c['case_id'],'C0')]; r1=latest[(m,c['case_id'],'C1')]; rpair.append((c,r0,r1))
 posflip=sum((not correct(a)) and correct(b) for _,a,b in cpair); negflip=sum(correct(a) and (not correct(b)) for _,a,b in cpair); net=posflip-negflip; eff=(net>=3 and negflip<=1)
 rev0=sum(correct(a) for _,a,b in rpair); rev1=sum(correct(b) for _,a,b in rpair); revharm=sum(correct(a) and not correct(b) for _,a,b in rpair); revpass=(rev1>=5 and revharm<=1 and rev1-rev0>=-1)
 all0=[latest[(m,cid,'C0')] for cid in plan['cases']]; all1=[latest[(m,cid,'C1')] for cid in plan['cases']]
 other0=sum(dec(r)=='OTHER' for r in all0); other1=sum(dec(r)=='OTHER' for r in all1); retry0,retry1=retries(m,'C0'),retries(m,'C1'); miss0=sum(int(r.get('experience_file_count') or 0)<1 for r in all0); miss1=sum(int(r.get('experience_file_count') or 0)<1 for r in all1)
 safety=(other1<=other0+1 and retry1<=retry0+1 and miss1<=miss0+1 and (23-miss1)>=22 and all(r.get('model_used')==plan['models'][m]['canonical'] and r.get('binding_asserted')==(r['arm']=='C1') and r.get('settlement_ok') is True and r.get('run_end_completed') is True for r in all0+all1))
 tok0=sum((r.get('tokens_in') or 0)+(r.get('tokens_out') or 0) for r in all0)/23; tok1=sum((r.get('tokens_in') or 0)+(r.get('tokens_out') or 0) for r in all1)/23; tr=tok1/tok0 if tok0 else math.inf; rnd0=sum(r.get('rounds') or 0 for r in all0)/23; rnd1=sum(r.get('rounds') or 0 for r in all1)/23; tc0=sum(r.get('tool_call_count') or 0 for r in all0); tc1=sum(r.get('tool_call_count') or 0 for r in all1); cost=(tr<=1.10 and rnd1<=rnd0+.25 and tc1<=tc0+2)
 guard=revpass and safety and cost; guard_all &= guard
 models[m]={'challenge':{'n':len(cpair),'C0_correct':sum(correct(a) for _,a,b in cpair),'C1_correct':sum(correct(b) for _,a,b in cpair),'positive_flip':posflip,'negative_flip':negflip,'net_flip':net,'efficacy_pass':eff},'reverse_risk':{'n':len(rpair),'C0_correct':rev0,'C1_correct':rev1,'new_harm':revharm,'pass':revpass},'safety':{'OTHER_C0':other0,'OTHER_C1':other1,'technical_retries_C0':retry0,'technical_retries_C1':retry1,'missing_experience_C0':miss0,'missing_experience_C1':miss1,'pass':safety},'cost':{'mean_tokens_C0':tok0,'mean_tokens_C1':tok1,'token_ratio':tr,'mean_rounds_C0':rnd0,'mean_rounds_C1':rnd1,'tool_calls_C0':tc0,'tool_calls_C1':tc1,'pass':cost},'guardrails_pass':guard}
strong=models['strong']; weak=models['weak']
if not allhealthy or not guard_all: disposition='GUARDRAIL_BREACH__NO_PROMOTION'; auth=False
elif strong['challenge']['efficacy_pass'] and weak['challenge']['efficacy_pass']: disposition='GENERAL_EFFICACY_QUALIFIED'; auth=True
elif weak['challenge']['efficacy_pass'] and strong['challenge']['net_flip']>=0: disposition='WEAK_TARGETED_EFFICACY_QUALIFIED'; auth=True
elif strong['challenge']['efficacy_pass'] and not weak['challenge']['efficacy_pass']: disposition='STRONG_ONLY_SIGNAL__NO_WEAKEST_MODEL_PROMOTION'; auth=False
else: disposition='EFFICACY_NOT_QUALIFIED'; auth=False
res={'schema':'subject-binding-v3-confirmatory-result/v1','formal_cells':92,'latest_cells':len(latest),'all_latest_mechanically_healthy':allhealthy,'models':models,'disposition':disposition,'production_promotion_authorized':auth,'input_sha256':{n:hashlib.sha256((H/n).read_bytes()).hexdigest() for n in ('SPEC.md','FREEZE.json','plan.json','matrix.jsonl','PREFLIGHT.json','SURFACE-PROBE.json')}}
(H/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n'); md=['# Subject-Binding v3 Confirmatory Result','',f'**Disposition: `{disposition}`**','',f'- production_promotion_authorized: {auth}',f'- all latest mechanically healthy: {allhealthy}']
for m in ('strong','weak'):
 x=models[m]; md += ['',f'## {m}',f"- challenge C0/C1: {x['challenge']['C0_correct']}/17 -> {x['challenge']['C1_correct']}/17",f"- flips +{x['challenge']['positive_flip']} / -{x['challenge']['negative_flip']} / net {x['challenge']['net_flip']}; efficacy={x['challenge']['efficacy_pass']}",f"- reverse-risk C0/C1: {x['reverse_risk']['C0_correct']}/6 -> {x['reverse_risk']['C1_correct']}/6; new_harm={x['reverse_risk']['new_harm']}; pass={x['reverse_risk']['pass']}",f"- token ratio={x['cost']['token_ratio']:.4f}; rounds {x['cost']['mean_rounds_C0']:.3f}->{x['cost']['mean_rounds_C1']:.3f}; tool calls {x['cost']['tool_calls_C0']}->{x['cost']['tool_calls_C1']}; cost={x['cost']['pass']}",f"- safety={x['safety']['pass']}"]
(H/'SYNTHESIS.md').write_text('\n'.join(md)+'\n'); print(json.dumps(res,ensure_ascii=False,indent=2))
