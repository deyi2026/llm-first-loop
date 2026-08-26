from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent;sys.path.insert(0,str(ROOT))
from scripts.calib.scorer_v19 import SCORER_VERSION,novel_stage
BANK=ROOT/'data/calib/h1f_control_bank.json';REPORT=ROOT/'data/calib/h1f_report.json'
def main():
 b=json.loads(BANK.read_text());rows=[]
 for c in b['controls']:
  p=novel_stage(c['trace'],c['source'],c['text'],c['truth_phrases'],waiver=c.get('waiver',False),verification_plan=c.get('verification_plan',False));rows.append({**c,'pred':p,'match':p==c['gold']})
 ok=all(r['match'] for r in rows);per={}
 for cls in sorted({r['class'] for r in rows}):
  rr=[r for r in rows if r['class']==cls];per[cls]={'n':len(rr),'correct':sum(x['match'] for x in rr)}
 rep={'scorer_version':SCORER_VERSION,'count':len(rows),'exact':sum(r['match'] for r in rows),'per_class':per,'overall_pass':ok,'mismatches':[r for r in rows if not r['match']]};REPORT.write_text(json.dumps(rep,ensure_ascii=False,indent=2));print(json.dumps(rep,ensure_ascii=False,indent=2));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
