"""Web model persistence must resolve against an atomic provider-registry snapshot."""

from types import SimpleNamespace
from unittest import mock

from llm_loop.web.routes import _canonical_persist_model


class _StaleRegistry:
    def resolve(self, _model: str):
        raise AssertionError("mutable pool.registry must not be read when snapshot API exists")


def test_canonical_persist_model_uses_registry_snapshot() -> None:
    current = mock.Mock()
    current.resolve.return_value = ("provider", "model")
    pool = SimpleNamespace(registry=_StaleRegistry(), registry_snapshot=lambda: current)
    engine = SimpleNamespace(llm_pool=pool)

    assert _canonical_persist_model(engine, "alias") == "provider/model"
    current.resolve.assert_called_once_with("alias")


def test_canonical_persist_model_keeps_legacy_registry_compatibility() -> None:
    registry = mock.Mock()
    registry.resolve.return_value = ("legacy", "model")
    engine = SimpleNamespace(llm_pool=SimpleNamespace(registry=registry))

    assert _canonical_persist_model(engine, "alias") == "legacy/model"
    registry.resolve.assert_called_once_with("alias")
