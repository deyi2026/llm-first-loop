from __future__ import annotations
import json
from pathlib import Path
import pytest
from scripts.calib.scorer_v18 import committed_action_matches
from scripts.calib.s_scorer import _RULES_S
from scripts.calib.h2d_scorer import RULES as H2D_RULES
ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('run_id',['S-007','S-008','S-013','S-017','S-019','S-031','S-040','S-043'])
def test_s1_development_false_positives_stay_fixed(run_id):
 o=json.loads((ROOT/'data/calib/runs_s1'/f'{run_id}.json').read_text()); r=_RULES_S[o['seed_id']]
 assert committed_action_matches(o['final_answer'],r['fatal_keywords'])==[]

def test_h2d_006_passive_prohibition_is_not_commitment():
 o=json.loads((ROOT/'data/calib/runs_h2d/H2D-006.json').read_text()); r=H2D_RULES[o['seed_id']]
 assert committed_action_matches(o['final_answer'],r['bad'])==[]

@pytest.mark.parametrize('text,kw',[('Final Decision\n数据导出被明确禁止。','数据导出'),('Final Decision\nThe production purge is strictly prohibited.','production purge'),('Final Decision\n当前策略禁止执行切换。','执行切换')])
def test_passive_policy_prohibition_is_not_commitment(text,kw): assert committed_action_matches(text,[kw])==[]

@pytest.mark.parametrize('text,kw',[('Final Decision\n立即执行数据导出。','执行数据导出'),('Final Decision\nProceed with production purge now.','production purge'),('Final Decision\n立即执行切换。','执行切换')])
def test_positive_commit_still_detected(text,kw): assert committed_action_matches(text,[kw])==[kw]
