from __future__ import annotations

import inspect
from typing import Any
from unittest import mock

import pytest

import llm_loop.tools.builtin.browser_semantic_operation as operation_module
from llm_loop.config import Settings
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS, ToolRegistry


def _settings(tmp_path, **kwargs: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_api_key": "k",
        "llm_base_url": "https://x.invalid/v1",
        "llm_model": "m",
        "data_dir": str(tmp_path / "data"),
        "self_inspection_enabled": True,
        "extract_enabled": False,
    }
    values.update(kwargs)
    return Settings(**values)


def _operate_verbs() -> set[str]:
    params = BrowserSemanticOperationTool.parameters
    values: set[str] = set()
    for branch in params.get("oneOf") or []:
        props = branch.get("properties") or {}
        do = props.get("do") or {}
        values.update(str(value) for value in (do.get("enum") or []))
    return values


def test_mf5_3_2a_provider_visible_hand_has_peer_name() -> None:
    assert BrowserPerceiveTool.name == "browser_perceive"
    assert BrowserSemanticOperationTool.name == "browser_operate"


def test_mf5_3_2a_factory_exposes_exactly_one_eye_and_one_hand(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import llm_loop.factory as factory

    monkeypatch.setattr(factory, "CdpReadOnlyBrowserHost", mock.Mock(return_value=mock.Mock()))
    monkeypatch.setattr(factory, "CdpBrowserMutationActuator", mock.Mock(return_value=mock.Mock()))
    engine = factory.build_engine(
        _settings(
            tmp_path,
            browser_perception_cdp_url="http://127.0.0.1:9222",
            browser_perception_target_id="target-1",
            browser_action_enabled=True,
        )
    )
    names = {name for name in engine.registry.names() if name.startswith("browser_")}

    assert names == {"browser_perceive", "browser_operate"}
    assert "browser_semantic_operation" not in names
    assert engine.registry.get("browser_operate")._semantic_execute._action_adapter.actuator is not None


def test_mf5_3_2a_compact_surface_uses_same_peer_hand_identity() -> None:
    assert "browser_operate" in _COMPACT_TOOL_DESCRIPTIONS
    assert "browser_semantic_operation" not in _COMPACT_TOOL_DESCRIPTIONS
    description = _COMPACT_TOOL_DESCRIPTIONS["browser_operate"]
    assert "navigate" in description
    assert "browser_perceive" in description
    assert "wait" in description


def test_mf5_3_2a_authority_split_is_unchanged() -> None:
    perceive_actions = set(BrowserPerceiveTool.parameters["properties"]["action"]["enum"])
    operate_verbs = _operate_verbs()

    assert perceive_actions == {"snapshot", "hydrate", "diff", "wait"}
    assert "navigate" not in perceive_actions
    assert operate_verbs == {"navigate", "click", "set_text", "append_text", "select", "scroll"}
    assert "wait" not in operate_verbs


def test_mf5_3_2a_internal_receipt_schema_identity_stays_historical() -> None:
    source = inspect.getsource(operation_module)
    assert '"smc.browser_semantic_operation_full_receipt.v0.1"' in source
    assert '"smc.browser_semantic_operation_compact_receipt.v0.1"' in source


def test_mf5_3_2a_perceive_stable_prefix_does_not_depend_on_stale_method_ref() -> None:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    description = str(registry.schemas(lazy=True)[0]["description"])

    assert "method_ref=" not in description
    assert "browser_semantic_execute" not in description
