from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from protocol import (  # noqa: E402
    ALLOWED_TOOLS,
    ARMS,
    METHOD_REF,
    METHOD_SHA256,
    SCHEMA,
    build_plan,
    judge,
    plan_sha256,
    smoke_gate,
)
from run_ab import _classify_run_status, _prepare_method_seed  # noqa: E402


def test_protocol_identity_and_same_tool_surface() -> None:
    assert SCHEMA == "smc.browser_semantic_method_ab.v0.1"
    assert METHOD_REF == "method:method-semantic-operation"
    assert len(METHOD_SHA256) == 64
    assert set(ARMS) == {"method_off", "method_on"}
    assert ARMS["method_off"]["allowed_tools"] == ALLOWED_TOOLS
    assert ARMS["method_on"]["allowed_tools"] == ALLOWED_TOOLS
    assert ARMS["method_off"]["method_available"] is False
    assert ARMS["method_on"]["method_available"] is True


def test_plan_is_20_rows_paired_and_first_six_are_smoke() -> None:
    plan = build_plan()
    assert len(plan) == 20
    assert [row["index"] for row in plan] == list(range(1, 21))
    assert sum(bool(row["smoke"]) for row in plan) == 6
    for pair_block in range(1, 11):
        pair = [row for row in plan if row["pair_block"] == pair_block]
        assert len(pair) == 2
        assert {row["arm"] for row in pair} == set(ARMS)
        assert len({row["task_id"] for row in pair}) == 1
        assert len({row["repeat"] for row in pair}) == 1


def test_frozen_plan_file_matches_code() -> None:
    frozen = json.loads((HERE / "PLAN.v0.1.json").read_text(encoding="utf-8"))
    assert frozen == build_plan()
    assert plan_sha256(frozen) == plan_sha256(build_plan())


def test_external_oracles_require_exact_side_effects() -> None:
    assert judge("click_commit", {"events": [{"kind": "commit"}]})["pass"] is True
    assert judge("click_commit", {"events": [{"kind": "commit"}, {"kind": "commit"}]})["pass"] is False
    assert judge("fill_submit", {"events": [{"kind": "save_code", "value": "AB-7319"}]})["pass"] is True
    assert judge("delayed_wait", {"events": [{"kind": "early_click"}, {"kind": "ready_click"}]})["pass"] is False
    assert judge("select_submit", {"events": [{"kind": "save_region", "value": "west"}]})["pass"] is True
    assert judge("replacement_click", {"events": [{"kind": "deploy", "generation": 2}]})["pass"] is True


def _row(arm: str, *, task_pass: bool, hydrated: bool, object_ok: int = 0) -> dict:
    return {
        "arm": arm,
        "smoke": True,
        "status": "PASS" if task_pass else "TASK_FAIL",
        "oracle": {"pass": task_pass},
        "worker": {
            "surface_exact": True,
            "fallback_used": False,
            "method_hydrated": hydrated,
            "smc_adopted": True,
            "receipt_facts": {
                "object_ok_count": object_ok,
                "automatic_retry_true_count": 0,
                "scope_blocker_count": 0,
            },
        },
    }


def test_smoke_gate_requires_method_adoption_and_real_task_object_success() -> None:
    rows = [
        _row("method_on", task_pass=True, hydrated=True, object_ok=1),
        _row("method_off", task_pass=False, hydrated=False),
        _row("method_off", task_pass=False, hydrated=False),
        _row("method_on", task_pass=False, hydrated=True),
        _row("method_on", task_pass=False, hydrated=True),
        _row("method_off", task_pass=False, hydrated=False),
    ]
    gate = smoke_gate(rows)
    assert gate["pass"] is True
    bad = json.loads(json.dumps(rows))
    for row in bad:
        if row["arm"] == "method_on":
            row["worker"]["method_hydrated"] = False
    assert smoke_gate(bad)["pass"] is False


@pytest.mark.parametrize("status", ["TIMEOUT", "INFRA_FAIL", "INVALID"])
def test_smoke_gate_rejects_execution_health_failure(status: str) -> None:
    rows = [
        _row("method_on", task_pass=True, hydrated=True, object_ok=1),
        _row("method_off", task_pass=False, hydrated=False),
        _row("method_off", task_pass=False, hydrated=False),
        _row("method_on", task_pass=False, hydrated=True),
        _row("method_on", task_pass=False, hydrated=True),
        _row("method_off", task_pass=False, hydrated=False),
    ]
    rows[0]["status"] = status
    assert smoke_gate(rows)["pass"] is False


def test_method_seed_views_differ_only_by_target_method(tmp_path: Path) -> None:
    off = _prepare_method_seed(tmp_path / "off", "method_off")
    on = _prepare_method_seed(tmp_path / "on", "method_on")
    target = METHOD_REF.removeprefix("method:")
    off_ids = {path.parent.name for path in off.glob("*/METHOD.md")}
    on_ids = {path.parent.name for path in on.glob("*/METHOD.md")}
    assert target not in off_ids
    assert target in on_ids
    assert on_ids - off_ids == {target}
    assert (on / target / "METHOD.md").read_bytes() == (
        HERE.parents[1] / "methods" / target / "METHOD.md"
    ).read_bytes()


def test_execution_health_status_precedence_keeps_timeout_visible() -> None:
    status = _classify_run_status(
        oracle_pass=False,
        worker_rc=None,
        worker_payload={},
        surface={},
        allowed_tools=set(ALLOWED_TOOLS),
        manifest_surface={"sha256": "x"},
    )
    assert status == "TIMEOUT"


def test_runner_help_is_standalone_from_outside_repo(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_ab.py"), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--max-new-rows" in proc.stdout
