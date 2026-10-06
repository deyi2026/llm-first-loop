import importlib.util,json,pathlib,sys
H=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(H))
from protocol import parse_verdict,MODELS
from healthcheck import is_healthy

def test_plan_shape():
 p=json.loads((H/'matrix_plan.json').read_text()); assert p['counts']=={'cases':21,'B':13,'C':8,'blocks':42,'formal_cells':84,'c0_first_blocks':21,'c1_first_blocks':21}; assert len({r['row_id'] for r in p['formal_rows']})==84

def test_parse_verdict():
 assert parse_verdict('APPLICABILITY_VERDICT: APPLY | SUBJECT: x | REASON: y')=='APPLY'; assert parse_verdict('junk')=='OTHER'

def test_health_requires_settlement_and_model():
 r={'status':'RUN_OK','truncated':False,'fallback_used':False,'model_key':'strong','model_used':MODELS['strong']['canonical'],'settlement_ok':True,'run_end_completed':True,'request_meta_tools_fp':'x'}; assert is_healthy(r); r['settlement_ok']=False; assert not is_healthy(r)

def test_selected_are_certified_bc_only():
 g=json.loads((H.parent/'GOLDSET-RESULT.json').read_text()); p=json.loads((H/'matrix_plan.json').read_text()); cert={x['case_id'] for x in g['per_case'] if x['certified'] and x['cell'] in {'B','C'}}; assert set(p['selected_case_ids'])==cert
