"""Calibration guardrails: safety hard gate, determinism, evidence immutability.

These tests pin the BASELINE_FAIL facts (current geometry touches cube with
wrist_rod) until a QA-approved scene/trajectory fix lands under a new
calibration_version. They are NOT a licence to relax any tolerance.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / "experiments" / "embodied" / "m1" / "calibration"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "m1_calibrate", ROOT / "scripts" / "embodied" / "m1_calibrate.py")
assert _spec is not None and _spec.loader is not None
m1_calibrate = importlib.util.module_from_spec(_spec)
sys.modules["m1_calibrate"] = m1_calibrate
_spec.loader.exec_module(m1_calibrate)

run_calibrated_episode = m1_calibrate.run_calibrated_episode
run_determinism_check = m1_calibrate.run_determinism_check
run_negative_checks = m1_calibrate.run_negative_checks


def test_safety_gate_hard_fails_on_unexpected_contacts():
    """wrist_rod-cube contact is a hard verdict gate: seed 7 currently trips it."""
    m = run_calibrated_episode(7)
    assert m["no_unexpected_contacts"] is False
    assert m["passed"] is False
    assert "cube_geom/wrist_rod" in m["unexpected_contacts_by_stage"].get("approach_down", {})
    fc = m["first_unexpected_contact_geometry"]
    assert fc is not None and fc["pair"] == ["wrist_rod", "cube_geom"]
    # disclosed penetration depth is sub-millimetre scuffing, not deep push-through
    assert -0.002 < fc["penetration_m"] <= 0.0


def test_negative_checks_fail_closed():
    neg = run_negative_checks()
    assert neg["grasp_empty"]["rejected"] is True
    assert neg["place_off_target"]["fake_success_rejected"] is True


def test_determinism_same_seed_identical_trajectory():
    det = run_determinism_check(3)
    assert det["deterministic"] is True


@pytest.mark.parametrize("name", ["M1-baseline-v1-initial-fail.json",
                                  "M1-baseline-v1.1-pre-safety-gate.json",
                                  "M1-baseline-v1.3-fail-rod-rear.json",
                                  "M1-baseline-v1.4.json"])
def test_evidence_versions_immutable(name):
    path = CAL / name
    assert path.exists(), "historical evidence must not be deleted"
    sidecar = CAL / (name + ".sha256")
    recorded = sidecar.read_text().strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert recorded == actual


def test_v12_hard_gate_present_in_evidence():
    data = json.loads((CAL / "M1-baseline-v1.2.json").read_text())
    assert data["verdict"] == "BASELINE_FAIL"
    assert all("no_unexpected_contacts" in s for s in data["seed_results"])


def test_v13_v14_failures_preserved():
    """v1.3 (rod-rear) and v1.4 (lateral rods) failures must stay on record."""
    v13 = json.loads((CAL / "M1-baseline-v1.3-fail-rod-rear.json").read_text())
    assert v13["verdict"] == "BASELINE_FAIL"
    v14 = json.loads((CAL / "M1-baseline-v1.4.json").read_text())
    assert v14["verdict"] == "BASELINE_FAIL"
    assert all(f["stage"] == "grasp" for f in v14["failures"])
