"""单元测试: factory 装配（M17 FR-REVIEW-AI-05 evolution_summary 闭包）.

覆盖: architecture_config 含 evolution_summary（total/pending_review/executing/recent）；
文件不存在 → 全 0 摘要；store.list 抛 OSError → error 字段如实标注（fail-open）；
既有 config 维度零变化。
P1-4（审计 #13）: 模型注册表 resolve 失败 → warning 告警（含模型名与原因, 不吞错）+
config_status 含 model_registry_resolved=false（成功为 true, AI 可经 architecture_status 感知）。
"""

from __future__ import annotations

import json
import logging
from unittest import mock

import pytest

from llm_loop.config import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=True,  # architecture_status 可用
        extract_enabled=False,
    )


def test_evolution_summary_present(tmp_path):
    """architecture_config 含 evolution_summary（total/pending_review/executing/recent）."""
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    # architecture_status 拉取 architecture_config 维度
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    cfg = snap.get("architecture_config", {})
    assert "evolution_summary" in cfg
    es = cfg["evolution_summary"]
    assert es["total"] == 1
    assert es["executing"] == 1
    assert es["recent"] and es["recent"][0]["id"] == sug.id
    # 既有 config 维度保留
    assert "evolve_local_exec" in cfg
    assert "self_eval_enabled" in cfg


def test_evolution_summary_empty_dir(tmp_path):
    """无建议文件 → 全 0 摘要（不报错）."""
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    es = snap.get("architecture_config", {}).get("evolution_summary", {})
    assert es.get("total") == 0
    assert es.get("executing") == 0
    assert "error" not in es


def test_evolution_summary_read_fail_open(tmp_path):
    """store.list 抛 OSError → evolution_summary.error 字段如实标注（fail-open 不抛穿）."""
    from llm_loop.factory import _build_config_status_with_evolution

    settings = _settings(tmp_path)
    cfg_fn = _build_config_status_with_evolution(settings, model_registry_resolved=True)
    with mock.patch(
        "llm_loop.introspection.evolution.EvolutionStore.list", side_effect=OSError("read fail")
    ):
        cfg = cfg_fn()
    es = cfg.get("evolution_summary", {})
    assert "error" in es
    assert "读取失败" in es["error"]
    assert "search_records(kind=evolution)" in es["note"]
    # 既有 config 维度不受影响（fail-open 不抛穿）
    assert cfg.get("evolve_local_exec") == 0


# ── P1-4（审计 #13）: 模型注册表 resolve 结果如实标注 ──


def test_model_registry_resolved_true_on_success(tmp_path):
    """P1-4: 配置模型在注册表中 → config_status.model_registry_resolved=true."""
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path)  # llm_model="m" → L0 合成注册表含 "m", resolve 成功
    engine = build_engine(settings)  # type: ignore[arg-type]
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    assert snap["architecture_config"]["model_registry_resolved"] is True


def test_model_registry_resolved_false_warns_on_resolve_failure(tmp_path, caplog):
    """P1-4: resolve 失败（配置模型不在注册表）→ warning 告警 + model_registry_resolved=false.

    告警含用户配置的模型名与失败原因（不吞错）; AI 可经 architecture_status 感知"模型配置未生效".
    """
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="ghost-model",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=True,  # architecture_status 可用
        extract_enabled=False,
        model_providers_raw=json.dumps(
            {"p1": {"base_url": "http://a", "api_key_env": "", "models": {"m1": {}}}}
        ),
    )
    with caplog.at_level(logging.WARNING, logger="llm_loop.factory"):
        engine = build_engine(settings)  # type: ignore[arg-type]
    # warning 含模型名与失败原因（不吞错）
    assert any(
        "ghost-model" in r.message and "resolve" in r.message and "不在注册表" in r.message
        for r in caplog.records
    )
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    assert snap["architecture_config"]["model_registry_resolved"] is False


# ── P1-8: 默认模型全限定 "provider/model"（默认 client 走注册表参数）──

_KIMI_PROVIDERS_JSON = json.dumps(
    {
        "kimi": {
            "base_url": "https://api.kimi.com/coding/v1",
            "api_key_env": "KIMI_API_KEY",
            "timeout_s": 333,
            "max_tokens": 16384,
            "models": {
                "k3-256k": {
                    "context": 262144,
                    "thinking": True,
                    "cost_tier": "low",
                    "send_tool_choice": False,
                    "reasoning_split": True,
                },
            },
            "default_model": "k3-256k",
        },
    }
)


def test_default_model_qualified_resolves_provider(tmp_path, monkeypatch):
    """LLM_MODEL="kimi/k3-256k"（全限定）→ 默认 client 走 kimi provider 参数.

    base_url/api_key 来自注册表（KIMI_API_KEY）, 模型名发送裸名（k3-256k）;
    env 三件套（LLM_BASE_URL=deepseek）不参与。
    """
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key-xyz")
    settings = Settings(
        llm_api_key="env-key",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="kimi/k3-256k",
        # Registry-resolved model contract must win over an unrelated env default.
        llm_wire_protocol="anthropic",
        data_dir=str(tmp_path / "data"),
        model_providers_raw=_KIMI_PROVIDERS_JSON,
        extract_enabled=False,
    )
    from llm_loop.factory import build_engine

    engine = build_engine(settings)  # type: ignore[arg-type]
    client = engine.llm
    assert client.base_url == "https://api.kimi.com/coding/v1"
    assert client.model == "k3-256k"  # 裸模型名（OpenAI 兼容端点不接受全限定）
    assert client.api_key == "kimi-key-xyz"
    assert client.thinking_supported is True  # 注册表元数据
    assert client.provider == "kimi"
    assert client.reasoning_capable is True  # legacy thinking=true 仍是 capability evidence
    assert client.reasoning_control == "legacy"
    assert client.timeout_s == 333
    assert client.max_tokens == 16384
    assert client.send_tool_choice is False
    assert client.reasoning_split is True
    assert client.wire_protocol == "openai"
    assert engine.llm_pool is not None
    assert engine.llm_pool.base_timeout_s == settings.llm_timeout_s
    assert engine.llm_pool.base_max_tokens == settings.llm_max_tokens
    # None is semantic: no independent global history cap. Factory must not freeze
    # it to the startup model's old 100K~200K heuristic.
    assert engine.settings.history_max_chars is None
    detail = engine._effective_history_budget_detail("kimi/k3-256k")
    assert detail["configured_global_budget"] is None
    assert detail["limited_by"] == "model_window"
    assert detail["effective_budget"] > 100_000


def test_default_model_status_window_remains_bound_to_startup_registry_after_reload(
    tmp_path, monkeypatch
):
    """architecture_status must report the same startup contract used by the default route."""
    from llm_loop.factory import build_engine
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec

    monkeypatch.setenv("KIMI_API_KEY", "kimi-key-xyz")
    settings = Settings(
        llm_api_key="env-key",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="kimi/k3-256k",
        data_dir=str(tmp_path / "data"),
        model_providers_raw=_KIMI_PROVIDERS_JSON,
        self_inspection_enabled=True,
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    startup = engine.llm_pool.default_registry_snapshot()
    replacement = ProviderRegistry(
        providers={
            "kimi": ProviderSpec(
                id="kimi",
                base_url="https://new.invalid/v1",
                api_key_env="",
                models={"k3-256k": ModelSpec(context=999999)},
                default_model="k3-256k",
            )
        }
    )
    engine.llm_pool.replace_registry(replacement)

    snap = engine.status.snapshot(dimensions=["context_usage"])

    assert engine.llm_pool.registry_snapshot() is replacement
    assert engine.llm_pool.default_registry_snapshot() is startup
    assert snap["context_usage"]["model_window"] == {
        "label": "kimi/k3-256k",
        "context": 262144,
    }


def test_default_model_bare_keeps_env_trio(tmp_path):
    """裸模型名（无 "/"）→ 默认 client 保持 env 三件套（零回归）."""
    settings = Settings(
        llm_api_key="env-key",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-v4-flash",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    from llm_loop.factory import build_engine

    engine = build_engine(settings)  # type: ignore[arg-type]
    client = engine.llm
    assert client.base_url == "https://api.deepseek.com/v1"
    assert client.model == "deepseek-v4-flash"
    assert client.api_key == "env-key"


def test_workspace_changed_dimension_in_status(tmp_path):
    """P1-12: architecture_status 含 workspace_changed 维度（guard flag 检测）."""
    import json as _json

    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    snap = engine.status.snapshot()
    # 无 flag → None
    assert snap.get("workspace_changed") is None
    # 有 flag → 返回内容
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace_changed.json").write_text(
        _json.dumps(
            {
                "changed_at": "2026-08-16T00:00:00+00:00",
                "changed_files": ["src/x.py"],
                "note": "变更",
                "action": "restart",
            }
        ),
        encoding="utf-8",
    )
    snap2 = engine.status.snapshot()
    assert snap2["workspace_changed"]["changed_files"] == ["src/x.py"]


def test_workspace_migration_conflict_stops_engine_startup(tmp_path, monkeypatch):
    """两份不同会话数据的迁移冲突必须阻止启动，不能catch后自动选择target副本。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine
    from llm_loop.workspace.store import WorkspaceMigrationConflictError, WorkspaceStore

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)

    def raise_conflict(self, data_dir, default_workspace):
        raise WorkspaceMigrationConflictError("会话迁移冲突: same.json")

    monkeypatch.setattr(WorkspaceStore, "migrate_legacy_sessions", raise_conflict)
    with pytest.raises(WorkspaceMigrationConflictError, match="迁移冲突"):
        build_engine(_settings(tmp_path))  # type: ignore[arg-type]


def test_recovery_sessions_dir_follows_session_store_workspace_root(tmp_path, monkeypatch):
    """恢复工具的session正式位置必须动态跟随当前workspace分区，不能固定在全局sessions根。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]

    assert engine.corrections is not None
    assert engine.corrections.recovery_sessions_dir == engine.session.root

    other = tmp_path / "other-workspace"
    other.mkdir()
    ws = engine.workspace_store.register(other)
    engine.workspace_store.switch(ws.id)
    engine.set_workspace(ws.path, ws.id)

    assert engine.corrections.recovery_sessions_dir == engine.session.root


def test_recover_from_backup_restores_session_into_current_workspace_partition(
    tmp_path, monkeypatch
):
    """真实恢复工具成功后，session必须落当前workspace分区并立即可被SessionStore读取。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.core.session import Session
    from llm_loop.factory import build_engine
    from llm_loop.recovery.backup import BackupArchive, BackupStore

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert engine.corrections is not None

    other = tmp_path / "recovery-workspace"
    other.mkdir()
    ws = engine.workspace_store.register(other)
    engine.workspace_store.switch(ws.id)
    engine.set_workspace(ws.path, ws.id)

    source_id = "recover-workspace-session"
    payload = json.dumps(Session(session_id=source_id).to_dict(), ensure_ascii=False)
    store = BackupStore(settings.recovery_dir)
    backup_id = store.save_archive(
        BackupArchive(
            source_id=source_id,
            backup_at="2026-08-25T07:40:00+08:00",
            target_type="session",
            payload=payload,
            retry_count=1,
            trigger_point="loop_end_save",
        )
    )

    result = engine.corrections.execute(
        "recover_from_backup",
        {"backup_id": backup_id, "on_conflict": "abort"},
    )

    assert result.status.value == "success"
    assert "已恢复" in result.content
    assert (engine.session.root / f"{source_id}.json").exists()
    assert not (settings.sessions_dir / f"{source_id}.json").exists()
    recovered = engine.session.load(source_id)
    assert recovered is not None and recovered.session_id == source_id


def test_recover_session_rejects_same_session_id_owned_by_other_workspace(tmp_path, monkeypatch):
    """Event/Archive按sid全局键，因此恢复不得把同sid复制进第二个workspace分区。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.core.session import Session
    from llm_loop.factory import build_engine
    from llm_loop.recovery.backup import BackupArchive, BackupStore

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert engine.corrections is not None
    source_id = "global-unique-recovery-session"
    payload = json.dumps(Session(session_id=source_id).to_dict(), ensure_ascii=False)
    backups = BackupStore(settings.recovery_dir)

    first_backup = backups.save_archive(
        BackupArchive(
            source_id=source_id,
            backup_at="2026-08-25T07:50:00+08:00",
            target_type="session",
            payload=payload,
            retry_count=1,
            trigger_point="loop_end_save",
        )
    )
    first_root = engine.session.root
    first = engine.corrections.execute(
        "recover_from_backup", {"backup_id": first_backup, "on_conflict": "abort"}
    )
    assert first.status.value == "success"
    assert (first_root / f"{source_id}.json").exists()

    other = tmp_path / "second-recovery-workspace"
    other.mkdir()
    ws = engine.workspace_store.register(other)
    engine.workspace_store.switch(ws.id)
    engine.set_workspace(ws.path, ws.id)
    second_root = engine.session.root
    second_backup = backups.save_archive(
        BackupArchive(
            source_id=source_id,
            backup_at="2026-08-25T07:51:00+08:00",
            target_type="session",
            payload=payload,
            retry_count=1,
            trigger_point="loop_end_save",
        )
    )

    second = engine.corrections.execute(
        "recover_from_backup", {"backup_id": second_backup, "on_conflict": "abort"}
    )

    assert second.status.value == "failure"
    assert "其他工作区" in second.content or "全局唯一" in second.content
    assert not (second_root / f"{source_id}.json").exists()
    assert (first_root / f"{source_id}.json").exists()


def test_recover_from_backup_conflict_is_tool_failure(tmp_path, monkeypatch):
    """on_conflict=abort未执行恢复必须返回ToolResult FAILURE，不能因文本前缀误报success。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine
    from llm_loop.recovery.backup import BackupArchive, BackupStore

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert engine.corrections is not None
    sid = engine.session.create()
    payload = (engine.session.root / f"{sid}.json").read_text(encoding="utf-8")
    backup_id = BackupStore(settings.recovery_dir).save_archive(
        BackupArchive(
            source_id=sid,
            backup_at="2026-08-25T08:02:00+08:00",
            target_type="session",
            payload=payload,
            retry_count=1,
            trigger_point="loop_end_save",
        )
    )

    result = engine.corrections.execute(
        "recover_from_backup", {"backup_id": backup_id, "on_conflict": "abort"}
    )

    assert result.status.value == "failure"
    assert "冲突" in result.content
    assert "未覆盖" in result.content


def test_physical_delete_purges_archive_content(tmp_path, monkeypatch):
    """Web/CLI语义称删除不可恢复，因此物理delete后压缩档案也不得继续按sid检索。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert engine.archive is not None
    sid = engine.session.create()
    engine.archive.archive(
        sid,
        role="user",
        source="user",
        content="delete-private-archive-token-OMEGA",
    )
    assert engine.archive.search(sid, "OMEGA")

    assert engine.session.delete(sid) is True

    assert engine.archive.search(sid, "OMEGA") == []


def test_deleted_session_cannot_be_restored_from_recovery_backup(tmp_path, monkeypatch):
    """Web/CLI明确删除不可恢复；已有recovery backup也不得把旧sid复活。"""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine
    from llm_loop.recovery.backup import BackupArchive, BackupStore

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    assert engine.corrections is not None
    sid = engine.session.create()
    payload = (engine.session.root / f"{sid}.json").read_text(encoding="utf-8")
    backup_id = BackupStore(settings.recovery_dir).save_archive(
        BackupArchive(
            source_id=sid,
            backup_at="2026-08-25T08:35:00+08:00",
            target_type="session",
            payload=payload,
            retry_count=1,
            trigger_point="loop_end_save",
        )
    )
    assert engine.session.delete(sid) is True
    assert not engine.session.exists(sid)
    backups = BackupStore(settings.recovery_dir)
    assert backups.get_archive(backup_id) is None

    result = engine.corrections.execute(
        "recover_from_backup", {"backup_id": backup_id, "on_conflict": "abort"}
    )

    assert result.status.value == "failure"
    assert "未找到" in result.content or "备份不存在" in result.content
    assert not engine.session.exists(sid)


def test_interop_watcher_observes_without_recent_session_attribution(tmp_path, monkeypatch):
    """E26: pending external state may be audited, but must not be attached to a guessed recent session."""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.core.scheduler import SchedulerThread
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    monkeypatch.setattr(SchedulerThread, "start", lambda self: None)
    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    assert engine.inbox_watcher is not None
    actions: list[tuple[str, str, str]] = []
    engine._record_action = lambda kind, status, detail: actions.append((kind, status, detail))
    event_calls: list[tuple] = []
    engine._event_append = lambda *args, **kwargs: event_calls.append(args)

    engine.inbox_watcher._on_notify(["coord.json"])

    assert event_calls == []
    assert actions == [
        (
            "interop.pending_notify",
            "awaiting_user_authorization",
            "count=1;files=coord.json;prompt_chars=0",
        )
    ]


def test_interop_wakeup_never_starts_model_without_user_authorization(tmp_path, monkeypatch):
    """E26: even INBOX_WAKEUP callback cannot fabricate user_text or start a run."""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.core.scheduler import SchedulerThread
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    monkeypatch.setattr(SchedulerThread, "start", lambda self: None)
    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    assert engine.inbox_watcher is not None
    starts: list[tuple] = []
    engine.runner.start = lambda *args, **kwargs: starts.append(args) or (None, None)
    actions: list[tuple[str, str, str]] = []
    engine._record_action = lambda kind, status, detail: actions.append((kind, status, detail))

    engine.inbox_watcher._wakeup_fn(["coord.json"])

    assert starts == []
    assert actions == [
        (
            "interop.coordinate_wakeup",
            "blocked_no_user_authorization",
            "files=coord.json;prompt_chars=0",
        )
    ]


def test_schedule_wake_uses_delegated_same_session_runner_not_inbox_wakeup(tmp_path, monkeypatch):
    """Authorized scheduler delivery starts same session directly; it does not use INBOX_WAKEUP."""
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.core.scheduler import SchedulerThread
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    monkeypatch.setattr(SchedulerThread, "start", lambda self: None)
    notified: list[str] = []
    monkeypatch.setattr(
        SchedulerThread,
        "_notify_via_interop",
        staticmethod(lambda entry: notified.append(entry.sid)),
    )
    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    store = engine.scheduler._store
    grant = object()
    sid = store.add(
        "复查后台 job", after=0, wake=True, session_id="sess-scheduled", wake_grant=grant
    )
    (entry,) = store.due()
    starts: list[tuple] = []

    def _start(session_id, user_text, *args, **kwargs):
        starts.append((session_id, user_text, kwargs.get("ingress")))
        return object(), object()

    engine.runner.start = _start
    assert engine.scheduler._notify(entry) is True
    assert starts == [
        (
            "sess-scheduled",
            "[定时续跑·先前真人授权的程序委派·非新真人输入] 复查后台 job",
            grant,
        )
    ]
    assert store.wake_grant(sid) is None, "成功启动后 one-shot grant 必须立即消费"
    # 模拟 run 已启动但 schedule ack 尚未落盘：同一 entry 再次交付时已无 capability，
    # 只能降级通知，不能重复自动启动第二个模型 run。
    assert engine.scheduler._notify(entry) is True
    assert len(starts) == 1
    assert notified == [sid]
    assert sid == entry.sid
