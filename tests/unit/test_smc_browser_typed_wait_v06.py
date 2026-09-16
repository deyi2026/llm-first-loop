from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.browser.predicate import validate_predicate
from llm_loop.tools.builtin import browser_wait as browser_wait_module
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_wait import (
    BrowserPredicateWaiter,
    BrowserWaitObjectTool,
    BrowserWaitScopeTool,
)
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS, ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_SCOPE_PROPERTIES = {"url", "document_ready_state", "object_count"}
_OBJECT_PROPERTIES = {
    "exists",
    "enabled",
    "visible",
    "checked",
    "selected",
    "expanded",
    "focused",
    "editable",
    "name",
    "value_text",
}


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


def _disabled_submit_fixture() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in raw[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    return raw


class _SequenceBackend:
    def __init__(self, items: list[dict[str, Any] | BaseException]) -> None:
        self.items = list(items)
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        item = self.items[min(self.calls - 1, len(self.items) - 1)]
        if isinstance(item, BaseException):
            raise item
        return deepcopy(item)


def _scope_tool(
    tmp_path: Path,
    backend: _SequenceBackend | None = None,
    *,
    session_id: str = "s1",
) -> tuple[BrowserPerceptionAdapter, BrowserWaitScopeTool]:
    adapter = _adapter(tmp_path)
    tool = BrowserWaitScopeTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: session_id,
    )
    return adapter, tool


def _object_tool(
    tmp_path: Path,
    backend: _SequenceBackend | None = None,
    *,
    session_id: str = "s1",
) -> tuple[BrowserPerceptionAdapter, BrowserWaitObjectTool]:
    adapter = _adapter(tmp_path)
    tool = BrowserWaitObjectTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: session_id,
    )
    return adapter, tool


def test_v06_provider_surface_aggregates_wait_over_closed_typed_primitives() -> None:
    perceive_props = BrowserPerceiveTool.parameters["properties"]
    assert perceive_props["action"]["enum"] == ["snapshot", "hydrate", "diff", "wait"]
    assert set(perceive_props) == {
        "action",
        "projection_limit",
        "projection_kinds",
        "projection_cursor",
        "vision",
        "grounding_ref",
        "from_version",
        "to_version",
        "kind",
        "state",
        "match",
        "url",
        "object_ref",
        "value",
        "field",
        "text",
        "within_ms",
    }
    assert "condition" not in perceive_props
    for forbidden in ("predicate", "timeout_ms", "interval_ms"):
        assert forbidden not in perceive_props

    expected_common = {
        "property",
        "operator",
        "value",
        "timeout_ms",
        "interval_ms",
    }
    scope = BrowserWaitScopeTool.parameters
    obj = BrowserWaitObjectTool.parameters
    assert set(scope["properties"]) == {"scope_ref", *expected_common}
    assert set(scope["required"]) == {"scope_ref", *expected_common}
    assert set(obj["properties"]) == {"object_ref", *expected_common}
    assert set(obj["required"]) == {"object_ref", *expected_common}
    assert set(scope["properties"]["property"]["enum"]) == _SCOPE_PROPERTIES
    assert set(obj["properties"]["property"]["enum"]) == _OBJECT_PROPERTIES
    for params in (scope, obj):
        assert params["properties"]["timeout_ms"]["minimum"] == 1
        assert params["properties"]["timeout_ms"]["maximum"] == 60_000
        assert params["properties"]["interval_ms"]["minimum"] == 1
        assert params["properties"]["interval_ms"]["maximum"] == 5_000
        assert params["additionalProperties"] is False


def test_v06_lazy_surface_keeps_typed_property_enums_and_machine_bounds(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    reg = ToolRegistry()
    reg.register(
        BrowserWaitScopeTool(
            adapter=adapter,
            backend=None,
            session_id_getter=lambda: "s1",
        )
    )
    reg.register(
        BrowserWaitObjectTool(
            adapter=adapter,
            backend=None,
            session_id_getter=lambda: "s1",
        )
    )
    schemas = {row["name"]: row for row in reg.schemas(lazy=True)}
    scope = schemas["browser_wait_scope"]
    obj = schemas["browser_wait_object"]
    assert set(scope["parameters"]["properties"]["property"]["enum"]) == _SCOPE_PROPERTIES
    assert set(obj["parameters"]["properties"]["property"]["enum"]) == _OBJECT_PROPERTIES
    for row in (scope, obj):
        props = row["parameters"]["properties"]
        assert props["timeout_ms"] == {"type": "integer", "minimum": 1, "maximum": 60_000}
        assert props["interval_ms"] == {"type": "integer", "minimum": 1, "maximum": 5_000}
    assert "target=scope_ref" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_scope"]
    assert "GroundingRef" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_object"]
    assert "object_ref" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_object"]
    assert "（grounding_ref）" not in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_object"]
    perceive_props = BrowserPerceiveTool.parameters["properties"]
    assert "wait" in perceive_props["action"]["enum"]
    assert "interval_ms" not in perceive_props


def test_scope_compiler_derives_only_fixed_predicate_identity(tmp_path: Path) -> None:
    adapter, tool = _scope_tool(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]

    predicate = tool.compile_predicate(
        "s1",
        {
            "scope_ref": scope_ref,
            "property": "url",
            "operator": "contains",
            "value": "/a",
            "timeout_ms": 100,
            "interval_ms": 1,
        },
    )

    assert predicate == {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": scope_ref,
        "property": "url",
        "operator": "contains",
        "value": "/a",
    }
    assert validate_predicate(predicate) is None


def test_object_compiler_hydrates_exact_ref_and_derives_id_and_scope(tmp_path: Path) -> None:
    adapter, tool = _object_tool(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(snap, "Submit")

    predicate = tool.compile_predicate(
        "s1",
        {
            "object_ref": submit["grounding_ref"],
            "property": "enabled",
            "operator": "eq",
            "value": True,
            "timeout_ms": 100,
            "interval_ms": 1,
        },
    )

    assert predicate == {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": submit["scope_ref"],
        "target": submit["id"],
        "property": "enabled",
        "operator": "eq",
        "value": True,
    }
    assert validate_predicate(predicate) is None


def test_object_compiler_rejects_cross_session_and_wrong_projection_before_polling(
    tmp_path: Path,
) -> None:
    backend = _SequenceBackend([FIXTURES["base"]])
    adapter, tool = _object_tool(tmp_path, backend)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(snap, "Submit")
    common = {
        "property": "enabled",
        "operator": "eq",
        "value": True,
        "timeout_ms": 100,
        "interval_ms": 1,
    }

    cross = tool.execute_request(
        "other-session",
        {"object_ref": submit["grounding_ref"], **common},
    )
    wrong = tool.execute_request(
        "s1",
        {"object_ref": snap["resource_ref"], **common},
    )

    assert cross.status.value == "failure"
    assert "unauthorized" in cross.content
    assert wrong.status.value == "failure"
    assert "projection" in wrong.content
    assert backend.calls == 0


def test_typed_object_wait_preserves_polling_until_satisfied(tmp_path: Path) -> None:
    backend = _SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]])
    adapter, tool = _object_tool(tmp_path, backend)
    seed = adapter.snapshot("s1", _disabled_submit_fixture())
    submit = _by_name(seed, "Submit")

    result = tool.execute(
        object_ref=submit["grounding_ref"],
        property="enabled",
        operator="eq",
        value=True,
        timeout_ms=100,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["action"] == "wait"
    assert payload["predicate"]["schema"] == "smc.predicate.v0.1"
    assert payload["predicate"]["scope_ref"] == submit["scope_ref"]
    assert payload["predicate"]["target"] == submit["id"]
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate_result"]["sample_count"] >= 2
    assert payload["predicate_result"]["observer_error_count"] == 0
    assert backend.calls >= 2


def test_typed_scope_wait_preserves_scope_indeterminate_on_document_change(tmp_path: Path) -> None:
    adapter, tool = _scope_tool(tmp_path, _SequenceBackend([FIXTURES["navigate"]]))
    seed = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = seed["snapshot"]["scope"]["scope_ref"]

    result = tool.execute(
        scope_ref=scope_ref,
        property="url",
        operator="contains",
        value="never",
        timeout_ms=1,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "indeterminate"
    assert payload["observation"]["reason"] == "scope_not_observed"


def test_typed_wait_observer_error_recovers_without_mutation_or_fallback(tmp_path: Path) -> None:
    backend = _SequenceBackend([RuntimeError("synthetic outage"), FIXTURES["base"]])
    adapter, tool = _object_tool(tmp_path, backend)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(seed, "Submit")

    result = tool.execute(
        object_ref=submit["grounding_ref"],
        property="enabled",
        operator="eq",
        value=True,
        timeout_ms=100,
        interval_ms=1,
    )

    payload = json.loads(result.content)
    assert result.status.value == "success"
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate_result"]["observer_error_count"] == 1
    assert "action_id" not in payload
    assert "receipt_id" not in payload


def test_typed_wait_bounds_and_invalid_operator_fail_before_capture(tmp_path: Path) -> None:
    backend = _SequenceBackend([FIXTURES["base"]])
    adapter, tool = _scope_tool(tmp_path, backend)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]

    invalid_operator = tool.execute(
        scope_ref=scope_ref,
        property="url",
        operator="ge",
        value="x",
        timeout_ms=10,
        interval_ms=1,
    )
    too_long = tool.execute(
        scope_ref=scope_ref,
        property="url",
        operator="eq",
        value="x",
        timeout_ms=60_001,
        interval_ms=1,
    )

    assert invalid_operator.status.value == "failure"
    assert too_long.status.value == "failure"
    assert backend.calls == 0


def test_browser_perceive_rejects_action_irrelevant_fields_instead_of_ignoring_them(
    tmp_path: Path,
) -> None:
    backend = _SequenceBackend([FIXTURES["base"]])
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(seed, "Submit")
    tool = BrowserPerceiveTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    snapshot_extra = tool.execute(action="snapshot", predicate={"ignored": True})
    hydrate_extra = tool.execute(
        action="hydrate",
        grounding_ref=submit["grounding_ref"],
        projection_limit=10,
    )
    diff_extra = tool.execute(
        action="diff",
        from_version=seed["snapshot"]["snapshot_id"],
        to_version=seed["snapshot"]["snapshot_id"],
        grounding_ref=submit["grounding_ref"],
    )

    assert snapshot_extra.status.value == "failure"
    assert hydrate_extra.status.value == "failure"
    assert diff_extra.status.value == "failure"
    assert "fields_mismatch" in snapshot_extra.content
    assert "fields_mismatch" in hydrate_extra.content
    assert "fields_mismatch" in diff_extra.content
    assert backend.calls == 0


def test_typed_wait_never_starts_poll_sample_at_or_after_deadline(
    tmp_path: Path, monkeypatch: Any
) -> None:
    backend = _SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]])
    adapter, tool = _object_tool(tmp_path, backend)
    seed = adapter.snapshot("s1", _disabled_submit_fixture())
    submit = _by_name(seed, "Submit")
    clock = {"now": 0.0}

    monkeypatch.setattr(browser_wait_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(browser_wait_module.time, "time", lambda: 1_700_000_000.0 + clock["now"])

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(browser_wait_module.time, "sleep", fake_sleep)

    result = tool.execute(
        object_ref=submit["grounding_ref"],
        property="enabled",
        operator="eq",
        value=True,
        timeout_ms=10,
        interval_ms=10,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "unsatisfied"
    assert payload["predicate_result"]["sample_count"] == 1
    assert backend.calls == 1
    assert clock["now"] == 0.01


def test_typed_object_wait_preserves_timeout_unsatisfied(tmp_path: Path) -> None:
    backend = _SequenceBackend([FIXTURES["base"]])
    adapter, tool = _object_tool(tmp_path, backend)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(seed, "Submit")

    result = tool.execute(
        object_ref=submit["grounding_ref"],
        property="name",
        operator="eq",
        value="Never this name",
        timeout_ms=3,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "unsatisfied"
    assert payload["predicate_result"]["sample_count"] >= 1


def test_typed_object_wait_preserves_complete_absence_vs_partial_indeterminate(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(seed, "Submit")
    common = {
        "object_ref": submit["grounding_ref"],
        "property": "exists",
        "operator": "eq",
        "value": False,
        "timeout_ms": 1,
        "interval_ms": 1,
    }

    complete_raw = deepcopy(FIXTURES["base"])
    complete_raw["dom"]["nodes"] = [
        node for node in complete_raw["dom"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    complete_raw["ax"]["nodes"] = [
        node for node in complete_raw["ax"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    complete_tool = BrowserWaitObjectTool(
        adapter=adapter,
        backend=_SequenceBackend([complete_raw]),
        session_id_getter=lambda: "s1",
    )
    complete = complete_tool.execute(**common)
    assert json.loads(complete.content)["predicate_result"]["result"] == "satisfied"

    partial_raw = deepcopy(complete_raw)
    partial_raw["dom"]["truncated"] = True
    partial_tool = BrowserWaitObjectTool(
        adapter=adapter,
        backend=_SequenceBackend([partial_raw]),
        session_id_getter=lambda: "s1",
    )
    partial = partial_tool.execute(**common)
    partial_payload = json.loads(partial.content)
    assert partial_payload["predicate_result"]["result"] == "indeterminate"
    assert "coverage" in str(partial_payload["observation"]["reason"])


def test_typed_wait_with_only_observer_failures_stays_indeterminate(tmp_path: Path) -> None:
    adapter, tool = _scope_tool(
        tmp_path,
        _SequenceBackend([RuntimeError("synthetic observer outage")]),
    )
    seed = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = seed["snapshot"]["scope"]["scope_ref"]

    result = tool.execute(
        scope_ref=scope_ref,
        property="url",
        operator="eq",
        value="https://example.test/a",
        timeout_ms=3,
        interval_ms=1,
    )

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "indeterminate"
    assert payload["predicate_result"]["observer_error_count"] >= 1
    assert payload["observation"]["reason"] == "observer_error"


def test_typed_wait_property_target_kind_mismatch_is_impossible_on_provider_surface_and_rejected_directly(
    tmp_path: Path,
) -> None:
    backend = _SequenceBackend([FIXTURES["base"]])
    adapter, scope_tool = _scope_tool(tmp_path, backend)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = seed["snapshot"]["scope"]["scope_ref"]
    submit = _by_name(seed, "Submit")
    object_tool = BrowserWaitObjectTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    scope_bad = scope_tool.execute(
        scope_ref=scope_ref,
        property="enabled",
        operator="eq",
        value=True,
        timeout_ms=10,
        interval_ms=1,
    )
    object_bad = object_tool.execute(
        object_ref=submit["grounding_ref"],
        property="document_ready_state",
        operator="eq",
        value="complete",
        timeout_ms=10,
        interval_ms=1,
    )

    assert scope_bad.status.value == "failure"
    assert object_bad.status.value == "failure"
    assert "target_kind_mismatch" in scope_bad.content
    assert "target_kind_mismatch" in object_bad.content
    assert backend.calls == 0



def _wait_facts(result: Any) -> dict[str, Any]:
    payload = json.loads(result.content)
    predicate_result = payload["predicate_result"]
    observation = payload["observation"]
    return {
        "result": predicate_result["result"],
        "sample_count": predicate_result["sample_count"],
        "observer_error_count": predicate_result["observer_error_count"],
        "observation_result": observation["result"],
        "reason": observation.get("reason"),
        "observed_value": observation.get("observed_value"),
        "coverage_complete": observation.get("coverage_complete"),
    }


def test_v06_typed_object_wait_is_deterministically_equivalent_to_canonical_wait(
    tmp_path: Path, monkeypatch: Any
) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", _disabled_submit_fixture())
    submit = _by_name(seed, "Submit")
    request = {
        "object_ref": submit["grounding_ref"],
        "property": "enabled",
        "operator": "eq",
        "value": True,
        "timeout_ms": 100,
        "interval_ms": 1,
    }
    compiler = BrowserWaitObjectTool(
        adapter=adapter,
        backend=None,
        session_id_getter=lambda: "s1",
    )
    predicate = compiler.compile_predicate("s1", request)
    clock = {"now": 0.0}
    monkeypatch.setattr(browser_wait_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        browser_wait_module.time,
        "time",
        lambda: 1_700_000_000.0 + clock["now"],
    )
    monkeypatch.setattr(
        browser_wait_module.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    canonical = BrowserPredicateWaiter(
        adapter=adapter,
        backend=_SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]]),
    ).wait(
        "s1",
        predicate=predicate,
        timeout_ms=100,
        interval_ms=1,
        tool_name="canonical",
    )
    clock["now"] = 0.0
    typed = BrowserWaitObjectTool(
        adapter=adapter,
        backend=_SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]]),
        session_id_getter=lambda: "s1",
    ).execute(**request)

    assert _wait_facts(typed) == _wait_facts(canonical)
    assert _wait_facts(typed) == {
        "result": "satisfied",
        "sample_count": 2,
        "observer_error_count": 0,
        "observation_result": "satisfied",
        "reason": None,
        "observed_value": True,
        "coverage_complete": True,
    }


def test_v06_typed_wait_preserves_canonical_indeterminate_and_coverage_semantics(
    tmp_path: Path, monkeypatch: Any
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(browser_wait_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        browser_wait_module.time,
        "time",
        lambda: 1_700_000_000.0 + clock["now"],
    )
    monkeypatch.setattr(
        browser_wait_module.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    scope_adapter = _adapter(tmp_path / "scope-case")
    scope_seed = scope_adapter.snapshot("s1", FIXTURES["base"])
    scope_request = {
        "scope_ref": scope_seed["snapshot"]["scope"]["scope_ref"],
        "property": "url",
        "operator": "eq",
        "value": "https://never.invalid/",
        "timeout_ms": 1,
        "interval_ms": 1,
    }
    scope_compiler = BrowserWaitScopeTool(
        adapter=scope_adapter, backend=None, session_id_getter=lambda: "s1"
    )
    scope_predicate = scope_compiler.compile_predicate("s1", scope_request)
    canonical_scope = BrowserPredicateWaiter(
        adapter=scope_adapter,
        backend=_SequenceBackend([FIXTURES["navigate"]]),
    ).wait(
        "s1",
        predicate=scope_predicate,
        timeout_ms=1,
        interval_ms=1,
        tool_name="canonical",
    )
    clock["now"] = 0.0
    typed_scope = BrowserWaitScopeTool(
        adapter=scope_adapter,
        backend=_SequenceBackend([FIXTURES["navigate"]]),
        session_id_getter=lambda: "s1",
    ).execute(**scope_request)
    assert _wait_facts(typed_scope) == _wait_facts(canonical_scope)
    assert _wait_facts(typed_scope)["result"] == "indeterminate"
    assert _wait_facts(typed_scope)["reason"] == "scope_not_observed"

    object_adapter = _adapter(tmp_path / "coverage-case")
    object_seed = object_adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(object_seed, "Submit")
    partial_raw = deepcopy(FIXTURES["base"])
    partial_raw["dom"]["nodes"] = [
        node for node in partial_raw["dom"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    partial_raw["ax"]["nodes"] = [
        node for node in partial_raw["ax"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    partial_raw["dom"]["truncated"] = True
    object_request = {
        "object_ref": submit["grounding_ref"],
        "property": "exists",
        "operator": "eq",
        "value": False,
        "timeout_ms": 1,
        "interval_ms": 1,
    }
    object_compiler = BrowserWaitObjectTool(
        adapter=object_adapter, backend=None, session_id_getter=lambda: "s1"
    )
    object_predicate = object_compiler.compile_predicate("s1", object_request)
    clock["now"] = 0.0
    canonical_object = BrowserPredicateWaiter(
        adapter=object_adapter,
        backend=_SequenceBackend([partial_raw]),
    ).wait(
        "s1",
        predicate=object_predicate,
        timeout_ms=1,
        interval_ms=1,
        tool_name="canonical",
    )
    clock["now"] = 0.0
    typed_object = BrowserWaitObjectTool(
        adapter=object_adapter,
        backend=_SequenceBackend([partial_raw]),
        session_id_getter=lambda: "s1",
    ).execute(**object_request)
    assert _wait_facts(typed_object) == _wait_facts(canonical_object)
    assert _wait_facts(typed_object)["result"] == "indeterminate"
    assert "coverage" in str(_wait_facts(typed_object)["reason"])


def test_v06_typed_wait_preserves_canonical_observer_error_accounting(
    tmp_path: Path, monkeypatch: Any
) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = seed["snapshot"]["scope"]["scope_ref"]
    request = {
        "scope_ref": scope_ref,
        "property": "url",
        "operator": "eq",
        "value": "https://example.test/a",
        "timeout_ms": 100,
        "interval_ms": 1,
    }
    compiler = BrowserWaitScopeTool(
        adapter=adapter, backend=None, session_id_getter=lambda: "s1"
    )
    predicate = compiler.compile_predicate("s1", request)
    clock = {"now": 0.0}
    monkeypatch.setattr(browser_wait_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        browser_wait_module.time,
        "time",
        lambda: 1_700_000_000.0 + clock["now"],
    )
    monkeypatch.setattr(
        browser_wait_module.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    sequence: list[dict[str, Any] | BaseException] = [
        RuntimeError("synthetic outage"),
        FIXTURES["base"],
    ]
    canonical = BrowserPredicateWaiter(
        adapter=adapter, backend=_SequenceBackend(sequence)
    ).wait(
        "s1",
        predicate=predicate,
        timeout_ms=100,
        interval_ms=1,
        tool_name="canonical",
    )
    clock["now"] = 0.0
    typed = BrowserWaitScopeTool(
        adapter=adapter,
        backend=_SequenceBackend(sequence),
        session_id_getter=lambda: "s1",
    ).execute(**request)

    assert _wait_facts(typed) == _wait_facts(canonical)
    assert _wait_facts(typed)["observer_error_count"] == 1
    assert _wait_facts(typed)["result"] == "satisfied"
