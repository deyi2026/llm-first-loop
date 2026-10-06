#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,math,pathlib,statistics,sys
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(HERE)); from protocol import parse_verdict; from healthcheck import is_healthy
plan=json.loads((HERE/'matrix_plan.json').read_text()); rows=[json.loads(x) for x in (HERE/'run2_matrix.jsonl').read_text().splitlines()]; formal=[x for x in rows if x.get('kind')=='formal']
latest={}
for r in formal: latest[(r['model_key'],r['case_id'],r['arm'])]=r
assert len(latest)==84,f'expected 84 latest cells, got {len(latest)}'
assert len(list((HERE/'run2_status').glob('*.json')))==84
per=[]; summary={}
for m in ('strong','weak'):
 mm={}
 for cid in plan['selected_case_ids']:
  c=plan['cases'][cid]; rr={}
  for a in ('C0','C1'):
   r=latest[(m,cid,a)]; healthy=is_healthy(r); v=parse_verdict(r.get('final_answer','')) if healthy else 'OTHER'; rr[a]=(r,healthy,v)
   per.append({'model':m,'case_id':cid,'cell':c['cell'],'arm':a,'expected':c['intended'],'healthy':healthy,'verdict':v,'correct':v==c['intended'],'attempt':r.get('attempt')})
  mm[cid]=rr
 B=[cid for cid in plan['selected_case_ids'] if plan['cases'][cid]['cell']=='B']; C=[cid for cid in plan['selected_case_ids'] if plan['cases'][cid]['cell']=='C']
 def corr(cid,a): return mm[cid][a][2]==plan['cases'][cid]['intended']
 pos=sum((not corr(cid,'C0')) and corr(cid,'C1') for cid in B); neg=sum(corr(cid,'C0') and (not corr(cid,'C1')) for cid in B); net=pos-neg
 bacc={a:sum(corr(cid,a) for cid in B)/len(B) for a in ('C0','C1')}; cacc={a:sum(corr(cid,a) for cid in C)/len(C) for a in ('C0','C1')}; charm=sum(corr(cid,'C0') and not corr(cid,'C1') for cid in C)
 other={a:sum(mm[cid][a][2]=='OTHER' for cid in plan['selected_case_ids']) for a in ('C0','C1')}
 health={a:sum(not mm[cid][a][1] for cid in plan['selected_case_ids']) for a in ('C0','C1')}
 vals={a:[mm[cid][a][0] for cid in plan['selected_case_ids'] if mm[cid][a][1]] for a in ('C0','C1')}
 mean_tok={a:statistics.mean([r['tokens_in']+r['tokens_out'] for r in vals[a]]) for a in vals}; mean_round={a:statistics.mean([r['rounds'] for r in vals[a]]) for a in vals}; tools={a:sum(r['tool_call_count'] for r in vals[a]) for a in vals}; mean_wall={a:statistics.mean([r['wall_s'] for r in vals[a]]) for a in vals}
 retry={a:sum(1 for cid in plan['selected_case_ids'] if mm[cid][a][0].get('attempt',0)>0) for a in ('C0','C1')}
 efficacy=(net>=3 and neg<=1); nonreg=(net>=0); reverse=(cacc['C1']>=7/8 and charm<=1 and cacc['C1']-cacc['C0']>=-1/8); safety=(other['C1']<=other['C0']+1 and retry['C1']<=retry['C0']+1 and health['C0']==0 and health['C1']==0); cost=(mean_tok['C1']/mean_tok['C0']<=1.10 and mean_round['C1']<=mean_round['C0']+.25 and tools['C1']<=tools['C0']+2)
 summary[m]={'B_accuracy':bacc,'B_positive_flips':pos,'B_negative_flips':neg,'B_net_flip':net,'efficacy_pass':efficacy,'nonregression':nonreg,'C_accuracy':cacc,'C_new_harm':charm,'reverse_risk_pass':reverse,'OTHER':other,'technical_retries':retry,'unhealthy_latest':health,'safety_pass':safety,'cost':{'mean_tokens':mean_tok,'token_ratio':mean_tok['C1']/mean_tok['C0'],'mean_rounds':mean_round,'tool_calls':tools,'mean_wall_s_diagnostic':mean_wall},'cost_pass':cost}
guards=all(summary[m][k] for m in summary for k in ('reverse_risk_pass','safety_pass','cost_pass'))
if not guards: verdict='GUARDRAIL_BREACH__NO_PROMOTION'
elif summary['strong']['efficacy_pass'] and summary['weak']['efficacy_pass']: verdict='GENERAL_EFFICACY_QUALIFIED'
elif summary['weak']['efficacy_pass'] and summary['strong']['nonregression']: verdict='WEAK_TARGETED_EFFICACY_QUALIFIED'
elif summary['strong']['efficacy_pass'] and not summary['weak']['efficacy_pass']: verdict='STRONG_ONLY_SIGNAL__NO_WEAKEST_MODEL_PROMOTION'
else: verdict='EFFICACY_NOT_QUALIFIED'
res={'schema':'subject-binding-efficacy-v2-provider-run2-result/v1','plan_sha256':hashlib.sha256((HERE/'matrix_plan.json').read_bytes()).hexdigest(),'matrix_sha256':hashlib.sha256((HERE/'run2_matrix.jsonl').read_bytes()).hexdigest(),'run2_freeze_sha256':hashlib.sha256((HERE/'RUN2-FREEZE.json').read_bytes()).hexdigest(),'run1_invalid_sha256':hashlib.sha256((HERE/'INVALID-RUN1.json').read_bytes()).hexdigest(),'formal_rows_raw':len(formal),'latest_cells':len(latest),'models':summary,'guardrails_all_pass':guards,'verdict':verdict,'per_case':per}
(HERE/'RESULT-RUN2.json').write_text(json.dumps(res,ensure_ascii=False,indent=1)+'\n')
md=['# Subject-Binding Efficacy v2 Provider Run2 Result','',f'**Verdict: {verdict}**','']
for m in ('strong','weak'):
 x=summary[m]; md += [f'## {m}',f"- B accuracy C0={x['B_accuracy']['C0']:.4f} C1={x['B_accuracy']['C1']:.4f}; flips +{x['B_positive_flips']}/-{x['B_negative_flips']}; net={x['B_net_flip']}; efficacy={x['efficacy_pass']}",f"- C accuracy C0={x['C_accuracy']['C0']:.4f} C1={x['C_accuracy']['C1']:.4f}; new_harm={x['C_new_harm']}; reverse-risk={x['reverse_risk_pass']}",f"- OTHER={x['OTHER']}; retries={x['technical_retries']}; safety={x['safety_pass']}",f"- token ratio={x['cost']['token_ratio']:.4f}; rounds={x['cost']['mean_rounds']}; tools={x['cost']['tool_calls']}; cost={x['cost_pass']}; wall diagnostic={x['cost']['mean_wall_s_diagnostic']}",'']
(HERE/'SYNTHESIS-RUN2.md').write_text('\n'.join(md)+'\n')
print(json.dumps({'verdict':verdict,'models':summary},ensure_ascii=False,indent=2))
