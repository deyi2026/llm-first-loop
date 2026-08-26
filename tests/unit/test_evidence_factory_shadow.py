from __future__ import annotations

from pathlib import Path

from llm_loop.config import Settings, load_settings
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.memory.evidence import EvidenceLedgerStore, OwnerScope


def _settings(tmp_path: Path, *, mode: str) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        evidence_mode=mode,
        extract_enabled=False,
    )


def test_evidence_mode_defaults_off_and_invalid_env_fails_safe(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.delenv("EVIDENCE_MODE", raising=False)
    assert load_settings().evidence_mode == "off"
    monkeypatch.setenv("EVIDENCE_MODE", "typo-mode")
    assert load_settings().evidence_mode == "off"


def test_factory_off_does_not_create_evidence_store_or_hook(tmp_path):
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path, mode="off")
    engine = build_engine(settings)
    assert settings.evidence_dir.exists() is False
    assert engine.registry._evidence_shadow_hook is None
    assert settings.to_status_dict()["evidence_mode"] == "off"


def test_factory_enforce_installs_canonical_capture_but_default_remains_opt_in(tmp_path):
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path, mode="enforce")
    engine = build_engine(settings)
    assert settings.evidence_dir.exists() is True
    assert engine.registry.evidence_mode == "enforce"
    assert engine.registry._evidence_shadow_hook is None
    assert engine.registry._evidence_enforcer is not None
    assert settings.to_status_dict()["evidence_mode"] == "enforce"


def test_factory_shadow_dual_writes_current_owner_without_changing_visible_output(tmp_path):
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path, mode="shadow")
    engine = build_engine(settings)
    assert settings.to_status_dict()["evidence_mode"] == "shadow"
    path = tmp_path / "large.txt"
    marker = "FACTORY_SHADOW_MIDDLE_MARKER"
    path.write_text("A" * 5000 + marker + "Z" * 5000, encoding="utf-8")

    sid_token = current_session_id.set("session-shadow")
    ws_token = current_workspace_root.set(str(tmp_path))
    try:
        result = engine.registry.execute(
            ToolCall(id="call-shadow", name="read_file", arguments={"path": str(path)})
        )
    finally:
        current_workspace_root.reset(ws_token)
        current_session_id.reset(sid_token)

    assert "[输出已截断]" in result.content
    assert marker not in result.content
    owner = OwnerScope(workspace_id=str(tmp_path.resolve()), session_id="session-shadow")
    ledger = EvidenceLedgerStore(settings.evidence_dir / "ledger")
    records = ledger.list_recent(owner, limit=10)
    assert len(records) == 1
    assert records[0].stable_capture_id == "call-shadow"
    assert records[0].source.locator == str(path)


def test_factory_shadow_owner_isolated_by_workspace_and_session(tmp_path):
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path, mode="shadow")
    engine = build_engine(settings)
    path = tmp_path / "small.txt"
    path.write_text("same observation", encoding="utf-8")

    scopes = [("ws-A", "s1", "c1"), ("ws-B", "s1", "c2"), ("ws-A", "s2", "c3")]
    for workspace, session, call_id in scopes:
        ws = tmp_path / workspace
        ws.mkdir(exist_ok=True)
        sid_token = current_session_id.set(session)
        ws_token = current_workspace_root.set(str(ws))
        try:
            engine.registry.execute(
                ToolCall(id=call_id, name="read_file", arguments={"path": str(path)})
            )
        finally:
            current_workspace_root.reset(ws_token)
            current_session_id.reset(sid_token)

    ledger = EvidenceLedgerStore(settings.evidence_dir / "ledger")
    for workspace, session, _call_id in scopes:
        owner = OwnerScope(workspace_id=str((tmp_path / workspace).resolve()), session_id=session)
        assert ledger.count(owner) == 1
