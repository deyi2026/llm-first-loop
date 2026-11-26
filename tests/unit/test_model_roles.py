from __future__ import annotations

import json

import pytest

from llm_loop.llm.model_roles import (
    model_roles_for_refresh,
    parse_model_roles,
    reviewer_models_configured,
    reviewer_models_for_refresh,
)
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec


def _registry(monkeypatch):
    monkeypatch.setenv("PRIMARY_KEY", "primary-test-key")
    monkeypatch.setenv("BACKUP_KEY", "backup-test-key")
    return ProviderRegistry(
        providers={
            "primary": ProviderSpec(
                id="primary",
                base_url="https://primary.invalid/v1",
                api_key_env="PRIMARY_KEY",
                models={"planner": ModelSpec(), "reviewer": ModelSpec()},
                default_model="planner",
            ),
            "backup": ProviderSpec(
                id="backup",
                base_url="https://backup.invalid/v1",
                api_key_env="BACKUP_KEY",
                models={"planner": ModelSpec(), "reviewer": ModelSpec()},
                default_model="planner",
            ),
        }
    )


def test_parse_model_roles_preserves_operator_order_and_rejects_ambiguous_shape():
    roles, error = parse_model_roles(
        json.dumps(
            {
                "planning": ["primary/planner", "backup/planner"],
                "reviewer": ["backup/reviewer"],
            }
        )
    )
    assert error == ""
    assert roles["planning"] == ("primary/planner", "backup/planner")
    assert (
        reviewer_models_configured(json.dumps({"reviewer": ["backup/reviewer"]}))
        == "backup/reviewer"
    )
    assert reviewer_models_configured("{}", "primary/reviewer") == "primary/reviewer"
    assert reviewer_models_configured("{}") == ""
    assert parse_model_roles("{bad")[1] == "model_roles_invalid_json"
    assert (
        parse_model_roles('{"planning":"primary/planner"}')[1] == "model_roles_invalid_candidates"
    )
    assert (
        parse_model_roles('{"planning":["primary/planner","primary/planner"]}')[1]
        == "model_roles_duplicate_candidate"
    )


def test_role_candidates_use_registry_and_skip_missing_or_uncredentialed_candidates(monkeypatch):
    registry = _registry(monkeypatch)
    pool = ModelClientPool(
        registry=registry,
        default_client=object(),  # type: ignore[arg-type]
        model_roles_raw=json.dumps(
            {
                "planning": [
                    "primary/planner",
                    "missing/model",
                    "backup/planner",
                ]
            }
        ),
    )
    assert pool.role_candidates("planning") == ["primary/planner", "backup/planner"]
    assert pool.role_candidates("reviewer") == []


def test_role_configuration_hot_reloads_atomically_and_invalid_update_is_rejected(monkeypatch):
    registry = _registry(monkeypatch)
    pool = ModelClientPool(
        registry=registry,
        default_client=object(),  # type: ignore[arg-type]
        model_roles_raw=json.dumps({"planning": ["primary/planner"]}),
    )
    before = pool.roles_generation()
    pool.replace_model_roles(json.dumps({"planning": ["backup/planner"]}))
    assert pool.roles_generation() == before + 1
    assert pool.role_candidates("planning") == ["backup/planner"]
    with pytest.raises(ValueError, match="model_roles_invalid_json"):
        pool.replace_model_roles("{")
    assert pool.role_candidates("planning") == ["backup/planner"]
    assert pool.roles_generation() == before + 1


def test_role_mapping_refresh_is_independent_of_registry_refresh(monkeypatch):
    registry = _registry(monkeypatch)
    pool = ModelClientPool(
        registry=registry,
        default_client=object(),  # type: ignore[arg-type]
        model_roles_raw=json.dumps({"execution": ["primary/planner"]}),
    )
    pool.replace_model_roles(json.dumps({"execution": ["backup/planner"]}))
    # The Provider Registry is unchanged; role candidate replacement is immediate.
    assert pool.registry_snapshot() is registry
    assert pool.role_candidates("execution") == ["backup/planner"]


def test_execution_role_is_live_fallback_policy_and_legacy_wins(monkeypatch):
    from types import SimpleNamespace

    pool = ModelClientPool(
        registry=_registry(monkeypatch),
        default_client=SimpleNamespace(provider="primary", model="planner"),  # type: ignore[arg-type]
        model_roles_raw=json.dumps({
            "execution": ["primary/planner", "backup/planner"],
            "reviewer": ["backup/reviewer"],
        }),
    )
    assert pool.fallback_candidates() == ["backup/planner"]
    pool.set_default_model("backup/planner")
    assert pool.fallback_candidates() == ["primary/planner"]
    pool.set_default_model("primary/planner")
    pool.replace_model_roles(json.dumps({"execution": ["primary/reviewer"]}))
    assert pool.fallback_candidates() == ["primary/reviewer"]
    pool.model_fallbacks_raw = "backup/planner"
    assert pool.fallback_candidates() == ["backup/planner"]


def test_managed_dotenv_refresh_overrides_stale_process_role_and_can_disable(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(path))
    stale = '{"execution":["primary/planner"]}'
    fresh = '{"execution":["backup/planner"]}'
    path.write_text(f"LFL_MODEL_ROLES='{fresh}'\n", encoding="utf-8")
    assert model_roles_for_refresh(stale) == fresh
    path.write_text("LFL_MODEL_ROLES=\n", encoding="utf-8")
    assert model_roles_for_refresh(stale) == ""
    path.write_text("# role removed\n", encoding="utf-8")
    assert model_roles_for_refresh(stale) == ""
    path.unlink()
    with pytest.raises(ValueError, match="model_roles_config_unreadable"):
        model_roles_for_refresh(stale)


def test_concurrent_role_replace_and_read_stays_generation_monotonic_and_torn_free(monkeypatch):
    """并发热更新 vs 读竞态：generation 单调、候选列表从不撕裂（半新半旧）。"""
    import threading

    registry = _registry(monkeypatch)
    pool = ModelClientPool(
        registry=registry,
        default_client=object(),  # type: ignore[arg-type]
        model_roles_raw=json.dumps({"planning": ["primary/planner"]}),
    )
    stop = threading.Event()
    writer_errors: list[str] = []
    reader_errors: list[str] = []

    def writer() -> None:
        flip = True
        while not stop.is_set():
            try:
                pool.replace_model_roles(
                    json.dumps(
                        {"planning": ["backup/planner"] if flip else ["primary/planner"]}
                    )
                )
                flip = not flip
            except Exception as exc:  # noqa: BLE001 — 记录而非中断，断言在主线程
                writer_errors.append(f"writer: {exc}")

    def reader() -> None:
        seen = 0
        while not stop.is_set():
            generation = pool.roles_generation()
            candidates = pool.role_candidates("planning")
            if candidates not in (["primary/planner"], ["backup/planner"]):
                reader_errors.append(f"torn read: {candidates!r}")
            if generation < seen:
                reader_errors.append(f"generation regressed: {seen}->{generation}")
            seen = generation

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    try:
        stop.wait(1.5)
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    assert not writer_errors, writer_errors
    assert not reader_errors, reader_errors
    assert pool.roles_generation() >= 1


def test_execution_role_hot_reload_never_touches_reviewer_resolution(monkeypatch):
    """execution 角色热更新不得波及 reviewer 解析（Reviewer 独立性断言）。

    replace_model_roles 是全量替换语义：同一批 JSON 里保留 reviewer 键时，
    execution 的变更不得改变 reviewer 解析；只发 execution 键时 reviewer 如实
    清空（全量语义如实，不是隐性丢失）。
    """
    registry = _registry(monkeypatch)
    pool = ModelClientPool(
        registry=registry,
        default_client=object(),  # type: ignore[arg-type]
        model_roles_raw=json.dumps(
            {"execution": ["primary/planner"], "reviewer": ["backup/reviewer"]}
        ),
    )
    reviewer_before = pool.role_candidates("reviewer")
    pool.replace_model_roles(
        json.dumps(
            {"execution": ["backup/planner"], "reviewer": ["backup/reviewer"]}
        )
    )
    assert pool.role_candidates("execution") == ["backup/planner"]
    assert pool.role_candidates("reviewer") == reviewer_before == ["backup/reviewer"]
    # 全量语义：键缺失的角色如实清空，无隐性残留。
    pool.replace_model_roles(json.dumps({"execution": ["primary/planner"]}))
    assert pool.role_candidates("execution") == ["primary/planner"]
    assert pool.role_candidates("reviewer") == []


def test_reviewer_refresh_prefers_legacy_dotenv_over_stale_process_copy(tmp_path, monkeypatch):
    """Legacy reviewer variable is re-read from the managed dotenv, not the startup copy."""
    path = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(path))
    roles = json.dumps({"reviewer": ["backup/reviewer"]})
    path.write_text("LFL_REVIEWER_MODELS='primary/reviewer'\n", encoding="utf-8")
    # The process still holds a stale legacy value; the file wins.
    assert reviewer_models_for_refresh(roles, "stale/model") == ("primary/reviewer", "")
    # Same precedence as the startup wiring (reviewer_models_configured).
    assert reviewer_models_for_refresh(roles, "primary/reviewer") == (
        reviewer_models_configured(roles, "primary/reviewer"), ""
    )
    # Legacy emptied in the file => the explicit reviewer role is used instead.
    path.write_text("LFL_REVIEWER_MODELS=\n", encoding="utf-8")
    assert reviewer_models_for_refresh(roles, "stale/model") == ("backup/reviewer", "")
    # Role mapping disabled (empty key) and legacy empty => authoritative "" = explicit revocation.
    assert reviewer_models_for_refresh("", "stale/model") == ("", "")
    # An empty roles object is invalid configuration (same rule as replace_model_roles),
    # so it is reported as a reason and never mistaken for a revocation.
    assert reviewer_models_for_refresh("{}", "") == ("", "model_roles_invalid_shape")


def test_reviewer_refresh_keeps_policy_when_roles_are_invalid_or_unreadable(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(path))
    path.write_text("# legacy key removed\n", encoding="utf-8")
    # An invalid role mapping must never be mistaken for a revocation.
    assert reviewer_models_for_refresh("{bad", "") == ("", "model_roles_invalid_json")
    path.unlink()
    assert reviewer_models_for_refresh("{}", "") == ("", "model_roles_config_unreadable")


def test_reviewer_refresh_without_managed_dotenv_uses_process_values(monkeypatch):
    monkeypatch.delenv("LFL_ENV_FILE", raising=False)
    monkeypatch.delenv("LFL_RUNTIME_ROOT", raising=False)
    assert reviewer_models_for_refresh("{}", "glm/glm-5.3-flash") == ("glm/glm-5.3-flash", "")
    assert reviewer_models_for_refresh(json.dumps({"reviewer": ["backup/reviewer"]}), "") == (
        "backup/reviewer", ""
    )
