"""P1-B1: runtime path consumers use resolved ownership, never stale process env."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.engine_services.interop import InteropService
from llm_loop.core.scheduler import ScheduleEntry, SchedulerThread
from llm_loop.tools.builtin.job_registry import JobEntry, JobRegistry
from scripts.audit_runtime_env import scan_tree

ROOT = Path(__file__).resolve().parents[2]


def _pending_dir(data_dir: Path) -> Path:
    return data_dir / "interop" / "lfl_to_dsh" / "pending"


def test_interop_service_uses_host_settings_data_dir_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    pending = _pending_dir(canonical)
    pending.mkdir(parents=True)
    message = pending / "n.json"
    message.write_text(
        json.dumps(
            {
                "id": "n1",
                "from": "scheduler",
                "to": "lfl",
                "topic": "notify",
                "status": "pending",
                "body": "done",
                "ref": "r1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LFL_DATA_DIR", str(stale))
    host = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(canonical)),
        _record_action=lambda *_args, **_kwargs: None,
    )

    InteropService(host)._interop_inbox_messages()

    assert not message.exists()
    archived = canonical / "interop" / "lfl_to_dsh" / "done" / "n.json"
    assert archived.is_file()
    assert not stale.exists()


def test_scheduler_notify_uses_explicit_data_dir_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    monkeypatch.setenv("LFL_DATA_DIR", str(stale))
    entry = ScheduleEntry(sid="sched-1", message="hello", trigger_at=time.time())

    SchedulerThread._notify_via_interop(entry, data_dir=canonical)

    files = sorted(_pending_dir(canonical).glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["ref"] == "sched-1"
    assert not stale.exists()


def test_job_registry_notify_uses_configured_data_dir_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    monkeypatch.setenv("LFL_DATA_DIR", str(stale))
    reg = JobRegistry(event_store=None)
    reg.configure(event_store=None, data_dir=canonical)
    entry = JobEntry(id="job-1", command="echo ok", done=True, exit_code=0)
    reg._jobs[entry.id] = entry

    reg._notify_completion(entry.id)

    files = sorted(_pending_dir(canonical).glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["ref"] == "job-1"
    assert not stale.exists()


def test_p1b1_selected_path_consumers_have_no_direct_lfl_data_dir_reads() -> None:
    selected = {
        "src/llm_loop/core/interop_watch.py",
        "src/llm_loop/core/loop/engine_services/interop.py",
        "src/llm_loop/core/scheduler.py",
        "src/llm_loop/tools/builtin/job_registry.py",
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file in selected and item.key == "LFL_DATA_DIR" and item.op != "write"
    ]
    assert not offenders, f"P1-B1 path consumers still read LFL_DATA_DIR directly: {offenders}"


def test_factory_binds_cache_audit_paths_to_resolved_data_dir(tmp_path: Path, monkeypatch) -> None:
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    monkeypatch.setenv("LFL_DATA_DIR", str(stale))
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(canonical),
        extract_enabled=False,
    )

    engine = build_engine(settings)  # type: ignore[arg-type]

    assert engine._cache_monitor._breaker_audit_file == canonical.resolve() / "audit" / "cache_breaker.jsonl"
    assert engine.llm.ensure_guard().audit_file == canonical.resolve() / "audit" / "guarded_requests.jsonl"
    assert not stale.exists()


def test_model_pool_propagates_guard_audit_path_to_routed_clients(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest import mock

    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec

    audit = tmp_path / "data" / "audit" / "guarded_requests.jsonl"
    registry = ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="https://p.invalid/v1",
                api_key_env="X",
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
    default = SimpleNamespace(
        timeout_s=60.0,
        max_tokens=4096,
        wire_protocol="openai",
        thinking_mode=True,
        reasoning_effort="high",
        thinking_supported=True,
        model="m",
        close=lambda: None,
    )
    made: list[SimpleNamespace] = []

    def build_client(**kwargs):
        obj = SimpleNamespace(**kwargs, close=lambda: None)
        made.append(obj)
        return obj

    with mock.patch("llm_loop.llm.pool.LLMClient", side_effect=build_client):
        pool = ModelClientPool(  # type: ignore[arg-type]
            registry=registry,
            default_client=default,
            guard_audit_file=audit,
        )
        routed = pool.get_client("p/m")

    assert routed.guard_audit_file == audit
    assert len(made) == 1


def test_p1b1_cache_path_consumers_have_no_direct_lfl_data_dir_reads() -> None:
    selected = {
        "src/llm_loop/cache_guard/guard.py",
        "src/llm_loop/core/cache_health.py",
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file in selected and item.key == "LFL_DATA_DIR" and item.op != "write"
    ]
    assert not offenders, f"cache audit path consumers still read LFL_DATA_DIR directly: {offenders}"


def test_p1b1_compat_path_helpers_have_no_direct_lfl_data_dir_reads() -> None:
    selected = {
        "src/llm_loop/core/history.py",
        "src/llm_loop/eval/oracle_1210.py",
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file in selected and item.key == "LFL_DATA_DIR" and item.op != "write"
    ]
    assert not offenders, f"compat/offline path helpers still read LFL_DATA_DIR directly: {offenders}"


def test_p1b1_trace_leak_quarantine_has_no_direct_lfl_data_dir_read() -> None:
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file == "src/llm_loop/core/trace_leak/leak_events.py"
        and item.key == "LFL_DATA_DIR"
        and item.op != "write"
    ]
    assert not offenders


def test_legacy_defer_trace_helper_uses_explicit_data_dir_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.core.loop.injection_span import record_defer_event

    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    monkeypatch.setenv("LFL_DATA_DIR", str(stale))
    monkeypatch.setenv("ERR1210_DEFER_TRACE", "1")

    record_defer_event(
        "probe", "s1", "all", {"ok": True}, data_dir=canonical
    )

    assert (canonical / "audit" / "defer_trace.jsonl").is_file()
    assert not stale.exists()


def test_p1b1_defer_trace_has_no_direct_lfl_data_dir_read() -> None:
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file == "src/llm_loop/core/loop/injection_span.py"
        and item.key == "LFL_DATA_DIR"
        and item.op != "write"
    ]
    assert not offenders


def test_factory_skill_runtime_root_comes_from_settings_snapshot_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.config import load_settings
    from llm_loop.factory import build_engine

    runtime_root = tmp_path / "runtime-root"
    data_dir = tmp_path / "custom-data-bundle"
    stale = tmp_path / "stale-runtime-root"
    runtime_root.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("LFL_RUNTIME_ROOT", str(stale))
    settings = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://x.invalid/v1",
            "LLM_MODEL": "m",
            "DATA_DIR": str(data_dir),
            "LFL_RUNTIME_ROOT": str(runtime_root),
        }
    )

    engine = build_engine(settings)

    assert settings._extra["runtime_root"] == str(runtime_root.resolve())
    assert engine.corrections.skill_execution_facts["runtime_root"] == str(runtime_root.resolve())
    assert engine.corrections.skill_execution_facts["runtime_root"] != str(stale.resolve())


def test_loop_signal_fallback_path_uses_explicit_data_owner_not_stale_env(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.introspection.loop_signals import LoopSignalDetector

    canonical = tmp_path / "canonical"
    stale = tmp_path / "stale"
    monkeypatch.setenv("DATA_DIR", str(stale))
    detector = LoopSignalDetector(data_dir=canonical)

    path = detector._ghost_ignore_path(object())

    assert path == canonical.resolve() / "audit" / "pending_ignored.jsonl"
    assert stale not in path.parents


def test_p1b1_runtime_fact_consumers_do_not_reread_process_paths() -> None:
    selected = {
        ("src/llm_loop/factory.py", "LFL_RUNTIME_ROOT"),
        ("src/llm_loop/introspection/loop_signals.py", "DATA_DIR"),
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if (item.file, item.key) in selected and item.op != "write"
    ]
    assert not offenders


def test_history_policy_is_resolved_from_explicit_settings_not_stale_env(
    monkeypatch,
) -> None:
    from llm_loop.config import load_settings

    monkeypatch.setenv("COMPACT_RATIO", "0.20")
    monkeypatch.setenv("HEAD_KEEP_RATIO", "0.99")
    settings = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://x.invalid/v1",
            "LLM_MODEL": "m",
            "COMPACT_RATIO": "0.85",
            "COMPRESS_TARGET_RATIO": "0.55",
            "HEAD_KEEP_RATIO": "0.31",
            "LFL_TOOL_WORKING_SET_RECEIPTS": "1",
            "LFL_TOOL_WORKING_SET_BATCH_CHARS": "65536",
        }
    )

    assert settings.history_policy.compact_ratio == 0.85
    assert settings.history_policy.compress_target_ratio == 0.55
    assert settings.history_policy.head_keep_ratio == 0.31
    assert settings.history_policy.working_set_receipts is True
    assert settings.history_policy.working_set_batch_chars == 65536


def test_working_set_projection_uses_explicit_history_policy() -> None:
    from types import SimpleNamespace

    from llm_loop.core.episode_history import project_active_tool_working_set_with_stats

    policy = SimpleNamespace(
        working_set_receipts=True,
        working_set_batch_chars=65536,
        working_set_grace_groups=2,
        working_set_soft_result_cap=7,
        working_set_hard_result_cap=19,
        working_set_min_net_gain_chars=1234,
    )
    projected, stats = project_active_tool_working_set_with_stats([], policy=policy)

    assert projected == []
    assert stats.enabled is True
    assert stats.batch_chars == 65536
    assert stats.grace_groups == 2
    assert stats.soft_result_cap == 7
    assert stats.hard_result_cap == 19
    assert stats.min_net_gain_chars == 1234


def test_p1b2_history_consumers_have_no_direct_business_env_reads() -> None:
    selected = {
        "src/llm_loop/core/episode_history.py": {
            "LFL_TOOL_WORKING_SET_RECEIPTS",
            "LFL_TOOL_WORKING_SET_BATCH_CHARS",
            "LFL_TOOL_WORKING_SET_GRACE_GROUPS",
            "LFL_TOOL_WORKING_SET_SOFT_RESULT_CAP",
            "LFL_TOOL_WORKING_SET_HARD_RESULT_CAP",
            "LFL_TOOL_WORKING_SET_MIN_NET_GAIN_CHARS",
        },
        "src/llm_loop/core/history.py": {
            "COMPRESS_TARGET_RATIO",
            "COG_RUNTIME_ANCHOR_MODE",
        },
        "src/llm_loop/core/prompt_build/stages/history_budget_prep.py": {
            "COMPACT_RATIO",
            "NUDGE_GROWTH_CHARS",
        },
        "src/llm_loop/core/prompt_build/stages/history_projection.py": {
            "HEAD_KEEP_RATIO",
            "HEAD_KEEP_FORCE_RATIO",
            "HEAD_KEEP_TARGET_RATIO",
        },
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if item.file in selected
        and item.key in selected[item.file]
        and item.op != "write"
    ]
    assert not offenders, f"history policy consumers still read env directly: {offenders}"


def test_tool_runtime_settings_are_explicit_and_ignore_stale_process_env(monkeypatch) -> None:
    from llm_loop.config import load_settings

    monkeypatch.setenv("JOB_MAX_CONCURRENT", "99")
    monkeypatch.setenv("LFL_TOOL_GUIDANCE", "on")
    monkeypatch.setenv("EXEC_SANDBOX", "docker")
    settings = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://x.invalid/v1",
            "LLM_MODEL": "m",
            "LFL_BREAKER_PRESSURE_NARROW": "0",
            "LFL_E18_HARD_STOP": "0",
            "LFL_TOOL_OCTET": "1",
            "DSH_HOME": "/tmp/dsh-explicit",
            "JOB_MAX_CONCURRENT": "3",
            "LFL_EVIDENCE_CAPSULE": "shadow",
            "LFL_TOOL_GUIDANCE": "off",
            "EXEC_SANDBOX": "bwrap",
            "EXEC_SANDBOX_IMAGE": "python:3.13-alpine",
            "LFL_NONCONV_FUSE_WINDOWS": "2",
            "LFL_NONCONV_FUSE_JACCARD": "0.75",
            "LFL_NONCONV_FUSE_MIN_DELTA": "7",
        }
    )
    tr = settings.tool_runtime
    assert tr.breaker_pressure_narrow is False
    assert tr.e18_hard_stop is False
    assert tr.tool_octet is True
    assert tr.dsh_home == "/tmp/dsh-explicit"
    assert tr.job_max_concurrent == 3
    assert tr.evidence_capsule == "shadow"
    assert tr.tool_guidance == "off"
    assert tr.exec_sandbox == "bwrap"
    assert tr.exec_sandbox_image == "python:3.13-alpine"
    assert tr.nonconvergence_fuse_windows == 2
    assert tr.nonconvergence_fuse_jaccard == 0.75
    assert tr.nonconvergence_fuse_min_delta == 7


def test_tool_octet_uses_registered_enablement_not_stale_process_env(monkeypatch) -> None:
    from llm_loop.runtime.tool_octet import record_tool_octet, register_octet_sink

    rows: list[tuple[str, dict]] = []
    monkeypatch.setenv("LFL_TOOL_OCTET", "1")  # stale process value must be irrelevant
    try:
        register_octet_sink(lambda stream, row: rows.append((stream, row)), enabled=False)
        record_tool_octet(
            session_id="s", round_index=1, tool_call_id="c-off", tool_name="read_file",
            args={"path": "x"}, status="success", result_content="ok",
        )
        assert rows == []

        register_octet_sink(lambda stream, row: rows.append((stream, row)), enabled=True)
        record_tool_octet(
            session_id="s", round_index=2, tool_call_id="c-on", tool_name="read_file",
            args={"path": "x"}, status="success", result_content="ok",
        )
        assert len(rows) == 1
        assert rows[0][0] == "tool_octet.jsonl"
        assert rows[0][1]["tool_call_id"] == "c-on"
    finally:
        register_octet_sink(None, enabled=False)


def test_p1b2_tool_runtime_consumers_have_no_direct_business_env_reads() -> None:
    targets = {
        ("src/llm_loop/core/loop/build.py", "LFL_BREAKER_PRESSURE_NARROW"),
        ("src/llm_loop/core/loop/engine.py", "LFL_E18_HARD_STOP"),
        ("src/llm_loop/runtime/tool_octet.py", "LFL_TOOL_OCTET"),
        ("src/llm_loop/tools/builtin/dsh_session_read.py", "DSH_HOME"),
        ("src/llm_loop/tools/builtin/job_registry.py", "JOB_MAX_CONCURRENT"),
        ("src/llm_loop/tools/evidence_enforce.py", "LFL_EVIDENCE_CAPSULE"),
        ("src/llm_loop/tools/registry.py", "LFL_TOOL_GUIDANCE"),
        ("src/llm_loop/tools/sandbox.py", "EXEC_SANDBOX"),
        ("src/llm_loop/tools/sandbox.py", "EXEC_SANDBOX_IMAGE"),
        ("src/llm_loop/core/loop/engine_services/nonconvergence_guard.py", "<dynamic>"),
    }
    offenders = [
        item.signature
        for item in scan_tree(ROOT / "src")
        if (item.file, item.key) in targets and item.op != "write"
    ]
    assert not offenders, f"tool-runtime consumers still read env directly: {offenders}"
