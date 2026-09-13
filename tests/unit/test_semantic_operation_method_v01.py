from __future__ import annotations

from pathlib import Path

from llm_loop.methods.store import MethodStore
from llm_loop.tools.builtin.browser_action import BrowserActionTool
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
        "Observe -> Ground -> Scope -> Act -> Receipt -> Re-observe/Verify",
        "object.id -> target_id",
        "object.scope_ref -> scope_ref",
        "snapshot.snapshot_id -> expected_version",
        "navigate",
        "version_scope=resource",
        "version_scope=object",
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


def test_browser_action_surfaces_point_to_method_without_inlining_it() -> None:
    compact = _COMPACT_TOOL_DESCRIPTIONS["browser_action"]
    full = BrowserActionTool.description
    assert METHOD_REF in compact
    assert METHOD_REF in full
    assert "search_records" in compact
    assert "search_records" in full
    # The provider-stable tool contract only carries the pointer, not the Method body.
    assert "Observe -> Ground" not in compact
    assert "Observe -> Ground" not in full


def test_semantic_operation_method_is_not_universal_prompt_injection() -> None:
    prompt_source = (ROOT / "src/llm_loop/core/prompt.py").read_text(encoding="utf-8")
    assert METHOD_REF not in prompt_source
