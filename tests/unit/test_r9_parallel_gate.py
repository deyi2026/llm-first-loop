"""Real wrapper, disposable repository: concurrent isolated gates and exact CAS."""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def checkouts(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    scripts = repo / "scripts"
    scripts.mkdir()
    for name in ("r9_commit.sh", "r9_probe_cleanup.sh"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    for name in ("r9_commit_check.sh", "git_security_scan.sh"):
        (scripts / name).write_text("#!/bin/bash\nexit 0\n")
    (scripts / "ci_gate.sh").write_text(
        '#!/bin/bash\nset -eu\n'
        'echo "gate-live-$R9_TEST_CASE"\n'
        'touch "$R9_TEST_BARRIER/$R9_TEST_CASE.ready"\n'
        'for i in $(seq 1 150); do\n'
        '  if [ -f "$R9_TEST_BARRIER/release" ]; then exit 0; fi\n'
        '  sleep 0.1\n'
        'done\nexit 1\n'
    )
    (repo / "seed").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    second = tmp_path / "second"
    _git(repo, "worktree", "add", "-qb", "second", str(second))
    for checkout in (repo, second):
        (checkout / "seed").write_text(f"candidate-{checkout.name}\n")
        _git(checkout, "add", "seed")
    return repo, second


def _start(checkout: Path, tmp_path: Path, case: str):
    output = tmp_path / f"{case}.output"
    env = {**os.environ, "R9_TEST_BARRIER": str(tmp_path), "R9_TEST_CASE": case,
           "R9_PROBE_ROOT": str(tmp_path / "probes"), "R9_STAGED_ALLOW": "seed",
           "R9_GATE_RECEIPT_FILE": str(tmp_path / f"{case}.receipt"),
           "R9_COMMIT_LOCK_TIMEOUT": "8"}
    with output.open("w") as stream:
        proc = subprocess.Popen(["bash", "scripts/r9_commit.sh", "fix(r9): test"],
                                cwd=checkout, env=env, stdout=stream,
                                stderr=subprocess.STDOUT)
    return proc, output


def _wait_live(tmp_path: Path, case: str, proc, output: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (tmp_path / f"{case}.ready").exists() and f"gate-live-{case}" in output.read_text():
            return
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    pytest.fail(f"gate did not stream while running: {output.read_text()}")


def test_two_worktrees_gate_concurrently_then_commit(checkouts, tmp_path):
    first, second = checkouts
    procs = []
    try:
        a, ao = _start(first, tmp_path, "a")
        procs.append(a)
        _wait_live(tmp_path, "a", a, ao)
        b, bo = _start(second, tmp_path, "b")
        procs.append(b)
        _wait_live(tmp_path, "b", b, bo)
        assert a.poll() is None and b.poll() is None
        (tmp_path / "release").touch()
        assert a.wait(timeout=15) == 0, ao.read_text()
        assert b.wait(timeout=15) == 0, bo.read_text()
        assert _git(first, "rev-list", "--count", "HEAD") == "2"
        assert _git(second, "rev-list", "--count", "HEAD") == "2"
        assert "gate-live-a" in (tmp_path / "a.receipt").read_text()
        assert "gate-live-b" in (tmp_path / "b.receipt").read_text()
    finally:
        (tmp_path / "release").touch()
        for proc in procs:
            if proc.poll() is None:
                proc.wait(timeout=20)


def test_index_drift_during_gate_is_refused(checkouts, tmp_path):
    first, _ = checkouts
    head = _git(first, "rev-parse", "HEAD")
    proc, output = _start(first, tmp_path, "stale")
    try:
        _wait_live(tmp_path, "stale", proc, output)
        (first / "seed").write_text("changed during gate\n")
        _git(first, "add", "seed")
        (tmp_path / "release").touch()
        assert proc.wait(timeout=15) != 0
        assert "R9_CANDIDATE_STALE" in output.read_text()
        assert _git(first, "rev-parse", "HEAD") == head
        assert _git(first, "show", ":seed") == "changed during gate"
    finally:
        (tmp_path / "release").touch()
        if proc.poll() is None:
            proc.wait(timeout=20)


def test_hook_mutation_cannot_advance_original_ref(checkouts, tmp_path):
    first, _ = checkouts
    head = _git(first, "rev-parse", "HEAD")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text('#!/bin/bash\nprintf "hook mutation\\n" > seed\ngit add seed\n')
    hook.chmod(0o755)
    _git(first, "config", "core.hooksPath", str(hooks))
    proc, output = _start(first, tmp_path, "hook")
    try:
        _wait_live(tmp_path, "hook", proc, output)
        (tmp_path / "release").touch()
        assert proc.wait(timeout=15) != 0
        assert "hook changed candidate tree/parent" in output.read_text()
        assert _git(first, "rev-parse", "HEAD") == head
        assert _git(first, "show", ":seed") in (f"candidate-{first.name}", "hook mutation")
        # Native hooks may edit the working tree; never discard those edits.
        assert (first / "seed").read_text() == "hook mutation\n"
    finally:
        (tmp_path / "release").touch()
        if proc.poll() is None:
            proc.wait(timeout=20)


def test_global_lock_acquire_is_idempotent_in_fcntl_mode(tmp_path):
    script = (ROOT / "scripts/r9_commit.sh").read_text()
    lock_code = script[script.index("LOCK_PROG="):script.index("trap 'r9_release_locks' EXIT")]
    # Force only the lock implementation selection to fcntl, exercising the
    # real holder protocol without granting or mocking any dev authorization.
    lock_code = lock_code.replace("if command -v flock >/dev/null 2>&1; then", "if false; then")
    setup = '''
COMMON_LOCK_FILE="$1"
LOCK_TIMEOUT=2
LOCK_HOLDER_PID=""
WORKTREE_LOCK_HOLDER_PID=""
GLOBAL_LOCK_HOLDER_PID=""
GLOBAL_LOCK_ACQUIRED=0
'''
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", setup + lock_code + '''
trap r9_release_locks EXIT
r9_acquire_global_lock
first="$GLOBAL_LOCK_HOLDER_PID"
r9_acquire_global_lock
[[ -n "$first" && "$first" == "$GLOBAL_LOCK_HOLDER_PID" ]]
kill -0 "$first"
''', "lock-test", str(tmp_path / "common.lock")],
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("R9 lock acquired") == 1


def test_receipt_archive_replaces_instead_of_accumulating(tmp_path):
    script = (ROOT / "scripts/r9_commit.sh").read_text()
    archive = script[script.index("r9_archive_receipt() {"):script.index("r9_cleanup_exit() {")]
    source, destination = tmp_path / "gate", tmp_path / "last.log"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", archive + '''
GATE_LOG="$1"
printf first > "$GATE_LOG"
r9_archive_receipt "$2"
printf second > "$GATE_LOG"
r9_archive_receipt "$2"
''', "receipt-test", str(source), str(destination)],
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert destination.read_text() == "second"
    assert list(tmp_path.glob("last.log*")) == [destination]


def test_gate_resource_slots_and_exclusive_phase(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    script = (ROOT / "scripts/ci_gate.sh").read_text()
    resource = script[script.index('CI_RESOURCE_DIR='):script.index('echo "═══ [1/5] Ruff')]
    procs = []

    def start(case, exclusive=False):
        output = tmp_path / f"{case}.resource"
        body = resource + '\necho shared-ready\n'
        if exclusive:
            body += 'while [ ! -f "$BARRIER/switch" ]; do sleep 0.05; done\nci_resource_phase exclusive\necho exclusive-ready\n'
        body += 'while [ ! -f "$BARRIER/$CASE.release" ]; do sleep 0.05; done\n'
        env = {**os.environ, "ROOT": str(repo), "BARRIER": str(tmp_path), "CASE": case}
        with output.open("w") as stream:
            proc = subprocess.Popen(["bash", "-euo", "pipefail", "-c", body], cwd=repo,
                                    env=env, stdout=stream, stderr=subprocess.STDOUT)
        procs.append((case, proc, output))
        return proc, output

    def wait_text(proc, output, text):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.poll() is None:
            if text in output.read_text():
                return
            time.sleep(0.05)
        pytest.fail(output.read_text())

    try:
        a, ao = start("a", exclusive=True)
        wait_text(a, ao, "shared-ready")
        b, bo = start("b")
        wait_text(b, bo, "shared-ready")
        c, co = start("c")
        time.sleep(0.4)
        assert c.poll() is None and "shared-ready" not in co.read_text()
        (tmp_path / "switch").touch()
        wait_text(a, ao, "waiting for exclusive phase")
        time.sleep(0.3)
        assert "exclusive-ready" not in ao.read_text()
        # The third gate can exit as soon as it gets a slot; either ordering
        # with A's exclusive acquisition is safe.
        (tmp_path / "c.release").touch()
        (tmp_path / "b.release").touch()
        assert b.wait(timeout=10) == 0, bo.read_text()
        wait_text(a, ao, "exclusive-ready")
        (tmp_path / "a.release").touch()
        assert a.wait(timeout=10) == 0, ao.read_text()
        assert c.wait(timeout=10) == 0, co.read_text()
    finally:
        (tmp_path / "switch").touch()
        for case, _proc, _ in procs:
            (tmp_path / f"{case}.release").touch()
        for _, proc, _ in procs:
            if proc.poll() is None:
                proc.wait(timeout=15)


def test_native_branch_hooks_and_reflog_are_preserved(checkouts, tmp_path):
    first, _ = checkouts
    hooks = tmp_path / "native-hooks"
    hooks.mkdir()
    trace = tmp_path / "hook-trace"
    for name in ("pre-commit", "commit-msg", "post-commit", "reference-transaction"):
        hook = hooks / name
        if name == "reference-transaction":
            body = f'printf "ref-%s\\n" "$1" >> {trace}\ncat >> {trace}\n'
        else:
            body = f'test "$(git branch --show-current)" = main || exit 91\nprintf "{name}\\n" >> {trace}\n'
        hook.write_text("#!/bin/bash\n" + body)
        hook.chmod(0o755)
    _git(first, "config", "core.hooksPath", str(hooks))
    proc, output = _start(first, tmp_path, "native")
    try:
        _wait_live(tmp_path, "native", proc, output)
        (tmp_path / "release").touch()
        assert proc.wait(timeout=15) == 0, output.read_text()
        recorded = trace.read_text()
        assert all(name in recorded for name in ("pre-commit", "commit-msg", "post-commit", "ref-prepared", "ref-committed"))
        assert "refs/heads/main" in recorded
        assert _git(first, "reflog", "-1", "--format=%gs", "HEAD") == "commit: fix(r9): test"
        assert _git(first, "config", "core.hooksPath") == str(hooks)
    finally:
        (tmp_path / "release").touch()
        if proc.poll() is None:
            proc.wait(timeout=20)


def test_branch_specific_hook_rejection_is_not_bypassed(checkouts, tmp_path):
    first, _ = checkouts
    head = _git(first, "rev-parse", "HEAD")
    hooks = tmp_path / "branch-hooks"
    hooks.mkdir()
    hook = hooks / "commit-msg"
    hook.write_text('#!/bin/bash\nif [ "$(git branch --show-current)" = main ]; then echo branch-policy-denied >&2; exit 91; fi\n')
    hook.chmod(0o755)
    _git(first, "config", "core.hooksPath", str(hooks))
    proc, output = _start(first, tmp_path, "branch-deny")
    try:
        _wait_live(tmp_path, "branch-deny", proc, output)
        (tmp_path / "release").touch()
        assert proc.wait(timeout=15) != 0
        assert "branch-policy-denied" in output.read_text()
        assert _git(first, "rev-parse", "HEAD") == head
    finally:
        (tmp_path / "release").touch()
        if proc.poll() is None:
            proc.wait(timeout=20)


def test_explicit_receipt_symlink_retains_original_copy_semantics(checkouts, tmp_path):
    first, _ = checkouts
    target = tmp_path / "existing-receipt"
    target.write_text("old")
    target.chmod(0o640)
    link = tmp_path / "symlink.receipt"
    link.symlink_to(target)
    proc, output = _start(first, tmp_path, "symlink")
    try:
        _wait_live(tmp_path, "symlink", proc, output)
        (tmp_path / "release").touch()
        assert proc.wait(timeout=15) == 0, output.read_text()
        assert link.is_symlink() and "gate-live-symlink" in target.read_text()
        assert target.stat().st_mode & 0o777 == 0o640
    finally:
        (tmp_path / "release").touch()
        if proc.poll() is None:
            proc.wait(timeout=20)


def test_resource_holders_release_after_gate_death_with_live_descendant(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    script = (ROOT / "scripts/ci_gate.sh").read_text()
    resource = script[script.index('CI_RESOURCE_DIR='):script.index('echo "═══ [1/5] Ruff')]
    body = resource + '\nsleep 30 &\necho $! > "$CHILD"\nwhile :; do sleep 0.1; done\n'
    child_file = tmp_path / "child.pid"
    proc = subprocess.Popen(["bash", "-euo", "pipefail", "-c", body], cwd=repo,
                            env={**os.environ, "ROOT": str(repo), "CHILD": str(child_file)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child = None
    try:
        deadline = time.monotonic() + 10
        while not child_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        child = int(child_file.read_text())
        proc.kill()
        proc.wait(timeout=5)
        # The descendant is still alive, but cannot retain either lock.
        os.kill(child, 0)
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", resource + '\nci_resource_phase exclusive\n'],
                                cwd=repo, env={**os.environ, "ROOT": str(repo)},
                                text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, 15)


def test_dev_and_normal_share_worktree_lock_before_common(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-qb", "main")
    script = (ROOT / "scripts/r9_commit.sh").read_text()
    locks = script[script.index('LOCK_PROG='):script.index('# 队头 ff 再检')]
    setup = '''
COMMON_LOCK_FILE="$PWD/.git/common.lock"
WORKTREE_LOCK_FILE="$PWD/.git/worktree.lock"
LOCK_TIMEOUT=5
LOCK_HOLDER_PID=""
WORKTREE_LOCK_HOLDER_PID=""
GLOBAL_LOCK_HOLDER_PID=""
GLOBAL_LOCK_ACQUIRED=0
DEV_MODE="$1"
'''
    # Test only the real lock ordering, never fake a Host dev grant.
    body = setup + locks + '\necho ready > "$READY"\nwhile [ ! -f "$RELEASE" ]; do sleep 0.05; done\n'
    procs = []
    try:
        for mode in (0, 1):
            ready, release = tmp_path / f"ready-{mode}", tmp_path / f"release-{mode}"
            proc = subprocess.Popen(["bash", "-euo", "pipefail", "-c", body, "lock-test", str(mode)],
                                    cwd=repo, env={**os.environ, "READY": str(ready), "RELEASE": str(release)},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append((proc, release))
            if mode == 0:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert ready.exists()
            else:
                time.sleep(0.5)
                assert proc.poll() is None and not ready.exists()
        procs[0][1].touch()
        assert procs[0][0].wait(timeout=10) == 0
        deadline = time.monotonic() + 5
        while not (tmp_path / "ready-1").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "ready-1").exists()
        procs[1][1].touch()
        assert procs[1][0].wait(timeout=10) == 0
    finally:
        for proc, release in procs:
            release.touch()
            if proc.poll() is None:
                proc.wait(timeout=15)
