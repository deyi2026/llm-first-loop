"""Explicit operator resource-product binding contract for RG-3E.

Provider routing configuration and resource identity are intentionally separate.
This module accepts only non-secret aliases and exact model ids, then materializes
provider-neutral Product/ResourceKey/ProviderResourceBinding facts. It performs no
file I/O, network I/O, provider selection, or admission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from llm_loop.resources.contracts import (
    FactProvenance,
    FactSource,
    ResourceKey,
    ResourceProductIdentity,
    ResourceScopeKind,
)
from llm_loop.resources.ledger_projection import (
    FactValidity,
    FactValidityKind,
    ProviderResourceBinding,
)

_ALLOWED_FIELDS = frozenset(
    {
        "provider_id",
        "product_id",
        "account_alias",
        "api_family",
        "region",
        "project_alias",
        "model_ids",
        "scopes",
        "source_ref",
        "version_ref",
    }
)
_ALLOWED_SCOPES = frozenset({"product", "account", "project"})
_FORBIDDEN_IDENTITY_FIELDS = frozenset(
    {
        "api_key",
        "api_key_env",
        "token",
        "secret",
        "authorization",
        "base_url",
        "endpoint",
    }
)


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _text(name, value)


def _model_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("model_ids must be a non-empty sequence")
    models = tuple(_text("model_id", item) for item in value)
    if not models:
        raise ValueError("model_ids must be non-empty")
    if len(set(models)) != len(models):
        raise ValueError("model_ids contains duplicates")
    return models


@dataclass(frozen=True)
class OperatorResourceBinding:
    """One explicit operator-owned provider/product identity binding."""

    provider_id: str
    product_id: str
    account_alias: str
    model_ids: tuple[str, ...]
    product_scope_id: str
    account_scope_id: str
    source_ref: str
    version_ref: str
    api_family: str | None = None
    region: str | None = None
    project_alias: str | None = None
    project_scope_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "product_id",
            "account_alias",
            "product_scope_id",
            "account_scope_id",
            "source_ref",
            "version_ref",
        ):
            _text(name, getattr(self, name))
        if not self.model_ids or any(not model.strip() for model in self.model_ids):
            raise ValueError("model_ids must be non-empty")
        if len(set(self.model_ids)) != len(self.model_ids):
            raise ValueError("model_ids contains duplicates")
        for name in ("api_family", "region", "project_alias", "project_scope_id"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)
        if (self.project_alias is None) != (self.project_scope_id is None):
            raise ValueError("project_alias and project_scope_id must be supplied together")

    def materialize(
        self, *, recorded_at: float
    ) -> tuple[ResourceProductIdentity, tuple[ResourceKey, ...], tuple[ProviderResourceBinding, ...]]:
        """Create exact aliases and per-model bindings; no semantic inference occurs."""

        if recorded_at < 0:
            raise ValueError("recorded_at must be >= 0")
        provenance = FactProvenance(
            source=FactSource.OPERATOR_CONFIG,
            source_ref=self.source_ref,
            recorded_at=recorded_at,
        )
        validity = FactValidity(
            kind=FactValidityKind.OPEN_ENDED,
            valid_from=recorded_at,
            version_ref=self.version_ref,
        )
        product = ResourceProductIdentity(
            provider_id=self.provider_id,
            product_id=self.product_id,
            account_alias=self.account_alias,
            api_family=self.api_family,
            region=self.region,
            project_alias=self.project_alias,
            provenance=provenance,
        )
        keys = [
            ResourceKey(self.provider_id, ResourceScopeKind.PRODUCT, self.product_scope_id),
            ResourceKey(self.provider_id, ResourceScopeKind.ACCOUNT, self.account_scope_id),
        ]
        if self.project_scope_id is not None:
            keys.append(ResourceKey(self.provider_id, ResourceScopeKind.PROJECT, self.project_scope_id))
        key_tuple = tuple(keys)
        bindings = tuple(
            ProviderResourceBinding(
                provider_id=self.provider_id,
                model_id=model_id,
                resource_keys=key_tuple,
                provenance=provenance,
                validity=validity,
                product=product,
            )
            for model_id in self.model_ids
        )
        return product, key_tuple, bindings


def parse_operator_resource_binding(raw: Mapping[str, Any]) -> OperatorResourceBinding:
    """Parse a closed, non-secret binding object.

    Routing/credential fields are rejected even if they are otherwise harmless. This
    keeps resource identity from becoming an accidental second provider registry.
    """

    keys = {str(key) for key in raw}
    forbidden = keys & _FORBIDDEN_IDENTITY_FIELDS
    if forbidden:
        raise ValueError(f"resource binding contains forbidden routing/credential fields: {sorted(forbidden)}")
    unknown = keys - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"resource binding contains unknown fields: {sorted(unknown)}")
    scopes_raw = raw.get("scopes")
    if not isinstance(scopes_raw, Mapping):
        raise ValueError("scopes must be an object")
    scope_names = {str(key) for key in scopes_raw}
    unknown_scopes = scope_names - _ALLOWED_SCOPES
    if unknown_scopes:
        raise ValueError(f"unknown resource scopes: {sorted(unknown_scopes)}")
    if "product" not in scopes_raw or "account" not in scopes_raw:
        raise ValueError("scopes.product and scopes.account are required")

    project_alias = _optional_text("project_alias", raw.get("project_alias"))
    project_scope_id = _optional_text("scopes.project", scopes_raw.get("project"))
    return OperatorResourceBinding(
        provider_id=_text("provider_id", raw.get("provider_id")),
        product_id=_text("product_id", raw.get("product_id")),
        account_alias=_text("account_alias", raw.get("account_alias")),
        model_ids=_model_ids(raw.get("model_ids")),
        product_scope_id=_text("scopes.product", scopes_raw.get("product")),
        account_scope_id=_text("scopes.account", scopes_raw.get("account")),
        project_alias=project_alias,
        project_scope_id=project_scope_id,
        api_family=_optional_text("api_family", raw.get("api_family")),
        region=_optional_text("region", raw.get("region")),
        source_ref=_text("source_ref", raw.get("source_ref")),
        version_ref=_text("version_ref", raw.get("version_ref")),
    )


def parse_operator_resource_manifest(
    raw_entries: Sequence[Mapping[str, Any]],
) -> tuple[OperatorResourceBinding, ...]:
    """Parse a closed list and reject overlapping exact provider/model ownership."""

    entries = tuple(parse_operator_resource_binding(raw) for raw in raw_entries)
    owner: dict[tuple[str, str], int] = {}
    for index, entry in enumerate(entries):
        for model_id in entry.model_ids:
            key = (entry.provider_id, model_id)
            if key in owner:
                raise ValueError(
                    "resource manifest contains overlapping provider/model bindings: "
                    f"{entry.provider_id}/{model_id}"
                )
            owner[key] = index
    return entries


def resolve_operator_resource_binding(
    entries: Sequence[OperatorResourceBinding], *, provider_id: str, model_id: str
) -> OperatorResourceBinding | None:
    """Resolve exact provider/model identity only; no alias or provider fallback exists."""

    provider_id = _text("provider_id", provider_id)
    model_id = _text("model_id", model_id)
    matches = [
        entry
        for entry in entries
        if entry.provider_id == provider_id and model_id in entry.model_ids
    ]
    if len(matches) > 1:
        raise ValueError("resource binding resolution is ambiguous")
    return matches[0] if matches else None
