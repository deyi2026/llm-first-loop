from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)["base"]


class _Backend:
    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(FIXTURE))


def _perceive(tmp_path: Path) -> BrowserPerceiveTool:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    return BrowserPerceiveTool(
        adapter=adapter,
        backend=_Backend(),
        session_id_getter=lambda: "s1",
    )


def _branch_key(branch: dict[str, Any]) -> tuple[str, str]:
    props = branch.get("properties") or {}
    action = str(((props.get("action") or {}).get("enum") or [""])[0])
    kind = str(((props.get("kind") or {}).get("enum") or [""])[0])
    return action, kind


def _branches(params: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        _branch_key(branch): branch
        for branch in (params.get("oneOf") or [])
        if isinstance(branch, dict)
    }


def test_mf5_3_1_perceive_provider_contract_is_root_direct_oneof() -> None:
    params = BrowserPerceiveTool.parameters
    branches = _branches(params)

    assert set(branches) == {
        ("snapshot", ""),
        ("hydrate", ""),
        ("diff", ""),
        ("wait", "page_ready"),
        ("wait", "page_url"),
        ("wait", "object_state"),
        ("wait", "object_text"),
    }
    assert all(branch.get("additionalProperties") is False for branch in branches.values())


def test_mf5_3_1_perceive_wait_fields_are_flat_not_nested_condition() -> None:
    branches = _branches(BrowserPerceiveTool.parameters)
    page_url = branches.get(("wait", "page_url"))
    assert isinstance(page_url, dict)
    props = page_url.get("properties") or {}

    assert "condition" not in props
    assert set(props) == {"action", "kind", "match", "url", "within_ms"}
    assert set(page_url.get("required") or []) == {"action", "kind", "match", "url"}


def test_mf5_3_1_action_specific_branches_exclude_cross_action_fields() -> None:
    branches = _branches(BrowserPerceiveTool.parameters)
    expected = {
        ("snapshot", ""): ({"action", "projection_limit"}, {"action"}),
        ("hydrate", ""): ({"action", "grounding_ref"}, {"action", "grounding_ref"}),
        ("diff", ""): (
            {"action", "from_version", "to_version"},
            {"action", "from_version", "to_version"},
        ),
        ("wait", "page_ready"): (
            {"action", "kind", "state", "within_ms"},
            {"action", "kind", "state"},
        ),
        ("wait", "page_url"): (
            {"action", "kind", "match", "url", "within_ms"},
            {"action", "kind", "match", "url"},
        ),
        ("wait", "object_state"): (
            {"action", "kind", "object_ref", "state", "value", "within_ms"},
            {"action", "kind", "object_ref", "state", "value"},
        ),
        ("wait", "object_text"): (
            {"action", "kind", "object_ref", "field", "match", "text", "within_ms"},
            {"action", "kind", "object_ref", "field", "match", "text"},
        ),
    }

    for key, (property_names, required_names) in expected.items():
        branch = branches.get(key)
        assert isinstance(branch, dict), f"missing root-direct branch: {key}"
        assert set((branch.get("properties") or {}).keys()) == property_names
        assert set(branch.get("required") or []) == required_names


def test_mf5_3_1_lazy_provider_surface_keeps_same_root_direct_branches() -> None:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    lazy = registry.schemas(lazy=True)[0]["parameters"]

    assert set(_branches(lazy)) == set(_branches(BrowserPerceiveTool.parameters))
    assert "condition" not in json.dumps(lazy, ensure_ascii=False, sort_keys=True)


def test_mf5_3_1_flat_page_url_wait_executes_without_nested_condition(tmp_path: Path) -> None:
    perceive = _perceive(tmp_path)
    result = perceive.execute(
        action="wait",
        kind="page_url",
        match="equals",
        url="https://example.test/a",
        within_ms=50,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate"]["property"] == "url"
    assert payload["predicate"]["value"] == "https://example.test/a"
    assert payload["predicate_result"]["result"] == "satisfied"


def test_mf5_3_1_flat_object_wait_executes_with_exact_ref(tmp_path: Path) -> None:
    perceive = _perceive(tmp_path)
    snapshot = json.loads(perceive.execute(action="snapshot").content)
    submit = next(
        obj for obj in snapshot["objects"] if obj.get("attributes", {}).get("name") == "Submit"
    )

    result = perceive.execute(
        action="wait",
        kind="object_state",
        object_ref=submit["grounding_ref"],
        state="enabled",
        value=True,
        within_ms=50,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate"]["target"] == submit["id"]
    assert payload["predicate"]["property"] == "enabled"


def test_mf5_3_1_runtime_poll_interval_remains_hidden_from_provider_contract() -> None:
    wire = json.dumps(BrowserPerceiveTool.parameters, ensure_ascii=False, sort_keys=True)
    assert "interval_ms" not in wire


def test_mf5_3_1_program_strategy_authority_stays_closed() -> None:
    wire = json.dumps(BrowserPerceiveTool.parameters, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "fuzzy",
        "best_match",
        "auto_target",
        "auto_retry",
        "rebind",
        "latest",
        "task_success",
        "task_complete",
    ):
        assert forbidden not in wire
