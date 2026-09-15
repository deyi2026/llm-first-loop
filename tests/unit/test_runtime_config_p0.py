"""P0 file-backed runtime configuration contracts on the current dual-root main."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.config import load_settings
from llm_loop.runtime.resolver import (
    RuntimeConfig,
    parse_runtime_toml,
    resolve_effective,
)


def _runtime_toml(root: Path, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "runtime.toml"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def test_dual_root_reads_runtime_toml_from_runtime_root_not_code_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    code_root = tmp_path / "code-worktree"
    code_root.mkdir()
    _runtime_toml(
        runtime_root,
        """
[llm]
model = "glm/glm-5.3"
base_url = "https://example.invalid/v1"
max_tokens = 16000
[runtime]
data_dir = "/tmp/lfl-p0-data"
history_max_chars = 184000
[web]
port = 8903
""",
    )

    ec = resolve_effective(
        "web",
        env={
            "LFL_RUNTIME_ROOT": str(runtime_root),
            "LFL_WORKSPACE_ROOT": str(code_root),
        },
    )

    assert isinstance(ec, RuntimeConfig)
    assert ec.runtime_root == str(runtime_root.resolve())
    assert ec.config_file == str((runtime_root / "runtime.toml").resolve())
    assert ec.toml_file == str((runtime_root / "runtime.toml").resolve())
    assert ec.env_file == str((runtime_root / ".env").resolve())
    assert ec.values["LLM_MODEL"] == "glm/glm-5.3"
    assert ec.values["LLM_BASE_URL"] == "https://example.invalid/v1"
    assert ec.values["LLM_MAX_TOKENS"] == "16000"
    assert ec.values["HISTORY_MAX_CHARS"] == "184000"
    assert ec.values["WEB_PORT"] == "8903"
    assert ec.sources["LLM_MODEL"] == "runtime_toml"
    assert not (code_root / "runtime.toml").exists()
    assert not (code_root / ".env").exists()


def test_runtime_toml_beats_legacy_dotenv_and_stale_shell_by_default(tmp_path: Path) -> None:
    _runtime_toml(tmp_path, '[llm]\nmodel = "glm/file"\n[web]\nport = 8903')
    (tmp_path / ".env").write_text("LLM_MODEL=glm/legacy\nWEB_PORT=8999\n", encoding="utf-8")

    ec = resolve_effective(
        "web",
        env={"LLM_MODEL": "glm/stale", "WEB_PORT": "8777"},
        workspace_root=tmp_path,
    )

    assert ec.values["LLM_MODEL"] == "glm/file"
    assert ec.values["WEB_PORT"] == "8903"
    assert ec.sources["LLM_MODEL"] == "runtime_toml"
    assert ec.ignored_shell_env["LLM_MODEL"] == "glm/stale"


def test_runtime_override_requires_explicit_opt_in(tmp_path: Path) -> None:
    _runtime_toml(tmp_path, '[llm]\nmodel = "glm/file"')
    ec = resolve_effective(
        "web",
        env={"LLM_MODEL": "glm/override", "LFL_ALLOW_RUNTIME_OVERRIDE": "1"},
        workspace_root=tmp_path,
    )
    assert ec.values["LLM_MODEL"] == "glm/override"
    assert ec.sources["LLM_MODEL"] == "shell_override"


def test_runtime_toml_is_closed_schema_and_forbids_secret_fields(tmp_path: Path) -> None:
    secret = tmp_path / "secret.toml"
    secret.write_text('[llm]\napi_key = "placeholder"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="凭证|密钥"):
        parse_runtime_toml(secret)

    unknown = tmp_path / "unknown.toml"
    unknown.write_text('[runtime]\nmagic_policy = true\n', encoding="utf-8")
    with pytest.raises(ValueError, match="未知字段"):
        parse_runtime_toml(unknown)


def test_runtime_config_is_immutable_and_missing_toml_keeps_legacy_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("LLM_MODEL=glm/legacy\n", encoding="utf-8")
    ec = resolve_effective("web", env={}, workspace_root=tmp_path)
    assert isinstance(ec, RuntimeConfig)
    assert ec.values["LLM_MODEL"] == "glm/legacy"
    assert ec.sources["LLM_MODEL"] == "dotenv"
    assert ec.config_file == str((tmp_path / ".env").resolve())
    with pytest.raises(TypeError):
        ec.values["LLM_MODEL"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        ec.sources["LLM_MODEL"] = "mutated"  # type: ignore[index]
    import json
    assert json.loads(json.dumps(ec.sources))["LLM_MODEL"] == "dotenv"


def test_load_settings_accepts_explicit_snapshot_without_mutating_ambient_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", "ambient-wrong")
    before = dict(os.environ)
    explicit = dict(before)
    explicit.update(
        {
            "LLM_API_KEY": "local-eval",
            "LLM_BASE_URL": "http://127.0.0.1:9/v1",
            "LLM_MODEL": "explicit-model",
            "DATA_DIR": str(tmp_path / "isolated-data"),
            "HISTORY_MAX_CHARS": "123456",
        }
    )
    settings = load_settings(explicit)
    assert settings.llm_model == "explicit-model"
    assert settings.history_max_chars == 123456
    assert settings.data_dir == str((tmp_path / "isolated-data").resolve())
    assert dict(os.environ) == before


def test_explicit_runtime_config_path_missing_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="config|配置|不存在"):
        resolve_effective(
            "web",
            env={},
            workspace_root=tmp_path,
            config_file=tmp_path / "missing.toml",
        )


def test_launch_dry_run_uses_dual_root_runtime_toml_and_reports_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from llm_loop.runtime.launch import main as launch_main

    code_root = Path(__file__).resolve().parents[2]
    runtime_root = tmp_path / "runtime-root"
    _runtime_toml(
        runtime_root,
        f"""
[llm]
model = \"glm/dry-run\"
base_url = \"https://example.invalid/v1\"
[runtime]
data_dir = \"{tmp_path / 'isolated-data'}\"
[web]
port = 8991
""",
    )
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(code_root))
    monkeypatch.setenv("LFL_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("LLM_API_KEY", "local-eval")
    monkeypatch.delenv("PYTHONPATH", raising=False)

    rc = launch_main(["web", "--dry-run"])
    captured = capsys.readouterr()
    assert rc == 0
    assert str((runtime_root / "runtime.toml").resolve()) in captured.out
    assert '"LLM_MODEL": "runtime_toml"' in captured.out
    assert '"WEB_PORT": "runtime_toml"' in captured.out
    assert f'"runtime_root": "{runtime_root.resolve()}"' in captured.out
    assert "identity_ok=True" in captured.err
    assert "local-eval" not in captured.out
    assert "local-eval" not in captured.err
    assert not (code_root / "runtime.toml").exists()
