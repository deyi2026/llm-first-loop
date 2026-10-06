from __future__ import annotations
import json,pathlib,hashlib,collections
H=pathlib.Path(__file__).resolve().parent
rows=[json.loads(x) for x in (H/'matrix.jsonl').read_text().splitlines() if x.strip()]
plan=json.loads((H/'plan.json').read_text()); assert len(rows)==44 and len(plan['rows'])==44
status=sorted((H/'status').glob('*.json')); assert len(status)==44
latest_healthy=all(json.loads(p.read_text()).get('state')=='terminal' and json.loads(p.read_text()).get('mechanically_healthy') is True for p in status)
valid={'applied','adapted','not_applicable','rejected'}; negative={'not_applicable','rejected'}
def decision(r):
 ds=r.get('record_use_decisions') or []
 return ds[0] if len(ds)==1 and ds[0] in valid else 'MALFORMED'
record_ok=sum(r.get('record_use_count')==1 and r.get('method_manage_calls')==1 for r in rows)
exp_ok=sum(int(r.get('experience_file_count') or 0)>=1 for r in rows)
malformed=sum(decision(r)=='MALFORMED' for r in rows)
weak=[r for r in rows if r['model_key']=='weak']; strong=[r for r in rows if r['model_key']=='strong']
weak_neg=sum(decision(r) in negative for r in weak); weak_acc=weak_neg/len(weak)
fams=sorted({r['family'] for r in rows}); family={}
viable=[]
for f in fams:
 entry={}
 for m in ('strong','weak'):
  rs=[r for r in rows if r['family']==f and r['model_key']==m]; n=len(rs); neg=sum(decision(r) in negative for r in rs); acc=neg/n
  entry[m]={'n':n,'negative':neg,'negative_accuracy':acc,'decisions':dict(collections.Counter(decision(r) for r in rs))}
 # family selection uses the pre-existing V3-CALIBRATION-CONTRACT band 0.45..0.80 on Weak C0 accuracy
 entry['viable']=0.45 <= entry['weak']['negative_accuracy'] <= 0.80
 if entry['viable']: viable.append(f)
 family[f]=entry
gates={'record_use_success':record_ok/44>=.90,'experience_write_success':exp_ok/44>=.90,'weak_negative_accuracy':.35<=weak_acc<=.80,'malformed_rate':malformed/44<=.10,'mechanical_all_healthy':latest_healthy}
result={'schema':'subject-binding-v3-natural-v2-result/v1','verdict':'PASS' if all(gates.values()) else 'HOLD','formal_rows':44,'record_use_ok':record_ok,'record_use_rate':record_ok/44,'experience_write_ok':exp_ok,'experience_write_rate':exp_ok/44,'exactly_one_save_experience_call':sum(r.get('save_experience_calls')==1 for r in rows),'duplicate_save_experience_call_rows':sum((r.get('save_experience_calls') or 0)>1 for r in rows),'weak_negative_decisions':weak_neg,'weak_n':len(weak),'weak_negative_accuracy':weak_acc,'malformed':malformed,'malformed_rate':malformed/44,'gates':gates,'families':family,'viable_families':viable,'input_sha256':{n:hashlib.sha256((H/n).read_bytes()).hexdigest() for n in ('PREREG.md','FREEZE.json','plan.json','matrix.jsonl')}}
(H/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=1)+'\n')
md=['# Subject-Binding v3 Natural Closeout Development Result','',f"**Verdict: {result['verdict']}**",'',f"- record_use success: {record_ok}/44 = {record_ok/44:.4f}",f"- successful experience artifact: {exp_ok}/44 = {exp_ok/44:.4f}",f"- Weak C0 negative-decision accuracy: {weak_neg}/22 = {weak_acc:.4f}",f"- malformed/missing decision: {malformed}/44 = {malformed/44:.4f}",f"- all latest mechanically healthy: {latest_healthy}",f"- exactly-one save_experience tool-call rows: {result['exactly_one_save_experience_call']}/44; duplicate-call rows: {result['duplicate_save_experience_call_rows']}/44 (diagnostic; frozen gate is successful artifact write)",'', '## Family selection']
for f in fams: md.append(f"- {f}: Weak negative accuracy={family[f]['weak']['negative_accuracy']:.4f}, viable={family[f]['viable']}")
md += ['', 'Development instances are permanently non-confirmatory. Only the viable abstract families may seed fresh holdout construction. C1 was never used on development cases.']
(H/'SYNTHESIS.md').write_text('\n'.join(md)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
