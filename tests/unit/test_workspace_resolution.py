"""Workspace resolution contract: flag > cwd-upward > deployment binding (warn/refuse).

The deployment shell leaks LFL_WORKSPACE_ROOT pointing at .releases/<hash>; these
tests pin the read-only query resolution so that ambient binding never wins over
an explicit --workspace or a registered cwd workspace.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from llm_loop.terminal import queries
from llm_loop.terminal.records import workspace_lookup
from llm_loop.workspace.store import WorkspaceStore


def _make_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'ws'\n", encoding="utf-8")
    return root


def _options(
    tmp_path: Path, *, workspace: str | None = None, data_dir: Path | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        workspace=workspace,
        config=str(tmp_path / "absent.env"),
        data_dir=str(data_dir or (tmp_path / "data")),
        _query_home=tmp_path,
    )


def test_ambient_env_ignored_when_cwd_is_registered_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    ws = _make_workspace(tmp_path / "ws")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    WorkspaceStore(data).register(ws)
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path / "fake-release-root"))
    monkeypatch.chdir(ws)

    _, workspace, _ = queries.query_context(_options(tmp_path, data_dir=data))

    assert workspace == ws.resolve()


def test_deployment_binding_ambiguity_exits_3(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    deploy = _make_workspace(tmp_path / "deploy")
    (deploy / "sub").mkdir()
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(deploy))
    monkeypatch.chdir(deploy / "sub")

    assert queries.dispatch_query(["sessions", "list"], _options(tmp_path)) == 3
    err = capsys.readouterr().err
    assert "cwd-derived" in err
    assert "deployment-bound" in err


def test_explicit_workspace_overrides_ambient(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    ws = _make_workspace(tmp_path / "ws")
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path / "fake-release-root"))

    _, workspace, _ = queries.query_context(_options(tmp_path, workspace=str(ws)))

    assert workspace == ws.resolve()


def test_blank_workspace_values_normalized(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    namespace = argparse.Namespace(workspace="  ", config=None, data_dir=None)

    result = queries._resolve_query_workspace(
        namespace, {"LFL_WORKSPACE_ROOT": "  "}
    )

    assert result != Path("  ")
    assert result == Path.cwd()
    assert queries._normalize_workspace_value("  ") is None
    namespace.workspace = None
    assert queries._resolve_query_workspace(
        namespace, {"LFL_WORKSPACE_ROOT": "  "}
    ) == Path.cwd()


def test_cwd_upward_finds_pyproject(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    ws = _make_workspace(tmp_path / "ws")
    deep = ws / "sub" / "deep"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)

    resolved = queries._resolve_query_workspace(None, {})

    assert resolved.resolve() == ws.resolve()


def test_single_workspace_degraded_listing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    WorkspaceStore(data).register(_make_workspace(tmp_path / "ws"))
    other = tmp_path / "other"
    other.mkdir()

    result = workspace_lookup(data, other)

    assert result == (data / "sessions", True)
    assert "degraded" in capsys.readouterr().err


def test_multi_workspace_refuses_without_listing_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    store = WorkspaceStore(data)
    first = _make_workspace(tmp_path / "first")
    second = _make_workspace(tmp_path / "second")
    store.register(first)
    store.register(second)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError, match="holds 2 workspaces") as info:
        workspace_lookup(data, other)

    message = str(info.value)
    assert str(first.resolve()) not in message
    assert str(second.resolve()) not in message


def test_sessions_show_refuses_same_as_list(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    store = WorkspaceStore(data)
    store.register(_make_workspace(tmp_path / "first"))
    store.register(_make_workspace(tmp_path / "second"))
    other = tmp_path / "other"
    other.mkdir()

    options = _options(tmp_path, workspace=str(other), data_dir=data)

    assert queries.dispatch_query(["sessions", "show", "some-id"], options) == 1


def test_workspace_explicit_only_from_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path / "fake-release-root"))
    captured: dict[str, bool] = {}

    def _capture_execute(cmd, ns, data, workspace, values, *, options=None,
                         workspace_explicit=False):
        captured["workspace_explicit"] = workspace_explicit
        return 0

    monkeypatch.setattr(queries, "_execute_query", _capture_execute)
    options = _options(tmp_path, workspace=None)

    assert queries.dispatch_query(["identity"], options) == 0
    assert captured["workspace_explicit"] is False


def test_identity_session_refuses_multi_registry_same_as_sessions(tmp_path, monkeypatch, capsys):
    # T8 consistency (review P2-1): the multi-registry refusal must not be bypassed
    # by the identity branch's former base-root fallback — identity --session has to
    # fail exactly like sessions show/list when the registry holds 2 workspaces.
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    store = WorkspaceStore(data)
    store.register(_make_workspace(tmp_path / "w1"))
    store.register(_make_workspace(tmp_path / "w2"))
    unregistered = _make_workspace(tmp_path / "unregistered")

    options = _options(tmp_path, workspace=str(unregistered), data_dir=data)

    assert queries.dispatch_query(["identity", "--session", "session-x"], options) == 1
    captured = capsys.readouterr()
    assert "holds 2 workspaces" in captured.err or "holds 2 workspaces" in captured.out
