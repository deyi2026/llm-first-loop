from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "evals/smc_semantic_logic_p4_fcr_v02"
PROTOCOL_JSON = HERE / "PROTOCOL.v0.2-ACTIONREF.json"
PROTOCOL_PY = HERE / "protocol.py"
RUNNER = HERE / "run_fcr.py"
COMPILER = ROOT / "tools/semantic_logic/p4_fcr_v02_actionref_compiler.py"
FIXTURE_PATH = ROOT / "tests/fixtures/smc_browser_perception_v01.json"

FROZEN = json.loads(PROTOCOL_JSON.read_text(encoding="utf-8"))
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _protocol() -> dict[str, Any]:
    assert PROTOCOL_PY.is_file(), "v0.2 protocol.py is not implemented yet"
    return runpy.run_path(str(PROTOCOL_PY))


def _compiler() -> dict[str, Any]:
    assert COMPILER.is_file(), "v0.2 ActionRef compiler is not implemented yet"
    return runpy.run_path(str(COMPILER))


class _NoDispatchAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("P4-FCR v0.2 qualification must never dispatch")


def _stack(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
) -> tuple[BrowserPerceptionAdapter, _NoDispatchAdapter, BrowserSemanticExecuteTool]:
    clock = now if now is not None else [1_000.0]
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            tmp_path / "browser",
            retention_seconds=60,
            now_fn=lambda: clock[0],
        ),
        capture_node_cap=10_000,
    )
    action_adapter = _NoDispatchAdapter()
    semantic_execute = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action_adapter,  # type: ignore[arg-type]
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


def _binding(
    module: dict[str, Any],
    *,
    action_ref: str,
    grounding_ref: str,
    target_kind: str,
    semantic_object_id: str,
    observed_version: str = "v1",
    session_id: str = "s1",
) -> dict[str, Any]:
    unsigned = {
        "action_ref": action_ref,
        "target_kind": target_kind,
        "session_id": session_id,
        "domain": "browser",
        "scope_ref": "scope:test",
        "semantic_object_id": semantic_object_id,
        "observation_ref": "obs:test:1",
        "observed_version": observed_version,
        "authority_scope": "authority:test",
        "grounding_ref": grounding_ref,
        "issued_at": "2026-09-19T20:00:00Z",
        "expires_at": "2026-09-19T21:00:00Z",
    }
    return module["seal_action_ref_binding"](unsigned)


def _store(
    module: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    now: list[str] | None = None,
    versions: dict[str, str] | None = None,
    authority_scope: str = "authority:test",
) -> Any:
    logical_now = now if now is not None else ["2026-09-19T20:30:00Z"]
    current_versions = (
        versions
        if versions is not None
        else {str(row["semantic_object_id"]): str(row["observed_version"]) for row in records}
    )
    return module["ActionRefBindingStore"](
        records,
        now_fn=lambda: logical_now[0],
        version_getter=lambda semantic_object_id: current_versions.get(semantic_object_id),
        authority_scope_getter=lambda _session_id: authority_scope,
    )


def test_p4_fcr_v02_protocol_identity_is_fresh_and_bounded() -> None:
    assert FROZEN["schema"] == "smc.semantic_logic_p4_fcr_actionref_protocol.v0.2"
    assert FROZEN["parent_negative_git_sha"] == "52d5e78e650e1693db3453285febf36e8ab9cb68"
    assert FROZEN["p1_git_sha"] == "d0af187baa2819b76a6df31a962f3c0f0fa6c814"
    assert FROZEN["p11_git_sha"] == "5d11c5866e0e9349163577a1382b8469c32dca51"
    assert FROZEN["matrix"]["rows"] == 40
    assert FROZEN["pre_model_stop"] is True


def test_p4_fcr_v02_plan_keeps_exact_v01_40_row_rotation() -> None:
    module = _protocol()
    plan = module["build_plan"]()
    assert len(plan) == 40
    assert [row["index"] for row in plan] == list(range(1, 41))
    assert sum(row["arm"] == "A" for row in plan) == 20
    assert sum(row["arm"] == "B" for row in plan) == 20
    assert module["TASK_ROTATION"] == {
        1: ("navigate", "click", "fill", "select", "scroll"),
        2: ("click", "fill", "select", "scroll", "navigate"),
        3: ("fill", "select", "scroll", "navigate", "click"),
        4: ("select", "scroll", "navigate", "click", "fill"),
    }
    assert module["ARM_ORDER"] == {
        1: ("A", "B"),
        2: ("B", "A"),
        3: ("A", "B"),
        4: ("B", "A"),
    }


def test_p4_fcr_v02_pair_prompts_expose_both_refs_byte_identically() -> None:
    module = _protocol()
    plan = module["build_plan"]()
    for block in range(20):
        left, right = plan[block * 2 : block * 2 + 2]
        assert left["prompt_sha256"] == right["prompt_sha256"]
        task = module["TASKS"][left["task_id"]]
        binding = module["ACTION_REF_BINDINGS"][left["task_id"]]
        assert binding["grounding_ref"] in task.prompt
        assert binding["action_ref"] in task.prompt


def test_p4_fcr_v02_arm_b_surface_uses_only_action_ref_for_target_identity() -> None:
    module = _protocol()
    assert set(module["ARM_B_TOOLS"]) == {
        "browser_semantic_click",
        "browser_semantic_fill",
        "browser_semantic_select",
        "browser_semantic_scroll",
        "browser_semantic_navigate",
    }
    for name, spec in module["ARM_B_TOOLS"].items():
        params = spec["parameters"]
        assert "action_ref" in params["properties"], name
        assert "action_ref" in params["required"], name
        assert "object_ref" not in params["properties"], name
        assert "resource_ref" not in params["properties"], name
        assert params["additionalProperties"] is False


def test_p4_fcr_v02_frozen_handles_are_short_unique_and_semantically_opaque() -> None:
    module = _protocol()
    handles = [row["action_ref"] for row in module["ACTION_REF_BINDINGS"].values()]
    assert handles == ["ar_5f8c2a", "ar_a17d93", "ar_c42e11", "ar_7b31f0", "ar_d9054c"]
    assert len(handles) == len(set(handles))
    for handle in handles:
        assert len(handle) == 9
        lowered = handle.lower()
        for semantic_word in ("click", "fill", "select", "scroll", "navigate", "page", "object"):
            assert semantic_word not in lowered


def test_p4_fcr_v02_frozen_binding_records_are_integrity_valid_and_exact() -> None:
    module = _protocol()
    expected = {
        "navigate": (module["RESOURCE_REF"], "resource"),
        "click": (module["OBJECT_REFS"]["click"], "object"),
        "fill": (module["OBJECT_REFS"]["fill"], "object"),
        "select": (module["OBJECT_REFS"]["select"], "object"),
        "scroll": (module["OBJECT_REFS"]["scroll"], "object"),
    }
    for task_id, binding in module["ACTION_REF_BINDINGS"].items():
        grounding_ref, target_kind = expected[task_id]
        assert module["action_ref_binding_integrity_ok"](binding) is True
        assert binding["grounding_ref"] == grounding_ref
        assert binding["target_kind"] == target_kind
        assert binding["observed_version"] == "p4fcr-v02-v1"
        assert binding["session_id"] == "p4fcr-v02-session"
        assert binding["authority_scope"] == "authority:p4fcr-v02"


def test_p4_fcr_v02_good_raw_declarations_score_exact_without_hydration() -> None:
    module = _protocol()
    score = module["score_first_response"]
    for task_id, task in module["TASKS"].items():
        a = score(
            task_id=task_id,
            arm="A",
            calls=[{"name": "browser_semantic_execute", "arguments": task.expected_a}],
        )
        b = score(
            task_id=task_id,
            arm="B",
            calls=[{"name": task.expected_b_tool, "arguments": task.expected_b_args}],
        )
        assert a["first_call_structural_valid"] is True
        assert a["first_call_mechanical_valid"] is True
        assert a["cross_binding_errors"] == []
        assert b["first_call_structural_valid"] is True
        assert b["first_call_mechanical_valid"] is True
        assert b["cross_binding_errors"] == []


def test_p4_fcr_v02_scorer_rejects_wrong_or_grounding_ref_in_action_ref_field() -> None:
    module = _protocol()
    task = module["TASKS"]["select"]
    wrong_handle = module["ACTION_REF_BINDINGS"]["click"]["action_ref"]
    wrong = module["score_first_response"](
        task_id="select",
        arm="B",
        calls=[
            {
                "name": "browser_semantic_select",
                "arguments": {"action_ref": wrong_handle, "value": "beta"},
            }
        ],
    )
    full_grounding = module["score_first_response"](
        task_id="select",
        arm="B",
        calls=[
            {
                "name": "browser_semantic_select",
                "arguments": {
                    "action_ref": module["ACTION_REF_BINDINGS"]["select"]["grounding_ref"],
                    "value": "beta",
                },
            }
        ],
    )
    assert task.expected_b_args["action_ref"] == "ar_7b31f0"
    assert "P4-X06" in wrong["cross_binding_errors"]
    assert "P4-X06" in full_grounding["cross_binding_errors"]
    assert wrong["first_call_mechanical_valid"] is False
    assert full_grounding["first_call_mechanical_valid"] is False


@pytest.mark.parametrize(
    ("tool_name", "request_builder", "expected_builder", "kind"),
    [
        (
            "browser_semantic_click",
            lambda action_ref: {"action_ref": action_ref},
            lambda target_ref: {"verb": "click", "target_ref": target_ref, "args": {}},
            "object",
        ),
        (
            "browser_semantic_fill",
            lambda action_ref: {
                "action_ref": action_ref,
                "text": "AB-7319",
                "mode": "replace",
            },
            lambda target_ref: {
                "verb": "fill",
                "target_ref": target_ref,
                "args": {"text": "AB-7319", "mode": "replace"},
            },
            "object",
        ),
        (
            "browser_semantic_select",
            lambda action_ref: {"action_ref": action_ref, "value": "beta"},
            lambda target_ref: {
                "verb": "select",
                "target_ref": target_ref,
                "args": {"value": "beta"},
            },
            "object",
        ),
        (
            "browser_semantic_scroll",
            lambda action_ref: {"action_ref": action_ref, "delta_pages": 1.5},
            lambda target_ref: {
                "verb": "scroll",
                "target_ref": target_ref,
                "args": {"delta_pages": 1.5},
            },
            "object",
        ),
        (
            "browser_semantic_navigate",
            lambda action_ref: {
                "action_ref": action_ref,
                "url": "http://127.0.0.1/example",
            },
            lambda target_ref: {
                "verb": "navigate",
                "target_ref": target_ref,
                "args": {"url": "http://127.0.0.1/example"},
            },
            "resource",
        ),
    ],
)
def test_p4_fcr_v02_actionref_hydration_compile_matches_arm_a(
    tmp_path: Path,
    tool_name: str,
    request_builder: Any,
    expected_builder: Any,
    kind: str,
) -> None:
    module = _compiler()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, resource_ref = _snapshot_refs(perception)
    target_ref = resource_ref if kind == "resource" else object_ref
    record = _binding(
        module,
        action_ref="ar_test01",
        grounding_ref=target_ref,
        target_kind=kind,
        semantic_object_id="semantic-test-1",
    )
    store = _store(module, [record])
    compiler = module["P4ActionRefCompiler"](arm_a, store)

    expected = arm_a.compile_request("s1", expected_builder(target_ref))
    actual = compiler.compile("s1", tool_name, request_builder("ar_test01"))

    assert actual == expected
    assert action_adapter.calls == 0


def test_p4_fcr_v02_actionref_store_rejects_unknown_cross_session_stale_expired_tampered_and_wrong_kind(
    tmp_path: Path,
) -> None:
    module = _compiler()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, resource_ref = _snapshot_refs(perception)
    object_record = _binding(
        module,
        action_ref="ar_obj001",
        grounding_ref=object_ref,
        target_kind="object",
        semantic_object_id="obj-1",
    )
    resource_record = _binding(
        module,
        action_ref="ar_res001",
        grounding_ref=resource_ref,
        target_kind="resource",
        semantic_object_id="res-1",
    )
    now = ["2026-09-19T20:30:00Z"]
    versions = {"obj-1": "v1", "res-1": "v1"}
    store = _store(module, [object_record, resource_record], now=now, versions=versions)
    compiler = module["P4ActionRefCompiler"](arm_a, store)
    error = module["P4ActionRefError"]

    with pytest.raises(error, match="action_ref_unavailable"):
        compiler.compile("s1", "browser_semantic_click", {"action_ref": "ar_missing"})
    with pytest.raises(error, match="action_ref_unauthorized"):
        compiler.compile("s2", "browser_semantic_click", {"action_ref": "ar_obj001"})
    wrong_authority_store = _store(
        module,
        [object_record, resource_record],
        now=now,
        versions=versions,
        authority_scope="authority:other",
    )
    wrong_authority_compiler = module["P4ActionRefCompiler"](arm_a, wrong_authority_store)
    with pytest.raises(error, match="action_ref_unauthorized"):
        wrong_authority_compiler.compile(
            "s1", "browser_semantic_click", {"action_ref": "ar_obj001"}
        )
    versions["obj-1"] = "v2"
    with pytest.raises(error, match="action_ref_stale"):
        compiler.compile("s1", "browser_semantic_click", {"action_ref": "ar_obj001"})
    versions["obj-1"] = "v1"
    now[0] = "2026-09-19T21:00:01Z"
    with pytest.raises(error, match="action_ref_expired"):
        compiler.compile("s1", "browser_semantic_click", {"action_ref": "ar_obj001"})
    now[0] = "2026-09-19T20:30:00Z"
    tampered = copy.deepcopy(object_record)
    tampered["grounding_ref"] = resource_ref
    tampered_store = _store(module, [tampered], now=now, versions=versions)
    tampered_compiler = module["P4ActionRefCompiler"](arm_a, tampered_store)
    with pytest.raises(error, match="action_ref_integrity_error"):
        tampered_compiler.compile("s1", "browser_semantic_click", {"action_ref": "ar_obj001"})
    with pytest.raises(error, match="action_ref_kind_mismatch"):
        compiler.compile("s1", "browser_semantic_click", {"action_ref": "ar_res001"})
    with pytest.raises(error, match="action_ref_kind_mismatch"):
        compiler.compile(
            "s1",
            "browser_semantic_navigate",
            {"action_ref": "ar_obj001", "url": "http://127.0.0.1/example"},
        )
    assert action_adapter.calls == 0


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("browser_semantic_click", {"action_ref": "ar_x", "extra": "x"}),
        ("browser_semantic_click", {"action_ref": 1}),
        ("browser_semantic_fill", {"action_ref": "ar_x", "text": "x"}),
        (
            "browser_semantic_fill",
            {"action_ref": "ar_x", "text": "x", "mode": "overwrite"},
        ),
        ("browser_semantic_select", {"action_ref": "ar_x", "value": 1}),
        ("browser_semantic_scroll", {"action_ref": "ar_x", "delta_pages": True}),
        ("browser_semantic_navigate", {"action_ref": "ar_x", "url": ""}),
        ("browser_semantic_click", {"object_ref": "grounding://old-shape"}),
    ],
)
def test_p4_fcr_v02_typed_surface_fails_closed_on_malformed_or_old_shapes(
    tmp_path: Path,
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    module = _compiler()
    _, action_adapter, arm_a = _stack(tmp_path)
    store = _store(module, [])
    compiler = module["P4ActionRefCompiler"](arm_a, store)
    with pytest.raises(module["P4ActionRefError"]):
        compiler.compile("s1", tool_name, payload)
    assert action_adapter.calls == 0


def test_p4_fcr_v02_same_actionref_request_has_deterministic_action_id(tmp_path: Path) -> None:
    module = _compiler()
    perception, action_adapter, arm_a = _stack(tmp_path)
    object_ref, _ = _snapshot_refs(perception)
    record = _binding(
        module,
        action_ref="ar_same01",
        grounding_ref=object_ref,
        target_kind="object",
        semantic_object_id="obj-same",
    )
    store = _store(module, [record])
    compiler = module["P4ActionRefCompiler"](arm_a, store)
    request = {"action_ref": "ar_same01", "text": "same", "mode": "append"}
    first = compiler.compile("s1", "browser_semantic_fill", request)
    second = compiler.compile("s1", "browser_semantic_fill", request)
    assert first == second
    assert first["action_id"] == second["action_id"]
    assert action_adapter.calls == 0


def test_p4_fcr_v02_runner_has_zero_model_preflight_and_no_browser_execution() -> None:
    assert RUNNER.is_file(), "v0.2 run_fcr.py is not implemented yet"
    source = RUNNER.read_text(encoding="utf-8")
    assert "if args.preflight:" in source
    assert source.index("if args.preflight:") < source.index("run_row(row, manifest)")
    assert '"model_requests": 0' in source
    assert '"tool_execution_total": 0' in source
    assert "BrowserActionAdapter" not in source
    assert "execute_request(" not in source
    assert "Factory" not in source


def test_p4_fcr_v02_has_no_production_wiring() -> None:
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    assert "smc_semantic_logic_p4_fcr_v02" not in factory
    assert "p4_fcr_v02_actionref_compiler" not in factory
    for name in FROZEN["arm_b"]["tools"]:
        assert name not in factory
