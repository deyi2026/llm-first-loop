from __future__ import annotations

import json
from pathlib import Path

from llm_loop.config import load_settings
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.resources.lfrt_runtime import make_lfrt_status_fn
from llm_loop.runtime.resolver import legacy_settings_snapshot, resolve_effective


def test_runtime_toml_projects_read_only_lfrt_settings(tmp_path: Path) -> None:
    (tmp_path / "runtime.toml").write_text(
        """
[llm]
model = "glm/glm-5.3"
base_url = "https://example.invalid/v1"
[runtime]
data_dir = "/tmp/lfrt-status-wiring"
[local_runtime]
observer = "lfrt"
cli = "/opt/lfrt/lfrt"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    effective = resolve_effective("web", env={}, workspace_root=tmp_path)
    env = legacy_settings_snapshot(
        effective,
        base_env={"LLM_API_KEY": "local-eval"},
    )

    settings = load_settings(env)

    assert settings.local_runtime_observer == "lfrt"
    assert settings.lfrt_cli == "/opt/lfrt/lfrt"
    assert effective.sources["LFL_LOCAL_RUNTIME_OBSERVER"] == "runtime_toml"
    assert effective.sources["LFL_LFRT_CLI"] == "runtime_toml"
    assert settings.to_status_dict()["local_runtime_observer"] == "lfrt"
    assert "/opt/lfrt/lfrt" not in str(settings.to_status_dict())


def test_local_runtime_dimension_is_on_demand_and_not_in_default_work() -> None:
    calls = []
    provider = ArchitectureStatusProvider()
    provider.set_local_runtime_fn(lambda: calls.append("called") or {"available": True, "pid": 7})

    default = provider.snapshot(dimensions=["current_phase"])
    assert "local_runtime" not in default
    assert calls == []

    local = provider.snapshot(dimensions=["local_runtime"])
    assert local["local_runtime"] == {"available": True, "pid": 7}
    assert calls == ["called"]


def test_local_runtime_dimension_fails_unknown_when_callback_fails() -> None:
    provider = ArchitectureStatusProvider()

    def boom():
        raise OSError("private path must not leak")

    provider.set_local_runtime_fn(boom)
    snap = provider.snapshot(dimensions=["local_runtime"])["local_runtime"]
    assert snap["available"] is False
    assert snap["status"] == "unknown"
    assert "private path" not in str(snap)


def test_lfrt_status_callback_projects_prompt_safe_facts(monkeypatch) -> None:
    payload = {
        "ok": True,
        "cmd": "status",
        "data": {
            "launchd": {"known": True, "registered": True, "state": "running", "pid": 7},
            "process": {
                "pid": 7,
                "flags": {
                    "model": "/models/Ornith",
                    "port": "8901",
                    "prompt-concurrency": "1",
                    "decode-concurrency": "1",
                },
            },
            "server": {
                "port_listening": True,
                "listener": {"known": True, "pid": 7},
                "health": True,
            },
            "config": {
                "model_path": "/models/Ornith",
                "aliases": ["ornith"],
                "concurrency": {"prompt": 1, "decode": 1},
                "port": 8901,
            },
        },
    }

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr("llm_loop.resources.lfrt_runtime.subprocess.run", fake_run)
    monkeypatch.setattr(
        "llm_loop.resources.lfrt_runtime._status_config_is_read_only_safe",
        lambda _path: True,
    )
    callback = make_lfrt_status_fn("/private/runtime/lfrt")
    view = callback()

    assert view["available"] is True
    assert view["pid"] == 7
    assert view["model"] == "Ornith"
    assert view["prompt_concurrency"] == 1
    assert view["drift"] is False
    assert "/private/runtime/lfrt" not in str(view)


def test_invalid_lfrt_cli_is_visible_as_unknown_without_startup_failure() -> None:
    view = make_lfrt_status_fn("relative/lfrt")()
    assert view == {
        "available": False,
        "observer": "lfrt",
        "status": "unknown",
        "reason": "invalid_configuration",
    }
