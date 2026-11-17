"""Live local context must never exceed the actual serving slot capacity."""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.engine_services.local_context_window import (
    LocalContextWindowObserver,
)
from llm_loop.core.loop.engine_services.routing import RoutingService


def _payloads(*, alias="qwen3.8-flash-next", props_ctx=131072, slot_ctx=131072):
    return {
        "/props": {
            "model_alias": alias,
            "total_slots": 2,
            "default_generation_settings": {"n_ctx": props_ctx},
            "is_sleeping": False,
        },
        "/slots": [{"id": 0, "n_ctx": slot_ctx}, {"id": 1, "n_ctx": slot_ctx}],
    }


def _observer(payloads, *, clock=lambda: 100.0):
    calls = []

    def fetch(url, timeout_s):
        calls.append((url, timeout_s))
        return payloads["/" + url.rsplit("/", 1)[-1]]

    return LocalContextWindowObserver(fetch_json=fetch, clock=clock), calls


def _routing(observer, *, registered=262144, output=32768):
    model = SimpleNamespace(context=registered, max_tokens=output, max_input_tokens=None)
    provider = SimpleNamespace(
        base_url="http://localhost:8901/v1",
        history_budget_chars=None,
        max_input_tokens=184000,
        max_tokens=None,
        chars_per_token=0.9,
        models={"qwen3.8-flash-next": model},
    )
    registry = SimpleNamespace(providers={"cognilocal": provider})
    pool = SimpleNamespace(registry_snapshot=lambda: registry)
    host = SimpleNamespace(
        settings=SimpleNamespace(history_max_chars=None, llm_max_tokens=output, data_dir=""),
        llm_pool=pool,
        runtime=None,
    )
    routing = RoutingService(host)
    routing._local_context_observer = observer
    return routing, model, provider


def test_live_128k_clamps_registered_256k_and_preserves_output_reserve():
    observer, calls = _observer(_payloads())
    routing, _model, _provider = _routing(observer)
    budget = routing._resolve_history_budget("cognilocal/qwen3.8-flash-next")
    assert budget["allowed_input_tokens"] == 98304
    assert budget["limited_by"] == "model_window"
    assert len(calls) == 2
    # Both planning and metadata must share one cached runtime observation.
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 131072
    assert len(calls) == 2


def test_live_64k_shrinks_registered_256k_without_changing_registry():
    observer, _calls = _observer(_payloads(props_ctx=65536, slot_ctx=65536))
    routing, model, _provider = _routing(observer)
    assert routing._resolve_history_budget("cognilocal/qwen3.8-flash-next")["allowed_input_tokens"] == 32768
    assert model.context == 262144


def test_live_256k_does_not_silently_expand_registered_128k():
    observer, _calls = _observer(_payloads(props_ctx=262144, slot_ctx=262144))
    routing, _model, _provider = _routing(observer, registered=131072)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 131072


def test_mismatched_model_alias_is_not_trusted_as_live_capacity():
    observer, _calls = _observer(_payloads(alias="different-model"))
    routing, _model, _provider = _routing(observer)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 32768


def test_inconsistent_slot_context_uses_smallest_live_slot():
    data = _payloads(props_ctx=131072)
    data["/slots"][1]["n_ctx"] = 65536
    observer, _calls = _observer(data)
    routing, _model, _provider = _routing(observer)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 65536


def test_probe_error_fails_to_conservative_local_window():
    def failed(_url, _timeout):
        raise TimeoutError("runtime restarted")

    observer = LocalContextWindowObserver(fetch_json=failed)
    routing, _model, _provider = _routing(observer)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 32768


def test_reprobe_after_ttl_handles_runtime_restart_and_context_shrink():
    now = [100.0]
    data = _payloads()
    observer, calls = _observer(data, clock=lambda: now[0])
    routing, _model, _provider = _routing(observer)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 131072
    data["/props"]["default_generation_settings"]["n_ctx"] = 65536
    data["/slots"][0]["n_ctx"] = 65536
    data["/slots"][1]["n_ctx"] = 65536
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 131072
    now[0] += 31
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 65536
    assert len(calls) == 4


def test_remote_endpoint_never_probed_or_clamped():
    observer, calls = _observer(_payloads())
    routing, _model, provider = _routing(observer)
    provider.base_url = "https://api.example.com/v1"
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 262144
    assert calls == []


def test_loopback_userinfo_and_non_api_path_are_not_probed():
    observer, calls = _observer(_payloads())
    routing, _model, provider = _routing(observer)
    for url in ("http://token@localhost:8901/v1", "http://localhost:8901/admin", "http://localhost.evil:8901/v1"):
        provider.base_url = url
        assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 262144
    assert calls == []


def test_invalid_props_and_slots_are_never_authoritative():
    for data in (
        _payloads(props_ctx=True),
        _payloads(slot_ctx="131072"),
        {"/props": _payloads()["/props"], "/slots": []},
        {"/props": {**_payloads()["/props"], "is_sleeping": True}, "/slots": _payloads()["/slots"]},
    ):
        observer, _calls = _observer(data)
        routing, _model, _provider = _routing(observer)
        assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 32768


def test_new_run_invalidates_cached_local_context():
    now = [100.0]
    data = _payloads()
    observer, calls = _observer(data, clock=lambda: now[0])
    routing, _model, _provider = _routing(observer)
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 131072
    data["/props"]["default_generation_settings"]["n_ctx"] = 65536
    for slot in data["/slots"]:
        slot["n_ctx"] = 65536
    # Explicit Run boundary clears the cache, even if the TTL has not elapsed.
    routing._host._run_state = lambda: SimpleNamespace(
        routing_epoch_active=False,
        routing_epoch=0,
        routing_registry_snapshot=None,
        routing_default_registry_snapshot=None,
        routing_registry_fp="",
        routing_transition="",
    )
    routing._pool_default_registry_snapshot = routing._pool_registry_snapshot
    routing._begin_run_routing_epoch()
    assert routing._current_context_limit("cognilocal/qwen3.8-flash-next") == 65536
    assert len(calls) == 4


def test_unmanaged_loopback_provider_keeps_explicit_operator_budget():
    observer, calls = _observer(_payloads())
    routing, _model, provider = _routing(observer)
    routing._host.llm_pool.registry_snapshot().providers["local"] = provider
    assert routing._current_context_limit("local/qwen3.8-flash-next") == 262144
    assert calls == []


def test_one_million_cloud_window_is_not_subject_to_local_probe_or_184k_cap():
    observer, calls = _observer(_payloads())
    routing, model, provider = _routing(observer, registered=1000000, output=65536)
    provider.base_url = "https://open.bigmodel.cn/api/coding/paas/v4"
    provider.max_input_tokens = 1000000
    model.max_tokens = 65536
    budget = routing._resolve_history_budget("cognilocal/qwen3.8-flash-next")
    assert budget["allowed_input_tokens"] == 900000
    assert budget["limited_by"] == "model_window"
    assert calls == []
