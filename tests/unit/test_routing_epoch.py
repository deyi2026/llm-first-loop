from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_session_id
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
from tests.unit.test_model_attribution import (
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)


def _replacement_registry() -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://routing-epoch-new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={
                    "deepseek-v4-flash": ModelSpec(context=262_144, thinking=True),
                    "deepseek-v4-pro": ModelSpec(context=262_144, thinking=True),
                },
                default_model="deepseek-v4-flash",
                chars_per_token=0.7,
            )
        }
    )


def test_run_routing_epoch_pins_registry_across_silent_reload_and_next_run_refreshes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    old_registry = pool.registry_snapshot()
    new_registry = _replacement_registry()

    token = current_session_id.set(sid)
    try:
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        first = engine._round_registry_snapshots("deepseek/deepseek-v4-pro", sess)
        identity0 = engine._routing._routing_identity()  # noqa: SLF001

        pool.replace_registry(new_registry)
        second = engine._round_registry_snapshots("deepseek/deepseek-v4-pro", sess)
        identity_after_reload = engine._routing._routing_identity()  # noqa: SLF001

        assert first[0] is old_registry
        assert second[0] is old_registry, "provider-admin/refresh must not silently rebind a live run"
        assert identity0 == identity_after_reload
        assert identity0["epoch"] == 0
        assert identity0["registry_fp"]

        # A new run establishes a new epoch-0 latch from then-current operator config.
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        third = engine._round_registry_snapshots("deepseek/deepseek-v4-pro", sess)
        identity_next_run = engine._routing._routing_identity()  # noqa: SLF001
        assert third[0] is new_registry
        assert identity_next_run["epoch"] == 0
        assert identity_next_run["registry_fp"]
        assert identity_next_run["registry_fp"] != identity0["registry_fp"]
    finally:
        current_session_id.reset(token)


def test_successful_switch_model_advances_routing_epoch_to_exact_switch_snapshot(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    old_registry = pool.registry_snapshot()
    new_registry = _replacement_registry()

    token = current_session_id.set(sid)
    try:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions[sid] = sess  # noqa: SLF001
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        before = engine._routing._routing_identity()  # noqa: SLF001
        assert engine._round_registry_snapshots(None, sess)[0] is old_registry

        # External reload alone is not authority. The model's explicit successful switch is.
        pool.replace_registry(new_registry)
        result = engine.corrections.execute(
            "switch_model",
            {"model": "deepseek/deepseek-v4-pro", "reason": "explicit routing epoch transition"},
        )
        after = engine._routing._routing_identity()  # noqa: SLF001
        snapshots = engine._round_registry_snapshots(None, sess)

        assert result.status.value == "success"
        assert sess.model_override == "deepseek/deepseek-v4-pro"
        assert before["epoch"] == 0
        assert after["epoch"] == 1
        assert after["registry_fp"] != before["registry_fp"]
        assert after["transition"] == "switch_model:deepseek/deepseek-v4-pro"
        assert snapshots[0] is new_registry
    finally:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions.pop(sid, None)  # noqa: SLF001
        current_session_id.reset(token)



def test_engine_multiround_dynamic_route_ignores_silent_reload_until_next_run(
    tmp_path, monkeypatch
) -> None:
    """Real loop: a tool round cannot silently jump to a hot-reloaded registry."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    old_client = _FakeLLMClient("deepseek-v4-pro")
    new_client = _FakeLLMClient("deepseek-v4-pro")
    pool = _make_pool(settings, default, cached={"deepseek": old_client})
    engine = _make_engine(tmp_path, pool, settings)
    old_registry = pool.registry_snapshot()
    new_registry = _replacement_registry()
    call_no = 0

    def old_chat(messages, tools, **kwargs):
        nonlocal call_no
        old_client.calls.append({"messages": messages, "kwargs": kwargs})
        call_no += 1
        if call_no == 1:
            pool.replace_registry(new_registry)
            return LLMResponse(
                content="inspect",
                tool_calls=[ToolCall(id="route-epoch-tool", name="read_file", arguments={"path": "missing.txt"})],
                provider="deepseek",
            )
        return LLMResponse(content="old-epoch-second-round", tool_calls=[], provider="deepseek")

    def new_chat(messages, tools, **kwargs):
        new_client.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(content="new-registry-route", tool_calls=[], provider="deepseek")

    old_client.chat = old_chat  # type: ignore[method-assign]
    new_client.chat = new_chat  # type: ignore[method-assign]

    def resolve(ref, *, registry=None):
        assert ref == "deepseek/deepseek-v4-pro"
        if registry is old_registry:
            return old_client, "deepseek", "deepseek-v4-pro"
        if registry is new_registry:
            return new_client, "deepseek", "deepseek-v4-pro"
        raise AssertionError("route must name an exact registry snapshot")

    monkeypatch.setattr(pool, "get_resolved_client", resolve)
    sid = engine.session.create()

    first = engine.run(sid, "run-one", model="deepseek/deepseek-v4-pro")
    assert first.final_answer == "old-epoch-second-round"
    assert len(old_client.calls) == 2
    assert new_client.calls == []

    second = engine.run(sid, "run-two", model="deepseek/deepseek-v4-pro")
    assert second.final_answer == "new-registry-route"
    assert len(new_client.calls) == 1


def test_failed_switch_model_does_not_advance_routing_epoch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)

    token = current_session_id.set(sid)
    try:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions[sid] = sess  # noqa: SLF001
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        before = engine._routing._routing_identity()  # noqa: SLF001
        result = engine.corrections.execute(
            "switch_model",
            {"model": "missing/not-real", "reason": "must fail closed"},
        )
        after = engine._routing._routing_identity()  # noqa: SLF001
        assert result.status.value == "failure"
        assert after == before
        assert sess.model_override is None
    finally:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions.pop(sid, None)  # noqa: SLF001
        current_session_id.reset(token)


def test_out_of_run_switch_does_not_mutate_previous_run_epoch(tmp_path, monkeypatch) -> None:
    """Persisted bucket state is diagnostic only once the run context is unbound."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    engine._run_state_mgr.last_active_sid = sid  # noqa: SLF001 - mirror real run ingress

    token = current_session_id.set(sid)
    try:
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        before = engine._routing._routing_identity()  # noqa: SLF001
    finally:
        current_session_id.reset(token)

    pool.replace_registry(_replacement_registry())
    # There is no active run binding; direct snapshot helpers see current operator config.
    sess = engine.session.load(sid)
    assert engine._round_registry_snapshots("deepseek/deepseek-v4-pro", sess)[0] is pool.registry_snapshot()
    assert engine._routing._routing_identity() == before  # noqa: SLF001



def test_switch_to_default_advances_epoch_without_authorizing_hot_registry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default)
    startup_registry = pool.default_registry_snapshot()
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create(model_override="deepseek/deepseek-v4-pro")
    sess = engine.session.load(sid)

    token = current_session_id.set(sid)
    try:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions[sid] = sess  # noqa: SLF001
        engine._routing._begin_run_routing_epoch()  # noqa: SLF001
        pool.replace_registry(_replacement_registry())

        result = engine.corrections.execute(
            "switch_model", {"model": "default", "reason": "explicit default transition"}
        )
        after = engine._routing._routing_identity()  # noqa: SLF001
        current, default_snapshot, planning = engine._round_registry_snapshots(None, sess)

        assert result.status.value == "success"
        assert sess.model_override is None
        assert after["epoch"] == 1
        assert after["transition"] == "switch_model:default"
        assert after["registry_fp"] == engine._routing._registry_fingerprint(startup_registry)  # noqa: SLF001
        assert after["registry_fp"] != engine._routing._registry_fingerprint(pool.registry_snapshot())  # noqa: SLF001
        assert current is startup_registry
        assert default_snapshot is startup_registry
        assert planning is startup_registry
    finally:
        with engine._run_state_mgr.guard:  # noqa: SLF001
            engine._run_sessions.pop(sid, None)  # noqa: SLF001
        current_session_id.reset(token)
