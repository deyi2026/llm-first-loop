"""Stage S1 multi-provider screening CLI.

Safety: scored real requests require --execute-real and a passing unscored smoke
artifact for the selected provider. Provider blocks may execute independently;
Full S is not complete until all four blocks finish.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent.parent
sys.path.insert(0,str(ROOT))

from llm_loop.config import load_env_file
from scripts.calib.s_scorer import score_run_s
from scripts.calib.screening_runner import execute_screening_run, snapshot_provider

MATRIX_PATH=ROOT/'data'/'calib'/'s_matrix_v1.json'
DEFAULT_OUT=ROOT/'data'/'calib'/'runs_s1'
SMOKE_DIR=ROOT/'data'/'calib'/'smoke_s1'
PROVIDERS=['minimax','deepseek','kimi','glm']


def _matrix():
    return json.loads(MATRIX_PATH.read_text(encoding='utf-8'))['rows']


def _smoke_ok(provider:str)->bool:
    p=SMOKE_DIR/f'{provider}.json'
    if not p.exists(): return False
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return False
    return d.get('provider')==provider and d.get('passed') is True


def _select(args):
    rows=_matrix()
    if args.provider:
        rows=[r for r in rows if r['provider']==args.provider]
    if args.run:
        rows=[r for r in rows if r['run_id']==args.run]
        if not rows: raise SystemExit(f'unknown/nonselected run: {args.run}')
    elif args.from_run:
        ids=[r['run_id'] for r in rows]
        if args.from_run not in ids: raise SystemExit(f'--from run not in selected block: {args.from_run}')
        rows=rows[ids.index(args.from_run):]
    elif not args.all:
        raise SystemExit('run action requires --all / --run / --from')
    return rows


def main(argv=None):
    ap=argparse.ArgumentParser(description='Stage S1 frozen 96-run screening matrix')
    ap.add_argument('--provider',choices=PROVIDERS)
    ap.add_argument('--run')
    ap.add_argument('--from',dest='from_run')
    ap.add_argument('--all',action='store_true')
    mode=ap.add_mutually_exclusive_group()
    mode.add_argument('--dry',action='store_true')
    mode.add_argument('--execute-real',action='store_true',help='explicit real-request gate')
    ap.add_argument('--dry-mode',choices=['pass','fail'],default='pass')
    ap.add_argument('--snapshot',action='store_true')
    ap.add_argument('--regrade',action='store_true')
    ap.add_argument('--out',type=Path,default=DEFAULT_OUT)
    args=ap.parse_args(argv)
    load_env_file()
    args.out.mkdir(parents=True,exist_ok=True)

    if args.snapshot:
        ps=[args.provider] if args.provider else PROVIDERS
        for p in ps:
            snap=snapshot_provider(p,args.out)
            print(json.dumps(snap,ensure_ascii=False))
        return 0

    if args.regrade:
        scores=[]
        for r in _matrix():
            if args.provider and r['provider']!=args.provider: continue
            path=args.out/f"{r['run_id']}.json"
            if not path.exists(): continue
            obj=json.loads(path.read_text(encoding='utf-8'))
            obj['score']=score_run_s(obj)
            path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
            scores.append(obj['score'])
        report={"generated":datetime.now(UTC).isoformat(),"mode":"regrade","count":len(scores),"matrix_version":"S1-v1","runs":scores}
        suffix=f"_{args.provider}" if args.provider else ''
        (args.out/f'report{suffix}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'regraded={len(scores)}')
        return 0

    rows=_select(args)
    if not args.dry and not args.execute_real:
        raise SystemExit('refusing provider requests: use --execute-real after approval + smoke gate')
    if args.execute_real:
        selected=sorted({r['provider'] for r in rows})
        bad=[p for p in selected if not _smoke_ok(p)]
        if bad:
            raise SystemExit('real screening blocked: missing/passing smoke artifact for '+','.join(bad))

    scores=[]
    for r in rows:
        print(f"[{r['run_id']}] {r['provider']} {r['seed']} {r['variant']} {'dry' if args.dry else 'REAL'}",flush=True)
        obj=execute_screening_run(r['run_id'],r['provider'],r['seed'],r['variant'],dry=args.dry,dry_mode=args.dry_mode)
        obj['matrix_block_seq']=r['block_seq']
        obj['score']=score_run_s(obj)
        (args.out/f"{r['run_id']}.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
        scores.append(obj['score'])
        s=obj['score']
        print(f" -> status={obj['status']} task={s['task_success']} novel={s['novel_stage']} fatal={s['fatal_behavior']} unnec={s['unnecessary_verification_count']}")
    report={"generated":datetime.now(UTC).isoformat(),"dry":args.dry,"count":len(scores),"matrix_version":"S1-v1","runs":scores}
    suffix=f"_{args.provider}" if args.provider else ''
    (args.out/f'report{suffix}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
