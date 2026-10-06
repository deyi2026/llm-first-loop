from protocol import MODELS

def is_healthy(r:dict)->bool:
 return bool(r.get('status')=='RUN_OK' and r.get('model_key') in MODELS and r.get('model_used')==MODELS[r['model_key']]['canonical'] and not r.get('fallback_used') and not r.get('truncated') and r.get('settlement_ok') is True and r.get('run_end_completed') is True and r.get('binding_asserted')==(r.get('arm')=='C1'))
