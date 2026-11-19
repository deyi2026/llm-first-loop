"""L3 probe is an explicitly disclosed smoke-only Host action, not paired data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts/embodied")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from m1_gate_c_host_episode import HostLinkError  # noqa: E402
from m1_l3_host_probe import (  # noqa: E402
    OneScriptedFaultThenLiveModel,
    assess_probe,
    validate_probe_trial,
)


def _run(arm="B2", phase="smoke", index=9, seed=9):
    return {"run_id": "a" * 32, "pid": 463, "scene_epoch": 1,
            "experiment_id": "M1-SIM-002",
            "trial": {"phase": phase, "arm": arm,
                      "trial_index": index, "seed": seed}}


@pytest.mark.parametrize("arm", ["B1", "B2"])
def test_l3_probe_accepts_only_root_selected_smoke_seed_nine(arm):
    assert validate_probe_trial(_run(arm)) == arm


@pytest.mark.parametrize("run", [
    _run(phase="paired", index=0, seed=20261117),
    _run(index=8, seed=8),
    _run(index=9, seed=8),
    _run(arm="B3"),
    {"run_id": "a" * 32, "pid": 463, "scene_epoch": 1,
     "experiment_id": "M1-SIM-001"},
])
def test_l3_probe_rejects_formal_or_wrong_identity(run):
    with pytest.raises(HostLinkError):
        validate_probe_trial(run)


def test_l3_probe_discloses_scripted_fault_and_uses_real_provider_afterward():
    class Live:
        model_used = "glm/glm-5.3-flash"

        def __init__(self):
            self.states = []

        def decide(self, state):
            self.states.append(state)
            return '{"skill":"move_to","params":{"x":0,"y":0,"z":0.1},"intent_key":"k1"}'

    live = Live()
    probe = OneScriptedFaultThenLiveModel(live)
    first = json.loads(probe.decide("first"))
    assert first == {"skill": "grasp", "params": {},
                     "intent_key": "l3-diagnostic-fault"}
    assert live.states == []
    assert json.loads(probe.decide("second"))["skill"] == "move_to"
    assert live.states == ["second"]
    assert probe.scripted_decisions == 1


def test_l3_b2_requires_actual_host_failure_reset_and_signed_success():
    base = {"terminated_by": "place_host_verified", "managed_recoveries": 1,
            "provider_attempts": 6, "tool_actions": 7, "elapsed_s": 120,
            "host_claims": {"grasp": {"status": "VERIFIED_BY_ORACLE"},
                            "place": {"status": "VERIFIED_BY_ORACLE"}},
            "trace": [
                {"event": "tool_action", "seq": 1,
                 "decision": {"skill": "grasp"}, "status": {"state": "failed"}},
                {"event": "grasp_failed", "seq": 1},
                {"event": "managed_grasp_recovery_release", "seq": 2,
                 "status": {"state": "done"}},
            ]}
    assert assess_probe(base, arm="B2") == ("L3_B2_HOST_RECOVERY_VERIFIED", True)
    assert assess_probe(base, arm="B1") == ("L3_B1_CONTROL_RECORDED", True)
    assert assess_probe({**base, "managed_recoveries": 0}, arm="B2")[1] is False
    assert assess_probe({**base, "host_claims": {}}, arm="B2")[1] is False
    assert assess_probe({**base, "tool_actions": 9}, arm="B2")[1] is False
    assert assess_probe({**base, "trace": base["trace"][1:]}, arm="B2")[1] is False
    assert assess_probe({**base, "terminated_by": "host_fail_closed"}, arm="B1")[1] is False
