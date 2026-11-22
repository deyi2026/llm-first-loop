"""Calibration guardrails: full-trajectory safety, determinism, and immutable evidence.

The local physics candidate does not replace independent Oracle acceptance.
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
FROZEN_RECEIPT_SHA256 = {
    'M1-baseline-v1-initial-fail.json': 'f0ff6c636f8fbc188af95def72695e9b903c98fb4eb9abab6eb6ffb692919dcf',
    'M1-baseline-v1.1-pre-safety-gate.json': 'b6a501602817e2782b5acf24c442dd473059cd5f3a19001f746958b2a233125c',
    'M1-baseline-v1.1.json': 'b6a501602817e2782b5acf24c442dd473059cd5f3a19001f746958b2a233125c',
    'M1-baseline-v1.2.json': 'd8b27eb5637899d2b3978981bb24d2b243dc900451708af01524d34630af6cd3',
    'M1-baseline-v1.3-fail-rod-rear.json': 'b5b0f4f2e1f31f2a761638bdccc80037f2b525c2fc32309c45c1879af9ade76a',
    'M1-baseline-v1.3.json': 'b5b0f4f2e1f31f2a761638bdccc80037f2b525c2fc32309c45c1879af9ade76a',
    'M1-baseline-v1.4.json': 'b7fe3972eb2a8219d77cd8cb0715769c3ed7363e6918cffde2ac668dce971365',
    'M1-baseline-v1.5.json': '1db27f8a373fac7af9896b7353dfc40bb54c7d580729752953099dea99e065c1',
    'M1-baseline-v1.6-pre-metadata-fix.json': '4e0f943a69910b8c9de3ad6f3459f5128b534c793f961d4e6cf8f4dfb37e819f',
    'M1-baseline-v1.6.1.json': '167c63560d346f74067381341e20427822350f0e4dcbb814575b4667d760590d',
    'M1-baseline-v1.6.2.json': '9ae1b7eeed11cde8e6039492e7a36725051ea00671001fbf53ccaa17bede6ff2',
    'M1-baseline-v1.6.3.json': 'cdb200973197f9493d4b11a5e630f8b675fe19e89f15eb045364f2c738683e3c',
    'M1-baseline-v1.6.4.json': '820b73cf54ddb13a0f86c179950b0fca58a7ddea632cbf565153772af5846f3d',
    'M1-baseline-v1.6.5.json': '3dedf7a8efa4288ef1a1ca785d1ae0e117b1e4b0e6e4cd2177f8677e24c71967',
    'M1-baseline-v1.7.json': '7f803cc1d54dcce350d953aa71bec200bba6b3cf4214f308176fcd39326d74f9',
    'M1-baseline-v1.8.json': 'bfcb4787ee50c61ee1da924ea13bfa5033bc1326549f58ef57a4d85e35506e46',
    'M1-baseline-v1.6.json': '4e0f943a69910b8c9de3ad6f3459f5128b534c793f961d4e6cf8f4dfb37e819f',
    'M1-baseline-v1.json': 'f0ff6c636f8fbc188af95def72695e9b903c98fb4eb9abab6eb6ffb692919dcf',
}
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


def test_safety_gate_clean_on_v16_geometry():
    """On the approved v1.6 scene the full-trajectory gate must be clean."""
    m = run_calibrated_episode(7)
    assert m["no_unexpected_contacts"] is True
    assert m["passed"] is True


def test_is_unexpected_contact_hard_gate_matrix():
    """Negative contacts stay hard-gated even though v1.6 is locally clean."""
    f = m1_calibrate.is_unexpected_contact
    assert f("wrist_rod", "floor") is True
    assert f("cube_geom", "l3") is True
    assert f("wrist_rod", "cube_geom") is True
    assert f("base_geom", "l1") is False          # only structural whitelist pair
    assert f("cube_geom", "fingertip_left") is False
    assert f("cube_geom", "tray_floor") is False


def test_v18_local_baseline_pass_metadata_consistent():
    """v1.8 = M2 review-fixed episode.py over the unchanged v1.6.2 physics.

    v1.7 stays frozen for QA traceability; it is no longer the receipt that
    describes the live code, so the code-hash pin moved to v1.8.
    """
    data = json.loads((CAL / "M1-baseline-v1.8.json").read_text())
    assert data["verdict"] == "LOCAL_PHYSICS_BASELINE_PASS"
    assert data["independent_oracle"].startswith("PENDING_ORACLE")
    assert data["structural_whitelist_verification"]["adjacent_assembly_confirmed"] is True
    assert all(r["passed"] and r["no_unexpected_contacts"] for r in data["seed_results"])
    assert len(data["seed_results"]) == 10
    assert data["cold_start_contact_gate"]["all_seeds_instrumented"] is True
    assert all(r["instrumented_steps_by_stage"]["cold_start_settle"] == 100
               for r in data["seed_results"])
    from llm_loop.embodied_sim.skills import _MOVE_MAX_STEPS
    assert _MOVE_MAX_STEPS == 750  # physics-step budget, NOT a tolerance change
    # receipt must describe the CURRENT scene, not stale v1.2-era metadata
    reason = data["scene_revision_reason"]
    assert "z0.12->0.11" in reason and "z[0.14,0.18]->z[0.12,0.13]" in reason
    assert "kinematically fine" in reason
    assert "M2 (issue #79" in reason and "PHYSICS UNCHANGED" in reason
    assert "M2 review fix" in reason and "only episode.py's digest moved" in reason
    # live scene XML must hash exactly to what the receipt recorded
    import hashlib
    sys.path.insert(0, str(ROOT / "src"))
    from llm_loop.embodied_sim.scene import build_scene_xml
    live_sha = hashlib.sha256(build_scene_xml().encode()).hexdigest()
    assert data["scene_xml_sha256"] == live_sha
    assert all(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == expected
               for rel, expected in data["code_sha256"].items())
    # pre-metadata-fix snapshot stays frozen for QA traceability
    pre = json.loads((CAL / "M1-baseline-v1.6-pre-metadata-fix.json").read_text())
    assert "restored original v1.2 axial rod geometry" in pre["scene_revision_reason"]



def test_existing_receipt_cannot_be_overwritten(monkeypatch):
    """Re-running a frozen version must fail BEFORE any physics or file writes."""
    frozen = CAL / "M1-baseline-v1.6.1.json"
    before = hashlib.sha256(frozen.read_bytes()).hexdigest()
    monkeypatch.setattr(m1_calibrate, "BASELINE_VERSION", "M1-baseline-v1.6.1")
    with pytest.raises(FileExistsError, match="immutable calibration receipt exists"):
        m1_calibrate.main()
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == before


def test_sidecar_only_also_blocks_version_reuse(monkeypatch, tmp_path):
    monkeypatch.setattr(m1_calibrate, "OUT_DIR", tmp_path)
    # bind to the CURRENT version: a bump must not silently disable this guard
    (tmp_path / (m1_calibrate.BASELINE_VERSION + ".json.sha256")).write_text("partial receipt")
    with pytest.raises(FileExistsError, match="immutable calibration receipt exists"):
        m1_calibrate.main()


def test_negative_checks_fail_closed():
    neg = run_negative_checks()
    assert neg["grasp_empty"]["rejected"] is True
    assert neg["place_off_target"]["fake_success_rejected"] is True


def test_determinism_same_seed_identical_trajectory():
    det = run_determinism_check(3)
    assert det["deterministic"] is True


@pytest.mark.parametrize("name,expected_sha", sorted(FROZEN_RECEIPT_SHA256.items()))
def test_evidence_versions_immutable(name, expected_sha):
    path = CAL / name
    assert path.exists(), "historical evidence must not be deleted"
    sidecar = CAL / (name + ".sha256")
    recorded = sidecar.read_text().strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    # Sidecar alone is insufficient: both files were once accidentally rewritten.
    assert recorded == actual == expected_sha


def test_v12_hard_gate_present_in_evidence():
    data = json.loads((CAL / "M1-baseline-v1.2.json").read_text())
    assert data["verdict"] == "BASELINE_FAIL"
    assert all("no_unexpected_contacts" in s for s in data["seed_results"])


def test_wrist_rod_floor_contacts_are_hard_gated():
    """v1.5-era rod<->floor contacts stay on frozen record; the classifier must
    keep gating them even though the approved v1.6 geometry no longer produces
    them (verified positive by test_safety_gate_clean_on_v16_geometry)."""
    v15 = json.loads((CAL / "M1-baseline-v1.5.json").read_text())
    s7 = next(r for r in v15["seed_results"] if r["seed"] == 7)
    assert s7["no_unexpected_contacts"] is False
    assert any("floor/wrist_rod" in pairs
               for pairs in s7["unexpected_contacts_by_stage"].values())
    assert m1_calibrate.is_unexpected_contact("wrist_rod", "floor") is True



def test_unexpected_contact_predicate():
    from m1_calibrate import is_unexpected_contact
    assert is_unexpected_contact("wrist_rod", "floor") is True
    assert is_unexpected_contact("wrist_rod", "cube_geom") is True
    assert is_unexpected_contact("l1", "floor") is True
    assert is_unexpected_contact("floor", "cube_geom") is False
    assert is_unexpected_contact("cube_geom", "fingertip_left") is False
    assert is_unexpected_contact("cube_geom", "tray_floor") is False


def test_v13_v14_failures_preserved():
    """v1.3 (rod-rear) and v1.4 (lateral rods) failures must stay on record."""
    v13 = json.loads((CAL / "M1-baseline-v1.3-fail-rod-rear.json").read_text())
    assert v13["verdict"] == "BASELINE_FAIL"
    v14 = json.loads((CAL / "M1-baseline-v1.4.json").read_text())
    assert v14["verdict"] == "BASELINE_FAIL"
    assert all(f["stage"] == "grasp" for f in v14["failures"])
