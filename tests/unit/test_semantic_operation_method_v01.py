from __future__ import annotations

from pathlib import Path

from llm_loop.methods.store import MethodStore
from llm_loop.tools.builtin.browser_action import BrowserActionTool
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

ROOT = Path(__file__).resolve().parents[2]
METHOD_REF = "method:method-semantic-operation"


def _method_body() -> str:
    record = MethodStore(ROOT / "methods").get(METHOD_REF)
    assert record is not None
    assert record.status == "active"
    return record.body


def test_semantic_operation_method_is_provider_agnostic_and_exactly_hydratable() -> None:
    store = MethodStore(ROOT / "methods")
    exact = store.list(METHOD_REF, 1)
    assert len(exact) == 1
    row = exact[0]
    assert row["key"] == METHOD_REF
    assert row["projection_complete"] is True
    assert row["task_applicability"] == "not_evaluated"
    lowered = str(row["body"]).lower()
    for provider_token in ("ornith", "qwen", "deepseek", "minimax", "glm-"):
        assert provider_token not in lowered


def test_semantic_operation_method_teaches_facts_not_target_policy() -> None:
    body = _method_body()
    for marker in (
        "Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify",
        "browser_semantic_execute",
        "target_ref",
        "SemanticObject.grounding_ref",
        "resource_ref",
        "工具内部",
        "target_id",
        "scope_ref",
        "expected_version",
        "version_scope",
        "action_id",
        "Commit",
        "expected_version_unavailable",
        "resource_scope_mismatch",
        "args_contract_mismatch",
        "document_generation_changed",
        "scope_changed",
        "ActionReceipt status=ok",
        "不等于任务完成",
        "模型选择",
    ):
        assert marker in body
    for forbidden_authority in (
        "自动选择目标",
        "自动重试直到成功",
        "程序自动 rebind",
        "receipt ok 即任务完成",
    ):
        assert forbidden_authority not in body


def test_browser_surfaces_keep_progressive_method_ref_without_forcing_perception_protocol() -> None:
    perceive_surfaces = (
        _COMPACT_TOOL_DESCRIPTIONS["browser_perceive"],
        BrowserPerceiveTool.description,
    )
    for surface in perceive_surfaces:
        assert METHOD_REF in surface
        assert "Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify" not in surface
        assert "browser_semantic_execute" not in surface

    legacy_execution_card_surfaces = (
        _COMPACT_TOOL_DESCRIPTIONS["browser_action"],
        BrowserActionTool.description,
        BrowserSemanticExecuteTool.description,
    )
    for surface in legacy_execution_card_surfaces:
        assert METHOD_REF in surface
        assert "Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify" in surface
        assert "receipt ok != task complete" in surface

    semantic_surface = _COMPACT_TOOL_DESCRIPTIONS["browser_semantic_execute"]
    for marker in ("snapshot", "GroundingRef", "resource_ref", "verb/args", "ActionReceipt"):
        assert marker in semantic_surface
    # Keep always-visible surfaces compact; detailed recovery remains progressive disclosure.
    for surface in (*perceive_surfaces, *legacy_execution_card_surfaces):
        assert "expected_version_unavailable" not in surface
        assert "resource_scope_mismatch" not in surface
        assert "args_contract_mismatch" not in surface


def test_semantic_operation_method_is_not_universal_prompt_injection() -> None:
    prompt_source = (ROOT / "src/llm_loop/core/prompt.py").read_text(encoding="utf-8")
    assert METHOD_REF not in prompt_source
