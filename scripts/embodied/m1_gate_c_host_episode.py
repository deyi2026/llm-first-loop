#!/usr/bin/env python3
"""Gate C: Host-linked autonomous episode (real glm/glm-5.3-flash decisions).

The client holds NO scene. Observations and actions go through the Host-owned
UID463 oracle daemon file queue (request_attestation). Two distinct receipt
shapes exist (measured live):
- observe/action receipts carry ONLY {action_seq, observation|action_status,
  oracle_execution, run_id} - no nonce, no scene_epoch. Binding checks for
  them are therefore limited to run_id, action_seq and the Host execution
  identity (runtime/run.json UID463 ownership).
- verify_grasp/verify_place CLAIM receipts carry the FULL binding
  (scene_epoch, nonce, snapshot_hash, uid, experiment_id, signature) and are
  the only path to VERIFIED_BY_ORACLE via request_host_verification.
The model sees ONLY projected public observations (including pre_grasp_point);
oracle verdicts, privileged snapshots, weld/contact truth never enter model
state. No scripted sequences: every move/grasp/release is a live model decision.

Fail-closed before any model call:
- Host runtime identity must be UID463-owned and M1-SIM-001 (run.json);
- freshness: seq-0 observe must show physics time within the deterministic
  initialization baseline (scene.step(100) @ 2ms = 0.2s; gate t <= 0.25) and
  action_seq == 0; anything else => HostStaleSceneError, approved Host-only
  restart required (never performed by this client).
- model stop is recorded as stop_requested_client_only: the daemon whitelist
  has no stop command, so no two-phase Host stop is ever claimed.
Frozen prereg budget: 6 provider attempts / 8 tool actions / 180s / learning off.
Provider secrets are never logged (only model_used, per-call status/latency).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "embodied"))

from llm_loop.embodied_sim.attestation import (  # noqa: E402
    AttestationUnavailableError,
    canonical,
    request_attestation,
)
from llm_loop.embodied_sim.host_bridge import (  # noqa: E402
    request_host_verification,
)
from llm_loop.embodied_sim.policy import TASK_BRIEF, build_prompt, parse_decision  # noqa: E402

RUN_INFO = Path("/private/var/run/lfl-m1-oracle/runtime/run.json")
BUDGET = {"max_provider_attempts": 6, "max_tool_actions": 8,
          "deadline_s": 180.0, "learning": "off"}
# Deterministic init baseline: build_daemon_from_scene_seed steps 100 ticks of
# 2ms = 0.2s of physics time before the first client action.
FRESH_T_MAX_S = 0.25
HOST_CLAIM_EXECUTION = "host_uid463_managed"
HOST_RUNTIME_EXECUTIONS = {"observe": "observation_only", "action": "action_only"}
PUBLIC_OBS_KEYS = ("t", "tool_pos", "cube", "tray_pos", "finger_qpos",
                   "pre_grasp_point")
PUBLIC_STATUS_KEYS = ("action_id", "skill", "state", "reason",
                      "last_err_m", "final_err_m", "steps")
EPISODE_EVIDENCE_PATH = ROOT / ("experiments/embodied/m1/gate_c/"
                                "episode_host_linked_latest.json")


class HostStaleSceneError(RuntimeError):
    """Host scene is not fresh: approved Host-only restart required."""


class HostLinkError(RuntimeError):
    """Daemon/verifier contract violation: fail closed."""


def load_run_identity() -> dict[str, Any]:
    run = json.loads(RUN_INFO.read_text(encoding="utf-8"))
    if RUN_INFO.stat().st_uid != 463:
        raise HostLinkError("run identity not UID463-owned")
    if len(run.get("run_id", "")) != 32 or run.get("experiment_id") != "M1-SIM-001":
        raise HostLinkError("invalid Host run identity")
    return run


def project_public_obs(observation: dict[str, Any]) -> dict[str, Any]:
    """Whitelist projection: documented public physics only (incl.
    pre_grasp_point). Privileged truth excluded by construction."""
    return {k: observation[k] for k in PUBLIC_OBS_KEYS if k in observation}


def project_public_status(status: dict[str, Any]) -> dict[str, Any]:
    """Exclude Host-private contact/weld mechanism from model feedback."""
    return {k: status[k] for k in PUBLIC_STATUS_KEYS if k in status}


def assert_runtime_binding(receipt: dict[str, Any], *, run_id: str, seq: int,
                           expected_kind: str) -> None:
    """Check Host queue shape and identity, never treat unsigned runtime as a claim."""
    if receipt.get("oracle_execution") == "daemon_fail_closed":
        raise HostLinkError(f"daemon rejected command: {receipt.get('error')}")
    if expected_kind not in HOST_RUNTIME_EXECUTIONS:
        raise HostLinkError("unknown Host runtime receipt kind")
    expected_execution = HOST_RUNTIME_EXECUTIONS[expected_kind]
    if receipt.get("oracle_execution") != expected_execution:
        raise HostLinkError("Host runtime receipt kind mismatch")
    payload_key = "observation" if expected_kind == "observe" else "action_status"
    if set(receipt) != {"action_seq", "run_id", "oracle_execution", payload_key}:
        raise HostLinkError("Host runtime receipt fields mismatch")
    if receipt.get("run_id") != run_id:
        raise HostLinkError("stale/foreign run_id in daemon receipt")
    if int(receipt.get("action_seq", -1)) != int(seq):
        raise HostLinkError("action_seq mismatch in daemon receipt")


def assert_claim_receipt_shape(receipt: dict[str, Any]) -> None:
    """Claim receipts MUST carry the full binding set (they are signed)."""
    required = ("claim_kind", "run_id", "scene_epoch", "action_seq", "nonce",
                "snapshot_hash", "oracle_execution", "verdict", "uid",
                "experiment_id", "oracle_impl", "evidence", "signature")
    missing = [k for k in required if k not in receipt]
    if missing:
        raise HostLinkError(f"claim receipt missing signed binding fields: {missing}")
    if receipt.get("oracle_execution") != HOST_CLAIM_EXECUTION:
        raise HostLinkError("claim receipt not from Host UID463 execution")


class HostOracleLink:
    """Production link: file-queue attestation + Host signed verification."""

    def __init__(self, run: dict[str, Any] | None = None):
        self.run = run or load_run_identity()

    def observe(self, seq: int) -> dict[str, Any]:
        _, receipt = request_attestation({"skill": "observe"},
                                         run_id=self.run["run_id"],
                                         action_seq=seq, timeout_s=30)
        assert_runtime_binding(receipt, run_id=self.run["run_id"], seq=seq,
                               expected_kind="observe")
        return receipt

    def execute(self, command: dict[str, Any], seq: int) -> dict[str, Any]:
        _, receipt = request_attestation(command, run_id=self.run["run_id"],
                                         action_seq=seq, timeout_s=30)
        assert_runtime_binding(receipt, run_id=self.run["run_id"], seq=seq,
                               expected_kind="action")
        return receipt

    def verify(self, claim_kind: str, seq: int) -> dict[str, Any]:
        """Host-signed claim path: request verify_grasp/verify_place, then let
        request_host_verification check the FULL signed binding. Action-only
        receipts are never verified."""
        if claim_kind not in ("grasp", "place"):
            raise HostLinkError(f"unsupported claim_kind {claim_kind!r}")
        nonce, signed = request_attestation(
            {"skill": f"verify_{claim_kind}"},
            run_id=self.run["run_id"], action_seq=seq, timeout_s=30)
        assert_claim_receipt_shape(signed)
        # Bind to trusted run.json and the client-issued nonce, never to
        # attacker-supplied values copied back out of the receipt.
        if (signed["claim_kind"] != claim_kind
                or signed["run_id"] != self.run["run_id"]
                or signed["experiment_id"] != self.run["experiment_id"]
                or signed["scene_epoch"] != self.run["scene_epoch"]
                or signed["action_seq"] != seq
                or signed["nonce"] != nonce
                or signed["uid"] != 463):
            raise HostLinkError("signed claim binding mismatch")
        status = request_host_verification(
            signed,
            expected_run=self.run["run_id"],
            expected_epoch=int(self.run["scene_epoch"]),
            expected_action_seq=int(seq),
            expected_nonce=nonce,
            expected_experiment_id=self.run["experiment_id"],
            expected_claim_kind=claim_kind,
            timeout_s=30)
        if status.name != "VERIFIED_BY_ORACLE":
            raise HostLinkError(f"host verification rejected: {status.name}")
        return {"status": "VERIFIED_BY_ORACLE", "claim_kind": claim_kind,
                "action_seq": int(seq), "scene_epoch": int(self.run["scene_epoch"]),
                "nonce": nonce, "signed_receipt_sha256": hashlib.sha256(canonical(signed)).hexdigest(),
                "signed_receipt": signed}


def fresh_precheck(link: HostOracleLink) -> dict[str, Any]:
    """Seq-0 freshness gate. A freshly launched daemon carries ~0.2s of
    deterministic init physics (scene.step(100) @ 2ms); anything beyond the
    baseline, or a non-zero action_seq, means prior use => restart required."""
    receipt = link.observe(0)
    obs = receipt.get("observation", {})
    t = float(obs.get("t", -1.0))
    if t < 0.0 or t > FRESH_T_MAX_S:
        raise HostStaleSceneError(
            f"host scene physics time t={t}s outside fresh init baseline "
            f"(<= {FRESH_T_MAX_S}s): approved Host-only restart required")
    if int(receipt.get("action_seq", -1)) != 0:
        raise HostStaleSceneError(
            "host scene has prior actions (action_seq!=0): restart required")
    return receipt


def run_host_episode(provider: Any, link: Any, *, clock: Any = None,
                     budget: dict[str, Any] | None = None,
                     fresh_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    now = clock or time.monotonic
    budget = budget or BUDGET
    t0 = now()
    run = link.run
    seq = 0
    attempts = 0
    tools = 0
    replans = 0
    used_intents: set[str] = set()
    history: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    terminated_by: str | None = None
    stop_receipts: dict[str, str] = {}
    host_claims: dict[str, Any] = {}
    try:
        public_last = project_public_obs((fresh_receipt or link.observe(0))["observation"])
    except (AttestationUnavailableError, HostLinkError) as e:
        return {"terminated_by": "host_fail_closed",
                "trace": [{"event": "HOST_FAIL_CLOSED", "detail": str(e)}],
                "provider_attempts": 0, "tool_actions": 0, "replans": 0,
                "elapsed_s": 0.0, "stop_receipts": {}, "host_claims": {},
                "model_used": getattr(provider, "model_used", "unknown"),
                "learning": budget["learning"],
                "oracle_binding": "host_uid463_managed (daemon-signed; client holds public key only)"}

    def elapsed() -> float:
        return now() - t0

    def observe_current() -> dict[str, Any]:
        nonlocal seq, terminated_by
        try:
            receipt = link.observe(seq)
        except (AttestationUnavailableError, HostLinkError) as e:
            trace.append({"event": "HOST_FAIL_CLOSED", "detail": str(e)})
            terminated_by = "host_fail_closed"
            return public_last
        return project_public_obs(receipt["observation"])

    while terminated_by is None:
        if attempts >= budget["max_provider_attempts"]:
            terminated_by = "provider_attempt_budget_exhausted"
            break
        if tools >= budget["max_tool_actions"]:
            terminated_by = "tool_action_budget_exhausted"
            break
        if elapsed() > budget["deadline_s"]:
            terminated_by = "episode_deadline_exceeded"
            break
        public_last = observe_current()
        if terminated_by is not None:
            break
        state_text = TASK_BRIEF + " | " + build_prompt(
            {"observation": public_last}, history)
        try:
            raw = provider.decide(state_text)
        except Exception as e:
            attempts += 1
            replans += 1
            trace.append({"event": "provider_retry", "attempts": attempts,
                          "error": type(e).__name__})
            continue
        attempts += 1
        try:
            decision = parse_decision(raw)
        except Exception:
            replans += 1
            trace.append({"event": "decision_invalid", "attempts": attempts})
            continue
        intent = decision["intent_key"]
        if intent in used_intents:
            replans += 1
            trace.append({"event": "duplicate_intent_key", "intent_key": intent})
            continue
        used_intents.add(intent)
        skill = decision["skill"]
        if skill == "stop":
            # The daemon whitelist has no stop command: record a client-only
            # request and HOLD. Never claim a two-phase Host safety stop.
            stop_receipts = {"requested": intent,
                             "state": "stop_requested_client_only"}
            trace.append({"event": "stop_requested_client_only",
                          "reason": decision["params"].get("reason")})
            terminated_by = "stop_requested_client_only"
            break
        seq += 1
        tools += 1
        try:
            action = link.execute({"skill": skill, "params": decision["params"]}, seq)
        except (AttestationUnavailableError, HostLinkError) as e:
            trace.append({"event": "HOST_FAIL_CLOSED", "detail": str(e)})
            terminated_by = "host_fail_closed"
            break
        status = action.get("action_status", {})
        public_status = project_public_status(status)
        trace.append({"event": "tool_action", "decision": decision, "seq": seq,
                      "status": public_status, "t_s": round(elapsed(), 3)})
        history.append({"decision": decision, "status": public_status})
        if skill == "grasp" and status.get("state") == "done":
            try:
                # Host-side verify_grasp advances ~30 physics steps on the daemon
                # scene; the client never advances physics itself.
                host_claims["grasp"] = link.verify("grasp", seq)
            except (AttestationUnavailableError, HostLinkError) as e:
                trace.append({"event": "HOST_FAIL_CLOSED", "detail": str(e)})
                terminated_by = "host_fail_closed"
                break
        if skill == "release" and status.get("state") == "done":
            public_last = observe_current()
            if terminated_by is not None:
                break
            tray = public_last.get("tray_pos")
            cube = public_last.get("cube", {}).get("pos")
            inside = bool(tray and cube
                          and abs(cube[0] - tray[0]) < 0.055
                          and abs(cube[1] - tray[1]) < 0.055)
            if inside:
                try:
                    # Host-side verify_place performs the 150-step settling and
                    # judges from its own privileged snapshot.
                    host_claims["place"] = link.verify("place", seq)
                    terminated_by = ("place_host_verified" if elapsed() <= budget["deadline_s"]
                                     else "episode_deadline_exceeded")
                except (AttestationUnavailableError, HostLinkError) as e:
                    trace.append({"event": "HOST_FAIL_CLOSED", "detail": str(e)})
                    terminated_by = "host_fail_closed"
                break

    if terminated_by is None:
        terminated_by = "no_progress_halt"
    return {
        "experiment_id": run.get("experiment_id", "M1-SIM-001"),
        "model_used": getattr(provider, "model_used", "unknown"),
        "learning": budget["learning"],
        "terminated_by": terminated_by,
        "provider_attempts": attempts,
        "tool_actions": tools,
        "replans": replans,
        "elapsed_s": round(elapsed(), 3),
        "stop_receipts": stop_receipts,
        "host_claims": host_claims,
        "oracle_binding": "host_uid463_managed (daemon-signed; client holds public key only)",
        "trace": trace,
    }


def main(argv: list[str]) -> int:
    try:
        run = load_run_identity()
    except (HostLinkError, OSError, json.JSONDecodeError) as e:
        print(json.dumps({"status": "HOLD", "reason": f"host identity: {e}"}))
        return 1
    try:
        link = HostOracleLink(run)
        fresh_receipt = fresh_precheck(link)
    except (AttestationUnavailableError, HostLinkError, HostStaleSceneError) as e:
        print(json.dumps({"status": "HOLD", "reason": str(e),
                          "action": "approved Host-only restart required before GLM run"}))
        return 1
    if "--check-fresh-only" in argv:
        print(json.dumps({"status": "FRESH"}))
        return 0

    # Real provider + bounded evidence. Secrets never logged.
    try:
        from m1_gate_c_episode import GLMHttpProvider  # type: ignore
        provider = GLMHttpProvider()
    except Exception as e:
        print(json.dumps({"status": "HOLD",
                          "reason": f"provider unavailable: {type(e).__name__}"}))
        return 2
    result = run_host_episode(provider, link, fresh_receipt=fresh_receipt)
    result["provider_calls_bounded"] = [
        {k: c.get(k) for k in ("latency_ms", "status", "finish_reason")}
        for c in getattr(provider, "calls", [])][: result["provider_attempts"]]
    evidence_path = EPISODE_EVIDENCE_PATH
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    verified = (result.get("terminated_by") == "place_host_verified"
                and result.get("elapsed_s", 999) <= BUDGET["deadline_s"]
                and result.get("host_claims", {}).get("place", {}).get("status")
                == "VERIFIED_BY_ORACLE")
    print(json.dumps({"status": "PLACE_HOST_VERIFIED" if verified else "NOT_VERIFIED",
                      "terminated_by": result["terminated_by"],
                      "provider_attempts": result["provider_attempts"],
                      "tool_actions": result["tool_actions"],
                      "model_used": result["model_used"],
                      "evidence": str(evidence_path)}))
    return 0 if verified else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
