"""Gate C negative tests: budgets, replans, contracts, worker receipts.

Every case keeps the real receipt/event in the returned trace — no assertion on
fabricated success. ScriptedStubProvider is used ONLY to exercise runner
mechanisms and is never presented as model autonomy.
"""
from __future__ import annotations

import io
import json

import pytest

from llm_loop.embodied_sim import MuJoCoScene
from llm_loop.embodied_sim.contract import (
    INDEPENDENT_ORACLE_EXECUTION,
    StopNotRequestedError,
    VerificationStatus,
)
from llm_loop.embodied_sim.episode import EpisodeBudget, run_episode
from llm_loop.embodied_sim.oracle import judge_grasp, judge_place, verify_receipt
from llm_loop.embodied_sim.oracle_worker import ORACLE_EXECUTION_STDIN, judge_from_stdin
from llm_loop.embodied_sim.policy import FlakyStubProvider, ScriptedStubProvider, build_prompt
from llm_loop.embodied_sim.skills import EmbodiedInterface


def _iface(clock=None, ledger_path=None):
    s = MuJoCoScene(seed=7)
    s.step(100)
    return EmbodiedInterface(s, ledger_path=ledger_path, clock=clock)


def _cube(iface):
    return iface.observe()["observation"]["cube"]["pos"]


def _mv(cube, dx=0.0, dy=0.0, dz=0.0, key="k"):
    return json.dumps({"skill": "move_to",
                       "params": {"x": cube[0] + dx, "y": cube[1] + dy, "z": cube[2] + dz},
                       "intent_key": key})


def test_expired_observation_ref_halts_with_receipt():
    t = {"n": 0.0}

    def fast_clock():
        t["n"] += 2.0
        return t["n"]

    iface = _iface(clock=fast_clock)
    r = run_episode(iface, ScriptedStubProvider([_mv(_cube(iface), key="k1")]),
                    clock=fast_clock)
    assert r["terminated_by"] == "observation_ref_invalid"
    assert any(e["event"] == "OBSERVATION_EXPIRED" for e in r["trace"])


def test_revoked_grant_halts():
    iface = _iface()
    cube = _cube(iface)
    script = [_mv(cube, key="k1"),
              json.dumps({"skill": "grasp", "params": {}, "intent_key": "k2"})]
    provider = ScriptedStubProvider(script)
    # revoke move_to right before the episode consumes its first decision
    provider.model_used = "stub/scripted"
    r = run_episode(iface, provider)
    # normal run first to prove the harness works, then revoke scenario:
    assert r["terminated_by"] in {"place_verified_locally_pending_oracle", "stop_confirmed",
                                  "no_progress_halt"}
    iface2 = _iface()
    iface2.grants.revoke("move_to")
    r2 = run_episode(iface2, ScriptedStubProvider([_mv(_cube(iface2), key="j1")]))
    assert r2["terminated_by"] == "grant_revoked"
    assert any(e["event"] == "GRANT_REVOKED" for e in r2["trace"])


def test_unknown_skill_rejected_then_replanned(tmp_path):
    iface = _iface(ledger_path=str(tmp_path / "unk_ledger.jsonl"))
    cube = _cube(iface)
    script = [
        json.dumps({"skill": "teleport_cube", "params": {}, "intent_key": "bad1"}),
        _mv(cube, dz=0.07, key="k1"),
        _mv(cube, dz=0.010, key="k2"),
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k3"}),
        json.dumps({"skill": "move_to", "params": {"x": 0.0, "y": 0.18, "z": cube[2] + 0.15}, "intent_key": "k4"}),
        json.dumps({"skill": "release", "params": {}, "intent_key": "k5"}),
    ]
    r = run_episode(iface, ScriptedStubProvider(script))
    # double defense: parse layer rejects first (decision_invalid); the interface
    # layer would reject the same way (execute_rejected/UNKNOWN_SKILL) if reached
    assert any(e["event"] == "decision_invalid" or
               (e.get("event") == "execute_rejected" and e.get("error") == "UNKNOWN_SKILL")
               for e in r["trace"])
    assert r["local_verdict"]["ok"] is True  # recovery after rejection still places the cube
    ledger = iface.ledger
    assert ledger is not None and ledger.reconcile()["chain_ok"] is True


def test_duplicate_intent_key_not_double_counted():
    iface = _iface()
    cube = _cube(iface)
    script = [_mv(cube, dz=0.07, key="dup"),
              _mv(cube, dz=0.07, key="dup"),  # same intent_key -> idempotent no-op
              _mv(cube, dz=0.010, key="k2")]
    r = run_episode(iface, ScriptedStubProvider(script + [
        json.dumps({"skill": "stop", "params": {"reason": "done"}, "intent_key": "kEnd"})]))
    dup_events = [e for e in r["trace"] if e["event"] == "duplicate_intent_key"]
    assert len(dup_events) == 1
    assert r["tool_actions"] == 2  # duplicate did not consume tool budget


def test_repeated_completed_move_rejected_and_feedback_reaches_model():
    iface = _iface()
    cube = _cube(iface)

    class RecordingProvider(ScriptedStubProvider):
        def __init__(self):
            super().__init__([
                _mv(cube, dz=0.07, key="k1"),
                _mv(cube, dz=0.07, key="k2"),  # fresh key, same reached target
                json.dumps({"skill": "stop", "params": {"reason": "hold"},
                            "intent_key": "k3"}),
            ])
            self.states: list[str] = []

        def decide(self, state_text: str) -> str:
            self.states.append(state_text)
            return super().decide(state_text)

    provider = RecordingProvider()
    r = run_episode(iface, provider)
    assert r["terminated_by"] == "stop_confirmed"
    assert r["provider_attempts"] == 3
    assert r["tool_actions"] == iface.tool_action_count == 1
    assert r["replans"] == 1
    rejected = [e for e in r["trace"] if e["event"] == "execute_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["error"] == "REDUNDANT_MOVE_TARGET"
    assert "REDUNDANT_MOVE_TARGET" in provider.states[2]


def test_redundant_move_never_bypasses_grant_or_stop():
    iface = _iface()
    cube = _cube(iface)
    params = {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}
    action = iface.execute_skill("move_to", params, "k1", 1)
    while action["state"] == "running":
        iface.advance(60)
        action = iface.get_action_status(action["action_id"])
    assert action["state"] == "done"
    iface.grants.revoke("move_to")
    from llm_loop.embodied_sim.contract import GrantRevokedError
    with pytest.raises(GrantRevokedError):
        iface.execute_skill("move_to", params, "k2", 1)
    request = iface.stop("safety")
    iface.confirm_stop(request["stop_id"])
    assert iface.execute_skill("move_to", params, "k3", 1)["error"] == "STOP_CONFIRMED"


def test_observable_grasp_affordance_without_oracle_truth():
    iface = _iface()
    cube = _cube(iface)
    assert "grasp_attempt_ready=no" in build_prompt(iface.observe())
    for idx, dz in enumerate((0.07, 0.012), 1):
        action = iface.execute_skill(
            "move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + dz},
            intent_key=f"approach{idx}", grant_version=1,
        )
        while action["state"] == "running":
            iface.advance(60)
            action = iface.get_action_status(action["action_id"])
        assert action["state"] == "done"
    prompt = build_prompt(iface.observe())
    assert "grasp_attempt_ready=yes" in prompt
    assert "contact_pairs" not in prompt
    assert "weld_active" not in prompt


def test_stop_requires_request_before_confirm():
    iface = _iface()
    with pytest.raises(StopNotRequestedError):
        iface.stopper.confirm("stop-999999")
    r = run_episode(iface, ScriptedStubProvider(
        [json.dumps({"skill": "stop", "params": {"reason": "safe hold"}, "intent_key": "kS"})]))
    assert r["terminated_by"] == "stop_confirmed"
    assert r["stop_receipts"]["request"]["state"] == "requested"
    assert r["stop_receipts"]["confirmation"]["state"] == "confirmed"


def test_provider_timeout_recovery():
    iface = _iface()
    cube = _cube(iface)
    script = [_mv(cube, dz=0.07, key="k1"),
              json.dumps({"skill": "stop", "params": {"reason": "done"}, "intent_key": "kE"})]
    provider = FlakyStubProvider(script, failures=2)
    r = run_episode(iface, provider)
    retries = [e for e in r["trace"] if e["event"] == "provider_retry"]
    assert len(retries) == 2 and all(e["error"] == "TimeoutError" for e in retries)
    assert r["terminated_by"] == "stop_confirmed"  # recovery succeeded within budget


def test_tool_action_budget_enforced():
    iface = _iface()
    cube = _cube(iface)
    script = [_mv(cube, dx=0.001 * i, dz=0.07, key=f"k{i}") for i in range(10)]
    script.append(json.dumps({"skill": "stop", "params": {"reason": "never"}, "intent_key": "kZ"}))
    budget = EpisodeBudget(max_provider_attempts=12, max_tool_actions=8)
    r = run_episode(iface, ScriptedStubProvider(script), budget)
    assert r["terminated_by"] == "tool_action_budget_exhausted"
    assert r["tool_actions"] <= r["budget"]["max_tool_actions"]


def test_release_hint_uses_only_model_history_and_public_geometry():
    iface = _iface()
    obs = iface.observe()
    obs["observation"]["tool_pos"] = [0.0, 0.18, 0.09]
    history = [
        {"decision": {"skill": "grasp", "intent_key": "k3"},
         "status": {"state": "done"}},
        {"decision": {"skill": "move_to", "intent_key": "k4"},
         "status": {"state": "done"}},
    ]
    prompt = build_prompt(obs, history)
    assert "release_attempt_ready=yes" in prompt
    assert "weld_active" not in prompt and "contact_pairs" not in prompt
    history.append({"decision": {"skill": "release", "intent_key": "k5"},
                    "status": {"state": "done"}})
    assert "release_attempt_ready=no" in build_prompt(obs, history)


def test_runner_does_not_finish_while_cube_still_welded_over_tray():
    iface = _iface()
    cube = _cube(iface)
    tray = iface.observe()["observation"]["tray_pos"]
    script = [
        _mv(cube, dz=0.07, key="k1"),
        _mv(cube, dz=0.012, key="k2"),
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k3"}),
        json.dumps({"skill": "move_to",
                    "params": {"x": tray[0], "y": tray[1], "z": 0.09},
                    "intent_key": "k4"}),
        json.dumps({"skill": "stop", "params": {"reason": "hold"},
                    "intent_key": "k5"}),
    ]
    r = run_episode(iface, ScriptedStubProvider(script))
    assert r["terminated_by"] == "stop_confirmed"
    assert r["local_verdict"]["ok"] is False
    assert iface.scene.weld_active() is True
    assert r["tool_actions"] == 4


def test_oracle_place_requires_release_and_real_tray_contact():
    snap = {
        "cube": {"pos": [0.0, 0.18, 0.077], "vel": [0.0, 0.0, 0.0]},
        "contact_pairs": [["cube_geom", "fingertip_left", -0.001]],
        "weld_active": True,
    }
    tray = [0.0, 0.18, 0.01]
    ok, ev = judge_place(snap, tray)
    assert ok is False and ev["released"] is False
    snap["weld_active"] = False
    snap["cube"]["pos"][2] = 0.04
    ok, ev = judge_place(snap, tray)
    assert ok is False and ev["tray_contact"] is False
    snap["contact_pairs"] = [["cube_geom", "tray_floor", -0.001]]
    ok, ev = judge_place(snap, tray)
    assert ok is True and ev["released"] and ev["tray_contact"]


def test_local_oracle_grasp_rejects_forged_weld_without_contact():
    snap = {
        "cube": {"pos": [0.1, 0.0, 0.06], "vel": [0.0, 0.0, 0.0]},
        "contact_pairs": [], "weld_active": True,
    }
    ok, ev = judge_grasp(snap)
    assert ok is False and ev["fingertips_contacting"] is False


def test_worker_receipt_is_pending_and_cannot_self_promote(monkeypatch):
    snap_payload = {
        "snapshot": {"t": 1.0,
                     "contact_pairs": [["cube_geom", "fingertip_left", 0.0],
                                       ["cube_geom", "fingertip_right", 0.0]],
                     "cube": {"pos": [0.1, 0.0, 0.06], "vel": [0.0, 0.0, 0.0]},
                     "weld_active": True},
        "claim_kind": "grasp", "scene_epoch": 3, "experiment_id": "M1-SIM-001",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(snap_payload)))
    receipt = judge_from_stdin()
    assert receipt["oracle_execution"] == ORACLE_EXECUTION_STDIN
    assert verify_receipt(receipt, 3, snap_payload["snapshot"]) == VerificationStatus.PENDING_ORACLE
    # editing the execution string alone still cannot reach VERIFIED
    receipt["oracle_execution"] = INDEPENDENT_ORACLE_EXECUTION
    assert verify_receipt(receipt, 3, snap_payload["snapshot"]) == VerificationStatus.PENDING_ORACLE
