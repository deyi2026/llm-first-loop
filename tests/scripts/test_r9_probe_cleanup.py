"""Regression: a large worktree listing must not defeat EXIT cleanup via SIGPIPE."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "r9_probe_cleanup.sh"


def _run_cleanup(tmp_path: Path, *, registered=True, list_exit=0, remove_exit=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        '#!/bin/sh\ncase "$1 $2" in\n'
        '"worktree list") cat "$LIST_FILE"; exit "$LIST_EXIT";;\n'
        '"worktree remove") printf "%s\\n" "$4" >> "$REMOVE_LOG"; exit "$REMOVE_EXIT";;\n'
        '*) exit 99;;\nesac\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o700)
    probe = str(tmp_path / "probe with spaces")
    listing = tmp_path / "listing"
    listing.write_text(
        (f"worktree {probe}\nHEAD {'a' * 40}\ndetached\n\n" if registered else "")
        + "".join(f"worktree /tmp/other-{i}\nHEAD {'b' * 40}\ndetached\n\n" for i in range(8000)),
        encoding="utf-8",
    )
    removed = tmp_path / "removed"
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "LIST_FILE": str(listing), "REMOVE_LOG": str(removed),
           "LIST_EXIT": str(list_exit), "REMOVE_EXIT": str(remove_exit)}
    proc = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", 'source "$1"; r9_cleanup_probe "$2"',
         "cleanup-test", str(HELPER), probe],
        env=env, text=True, capture_output=True, timeout=10,
    )
    return proc, removed, probe


def test_large_listing_is_consumed_before_registered_probe_removal(tmp_path):
    proc, removed, probe = _run_cleanup(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert removed.read_text(encoding="utf-8").splitlines() == [probe]


def test_unregistered_probe_does_not_remove_another_worktree(tmp_path):
    proc, removed, _ = _run_cleanup(tmp_path, registered=False)
    assert proc.returncode == 0, proc.stderr
    assert not removed.exists()


@pytest.mark.parametrize("failure", ["list", "remove"])
def test_cleanup_failure_is_visible_and_nonzero(tmp_path, failure):
    proc, _, _ = _run_cleanup(
        tmp_path, list_exit=1 if failure == "list" else 0,
        remove_exit=1 if failure == "remove" else 0,
    )
    assert proc.returncode != 0
    assert "PROBE cleanup failed" in proc.stderr


@pytest.mark.parametrize("original_status, expected_status", [(0, 1), (7, 7)])
def test_exit_trap_reports_cleanup_failure_without_hiding_original_failure(
    original_status, expected_status,
):
    wrapper = (ROOT / "scripts" / "r9_commit.sh").read_text(encoding="utf-8")
    function = "r9_cleanup_exit() {" + wrapper.split("r9_cleanup_exit() {", 1)[1].split(
        "\n}\ntrap", 1
    )[0] + "\n}\n"
    proc = subprocess.run(
        ["bash", "-euo", "pipefail", "-c",
         function + 'PROBE_WT=owned\nr9_cleanup_probe() { return 1; }\n'
         + 'trap \'r9_cleanup_exit $?\' EXIT\nexit "$1"\n',
         "exit-test", str(original_status)],
        text=True, capture_output=True, timeout=10,
    )
    assert proc.returncode == expected_status, proc.stderr
