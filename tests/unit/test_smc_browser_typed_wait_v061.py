from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_wait import (
    BrowserWaitObjectStateTool,
    BrowserWaitObjectTextTool,
    BrowserWaitScopeCountTool,
    BrowserWaitScopeReadyTool,
    BrowserWaitScopeUrlTool,
)
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _adapter(tmp_path: Path) -> BrowserPerceptionAdapter:
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "browser", retention_seconds=60),
        capture_node_cap=10_000,
    )


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        obj
        for obj in result["objects"]
        if obj["attributes"].get("name") == name
        and "dom" in obj.get("coverage", {}).get("sources", [])
    ]
    assert len(matches) == 1
    return matches[0]


def _tools(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    common = {
        "adapter": adapter,
        "backend": None,
        "session_id_getter": lambda: "s1",
    }
    return {
        tool.name: tool
        for tool in (
            BrowserWaitScopeUrlTool(**common),
            BrowserWaitScopeReadyTool(**common),
            BrowserWaitScopeCountTool(**common),
            BrowserWaitObjectStateTool(**common),
            BrowserWaitObjectTextTool(**common),
        )
    }


class _SequenceBackend:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = [deepcopy(item) for item in items]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        return deepcopy(item)


def test_v061_lazy_surface_encodes_value_types_without_anyof(tmp_path: Path) -> None:
    reg = ToolRegistry()
    for tool in _tools(tmp_path).values():
        reg.register(tool)
    lazy = {row["name"]: row for row in reg.schemas(lazy=True)}

    assert set(lazy) == {
        "browser_wait_scope_url",
        "browser_wait_scope_ready",
        "browser_wait_scope_count",
        "browser_wait_object_state",
        "browser_wait_object_text",
    }

    ready = lazy["browser_wait_scope_ready"]["parameters"]
    assert ready["properties"]["state"] == {
        "type": "string",
        "enum": ["loading", "interactive", "complete"],
    }
    assert "operator" not in ready["properties"]
    assert "value" not in ready["properties"]

    state = lazy["browser_wait_object_state"]["parameters"]
    assert state["properties"]["value"] == {"type": "boolean"}
    assert state["properties"]["property"]["enum"] == [
        "exists",
        "enabled",
        "checked",
        "selected",
        "expanded",
        "focused",
        "editable",
    ]
    assert "visible" not in state["properties"]["property"]["enum"]
    assert "operator" not in state["properties"]

    text = lazy["browser_wait_object_text"]["parameters"]
    assert text["properties"]["value"] == {"type": "string"}
    assert text["properties"]["property"]["enum"] == ["name", "value_text"]
    assert text["properties"]["operator"]["enum"] == ["eq", "contains", "prefix", "suffix"]

    url = lazy["browser_wait_scope_url"]["parameters"]
    assert url["properties"]["value"] == {"type": "string"}
    assert url["properties"]["operator"]["enum"] == ["eq", "contains", "prefix", "suffix"]

    count = lazy["browser_wait_scope_count"]["parameters"]
    assert count["properties"]["count"] == {"type": "integer", "minimum": 0}
    assert count["properties"]["operator"]["enum"] == ["eq", "ge", "le"]


def test_v061_compilers_only_fill_mechanical_predicate_fields(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]
    submit = _by_name(snap, "Submit")
    common = {"adapter": adapter, "backend": None, "session_id_getter": lambda: "s1"}

    ready = BrowserWaitScopeReadyTool(**common).compile_predicate(
        "s1",
        {"scope_ref": scope_ref, "state": "complete", "timeout_ms": 100, "interval_ms": 1},
    )
    assert ready == {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": scope_ref,
        "property": "document_ready_state",
        "operator": "eq",
        "value": "complete",
    }

    state = BrowserWaitObjectStateTool(**common).compile_predicate(
        "s1",
        {
            "object_ref": submit["grounding_ref"],
            "property": "enabled",
            "value": True,
            "timeout_ms": 100,
            "interval_ms": 1,
        },
    )
    assert state == {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": submit["scope_ref"],
        "target": submit["id"],
        "property": "enabled",
        "operator": "eq",
        "value": True,
    }


def test_v061_wrong_json_types_fail_before_polling(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(snap, "Submit")
    common = {"adapter": adapter, "backend": None, "session_id_getter": lambda: "s1"}

    state = BrowserWaitObjectStateTool(**common).execute(
        object_ref=submit["grounding_ref"],
        property="enabled",
        value="true",
        timeout_ms=100,
        interval_ms=1,
    )
    count = BrowserWaitScopeCountTool(**common).execute(
        scope_ref=snap["snapshot"]["scope"]["scope_ref"],
        operator="ge",
        count="1",
        timeout_ms=100,
        interval_ms=1,
    )

    assert state.status.value == "failure"
    assert "expected boolean" in state.content
    assert count.status.value == "failure"
    assert "count" in count.content and "integer" in count.content


def test_v061_scope_ready_polls_same_canonical_ready_state_fact(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    initial = deepcopy(FIXTURES["base"])
    initial["document_ready_state"] = "loading"
    complete = deepcopy(FIXTURES["base"])
    complete["document_ready_state"] = "complete"
    seed = adapter.snapshot("s1", initial)
    scope_ref = seed["snapshot"]["scope"]["scope_ref"]
    backend = _SequenceBackend([initial, complete])
    tool = BrowserWaitScopeReadyTool(
        adapter=adapter, backend=backend, session_id_getter=lambda: "s1"
    )

    result = tool.execute(
        scope_ref=scope_ref,
        state="complete",
        timeout_ms=100,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate"]["property"] == "document_ready_state"
    assert payload["predicate"]["operator"] == "eq"
    assert payload["predicate"]["value"] == "complete"
    assert backend.calls == 2


def test_v061_object_state_polls_same_canonical_boolean_fact(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    disabled = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in disabled[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    seed = adapter.snapshot("s1", disabled)
    submit = _by_name(seed, "Submit")
    backend = _SequenceBackend([disabled, FIXTURES["base"]])
    tool = BrowserWaitObjectStateTool(
        adapter=adapter, backend=backend, session_id_getter=lambda: "s1"
    )

    result = tool.execute(
        object_ref=submit["grounding_ref"],
        property="enabled",
        value=True,
        timeout_ms=100,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate"]["operator"] == "eq"
    assert payload["predicate"]["value"] is True
    assert backend.calls == 2
