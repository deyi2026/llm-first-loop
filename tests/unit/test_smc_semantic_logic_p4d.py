from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import (
    BrowserSemanticExecuteCompileError,
    BrowserSemanticExecuteTool,
)

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "docs/SMC-SEMANTIC-LOGIC-P4-AB-PROTOCOL-v0.1.json"
QUALIFICATION_PATH = ROOT / "tools/semantic_logic/p4d_typed_compiler.py"
FIXTURE_PATH = ROOT / "tests/fixtures/smc_browser_perception_v01.json"

PROTOCOL = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _qualification() -> dict[str, Any]:
    assert QUALIFICATION_PATH.is_file(), "P4-D typed compiler helper is not implemented yet"
    return runpy.run_path(str(QUALIFICATION_PATH))


class _NoDispatchAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("P4-D compile-only harness must never dispatch")


def _adapter(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
    retention_seconds: int = 60,
) -> BrowserPerceptionAdapter:
    clock = now if now is not None else [1_000.0]
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            tmp_path / "browser",
            retention_seconds=retention_seconds,
            now_fn=lambda: clock[0],
        ),
        capture_node_cap=10_000,
    )


def _stack(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
    retention_seconds: int = 60,
) -> tuple[BrowserPerceptionAdapter, _NoDispatchAdapter, BrowserSemanticExecuteTool]:
    perception = _adapter(
        tmp_path,
        now=now,
        retention_seconds=retention_seconds,
    )
    action_adapter = _NoDispatchAdapter()
    semantic_execute = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action_adapter,  # type: ignore[arg-type] - compile-only qualification path
        session_id_getter=lambda: "s1",
    )
    return perception, action_adapter, semantic_execute


def _snapshot_refs(perception: BrowserPerceptionAdapter) -> tuple[str, str]:
    snapshot = perception.snapshot("s1", FIXTURES["base"])
    object_ref = next(
        str(obj["grounding_ref"])
        for obj in snapshot["objects"]
        if isinstance(obj, dict) and obj.get("grounding_ref")
    )
    return object_ref, str(snapshot["resource_ref"])


def test_p4d_protocol_is_frozen_before_helper_implementation() -> None:
    assert PROTOCOL["schema"] == "smc.semantic_logic_p4_ab_protocol.v0.1"
    assert PROTOCOL["status"] == "FROZEN_PROTOCOL_ONLY"
    stage = next(item for item in PROTOCOL["qualification_stages"] if item["id"] == "P4-D")
    assert stage == {
        "id": "P4-D",
        "name": "deterministic compiler equivalence",
        "model_calls": False,
        "browser_physical_mutation": False,
        "requirements": [
            "positive compile parity for click/fill/select/scroll/navigate",
            "exact equality of authority-bearing SemanticAction fields against Arm A compile_request",
            "wrong-kind object/resource ref rejects",
            "expired/unauthorized/cross-session refs reject",
            "no dispatch occurs for any compile rejection",
            "same declared request produces deterministic action_id",
        ],
        "gate": "100% deterministic PASS before any model FCR run",
    }


def test_p4d_typed_schema_is_exactly_the_frozen_arm_b_surface() -> None:
    module = _qualification()
    assert module["P4_TYPED_TOOL_SCHEMAS"] == PROTOCOL["arm_b"]["mutation_tools"]
    assert set(module["P4_TYPED_TOOL_SCHEMAS"]) == {
        "browser_semantic_click",
        "browser_semantic_fill",
        "browser_semantic_select",
        "browser_semantic_scroll",
        "browser_semantic_navigate",
    }


@pytest.mark.parametrize(
    ("tool_name", "typed_request", "a_request"),
    [
        (
            "browser_semantic_click",
            lambda object_ref, _resource_ref: {"object_ref": object_ref},
            lambda object_ref, _resource_ref: {
                "verb": "click",
                "target_ref": object_ref,
                "args": {},
            },
        ),
        (
            "browser_semantic_fill",
            lambda object_ref, _resource_ref: {
                "object_ref": object_ref,
                "text": "AB-7319",
                "mode": "replace",
            },
            lambda object_ref, _resource_ref: {
                "verb": "fill",
                "target_ref": object_ref,
                "args": {"text": "AB-7319", "mode": "replace"},
            },
        ),
        (
            "browser_semantic_select",
            lambda object_ref, _resource_ref: {"object_ref": object_ref, "value": "beta"},
            lambda object_ref, _resource_ref: {
                "verb": "select",
                "target_ref": object_ref,
                "args": {"value": "beta"},
            },
        ),
        (
            "browser_semantic_scroll",
            lambda object_ref, _resource_ref: {"object_ref": object_ref, "delta_pages": 1.5},
            lambda object_ref, _resource_ref: {
                "verb": "scroll",
                "target_ref": object_ref,
                "args": {"delta_pages": 1.5},
            },
        ),
        (
            "browser_semantic_navigate",
            lambda _object_ref, resource_ref: {
                "resource_ref": resource_ref,
                "url": "http://127.0.0.1/example",
            },
            lambda _object_ref, resource_ref: {
                "verb": "navigate",
                "target_ref": resource_ref,
                "args": {"url": "http://127.0.0.1/example"},
            },
        ),
    ],
)
def test_p4d_positive_compile_is_byte_semantic_equal_to_arm_a(
    tmp_path: Path,
    tool_name: str,
    typed_request: Any,
    a_request: Any,
) -> None:
    module = _qualification()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, resource_ref = _snapshot_refs(perception)
    compiler = module["P4TypedCompiler"](arm_a)

    expected = arm_a.compile_request("s1", a_request(object_ref, resource_ref))
    actual = compiler.compile("s1", tool_name, typed_request(object_ref, resource_ref))

    assert actual == expected
    assert action_adapter.calls == 0


def test_p4d_wrong_kind_refs_reject_without_dispatch(tmp_path: Path) -> None:
    module = _qualification()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, resource_ref = _snapshot_refs(perception)
    compiler = module["P4TypedCompiler"](arm_a)

    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_projection_mismatch"):
        compiler.compile("s1", "browser_semantic_click", {"object_ref": resource_ref})
    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_projection_mismatch"):
        compiler.compile(
            "s1",
            "browser_semantic_navigate",
            {"resource_ref": object_ref, "url": "http://127.0.0.1/example"},
        )
    assert action_adapter.calls == 0


def test_p4d_cross_session_and_malformed_refs_reject_without_dispatch(tmp_path: Path) -> None:
    module = _qualification()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, _ = _snapshot_refs(perception)
    compiler = module["P4TypedCompiler"](arm_a)

    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_unauthorized"):
        compiler.compile("s2", "browser_semantic_click", {"object_ref": object_ref})
    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_unavailable"):
        compiler.compile(
            "s1",
            "browser_semantic_navigate",
            {"resource_ref": "https://example.invalid/not-a-grounding-ref", "url": "https://example.invalid/"},
        )
    assert action_adapter.calls == 0


def test_p4d_expired_ref_rejects_without_refresh_rebind_or_dispatch(tmp_path: Path) -> None:
    module = _qualification()
    now = [1_000.0]
    perception, action_adapter, arm_a = _stack(
        tmp_path,
        now=now,
        retention_seconds=10,
    )
    object_ref, _ = _snapshot_refs(perception)
    compiler = module["P4TypedCompiler"](arm_a)
    now[0] = 1_011.0

    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_expired"):
        compiler.compile("s1", "browser_semantic_click", {"object_ref": object_ref})
    assert action_adapter.calls == 0


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("browser_semantic_click", {"object_ref": "ref", "args": {}}),
        ("browser_semantic_fill", {"object_ref": "ref", "text": "x"}),
        (
            "browser_semantic_fill",
            {"object_ref": "ref", "text": "x", "mode": "overwrite"},
        ),
        ("browser_semantic_select", {"object_ref": "ref", "value": 1}),
        ("browser_semantic_scroll", {"object_ref": "ref", "delta_pages": True}),
        ("browser_semantic_navigate", {"resource_ref": "ref", "url": ""}),
        ("browser_semantic_execute", {"verb": "click", "target_ref": "ref", "args": {}}),
    ],
)
def test_p4d_typed_surface_fails_closed_on_undeclared_or_cross_bound_shapes(
    tmp_path: Path,
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    module = _qualification()
    _, action_adapter, arm_a = _stack(tmp_path)
    compiler = module["P4TypedCompiler"](arm_a)
    with pytest.raises(module["P4TypedCompilerError"]):
        compiler.compile("s1", tool_name, payload)
    assert action_adapter.calls == 0


def test_p4d_same_typed_request_has_deterministic_action_id(tmp_path: Path) -> None:
    module = _qualification()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, _ = _snapshot_refs(perception)
    compiler = module["P4TypedCompiler"](arm_a)
    request = {"object_ref": object_ref, "text": "same", "mode": "append"}

    first = compiler.compile("s1", "browser_semantic_fill", request)
    second = compiler.compile("s1", "browser_semantic_fill", request)
    assert first == second
    assert first["action_id"] == second["action_id"]
    assert action_adapter.calls == 0


def test_p4d_helper_is_qualification_only_and_has_no_production_wiring() -> None:
    module = _qualification()
    del module
    source = QUALIFICATION_PATH.read_text(encoding="utf-8")
    forbidden = (
        "llm_loop.factory",
        "llm_loop.tools.registry",
        "BrowserActionAdapter",
        "register(",
        "automatic_retry",
        "task_complete",
        "goal_complete",
    )
    for marker in forbidden:
        assert marker not in source

    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    for tool_name in PROTOCOL["arm_b"]["mutation_tools"]:
        assert tool_name not in factory
    assert "p4d_typed_compiler" not in factory
