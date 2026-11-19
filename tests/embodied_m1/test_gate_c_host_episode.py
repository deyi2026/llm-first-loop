"""Gate C Host-linked client tests against ACTUAL receipt shapes measured live.

Observe/action receipts carry ONLY {action_seq, observation|action_status,
oracle_execution, run_id} (no nonce, no scene_epoch - measured on live
observe(seq6) with t=3.108). Claim receipts carry the full signed binding.
Mocks sit exactly on the real API surface: request_attestation -> (nonce,
receipt); request_host_verification(receipt, expected_run, expected_epoch,
expected_action_seq, expected_nonce, expected_experiment_id,
expected_claim_kind, timeout_s) -> VerificationStatus.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_scripts = str(ROOT / "scripts" / "embodied")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import m1_gate_c_host_episode as host_episode  # noqa: E402

from llm_loop.embodied_sim.attestation import VerificationStatus  # noqa: E402
from llm_loop.embodied_sim.paired_budget import PairedCostHold  # noqa: E402
from llm_loop.embodied_sim.policy import ScriptedStubProvider  # noqa: E402

RUN_ID = "a" * 32
RUN = {"run_id": RUN_ID, "experiment_id": "M1-SIM-001", "scene_epoch": 1}
TRIAL = {"phase": "smoke", "arm": "B2", "trial_index": 7, "seed": 7}


def _obs(t: float) -> dict:
    return {"t": t, "tool_pos": [0.18, 0.0, 0.05],
            "cube": {"pos": [0.18, 0.0, 0.02], "vel": [0.0, 0.0, 0.0]},
            "tray_pos": [0.0, 0.18, 0.01], "finger_qpos": [0.0, 0.0],
            "pre_grasp_point": [0.18, 0.0, 0.08]}


def _observe_receipt(run_id: str, seq: int, t: float) -> dict:
    """Measured live shape: no nonce, no scene_epoch keys."""
    return {"action_seq": seq, "observation": _obs(t),
            "oracle_execution": "observation_only", "run_id": run_id}


def _action_receipt(run_id: str, seq: int, state: str = "done") -> dict:
    return {"action_seq": seq, "action_status": {"state": state},
            "oracle_execution": "action_only", "run_id": run_id}


def _claim_receipt(run_id: str, seq: int, nonce: str, epoch: int,
                   claim: str, verdict: str = "success") -> dict:
    return {"claim_kind": claim.removeprefix("verify_"), "run_id": run_id, "scene_epoch": epoch,
            "action_seq": seq, "nonce": nonce, "snapshot_hash": "f" * 64,
            "oracle_execution": "host_uid463_managed", "verdict": verdict,
            "uid": 463, "experiment_id": "M1-SIM-001", "signature": "ab" * 64,
            "oracle_impl": "embodied-m1-oracle-daemon-v0",
            "evidence": {"disclosed": "contact_confirmed_weld"}}


class _FakeQueue:
    """Dispatches at the REAL API surface with LIVE receipt shapes."""

    def __init__(self, obs_t: float = 0.2):
        self.obs_t = obs_t
        self.obs_calls = 0
        self.cube_pos = [0.18, 0.0, 0.02]
        self.grasped = False
        self.events: list[str] = []
        self.commands: list[dict] = []
        self.verify_kwargs: list[dict] = []
        self.verify_status = VerificationStatus.VERIFIED_BY_ORACLE

    def request_attestation(self, command, *, run_id, action_seq, timeout_s=30):
        skill = command.get("skill")
        if skill == "observe":
            self.obs_calls += 1
            receipt = _observe_receipt(run_id, action_seq, self.obs_t)
            receipt["observation"]["cube"]["pos"] = list(self.cube_pos)
            return "ignored", receipt
        if skill in ("verify_grasp", "verify_place"):
            self.events.append(skill)
            nonce = ("a" if skill == "verify_grasp" else "b") * 32
            return nonce, _claim_receipt(run_id, action_seq, nonce, 1, skill)
        if skill == "grasp":
            self.grasped = True
        if skill == "move_to" and self.grasped:
            # Public observation reflects the cube following the gripper.
            params = command["params"]
            self.cube_pos = [params["x"], params["y"],
                             max(0.02, params["z"] - 0.01)]
        if skill == "release":
            # daemon physics: after a release the cube rests in the tray
            self.cube_pos = [0.0, 0.18, 0.02]
            self.grasped = False
        self.events.append(skill)
        self.commands.append(command)
        return "c" * 32, _action_receipt(run_id, action_seq)

    def request_host_verification(self, receipt, **kwargs):
        self.verify_kwargs.append({"receipt": receipt, **kwargs})
        return self.verify_status


@pytest.fixture()
def wired(monkeypatch):
    queue = _FakeQueue()
    monkeypatch.setattr(host_episode, "request_attestation", queue.request_attestation)
    monkeypatch.setattr(host_episode, "request_host_verification", queue.request_host_verification)
    monkeypatch.setattr(host_episode, "load_run_identity", lambda: dict(RUN))
    return queue


def test_observe_action_receipts_need_no_nonce_or_epoch(wired):
    link = host_episode.HostOracleLink(RUN)
    receipt = link.observe(6)  # live shape had t=3.108 and 4 keys only
    assert set(receipt.keys()) == {"action_seq", "observation",
                                   "oracle_execution", "run_id"}
    action = link.execute({"skill": "grasp", "params": {}}, 7)
    assert action["action_status"]["state"] == "done"
    # foreign run / wrong seq must still fail closed
    bad = _observe_receipt("b" * 32, 6, 0.2)
    with pytest.raises(host_episode.HostLinkError):
        host_episode.assert_runtime_binding(bad, run_id=RUN_ID, seq=6, expected_kind="observe")


def test_v2_client_binds_root_selected_trial_in_all_receipt_types(wired, monkeypatch):
    run = {**RUN, "experiment_id": "M1-SIM-002", "pid": 123, "trial": TRIAL}
    assert host_episode.validate_run_identity(run) == run
    original = wired.request_attestation

    def dispatch(command, *, run_id, action_seq, timeout_s=30):
        nonce, receipt = original(command, run_id=run_id, action_seq=action_seq,
                                  timeout_s=timeout_s)
        return nonce, {**receipt, "trial": TRIAL,
                       **({"experiment_id": "M1-SIM-002"}
                          if command["skill"].startswith("verify_") else {})}

    monkeypatch.setattr(host_episode, "request_attestation", dispatch)
    link = host_episode.HostOracleLink(run)
    assert link.observe(0)["trial"] == TRIAL
    assert link.execute({"skill": "grasp", "params": {}}, 1)["trial"] == TRIAL
    assert link.verify("grasp", 1)["status"] == "VERIFIED_BY_ORACLE"
    assert wired.verify_kwargs[-1]["expected_trial"] == TRIAL
    bad = {**_observe_receipt(RUN_ID, 0, 0.2), "trial": {**TRIAL, "arm": "B1"}}
    with pytest.raises(host_episode.HostLinkError, match="trial binding mismatch"):
        host_episode.assert_runtime_binding(bad, run_id=RUN_ID, seq=0,
                                            expected_kind="observe", expected_trial=TRIAL)


def test_v2_client_rejects_missing_or_changed_seed():
    base = {**RUN, "experiment_id": "M1-SIM-002", "pid": 123}
    with pytest.raises(host_episode.HostLinkError, match="trial"):
        host_episode.validate_run_identity(base)
    with pytest.raises(host_episode.HostLinkError, match="trial"):
        host_episode.validate_run_identity({**base, "trial": {**TRIAL, "seed": 8}})
    with pytest.raises(host_episode.HostLinkError):
        host_episode.assert_runtime_binding(_observe_receipt(RUN_ID, 9, 0.2), run_id=RUN_ID, seq=6, expected_kind="observe")


def test_deepseek_run_identity_requires_trial_and_preserves_glm_history():
    run = {**RUN, "experiment_id": "M1-SIM-003", "pid": 123, "trial": TRIAL}
    assert host_episode.validate_run_identity(run)["experiment_id"] == "M1-SIM-003"
    with pytest.raises(host_episode.HostLinkError, match="trial"):
        host_episode.validate_run_identity({**run, "trial": {**TRIAL, "seed": 8}})
    assert host_episode.validate_run_identity(
        {**run, "experiment_id": "M1-SIM-002"})["experiment_id"] == "M1-SIM-002"


def test_fresh_precheck_uses_init_baseline_not_t_zero(wired):
    link = host_episode.HostOracleLink(RUN)
    ok = host_episode.fresh_precheck(link)  # t=0.2 == deterministic init baseline
    assert ok["action_seq"] == 0
    queue = _FakeQueue(obs_t=3.108)  # measured live stale value
    monkey_link = host_episode.HostOracleLink(RUN)
    monkey_link.observe = lambda seq: queue.request_attestation(
        {"skill": "observe"}, run_id=RUN_ID, action_seq=seq)[1]
    with pytest.raises(host_episode.HostStaleSceneError):
        host_episode.fresh_precheck(monkey_link)


def test_verify_claim_uses_real_api_shape(wired):
    link = host_episode.HostOracleLink(RUN)
    claim = link.verify("grasp", 4)
    call = wired.verify_kwargs[-1]
    signed = call["receipt"]
    assert call["expected_nonce"] == signed["nonce"]  # nonce from request, not receipt
    assert call["expected_claim_kind"] == "grasp"
    assert call["expected_experiment_id"] == "M1-SIM-001"
    assert call["expected_epoch"] == RUN["scene_epoch"]
    assert signed["claim_kind"] == "grasp"
    assert claim["signed_receipt"] == signed
    assert claim["status"] == "VERIFIED_BY_ORACLE"


def test_full_episode_place_host_verified_no_client_physics(wired):
    cube = [0.18, 0.0, 0.02]
    script = [
        json.dumps({"skill": "move_to", "params": {"x": cube[0], "y": cube[1],
                                                   "z": cube[2] + 0.07}, "intent_key": "k1"}),
        json.dumps({"skill": "move_to", "params": {"x": cube[0], "y": cube[1],
                                                   "z": cube[2] + 0.01}, "intent_key": "k2"}),
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k3"}),
        json.dumps({"skill": "move_to", "params": {"x": 0.0, "y": 0.18,
                                                   "z": cube[2] + 0.15}, "intent_key": "k4"}),
        json.dumps({"skill": "release", "params": {}, "intent_key": "k5"}),
    ]
    result = host_episode.run_host_episode(ScriptedStubProvider(script), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "place_host_verified"
    assert result["host_claims"]["place"]["status"] == "VERIFIED_BY_ORACLE"
    assert result["host_claims"]["grasp"]["status"] == "VERIFIED_BY_ORACLE"
    assert wired.events == ["move_to", "move_to", "grasp", "move_to",
                            "verify_grasp", "release", "verify_place"]
    # One initial observe, one per model decision, plus post-lift and
    # post-release observations. No client physics or hidden settle loops.
    assert wired.obs_calls == 8
    assert [c["skill"] for c in wired.commands] == [
        "move_to", "move_to", "grasp", "move_to", "release"]
    assert result["stop_receipts"] == {}


def test_stop_is_client_only_never_host_confirmed(wired):
    result = host_episode.run_host_episode(ScriptedStubProvider(
        [json.dumps({"skill": "stop", "params": {"reason": "hold"}, "intent_key": "kS"})]),
        host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "stop_requested_client_only"
    assert result["stop_receipts"]["state"] == "stop_requested_client_only"
    assert "confirmed" not in json.dumps(result["stop_receipts"])
    assert wired.commands == []  # no stop command ever sent to the daemon


def test_projection_keeps_pre_grasp_drops_privileged():
    obs = _obs(3.108)
    obs["weld_active"] = True
    obs["contact_pairs"] = [["cube_geom", "fingertip_left", -0.001]]
    obs["verdict"] = "success"
    obs["snapshot_hash"] = "f" * 64
    proj = host_episode.project_public_obs(obs)
    assert "pre_grasp_point" in proj
    for forbidden in ("weld_active", "contact_pairs", "verdict", "snapshot_hash"):
        assert forbidden not in proj


def test_main_hold_and_fresh_branches(wired, tmp_path, monkeypatch, capsys):
    missing = tmp_path / "missing_run.json"
    monkeypatch.setattr(host_episode, "RUN_INFO", missing)
    monkeypatch.setattr(
        host_episode, "load_run_identity",
        lambda: (_ for _ in ()).throw(FileNotFoundError("Host identity missing")),
    )
    assert host_episode.main([]) == 1  # no Host identity => HOLD
    assert "HOLD" in capsys.readouterr().out
    monkeypatch.setattr(host_episode, "load_run_identity", lambda: dict(RUN))
    assert host_episode.main(["--check-fresh-only"]) == 0  # fresh gate passes
    assert "FRESH" in capsys.readouterr().out
    # Never rely on ambient provider keys: force a constructor failure so
    # this unit test cannot make paid calls or mutate real episode evidence.
    fake_mod = types.ModuleType("m1_gate_c_episode")

    class NoProvider:
        def __init__(self):
            raise RuntimeError("provider deliberately disabled in unit test")

    setattr(fake_mod, "GLMHttpProvider", NoProvider)  # noqa: B010
    monkeypatch.setitem(sys.modules, "m1_gate_c_episode", fake_mod)
    evidence = tmp_path / "must_not_be_written.json"
    monkeypatch.setattr(host_episode, "EPISODE_EVIDENCE_PATH", evidence)
    rc = host_episode.main([])
    out = capsys.readouterr().out
    assert rc == 2 and "HOLD" in out and "provider unavailable" in out
    assert not evidence.exists()


def test_paired_cost_hold_never_dispatches_a_tool_or_retries_provider(wired):
    class BlockedProvider:
        model_used = "glm/glm-5.3-flash"

        def decide(self, _state):
            raise PairedCostHold("TOTAL_USD_STOP_THRESHOLD")

    result = host_episode.run_host_episode(
        BlockedProvider(), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "cost_guard_hold"
    assert result["provider_attempts"] == 0
    assert result["tool_actions"] == 0
    assert result["trace"][-1] == {"event": "COST_GUARD_HOLD",
                                   "code": "TOTAL_USD_STOP_THRESHOLD"}
    assert wired.commands == []


def test_paired_main_blocks_before_provider_without_root_grant(
        wired, monkeypatch, capsys):
    run = {**RUN, "experiment_id": "M1-SIM-003", "pid": 123,
           "trial": {"phase": "paired", "arm": "B2", "trial_index": 0,
                     "seed": 20261117}}
    monkeypatch.setattr(host_episode, "load_run_identity", lambda: run)
    monkeypatch.setattr(host_episode, "fresh_precheck",
                        lambda _link: _observe_receipt(RUN_ID, 0, 0.2))
    monkeypatch.setattr(host_episode.subprocess, "check_output",
                        lambda *_a, **_k: "a" * 40)
    monkeypatch.setattr(host_episode.subprocess, "run",
                        lambda *_a, **_k: types.SimpleNamespace(returncode=0))

    def missing(_cls, _repo, *, candidate_sha, run):
        raise FileNotFoundError("root grant not installed")

    monkeypatch.setattr(host_episode.PairedCostGate, "load", classmethod(missing))
    fake_mod = types.ModuleType("m1_gate_c_episode")
    constructed = []

    class ForbiddenProvider:
        def __init__(self, **_kwargs):
            constructed.append(True)
            raise AssertionError("provider must not initialize")

    setattr(fake_mod, "GLMHttpProvider", ForbiddenProvider)  # noqa: B010
    monkeypatch.setitem(sys.modules, "m1_gate_c_episode", fake_mod)
    assert host_episode.main([]) == 2
    assert "PAIRED_BATCH_GRANT_OR_LEDGER_MISSING" in capsys.readouterr().out
    assert constructed == []
    assert wired.commands == []


def test_main_wires_real_provider_bounded_evidence_no_secrets(
        wired, tmp_path, monkeypatch, capsys):
    fake_mod = types.ModuleType("m1_gate_c_episode")

    class FakeProvider:
        model_used = "glm/glm-5.3-flash"
        calls = [{"latency_ms": 100.0, "status": 200, "finish_reason": "stop",
                  "api_key_used": "sk-secret-should-not-appear"}]

        def __init__(self):
            self._script = [
                json.dumps({"skill": "move_to", "params": {"x": 0.18, "y": 0.0,
                                                           "z": 0.09}, "intent_key": "k1"}),
                json.dumps({"skill": "move_to", "params": {"x": 0.18, "y": 0.0,
                                                           "z": 0.03}, "intent_key": "k2"}),
                json.dumps({"skill": "grasp", "params": {}, "intent_key": "k3"}),
                json.dumps({"skill": "move_to", "params": {"x": 0.0, "y": 0.18,
                                                           "z": 0.17}, "intent_key": "k4"}),
                json.dumps({"skill": "release", "params": {}, "intent_key": "k5"}),
            ]

        def decide(self, state_text):
            return self._script.pop(0)

    setattr(fake_mod, "GLMHttpProvider", FakeProvider)  # noqa: B010
    monkeypatch.setitem(__import__("sys").modules, "m1_gate_c_episode", fake_mod)
    evidence_path = tmp_path / "episode_host_linked_latest.json"
    monkeypatch.setattr(host_episode, "EPISODE_EVIDENCE_PATH", evidence_path)
    rc = host_episode.main([])
    out = capsys.readouterr().out
    assert rc == 0 and "PLACE_HOST_VERIFIED" in out
    assert "sk-secret" not in out  # provider secrets never logged
    data = json.loads(evidence_path.read_text())
    assert data["terminated_by"] == "place_host_verified"
    assert data["model_used"] == "glm/glm-5.3-flash"



def test_claim_kind_and_epoch_bound_to_host_run(wired):
    link = host_episode.HostOracleLink(RUN)
    original = wired.request_attestation

    def wrong_claim(command, *, run_id, action_seq, timeout_s=30):
        nonce, receipt = original(command, run_id=run_id, action_seq=action_seq,
                                  timeout_s=timeout_s)
        if command["skill"] == "verify_grasp":
            receipt["claim_kind"] = "place"
        return nonce, receipt

    host_episode.request_attestation = wrong_claim
    try:
        with pytest.raises(host_episode.HostLinkError, match="binding mismatch"):
            link.verify("grasp", 4)
    finally:
        host_episode.request_attestation = original
    assert wired.verify_kwargs == []  # no verifier request on mismatched claim


def test_host_verifier_denial_never_promotes(wired):
    wired.verify_status = VerificationStatus.FAILED_CLAIM
    with pytest.raises(host_episode.HostLinkError, match="rejected"):
        host_episode.HostOracleLink(RUN).verify("place", 5)


def test_model_status_projection_hides_privileged_contact_truth():
    private = {"state": "done", "action_id": "act-000003",
               "grasp_mechanism": "contact_confirmed_weld",
               "weld_active": True, "contact_pairs": [["a", "b"]]}
    public = host_episode.project_public_status(private)
    assert public == {"state": "done", "action_id": "act-000003"}
    assert "weld" not in json.dumps(public)


def test_grasp_close_alone_does_not_claim_oracle_success(wired):
    script = [
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"}),
        json.dumps({"skill": "stop", "params": {"reason": "pause"}, "intent_key": "k2"}),
    ]
    result = host_episode.run_host_episode(
        ScriptedStubProvider(script), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "stop_requested_client_only"
    assert result["host_claims"] == {}
    assert "verify_grasp" not in wired.events


def test_release_without_independent_lift_proof_is_blocked(wired):
    script = [
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"}),
        json.dumps({"skill": "release", "params": {}, "intent_key": "k2"}),
    ]
    result = host_episode.run_host_episode(
        ScriptedStubProvider(script), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "client_guard_release_blocked"
    assert result["tool_actions"] == 1
    assert "release" not in wired.events
    assert "verify_grasp" not in wired.events
    assert any(t["event"] == "release_blocked_unverified_grasp"
               for t in result["trace"])


def _fail_first_grasp(wired, monkeypatch):
    """Mechanism-only fault injection at the public action receipt boundary."""
    original = wired.request_attestation
    failed = False

    def dispatch(command, *, run_id, action_seq, timeout_s=30):
        nonlocal failed
        if command["skill"] == "grasp" and not failed:
            failed = True
            wired.events.append("grasp_failed")
            wired.commands.append(command)
            receipt = _action_receipt(run_id, action_seq, "failed")
            receipt["action_status"]["reason"] = "no fingertip-cube contact"
            return "c" * 32, receipt
        return original(command, run_id=run_id, action_seq=action_seq,
                        timeout_s=timeout_s)

    monkeypatch.setattr(host_episode, "request_attestation", dispatch)


def test_failed_grasp_can_release_for_recovery_but_never_claim_place(wired, monkeypatch):
    _fail_first_grasp(wired, monkeypatch)
    script = [
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"}),
        json.dumps({"skill": "release", "params": {}, "intent_key": "k2"}),
        json.dumps({"skill": "stop", "params": {"reason": "hold"}, "intent_key": "k3"}),
    ]
    result = host_episode.run_host_episode(
        ScriptedStubProvider(script), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "stop_requested_client_only"
    assert result["tool_actions"] == 2
    assert result["host_claims"] == {}
    assert wired.events == ["grasp_failed", "release"]
    assert any(t["event"] == "grasp_failed" for t in result["trace"])
    assert any(t["event"] == "recovery_release" for t in result["trace"])


def test_b2_recovers_failed_grasp_without_extra_provider_decision(wired, monkeypatch):
    _fail_first_grasp(wired, monkeypatch)
    script = [
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"}),
        json.dumps({"skill": "stop", "params": {"reason": "hold"}, "intent_key": "k2"}),
    ]
    result = host_episode.run_host_episode(
        ScriptedStubProvider(script), host_episode.HostOracleLink(RUN),
        auto_recover_failed_grasp=True)
    assert result["terminated_by"] == "stop_requested_client_only"
    assert result["provider_attempts"] == 2
    assert result["tool_actions"] == 2  # recovery release counts against 8
    assert result["host_claims"] == {}
    assert wired.events == ["grasp_failed", "release"]
    assert any(t["event"] == "managed_grasp_recovery_release"
               for t in result["trace"])


def test_b2_never_exceeds_frozen_action_budget_for_recovery(wired, monkeypatch):
    _fail_first_grasp(wired, monkeypatch)
    provider = ScriptedStubProvider([
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"})])
    result = host_episode.run_host_episode(
        provider, host_episode.HostOracleLink(RUN),
        budget={**host_episode.BUDGET, "max_tool_actions": 1},
        auto_recover_failed_grasp=True)
    assert result["terminated_by"] == "tool_action_budget_exhausted"
    assert result["tool_actions"] == 1
    assert wired.events == ["grasp_failed"]
    assert result["host_claims"] == {}


def test_b2_failed_reset_is_fail_closed_not_place(wired, monkeypatch):
    _fail_first_grasp(wired, monkeypatch)
    original = host_episode.request_attestation

    def failed_reset(command, *, run_id, action_seq, timeout_s=30):
        if command["skill"] == "release":
            wired.events.append("release_failed")
            return "c" * 32, _action_receipt(run_id, action_seq, "failed")
        return original(command, run_id=run_id, action_seq=action_seq,
                        timeout_s=timeout_s)

    monkeypatch.setattr(host_episode, "request_attestation", failed_reset)
    provider = ScriptedStubProvider([
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"})])
    result = host_episode.run_host_episode(
        provider, host_episode.HostOracleLink(RUN),
        auto_recover_failed_grasp=True)
    assert result["terminated_by"] == "managed_recovery_failed"
    assert result["tool_actions"] == 2
    assert result["host_claims"] == {}
    assert wired.events == ["grasp_failed", "release_failed"]


def test_non_lifting_move_does_not_prematurely_verify(wired):
    script = [
        json.dumps({"skill": "grasp", "params": {}, "intent_key": "k1"}),
        json.dumps({"skill": "move_to", "params": {"x": 0.18, "y": 0.0,
                                                   "z": 0.035}, "intent_key": "k2"}),
        json.dumps({"skill": "stop", "params": {"reason": "pause"}, "intent_key": "k3"}),
    ]
    result = host_episode.run_host_episode(
        ScriptedStubProvider(script), host_episode.HostOracleLink(RUN))
    assert result["terminated_by"] == "stop_requested_client_only"
    assert result["host_claims"] == {}
    assert "verify_grasp" not in wired.events


def test_missing_scene_epoch_and_pid_fail_closed_before_host_calls():
    for field in ("scene_epoch", "pid"):
        identity = {**RUN, "pid": 1234}
        identity.pop(field)
        with pytest.raises(host_episode.HostLinkError, match="invalid Host"):
            host_episode.validate_run_identity(identity)
    for bad_epoch in (None, 0, True, "1"):
        with pytest.raises(host_episode.HostLinkError, match="scene_epoch"):
            host_episode.validate_run_identity({**RUN, "pid": 1234,
                                                "scene_epoch": bad_epoch})


def test_malformed_parser_result_records_invalid_without_action(wired, monkeypatch):
    monkeypatch.setattr(host_episode, "parse_decision", lambda _raw: {"skill": "grasp"})
    provider = ScriptedStubProvider(["ignored"], model_used="stub/parser-malformed")
    result = host_episode.run_host_episode(provider, host_episode.HostOracleLink(RUN),
                                          budget={"max_provider_attempts": 1,
                                                  "max_tool_actions": 8,
                                                  "deadline_s": 180.0,
                                                  "learning": "off"})
    assert result["terminated_by"] == "provider_attempt_budget_exhausted"
    assert result["provider_attempts"] == 1
    assert result["tool_actions"] == 0
    assert result["trace"][0]["event"] == "decision_invalid"
    assert wired.commands == []
