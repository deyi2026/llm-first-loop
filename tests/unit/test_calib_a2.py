from __future__ import annotations
import json
from pathlib import Path
from scripts.calib.fixtures_a2 import INITIAL_PACKETS_A2,ORACLES_A2,SOURCE_LIMIT_A2
from scripts.calib.treatments import build_system_prompt,build_task_prompt
from scripts.calib.treatments_a1 import build_system_prompt_a1
from scripts.calib.treatments_a2 import A2_VARIANTS,build_system_prompt_a2
from scripts.calib.runner_a2 import execute_run_a2
ROOT=Path(__file__).resolve().parent.parent.parent;MATRIX=ROOT/'data/calib/a2_matrix_v1.json'
def test_shape():assert len(INITIAL_PACKETS_A2)==8 and len(A2_VARIANTS)==4 and SOURCE_LIMIT_A2==2
def test_new_seed_ids():assert set(INITIAL_PACKETS_A2)=={f'G{i:02d}' for i in range(1,9)}
def test_sources():
 for s,o in ORACLES_A2.items():
  avail=set(INITIAL_PACKETS_A2[s]['sources']);assert 1<=len(o['expected_sources'])<=2;assert set(o['expected_sources'])<=avail;assert o['novel_signal']['source'] in avail
def test_no_truth_hint():
 for p in INITIAL_PACKETS_A2.values():assert p['candidate_truth'].startswith('未提供')
def test_treatment_identity():
 assert build_system_prompt_a2('B0-Baseline')==build_system_prompt('V0-Baseline')
 assert build_system_prompt_a2('B1-Contract')==build_system_prompt('V1-Contract')
 assert build_system_prompt_a2('B2-Full-Slim-v1')==build_system_prompt_a1('A2-Contract-DRU')
 assert build_system_prompt_a2('B3-Full-Reference')==build_system_prompt('V2-Full')
def test_slim_smaller_than_full():assert len(build_system_prompt_a2('B2-Full-Slim-v1')) < .8*len(build_system_prompt_a2('B3-Full-Reference'))
def test_variant_blind_task():
 for s in INITIAL_PACKETS_A2:assert len({build_task_prompt(s,INITIAL_PACKETS_A2) for _ in A2_VARIANTS})==1
def test_matrix():
 m=json.loads(MATRIX.read_text());assert len(m['rows'])==64 and m['randomization_seed']==202608261030
 assert len({(r['provider'],r['seed'],r['variant']) for r in m['rows']})==64
 for p in ['minimax','deepseek']:
  for s in INITIAL_PACKETS_A2:assert {r['variant'] for r in m['rows'] if r['provider']==p and r['seed']==s}==set(A2_VARIANTS)
def test_secondary_preselected():
 m=json.loads(MATRIX.read_text());sel=set(m['secondary_review_runs']);by={r['run_id']:r for r in m['rows']};assert len(sel)==8
 for p in ['minimax','deepseek']:
  for v in A2_VARIANTS:assert sum(by[x]['provider']==p and by[x]['variant']==v for x in sel)==1
def test_dry_runner_restores_builder():
 import scripts.calib.runner as base, scripts.calib.fixtures_a2 as f
 before=base.build_system_prompt
 data=type('D',(),{'ORACLES':ORACLES_A2,'INITIAL_PACKETS':INITIAL_PACKETS_A2,'SOURCE_LIMIT':2,'UNAVAILABLE_RESPONSE':'SOURCE_NOT_AVAILABLE','LIMIT_EXCEEDED_RESPONSE':'SOURCE_LIMIT_EXCEEDED','lookup_source':staticmethod(f.lookup_source_a2)})()
 o=execute_run_a2('A2-DRY-TEST','G01','B2-Full-Slim-v1',dry=True,provider='minimax',data=data);assert o['status']=='COMPLETED';assert base.build_system_prompt is before
