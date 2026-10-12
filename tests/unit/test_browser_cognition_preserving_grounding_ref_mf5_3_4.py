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
    return BrowserPerceiveTool(
        adapter=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception")),
        backend=_Backend(),
        session_id_getter=lambda: "s1",
    )


def _branch(params: dict[str, Any], kind: str) -> dict[str, Any]:
    for branch in params.get("oneOf") or []:
        props = branch.get("properties") or {}
        if ((props.get("action") or {}).get("enum") or []) != ["wait"]:
            continue
        if ((props.get("kind") or {}).get("enum") or []) == [kind]:
            return branch
    raise AssertionError(f"wait branch {kind!r} not found")


def _assert_grounding_ref_branch(params: dict[str, Any], kind: str) -> None:
    branch = _branch(params, kind)
    props = branch.get("properties") or {}
    required = set(branch.get("required") or [])

    assert "grounding_ref" in props
    assert "grounding_ref" in required
    assert "object_ref" not in props
    assert "object_ref" not in required
    assert branch.get("additionalProperties") is False


def test_mf5_3_4_provider_object_state_wait_uses_grounding_ref() -> None:
    _assert_grounding_ref_branch(BrowserPerceiveTool.parameters, "object_state")


def test_mf5_3_4_provider_object_text_wait_uses_grounding_ref() -> None:
    _assert_grounding_ref_branch(BrowserPerceiveTool.parameters, "object_text")


def test_mf5_3_4_lazy_provider_surface_uses_grounding_ref_too() -> None:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    lazy = registry.schemas(lazy=True)[0]["parameters"]

    _assert_grounding_ref_branch(lazy, "object_state")
    _assert_grounding_ref_branch(lazy, "object_text")


def test_mf5_3_4_model_visible_grounding_ref_executes_exact_object_wait(tmp_path: Path) -> None:
    perceive = _perceive(tmp_path)
    snapshot = json.loads(perceive.execute(action="snapshot").content)
    submit = next(
        obj for obj in snapshot["objects"] if obj.get("attributes", {}).get("name") == "Submit"
    )

    result = perceive.execute(
        action="wait",
        kind="object_state",
        grounding_ref=submit["grounding_ref"],
        state="enabled",
        value=True,
        within_ms=50,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate"]["target"] == submit["id"]
    assert payload["predicate"]["property"] == "enabled"


def test_mf5_3_4_hidden_legacy_object_ref_remains_mechanically_executable(tmp_path: Path) -> None:
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


def test_mf5_3_4_hidden_legacy_object_ref_still_rejects_bare_semantic_id(tmp_path: Path) -> None:
    perceive = _perceive(tmp_path)
    snapshot = json.loads(perceive.execute(action="snapshot").content)
    submit = next(
        obj for obj in snapshot["objects"] if obj.get("attributes", {}).get("name") == "Submit"
    )

    result = perceive.execute(
        action="wait",
        kind="object_state",
        object_ref=submit["id"],
        state="enabled",
        value=True,
        within_ms=50,
    )

    assert result.status.value == "failure"
    assert "object_ref_unavailable:invalid_ref" in result.content
