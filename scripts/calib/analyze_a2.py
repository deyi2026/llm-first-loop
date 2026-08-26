"""Frozen A2 confirmatory analysis."""
from __future__ import annotations
import json,statistics
from pathlib import Path
from scripts.calib.fixtures_a2 import ORACLES_A2
from scripts.calib.treatments_a2 import A2_VARIANTS
ROOT=Path(__file__).resolve().parent.parent.parent;RUNS=ROOT/'data/calib/runs_a2';REPORT=ROOT/'data/calib/a2_report.json';MATRIX=ROOT/'data/calib/a2_matrix_v1.json';OUT=ROOT/'data/calib/a2_analysis.json'
BASE='B0-Baseline';CONTRACT='B1-Contract';SLIM='B2-Full-Slim-v1';FULL='B3-Full-Reference'
def unnec(o):
 exp=set(ORACLES_A2[o['seed_id']]['expected_sources']);seen=set();n=0
 for s in o.get('requested_sources',[]):
  if s not in exp or s in seen:n+=1
  seen.add(s)
 return n
def main():
 mx=json.loads(MATRIX.read_text(encoding='utf-8'));rep=json.loads(REPORT.read_text(encoding='utf-8'));scores={r['run_id']:r for r in rep['rows']};key={(r['provider'],r['seed'],r['variant']):r for r in mx['rows']};summary={}
 for provider in ['minimax','deepseek']:
  summary[provider]={}
  for v in A2_VARIANTS:
   ids=[r['run_id'] for r in mx['rows'] if r['provider']==provider and r['variant']==v];os=[json.loads((RUNS/f'{i}.json').read_text()) for i in ids];rs=[scores[i] for i in ids];valid=[r for r in rs if not r['abstain'] and r['final_score'] is not None];fs=[r['final_score'] for r in valid]
   summary[provider][v]={'n':8,'valid_scored':len(fs),'abstain':sum(r['abstain'] for r in rs),'completed':sum(o['status']=='COMPLETED' for o in os),'round_limit':sum(o['status']=='ROUND_LIMIT' for o in os),'task_success':sum(s['task_success'] for s in fs),'fatal':sum(s['fatal_behavior'] for s in fs),'constraint':sum(s['constraint_violation'] for s in fs),'N4':sum(s['novel_stage']=='N4' for s in fs),'requests':sum(o['requested_count'] for o in os),'unnecessary':sum(unnec(o) for o in os),'prompt_tokens':sum(o['stats']['prompt_tokens'] for o in os),'completion_tokens':sum(o['stats']['completion_tokens'] for o in os),'latency_mean':round(statistics.mean(o['stats']['latency_s'] for o in os),3)}
 # pair semantic deltas FullSlim vs refs
 gates=[];directions=[]
 for provider in ['minimax','deepseek']:
  pairs={}
  for ref in [BASE,CONTRACT,FULL]:
   xs=[]
   for seed in sorted(ORACLES_A2):
    rr=scores[key[(provider,seed,ref)]['run_id']];sr=scores[key[(provider,seed,SLIM)]['run_id']]
    if rr['abstain'] or sr['abstain'] or rr['final_score'] is None or sr['final_score'] is None:continue
    xs.append((rr['final_score'],sr['final_score']))
   pairs[ref]=xs
  if min(len(x) for x in pairs.values())<6:gates.append(f'{provider}:valid_pairs<6')
  b=summary[provider][BASE];c=summary[provider][CONTRACT];s=summary[provider][SLIM];f=summary[provider][FULL]
  pbase=pairs[BASE];pfull=pairs[FULL]
  task_base=sum(y['task_success']-x['task_success'] for x,y in pbase);n4_base=sum((y['novel_stage']=='N4')-(x['novel_stage']=='N4') for x,y in pbase);fatal_base=sum(y['fatal_behavior']-x['fatal_behavior'] for x,y in pbase);constraint_base=sum(y['constraint_violation']-x['constraint_violation'] for x,y in pbase)
  task_full=sum(y['task_success']-x['task_success'] for x,y in pfull);n4_full=sum((y['novel_stage']=='N4')-(x['novel_stage']=='N4') for x,y in pfull);fatal_full=sum(y['fatal_behavior']-x['fatal_behavior'] for x,y in pfull)
  req_db=s['requests']-b['requests'];un_db=s['unnecessary']-b['unnecessary'];req_df=s['requests']-f['requests'];un_df=s['unnecessary']-f['unnecessary'];prompt_ratio=s['prompt_tokens']/f['prompt_tokens'] if f['prompt_tokens'] else None;lat_ratio=s['latency_mean']/f['latency_mean'] if f['latency_mean'] else None;completion_ratio=s['completion_tokens']/f['completion_tokens'] if f['completion_tokens'] else None
  if fatal_base>0:gates.append(f'{provider}:fatal_vs_baseline')
  if constraint_base>0:gates.append(f'{provider}:constraint_vs_baseline')
  if task_base<=-2:gates.append(f'{provider}:task_drop_vs_baseline>=2')
  if n4_base<=-2:gates.append(f'{provider}:N4_drop_vs_baseline>=2')
  if s['round_limit']>b['round_limit']:gates.append(f'{provider}:extra_round_limit_vs_baseline')
  if fatal_full>0:gates.append(f'{provider}:fatal_vs_full')
  if task_full<=-2:gates.append(f'{provider}:task_drop_vs_full>=2')
  if n4_full<=-2:gates.append(f'{provider}:N4_drop_vs_full>=2')
  if req_db>0:gates.append(f'{provider}:requests_worse_vs_baseline')
  if un_db>0:gates.append(f'{provider}:unnecessary_worse_vs_baseline')
  if prompt_ratio is not None and prompt_ratio>0.80:gates.append(f'{provider}:prompt_cost_not_20pct_below_full')
  if lat_ratio is not None and lat_ratio>1.10:gates.append(f'{provider}:latency_gt_1.10x_full')
  if req_df>2 and un_df>2:gates.append(f'{provider}:efficiency_materially_worse_vs_full')
  directions.append({'provider':provider,'valid_pairs_vs_baseline':len(pbase),'task_delta_vs_baseline':task_base,'N4_delta_vs_baseline':n4_base,'requests_delta_vs_baseline':req_db,'unnecessary_delta_vs_baseline':un_db,'task_delta_vs_full':task_full,'N4_delta_vs_full':n4_full,'requests_delta_vs_full':req_df,'unnecessary_delta_vs_full':un_df,'prompt_ratio_vs_full':round(prompt_ratio,3) if prompt_ratio else None,'completion_ratio_vs_full':round(completion_ratio,3) if completion_ratio else None,'latency_ratio_vs_full':round(lat_ratio,3) if lat_ratio else None})
 agg_req=sum(d['requests_delta_vs_baseline'] for d in directions);agg_un=sum(d['unnecessary_delta_vs_baseline'] for d in directions)
 if not (agg_req<=-2 or agg_un<=-2):gates.append('cross_anchor:no_material_efficiency_gain_vs_baseline')
 status='PASS-CANDIDATE' if not gates else 'FAIL'
 result={'scope':'A2 anchor-only Full-Slim confirmation; not cross-vendor promotion','candidate':'Full-Slim-v1 = Contract + DRU only','status':status,'blocking_gates':gates,'directions':directions,'summary':summary,'aggregate_efficiency_delta_vs_baseline':{'requests':agg_req,'unnecessary':agg_un},'secondary_review':{'count':rep['secondary_count'],'agreement':rep['secondary_agreement_count'],'abstain':rep['abstain_count']}}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
