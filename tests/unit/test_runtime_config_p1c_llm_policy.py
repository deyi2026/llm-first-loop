"""P1-C1: LLM call-time business policy is owned by the startup config snapshot."""

from __future__ import annotations

from pathlib import Path

from llm_loop.config import load_settings
from llm_loop.llm.client import LLMClient
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
from llm_loop.runtime.resolver import (
    legacy_settings_snapshot,
    parse_runtime_toml,
    resolve_effective,
)
from scripts.audit_runtime_env import scan_tree

ROOT = Path(__file__).resolve().parents[2]

_LLM_POLICY_KEYS = {
    "LLM_TRUST_ENV",
    "LLM_RETRY_DISCONNECT",
    "ANTHROPIC_CACHE_CONTROL",
    "CACHE_GUARD_HIT_TELEMETRY",
}


def test_llm_policy_fields_are_closed_schema_runtime_toml(tmp_path: Path) -> None:
    path = tmp_path / "runtime.toml"
    path.write_text(
        """
[llm]
trust_env = false
retry_disconnect = 0
anthropic_cache_control = true
cache_guard_hit_telemetry = false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    values = parse_runtime_toml(path)

    assert values["LLM_TRUST_ENV"] == "0"
    assert values["LLM_RETRY_DISCONNECT"] == "0"
    assert values["ANTHROPIC_CACHE_CONTROL"] == "1"
    assert values["CACHE_GUARD_HIT_TELEMETRY"] == "0"


def test_load_settings_freezes_llm_policy_values() -> None:
    settings = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_TRUST_ENV": "0",
            "LLM_RETRY_DISCONNECT": "3",
            "ANTHROPIC_CACHE_CONTROL": "1",
            "CACHE_GUARD_HIT_TELEMETRY": "0",
        }
    )

    assert settings.llm_trust_env is False
    assert settings.llm_retry_disconnect == 3
    assert settings.anthropic_cache_control is True
    assert settings.cache_guard_hit_telemetry is False

    defaults = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://example.invalid/v1",
        }
    )
    assert defaults.llm_trust_env is None
    assert defaults.llm_retry_disconnect == 1
    assert defaults.anthropic_cache_control is None
    assert defaults.cache_guard_hit_telemetry is None


def test_runtime_toml_llm_policy_beats_stale_shell(tmp_path: Path) -> None:
    (tmp_path / "runtime.toml").write_text(
        """
[llm]
base_url = "https://example.invalid/v1"
trust_env = false
retry_disconnect = 2
anthropic_cache_control = true
cache_guard_hit_telemetry = false
""".strip()
        + "\n",
        encoding="utf-8",
    )
    effective = resolve_effective(
        "web",
        env={
            "LLM_TRUST_ENV": "1",
            "LLM_RETRY_DISCONNECT": "9",
            "ANTHROPIC_CACHE_CONTROL": "0",
            "CACHE_GUARD_HIT_TELEMETRY": "1",
        },
        workspace_root=tmp_path,
    )
    settings = load_settings(
        legacy_settings_snapshot(effective, base_env={"LLM_API_KEY": "k"})
    )

    assert settings.llm_trust_env is False
    assert settings.llm_retry_disconnect == 2
    assert settings.anthropic_cache_control is True
    assert settings.cache_guard_hit_telemetry is False
    for key in _LLM_POLICY_KEYS:
        assert effective.sources[key] == "runtime_toml"


def test_factory_passes_llm_policy_snapshot_to_default_client(tmp_path: Path) -> None:
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        llm_trust_env=False,
        llm_retry_disconnect=4,
        anthropic_cache_control=True,
        cache_guard_hit_telemetry=False,
    )

    engine = build_engine(settings)
    try:
        assert engine.llm.trust_env is False
        assert engine.llm.retry_disconnect == 4
        assert engine.llm.anthropic_cache_control is True
        assert engine.llm.guard_hit_telemetry is False
    finally:
        engine.llm.close()


def test_llm_client_policy_snapshot_ignores_late_process_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TRUST_ENV", "1")
    monkeypatch.setenv("ANTHROPIC_CACHE_CONTROL", "1")
    monkeypatch.setenv("CACHE_GUARD_HIT_TELEMETRY", "1")
    monkeypatch.setenv("LLM_RETRY_DISCONNECT", "9")

    captured: dict[str, object] = {}

    class _HttpClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self) -> None:
            return None

    monkeypatch.setattr("llm_loop.llm.client.httpx.Client", _HttpClient)

    client = LLMClient(
        api_key="k",
        base_url="http://127.0.0.1:8901/v1",
        model="m",
        trust_env=False,
        retry_disconnect=0,
        anthropic_cache_control=False,
        guard_hit_telemetry=False,
    )

    assert captured["trust_env"] is False
    assert client.retry_disconnect == 0
    assert client._anthropic_cache_enabled() is False
    assert client.ensure_guard().hit_telemetry is False


def test_routed_clients_inherit_startup_llm_policy_snapshot(monkeypatch) -> None:
    registry = ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="https://p.invalid/v1",
                api_key_env="P_KEY",
                models={"m": ModelSpec()},
                default_model="m",
            )
        }
    )
    monkeypatch.setattr(
        ProviderRegistry,
        "client_params",
        lambda self, pid, mid: {
            "api_key": "k",
            "base_url": "https://p.invalid/v1",
            "model": mid,
        },
    )
    default = LLMClient(
        api_key="k",
        base_url="https://default.invalid/v1",
        model="default",
        trust_env=False,
        retry_disconnect=0,
        anthropic_cache_control=True,
        guard_hit_telemetry=False,
    )
    pool = ModelClientPool(registry=registry, default_client=default)

    routed = pool.get_client("p/m")

    assert routed.trust_env is False
    assert routed.retry_disconnect == 0
    assert routed.anthropic_cache_control is True
    assert routed.guard_hit_telemetry is False


def test_llm_client_has_no_direct_reads_of_migrated_business_policy() -> None:
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file == "src/llm_loop/llm/client.py"
        and item.key in _LLM_POLICY_KEYS
        and item.op != "write"
    ]
    assert not offenders, f"LLM policy still reads process env at call time: {offenders}"
