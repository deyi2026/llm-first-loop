"""P0 file-backed runtime configuration contracts on the current dual-root main."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.config import load_settings
from llm_loop.runtime.resolver import (
    RuntimeConfig,
    legacy_settings_snapshot,
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


def test_service_scoped_semantic_runtime_toml_overrides_global_and_dotenv(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[semantic]
memory = true
archive = false
method = false
docs = false
experience = false

[semantic.web]
experience = true

[semantic.feishu]
docs = true
""",
    )
    (tmp_path / ".env").write_text(
        "SEMANTIC_MEMORY_ENABLED=0\n"
        "SEMANTIC_DOCS_ENABLED=0\n"
        "SEMANTIC_EXPERIENCE_ENABLED=0\n",
        encoding="utf-8",
    )

    web = resolve_effective("web", env={}, workspace_root=tmp_path)
    feishu = resolve_effective("feishu", env={}, workspace_root=tmp_path)
    learning = resolve_effective("learning", env={}, workspace_root=tmp_path)

    assert web.values["SEMANTIC_MEMORY_ENABLED"] == "1"
    assert web.values["SEMANTIC_EXPERIENCE_ENABLED"] == "1"
    assert web.values["SEMANTIC_DOCS_ENABLED"] == "0"
    assert web.sources["SEMANTIC_MEMORY_ENABLED"] == "runtime_toml"
    assert web.sources["SEMANTIC_EXPERIENCE_ENABLED"] == "runtime_toml_service:web"

    assert feishu.values["SEMANTIC_MEMORY_ENABLED"] == "1"
    assert feishu.values["SEMANTIC_DOCS_ENABLED"] == "1"
    assert feishu.values["SEMANTIC_EXPERIENCE_ENABLED"] == "0"
    assert feishu.sources["SEMANTIC_DOCS_ENABLED"] == "runtime_toml_service:feishu"

    assert learning.values["SEMANTIC_MEMORY_ENABLED"] == "1"
    assert learning.values["SEMANTIC_DOCS_ENABLED"] == "0"
    assert learning.values["SEMANTIC_EXPERIENCE_ENABLED"] == "0"
    assert learning.sources["SEMANTIC_DOCS_ENABLED"] == "runtime_toml"


def test_service_scoped_chatgpt_web_is_visible_only_to_web(tmp_path: Path) -> None:
    _runtime_toml(
        tmp_path,
        """
[chatgpt_web.web]
enabled = true
cdp_endpoint = "http://127.0.0.1:9229"
project_url = "https://chatgpt.com/g/g-project/project"
project_ref = "g-project"
project_name = "LFL Web Project"
profile_label = "lfl-web-gpt-production"
turn_timeout_s = 120
reasoning_effort = "high"
context_tokens = 262144
max_request_chars = 150000
""",
    )

    web = resolve_effective("web", env={}, workspace_root=tmp_path)
    feishu = resolve_effective("feishu", env={}, workspace_root=tmp_path)
    learning = resolve_effective("learning", env={}, workspace_root=tmp_path)

    assert web.values["CHATGPT_WEB_ENABLED"] == "1"
    assert web.values["CHATGPT_WEB_CDP_ENDPOINT"] == "http://127.0.0.1:9229"
    assert web.values["CHATGPT_WEB_PROJECT_REF"] == "g-project"
    assert web.values["CHATGPT_WEB_PROFILE_LABEL"] == "lfl-web-gpt-production"
    assert web.values["CHATGPT_WEB_TURN_TIMEOUT_S"] == "120"
    assert web.values["CHATGPT_WEB_REASONING_EFFORT"] == "high"
    assert web.values["CHATGPT_WEB_CONTEXT_TOKENS"] == "262144"
    assert web.values["CHATGPT_WEB_MAX_REQUEST_CHARS"] == "150000"
    assert web.sources["CHATGPT_WEB_ENABLED"] == "runtime_toml_service:web"

    assert "CHATGPT_WEB_ENABLED" not in feishu.values
    assert "CHATGPT_WEB_PROJECT_REF" not in feishu.values
    assert "CHATGPT_WEB_ENABLED" not in learning.values
    assert "CHATGPT_WEB_PROJECT_REF" not in learning.values


def test_service_scoped_deepseek_web_is_visible_only_to_web(tmp_path: Path) -> None:
    _runtime_toml(
        tmp_path,
        """
[deepseek_web.web]
enabled = true
cdp_endpoint = "http://127.0.0.1:9229"
root_url = "https://chat.deepseek.com/"
profile_label = "lfl-web-deepseek-production"
turn_timeout_s = 120
reasoning_effort = "high"
context_tokens = 131072
max_request_chars = 100000
""",
    )

    web = resolve_effective("web", env={}, workspace_root=tmp_path)
    feishu = resolve_effective("feishu", env={}, workspace_root=tmp_path)
    learning = resolve_effective("learning", env={}, workspace_root=tmp_path)

    assert web.values["DEEPSEEK_WEB_ENABLED"] == "1"
    assert web.values["DEEPSEEK_WEB_CDP_ENDPOINT"] == "http://127.0.0.1:9229"
    assert web.values["DEEPSEEK_WEB_ROOT_URL"] == "https://chat.deepseek.com/"
    assert web.values["DEEPSEEK_WEB_PROFILE_LABEL"] == "lfl-web-deepseek-production"
    assert web.values["DEEPSEEK_WEB_TURN_TIMEOUT_S"] == "120"
    assert web.values["DEEPSEEK_WEB_REASONING_EFFORT"] == "high"
    assert web.values["DEEPSEEK_WEB_CONTEXT_TOKENS"] == "131072"
    assert web.values["DEEPSEEK_WEB_MAX_REQUEST_CHARS"] == "100000"
    assert web.sources["DEEPSEEK_WEB_ENABLED"] == "runtime_toml_service:web"

    assert "DEEPSEEK_WEB_ENABLED" not in feishu.values
    assert "DEEPSEEK_WEB_ROOT_URL" not in feishu.values
    assert "DEEPSEEK_WEB_ENABLED" not in learning.values
    assert "DEEPSEEK_WEB_ROOT_URL" not in learning.values


def test_service_scoped_deepseek_web_rejects_non_web_service(tmp_path: Path) -> None:
    bad = tmp_path / "bad-deepseek-service.toml"
    bad.write_text("[deepseek_web.feishu]\nenabled = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知服务级 deepseek_web scope"):
        parse_runtime_toml(bad, service="web")


def test_service_scoped_chatgpt_web_rejects_non_web_service(tmp_path: Path) -> None:
    bad = tmp_path / "bad-chatgpt-service.toml"
    bad.write_text("[chatgpt_web.feishu]\nenabled = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知服务级 chatgpt_web scope"):
        parse_runtime_toml(bad, service="web")


def test_service_scoped_semantic_keeps_cli_and_explicit_shell_override_priority(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[semantic]
docs = false
[semantic.feishu]
docs = true
""",
    )

    shell = resolve_effective(
        "feishu",
        env={"LFL_ALLOW_RUNTIME_OVERRIDE": "1", "SEMANTIC_DOCS_ENABLED": "0"},
        workspace_root=tmp_path,
    )
    cli = resolve_effective(
        "feishu",
        cli_overrides={"SEMANTIC_DOCS_ENABLED": "0"},
        env={"LFL_ALLOW_RUNTIME_OVERRIDE": "1", "SEMANTIC_DOCS_ENABLED": "1"},
        workspace_root=tmp_path,
    )

    assert shell.values["SEMANTIC_DOCS_ENABLED"] == "0"
    assert shell.sources["SEMANTIC_DOCS_ENABLED"] == "shell_override"
    assert cli.values["SEMANTIC_DOCS_ENABLED"] == "0"
    assert cli.sources["SEMANTIC_DOCS_ENABLED"] == "cli"


def test_service_scoped_semantic_schema_rejects_unknown_service_and_field(
    tmp_path: Path,
) -> None:
    bad_service = tmp_path / "bad-service.toml"
    bad_service.write_text("[semantic.cli]\ndocs = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知服务级 semantic scope"):
        parse_runtime_toml(bad_service, service="web")

    bad_field = tmp_path / "bad-field.toml"
    bad_field.write_text("[semantic.web]\nmagic = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知字段"):
        parse_runtime_toml(bad_field, service="web")



def test_history_policy_runtime_toml_beats_stale_shell_and_reaches_settings(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[llm]
model = "glm/file"
base_url = "https://example.invalid/v1"
[history]
working_set_receipts = true
working_set_batch_chars = 65536
working_set_grace_groups = 2
working_set_soft_result_cap = 7
working_set_hard_result_cap = 19
working_set_min_net_gain_chars = 1234
compress_target_ratio = 0.54
compact_ratio = 0.82
nudge_growth_chars = 23456
head_keep_ratio = 0.33
head_keep_force_ratio = 0.44
head_keep_target_ratio = 0.66
""",
    )
    ec = resolve_effective(
        "web",
        env={
            "COMPACT_RATIO": "0.20",
            "HEAD_KEEP_RATIO": "0.99",
            "LFL_TOOL_WORKING_SET_BATCH_CHARS": "4096",
        },
        workspace_root=tmp_path,
    )
    snapshot = legacy_settings_snapshot(
        ec,
        base_env={
            "LLM_API_KEY": "local-eval",
            "DATA_DIR": str(tmp_path / "isolated-data"),
            "COMPACT_RATIO": "0.20",
            "HEAD_KEEP_RATIO": "0.99",
        },
    )
    settings = load_settings(snapshot)

    assert ec.sources["COMPACT_RATIO"] == "runtime_toml"
    assert ec.sources["HEAD_KEEP_RATIO"] == "runtime_toml"
    assert ec.ignored_shell_env["COMPACT_RATIO"] == "0.20"
    hp = settings.history_policy
    assert hp.working_set_receipts is True
    assert hp.working_set_batch_chars == 65536
    assert hp.working_set_grace_groups == 2
    assert hp.working_set_soft_result_cap == 7
    assert hp.working_set_hard_result_cap == 19
    assert hp.working_set_min_net_gain_chars == 1234
    assert hp.compress_target_ratio == 0.54
    assert hp.compact_ratio == 0.82
    assert hp.nudge_growth_chars == 23456
    assert hp.head_keep_ratio == 0.33
    assert hp.head_keep_force_ratio == 0.44
    assert hp.head_keep_target_ratio == 0.66


def test_nonconvergence_runtime_toml_beats_stale_shell_and_reaches_settings(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[llm]
model = "glm/file"
base_url = "https://example.invalid/v1"
[tools]
nonconvergence_fuse_windows = 2
nonconvergence_fuse_jaccard = 0.75
nonconvergence_fuse_min_delta = 7
""",
    )
    ec = resolve_effective(
        "web",
        env={
            "LFL_NONCONV_FUSE_WINDOWS": "99",
            "LFL_NONCONV_FUSE_JACCARD": "0.2",
            "LFL_NONCONV_FUSE_MIN_DELTA": "1",
        },
        workspace_root=tmp_path,
    )
    snapshot = legacy_settings_snapshot(
        ec,
        base_env={
            "LLM_API_KEY": "local-eval",
            "DATA_DIR": str(tmp_path / "isolated-data"),
        },
    )
    settings = load_settings(snapshot)

    assert ec.sources["LFL_NONCONV_FUSE_WINDOWS"] == "runtime_toml"
    assert ec.sources["LFL_NONCONV_FUSE_JACCARD"] == "runtime_toml"
    assert ec.sources["LFL_NONCONV_FUSE_MIN_DELTA"] == "runtime_toml"
    assert ec.ignored_shell_env["LFL_NONCONV_FUSE_WINDOWS"] == "99"
    tr = settings.tool_runtime
    assert tr.nonconvergence_fuse_windows == 2
    assert tr.nonconvergence_fuse_jaccard == 0.75
    assert tr.nonconvergence_fuse_min_delta == 7


def test_retrieval_multiquery_mode_runtime_toml_beats_stale_shell_and_reaches_settings(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[llm]
model = "glm/file"
base_url = "https://example.invalid/v1"
[retrieval]
multiquery_mode = "shadow"
""",
    )
    ec = resolve_effective(
        "web",
        env={"RETRIEVAL_MULTIQUERY_MODE": "off"},
        workspace_root=tmp_path,
    )
    snapshot = legacy_settings_snapshot(
        ec,
        base_env={
            "LLM_API_KEY": "local-eval",
            "DATA_DIR": str(tmp_path / "isolated-data"),
        },
    )
    settings = load_settings(snapshot)

    assert ec.sources["RETRIEVAL_MULTIQUERY_MODE"] == "runtime_toml"
    assert ec.ignored_shell_env["RETRIEVAL_MULTIQUERY_MODE"] == "off"
    assert settings.retrieval_multiquery_mode == "shadow"


def test_retrieval_multiquery_mode_invalid_toml_value_fails_safe_to_off(
    tmp_path: Path,
) -> None:
    _runtime_toml(
        tmp_path,
        """
[llm]
model = "glm/file"
base_url = "https://example.invalid/v1"
[retrieval]
multiquery_mode = "bogus"
""",
    )
    ec = resolve_effective("web", env={}, workspace_root=tmp_path)
    snapshot = legacy_settings_snapshot(
        ec,
        base_env={
            "LLM_API_KEY": "local-eval",
            "DATA_DIR": str(tmp_path / "isolated-data"),
        },
    )
    settings = load_settings(snapshot)

    # toml 值原样通过 resolver（str 类型合法），非法枚举由 config fail-safe 回 off
    assert ec.values["RETRIEVAL_MULTIQUERY_MODE"] == "bogus"
    assert settings.retrieval_multiquery_mode == "off"


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
    # code_root is the real repo root; a gitignored runtime.toml may legitimately
    # pre-exist there on dev machines. The intent of the final assertion is
    # "dry-run never writes to code_root", so compare content, not existence.
    _code_toml = code_root / "runtime.toml"
    _pre = _code_toml.read_bytes() if _code_toml.exists() else None
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
    assert (_code_toml.read_bytes() if _code_toml.exists() else None) == _pre
