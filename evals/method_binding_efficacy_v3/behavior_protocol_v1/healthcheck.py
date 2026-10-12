from dev_protocol import MODELS

def is_healthy(row:dict)->bool:
 if row.get('status')!='RUN_OK': return False
 if row.get('truncated') or row.get('fallback_used'): return False
 model=row.get('model_key')
 if model not in MODELS or row.get('model_used')!=MODELS[model]['canonical']: return False
 if not row.get('settlement_ok'): return False
 if not row.get('run_end_completed'): return False
 if not row.get('request_meta_tools_fp'): return False
 return True
