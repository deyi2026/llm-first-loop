"""Frozen M1 Host trial identities, never selected by the model/client.

An isolated Host process reads this identity from a root-owned configuration.
No dynamic skill, seed override, or arbitrary action is exposed over IPC.
M1-SIM-001 remains a separate, immutable legacy experiment.
"""

from __future__ import annotations

from typing import Any

EXPERIMENT_ID = "M1-SIM-002"
DEEPSEEK_EXPERIMENT_ID = "M1-SIM-003"
TRIAL_EXPERIMENT_IDS = frozenset({EXPERIMENT_ID, DEEPSEEK_EXPERIMENT_ID})
CONFIG_SCHEMA = "lfl.m1-oracle-host-trial/v1"
PAIRED_SEED_START = 20261117
PAIRED_TRIALS = 30
ENGINEERING_TRIALS = 10
TRIAL_FIELDS = frozenset({"phase", "arm", "trial_index", "seed"})


def validate_trial(trial: Any) -> dict[str, Any]:
    """Fail closed on changed frozen seeds, arms, budgets or extra fields."""
    if not isinstance(trial, dict) or set(trial) != TRIAL_FIELDS:
        raise ValueError("trial must contain exactly phase/arm/trial_index/seed")
    phase, arm = trial["phase"], trial["arm"]
    index, seed = trial["trial_index"], trial["seed"]
    if phase not in ("smoke", "paired") or arm not in ("B1", "B2"):
        raise ValueError("unknown trial phase or comparison arm")
    if type(index) is not int or type(seed) is not int:
        raise ValueError("trial index and seed must be integers, not booleans")
    count = ENGINEERING_TRIALS if phase == "smoke" else PAIRED_TRIALS
    start = 0 if phase == "smoke" else PAIRED_SEED_START
    if not 0 <= index < count or seed != start + index:
        raise ValueError("trial index or seed differs from frozen preregistration")
    return dict(trial)


def validate_host_config(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {"schema", "experiment_id", "trial"}:
        raise ValueError("Host trial configuration has unknown/missing fields")
    if (data["schema"] != CONFIG_SCHEMA
            or data["experiment_id"] not in TRIAL_EXPERIMENT_IDS):
        raise ValueError("Host trial schema or experiment identity mismatch")
    return validate_trial(data["trial"])
