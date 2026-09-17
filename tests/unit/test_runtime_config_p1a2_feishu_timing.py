"""P1-A2: Feishu import-time timing policy must come from RuntimeConfig, not env reads."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.audit_runtime_env import build_inventory, scan_tree

ROOT = Path(__file__).resolve().parents[2]


def test_feishu_timing_fields_are_closed_schema_runtime_toml(tmp_path: Path) -> None:
    from llm_loop.runtime.resolver import parse_runtime_toml

    path = tmp_path / "runtime.toml"
    path.write_text(
        """
[feishu]
exit_wait_s = 7.5
exit_drain_s = 2.25
msg_process_timeout_s = 456.5
silent_threshold_s = 2345.0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    values = parse_runtime_toml(path)
    assert values["FEISHU_EXIT_WAIT_S"] == "7.5"
    assert values["FEISHU_EXIT_DRAIN_S"] == "2.25"
    assert values["FEISHU_MSG_PROCESS_TIMEOUT_S"] == "456.5"
    assert values["FEISHU_SILENT_THRESHOLD_S"] == "2345.0"


def test_feishu_import_timing_uses_runtime_toml_not_stale_shell(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "runtime.toml").write_text(
        """
[feishu]
exit_wait_s = 7.5
exit_drain_s = 2.25
msg_process_timeout_s = 456.5
silent_threshold_s = 2345.0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "LFL_RUNTIME_ROOT": str(runtime_root),
            "LFL_WORKSPACE_ROOT": str(ROOT),
            "PYTHONPATH": str(ROOT / "src"),
            # Stale ambient business values are observable but not authoritative.
            "FEISHU_EXIT_WAIT_S": "1",
            "FEISHU_EXIT_DRAIN_S": "1",
            "FEISHU_MSG_PROCESS_TIMEOUT_S": "1",
            "FEISHU_SILENT_THRESHOLD_S": "1",
        }
    )
    code = r'''
import json
import llm_loop.feishu as feishu
from llm_loop.feishu import bridge
print(json.dumps({
  "exit_wait": feishu._EXIT_WAIT_S,
  "exit_drain": feishu._EXIT_DRAIN_S,
  "bridge_drain": bridge._DRAIN_BUDGET_S,
  "process_timeout": bridge._MSG_PROCESS_TIMEOUT_S,
  "silent_threshold": bridge._SILENT_THRESHOLD_S,
}))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {
        "exit_wait": 7.5,
        "exit_drain": 2.25,
        "bridge_drain": 2.25,
        "process_timeout": 456.5,
        "silent_threshold": 2345.0,
    }


def test_effective_module_import_business_env_reads_are_zero() -> None:
    inventory = build_inventory(scan_tree(ROOT / "src"))
    assert inventory["module_import_direct_access_count"] == 0
    assert inventory["module_import_helper_access_count"] == 0
    assert inventory["module_import_access_count"] == 0


def test_explicit_runtime_override_remains_operator_authority(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "runtime.toml").write_text(
        "[feishu]\nexit_wait_s = 7.5\nexit_drain_s = 2.25\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "LFL_RUNTIME_ROOT": str(runtime_root),
            "LFL_WORKSPACE_ROOT": str(ROOT),
            "LFL_ALLOW_RUNTIME_OVERRIDE": "1",
            "PYTHONPATH": str(ROOT / "src"),
            "FEISHU_EXIT_WAIT_S": "8.5",
            "FEISHU_EXIT_DRAIN_S": "1.5",
        }
    )
    code = "import json, llm_loop.feishu as f; print(json.dumps([f._EXIT_WAIT_S,f._EXIT_DRAIN_S]))"
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [8.5, 1.5]


def test_legacy_dotenv_invalid_timing_fails_open_to_defaults(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / ".env").write_text(
        "FEISHU_EXIT_WAIT_S=invalid\nFEISHU_EXIT_DRAIN_S=\n"
        "FEISHU_MSG_PROCESS_TIMEOUT_S=bad\nFEISHU_SILENT_THRESHOLD_S=oops\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "LFL_RUNTIME_ROOT": str(runtime_root),
            "LFL_WORKSPACE_ROOT": str(ROOT),
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    for key in (
        "LFL_ALLOW_RUNTIME_OVERRIDE",
        "FEISHU_EXIT_WAIT_S",
        "FEISHU_EXIT_DRAIN_S",
        "FEISHU_MSG_PROCESS_TIMEOUT_S",
        "FEISHU_SILENT_THRESHOLD_S",
    ):
        env.pop(key, None)
    code = r'''
import json
import llm_loop.feishu as f
from llm_loop.feishu import bridge
print(json.dumps([f._EXIT_WAIT_S,f._EXIT_DRAIN_S,bridge._MSG_PROCESS_TIMEOUT_S,bridge._SILENT_THRESHOLD_S]))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [10.0, 3.0, 300.0, 1800.0]
