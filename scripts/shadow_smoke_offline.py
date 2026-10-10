#!/usr/bin/env python3
"""Offline, fail-closed execution-knowledge smoke driver.

The ONLY supported mode is the checked-in FakeLLM pytest case. Do not add an
HTTP endpoint/model switch here: a live smoke requires independent budget and
capability authority at the real provider and tool-execution boundaries.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

_MAX_WALL_SECONDS = 20.0
_TEST_PATH = "tests/unit/test_shadow_bounded_smoke.py"


def _run_isolated(
    argv: list[str], *,
    cwd: Path, env: dict[str, str], timeout_seconds: float,
) -> tuple[int, str]:
    """A child wall deadline terminates its entire process group, not only pytest."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = process.communicate(timeout=timeout_seconds)
        return process.returncode, out
    except subprocess.TimeoutExpired:
        # The child is a new POSIX session. Never signal another program's PID.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            out, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            out, _ = process.communicate()
        return 124, (out or "") + "\nFAIL: offline smoke hard wall deadline exceeded\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provider-free, zero-tool, single-round Shadow smoke"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Explicit offline mode (the only supported mode)",
    )
    options = parser.parse_args(argv)
    if not options.offline:
        parser.error("--offline is mandatory; live provider execution is prohibited")
    if os.name != "posix":
        parser.error("process-group wall enforcement requires POSIX")

    root = Path(__file__).resolve().parents[1]
    if not (root / _TEST_PATH).is_file() or not (root / "src/llm_loop").is_dir():
        parser.error("closed smoke fixture or source root is unavailable")

    with tempfile.TemporaryDirectory(prefix="lfl-shadow-offline-") as td:
        # Do not inherit production provider credentials, model routes, or tool
        # runtime switches from the operator's environment. All writes land in
        # a temporary HOME / data directory; tests/conftest.py adds a second
        # real-data isolation fence and chdir(tmp_path).
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": td,
            "TMPDIR": td,
            "PYTHONPATH": str(root / "src"),
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "DATA_DIR": str(Path(td) / "data"),
            "LFL_DATA_DIR": str(Path(td) / "data"),
            "LLM_API_KEY": "offline-do-not-route",
            "LLM_BASE_URL": "https://offline.invalid/v1",
            "LLM_MODEL": "fake-model",
        }
        cmd = [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            _TEST_PATH,
        ]
        rc, output = _run_isolated(
            cmd, cwd=root, env=safe_env, timeout_seconds=_MAX_WALL_SECONDS,
        )
        print(output, end="" if output.endswith("\n") else "\n")
        print(
            "offline_smoke_exit=" + str(rc)
            + " provider=FakeLLM tool_registry=empty"
            + " max_provider_calls=1 max_iterations=1"
            + " max_input_tokens=2000 max_output_tokens=128"
            + " max_wall_s=20"
        )
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
