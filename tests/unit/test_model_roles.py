from __future__ import annotations

import json

import pytest

from llm_loop.llm.model_roles import (
    model_roles_for_refresh,
    parse_model_roles,
    reviewer_models_configured,
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
