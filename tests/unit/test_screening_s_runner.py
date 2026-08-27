from __future__ import annotations

from scripts.calib.screening_runner import build_screening_task_prompt, execute_screening_run, load_manifest
from scripts.calib.s_scorer import score_run_s


def test_s_task_prompt_has_no_candidate_truth():
    p=build_screening_task_prompt('P01')
    assert 'Candidate current truth' not in p
    assert 'fixture://P01/write_fence' in p
    assert '最多 2' in p


def test_manifest_has_four_provider_panel():
    m=load_manifest()
    assert list(m['providers']) == ['minimax','deepseek','kimi','glm']
    assert m['providers']['kimi']['model']=='k3'
    assert m['providers']['glm']['model']=='glm-5.2'


def test_dry_p01_success_and_metadata():
    r=execute_screening_run('T','deepseek','P01','V2-Full',dry=True)
    s=score_run_s(r)
    assert r['status']=='COMPLETED'
    assert r['provider_id']=='deepseek'
    assert r['thinking_mode'] is True
    assert s['task_success']==1
    assert s['novel_stage']=='N4'


def test_dry_p05_preserves_dru_waiver():
    r=execute_screening_run('T','minimax','P05','V2-Full',dry=True)
    s=score_run_s(r)
    assert r['requested_count']==0
    assert s['task_success']==1
    assert s['novel_stage']=='N2'
    assert s['verification_waived_decision_irrelevant']==1


def test_dry_minimax_thinking_covariate_false():
    r=execute_screening_run('T','minimax','P08','V0-Baseline',dry=True)
    assert r['thinking_mode'] is False
