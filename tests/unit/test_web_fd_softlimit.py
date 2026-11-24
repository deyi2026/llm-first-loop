"""Web-only file descriptor headroom and deterministic event scan cleanup."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.runtime import launch


def _fake_resource(monkeypatch: pytest.MonkeyPatch, *, soft: int, hard: int):
    writes: list[tuple[int, tuple[int, int]]] = []
    resource = SimpleNamespace(
        RLIMIT_NOFILE=7,
        RLIM_INFINITY=-1,
        getrlimit=lambda _kind: (soft, hard),
        setrlimit=lambda kind, limits: writes.append((kind, limits)),
    )
    monkeypatch.setitem(sys.modules, "resource", resource)
    return writes


def test_web_fd_limit_raises_only_soft_within_hard(monkeypatch: pytest.MonkeyPatch):
    writes = _fake_resource(monkeypatch, soft=256, hard=4096)
    launch._raise_web_fd_soft_limit()
    assert writes == [(7, (1024, 4096))]


def test_web_fd_limit_respects_lower_hard_cap(monkeypatch: pytest.MonkeyPatch):
    writes = _fake_resource(monkeypatch, soft=256, hard=512)
    launch._raise_web_fd_soft_limit()
    assert writes == [(7, (512, 512))]


def test_web_fd_limit_is_noop_when_already_sufficient(monkeypatch: pytest.MonkeyPatch):
    writes = _fake_resource(monkeypatch, soft=2048, hard=4096)
    launch._raise_web_fd_soft_limit()
    assert writes == []


def test_web_fd_limit_failure_does_not_prevent_startup(monkeypatch: pytest.MonkeyPatch):
    _fake_resource(monkeypatch, soft=256, hard=4096)
    monkeypatch.setattr(
        sys.modules["resource"], "setrlimit",
        lambda _kind, _limits: (_ for _ in ()).throw(OSError(1, "not permitted")),
    )
    launch._raise_web_fd_soft_limit()


def test_only_live_web_launch_adjusts_fd_limit(monkeypatch: pytest.MonkeyPatch, tmp_path):
    calls: list[str] = []
    ec = SimpleNamespace(
        values={}, runtime_root=tmp_path, config_file=None, ignored_shell_env=[],
        to_summary=lambda: {},
    )
    report = SimpleNamespace(ok=True, data_dir=tmp_path)
    monkeypatch.setattr(launch, "resolve_effective", lambda *_args, **_kw: ec)
    monkeypatch.setattr(launch, "legacy_env_snapshot", lambda _ec: {})
    monkeypatch.setattr(launch, "check_identity", lambda **_kw: report)
    monkeypatch.setattr(launch, "apply_to_environ", lambda _ec: None)
    monkeypatch.setattr(launch, "build_manifest", lambda *_args: {"config_hash": "abc"})
    monkeypatch.setattr(launch, "write_manifest", lambda *_args: tmp_path / "manifest.json")
    monkeypatch.setattr(launch.runpy, "run_module", lambda *_args, **_kw: None)
    monkeypatch.setattr(launch, "_raise_web_fd_soft_limit", lambda: calls.append("web"))
    assert launch.main(["web", "--dry-run"]) == 0
    assert launch.main(["feishu"]) == 0
    assert calls == []
    assert launch.main(["web"]) == 0
    assert calls == ["web"]


@pytest.mark.parametrize("method", ["_all_segment_paths", "_active_segment_path"])
def test_event_scandir_closed_even_when_entry_stat_fails(monkeypatch: pytest.MonkeyPatch, tmp_path, method):
    from llm_loop.event_log import store as store_module

    class BadEntry:
        name = "1.jsonl"
        path = "1.jsonl"

        def is_file(self):
            raise OSError(24, "Too many open files")

    class FakeScandir:
        closed = False

        def __enter__(self):
            return iter([BadEntry()])

        def __exit__(self, _exc_type, _exc, _tb):
            self.closed = True

    fake = FakeScandir()
    monkeypatch.setattr(store_module.os, "scandir", lambda _path: fake)
    with pytest.raises(OSError, match="Too many open files"):
        getattr(EventStore(tmp_path), method)("session-1")
    assert fake.closed
