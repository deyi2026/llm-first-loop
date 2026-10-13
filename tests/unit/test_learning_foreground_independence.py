"""Regression for whole-run foreground starvation of an explicitly independent cloud lane."""
from __future__ import annotations

import fcntl
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane
from llm_loop.resources.foreground import ForegroundActivityProbe
from llm_loop.resources.governor import ResourceGovernor


def _plane(tmp_path, monkeypatch, *, hosts="api.example.test", endpoint="https://api.example.test/v1",
           extractor_endpoint=None):
    from llm_loop.resources.learning_foreground import LearningForegroundActivityProbe
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    engine = SimpleNamespace(runner=None, settings=SimpleNamespace(method_reflection_timeout_s=1))
    parent = ForegroundActivityProbe(engine, sessions)
    client = SimpleNamespace(base_url=endpoint)
    extraction_client = SimpleNamespace(base_url=extractor_endpoint or endpoint)
    probe = LearningForegroundActivityProbe(
        foreground_probe=parent.active, independent_cloud_hosts=hosts,
        clients=lambda: [client, extraction_client],
    )
    governor = ResourceGovernor(foreground_probe=probe.active)
    journal = LearningJournal(tmp_path / "journal.jsonl")
    job = journal.enqueue("episode:test", session_id="session", source_model="provider/model")
    monkeypatch.setattr("llm_loop.methods.learning_plane.reflect_on_episode", lambda **kw:
                        SimpleNamespace(attempted=True, reason="model_none", candidate_payload=None))
    plane = LearningPlane(
        journal=journal, episode_store=SimpleNamespace(get=lambda *_:
            {"messages": [{"role": "assistant", "content": "done"}]}),
        method_store=SimpleNamespace(), engine=engine, model_resolver=lambda _: client,
        resource_governor=governor, resource_target_resolver=lambda _: ("provider", "model"),
        quiet_period_s=0, model_override="provider/model",
    )
    assert job is not None
    return plane, journal, job, sessions, client, extraction_client


def test_cloud_learning_finishes_with_real_foreground_run_lock(tmp_path, monkeypatch):
    plane, journal, job, sessions, _, _ = _plane(tmp_path, monkeypatch)
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert plane._try_execute(job) is True
        assert journal.job(job.job_id).state == "none"


@pytest.mark.parametrize("hosts,endpoint", [
    ("", "https://api.example.test/v1"),
    ("other.example.test", "https://api.example.test/v1"),
    ("api.example.test", "http://api.example.test/v1"),
    ("api.example.test", "https://api.example.test:8443/v1"),
    ("localhost", "https://localhost/v1"),
    ("127.0.0.1", "https://127.0.0.1/v1"),
    ("127.1", "https://127.1/v1"),
    ("127.0.0.01", "https://127.0.0.01/v1"),
    ("0x7f.1", "https://0x7f.1/v1"),
    ("10.0.0.01", "https://10.0.0.01/v1"),
    ("localhost.", "https://localhost./v1"),
    ("host.local.", "https://host.local./v1"),
    ("host.internal.", "https://host.internal./v1"),
    ("api..example.test", "https://api..example.test/v1"),
    ("api.example.test..", "https://api.example.test../v1"),
    ("api .example.test", "https://api .example.test/v1"),
    ("10.0.0.1", "https://10.0.0.1/v1"),
    ("api.example.test", "https://api.example.test.evil.test/v1"),
    ("api.example.test", ""),
])
def test_default_unknown_and_local_targets_keep_foreground_yield(tmp_path, monkeypatch, hosts, endpoint):
    plane, journal, job, sessions, _, _ = _plane(tmp_path, monkeypatch, hosts=hosts, endpoint=endpoint)
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert plane._try_execute(job) is False
        assert journal.job(job.job_id).state == "queued"


def test_extraction_transport_is_checked_too(tmp_path, monkeypatch):
    plane, _, job, sessions, _, _ = _plane(
        tmp_path, monkeypatch, extractor_endpoint="http://127.0.0.1:8080/v1")
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert plane._try_execute(job) is False


def test_target_refresh_revokes_independence(tmp_path, monkeypatch):
    plane, journal, job, sessions, client, _ = _plane(tmp_path, monkeypatch)
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client.base_url = "http://127.0.0.1:8080/v1"
        assert plane._try_execute(job) is False
        assert journal.job(job.job_id).state == "queued"


def test_probe_error_preserves_yield():
    from llm_loop.resources.learning_foreground import LearningForegroundActivityProbe
    def unavailable():
        raise OSError("no client")
    probe = LearningForegroundActivityProbe(
        foreground_probe=lambda: True, independent_cloud_hosts="api.example.test", clients=unavailable)
    assert probe.active() is True


def test_independence_does_not_bypass_service_restart_barrier(tmp_path, monkeypatch):
    plane, _, job, sessions, _, _ = _plane(tmp_path, monkeypatch)
    plane._restart_admission_blocked = lambda: SimpleNamespace(service="learning", operation_id="test")
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert plane._try_execute(job) is False


def test_cloud_learning_is_not_abandoned_when_foreground_arrives(tmp_path, monkeypatch):
    plane, journal, job, sessions, _, _ = _plane(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def reflect(**kw):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(attempted=True, reason="model_none", candidate_payload=None)
    monkeypatch.setattr("llm_loop.methods.learning_plane.reflect_on_episode", reflect)
    result = []
    thread = threading.Thread(target=lambda: result.append(plane._try_execute(job)))
    thread.start()
    assert entered.wait(3)
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        assert result == [True]
        assert journal.job(job.job_id).state == "none"


def test_runtime_toml_learning_grant_reaches_settings(tmp_path, monkeypatch):
    from llm_loop.config import load_settings
    from llm_loop.runtime.resolver import resolve_effective
    (tmp_path / ".env").write_text(
        "LLM_API_KEY=local-eval\nLLM_BASE_URL=https://api.example.test/v1\n"
        "LLM_MODEL=provider/model\nDATA_DIR=" + str(tmp_path / "data") + "\n")
    (tmp_path / "runtime.toml").write_text(
        '[learning]\nmodel="provider/model"\nindependent_cloud_hosts="api.example.test"\n')
    config = resolve_effective(service="learning", workspace_root=tmp_path, env={})
    settings = load_settings(env=config.values)
    assert settings.learning_independent_cloud_hosts == "api.example.test"
    assert settings.learning_model == "provider/model"


def test_memory_extraction_executes_with_foreground_lock(tmp_path, monkeypatch):
    plane, journal, _, sessions, _, extraction_client = _plane(tmp_path, monkeypatch)
    calls = []
    def extract(session_id, *, trigger):
        calls.append((session_id, trigger))
        return SimpleNamespace(entries=[], skipped_duplicates=0)
    plane._memory_extractor = SimpleNamespace(llm=extraction_client, extract_session=extract)
    job = journal.enqueue("memory-extract:test:20", session_id="session",
                          source_model="provider/model", kind="memory_extract")
    assert job is not None
    with (sessions / "foreground.run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert plane._try_execute(job) is True
        assert calls == [("session", "interval")]
        assert journal.job(job.job_id).state == "none"


def _build_real_engine(fake_settings, monkeypatch, *, role="learning", model=None):
    from llm_loop.factory import build_engine
    monkeypatch.setattr(LearningPlane, "start", lambda self: None)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    settings = replace(
        fake_settings,
        llm_base_url="https://api.example.test/v1",
        learning_model=model or fake_settings.llm_model,
        learning_independent_cloud_hosts="api.example.test",
        extract_enabled=False,
    )
    return build_engine(settings, runtime_role=role)


def test_real_factory_pin_survives_pool_replacement(fake_settings, monkeypatch):
    engine = _build_real_engine(fake_settings, monkeypatch)
    try:
        plane = engine.learning_plane
        assert plane is not None
        old = plane._resolve_model("")
        old.base_url = "http://127.0.0.1:8080/v1"
        replacement = SimpleNamespace(base_url="https://api.example.test/v1")
        monkeypatch.setattr(engine.llm_pool, "get_client", lambda _: replacement)
        assert plane._resolve_model("") is old
        sessions = Path(fake_settings.sessions_dir)
        sessions.mkdir(parents=True, exist_ok=True)
        with (sessions / "foreground.run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert plane.foreground_busy() is True
    finally:
        engine.close()


def test_real_task_factory_keeps_whole_run_priority(fake_settings, monkeypatch):
    engine = _build_real_engine(fake_settings, monkeypatch, role="task")
    try:
        from llm_loop.resources.contracts import ServicePriority
        sessions = Path(fake_settings.sessions_dir)
        sessions.mkdir(parents=True, exist_ok=True)
        with (sessions / "foreground.run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert engine.resource_governor.higher_priority_active(
                ServicePriority.P3_BACKGROUND_LEARNING) is True
    finally:
        engine.close()


def test_real_factory_unresolved_grant_preserves_startup(fake_settings, monkeypatch):
    engine = _build_real_engine(fake_settings, monkeypatch, model="missing/model")
    try:
        plane = engine.learning_plane
        assert plane is not None
        with pytest.raises(ValueError):
            plane._resolve_model("")
        sessions = Path(fake_settings.sessions_dir)
        sessions.mkdir(parents=True, exist_ok=True)
        with (sessions / "foreground.run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert plane.foreground_busy() is True
    finally:
        engine.close()
