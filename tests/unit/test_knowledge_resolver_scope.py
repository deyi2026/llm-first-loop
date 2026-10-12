"""Service-scoped Knowledge Advisor config must reach the real Web Settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.config import load_settings
from llm_loop.runtime.resolver import (
    apply_to_environ,
    legacy_env_snapshot,
    resolve_effective,
)

_MODE = "LFL_KNOWLEDGE_ADVISOR"
_SESSIONS = "LFL_KNOWLEDGE_ADVISOR_SESSIONS"


def _write_config(tmp_path: Path, toml: str, *, dotenv_mode: str = "off") -> None:
    (tmp_path / "runtime.toml").write_text(toml, encoding="utf-8")
    (tmp_path / ".env").write_text(
        "\n".join([
            "LLM_API_KEY=offline-test-placeholder",
            "LLM_BASE_URL=https://offline.invalid/v1",
            "LLM_MODEL=glm/glm-5.3",
            f"DATA_DIR={tmp_path / 'data'}",
            f"{_MODE}={dotenv_mode}",
            f"{_SESSIONS}=historical-session-not-authorized",
        ]) + "\n",
        encoding="utf-8",
    )


def test_web_only_shadow_reaches_settings_with_scoped_provenance(tmp_path: Path) -> None:
    _write_config(
        tmp_path, '[knowledge_advisor.web]\nmode = "shadow"\nsessions = ""\n',
        dotenv_mode="canary",
    )
    ec = resolve_effective(
        "web", env={_MODE: "canary"}, workspace_root=tmp_path,
    )
    assert ec.values[_MODE] == "shadow"
    assert ec.values[_SESSIONS] == ""
    assert ec.sources[_MODE] == "runtime_toml_service:web"
    assert ec.sources[_SESSIONS] == "runtime_toml_service:web"
    assert ec.ignored_shell_env[_MODE] == "canary"
    settings = load_settings(legacy_env_snapshot(ec, base_env={}))
    assert settings.tool_runtime.knowledge_advisor_mode == "shadow"
    assert settings.tool_runtime.knowledge_advisor_sessions == ""


@pytest.mark.parametrize("service", ["feishu", "learning"])
def test_non_web_never_inherits_shadow_or_canary_from_dotenv_or_shell(
    tmp_path: Path, service: str,
) -> None:
    _write_config(
        tmp_path,
        '[knowledge_advisor.web]\nmode = "canary"\n'
        'sessions = "web-only-synthetic-session"\n',
        dotenv_mode="canary",
    )
    ec = resolve_effective(
        service,
        env={
            _MODE: "canary", _SESSIONS: "shell-unsafe-session",
            "LFL_ALLOW_RUNTIME_OVERRIDE": "1",
        },
        workspace_root=tmp_path,
    )
    assert ec.values[_MODE] == "off"
    assert ec.values[_SESSIONS] == ""
    assert ec.sources[_MODE] == "service_scope:disabled"
    assert ec.sources[_SESSIONS] == "service_scope:disabled"
    settings = load_settings(legacy_env_snapshot(ec, base_env={}))
    assert settings.tool_runtime.knowledge_advisor_mode == "off"
    assert settings.tool_runtime.knowledge_advisor_sessions == ""


def test_web_dotenv_mode_is_accepted_only_for_web(tmp_path: Path) -> None:
    _write_config(tmp_path, "", dotenv_mode="shadow")
    web = resolve_effective("web", env={}, workspace_root=tmp_path)
    assert web.values[_MODE] == "shadow"
    assert web.sources[_MODE] == "dotenv"
    feishu = resolve_effective("feishu", env={}, workspace_root=tmp_path)
    assert feishu.values[_MODE] == "off"
    assert feishu.sources[_MODE] == "service_scope:disabled"


def test_global_knowledge_advisor_toml_rejected_before_restart(tmp_path: Path) -> None:
    _write_config(tmp_path, '[knowledge_advisor]\nmode = "shadow"\n')
    with pytest.raises(ValueError, match="仅支持服务级"):
        resolve_effective("web", env={}, workspace_root=tmp_path)


def test_non_web_scoped_toml_is_rejected(tmp_path: Path) -> None:
    _write_config(tmp_path, '[knowledge_advisor.feishu]\nmode = "shadow"\n')
    with pytest.raises(ValueError, match="未知服务级"):
        resolve_effective("feishu", env={}, workspace_root=tmp_path)


def test_web_canary_allowlist_is_masked_in_dry_run_summary(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        '[knowledge_advisor.web]\nmode = "canary"\n'
        'sessions = "web-only-synthetic-session"\n',
    )
    ec = resolve_effective("web", env={}, workspace_root=tmp_path)
    assert ec.values[_SESSIONS] == "web-only-synthetic-session"
    summary_values = ec.to_summary()["values"]
    assert isinstance(summary_values, dict)
    assert str(summary_values[_SESSIONS]).startswith("<secret:")
    assert "web-only-synthetic-session" not in str(ec.to_summary())


def test_live_launch_style_env_projection_is_service_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, '[knowledge_advisor.web]\nmode = "shadow"\n')
    for service, expected in [("web", "shadow"), ("feishu", "off"), ("learning", "off")]:
        ec = resolve_effective(service, env={}, workspace_root=tmp_path)
        with monkeypatch.context() as scope:
            scope.setenv("LLM_API_KEY", "offline-test-placeholder")
            scope.setenv("LLM_BASE_URL", "https://offline.invalid/v1")
            scope.setenv("LLM_MODEL", "glm/glm-5.3")
            scope.setenv("DATA_DIR", str(tmp_path / "data"))
            scope.delenv(_MODE, raising=False)
            scope.delenv(_SESSIONS, raising=False)
            apply_to_environ(ec)
            assert os.environ[_MODE] == expected
            assert load_settings().tool_runtime.knowledge_advisor_mode == expected


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_resolved_mode_reaches_real_loop_without_shadow_prompt_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """Source config → resolved Settings → real LoopEngine fake provider wire."""
    from dataclasses import replace

    from llm_loop.core.trace_leak.ingress_token import issue_ingress
    from tests.unit.test_err1210_recovery import _mk, _resp

    config_root = tmp_path / "config"
    config_root.mkdir()
    _write_config(
        config_root,
        f'[knowledge_advisor.web]\nmode = "{mode}"\n',
    )
    ec = resolve_effective("web", env={}, workspace_root=config_root)
    resolved = load_settings(legacy_env_snapshot(ec, base_env={}))
    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    engine, fake = _mk(engine_root, monkeypatch, responses=[_resp("resolved")])
    engine.settings = replace(
        engine.settings, tool_runtime=resolved.tool_runtime,
    )
    seen: list[str] = []

    def search(*, kind: str, **_kw: object) -> list[dict[str, str]]:
        seen.append(kind)
        return {
            "method": [
                {"method_ref": "method:known-candidate", "status": "candidate",
                 "name": "repair pytest fixture environment"},
            ],
            "experience": [],
            "lesson": [],
        }[kind]

    # Use the actual registry adapter entrypoint, not a mock build function.
    corrections = engine.corrections
    assert corrections is not None
    corrections._search_records_fn = search  # noqa: SLF001
    sid = engine.session.create()
    result = engine.run(
        sid, "repair failing pytest fixture tests", ingress=issue_ingress("web"),
    )
    assert result.final_answer == "resolved"
    assert len(fake.calls) == 1
    wire = fake.calls[0]["messages"]
    assert "knowledge_reference" not in str(wire)
    assert "[资料·记忆/经验]" not in str(wire)
    assert seen == (["method", "experience", "lesson"] if mode == "shadow" else [])
    assert not any(
        "[资料·记忆/经验]" in m.content
        for m in engine.session.load(sid).messages
    )
