"""#3 回归：服务日志轮转（restart_mirror._spawn_detached）+ 重复失败降噪."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from llm_loop.methods import learning_plane as lp

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "restart_mirror.sh"


def _spawn_detached_source() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("_spawn_detached() {")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


def _run_spawn(tmp_path: Path, log: Path, limit: str) -> subprocess.CompletedProcess:
    runner = tmp_path / "runner.sh"
    runner.write_text(
        "set -euo pipefail\nVENV_PY=/usr/bin/true\n"
        + _spawn_detached_source()
        + "\n_spawn_detached \"$1\"\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(runner), str(log)],
        env={**os.environ, "LFL_LOG_ROTATE_BYTES": limit},
        capture_output=True,
        text=True,
        check=False,
    )


def test_oversized_log_is_rotated_to_single_generation(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    log.write_text("x" * 200, encoding="utf-8")
    result = _run_spawn(tmp_path, log, "100")
    assert result.returncode == 0, result.stderr
    rotated = tmp_path / "svc.log.1"
    assert rotated.is_file()
    assert rotated.stat().st_size == 200
    assert log.is_file() and log.stat().st_size == 0
    assert "[log-rotate]" in result.stderr


def test_small_log_is_left_in_place(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    log.write_text("x" * 10, encoding="utf-8")
    result = _run_spawn(tmp_path, log, "100")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "svc.log.1").exists()
    assert log.read_text(encoding="utf-8") == "x" * 10


def test_rotation_keeps_exactly_one_previous_generation(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    (tmp_path / "svc.log.1").write_text("old" * 50, encoding="utf-8")
    log.write_text("y" * 300, encoding="utf-8")
    assert _run_spawn(tmp_path, log, "100").returncode == 0
    assert (tmp_path / "svc.log.1").read_text(encoding="utf-8") == "y" * 300
    assert not (tmp_path / "svc.log.2").exists()


@pytest.fixture(autouse=True)
def _reset_dedupe_state():
    lp._repeated_failure_state.clear()
    yield
    lp._repeated_failure_state.clear()


def _logger() -> logging.Logger:
    return logging.getLogger("tests.learning.dedupe")


def test_same_root_cause_logs_once_with_full_traceback(caplog) -> None:
    logger = _logger()
    with caplog.at_level(logging.WARNING, logger="tests.learning.dedupe"):
        for _ in range(5):
            lp._log_repeated_failure(
                logger, ValueError("模型 not in registry"), "learn:1"
            )
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "crashed fail-open" in record.getMessage()
    assert "x1" in record.getMessage()
    assert record.exc_info is not None


def test_new_root_cause_is_not_swallowed(caplog) -> None:
    logger = _logger()
    with caplog.at_level(logging.WARNING, logger="tests.learning.dedupe"):
        lp._log_repeated_failure(logger, ValueError("cause A"), "j1")
        lp._log_repeated_failure(logger, ValueError("cause B"), "j2")
    assert len(caplog.records) == 2
    assert "cause A" in caplog.records[0].getMessage()
    assert "cause B" in caplog.records[1].getMessage()


def test_batch_summary_reports_suppressed_count(monkeypatch, caplog) -> None:
    monkeypatch.setattr(lp, "_REPEATED_FAILURE_EVERY_N", 3)
    logger = _logger()
    with caplog.at_level(logging.WARNING, logger="tests.learning.dedupe"):
        for _ in range(7):
            lp._log_repeated_failure(logger, RuntimeError("flood"), "j")
    assert len(caplog.records) == 3
    last = caplog.records[-1].getMessage()
    assert "suppressed=" in last
    assert "x7" in last
