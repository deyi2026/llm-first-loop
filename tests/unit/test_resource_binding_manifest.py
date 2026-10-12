from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.resources.contracts import FactSource, ResourceScopeKind
from llm_loop.resources.resource_bindings import parse_operator_resource_binding


def _raw() -> dict:
    return {
        "provider_id": "minimax",
        "product_id": "token-plan-plus",
        "account_alias": "primary",
        "api_family": "openai-compatible",
        "region": "global",
        "model_ids": ["MiniMax-M3", "MiniMax-M2.7"],
        "scopes": {
            "product": "primary:minimax-token-plan-plus",
            "account": "primary:minimax-account",
        },
        "source_ref": "operator:resource-products:v1",
        "version_ref": "sha256:fixture",
    }


def test_closed_manifest_materializes_exact_non_secret_resource_aliases() -> None:
    parsed = parse_operator_resource_binding(_raw())
    product, keys, bindings = parsed.materialize(recorded_at=100.0)
    assert product.product_id == "token-plan-plus"
    assert product.account_alias == "primary"
    assert product.provenance.source is FactSource.OPERATOR_CONFIG
    assert {key.scope_kind for key in keys} == {ResourceScopeKind.PRODUCT, ResourceScopeKind.ACCOUNT}
    assert {row.model_id for row in bindings} == {"MiniMax-M3", "MiniMax-M2.7"}
    assert all(row.resource_keys == keys for row in bindings)
    assert all(row.validity.version_ref == "sha256:fixture" for row in bindings)


def test_project_scope_requires_explicit_project_alias_and_scope_id_together() -> None:
    raw = _raw()
    raw["project_alias"] = "team-a"
    raw["scopes"]["project"] = "primary:team-a"
    parsed = parse_operator_resource_binding(raw)
    product, keys, _bindings = parsed.materialize(recorded_at=100.0)
    assert product.project_alias == "team-a"
    assert any(key.scope_kind is ResourceScopeKind.PROJECT for key in keys)

    missing_alias = _raw()
    missing_alias["scopes"]["project"] = "primary:team-a"
    with pytest.raises(ValueError, match="together"):
        parse_operator_resource_binding(missing_alias)


def test_manifest_rejects_routing_and_credential_fields_instead_of_using_them_as_identity() -> None:
    for field, value in (
        ("base_url", "https://api.example.invalid/v1"),
        ("api_key_env", "MINIMAX_API_KEY"),
        ("api_key", "not-a-real-key"),
        ("endpoint", "coding"),
    ):
        raw = _raw()
        raw[field] = value
        with pytest.raises(ValueError, match="forbidden"):
            parse_operator_resource_binding(raw)


def test_manifest_rejects_implicit_or_ambiguous_identity() -> None:
    raw = _raw()
    del raw["product_id"]
    with pytest.raises(ValueError, match="product_id"):
        parse_operator_resource_binding(raw)

    raw = _raw()
    raw["model_ids"] = ["MiniMax-M3", "MiniMax-M3"]
    with pytest.raises(ValueError, match="duplicates"):
        parse_operator_resource_binding(raw)

    raw = _raw()
    raw["scopes"] = {"account": "primary"}
    with pytest.raises(ValueError, match="scopes.product"):
        parse_operator_resource_binding(raw)


def test_manifest_parser_has_no_file_network_or_governor_dependency() -> None:
    root = Path(__file__).parents[2]
    text = (root / "src/llm_loop/resources/resource_bindings.py").read_text().lower()
    for token in ("open(", "read_text", "httpx", "requests", "resources.governor", "provider_calls"):
        assert token not in text


def test_manifest_resolution_is_exact_and_empty_manifest_stays_unbound() -> None:
    from llm_loop.resources.resource_bindings import (
        parse_operator_resource_manifest,
        resolve_operator_resource_binding,
    )

    entries = parse_operator_resource_manifest((_raw(),))
    assert resolve_operator_resource_binding(
        entries, provider_id="minimax", model_id="MiniMax-M3"
    ) is entries[0]
    assert resolve_operator_resource_binding(
        entries, provider_id="minimax", model_id="minimax-m3"
    ) is None
    assert resolve_operator_resource_binding(
        (), provider_id="minimax", model_id="MiniMax-M3"
    ) is None


def test_manifest_rejects_overlapping_exact_provider_model_bindings() -> None:
    from llm_loop.resources.resource_bindings import parse_operator_resource_manifest

    second = _raw()
    second["product_id"] = "paygo"
    second["scopes"] = {
        "product": "primary:minimax-paygo",
        "account": "primary:minimax-account",
    }
    with pytest.raises(ValueError, match="overlapping"):
        parse_operator_resource_manifest((_raw(), second))
