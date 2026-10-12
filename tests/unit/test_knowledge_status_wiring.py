from llm_loop.introspection.status import ArchitectureStatusProvider


def test_architecture_status_exposes_knowledge_health_as_default_dimension():
    provider = ArchitectureStatusProvider()
    provider.set_knowledge_health_fn(
        lambda: {"status": "healthy", "writes_enabled": True, "stores": {}}
    )
    snap = provider.snapshot()
    assert snap["knowledge_health"]["status"] == "healthy"


def test_architecture_status_knowledge_health_failure_is_visible_not_fake_green():
    provider = ArchitectureStatusProvider()

    def boom():
        raise OSError("probe failed")

    provider.set_knowledge_health_fn(boom)
    snap = provider.snapshot(dimensions=["knowledge_health"])
    assert snap["knowledge_health"]["status"] == "unknown"
    assert snap["knowledge_health"]["writes_enabled"] is False
    assert "OSError" in snap["knowledge_health"]["note"]
