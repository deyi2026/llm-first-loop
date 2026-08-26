"""H2h dual-judge scorer; resumable and abstains on judge disagreement."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent
sys.path.insert(0,str(ROOT))
from llm_loop.config import load_env_file
from scripts.calib.fixtures_h2h import INITIAL_PACKETS_H2H,ORACLES_H2H
from scripts.calib.semantic_judge_v21 import judge_case,derive_core_score
from scripts.calib.treatments import build_task_prompt
RUNS=ROOT/'data/calib/runs_h2h'; JDIR=ROOT/'data/calib/h2h_judges'; REPORT=ROOT/'data/calib/h2h_report.json'

def case_for(o):
    oracle=ORACLES_H2H[o['seed_id']]
    trace=[{'round':t.get('round'),'source':t.get('source'),'result_full':t.get('result_full')} for t in o.get('trace',[])]
    return {'task':build_task_prompt(o['seed_id'],INITIAL_PACKETS_H2H),'oracle_expected_decision':oracle['expected_decision'],'prohibited_behavior':oracle['prohibited_behavior'],'novel_signal':oracle['novel_signal'],'trace':trace,'final_answer':o.get('final_answer')}

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--all',action='store_true'); a=ap.parse_args(argv)
    if not a.all: raise SystemExit('use --all')
    load_env_file(); JDIR.mkdir(parents=True,exist_ok=True); rows=[]
    for p in sorted(RUNS.glob('H2H-*.json')):
        o=json.loads(p.read_text(encoding='utf-8')); case=case_for(o); js={}; derived={}
        for provider in ['minimax','deepseek']:
            jp=JDIR/f"{o['run_id']}-{provider}.json"
            if jp.exists(): j=json.loads(jp.read_text(encoding='utf-8'))['judge']
            else:
                j=judge_case(case,provider,f"H2H-JUDGE-{provider}-{o['run_id']}")
                jp.write_text(json.dumps({'run_id':o['run_id'],'judge_provider':provider,'judge':j},ensure_ascii=False,indent=2),encoding='utf-8')
            js[provider]=j; derived[provider]=derive_core_score(case,j,o['status'])
        semantic_agree=all(js['minimax'][f]==js['deepseek'][f] for f in ['decision_matches_oracle','commits_prohibited_action','verified_truth_integrated'])
        derived_agree=all(derived['minimax'][f]==derived['deepseek'][f] for f in ['task_success','fatal_behavior','constraint_violation','novel_stage'])
        primary='deepseek' if o['provider']=='minimax' else 'minimax'
        row={'run_id':o['run_id'],'seed_id':o['seed_id'],'generation_provider':o['provider'],'primary_judge':primary,'judges':js,'derived':derived,'semantic_agree':semantic_agree,'derived_agree':derived_agree,'abstain':not(semantic_agree and derived_agree),'final_score':None if not(semantic_agree and derived_agree) else derived[primary]}
        rows.append(row); print(o['run_id'],'agree',semantic_agree and derived_agree,'primary',primary,derived[primary],flush=True)
    n=len(rows); agree=sum(not r['abstain'] for r in rows); report={'count':n,'agreement_count':agree,'agreement_rate':agree/n if n else 0,'abstain_count':n-agree,'rows':rows}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({k:report[k] for k in ['count','agreement_count','agreement_rate','abstain_count']},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
