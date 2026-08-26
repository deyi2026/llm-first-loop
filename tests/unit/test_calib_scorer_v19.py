import json
from pathlib import Path
from scripts.calib.scorer_v19 import novel_stage,truth_integrated,source_successfully_verified
ROOT=Path(__file__).resolve().parents[2]

def tr(source,result):return [{'name':'request_fixture','source':source,'result_full':result,'round':1}]
def test_n4_success_plus_asserted_truth():assert novel_stage(tr('fixture://x','{"state":"blocked"}'),'fixture://x','Final Decision\n当前 state=blocked，已核实。',['state=blocked','blocked'])=='N4'
def test_n3_success_but_final_claims_unverified():assert novel_stage(tr('fixture://x','{"state":"blocked"}'),'fixture://x','Final Decision\n当前 state 未核实；若后续确认 blocked 再处理。',['state=blocked','blocked'])=='N3'
def test_n2_requested_but_source_failed():assert novel_stage(tr('fixture://x','SOURCE_LIMIT_EXCEEDED'),'fixture://x','需要后续核实。',['blocked'],verification_plan=True)=='N2'
def test_conditional_truth_not_integrated():assert not truth_integrated('若后续核实到 quorum unhealthy，则拒绝。',['quorum unhealthy'])
def test_h2e_019_development_becomes_n3():
 o=json.loads((ROOT/'data/calib/runs_h2e/H2E-019.json').read_text())
 assert novel_stage(o['trace'],'fixture://K04/quorum_status',o['final_answer'],['quorum_healthy=false','quorum unhealthy','2/3 voters'])=='N3'
def test_source_success_requires_real_non_error_result():
 assert source_successfully_verified(tr('fixture://x','{"ok":true}'),'fixture://x')
 assert not source_successfully_verified(tr('fixture://x','SOURCE_NOT_AVAILABLE'),'fixture://x')
