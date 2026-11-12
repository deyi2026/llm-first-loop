
"""Execute the real gate wrapper with failing boundary tools."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.unit import test_ci_gate_conclusion_line as harness


def _release_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    run = subprocess.run

    def release(args, *a, **kw):
        if args == ["bash", "scripts/ci_gate.sh"]:
            args = [*args, "--release"]
        return run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", release)


def test_release_requires_completed_type_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_mode(monkeypatch)
    result = harness._run_gate(
        tmp_path, "R9 pyright status=unknown",
        python_script=harness._FAKE_PYTHON.replace('*"-c"*', '"-c "*'),
    )
    assert result.returncode != 0
    assert "✅ ci_gate 全链路通过" not in result.stdout


def test_release_accepts_completed_type_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_mode(monkeypatch)
    result = harness._run_gate(tmp_path, "R9 pyright status=complete")
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontend_behavior_failure_blocks_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness, "_FAKE_NPM", """#!/bin/sh
if [ "$1" = test ]; then echo 'behavior regression' >&2; exit 17; fi
mkdir -p dist && : > dist/index.html
""")
    result = harness._run_gate(tmp_path, "R9 pyright status=complete")
    assert result.returncode != 0
    assert "behavior regression" in result.stderr
    assert "✅ ci_gate 全链路通过" not in result.stdout
