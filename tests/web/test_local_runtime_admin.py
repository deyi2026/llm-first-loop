"""本地运行时（lfrt）管理面：状态聚合、动作门控、job 生命周期与注册表自动同步。"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import llm_loop.web.local_runtime_admin as lra
from llm_loop.web import build_app

STATUS_DATA = {
    "launchd": {"state": "running", "pid": 63923},
    "process": {"pid": 63923, "rss_mb": 55500},
    "server": {"port_listening": True, "health": True,
               "model_ids": ["qwen3.8-flash-next"], "model_count": 1},
    "config": {
        "backend": "llama", "model_path": "/m/Qwen3.8-Flash-Next-00001-of-00003.gguf",
        "alias": "qwen3.8-flash-next", "ctx": 65536, "port": 8901,
        "shards": {"count": 3, "present": 3, "size_gb": 76.3, "ok": True, "missing": []},
    },
    "memory": {"free_gb": 12.4, "used_pct": 80.5},
}

MODELS_DATA = {
    "active_path": "/m/unsloth/Qwen3.8-Flash-Next-GGUF",
    "models": [
        {"name": "unsloth/Qwen3.8-Flash-Next-GGUF", "path": "/m/unsloth/Qwen3.8-Flash-Next-GGUF",
         "size_gb": 77.2,
         "gguf": {"first_shard": "Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf",
                  "shards": "3/3", "shards_ok": True, "mmproj": True},
         "active": True},
        {"name": "lmstudio-community/Qwen3.8-27B-MLX-8bit",
         "path": "/m/lmstudio-community/Qwen3.8-27B-MLX-8bit", "size_gb": 27.5,
         "active": False},
    ],
}


def _payload(argv_tail):
    if argv_tail[:2] == ["status", "--json"]:
        return STATUS_DATA
    if argv_tail[:2] == ["models", "--json"]:
        return MODELS_DATA
    raise AssertionError(f"unexpected argv {argv_tail}")


@pytest.fixture
def client(build_test_engine, fake_settings, tmp_path, monkeypatch) -> TestClient:
    engine, _ = build_test_engine([])
    monkeypatch.setattr(lra, "_lfrt_path", lambda _engine: "/fake/lfrt")
    monkeypatch.setattr(lra, "_stashed_backends", lambda _engine: ["mlx"])

    def fake_run(_engine, argv_tail, timeout_s):
        return 0, json.dumps({"ok": True, "data": _payload(argv_tail)})

    monkeypatch.setattr(lra, "_run_lfrt", fake_run)
    return TestClient(build_app(engine=engine))


def _create_local_provider(client: TestClient, provider_id: str = "cognilocal") -> None:
    created = client.post(
        "/api/v1/providers",
        json={
            "expected_version": "missing",
            "provider": {
                "id": provider_id,
                "enabled": True,
                "base_url": "http://localhost:8901/v1",
                "api_key_env": "",
                "default_model": "",
                "timeout_s": 600,
                "models": [
                    {"id": "qwen3.8-flash-next", "enabled": True, "context": 65536,
                     "max_tokens": 4096, "cost_tier": "free", "wire_protocol": "openai"}
                ],
            },
        },
    )
    assert created.status_code == 201, created.text


class _FakeProc:
    def __init__(self, lines=None, rc=0):
        self.stdout = io.StringIO("".join(line + "\n" for line in (lines or ["switch plan:", "ok"])))
        self._rc = rc
        self.killed = False

    def wait(self, timeout=None):
        return self._rc

    def kill(self):
        self.killed = True


def test_status_merges_runtime_and_model_catalog(client):
    body = client.get("/api/v1/local-runtime").json()
    assert body["backend"] == "llama"
    assert body["port"] == 8901
    assert body["alias"] == "qwen3.8-flash-next"
    assert body["wire_model_ids"] == ["qwen3.8-flash-next"]
    assert body["stashed_backends"] == ["mlx"]
    kinds = {m["name"]: m["kind"] for m in body["models"]}
    assert kinds["unsloth/Qwen3.8-Flash-Next-GGUF"] == "gguf"
    assert kinds["lmstudio-community/Qwen3.8-27B-MLX-8bit"] == "mlx"
    assert [m["name"] for m in body["models"] if m["active"]] == [
        "unsloth/Qwen3.8-Flash-Next-GGUF"]
    assert body["state"]["health"] is True
    # 还没有指向 8901 的 provider：不臆造入口
    assert body["provider"] is None
    assert body["suggested_model_ref"] is None


def test_status_links_provider_by_loopback_port(client):
    _create_local_provider(client)
    body = client.get("/api/v1/local-runtime").json()
    assert body["provider"] == {"id": "cognilocal", "base_url": "http://localhost:8901/v1"}
    assert body["suggested_model_ref"] == "cognilocal/qwen3.8-flash-next"


def test_switch_model_rejects_unknown_model(client):
    resp = client.post("/api/v1/local-runtime/jobs",
                       json={"action": "switch_model", "model": "org/nowhere-GGUF"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_model"


def test_stop_requires_explicit_confirm(client):
    resp = client.post("/api/v1/local-runtime/jobs", json={"action": "stop"})
    assert resp.status_code == 428
    assert resp.json()["error"] == "confirm_required"


def test_switch_backend_rejects_noop_and_bad_value(client):
    assert client.post("/api/v1/local-runtime/jobs",
                       json={"action": "switch_backend", "backend": "llama"}
                       ).json()["error"] == "backend_noop"
    assert client.post("/api/v1/local-runtime/jobs",
                       json={"action": "switch_backend", "backend": "vllm"}
                       ).status_code == 400


def _drain_job(client: TestClient, job_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/local-runtime/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    pytest.fail(f"job did not finish in {timeout_s:.1f}s")


def test_switch_job_runs_lfrt_and_syncs_registry_preserving_custom_fields(
        client, fake_settings, monkeypatch):
    _create_local_provider(client)
    procs = []
    monkeypatch.setattr(lra.subprocess, "Popen",
                        lambda *a, **k: procs.append(_FakeProc(["switch plan:", "warmup ok"]))
                        or procs[-1])
    resp = client.post("/api/v1/local-runtime/jobs",
                       json={"action": "switch_model",
                             "model": "unsloth/Qwen3.8-Flash-Next-GGUF"})
    assert resp.status_code == 202, resp.text
    job = resp.json()["job"]
    assert job["status"] in {"running", "done"}  # fake Popen 可瞬间完成
    done = _drain_job(client, job["id"])
    assert done["status"] == "done", done
    assert done["rc"] == 0
    assert "warmup ok" in done["output_tail"]
    assert done["result"]["registry_synced"] is True
    assert done["result"]["model_ref"] == "cognilocal/qwen3.8-flash-next"
    # 注册表：默认字段补齐，运维自定义（max_tokens=4096）原样保留
    local = json.loads((Path(fake_settings.data_dir) / "providers.local.json").read_text())
    spec = local["cognilocal"]["models"]["qwen3.8-flash-next"]
    assert spec["max_tokens"] == 4096
    assert spec["context"] == 65536
    assert spec["wire_protocol"] == "openai"
    # 注册表为源：表单创建时显式写的 false 属于运维事实，sync 不改写；
    # 只补缺失键（send_tool_choice / reasoning_replay / temperature）。
    assert spec["reasoning_capable"] is False
    assert spec["send_tool_choice"] is True
    assert spec["temperature"] == 0.0  # 缺失键由 sync 补缺省


def test_registry_sync_reports_missing_provider(client):
    result = lra.sync_provider_model(client.app.state.engine)
    assert result == {"registry_synced": False, "reason": "no_provider_on_port_8901"}


def test_one_long_action_at_a_time(client, monkeypatch):
    with lra._JOBS_LOCK:
        lra._JOBS["busyjob"] = {
            "id": "busyjob", "action": "restart", "label": "重启服务", "detail": "",
            "status": "running", "started_at": time.time(), "duration_s": 0.0,
            "rc": None, "lines": [], "result": None, "error": None,
        }
    try:
        resp = client.post("/api/v1/local-runtime/jobs",
                           json={"action": "restart"})
        assert resp.status_code == 409
        assert resp.json()["error"] == "job_busy"
    finally:
        with lra._JOBS_LOCK:
            lra._JOBS.pop("busyjob", None)


def test_failed_lfrt_exit_marks_job_failed(client, monkeypatch):
    monkeypatch.setattr(lra.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(["REFUSED: ..."], rc=2))
    resp = client.post("/api/v1/local-runtime/jobs", json={"action": "restart"})
    job = resp.json()["job"]
    done = _drain_job(client, job["id"])
    assert done["status"] == "failed"
    assert "退出码 2" in done["error"]


def test_base_url_port_only_matches_loopback():
    assert lra._base_url_port("http://localhost:8901/v1") == 8901
    assert lra._base_url_port("http://127.0.0.1:8901/v1") == 8901
    assert lra._base_url_port("https://api.example.com:8901/v1") is None
    assert lra._base_url_port("http://10.0.0.5:8901/v1") is None
