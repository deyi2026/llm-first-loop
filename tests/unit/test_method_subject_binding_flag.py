from __future__ import annotations

from llm_loop.introspection import registry_experience as registry
from llm_loop.factory import _CorrectionAdapterTool
from llm_loop.tools.registry import ToolRegistry


def _by_name() -> dict[str, dict]:
    return {str(row["name"]): row for row in registry.tool_defs()}


def test_subject_binding_flag_default_off_is_exact_noop(monkeypatch) -> None:
    monkeypatch.delenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, raising=False)
    save = _by_name()["save_experience"]
    assert save is registry._SAVE_EXPERIENCE_TOOL_DEF
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in save["description"]
    assert "compact_description" not in save


def test_subject_binding_flag_on_appends_once_without_mutating_global(monkeypatch) -> None:
    monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, "1")
    first = _by_name()["save_experience"]
    second = _by_name()["save_experience"]
    assert first is not registry._SAVE_EXPERIENCE_TOOL_DEF
    assert second is not registry._SAVE_EXPERIENCE_TOOL_DEF
    assert first["description"] == second["description"]
    assert first["description"].count(registry.METHOD_SUBJECT_BINDING_SCHEMA) == 2
    assert "claim subject" in first["description"]
    assert "result/output" in first["description"]
    assert "不得仅为本提示新增搜索、取证或工具调用" in first["description"]
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA in first["compact_description"]
    assert "claim subject" in first["compact_description"]
    assert "experience/result/fixture" in first["compact_description"]
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in registry._SAVE_EXPERIENCE_TOOL_DEF["description"]


def test_subject_binding_flag_truthy_values(monkeypatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, value)
        assert registry.METHOD_SUBJECT_BINDING_SCHEMA in _by_name()["save_experience"]["description"]


def test_subject_binding_flag_other_values_off(monkeypatch) -> None:
    for value in ("", "0", "false", "off", "no", "unexpected"):
        monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, value)
        assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in _by_name()["save_experience"]["description"]


def test_subject_binding_flag_reaches_lazy_provider_schema(monkeypatch) -> None:
    monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, "1")
    td = _by_name()["save_experience"]
    tool = _CorrectionAdapterTool(
        None,
        name=td["name"],
        description=td["description"],
        parameters=td["parameters"],
        compact_description=td.get("compact_description"),
    )
    tools = ToolRegistry()
    tools.register(tool)
    lazy = tools.schemas(lazy=True)
    assert len(lazy) == 1
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA in lazy[0]["description"]
    assert "claim subject" in lazy[0]["description"]
