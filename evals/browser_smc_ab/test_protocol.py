from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from analyze import analyze  # noqa: E402
from fixture_server import FixtureServer  # noqa: E402
from protocol import (  # noqa: E402
    ARMS,
    SCHEMA,
    SEED,
    TASKS,
    build_plan,
    judge,
    plan_sha256,
    smoke_gate,
)
from run_ab import _pending_rows, _provider_contract  # noqa: E402


def test_plan_is_20_rows_paired_and_smoke_prefix_is_three_complete_blocks() -> None:
    assert SCHEMA == "smc.browser_real_model_ab.v0.3"
    assert SEED == 2026091303
    plan = build_plan()
    assert len(plan) == 20
    assert [row["index"] for row in plan] == list(range(1, 21))
    assert sum(bool(row["smoke"]) for row in plan) == 6
    assert build_plan(SEED) == plan
    assert len(plan_sha256(plan)) == 64
    by_pair: dict[int, list[dict]] = {}
    for row in plan:
        by_pair.setdefault(int(row["pair_block"]), []).append(row)
    assert len(by_pair) == 10
    for rows in by_pair.values():
        assert {row["arm"] for row in rows} == {"smc", "legacy"}
        assert len({(row["task_id"], row["repeat"]) for row in rows}) == 1

    frozen = json.loads((HERE / "PLAN.v0.3.json").read_text(encoding="utf-8"))
    assert frozen["seed"] == SEED
    assert frozen["plan_sha256"] == plan_sha256(plan)
    assert frozen["rows"] == plan


def test_arm_surfaces_are_exact_and_do_not_offer_cross_treatment_browser_tools() -> None:
    assert set(ARMS["smc"]["allowed_tools"]) == {"browser_perceive", "browser_action", "get_tool_schema"}
    assert set(ARMS["legacy"]["allowed_tools"]) == {"playwright_exec", "playwright_test", "get_tool_schema"}
    assert not set(ARMS["smc"]["allowed_tools"]) & {"playwright_exec", "playwright_test"}
    assert not set(ARMS["legacy"]["allowed_tools"]) & {"browser_perceive", "browser_action"}


def test_runner_is_standalone_importable_outside_repo_cwd(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_ab.py"), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--workdir" in proc.stdout
    assert "--max-new-rows" in proc.stdout


def test_pending_rows_bounds_each_controller_invocation_without_changing_plan() -> None:
    plan = build_plan()
    done = {1, 2, 3}
    pending = _pending_rows(plan[:6], done, 1)
    assert [row["index"] for row in pending] == [4]
    assert [row["index"] for row in _pending_rows(plan[:6], done, 2)] == [4, 5]
    with pytest.raises(ValueError, match="max_new_rows"):
        _pending_rows(plan[:6], done, 0)


def test_effective_cognilocal_provider_contract_is_frozen() -> None:
    assert _provider_contract() == {
        "timeout_s": 1800,
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
    }


def test_task_prompts_do_not_name_treatment_tools_or_locators() -> None:
    forbidden = ("browser_perceive", "browser_action", "playwright", "selector", "xpath", "backendNodeId")
    for task in TASKS.values():
        low = task.prompt_template.lower()
        assert all(token.lower() not in low for token in forbidden)


def test_external_oracles_are_exact() -> None:
    assert judge("click_commit", {"events": [{"kind": "commit"}]})["pass"] is True
    assert judge("click_commit", {"events": [{"kind": "commit"}, {"kind": "commit"}]})["pass"] is False
    assert judge("fill_submit", {"events": [{"kind": "save_code", "value": "AB-7319"}]})["pass"] is True
    assert judge("fill_submit", {"events": [{"kind": "save_code", "value": "wrong"}]})["pass"] is False
    assert judge("delayed_wait", {"events": [{"kind": "ready_click"}]})["pass"] is True
    assert judge("select_submit", {"events": [{"kind": "save_region", "value": "west"}]})["pass"] is True
    assert judge("replacement_click", {"events": [{"kind": "deploy", "generation": 2}]})["pass"] is True
    assert judge("replacement_click", {"events": [{"kind": "deploy", "generation": 1}, {"kind": "deploy", "generation": 2}]})["pass"] is False


def test_fixture_server_is_loopback_and_state_is_external() -> None:
    import httpx

    with FixtureServer("click_commit") as server:
        assert server.url.startswith("http://127.0.0.1:")
        assert httpx.get(server.url, trust_env=False).status_code == 200
        assert server.state.snapshot()["events"] == []
        response = httpx.post(server.url + "event", json={"kind": "commit"}, trust_env=False)
        assert response.status_code == 200
        assert judge("click_commit", server.state.snapshot())["pass"] is True


def test_smoke_gate_requires_both_arm_adoption_and_clean_mechanics() -> None:
    rows = []
    for arm in ("smc", "legacy") * 3:
        rows.append(
            {
                "smoke": True,
                "arm": arm,
                "status": "PASS",
                "worker": {
                    "smc_adopted": arm == "smc",
                    "legacy_physical_exec_count": 1 if arm == "legacy" else 0,
                    "fallback_used": False,
                    "surface_exact": True,
                    "receipt_facts": (
                        {
                            "ok_count": 1,
                            "scope_blocker_count": 0,
                        }
                        if arm == "smc"
                        else {}
                    ),
                },
                "oracle": {"pass": True},
            }
        )
    gate = smoke_gate(rows)
    assert gate["pass"] is True
    assert gate["smc_successful_physical_dispatch"] == 3
    assert gate["smc_scope_blocker_count"] == 0
    assert gate["smc_task_pass"] == 3
    rows[0]["worker"]["surface_exact"] = False
    assert smoke_gate(rows)["pass"] is False


def test_smoke_gate_stops_on_old_version_scope_blocker_or_zero_dispatch() -> None:
    rows = []
    for arm in ("smc", "legacy") * 3:
        rows.append(
            {
                "smoke": True,
                "arm": arm,
                "status": "PASS",
                "oracle": {"pass": True},
                "worker": {
                    "smc_adopted": arm == "smc",
                    "legacy_physical_exec_count": 1 if arm == "legacy" else 0,
                    "fallback_used": False,
                    "surface_exact": True,
                    "receipt_facts": (
                        {"ok_count": 1, "scope_blocker_count": 0}
                        if arm == "smc"
                        else {}
                    ),
                },
            }
        )
    smc_rows = [row for row in rows if row["arm"] == "smc"]
    for row in smc_rows:
        row["worker"]["receipt_facts"]["ok_count"] = 0
    assert smoke_gate(rows)["pass"] is False
    smc_rows[0]["worker"]["receipt_facts"]["ok_count"] = 1
    smc_rows[0]["worker"]["receipt_facts"]["scope_blocker_count"] = 1
    assert smoke_gate(rows)["pass"] is False


def test_analyzer_is_mechanical_and_paired() -> None:
    rows = [
        {"task_id": "click_commit", "repeat": 1, "arm": "smc", "status": "PASS", "oracle": {"pass": True}, "wall_s": 1.0, "worker": {"rounds": 2, "tool_call_count": 2, "tokens_in": 100, "tokens_out": 20, "cache_hit_tokens": 0, "receipt_facts": {"automatic_retry_true_count": 0, "rejected_count": 0, "failed_count": 0}}},
        {"task_id": "click_commit", "repeat": 1, "arm": "legacy", "status": "PASS", "oracle": {"pass": True}, "wall_s": 1.5, "worker": {"rounds": 3, "tool_call_count": 3, "tokens_in": 140, "tokens_out": 30, "cache_hit_tokens": 0}},
    ]
    result = analyze(rows)
    assert result["arms"]["smc"]["task_pass"] == 1
    assert result["paired"][0]["rounds_delta_smc_minus_legacy"] == -1
    assert result["smc_safety"]["automatic_retry_true_total"] == 0
