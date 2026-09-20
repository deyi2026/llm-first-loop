from __future__ import annotations

import json
import runpy
from copy import deepcopy
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.browser.predicate import PREDICATE_SPECS, predicate_parameter_schema
from llm_loop.tools.builtin import browser_wait as browser_wait_module
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_wait import (
    BrowserPredicateWaiter,
    BrowserWaitObjectTool,
    BrowserWaitScopeTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)
PROFILE = json.loads(
    (ROOT / "docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads(
    (ROOT / "docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json").read_text(encoding="utf-8")
)


def _adapter(tmp_path: Path) -> BrowserPerceptionAdapter:
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "browser", retention_seconds=60),
        capture_node_cap=10_000,
    )


def _snapshot_id(result: dict[str, Any]) -> str:
    return str(result["snapshot"]["snapshot_id"])


def _dom_object_named(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        obj
        for obj in result["objects"]
        if obj["attributes"].get("name") == name
        and "dom" in obj.get("coverage", {}).get("sources", [])
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one DOM-backed object named {name!r}, got {len(matches)}")
    return matches[0]


def _predicate(
    *,
    scope_ref: str,
    target: str,
    property_name: str,
    operator: str,
    value: Any,
) -> dict[str, Any]:
    return {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": target,
        "property": property_name,
        "operator": operator,
        "value": value,
    }


def _bspec_errors(value: Any, schema_name: str) -> list[str]:
    namespace = runpy.run_path(str(ROOT / "tests/unit/test_smc_browser_phase1_spec_v01.py"))
    validate = namespace["_validate"]
    return validate(value, {"$ref": f"#/$defs/{schema_name}"}, SCHEMA)


def _disabled_submit_fixture() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in raw[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    return raw


def _without_submit_fixture(*, truncated: bool = False) -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    raw["dom"]["nodes"] = [
        node for node in raw["dom"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    raw["ax"]["nodes"] = [
        node for node in raw["ax"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    if truncated:
        raw["dom"]["truncated"] = True
    return raw


def _with_snapshot_local_ax_object() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-local-only",
            "physical_id": None,
            "frame_token": None,
            "kind": "text",
            "attributes": {"role": "InlineTextBox", "name": "Local only"},
            "state": {"exists": True},
        }
    )
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


class _CanonicalWaitTool:
    """Test-only adapter for the frozen canonical Predicate polling semantics."""

    def __init__(
        self,
        *,
        adapter: BrowserPerceptionAdapter,
        backend: _SequenceBackend | None,
        session_id_getter: Any,
    ) -> None:
        self._waiter = BrowserPredicateWaiter(adapter=adapter, backend=backend)
        self._session_id_getter = session_id_getter

    def execute(self, **kwargs: Any):
        assert kwargs.pop("action", None) == "wait"
        predicate = kwargs.get("predicate")
        assert isinstance(predicate, dict)
        return self._waiter.wait(
            str(self._session_id_getter() or ""),
            predicate=predicate,
            timeout_ms=kwargs.get("timeout_ms"),
            interval_ms=kwargs.get("interval_ms"),
            tool_name="browser_wait_canonical_test",
        )


def test_model_surface_aggregates_wait_while_typed_primitives_remain_closed(tmp_path: Path) -> None:
    tool = BrowserPerceiveTool(
        adapter=_adapter(tmp_path),
        backend=None,
        session_id_getter=lambda: "s1",
    )
    props = tool.parameters["properties"]
    assert props["action"]["enum"] == ["snapshot", "hydrate", "diff", "wait"]
    # v02-20260920 合并面：URL-role 分离改 url→expected_url；
    # grounding-ref 统一后对象等待引用统一为 grounding_ref（原 object_ref 退出）。
    assert set(props) == {
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
        "expected_url",
        "value",
        "field",
        "text",
        "within_ms",
    }
    assert "condition" not in props
    assert "interval_ms" not in props

    scope = BrowserWaitScopeTool.parameters
    obj = BrowserWaitObjectTool.parameters
    assert set(scope["properties"]["property"]["enum"]) == {
        name for name, spec in PREDICATE_SPECS.items() if spec["target_kind"] == "scope"
    }
    assert set(obj["properties"]["property"]["enum"]) == {
        name for name, spec in PREDICATE_SPECS.items() if spec["target_kind"] == "semantic_object"
    }


def test_wait_first_call_contract_survives_perceive_facade_and_typed_internals(tmp_path: Path) -> None:
    from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS, ToolRegistry

    perceive_props = BrowserPerceiveTool.parameters["properties"]
    assert "wait" in perceive_props["action"]["enum"]
    assert "interval_ms" not in perceive_props
    assert "target=scope_ref" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_scope"]
    assert "GroundingRef" in _COMPACT_TOOL_DESCRIPTIONS["browser_wait_object"]

    adapter = _adapter(tmp_path)
    reg = ToolRegistry()
    reg.register(BrowserWaitScopeTool(adapter=adapter, backend=None, session_id_getter=lambda: "s1"))
    reg.register(BrowserWaitObjectTool(adapter=adapter, backend=None, session_id_getter=lambda: "s1"))
    lazy = {row["name"]: row for row in reg.schemas(lazy=True)}
    assert lazy["browser_wait_scope"]["parameters"]["properties"]["interval_ms"] == {
        "type": "integer", "minimum": 1, "maximum": 5000
    }
    assert lazy["browser_wait_object"]["parameters"]["properties"]["interval_ms"] == {
        "type": "integer", "minimum": 1, "maximum": 5000
    }

def test_runtime_predicate_vocabulary_matches_frozen_bspec_profile_and_schema() -> None:
    expected = PROFILE["predicate_vocabulary"]["properties"]
    runtime = {
        name: {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in spec.items()
            if key != "target_kind"
        }
        for name, spec in PREDICATE_SPECS.items()
    }

    assert runtime == expected
    provider = predicate_parameter_schema()
    assert provider["additionalProperties"] is False
    assert set(provider["properties"]["property"]["enum"]) == set(expected)

    example = _predicate(
        scope_ref="browser-document-scope:0123456789abcdef01234567",
        target="el_0123456789abcdef0123",
        property_name="enabled",
        operator="eq",
        value=True,
    )
    assert _bspec_errors(example, "predicate") == []


def test_predicate_runtime_rejects_unknown_or_mistyped_contract_before_capture(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    backend = _SequenceBackend([FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )
    invalid = _predicate(
        scope_ref="scope:any",
        target="el_deadbeef",
        property_name="enabled",
        operator="contains",
        value="yes",
    )

    result = tool.execute(action="wait", predicate=invalid, timeout_ms=10, interval_ms=1)

    assert result.status.value == "failure"
    assert backend.calls == 0
    assert "operator" in result.content.lower() or "value" in result.content.lower()


def test_integer_predicate_does_not_accept_boolean_value(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    backend = _SequenceBackend([FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )
    invalid = _predicate(
        scope_ref="scope:any",
        target="scope:any",
        property_name="object_count",
        operator="ge",
        value=True,
    )

    result = tool.execute(action="wait", predicate=invalid, timeout_ms=10, interval_ms=1)

    assert result.status.value == "failure"
    assert backend.calls == 0
    assert "integer" in result.content.lower()


def test_grounded_boolean_predicate_is_three_state_mechanical(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(snap, "Submit")
    predicate_true = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    predicate_false = {**predicate_true, "value": False}

    yes = adapter.evaluate_predicate("s1", _snapshot_id(snap), predicate_true)
    no = adapter.evaluate_predicate("s1", _snapshot_id(snap), predicate_false)

    assert yes["result"] == "satisfied"
    assert yes["observed_value"] is True
    assert yes["reason"] is None
    assert no["result"] == "unsatisfied"
    assert no["observed_value"] is True


def test_missing_stable_object_can_prove_absence_only_with_complete_coverage(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(before, "Submit")
    complete_after = adapter.snapshot("s1", _without_submit_fixture())
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="exists",
        operator="eq",
        value=False,
    )

    complete = adapter.evaluate_predicate("s1", _snapshot_id(complete_after), predicate)
    partial_after = adapter.snapshot("s1", _without_submit_fixture(truncated=True))
    partial = adapter.evaluate_predicate("s1", _snapshot_id(partial_after), predicate)

    assert complete["result"] == "satisfied"
    assert complete["observed_value"] is False
    assert complete["coverage_complete"] is True
    assert partial["result"] == "indeterminate"
    assert partial["observed_value"] is None
    assert partial["coverage_complete"] is False
    assert "coverage" in str(partial["reason"])


def test_invented_or_snapshot_local_identity_never_turns_into_false_absence(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    first = adapter.snapshot("s1", _with_snapshot_local_ax_object())
    local = [
        obj
        for obj in first["objects"]
        if obj["attributes"].get("name") == "Local only"
    ]
    assert len(local) == 1
    second = adapter.snapshot("s1", _with_snapshot_local_ax_object())

    local_predicate = _predicate(
        scope_ref=local[0]["scope_ref"],
        target=local[0]["id"],
        property_name="exists",
        operator="eq",
        value=False,
    )
    invented_predicate = {**local_predicate, "target": "el_00000000000000000000"}

    local_result = adapter.evaluate_predicate("s1", _snapshot_id(second), local_predicate)
    invented = adapter.evaluate_predicate("s1", _snapshot_id(second), invented_predicate)

    assert local_result["result"] == "indeterminate"
    assert "identity_unstable" in str(local_result["reason"])
    assert invented["result"] == "indeterminate"
    assert "identity_unknown" in str(invented["reason"])


def test_unobserved_object_field_is_indeterminate_not_false(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(snap, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="focused",
        operator="eq",
        value=True,
    )

    result = adapter.evaluate_predicate("s1", _snapshot_id(snap), predicate)

    assert result["result"] == "indeterminate"
    assert result["observed_value"] is None
    assert result["reason"] == "property_unobserved"


def test_predicate_scope_is_a_hard_observation_boundary(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(before, "Submit")
    after = adapter.snapshot("s1", FIXTURES["navigate"])
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="exists",
        operator="eq",
        value=False,
    )

    result = adapter.evaluate_predicate("s1", _snapshot_id(after), predicate)

    assert result["result"] == "indeterminate"
    assert result["reason"] == "scope_not_observed"


def test_scope_url_and_optional_ready_state_use_only_captured_mechanical_facts(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    raw = deepcopy(FIXTURES["base"])
    raw["document_ready_state"] = "complete"
    snap = adapter.snapshot("s1", raw)
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]

    url_predicate = _predicate(
        scope_ref=scope_ref,
        target=scope_ref,
        property_name="url",
        operator="contains",
        value="/a",
    )
    ready_predicate = _predicate(
        scope_ref=scope_ref,
        target=scope_ref,
        property_name="document_ready_state",
        operator="eq",
        value="complete",
    )

    url_result = adapter.evaluate_predicate("s1", _snapshot_id(snap), url_predicate)
    ready_result = adapter.evaluate_predicate("s1", _snapshot_id(snap), ready_predicate)

    assert url_result["result"] == "satisfied"
    assert url_result["observed_value"] == "https://example.test/a"
    assert ready_result["result"] == "satisfied"
    assert ready_result["observed_value"] == "complete"


def test_unobserved_document_ready_state_is_indeterminate(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]
    predicate = _predicate(
        scope_ref=scope_ref,
        target=scope_ref,
        property_name="document_ready_state",
        operator="eq",
        value="complete",
    )

    result = adapter.evaluate_predicate("s1", _snapshot_id(snap), predicate)

    assert result["result"] == "indeterminate"
    assert result["reason"] == "property_unobserved"


def test_object_count_uses_lower_bound_logic_under_incomplete_coverage(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    raw = deepcopy(FIXTURES["base"])
    raw["dom"]["truncated"] = True
    snap = adapter.snapshot("s1", raw)
    scope_ref = snap["snapshot"]["scope"]["scope_ref"]
    at_least_one = _predicate(
        scope_ref=scope_ref,
        target=scope_ref,
        property_name="object_count",
        operator="ge",
        value=1,
    )
    at_most_many = {**at_least_one, "operator": "le", "value": 999}

    positive = adapter.evaluate_predicate("s1", _snapshot_id(snap), at_least_one)
    unknown = adapter.evaluate_predicate("s1", _snapshot_id(snap), at_most_many)

    assert positive["result"] == "satisfied"
    assert positive["coverage_complete"] is False
    assert isinstance(positive["observed_value"], int)
    assert unknown["result"] == "indeterminate"
    assert "coverage" in str(unknown["reason"])


def test_wait_polls_observation_until_satisfied_and_returns_bspec_predicate_result(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", _disabled_submit_fixture())
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    backend = _SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=100, interval_ms=1)

    assert result.status.value == "success"
    payload = json.loads(result.content)
    predicate_result = payload["predicate_result"]
    assert _bspec_errors(predicate_result, "predicate_result") == []
    assert predicate_result["result"] == "satisfied"
    assert predicate_result["evaluation_mode"] == "polling"
    assert predicate_result["sample_count"] >= 2
    assert predicate_result["observer_error_count"] == 0
    assert predicate_result["interval_ms"] == 1
    assert predicate_result["deadline"] is not None
    assert payload["observation"]["snapshot_id"]
    assert "action_id" not in payload
    assert "receipt_id" not in payload


def test_wait_timeout_unsatisfied_is_successful_observation_not_tool_failure(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="name",
        operator="eq",
        value="Never this name",
    )
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=_SequenceBackend([FIXTURES["base"]]),
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=3, interval_ms=1)

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "unsatisfied"
    assert payload["predicate_result"]["evaluation_mode"] == "polling"
    assert payload["predicate_result"]["sample_count"] >= 1


def test_wait_observer_error_is_counted_and_later_valid_sample_can_recover(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    backend = _SequenceBackend([RuntimeError("synthetic observer outage"), FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=100, interval_ms=1)

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate_result"]["observer_error_count"] == 1
    assert payload["predicate_result"]["sample_count"] >= 2


def test_wait_with_only_observer_failures_returns_indeterminate_not_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    backend = _SequenceBackend([RuntimeError("synthetic observer outage")])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=3, interval_ms=1)

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "indeterminate"
    assert payload["predicate_result"]["observer_error_count"] >= 1
    assert payload["observation"]["reason"] == "observer_error"


def test_wait_requires_readonly_backend_and_never_falls_back_to_mutation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=None,
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=100, interval_ms=10)

    assert result.status.value == "failure"
    assert "backend" in result.content.lower()
    assert "fallback" in result.content.lower() or "未执行" in result.content


def test_wait_bounds_are_rejected_not_silently_clamped(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", FIXTURES["base"])
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    backend = _SequenceBackend([FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )

    too_long = tool.execute(
        action="wait", predicate=predicate, timeout_ms=60_001, interval_ms=1
    )
    too_sparse = tool.execute(
        action="wait", predicate=predicate, timeout_ms=10, interval_ms=5_001
    )

    assert too_long.status.value == "failure"
    assert too_sparse.status.value == "failure"
    assert backend.calls == 0


def test_wait_never_starts_a_poll_sample_at_or_after_deadline(
    tmp_path: Path, monkeypatch: Any
) -> None:
    adapter = _adapter(tmp_path)
    seed = adapter.snapshot("s1", _disabled_submit_fixture())
    submit = _dom_object_named(seed, "Submit")
    predicate = _predicate(
        scope_ref=submit["scope_ref"],
        target=submit["id"],
        property_name="enabled",
        operator="eq",
        value=True,
    )
    backend = _SequenceBackend([_disabled_submit_fixture(), FIXTURES["base"]])
    tool = _CanonicalWaitTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )
    clock = {"now": 0.0}

    monkeypatch.setattr(browser_wait_module.time, "monotonic", lambda: clock["now"])

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(browser_wait_module.time, "sleep", fake_sleep)

    result = tool.execute(action="wait", predicate=predicate, timeout_ms=10, interval_ms=10)

    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["predicate_result"]["result"] == "unsatisfied"
    assert payload["predicate_result"]["sample_count"] == 1
    assert backend.calls == 1
    assert clock["now"] == 0.01
