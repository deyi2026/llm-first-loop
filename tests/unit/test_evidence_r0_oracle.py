from __future__ import annotations

import json
from pathlib import Path

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "evidence_recoverability_r0.json"


def test_r0_oracle_is_complete_and_frozen_to_v11_contract():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert data["version"] == "R0-v1.1"
    assert data["provider_calls_allowed"] is False
    assert data["contract_sha256"] == {
        "spec": "97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771",
        "design": "95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b",
    }
    ids = [case["id"] for case in data["cases"]]
    assert ids == [f"R0-{i}" for i in range(1, 13)]
    assert all(case["oracle"] for case in data["cases"])


def test_r0_phase_assignment_prevents_early_scope_creep():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    phases = {case["id"]: case["phase"] for case in data["cases"]}
    assert phases["R0-2"] == 1
    assert phases["R0-3"] == 1
    assert phases["R0-5"] == 1
    assert phases["R0-7"] == 3
    assert phases["R0-8"] == 4
    assert phases["R0-9"] == 5
    assert phases["R0-10"] == 6
    assert phases["R0-12"] == 0
