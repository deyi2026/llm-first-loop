from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESTART = ROOT / "scripts" / "restart_mirror.sh"


def test_official_restart_routes_web_and_feishu_through_runtime_launch() -> None:
    src = RESTART.read_text(encoding="utf-8")
    web = src.split("_start_web()", 1)[1].split("\n}", 1)[0]
    feishu = src.split("_start_feishu()", 1)[1].split("\n}", 1)[0]

    assert '-m llm_loop.runtime.launch web' in web
    assert '-m llm_loop.runtime.launch feishu' in feishu
    assert '-m llm_loop.web' not in web
    assert '-m llm_loop.feishu' not in feishu


def test_runtime_launch_keeps_manifest_and_real_settings_on_one_toml_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.config import load_settings
    from llm_loop.runtime import launch as launch_mod
    from llm_loop.runtime.manifest import read_manifest

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    data_dir = tmp_path / "runtime-data"
    (runtime_root / "runtime.toml").write_text(
        "\n".join(
            [
                "[llm]",
                'model = "glm/toml-model"',
                'base_url = "http://127.0.0.1:9/v1"',
                "[runtime]",
                f'data_dir = "{data_dir}"',
                "history_max_chars = 333333",
                "[web]",
                "port = 8991",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_root / ".env").write_text(
        "\n".join(
            [
                "LLM_MODEL=glm/dotenv-model",
                "LLM_BASE_URL=http://dotenv.invalid/v1",
                "HISTORY_MAX_CHARS=222222",
                "WEB_PORT=8992",
                "LLM_API_KEY=dotenv-secret-placeholder",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(ROOT))
    monkeypatch.setenv("LFL_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("LLM_MODEL", "glm/stale-shell")
    monkeypatch.setenv("LLM_BASE_URL", "http://stale.invalid/v1")
    monkeypatch.setenv("HISTORY_MAX_CHARS", "111111")
    monkeypatch.setenv("WEB_PORT", "8993")
    monkeypatch.setenv("LLM_API_KEY", "shell-secret-placeholder")
    monkeypatch.delenv("LFL_ALLOW_RUNTIME_OVERRIDE", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)

    observed: dict[str, object] = {}

    def fake_run_module(mod: str, run_name: str) -> dict[str, object]:
        settings = load_settings()
        observed.update(
            {
                "module": mod,
                "run_name": run_name,
                "llm_model": settings.llm_model,
                "llm_base_url": settings.llm_base_url,
                "history_max_chars": settings.history_max_chars,
                "data_dir": settings.data_dir,
                "web_port": os.environ.get("WEB_PORT"),
            }
        )
        return {}

    monkeypatch.setattr(launch_mod.runpy, "run_module", fake_run_module)
    saved = dict(os.environ)
    try:
        rc = launch_mod.main(["web"])
        manifest = read_manifest(data_dir)
    finally:
        os.environ.clear()
        os.environ.update(saved)

    assert rc == 0
    assert observed == {
        "module": "llm_loop.web",
        "run_name": "__main__",
        "llm_model": "glm/toml-model",
        "llm_base_url": "http://127.0.0.1:9/v1",
        "history_max_chars": 333333,
        "data_dir": str(data_dir.resolve()),
        "web_port": "8991",
    }
    assert manifest is not None
    assert manifest["model_ref"] == "glm/toml-model"
    assert manifest["history_budget_chars"] == "333333"
    assert manifest["config_sources"]["LLM_MODEL"] == "runtime_toml"
    assert manifest["config_sources"]["HISTORY_MAX_CHARS"] == "runtime_toml"
    assert manifest["config_sources"]["WEB_PORT"] == "runtime_toml"
    dumped = json.dumps(manifest, ensure_ascii=False)
    assert "stale-shell" not in dumped
    assert "dotenv-model" not in dumped
    assert "secret-placeholder" not in dumped


def test_restart_pid_fallbacks_cover_legacy_and_canonical_launch_argv() -> None:
    src = RESTART.read_text(encoding="utf-8")
    web_pid_body = src.split("_mirror_web_pids()", 1)[1].split("\n}", 1)[0]
    feishu_pid_body = src.split("_feishu_pids()", 1)[1].split("\n}", 1)[0]

    assert "llm_loop\\.web" in web_pid_body
    assert "llm_loop\\.runtime\\.launch web" in web_pid_body
    assert "llm_loop\\.feishu" in feishu_pid_body
    assert "llm_loop\\.runtime\\.launch feishu" in feishu_pid_body
