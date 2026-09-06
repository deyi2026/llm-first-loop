from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "continuity.py"
SPEC = importlib.util.spec_from_file_location("lfl_continuity_script", SCRIPT)
assert SPEC and SPEC.loader
continuity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(continuity)


def _run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", *args], cwd).stdout.strip()


def _init_source(tmp_path: Path, *, with_remote: bool = False) -> tuple[Path, Path | None]:
    source = tmp_path / "source"
    source.mkdir()
    _run(["git", "init", "-q", "-b", "main"], source)
    _git(source, "config", "user.name", "Test User")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-q", "-m", "init")
    remote = None
    if with_remote:
        remote = tmp_path / "source-remote.git"
        _run(["git", "init", "-q", "--bare", str(remote)], tmp_path)
        _git(source, "remote", "add", "origin", str(remote))
        _git(source, "push", "-q", "-u", "origin", "main")
    return source, remote


def _configure_local(source: Path, store: Path, *, remote: Path | None = None) -> None:
    _git(source, "config", "--local", "lfl.continuity.path", str(store))
    _git(source, "config", "--local", "lfl.continuity.project", "test-project")
    if remote is not None:
        _git(source, "config", "--local", "lfl.continuity.remote", str(remote))


def _write_input(path: Path, workstream: str, *, extra: dict | None = None) -> Path:
    data = {
        "workstream_id": workstream,
        "objective": f"objective for {workstream}",
        "verified_facts": ["verified fact"],
        "completed": ["completed item"],
        "decisions": ["decision with rationale"],
        "open_questions": [],
        "suggested_next_step": "historical suggestion",
        "affected_paths": ["src/example.py"],
    }
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _cli(source: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, str(SCRIPT), *args], source, check=check)


def test_configure_rejects_credentialed_https_remote(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    credentialed_remote = "https://" + "user:" + "token" + "@example.invalid/private.git"
    result = _cli(
        source,
        "configure",
        "--remote",
        credentialed_remote,
        check=False,
    )
    assert result.returncode == 2
    assert "credentialed HTTP(S)" in result.stderr
    cfg = _run(["git", "config", "--local", "--get", "lfl.continuity.remote"], source, check=False)
    assert cfg.returncode != 0


def test_handoff_manifest_excludes_absolute_source_and_remote(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path, with_remote=True)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    input_path = _write_input(tmp_path / "handoff.json", "alpha")

    result = _cli(source, "handoff", "--input", str(input_path))
    payload = json.loads(result.stdout)
    manifest_path = next(store.glob("projects/test-project/handoffs/*/manifest.json"))
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert payload["source_portability"] == "complete"
    assert str(source) not in manifest_text
    assert "source-remote.git" not in manifest_text
    assert "remote" not in json.loads(manifest_text)


def test_dirty_source_is_metadata_only_with_fingerprint(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path, with_remote=True)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    (source / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (source / "new.txt").write_text("untracked\n", encoding="utf-8")
    input_path = _write_input(tmp_path / "handoff.json", "dirty-work")

    payload = json.loads(_cli(source, "handoff", "--input", str(input_path)).stdout)
    manifest = json.loads(next(store.glob("projects/test-project/handoffs/*/manifest.json")).read_text())
    assert payload["source_portability"] == "metadata_only"
    assert manifest["tracked_dirty_count"] == 1
    assert manifest["untracked_count"] == 1
    assert len(manifest["working_tree_fingerprint_sha256"]) == 64
    handoff_text = next(store.glob("projects/test-project/handoffs/*/HANDOFF.md")).read_text()
    assert "dirty\n" not in handoff_text
    assert "untracked\n" not in handoff_text


def test_candidates_filter_and_head_relation(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path, with_remote=True)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    first = json.loads(
        _cli(source, "handoff", "--input", str(_write_input(tmp_path / "a.json", "alpha"))).stdout
    )
    (source / "tracked.txt").write_text("v2\n", encoding="utf-8")
    _git(source, "add", "tracked.txt")
    _git(source, "commit", "-q", "-m", "advance")
    _git(source, "push", "-q")
    _cli(source, "handoff", "--input", str(_write_input(tmp_path / "b.json", "beta")))

    rows = json.loads(_cli(source, "candidates", "--workstream", "alpha").stdout)
    assert [row["handoff_id"] for row in rows] == [first["handoff_id"]]
    assert rows[0]["head_relation"] == "CURRENT_IS_DESCENDANT"


def test_concurrent_handoffs_use_unique_files_and_no_index_collision(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path, with_remote=True)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    inputs = [
        _write_input(tmp_path / "one.json", "one"),
        _write_input(tmp_path / "two.json", "two"),
    ]

    def run_one(path: Path) -> subprocess.CompletedProcess[str]:
        return _cli(source, "handoff", "--input", str(path), check=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_one, inputs))
    assert [result.returncode for result in results] == [0, 0]
    manifests = list(store.glob("projects/test-project/handoffs/*/manifest.json"))
    assert len(manifests) == 2
    assert len({_load["handoff_id"] for _load in map(lambda p: json.loads(p.read_text()), manifests)}) == 2
    assert _git(store, "status", "--porcelain") == ""


def test_offline_sync_preserves_local_handoff(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path, with_remote=True)
    continuity_remote = tmp_path / "continuity-remote.git"
    _run(["git", "init", "-q", "--bare", str(continuity_remote)], tmp_path)
    store = tmp_path / "private-continuity"
    _configure_local(source, store, remote=continuity_remote)
    _cli(source, "configure")
    continuity_remote.rename(tmp_path / "continuity-remote.offline")

    result = _cli(source, "handoff", "--input", str(_write_input(tmp_path / "offline.json", "offline")))
    payload = json.loads(result.stdout)
    assert payload["remote_synced"] is False
    assert payload["sync_reason"] == "fetch_failed"
    assert len(list(store.glob("projects/test-project/handoffs/*/manifest.json"))) == 1
    assert _git(store, "status", "--porcelain") == ""


def test_secret_scan_rejects_private_key_and_does_not_commit(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    bad = _write_input(
        tmp_path / "bad.json",
        "bad",
        extra={"verified_facts": ["-" * 5 + "BEGIN " + "PRIVATE KEY" + "-" * 5]},
    )
    result = _cli(source, "handoff", "--input", str(bad), check=False)
    assert result.returncode == 2
    assert "secret scan" in result.stderr
    assert not list(store.glob("projects/test-project/handoffs/*/manifest.json"))



def test_cross_clone_remote_roundtrip_and_closure(tmp_path: Path) -> None:
    source_a_parent = tmp_path / "a"
    source_a_parent.mkdir()
    source_a, source_remote = _init_source(source_a_parent, with_remote=True)
    assert source_remote is not None

    source_b_parent = tmp_path / "b"
    source_c_parent = tmp_path / "c"
    source_b_parent.mkdir()
    source_c_parent.mkdir()
    source_b = source_b_parent / "source"
    source_c = source_c_parent / "source"
    _run(["git", "clone", "-q", str(source_remote), str(source_b)], source_b_parent)
    _run(["git", "clone", "-q", str(source_remote), str(source_c)], source_c_parent)

    continuity_remote = tmp_path / "continuity.git"
    _run(["git", "init", "-q", "--bare", str(continuity_remote)], tmp_path)
    store_a = tmp_path / "store-a"
    store_b = tmp_path / "store-b"
    store_c = tmp_path / "store-c"
    _configure_local(source_a, store_a, remote=continuity_remote)
    _configure_local(source_b, store_b, remote=continuity_remote)
    _configure_local(source_c, store_c, remote=continuity_remote)

    input_path = _write_input(tmp_path / "handoff.json", "cross-clone")
    created = json.loads(_cli(source_a, "handoff", "--input", str(input_path)).stdout)
    assert created["remote_synced"] is True
    assert created["source_portability"] == "complete"
    handoff_id = created["handoff_id"]

    rows_b = json.loads(_cli(source_b, "candidates", "--workstream", "cross-clone").stdout)
    assert len(rows_b) == 1
    assert rows_b[0]["handoff_id"] == handoff_id
    assert rows_b[0]["head_relation"] == "EXACT_HEAD"
    assert rows_b[0]["source_portability"] == "complete"

    reason = tmp_path / "reason.txt"
    reason.write_text("acceptance complete\n", encoding="utf-8")
    closed = json.loads(
        _cli(source_b, "close", handoff_id, "--reason-file", str(reason)).stdout
    )
    assert closed["remote_synced"] is True

    rows_c = json.loads(_cli(source_c, "candidates", "--workstream", "cross-clone").stdout)
    assert rows_c == []
    all_c = json.loads(
        _cli(
            source_c,
            "candidates",
            "--workstream",
            "cross-clone",
            "--include-closed",
        ).stdout
    )
    assert len(all_c) == 1
    assert all_c[0]["handoff_id"] == handoff_id
    assert all_c[0]["closed"] is True


def test_show_is_read_only_even_if_handoff_contains_shell_text(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    marker = tmp_path / "must-not-exist"
    text = f"touch {marker}"
    input_path = _write_input(tmp_path / "show.json", "show", extra={"suggested_next_step": text})
    created = json.loads(_cli(source, "handoff", "--input", str(input_path)).stdout)

    shown = _cli(source, "show", created["handoff_id"]).stdout
    assert text in shown
    assert not marker.exists()


def test_close_is_append_only_and_hides_closed_candidate(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    store = tmp_path / "private-continuity"
    _configure_local(source, store)
    created = json.loads(
        _cli(source, "handoff", "--input", str(_write_input(tmp_path / "close.json", "close"))).stdout
    )
    hid = created["handoff_id"]
    handoff_path = store / "projects" / "test-project" / "handoffs" / hid / "HANDOFF.md"
    before = hashlib.sha256(handoff_path.read_bytes()).hexdigest()

    _cli(source, "close", hid)
    after = hashlib.sha256(handoff_path.read_bytes()).hexdigest()
    assert before == after
    assert (store / "projects" / "test-project" / "closures" / f"{hid}.json").is_file()
    assert json.loads(_cli(source, "candidates").stdout) == []
    included = json.loads(_cli(source, "candidates", "--include-closed").stdout)
    assert included[0]["closed"] is True


def test_status_and_configure_output_do_not_expose_private_path_or_remote(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    store = tmp_path / "secret-private-path"
    remote = tmp_path / "secret-private-remote.git"
    _run(["git", "init", "-q", "--bare", str(remote)], tmp_path)
    configured = _cli(
        source,
        "configure",
        "--path",
        str(store),
        "--remote",
        str(remote),
    )
    status = _cli(source, "status")
    combined = configured.stdout + configured.stderr + status.stdout + status.stderr
    assert str(store) not in combined
    assert str(remote) not in combined
    assert json.loads(configured.stdout)["remote_configured"] is True
    assert json.loads(status.stdout)["remote_configured"] is True


def test_clone_failure_error_does_not_echo_private_remote(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    private_remote = tmp_path / "very-private-name.git"
    result = _cli(
        source,
        "configure",
        "--remote",
        str(private_remote),
        "--path",
        str(tmp_path / "store"),
        check=False,
    )
    assert result.returncode == 2
    assert str(private_remote) not in result.stderr
    assert "could not be cloned" in result.stderr


def test_default_project_id_comes_from_public_pyproject_not_clone_dir(tmp_path: Path) -> None:
    source, _ = _init_source(tmp_path)
    (source / "pyproject.toml").write_text(
        '[project]\nname = "stable-project-id"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    _git(source, "add", "pyproject.toml")
    _git(source, "commit", "-q", "-m", "project metadata")
    payload = json.loads(_cli(source, "status").stdout)
    assert source.name == "source"
    assert payload["project_id"] == "stable-project-id"
