from __future__ import annotations
import argparse,json,sys
from datetime import UTC,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent;sys.path.insert(0,str(ROOT))
from llm_loop.config import load_env_file
from scripts.calib import fixtures_h2e as f
from scripts.calib.h2e_scorer import score_run_h2e
from scripts.calib.runner import execute_run
MATRIX=ROOT/'data/calib/h2e_matrix_v1.json';OUT=ROOT/'data/calib/runs_h2e'
class Data:
 ORACLES=f.ORACLES_H2E;SOURCES=f.SOURCES_H2E;INITIAL_PACKETS=f.INITIAL_PACKETS_H2E;SOURCE_LIMIT=f.SOURCE_LIMIT_H2E;UNAVAILABLE_RESPONSE=f.UNAVAILABLE_RESPONSE_H2E;LIMIT_EXCEEDED_RESPONSE=f.LIMIT_EXCEEDED_RESPONSE_H2E
 @staticmethod
 def lookup_source(seed,source):return f.lookup_source_h2e(seed,source)
DATA=Data()
def rows():return json.loads(MATRIX.read_text())['rows']
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--provider',choices=['minimax','deepseek']);ap.add_argument('--run');ap.add_argument('--all',action='store_true');ap.add_argument('--dry',action='store_true');ap.add_argument('--execute-real',action='store_true');ap.add_argument('--regrade',action='store_true');a=ap.parse_args(argv);load_env_file();OUT.mkdir(parents=True,exist_ok=True)
 rs=[r for r in rows() if not a.provider or r['provider']==a.provider]
 if a.regrade:
  ss=[]
  for r in rs:
   p=OUT/f"{r['run_id']}.json";
   if not p.exists():continue
   o=json.loads(p.read_text());o['score']=score_run_h2e(o);p.write_text(json.dumps(o,ensure_ascii=False,indent=2));ss.append(o['score'])
  (OUT/f"report_{a.provider or 'all'}.json").write_text(json.dumps({'generated':datetime.now(UTC).isoformat(),'count':len(ss),'runs':ss},ensure_ascii=False,indent=2));print('regraded',len(ss));return 0
 if a.run:rs=[r for r in rs if r['run_id']==a.run]
 elif not a.all:raise SystemExit('use --all or --run')
 if not a.dry and not a.execute_real:raise SystemExit('real H2e blocked')
 for r in rs:
  print(f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'DRY' if a.dry else 'REAL'}",flush=True);o=execute_run(r['run_id'],r['seed'],r['variant'],dry=a.dry,provider=r['provider'],data=DATA);o['provider']=r['provider'];o['score']=score_run_h2e(o);(OUT/f"{r['run_id']}.json").write_text(json.dumps(o,ensure_ascii=False,indent=2));s=o['score'];print(' ->',o['status'],'task',s['task_success'],'fatal',s['fatal_behavior'],'novel',s['novel_stage'],'unnec',s['unnecessary_verification_count'])
 return 0
if __name__=='__main__':raise SystemExit(main())
