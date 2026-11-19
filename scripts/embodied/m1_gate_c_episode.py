#!/usr/bin/env python
"""Gate C: one REAL glm/glm-5.3-flash episode through the thin interface.

No scripted action sequence anywhere in this path: every tool action comes from
a live provider decision parsed via policy.parse_decision. Budgets are the
prereg values (6 provider attempts / 8 tool actions / 180 s / learning off).
The oracle receipt stays PENDING_ORACLE (in-process). UID-463 Worker is
installed, but no trusted Host attestation signer is installed.

Usage:
  set -a; source /path/to/llm-first-loop-mirror/.env; set +a
  data/.venv-m1/bin/python scripts/embodied/m1_gate_c_episode.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.config import load_settings  # noqa: E402
from llm_loop.embodied_sim import MuJoCoScene  # noqa: E402
from llm_loop.embodied_sim.episode import EpisodeBudget, run_episode  # noqa: E402
from llm_loop.embodied_sim.policy import TASK_BRIEF  # noqa: E402
from llm_loop.embodied_sim.skills import EmbodiedInterface  # noqa: E402
from llm_loop.llm.providers import load_registry  # noqa: E402

OUT = ROOT / ("experiments/embodied/m1/gate_c/" + (sys.argv[1] if len(sys.argv) > 1
               else "episode_glm_002.json"))
MODEL_REF = "glm/glm-5.3-flash"
DECISION_MAX_TOKENS = 4096  # engineering iteration after 008 empty content/finish=length


class GLMHttpProvider:
    """Minimal OpenAI-compatible wire client resolved through the LFL registry.

    model_used is the authoritative registry resolution (provider/model), not a
    free string; raw content per call is kept for honest traces.
    """

    def __init__(self, model_ref: str = MODEL_REF, timeout_s: float = 60.0):
        registry = load_registry(load_settings())
        pid, mid = registry.resolve(model_ref)
        params = registry.client_params(pid, mid)
        self.model_used = f"{pid}/{mid}"
        self.wire_model = str(params["model"])
        self._api_key = str(params["api_key"])
        self._base_url = str(params["base_url"]).rstrip("/")
        self._timeout_s = timeout_s
        self.calls: list[dict[str, Any]] = []

    def decide(self, state_text: str) -> str:
        payload = {
            "model": self.wire_model,
            "messages": [
                {"role": "system", "content": TASK_BRIEF},
                {"role": "user", "content": state_text},
            ],
            "temperature": 0,
            "max_tokens": DECISION_MAX_TOKENS,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        t0 = time.monotonic()
        resp = httpx.post(f"{self._base_url}/chat/completions", json=payload,
                          headers=headers, timeout=self._timeout_s)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        content = ""
        if resp.status_code == 200:
            body = resp.json()
            msg = body["choices"][0].get("message", {})
            content = str(msg.get("content") or "")
            finish = str(body["choices"][0].get("finish_reason", ""))
            self.calls.append({"latency_ms": latency_ms, "status": 200,
                               "finish_reason": finish,
                               "content_len": len(content),
                               "content_head": content[:300]})
        else:
            self.calls.append({"latency_ms": latency_ms, "status": resp.status_code,
                               "body_head": resp.text[:200]})
            raise RuntimeError(f"provider HTTP {resp.status_code}")
        return content


def measure_t_stop(iface: EmbodiedInterface) -> dict[str, Any]:
    """t_stop_max_ms provenance for the gate receipt (M0 P2 gap, measured here).

    Definition: request->confirm wall time plus physics steps needed for the
    actuated joints to settle below 1e-3 rad/s after servo targets are zeroed.
    """
    scene = iface.scene
    t0 = time.monotonic()
    req = iface.stop("t_stop provenance measurement")
    conf = iface.confirm_stop(req["stop_id"])
    request_confirm_ms = (time.monotonic() - t0) * 1000.0
    steps = 0
    while steps < 3000:
        qvel_max = max(abs(v) for v in scene.observe()["arm_qvel"])
        if qvel_max < 1e-3:
            break
        scene.step(1)
        steps += 1
    settle_ms = steps * scene.model.opt.timestep * 1000.0
    return {"request_confirm_ms": round(request_confirm_ms, 3),
            "settle_steps": steps, "settle_ms": round(settle_ms, 1),
            "t_stop_max_ms": round(request_confirm_ms + settle_ms, 1),
            "source": "gate_c measured (m1_gate_c_episode.py), timestep=2ms",
            "backfill_for": "M0 P2 prereg gap; old prereg untouched (frozen sha 56f79674...)",
            "stop_request": req, "stop_confirmation": conf}


def main() -> int:
    started = time.time()
    report: dict[str, Any] = {"experiment_id": "M1-SIM-001", "scenario": "L1 place",
                              "model_required_by_prereg": MODEL_REF,
                              "decision_max_tokens": DECISION_MAX_TOKENS,
                              "decision_token_change_note": "Gate C engineering iteration 009: "
                              "2000->4096 after 008 two empty finish=length outputs; "
                              "prereg 6/8/180/learning-off limits unchanged"}
    try:
        provider = GLMHttpProvider()
        report["model_used"] = provider.model_used
        report["wire_model"] = provider.wire_model
    except Exception as e:
        report["status"] = "provider_unavailable"
        report["error"] = f"{type(e).__name__}: {e}"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    scene = MuJoCoScene(seed=7)
    scene.step(100)
    iface = EmbodiedInterface(scene, ledger_path=str(ROOT / "experiments/embodied/m1/gate_c/ledger_glm_001.jsonl"))
    result = run_episode(iface, provider, EpisodeBudget())  # prereg budgets: 6/8/180/off
    result["provider_calls"] = provider.calls
    result["t_stop_provenance"] = measure_t_stop(iface)
    result["oracle_channel_hold"] = {
        "status": "HOLD",
        "reason": "uid 463 (_lfl_oracle) Worker installed and Host-accepted, "
                  "but trusted snapshot-provenance attestation signer NOT_INSTALLED. "
                  "Caller-provided Oracle receipts cannot be promoted to VERIFIED.",
        "independent_verification": "PENDING_ORACLE",
    }
    result["status"] = "ok"
    result["elapsed_wall_s"] = round(time.time() - started, 3)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "model_used", "terminated_by", "provider_attempts", "tool_actions",
        "replans", "elapsed_s", "local_verdict", "oracle_execution",
        "t_stop_provenance")}, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
