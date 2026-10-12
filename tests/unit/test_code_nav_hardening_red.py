from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "code_nav.py"
FAKE_LSP = REPO_ROOT / "tests" / "fixtures" / "code_nav_fake_lsp.py"


def load_code_nav() -> ModuleType:
    spec = importlib.util.spec_from_file_location("code_nav_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryClient:
    def __init__(
        self, *, ready: bool = True, references: list[dict[str, Any]] | None = None
    ) -> None:
        self.ready = ready
        self.references = references or []

    def initialize(self) -> dict[str, Any]:
        return {"referencesProvider": True, "callHierarchyProvider": True}

    def open_file(self, _path: str) -> None:
        return None

    def await_analysis(self, _path: str, _timeout: float) -> bool:
        return self.ready

    def request(self, method: str, _params: dict[str, Any], timeout: float) -> Any:
        assert timeout >= 0
        if method == "textDocument/references":
            return self.references
        if method == "textDocument/prepareCallHierarchy":
            return []
        raise AssertionError(f"unexpected request: {method}")

    def close(self) -> None:
        return None


class HierarchyClient(QueryClient):
    def __init__(self, target_uri: str) -> None:
        super().__init__(ready=True)
        self.target_uri = target_uri

    def request(self, method: str, _params: dict[str, Any], timeout: float) -> Any:
        assert timeout >= 0
        if method == "textDocument/prepareCallHierarchy":
            return [
                {
                    "name": "build",
                    "uri": "file:///placeholder/caller.py",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "selectionRange": {
                        "start": {"line": 0, "character": 4},
                        "end": {"line": 0, "character": 9},
                    },
                }
            ]
        if method == "callHierarchy/outgoingCalls":
            return [
                {
                    "to": {
                        "name": "target",
                        "uri": self.target_uri,
                        "range": {
                            "start": {"line": 10, "character": 0},
                            "end": {"line": 10, "character": 10},
                        },
                        "selectionRange": {
                            "start": {"line": 10, "character": 4},
                            "end": {"line": 10, "character": 10},
                        },
                    },
                    "fromRanges": [
                        {"start": {"line": 3, "character": 4}, "end": {"line": 3, "character": 10}},
                        {"start": {"line": 7, "character": 4}, "end": {"line": 7, "character": 10}},
                    ],
                }
            ]
        raise AssertionError(f"unexpected request: {method}")


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def test_protocol_sends_initialized_and_answers_progress_request(tmp_path: Path) -> None:
    nav = load_code_nav()
    client = nav.LspClient([sys.executable, str(FAKE_LSP), "protocol"], str(tmp_path))
    try:
        caps = client.initialize()
        assert caps["referencesProvider"] is True
        for _ in range(20):
            client._pump(0.02)
            if "initialized-seen" in client.server_logs:
                break
        assert "initialized-seen" in client.server_logs
    finally:
        client.close()


def test_unknown_server_request_returns_method_not_found(tmp_path: Path) -> None:
    nav = load_code_nav()
    client = nav.LspClient([sys.executable, str(FAKE_LSP), "unknown-request"], str(tmp_path))
    try:
        client.initialize()
        note = client.wait_notification(lambda m: m.get("method") == "test/unknownHandled", 1.0)
        assert note is not None
        assert note["params"]["ok"] is True
    finally:
        client.close()


def test_close_uses_graceful_shutdown_then_exit(tmp_path: Path) -> None:
    nav = load_code_nav()
    marker = tmp_path / "graceful.marker"
    client = nav.LspClient(
        [sys.executable, str(FAKE_LSP), "protocol", str(marker)],
        str(tmp_path),
    )
    client.initialize()
    client.close()
    assert marker.read_text(encoding="utf-8").strip() == "graceful"


def test_readiness_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    target = root / "a.py"
    target.write_text("class ToolResult:\n    pass\n", encoding="utf-8")
    client = QueryClient(
        ready=False,
        references=[
            {
                "uri": nav.path_to_uri(str(target)),
                "range": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 16},
                },
            }
        ],
    )
    monkeypatch.setattr(nav, "new_client", lambda _root: client)

    rc = nav.main(
        [
            "--root",
            str(root),
            "--json",
            "refs",
            str(target),
            "ToolResult",
            "--no-cross-check",
            "--ready-timeout",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "not_ready"
    assert payload["trust"]["analysis_ready"] is False


def test_symbol_ambiguity_fails_before_lsp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    target = root / "dup.py"
    target.write_text("def run():\n    pass\n\ndef run():\n    pass\n", encoding="utf-8")
    client = QueryClient(ready=True)
    monkeypatch.setattr(nav, "new_client", lambda _root: client)

    rc = nav.main(["--root", str(root), "refs", str(target), "run", "--no-cross-check"])
    assert rc == 1


def test_ref_paths_are_repo_root_relative_not_cwd_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    target = root / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("class ToolResult:\n    pass\n", encoding="utf-8")
    subdir = root / "scripts"
    subdir.mkdir()
    client = QueryClient(
        ready=True,
        references=[
            {
                "uri": nav.path_to_uri(str(target)),
                "range": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 16},
                },
            }
        ],
    )
    monkeypatch.setattr(nav, "new_client", lambda _root: client)
    monkeypatch.chdir(subdir)

    rc = nav.main(
        ["--root", str(root), "--json", "refs", str(target), "ToolResult", "--no-cross-check"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["trust"]["analysis_ready"] is True
    assert payload["trust"]["repo_lexical_cross_check"] == "not_checked"
    assert payload["refs"][0]["path"] == "src/a.py"


def test_cross_check_uses_git_visible_python_universe(tmp_path: Path) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "examples").mkdir()
    (root / "ignored").mkdir()
    (root / "src/a.py").write_text("ToolResult = object()\n", encoding="utf-8")
    (root / "tests/test_a.py").write_text("ToolResult\nToolResult\n", encoding="utf-8")
    (root / "examples/demo.py").write_text("ToolResult\n", encoding="utf-8")
    (root / "ignored/cache.py").write_text("ToolResult\n" * 5, encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "src/a.py", "tests/test_a.py"], cwd=root, check=True
    )

    result = nav.cross_check(
        "ToolResult",
        str(root),
        {"src/a.py"},
        {"include": ["src"]},
    )

    assert result["matching_files"] == 2
    assert result["matching_lines"] == 3
    assert result["occurrences"] == 3
    assert result["by_top_level_dir"] == {"examples": 1, "tests": 2}
    assert result["include_classifier"] == "exact-prefix"
    assert result["inside_configured_include"] == {
        "matching_files": 0,
        "occurrences": 0,
    }
    assert result["outside_configured_include"] == {
        "matching_files": 2,
        "occurrences": 3,
    }


def test_callees_separate_site_and_target_paths_and_keep_all_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    caller = root / "src" / "caller.py"
    target = root / "src" / "target.py"
    caller.parent.mkdir()
    caller.write_text("def build():\n    target()\n    target()\n", encoding="utf-8")
    target.write_text("\n" * 10 + "def target():\n    pass\n", encoding="utf-8")
    client = HierarchyClient(nav.path_to_uri(str(target)))
    monkeypatch.setattr(nav, "new_client", lambda _root: client)

    rc = nav.main(["--root", str(root), "--json", "callees", str(caller), "build"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    row = payload["calls"][0]
    assert row["site_path"] == "src/caller.py"
    assert row["site_lines"] == [4, 8]
    assert row["target_path"] == "src/target.py"
    assert row["target_definition_line"] == 11


def test_managed_worktree_finds_pyright_from_git_common_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    shared = root / ".venv" / "bin" / "pyright-langserver"
    shared.parent.mkdir(parents=True)
    shared.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shared.chmod(0o755)
    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-qb", "feature", str(worktree)], cwd=root, check=True
    )
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    found = nav.find_langserver(str(worktree))
    assert found == str(shared)
    meta = nav.langserver_metadata(str(worktree), found)
    assert meta["source"] == "git_common_root_venv"


class AmbiguousHierarchyClient(HierarchyClient):
    def request(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        if method == "textDocument/prepareCallHierarchy":
            item = {
                "name": "build",
                "uri": "file:///placeholder/caller.py",
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 5},
                },
                "selectionRange": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 9},
                },
            }
            return [item, {**item, "name": "build_ambiguous"}]
        return super().request(method, params, timeout)


def test_process_exit_is_reported_before_request_timeout(tmp_path: Path) -> None:
    nav = load_code_nav()
    client = nav.LspClient(
        [sys.executable, str(FAKE_LSP), "exit-after-initialized"],
        str(tmp_path),
    )
    client.initialize()
    time.sleep(0.05)
    try:
        with pytest.raises(RuntimeError, match="退出|exit|returncode"):
            client.request("test/willFail", {}, timeout=1.0)
    finally:
        client.close()


def test_reader_protocol_error_is_fail_fast(tmp_path: Path) -> None:
    nav = load_code_nav()
    client = nav.LspClient(
        [sys.executable, str(FAKE_LSP), "malformed-after-initialized"],
        str(tmp_path),
    )
    client.initialize()
    time.sleep(0.05)
    try:
        with pytest.raises(RuntimeError, match="reader|JSON|protocol|解析"):
            client.request("test/willFail", {}, timeout=0.5)
    finally:
        client.close()


def test_prepare_call_hierarchy_ambiguity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    caller = root / "caller.py"
    target = root / "target.py"
    caller.write_text("def build():\n    target()\n", encoding="utf-8")
    target.write_text("def target():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        nav,
        "new_client",
        lambda _root: AmbiguousHierarchyClient(nav.path_to_uri(str(target))),
    )

    rc = nav.main(["--root", str(root), "callees", str(caller), "build"])
    assert rc == 1


def test_target_file_must_stay_inside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("class ToolResult:\n    pass\n", encoding="utf-8")
    called = False

    def should_not_start(_root: str):
        nonlocal called
        called = True
        raise AssertionError("langserver must not start for out-of-repo target")

    monkeypatch.setattr(nav, "new_client", should_not_start)
    rc = nav.main(["--root", str(root), "refs", str(outside), "ToolResult", "--no-cross-check"])
    assert rc == 1
    assert called is False


def test_repo_lock_rejects_second_holder(tmp_path: Path) -> None:
    nav = load_code_nav()
    root = make_repo(tmp_path)
    with (
        nav.RepoLock(str(root), timeout=0.1),
        pytest.raises(RuntimeError, match="busy|占用|lock"),
        nav.RepoLock(str(root), timeout=0.01),
    ):
        pass
