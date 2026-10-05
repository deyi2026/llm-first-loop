from __future__ import annotations
import hashlib,json,pathlib,re
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PM=ROOT/'evals/method_binding_efficacy_v2/provider_matrix_v1'
V1=ROOT/'evals/method_binding_efficacy_v1'
plan=json.loads((PM/'matrix_plan.json').read_text())
rows=[json.loads(x) for x in (PM/'run2_matrix.jsonl').read_text().splitlines()]
latest={(r['model_key'],r['case_id'],r['arm']):r for r in rows if r.get('kind')=='formal'}
B=[cid for cid in plan['selected_case_ids'] if plan['cases'][cid]['cell']=='B']
assert len(B)==13
ANTI=[r'没有',r'不存在',r'不需要',r'不是',r'尚未',r'非[A-Za-z\u4e00-\u9fff]{1,12}']
SCOPE=[r'只需要',r'只问',r'当前唯一目标',r'只是',r'先[^。；]{0,24}(?:再|决定|核)']
manual={
 'sb2-B07':'positive_alternative_path_giveaway',
 'sb2-B09':'positive_alternative_path_giveaway',
}
case_rows=[]
for cid in B:
 c=plan['cases'][cid]; task=c['task']
 neg=[]
 for p in ANTI: neg += re.findall(p,task,re.I)
 scope=[]
 for p in SCOPE: scope += re.findall(p,task,re.I)
 out={'case_id':cid,'task':task,'subject_method_id':c['subject_method_id'],'purpose_divergence':c.get('purpose_divergence'),'explicit_anti_trigger_hits':neg,'exclusive_scope_hits':scope,'leak_class':'explicit_anti_trigger_leak' if neg else manual.get(cid,'none')}
 for m in ('strong','weak'):
  r=latest[(m,cid,'C0')]
  out[m+'_c0_final']=r.get('final_answer','')
  out[m+'_c0_correct']=r.get('final_answer','').find('APPLICABILITY_VERDICT: SKIP')>=0
  out[m+'_c0_tool_calls']=r.get('tool_call_count',0)
 case_rows.append(out)
assert all(x['strong_c0_correct'] and x['weak_c0_correct'] for x in case_rows)
# Historical hard exemplar: latest-wins mb-024 from v1.
v1rows=[json.loads(x) for x in (V1/'matrix.jsonl').read_text().splitlines()]
v1latest={}
for r in v1rows:
 if r.get('kind')=='formal': v1latest[(r['case_id'],r['arm'])]=r
pool=json.loads((V1/'pool.json').read_text())['cases']
mb=pool['mb-024']; mbtask=mb['trigger']
mbneg=[]
for p in ANTI: mbneg += re.findall(p,mbtask,re.I)
mb24={'task':mbtask,'subject_method_id':mb['method_ref'].removeprefix('method:'),'trigger_source':mb['trigger_source'],'explicit_anti_trigger_hits':mbneg,'latest_C0':v1latest[('mb-024','C0')]['final_answer'],'latest_C1':v1latest[('mb-024','C1')]['final_answer']}
protocol=(PM/'protocol.py').read_text()
registry=(ROOT/'src/llm_loop/introspection/registry_experience.py').read_text()
res=json.loads((PM/'RESULT-RUN2.json').read_text())
result={
 'schema':'subject-binding-opportunity-forensic/v1',
 'source_run2_result_sha256':hashlib.sha256((PM/'RESULT-RUN2.json').read_bytes()).hexdigest(),
 'selected_B':13,
 'realized_control_errors':{'strong':sum(not x['strong_c0_correct'] for x in case_rows),'weak':sum(not x['weak_c0_correct'] for x in case_rows)},
 'explicit_anti_trigger_leak_cases':sum(x['leak_class']=='explicit_anti_trigger_leak' for x in case_rows),
 'positive_alternative_path_giveaway_cases':sum(x['leak_class']=='positive_alternative_path_giveaway' for x in case_rows),
 'exclusive_scope_cases':sum(bool(x['exclusive_scope_hits']) for x in case_rows),
 'all_B_have_easy_skip_channel':all(x['leak_class']!='none' for x in case_rows),
 'protocol_facts':{
   'prompt_explicitly_requests_applicability': '请判断该 Method 是否适用于当前任务' in protocol,
   'prompt_injects_full_card': '{card}' in protocol,
   'prompt_mentions_save_experience': 'save_experience' in protocol.split("FORMAL_PROMPT=",1)[1].split("PREFLIGHT_PROMPT=",1)[0],
   'binding_text_mentions_save_experience': '判断它是否适用于本次 save_experience' in registry,
   'binding_appended_to_save_experience_tool_def': 'row["description"] = str(row["description"]).rstrip() + "\\n" + METHOD_SUBJECT_BINDING_TEXT' in registry,
   'control_tool_calls':{'strong':res['models']['strong']['cost']['tool_calls']['C0'],'weak':res['models']['weak']['cost']['tool_calls']['C0']},
 },
 'historical_hard_exemplar_mb024':mb24,
 'cases':case_rows,
 'conclusion':'failure_of_opportunity: v2 B labels were valid but confirmatory tasks exposed SKIP too directly; label validity was misused as a headroom proxy, while the explicit applicability/full-card prompt further compressed treatment opportunity.'
}
(HERE/'OPPORTUNITY-FORENSIC.json').write_text(json.dumps(result,ensure_ascii=False,indent=1)+'\n')
print(json.dumps({k:result[k] for k in ('selected_B','realized_control_errors','explicit_anti_trigger_leak_cases','positive_alternative_path_giveaway_cases','exclusive_scope_cases','all_B_have_easy_skip_channel','protocol_facts','historical_hard_exemplar_mb024','conclusion')},ensure_ascii=False,indent=2))
