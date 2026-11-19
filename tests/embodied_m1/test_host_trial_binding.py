"""M1-SIM-002 trial metadata: frozen paired seeds, fail-closed bindings."""

from __future__ import annotations

import pytest

from llm_loop.embodied_sim.trial import (
    DEEPSEEK_EXPERIMENT_ID,
    EXPERIMENT_ID,
    validate_host_config,
    validate_trial,
)


def test_trial_smoke_and_paired_seeds_are_fixed():
    assert EXPERIMENT_ID == "M1-SIM-002"
    assert validate_trial({"phase": "smoke", "arm": "B1", "trial_index": 7,
                           "seed": 7})["seed"] == 7
    assert validate_trial({"phase": "paired", "arm": "B2", "trial_index": 0,
                           "seed": 20261117})["seed"] == 20261117
    assert validate_trial({"phase": "paired", "arm": "B1", "trial_index": 29,
                           "seed": 20261146})["seed"] == 20261146


def test_new_deepseek_experiment_keeps_original_host_protocol_and_frozen_seeds():
    assert EXPERIMENT_ID == "M1-SIM-002"
    assert DEEPSEEK_EXPERIMENT_ID == "M1-SIM-003"
    trial = {"phase": "paired", "arm": "B2", "trial_index": 29, "seed": 20261146}
    for experiment_id in (EXPERIMENT_ID, DEEPSEEK_EXPERIMENT_ID):
        config = {"schema": "lfl.m1-oracle-host-trial/v1",
                  "experiment_id": experiment_id, "trial": trial}
        assert validate_host_config(config) == trial
    with pytest.raises(ValueError, match="identity"):
        validate_host_config({**config, "experiment_id": "M1-SIM-004"})


@pytest.mark.parametrize("bad", [
    {"phase": "paired", "arm": "B1", "trial_index": 0, "seed": 7},
    {"phase": "paired", "arm": "B1", "trial_index": 30, "seed": 20261147},
    {"phase": "smoke", "arm": "B1", "trial_index": 10, "seed": 10},
    {"phase": "smoke", "arm": "B1", "trial_index": 7, "seed": 8},
    {"phase": "paired", "arm": "B3", "trial_index": 0, "seed": 20261117},
    {"phase": "paired", "arm": "B1", "trial_index": True, "seed": 20261117},
    {"phase": "paired", "arm": "B1", "trial_index": 0, "seed": 20261117,
     "untrusted": "extra"},
    {"phase": "paired", "arm": "B1", "trial_index": 0},
])
def test_invalid_trial_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_trial(bad)
