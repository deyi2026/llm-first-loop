"""Runner/Analyzer v2 shared health gate.
Root-cause fixes: D4 (v1 healthy() compared bare MODEL vs canonical model_used -> every cell double-ran)
and v1 analyze.py line-19 operator-precedence latent bug (A and B and C and D==X or E is True).
Single source of truth; both run_matrix_v2 and analyze_v2 must import from here."""
from protocol import MODEL_CANONICAL

def is_healthy(row: dict) -> bool:
    if row.get("status") != "RUN_OK":
        return False
    if row.get("truncated") or row.get("fallback_used"):
        return False
    flag = row.get("model_canonical_ok")
    if flag is not None:                      # worker v1+ always emits it on RUN_OK
        return flag is True
    return row.get("model_used") == MODEL_CANONICAL  # legacy rows without the flag
