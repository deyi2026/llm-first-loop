"""A3 Action-Plane mechanism ablation generation runner."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent
sys.path.insert(0,str(ROOT))
from llm_loop.config import load_env_file
from scripts.calib import fixtures_a3 as f
from scripts.calib.runner_a3 import execute_run_a3
MATRIX=ROOT/'data/calib/a3_matrix_v1.json';OUT=ROOT/'data/calib/runs_a3'
class Data:
 ORACLES=f.ORACLES_A3;SOURCES=f.SOURCES_A3;INITIAL_PACKETS=f.INITIAL_PACKETS_A3
 SOURCE_LIMIT=f.SOURCE_LIMIT_A3;UNAVAILABLE_RESPONSE=f.UNAVAILABLE_RESPONSE_A3;LIMIT_EXCEEDED_RESPONSE=f.LIMIT_EXCEEDED_RESPONSE_A3
 @staticmethod
 def lookup_source(seed,source):return f.lookup_source_a3(seed,source)
DATA=Data()
def rows():return json.loads(MATRIX.read_text(encoding='utf-8'))['rows']
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--provider',choices=['minimax','deepseek']);ap.add_argument('--run');ap.add_argument('--all',action='store_true');ap.add_argument('--from-run');ap.add_argument('--count',type=int);ap.add_argument('--dry',action='store_true');ap.add_argument('--execute-real',action='store_true');a=ap.parse_args(argv)
 load_env_file();OUT.mkdir(parents=True,exist_ok=True)
 rs=[r for r in rows() if not a.provider or r['provider']==a.provider]
 if a.run:rs=[r for r in rs if r['run_id']==a.run]
 elif a.from_run:
  idx=next((i for i,r in enumerate(rs) if r['run_id']==a.from_run),None)
  if idx is None:raise SystemExit(f'from-run not found: {a.from_run}')
  rs=rs[idx:];rs=rs[:a.count] if a.count is not None else rs
 elif not a.all:raise SystemExit('use --all, --run, or --from-run')
 if not a.dry and not a.execute_real:raise SystemExit('real A3 blocked until frozen preregistration')
 for r in rs:
  print(f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'DRY' if a.dry else 'REAL'}",flush=True)
  p=OUT/f"{r['run_id']}.json"
  if p.exists() and not a.dry:
   print(' -> SKIP existing raw artifact',flush=True);continue
  o=execute_run_a3(r['run_id'],r['seed'],r['variant'],dry=a.dry,provider=r['provider'],data=DATA);o['provider']=r['provider'];o['matrix_block_seq']=r['block_seq'];p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
  print(' ->',o['status'],'attempt',o['tool_attempt_count'],'exec',o['tool_execution_count'],'dup',o['duplicate_suppressed_count'],'blocked',o['budget_blocked_count'],'rounds',o['rounds_to_final'],'lat',o['stats']['latency_s'],flush=True)
 return 0
if __name__=='__main__':raise SystemExit(main())
