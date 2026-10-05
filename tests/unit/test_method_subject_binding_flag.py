from __future__ import annotations

from llm_loop.introspection import registry_experience as registry


def _by_name() -> dict[str, dict]:
    return {str(row["name"]): row for row in registry.tool_defs()}


def test_subject_binding_flag_default_off_is_exact_noop(monkeypatch) -> None:
    monkeypatch.delenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, raising=False)
    save = _by_name()["save_experience"]
    assert save is registry._SAVE_EXPERIENCE_TOOL_DEF
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in save["description"]


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
    assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in registry._SAVE_EXPERIENCE_TOOL_DEF["description"]


def test_subject_binding_flag_truthy_values(monkeypatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, value)
        assert registry.METHOD_SUBJECT_BINDING_SCHEMA in _by_name()["save_experience"]["description"]


def test_subject_binding_flag_other_values_off(monkeypatch) -> None:
    for value in ("", "0", "false", "off", "no", "unexpected"):
        monkeypatch.setenv(registry.METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, value)
        assert registry.METHOD_SUBJECT_BINDING_SCHEMA not in _by_name()["save_experience"]["description"]
