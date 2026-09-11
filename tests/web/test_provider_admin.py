"""Web provider/model admin: safe full local snapshot, secret redaction, CAS, reload/default facts."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def _provider(pid: str = "demo", *, enabled: bool = True, api_key_env: str = "") -> dict:
    return {
        "id": pid,
        "enabled": enabled,
        "base_url": "https://provider.example/v1",
        "api_key_env": api_key_env,
        "default_model": "m1",
        "timeout_s": 30,
        "max_input_tokens": 120000,
        "max_tokens": 8000,
        "models": [
            {
                "id": "m1",
                "enabled": True,
                "context": 131072,
                "max_input_tokens": 120000,
                "max_tokens": 8000,
                "cost_tier": "mid",
                "reasoning_capable": True,
                "reasoning_control": "unknown",
                "wire_protocol": "openai",
                "capability_tier": "unknown",
                "send_tool_choice": True,
                "reasoning_split": False,
                "reasoning_replay": "configured",
            }
        ],
    }


def test_provider_admin_create_uses_ignored_overlay_and_never_returns_secret(
    build_test_engine, fake_settings, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    env_file = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(env_file))
    client = _client(engine)

    initial = client.get("/api/v1/providers")
    assert initial.status_code == 200
    assert initial.json()["source"] == "missing"
    assert initial.json()["config_version"] == "missing"

    secret = "provider-secret-fixture-123"
    created = client.post(
        "/api/v1/providers",
        json={
            "expected_version": "missing",
            "provider": _provider(),
            "api_key": secret,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "local"
    assert body["providers"][0]["credential_configured"] is True
    assert secret not in created.text

    local_path = Path(fake_settings.data_dir) / "providers.local.json"
    assert local_path.is_file()
    assert secret not in local_path.read_text(encoding="utf-8")
    assert not (Path(fake_settings.data_dir) / "providers.json").exists()
    assert secret in env_file.read_text(encoding="utf-8")
    assert "LFL_PROVIDER_DEMO_API_KEY" in env_file.read_text(encoding="utf-8")

    listed = client.get("/api/v1/providers")
    assert secret not in listed.text
    assert listed.json()["providers"][0]["credential_source"] == "dotenv"

    models = client.get("/api/v1/models")
    assert models.status_code == 200
    assert "demo/m1" in models.json()["models"]
    catalog = {item["id"]: item for item in models.json()["catalog"]}
    assert catalog["demo/m1"]["reasoning_capable"] is True
    assert catalog["demo/m1"]["reasoning_control_supported"] is False


def test_provider_admin_cas_conflict_and_disable_reload(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)

    first = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert first.status_code == 201
    version = first.json()["config_version"]

    stale = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("beta")},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "provider_config_conflict"

    disabled_provider = _provider("alpha", enabled=False)
    disabled = client.put(
        "/api/v1/providers/alpha",
        json={"expected_version": version, "provider": disabled_provider},
    )
    assert disabled.status_code == 200, disabled.text
    row = disabled.json()["providers"][0]
    assert row["enabled"] is False
    assert row["effective"] is False
    assert "alpha/m1" not in client.get("/api/v1/models").json()["models"]


def test_provider_admin_default_is_persisted_but_runtime_default_stays_startup_snapshot(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    env_file = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(env_file))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    changed = client.post("/api/v1/providers/default-model", json={"model": "alpha/m1"})
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["configured_default_model"] == "alpha/m1"
    assert body["runtime_default_model"] != "alpha/m1"
    assert body["restart_required"] is True
    assert "LLM_MODEL=alpha/m1" in env_file.read_text(encoding="utf-8")

    blocked = client.delete(
        f"/api/v1/providers/alpha?expected_version={body['config_version']}&confirm=true"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "default_provider_cannot_delete"


def test_provider_admin_refuses_file_mutation_when_model_providers_env_owns_source(
    build_test_engine, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv(
        "MODEL_PROVIDERS",
        json.dumps(
            {
                "envp": {
                    "base_url": "https://env.example/v1",
                    "api_key_env": "",
                    "default_model": "e1",
                    "models": {"e1": {"context": 131072}},
                }
            }
        ),
    )
    client = _client(engine)
    snap = client.get("/api/v1/providers")
    assert snap.status_code == 200
    assert snap.json()["source"] == "env"
    assert snap.json()["mutable"] is False

    refused = client.post(
        "/api/v1/providers",
        json={"expected_version": snap.json()["config_version"], "provider": _provider("demo")},
    )
    assert refused.status_code == 409
    assert refused.json()["error"] == "provider_config_managed_by_env"


def test_provider_credential_does_not_override_external_environment(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("EXTERNAL_API_KEY", "externally-owned")
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={
            "expected_version": "missing",
            "provider": _provider("alpha", api_key_env="EXTERNAL_API_KEY"),
        },
    )
    assert created.status_code == 201
    changed = client.put(
        "/api/v1/providers/alpha/credential",
        json={"api_key": "new-secret"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"] == "config_managed_externally"
    assert "new-secret" not in changed.text


def test_provider_test_is_explicit_bounded_request_and_never_returns_model_text(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    seen: dict[str, object] = {}

    def fake_chat(self, messages, tools, **kwargs):  # noqa: ANN001
        seen["messages"] = messages
        seen["tools"] = tools
        seen["max_tokens"] = self.max_tokens
        from llm_loop.llm.client import LLMResponse

        return LLMResponse(content="TOP SECRET MODEL REPLY", tool_calls=[], provider="alpha")

    monkeypatch.setattr("llm_loop.llm.client.LLMClient.chat", fake_chat)
    tested = client.post("/api/v1/providers/alpha/test", json={"model": "m1"})
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True
    assert tested.json()["model"] == "m1"
    assert "TOP SECRET MODEL REPLY" not in tested.text
    assert seen["tools"] == []
    assert seen["max_tokens"] == 8



def test_provider_admin_inherits_public_auth_and_origin_guards(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("WEB_API_KEY", "web-admin-auth-fixture")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    engine, _ = build_test_engine([])
    client = _client(engine)

    assert client.get("/api/v1/providers").status_code == 401
    auth = {"Authorization": "Bearer web-admin-auth-fixture"}
    listed = client.get("/api/v1/providers", headers=auth)
    assert listed.status_code == 200

    # Even authenticated browser writes remain exact-Origin protected.
    bad_origin = client.post(
        "/api/v1/providers",
        headers={**auth, "Origin": "https://evil.example"},
        json={"expected_version": "missing", "provider": _provider("guarded")},
    )
    assert bad_origin.status_code == 403
    assert "web-admin-auth-fixture" not in bad_origin.text


def test_provider_test_error_detail_never_reflects_untrusted_secret_material(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    def fake_chat(self, messages, tools, **kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError(
            "connect https://alice:USERINFO-SECRET@provider.example/v1"
            "?api_key=QUERY-SECRET&token=TOKEN-SECRET "
            "Authorization: Bearer BEARER-SECRET response_body=BODY-SECRET"
        )

    monkeypatch.setattr("llm_loop.llm.client.LLMClient.chat", fake_chat)
    tested = client.post("/api/v1/providers/alpha/test", json={"model": "m1"})
    assert tested.status_code == 502
    assert tested.json()["error"] == "provider_test_failed"
    body = tested.text
    for secret in (
        "USERINFO-SECRET",
        "QUERY-SECRET",
        "TOKEN-SECRET",
        "BEARER-SECRET",
        "BODY-SECRET",
    ):
        assert secret not in body
    assert "RuntimeError" in body


def test_provider_test_reports_mechanical_http_status_without_error_body(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    class ProviderHTTPError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("SECRET-RESPONSE-BODY")
            self.response = SimpleNamespace(status_code=401)

    def fake_chat(self, messages, tools, **kwargs):  # noqa: ANN001, ARG001
        raise ProviderHTTPError()

    monkeypatch.setattr("llm_loop.llm.client.LLMClient.chat", fake_chat)
    tested = client.post("/api/v1/providers/alpha/test", json={"model": "m1"})
    assert tested.status_code == 502
    assert "ProviderHTTPError" in tested.json()["detail"]
    assert "HTTP 401" in tested.json()["detail"]
    assert "SECRET-RESPONSE-BODY" not in tested.text


def test_disabled_current_session_model_is_reported_unavailable_not_reinserted(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    sid = engine.session.create(model_override="alpha/m1")
    engine.session.set_shared_current(sid)

    before = client.get("/api/v1/models").json()
    assert before["current"] == "alpha/m1"
    assert before["current_available"] is True
    assert "alpha/m1" in before["models"]

    disabled = client.put(
        "/api/v1/providers/alpha",
        json={
            "expected_version": created.json()["config_version"],
            "provider": _provider("alpha", enabled=False),
        },
    )
    assert disabled.status_code == 200, disabled.text
    after = client.get("/api/v1/models").json()
    assert after["current"] == "alpha/m1"
    assert after["current_available"] is False
    assert "alpha/m1" not in after["models"]
    assert all(row["id"] != "alpha/m1" for row in after["catalog"])
    assert engine.session.load(sid).model_override == "alpha/m1"


def test_provider_admin_keeps_authenticated_local_http_provider_capability(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """Local/private HTTP endpoints remain an explicit authenticated operator capability."""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    provider = _provider("local")
    provider["base_url"] = "http://127.0.0.1:8901/v1"
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": provider},
    )
    assert created.status_code == 201, created.text

    seen: dict[str, str] = {}

    def fake_chat(self, messages, tools, **kwargs):  # noqa: ANN001, ARG001
        from llm_loop.llm.client import LLMResponse

        seen["base_url"] = self.base_url
        return LLMResponse(content="OK", tool_calls=[], provider="local")

    monkeypatch.setattr("llm_loop.llm.client.LLMClient.chat", fake_chat)
    tested = client.post("/api/v1/providers/local/test", json={"model": "m1"})
    assert tested.status_code == 200, tested.text
    assert seen["base_url"] == "http://127.0.0.1:8901/v1"


def test_provider_admin_cas_is_atomic_across_concurrent_writers(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """Two writers based on one version must not both commit (lost-update guard)."""
    import copy
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from llm_loop.web import provider_admin

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201, created.text

    raw, version, source, _path = provider_admin._effective_config(engine)
    assert source == "local"
    left = copy.deepcopy(raw)
    right = copy.deepcopy(raw)
    left["alpha"]["max_tokens"] = 8001
    right["alpha"]["max_tokens"] = 8002

    original_write = provider_admin._atomic_write_json
    first_writer_paused = threading.Event()
    release_first = threading.Event()
    write_calls = 0
    write_calls_guard = threading.Lock()

    def controlled_write(path, payload):
        nonlocal write_calls
        with write_calls_guard:
            write_calls += 1
            call_no = write_calls
        if call_no == 1:
            first_writer_paused.set()
            assert release_first.wait(timeout=5)
        original_write(path, payload)

    monkeypatch.setattr(provider_admin, "_atomic_write_json", controlled_write)

    def apply(payload):
        try:
            provider_admin._apply_local_config(engine, payload, expected_version=version)
            return "ok"
        except provider_admin.ProviderAdminError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(apply, left)
        assert first_writer_paused.wait(timeout=5)
        second = executor.submit(apply, right)
        # Without a compare/write lock the second writer reaches _atomic_write_json
        # during this window; with the lock it waits, then sees the new version.
        time.sleep(0.05)
        release_first.set()
        outcomes = [first.result(timeout=5), second.result(timeout=5)]

    assert sorted(outcomes) == ["ok", "provider_config_conflict"]
    assert write_calls == 1



def test_provider_admin_serializes_dotenv_read_modify_write(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """Credential/default writes must preserve each other under concurrent Web requests."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from llm_loop.web import provider_admin

    engine, _ = build_test_engine([])
    env_file = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(env_file))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={
            "expected_version": "missing",
            "provider": _provider("alpha", api_key_env="ALPHA_API_KEY"),
        },
    )
    assert created.status_code == 201, created.text

    original_write = provider_admin._atomic_write
    first_write_paused = threading.Event()
    release_first = threading.Event()
    write_calls = 0
    write_guard = threading.Lock()

    def controlled_write(path, raw, *, mode=None):
        nonlocal write_calls
        if Path(path) == env_file:
            with write_guard:
                write_calls += 1
                call_no = write_calls
            if call_no == 1:
                first_write_paused.set()
                assert release_first.wait(timeout=5)
        return original_write(path, raw, mode=mode)

    monkeypatch.setattr(provider_admin, "_atomic_write", controlled_write)

    with ThreadPoolExecutor(max_workers=2) as executor:
        credential = executor.submit(provider_admin.set_credential, engine, "alpha", "fixture-secret")
        assert first_write_paused.wait(timeout=5)
        default = executor.submit(provider_admin.set_default_model, engine, "alpha/m1")
        time.sleep(0.05)
        release_first.set()
        credential.result(timeout=5)
        default.result(timeout=5)

    text = env_file.read_text(encoding="utf-8")
    assert "ALPHA_API_KEY=fixture-secret" in text
    assert "LLM_MODEL=alpha/m1" in text
    assert write_calls == 2
