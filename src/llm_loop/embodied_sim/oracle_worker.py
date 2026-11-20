"""Independent oracle worker entrypoint (read-only truth input, stdout receipt).

Designed for Host-managed cross-UID execution, e.g.:
  sudo -u _lfl_oracle python -m llm_loop.embodied_sim.oracle_worker grasp < snap.json
It reads exactly one snapshot JSON from stdin, judges it, and writes one receipt
JSON to stdout. It performs NO network I/O, NO filesystem writes, and reads NO
environment variables. Its receipts carry
oracle_execution="oracle_worker_stdin" and can NEVER reach VERIFIED_BY_ORACLE
by themselves: the Host acceptance block is added only by the managed channel
after real cross-UID execution, and verify_receipt_fields() treats any
caller-provided execution string without that block as PENDING_ORACLE.

Cross-UID execution today: uid 463 (_lfl_oracle) exists per Host read-only
check, but non-interactive sudo requires a password (exit 1) — the real
hand-off is therefore HOLD pending a formal Host authorization request.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from llm_loop.embodied_sim.oracle import judge_grasp, judge_place, make_receipt

ORACLE_EXECUTION_STDIN = "oracle_worker_stdin"


def judge_from_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw)
    snapshot = payload["snapshot"]
    kind = str(payload.get("claim_kind", "grasp"))
    scene_epoch = int(payload.get("scene_epoch", 0))
    experiment_id = str(payload.get("experiment_id", "unknown"))
    if kind == "grasp":
        ok, evidence = judge_grasp(snapshot)
    elif kind == "place":
        ok, evidence = judge_place(snapshot, payload["tray_pos"])
    else:
        raise ValueError(f"unsupported claim_kind '{kind}'")
    receipt = make_receipt(snapshot, kind, ok, evidence, experiment_id, scene_epoch)
    receipt["oracle_execution"] = ORACLE_EXECUTION_STDIN
    return receipt


def main() -> int:
    try:
        receipt = judge_from_stdin()
    except Exception as e:  # fail-closed: any malformed input yields a failure receipt
        receipt = {"oracle_execution": ORACLE_EXECUTION_STDIN, "verdict": "failure",
                   "error": f"{type(e).__name__}: {e}"}
    json.dump(receipt, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
