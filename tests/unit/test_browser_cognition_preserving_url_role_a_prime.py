from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool

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


def _branch(params: dict[str, Any], *, discriminator: str, value: str) -> dict[str, Any]:
    for branch in params.get("oneOf") or []:
        props = branch.get("properties") or {}
        values = (props.get(discriminator) or {}).get("enum") or []
        if values == [value]:
            return branch
    raise AssertionError(f"branch {discriminator}={value!r} not found")


def _property_keys(schema: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            keys.update(str(key) for key in props)
        for value in schema.values():
            keys.update(_property_keys(value))
    elif isinstance(schema, list):
        for value in schema:
            keys.update(_property_keys(value))
    return keys


def test_a_prime_perceive_provider_surface_has_observation_specific_url_role_only() -> None:
    for params in (BrowserPerceiveTool.parameters, BrowserPerceiveTool.lazy_parameters):
        root_props = params.get("properties") or {}
        page_url = next(
            branch
            for branch in params.get("oneOf") or []
            if ((branch.get("properties") or {}).get("kind") or {}).get("enum") == ["page_url"]
        )
        page_props = page_url.get("properties") or {}

        assert "url" not in root_props
        assert "url" not in _property_keys(params)
        assert "expected_url" in root_props
        assert set(page_props) == {"action", "kind", "match", "expected_url", "within_ms"}
        assert set(page_url.get("required") or []) == {
            "action",
            "kind",
            "match",
            "expected_url",
        }


def test_a_prime_operate_keeps_destination_url_for_navigate() -> None:
    params = BrowserSemanticOperationTool.lazy_parameters
    navigate = _branch(params, discriminator="do", value="navigate")
    props = navigate.get("properties") or {}

    assert set(props) == {"do", "url"}
    assert set(navigate.get("required") or []) == {"do", "url"}
    assert "expected_url" not in _property_keys(params)


def test_a_prime_flat_page_url_wait_executes_with_expected_url(tmp_path: Path) -> None:
    result = _perceive(tmp_path).execute(
        action="wait",
        kind="page_url",
        match="equals",
        expected_url="https://example.test/a",
        within_ms=50,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate"]["property"] == "url"
    assert payload["predicate"]["value"] == "https://example.test/a"
    assert payload["predicate_result"]["result"] == "satisfied"


def test_a_prime_hidden_legacy_flat_url_remains_mechanically_executable(tmp_path: Path) -> None:
    result = _perceive(tmp_path).execute(
        action="wait",
        kind="page_url",
        match="equals",
        url="https://example.test/a",
        within_ms=50,
    )

    assert result.status.value == "success"
