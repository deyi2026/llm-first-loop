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
                "reasoning_efforts": ["low", "high", "max"],
                "reasoning_default_effort": "max",
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
    assert catalog["demo/m1"]["reasoning_efforts"] == ["low", "high", "max"]
    assert catalog["demo/m1"]["reasoning_default_effort"] == "max"


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


def test_provider_admin_default_is_persisted_and_applies_live(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """model-admin design §6.2.3/§9.2-7: 默认模型写 .env 且 live 生效（旧测试锁定
    restart_required=true 的启动快照语义，Phase 1 起按 live 断言更新）。"""
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
    assert body["runtime_default_model"] == "alpha/m1"
    assert body["restart_required"] is False
    assert body["default"]["persistence"] == "dotenv"
    assert body["default"]["applied"] is True
    assert body["default"]["restart_required"] is False
    assert "LLM_MODEL=alpha/m1" in env_file.read_text(encoding="utf-8")
    # live 默认已进 pool：展示 ref 与 get_client(None) 都指向新模型。
    assert engine.llm_pool.get_default_ref() == "alpha/m1"
    routed = engine.llm_pool.get_client(None)
    assert routed is not engine.llm_pool.default_client

    blocked = client.delete(
        f"/api/v1/providers/alpha?expected_version={body['config_version']}&confirm=true"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "default_provider_cannot_delete"

    # design §7.7 default_provider_cannot_disable：承载默认（含 runtime 默认）不可停用。
    patch_blocked = client.patch(
        "/api/v1/providers/alpha",
        json={"expected_version": body["config_version"], "enabled": False},
    )
    assert patch_blocked.status_code == 409
    assert patch_blocked.json()["error"] == "default_provider_cannot_disable"


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


# ── model-admin design §9.2：C0-C3 后端新增测试 ────────────────────────────


def _ui_projection_provider(pid: str = "alpha") -> dict:
    """§6.1.1 toProviderConfig/toModelConfig 投影形状（配置事实，无运行时字段）."""
    return {
        "id": pid,
        "display_name": "Alpha",
        "enabled": True,
        "base_url": "https://provider.example/v1",
        "api_key_env": "",
        "default_model": "m1",
        "timeout_s": 30,
        "models": [
            {
                "id": "m1",
                "name": "Alpha M1",
                "note": "operator note",
                "enabled": True,
                "context": 131072,
                "max_input_tokens": None,
                "max_tokens": None,
                "cost_tier": "mid",
                "capability_tier": "unknown",
                "input_modalities": ["text"],
                "multimodal": False,
                "wire_protocol": "openai",
                "thinking": False,
                "reasoning_capable": False,
                "reasoning_control": "unknown",
                "reasoning_efforts": [],
                "reasoning_effort_map": {},
                "reasoning_default_effort": None,
                "reasoning_replay": "configured",
                "send_tool_choice": True,
                "reasoning_split": False,
                "runtime_identity": "",
                "temperature": None,
                "top_p": None,
                "top_k": None,
                "min_p": None,
            }
        ],
    }


def test_replace_provider_accepts_ui_projection_without_runtime_facts(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-1: UI 配置投影（含 note/name/input_modalities）不再 422；文件无 effective."""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _ui_projection_provider()},
    )
    assert created.status_code == 201, created.text
    version = created.json()["config_version"]

    body = _ui_projection_provider()
    body["timeout_s"] = 45
    replaced = client.put(
        "/api/v1/providers/alpha", json={"expected_version": version, "provider": body}
    )
    assert replaced.status_code == 200, replaced.text
    row = replaced.json()["providers"][0]
    assert row["display_name"] == "Alpha"
    assert row["models"][0]["note"] == "operator note"
    assert row["models"][0]["name"] == "Alpha M1"
    assert row["models"][0]["input_modalities"] == ["text"]

    local = Path(engine.settings.data_dir) / "providers.local.json"
    text = local.read_text(encoding="utf-8")
    assert "operator note" in text
    assert '"effective"' not in text
    # /models 目录反映新元数据（§6.3.2）。
    models = client.get("/api/v1/models").json()
    catalog = {item["id"]: item for item in models["catalog"]}
    assert catalog["alpha/m1"]["display_name"] == "Alpha M1"
    assert catalog["alpha/m1"]["input_modalities"] == ["text"]
    assert catalog["alpha/m1"]["provider_name"] == "Alpha"


def test_replace_provider_rejects_runtime_facts_with_field_path(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-2/R3: 快照回写形态（含 effective）→ 422 且 detail[].loc 含字段路径."""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    body = _ui_projection_provider()
    body["models"][0]["effective"] = True  # 运行时事实回写（旧 UI bug 形态）
    response = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": body},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        "effective" in [str(seg) for seg in item.get("loc", [])] for item in detail
    ), detail


def test_patch_provider_enabled_default_model_and_conflict_version(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§6.1.3/§7.2: 行级 PATCH（enabled/default_model/display_name）+ 冲突带 current_version."""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    version = created.json()["config_version"]

    # 加第二个模型，PATCH 不得动 models。
    added = client.post(
        "/api/v1/providers/alpha/models",
        json={
            "expected_version": version,
            "model": {"id": "m2", "context": 65536, "note": "second"},
        },
    )
    assert added.status_code == 201, added.text
    version = added.json()["config_version"]

    disabled = client.patch(
        "/api/v1/providers/alpha",
        json={"expected_version": version, "enabled": False, "display_name": "A-off"},
    )
    assert disabled.status_code == 200, disabled.text
    row = disabled.json()["providers"][0]
    assert row["enabled"] is False
    assert row["display_name"] == "A-off"
    assert {m["id"] for m in row["models"]} == {"m1", "m2"}, "PATCH 不得修改 models"
    assert "alpha/m1" not in client.get("/api/v1/models").json()["models"]

    reenabled = client.patch(
        "/api/v1/providers/alpha",
        json={"expected_version": disabled.json()["config_version"], "enabled": True},
    )
    assert reenabled.status_code == 200
    assert "alpha/m1" in client.get("/api/v1/models").json()["models"]

    # 冲突错误体可读且带 current_version（§6.1.4/§7.2）。
    conflict = client.patch(
        "/api/v1/providers/alpha",
        json={"expected_version": version, "enabled": False},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "provider_config_conflict"
    assert conflict.json()["current_version"] == reenabled.json()["config_version"]

    # default_model PATCH 校验最终配置（指向不存在模型 → 422 字段路径）。
    bad = client.patch(
        "/api/v1/providers/alpha",
        json={
            "expected_version": reenabled.json()["config_version"],
            "default_model": "ghost",
        },
    )
    assert bad.status_code == 422
    assert bad.json()["error"] == "invalid_field"
    assert "default_model" in bad.json()["detail"]


def test_patch_provider_requires_at_least_one_field(
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
    empty = client.patch(
        "/api/v1/providers/alpha", json={"expected_version": created.json()["config_version"]}
    )
    assert empty.status_code == 422


def test_add_model_endpoint_appears_in_catalog_without_restart(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-4: POST /models 后目录立即出现新模型（含 name/input_modalities）。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    version = created.json()["config_version"]

    added = client.post(
        "/api/v1/providers/alpha/models",
        json={
            "expected_version": version,
            "model": {
                "id": "m2",
                "context": 262144,
                "name": "Alpha M2",
                "input_modalities": ["text", "image"],
                "note": "vision",
            },
        },
    )
    assert added.status_code == 201, added.text
    models = client.get("/api/v1/models").json()
    assert "alpha/m2" in models["models"]
    catalog = {item["id"]: item for item in models["catalog"]}
    assert catalog["alpha/m2"]["display_name"] == "Alpha M2"
    assert catalog["alpha/m2"]["input_modalities"] == ["text", "image"]
    assert catalog["alpha/m2"]["multimodal"] is True  # 与 input_modalities 同步
    # 运行 registry 已热替换（无需重启）。
    assert engine.llm_pool.registry_snapshot().providers["alpha"].models["m2"].name == "Alpha M2"


def test_replace_model_rename_preserves_unknown_fields(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-5/FR-13: 模型改名后 note 与 schema 外未知字段保留。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    local = Path(engine.settings.data_dir) / "providers.local.json"
    raw = json.loads(local.read_text(encoding="utf-8"))
    raw["alpha"]["models"]["m1"]["x_custom_flag"] = "keep-me"
    local.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    # 手改文件改变内容 hash → 重取 CAS 版本。
    version = client.get("/api/v1/providers").json()["config_version"]

    replaced = client.put(
        "/api/v1/providers/alpha/models/m1",
        json={
            "expected_version": version,
            "model": {"id": "m1-renamed", "context": 131072, "note": "operator note"},
        },
    )
    assert replaced.status_code == 200, replaced.text
    raw_after = json.loads(local.read_text(encoding="utf-8"))
    model = raw_after["alpha"]["models"]["m1-renamed"]
    assert model["note"] == "operator note"
    assert model["x_custom_flag"] == "keep-me"
    assert "m1" not in raw_after["alpha"]["models"]
    assert raw_after["alpha"]["default_model"] == "m1-renamed"


def test_delete_model_default_guards(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§7.3: 配置默认/live 默认/Provider 默认三重删除保护。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    version = created.json()["config_version"]
    added = client.post(
        "/api/v1/providers/alpha/models",
        json={"expected_version": version, "model": {"id": "m2", "context": 65536}},
    )
    assert added.status_code == 201, added.text
    version = added.json()["config_version"]

    # Provider 默认模型（m1）删除 → provider_default_model_cannot_delete。
    provider_default = client.delete(
        f"/api/v1/providers/alpha/models/m1?expected_version={version}&confirm=true"
    )
    assert provider_default.status_code == 409
    assert provider_default.json()["error"] == "provider_default_model_cannot_delete"

    # 设为全局默认后，目标模型删除 → default_model_cannot_delete。
    set_default = client.post("/api/v1/providers/default-model", json={"model": "alpha/m2"})
    assert set_default.status_code == 200, set_default.text
    global_default = client.delete(
        f"/api/v1/providers/alpha/models/m2?expected_version={set_default.json()['config_version']}&confirm=true"
    )
    assert global_default.status_code == 409
    assert global_default.json()["error"] == "default_model_cannot_delete"

    # 停用默认模型同样拒绝（default_model_cannot_disable）。
    disable = client.put(
        "/api/v1/providers/alpha/models/m2",
        json={
            "expected_version": set_default.json()["config_version"],
            "model": {"id": "m2", "context": 65536, "enabled": False},
        },
    )
    assert disable.status_code == 409
    assert disable.json()["error"] == "default_model_cannot_disable"

    # 切换默认后可删除（验收 §10-5）。
    switched = client.post("/api/v1/providers/default-model", json={"model": "alpha/m1"})
    assert switched.status_code == 200, switched.text
    removed = client.delete(
        f"/api/v1/providers/alpha/models/m2?expected_version={switched.json()['config_version']}&confirm=true"
    )
    assert removed.status_code == 200, removed.text
    assert "alpha/m2" not in client.get("/api/v1/models").json()["models"]


def test_set_default_external_env_is_runtime_only(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-8: LLM_MODEL 由外部 env 拥有 → runtime-only（persistence=process，不写 .env）。"""
    engine, _ = build_test_engine([])
    env_file = tmp_path / ".env"
    monkeypatch.setenv("LFL_ENV_FILE", str(env_file))
    monkeypatch.setenv("LLM_MODEL", "boot/frozen-model")
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    changed = client.post("/api/v1/providers/default-model", json={"model": "alpha/m1"})
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["runtime_default_model"] == "alpha/m1"
    assert body["default"]["persistence"] == "process"
    assert body["default_persistence"] == "process"
    assert not env_file.exists(), "外部 env 拥有时不得写 .env"
    assert engine.llm_pool.get_default_ref() == "alpha/m1"
    # 配置默认仍是外部 env 值；重启后由外部环境决定（如实标注 restart_required）。
    assert body["configured_default_model"] == "boot/frozen-model"
    assert body["restart_required"] is True


def test_default_change_does_not_override_existing_session(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-9: 旧会话显式 override 不被默认切换改写；/models 如实标注来源。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    sid = engine.session.create(model_override="alpha/m1", model_override_source="user")
    engine.session.set_shared_current(sid)

    switched = client.post("/api/v1/providers/default-model", json={"model": "alpha/m1"})
    assert switched.status_code == 200
    sess = engine.session.load(sid)
    assert sess.model_override == "alpha/m1"
    assert sess.model_override_source == "user"
    models = client.get("/api/v1/models").json()
    assert models["current"] == "alpha/m1"
    assert models["current_source"] == "session"
    assert models["default"] == "alpha/m1"


def test_new_session_inherits_only_explicit_user_override(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-10/§5.4: 只有 source=="user" 的覆盖可被新会话继承（一跳即止）。"""
    from llm_loop.web.routes import _new_session_model_override

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201

    # 无共享会话 → None（用 live 默认）。
    assert _new_session_model_override(engine, None) == (None, None)

    # 显式选择（user）→ 继承一跳，标记 inherit。
    s1 = engine.session.create(model_override="alpha/m1", model_override_source="user")
    engine.session.set_shared_current(s1)
    assert _new_session_model_override(engine, None) == ("alpha/m1", "inherit")

    # inherit 态不再继续传播（切默认后新会话用默认）。
    s2 = engine.session.create(model_override="alpha/m1", model_override_source="inherit")
    engine.session.set_shared_current(s2)
    assert _new_session_model_override(engine, None) == (None, None)

    # 旧数据（override 存在、无 source 键）读取时追认 user（design §5.4 兼容）。
    s3 = engine.session.create(model_override="alpha/m1")
    engine.session.set_shared_current(s3)
    loaded = engine.session.load(s3)
    assert loaded.model_override_source == "user"
    assert _new_session_model_override(engine, None) == ("alpha/m1", "inherit")

    # 本请求显式选模型 → user。
    assert _new_session_model_override(engine, "alpha/m1") == ("alpha/m1", "user")


def test_session_model_endpoint_sets_and_clears_override(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§7.6: POST /sessions/{id}/model 设置/清除会话覆盖。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    sid = engine.session.create()
    engine.session.set_shared_current(sid)

    unknown = client.post(f"/api/v1/sessions/{sid}/model", json={"model": "nope/x"})
    assert unknown.status_code == 404
    assert unknown.json()["error"] == "model_not_found"

    set_ref = client.post(f"/api/v1/sessions/{sid}/model", json={"model": "alpha/m1"})
    assert set_ref.status_code == 200, set_ref.text
    assert set_ref.json() == {
        "session_id": sid,
        "model": "alpha/m1",
        "source": "user",
        "available": True,
    }
    sess = engine.session.load(sid)
    assert sess.model_override == "alpha/m1"
    assert sess.model_override_source == "user"

    cleared = client.post(f"/api/v1/sessions/{sid}/model", json={"model": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["model"] is None
    assert cleared.json()["source"] is None
    sess = engine.session.load(sid)
    assert sess.model_override is None
    assert sess.model_override_source is None


def test_providers_updated_fingerprint_changes_on_catalog_and_default(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-11: providers 指纹（配置版本+live 默认+代数）随目录/默认变化。"""
    from llm_loop.web.routes import _providers_events_fingerprint

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    fp0, payload0 = _providers_events_fingerprint(engine)

    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    fp1, payload1 = _providers_events_fingerprint(engine)
    assert fp1 != fp0
    assert payload1["config_version"] == created.json()["config_version"]
    assert payload1["type"] == "providers_updated"

    changed = client.post("/api/v1/providers/default-model", json={"model": "alpha/m1"})
    assert changed.status_code == 200
    fp2, payload2 = _providers_events_fingerprint(engine)
    assert fp2 != fp1, "默认切换必须反映在 providers 指纹（default_model 字段）"
    assert payload2["default_model"] == "alpha/m1"


def _install_mock_transport(monkeypatch, handler) -> dict:
    """给 discover 注入 httpx.MockTransport；返回请求记录 dict."""
    import httpx

    seen: dict[str, object] = {}

    def transport(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return handler(request)

    def factory():
        return httpx.Client(
            timeout=10.0, follow_redirects=False, transport=httpx.MockTransport(transport)
        )

    from llm_loop.web import provider_admin

    monkeypatch.setattr(provider_admin, "_new_discover_http_client", factory)
    return seen


def test_discover_models_openai_and_anthropic(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-12: openai/anthropic 候选解析；不写任何配置。"""
    import httpx

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)

    def openai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "glm-5.3"}, {"id": "glm-5.3"}, {"id": "gpt-x"}]},
        )

    seen = _install_mock_transport(monkeypatch, openai_handler)
    found = client.post(
        "/api/v1/providers/discover-models",
        json={
            "base_url": "https://api.glm.example/v1",
            "wire_protocol": "openai",
            "api_key": "sk-discover-secret",
        },
    )
    assert found.status_code == 200, found.text
    assert [c["id"] for c in found.json()["candidates"]] == ["glm-5.3", "gpt-x"]
    assert str(seen["url"]).endswith("/v1/models")
    assert "Bearer sk-discover-secret" in str(seen["headers"].get("authorization", ""))
    # 只返回候选：不写配置文件。
    assert not (Path(engine.settings.data_dir) / "providers.local.json").exists()

    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "claude-x", "display_name": "Claude X"}]},
        )

    _install_mock_transport(monkeypatch, anthropic_handler)
    found2 = client.post(
        "/api/v1/providers/discover-models",
        json={
            "base_url": "https://api.anthropic.example",
            "wire_protocol": "anthropic",
            "api_key": "sk-ant",
        },
    )
    assert found2.status_code == 200, found2.text
    assert found2.json()["candidates"][0]["name"] == "Claude X"

    # 短路径别名（委派口径）行为一致。
    found3 = client.post(
        "/api/v1/providers/discover",
        json={"base_url": "https://api.glm.example/v1", "wire_protocol": "openai"},
    )
    assert found3.status_code == 200, found3.text

    # 不支持的协议如实拒绝（google/lms-chat）。
    unsupported = client.post(
        "/api/v1/providers/discover-models",
        json={"base_url": "https://g.example", "wire_protocol": "google"},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"] == "unsupported_protocol"


def test_discover_models_redacts_secret_and_bounds_response(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§9.2-13: 跨 host 重定向拒绝；错误不反射密钥；超大响应拒绝。"""
    import httpx

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example/v1/models"})

    _install_mock_transport(monkeypatch, redirect_handler)
    redirected = client.post(
        "/api/v1/providers/discover-models",
        json={
            "base_url": "https://api.glm.example/v1",
            "wire_protocol": "openai",
            "api_key": "sk-cross-host-secret",
        },
    )
    assert redirected.status_code == 502
    assert redirected.json()["error"] == "discovery_failed"
    assert "跨 host" in redirected.json()["detail"]
    assert "sk-cross-host-secret" not in redirected.text

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "BODY-SECRET-MATERIAL"})

    _install_mock_transport(monkeypatch, error_handler)
    denied = client.post(
        "/api/v1/providers/discover-models",
        json={
            "base_url": "https://api.glm.example/v1",
            "wire_protocol": "openai",
            "api_key": "sk-http-secret",
        },
    )
    assert denied.status_code == 502
    assert "HTTP 401" in denied.json()["detail"]
    assert "BODY-SECRET-MATERIAL" not in denied.text
    assert "sk-http-secret" not in denied.text

    def huge_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data": [' + b'{"id": "m"},' * 700_000 + b"{}]}")

    _install_mock_transport(monkeypatch, huge_handler)
    huge = client.post(
        "/api/v1/providers/discover-models",
        json={"base_url": "https://api.glm.example/v1", "wire_protocol": "openai"},
    )
    assert huge.status_code == 502
    assert "上限" in huge.json()["detail"]


def test_unknown_provider_fields_preserved_on_replace(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """FR-13/§9.2-14: 整包替换保留 provider 级 schema 外未知字段（疑似密钥除外）。"""
    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    local = Path(engine.settings.data_dir) / "providers.local.json"
    raw = json.loads(local.read_text(encoding="utf-8"))
    raw["alpha"]["x_operator_hint"] = "keep"
    raw["alpha"]["api_key"] = "plaintext-must-drop"
    local.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    version = client.get("/api/v1/providers").json()["config_version"]

    replaced = client.put(
        "/api/v1/providers/alpha",
        json={"expected_version": version, "provider": _provider("alpha")},
    )
    assert replaced.status_code == 200, replaced.text
    raw_after = json.loads(local.read_text(encoding="utf-8"))
    assert raw_after["alpha"]["x_operator_hint"] == "keep"
    assert "api_key" not in raw_after["alpha"]
    # 快照永不回显明文（即使手写配置里有）。
    assert "plaintext-must-drop" not in replaced.text


def test_registry_reload_failure_rolls_back_file_and_runtime(
    build_test_engine, tmp_path, monkeypatch
) -> None:
    """§7.4/FR-15: 写文件后 reload 失败 → 文件与内存 Registry 回滚到修改前。"""
    import llm_loop.llm.providers as providers_module

    engine, _ = build_test_engine([])
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    client = _client(engine)
    created = client.post(
        "/api/v1/providers",
        json={"expected_version": "missing", "provider": _provider("alpha")},
    )
    assert created.status_code == 201
    local = Path(engine.settings.data_dir) / "providers.local.json"
    before_bytes = local.read_bytes()
    before_registry = engine.llm_pool.registry_snapshot()
    before_generation = engine.llm_pool.registry_generation()

    def broken_load(_settings):
        raise RuntimeError("injected reload failure")

    original_load = providers_module.load_registry
    monkeypatch.setattr(providers_module, "load_registry", broken_load)
    failed = client.delete(
        f"/api/v1/providers/alpha?expected_version={created.json()['config_version']}&confirm=true"
    )
    assert failed.status_code == 500
    assert failed.json()["error"] == "provider_reload_failed"
    assert "已恢复" in failed.json()["detail"]
    assert local.read_bytes() == before_bytes, "配置文件必须回滚到修改前字节"
    assert engine.llm_pool.registry_snapshot() is before_registry, "内存 Registry 未被替换"
    assert engine.llm_pool.registry_generation() == before_generation
    # 回滚后操作可继续（锁/状态未被破坏；只还原注入的 load_registry，不动其它 patch）。
    monkeypatch.setattr(providers_module, "load_registry", original_load)
    still_there = client.get("/api/v1/providers").json()
    assert still_there["source"] == "local"
    assert [p["id"] for p in still_there["providers"]] == ["alpha"]
