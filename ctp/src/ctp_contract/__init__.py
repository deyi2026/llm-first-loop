"""CTP C-5 读取输出契约（SPEC-20261123-CTP-0.9.2 §5）。"""

from __future__ import annotations

from .errors import ContractError
from .model import (
    DegradationFlag,
    Observation,
    Pose,
    Quaternion,
    Resolution,
    Uncertainty,
    Vector3,
)
from .validate import collect_errors, load_observation, parse_observation

__all__ = [
    "ContractError",
    "DegradationFlag",
    "Observation",
    "Pose",
    "Quaternion",
    "Resolution",
    "Uncertainty",
    "Vector3",
    "collect_errors",
    "load_observation",
    "parse_observation",
]
