"""C-5 契约：合规样本必须全部通过，且 round-trip 无损。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctp_contract import (
    DegradationFlag,
    Observation,
    Resolution,
    load_observation,
    parse_observation,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "valid"
VALID = sorted(FIXTURE_DIR.glob("*.json"))


def test_fixture_set_is_not_vacuous():
    assert len(VALID) >= 8, "计划要求 >=8 合法样本"


@pytest.mark.parametrize("path", VALID, ids=lambda item: item.stem)
def test_valid_fixture_parses(path: Path) -> None:
    observation = load_observation(path)
    assert isinstance(observation, Observation)
    assert isinstance(observation.resolution, Resolution)
    assert isinstance(observation.degradation_flag, DegradationFlag)


@pytest.mark.parametrize("path", VALID, ids=lambda item: item.stem)
def test_roundtrip_is_lossless(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    observation = parse_observation(raw)
    assert observation.as_dict() == raw


def test_all_c5_fields_present_in_model():
    """C-5 表的九个字段必须都能读出来（缺一即不合规）。"""
    raw = json.loads(VALID[0].read_text(encoding="utf-8"))
    payload = parse_observation(raw).as_dict()
    for field_name in (
        "target_index",
        "logical_id",
        "resolution",
        "pose",
        "uncertainty",
        "degradation_flag",
        "timestamp",
        "reader_id",
        "reader_version",
    ):
        assert field_name in payload


def test_uncertainty_carries_k_and_one_sigma():
    raw = json.loads(VALID[0].read_text(encoding="utf-8"))
    uncertainty = parse_observation(raw).uncertainty
    assert uncertainty.k > 0
    assert uncertainty.translation_1sigma_m.z > 0
    assert uncertainty.rotation_1sigma_deg.z > 0


def test_v04_covariance_units_are_m2_rad2():
    """P0-1 回归钉：协方差平移对角 = σ²(m²)，旋转对角 = radians(σ_deg)²(rad²)。"""
    import math

    raw = json.loads((FIXTURE_DIR / "v04_covariance.json").read_text(encoding="utf-8"))
    uncertainty = raw["uncertainty"]
    cov = uncertainty["covariance_6x6"]
    for axis, index in (("x", 0), ("y", 1), ("z", 2)):
        sigma_m = uncertainty["translation_1sigma_m"][axis]
        assert math.isclose(cov[index][index], sigma_m**2, rel_tol=1e-9)
    for axis, index in (("x", 3), ("y", 4), ("z", 5)):
        sigma_deg = uncertainty["rotation_1sigma_deg"][axis]
        assert math.isclose(cov[index][index], math.radians(sigma_deg) ** 2, rel_tol=1e-9)
