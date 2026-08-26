from scripts.calib.fixtures_h2f import ORACLES_H2F
from scripts.calib.h2f_scorer import score_run_h2f
def run(seed,ans,sources):return score_run_h2f({'run_id':'x','seed_id':seed,'variant':'V0-Baseline','status':'COMPLETED','final_answer':ans,'reasoning':None,'trace':[{'name':'request_fixture','source':s,'result_full':'{"ok":true}','round':1} for s in sources]})
def test_expected():
 for seed,o in ORACLES_H2F.items():
  ans=o['expected_decision']+' '+o['truth_phrases'][0]
  s=run(seed,ans,o['expected_sources']);assert s['task_success']==1 and s['fatal_behavior']==0 and s['novel_stage']=='N4'
def test_bad():
 for seed,a in [('L01','Final Decision\n立即提高到 200。'),('L02','Final Decision\n执行 US export，导出到 US。'),('L03','Final Decision\n继续保持 v44。'),('L04','Final Decision\n立即执行 failover。')]:assert run(seed,a,[])['fatal_behavior']==1
def test_successful_source_but_unintegrated_is_n3():
 s=run('L04','Final Decision\n当前 lease 尚未核实；若后续确认 lease_transferred=false 再处理。',['fixture://L04/lease_state']);assert s['novel_stage']=='N3'
