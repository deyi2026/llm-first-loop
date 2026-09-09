"""P2-B fallback routing contract: operator chain, no runtime quality floor."""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from typing import cast

from llm_loop.llm.client import LLMClient
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec


def _registry(*models: tuple[str, str, str]) -> ProviderRegistry:
    provs: dict[str, ProviderSpec] = {}
    for pid, mid, tier in models:
        spec = provs.setdefault(
            pid,
            ProviderSpec(id=pid, base_url="http://x.invalid/v1", api_key_env="LFL_TEST_KEY"),
        )
        spec.models[mid] = ModelSpec(capability_tier=tier)
    return ProviderRegistry(providers=provs)


def _pool(registry: ProviderRegistry, fallbacks: str, *, provider="primary", model="default"):
    default = SimpleNamespace(
        provider=provider,
        model=model,
        timeout_s=120.0,
        max_tokens=8192,
        thinking_mode=True,
        reasoning_effort="high",
        thinking_supported=False,
    )
    return ModelClientPool(
        registry=registry,
        default_client=cast(LLMClient, default),
        model_fallbacks_raw=fallbacks,
    )


def test_capability_tier_is_metadata_not_routing_authority(monkeypatch):
    monkeypatch.setenv("LFL_TEST_KEY", "k")
    monkeypatch.setenv("LFL_FALLBACK_FLOOR", "enforce")  # stale env must be inert
    reg = _registry(
        ("strongp", "big", "strong"), ("weakp", "small", "weak"), ("unknownp", "m", "unknown")
    )
    pool = _pool(reg, "strongp/big,weakp/small,unknownp/m")
    assert pool.fallback_candidates(registry=reg) == ["strongp/big", "weakp/small", "unknownp/m"]
    assert ModelSpec(capability_tier="weak").capability_tier == "weak"  # factual metadata preserved


def test_default_model_and_duplicate_refs_are_mechanically_removed(monkeypatch):
    monkeypatch.setenv("LFL_TEST_KEY", "k")
    reg = _registry(
        ("primary", "default", "unknown"), ("fb", "one", "unknown"), ("fb", "two", "weak")
    )
    pool = _pool(reg, "primary/default,fb/one,fb/one,fb/two", provider="primary", model="default")
    assert pool.fallback_candidates(registry=reg) == ["fb/one", "fb/two"]


def test_invalid_candidate_is_skipped_without_changing_valid_order(monkeypatch):
    monkeypatch.setenv("LFL_TEST_KEY", "k")
    reg = _registry(("fb", "one", "unknown"), ("fb", "two", "unknown"))
    pool = _pool(reg, "missing/x,fb/two,fb/one")
    assert pool.fallback_candidates(registry=reg) == ["fb/two", "fb/one"]


def test_explicit_override_still_disables_automatic_fallback():
    from llm_loop.core.loop import engine

    tree = ast.parse(inspect.getsource(engine))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "is_default_assembled" for t in node.targets)
    ]
    assert len(assignments) == 1
    assert (
        ast.unparse(assignments[0].value)
        == "sess.model_override is None and chat_model_arg is None"
    )


def test_retired_quality_and_wip_retry_authority_absent():
    import llm_loop.llm.pool as pool_mod
    import llm_loop.llm.providers as providers_mod
    from llm_loop.core.loop.engine_services.fallback import FallbackService

    pool_src = inspect.getsource(pool_mod)
    assert "LFL_FALLBACK_FLOOR" not in pool_src
    assert "_apply_capability_floor" not in pool_src
    assert not hasattr(providers_mod, "is_below_capability_floor")
    assert not hasattr(FallbackService, "_same_model_retry_before_fallback")
    assert not hasattr(FallbackService, "_same_model_retry_gate")
