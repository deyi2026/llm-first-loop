"""P1-A contracts for import-time business configuration migration."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_p1_runtime_toml_parses_import_time_business_types(tmp_path: Path) -> None:
    from llm_loop.runtime.resolver import parse_runtime_toml

    path = tmp_path / "runtime.toml"
    path.write_text(
        """
[cache_guard]
perf_block_mode = "enforce"
hit_block = 0.30
hit_warn = 0.85
hit_warn_adaptive = true
hit_warn_tiers = [[30000, 0.65], [80000, 0.75], [200000, 0.80]]
hit_sample = 3
block_escape = 3

[cache_health]
breaker_trigger_runs = 5
breaker_exit_chars_ratio = 0.8
telemetry_strip_audit_log = false
telemetry_strip_tail_lines = 10

[interop]
watch_poll_s = 10.0
wakeup = false
pending_max = 20

[run_cleanup]
stale_run_inspect_hours = 24.0
shutdown_timeout_s = 10.0
confirmation_required = true

[feishu]
ws_watchdog_poll_s = 30
ws_watchdog_lock_s = 180.0
heartbeat_path = "data/feishu_heartbeat.json"
cross_sync = true
cross_sync_poll_s = 1.5
interrupt_notify_timeout_s = 1.0
audit_dir = "data/audit"

[dsh]
sessions_root = "/tmp/dsh-sessions"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    values = parse_runtime_toml(path)
    assert values["CACHE_GUARD_HIT_BLOCK"] == "0.3"
    assert values["CACHE_GUARD_HIT_WARN_ADAPTIVE"] == "1"
    assert values["CACHE_GUARD_HIT_WARN_TIERS"] == "[[30000,0.65],[80000,0.75],[200000,0.8]]"
    assert values["BREAKER_EXIT_CHARS_RATIO"] == "0.8"
    assert values["CACHE_TELEMETRY_STRIP_AUDIT_LOG"] == "0"
    assert values["INBOX_WATCH_POLL_S"] == "10.0"
    assert values["RUN_CLEANUP_CONFIRMATION_REQUIRED"] == "1"
    assert values["FEISHU_CROSS_SYNC"] == "1"
    assert values["DSH_SESSIONS_ROOT"] == "/tmp/dsh-sessions"


def test_business_config_snapshot_is_file_backed_nonsecret_and_immutable(tmp_path: Path) -> None:
    from llm_loop.runtime.resolver import business_config_snapshot

    (tmp_path / "runtime.toml").write_text(
        """
[cache_guard]
hit_warn = 0.91
[feishu]
ws_queue_max = 77
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "CACHE_GUARD_HIT_WARN=0.42\nFEISHU_WS_QUEUE_MAX=55\nLLM_API_KEY=do-not-project\n",
        encoding="utf-8",
    )

    snap = business_config_snapshot("p1-test", env={}, workspace_root=tmp_path)
    assert snap["CACHE_GUARD_HIT_WARN"] == "0.91"
    assert snap["FEISHU_WS_QUEUE_MAX"] == "77"
    assert "LLM_API_KEY" not in snap
    with pytest.raises(TypeError):
        snap["CACHE_GUARD_HIT_WARN"] = "0.1"  # type: ignore[index]


def test_import_time_modules_read_runtime_toml_not_stale_shell(tmp_path: Path) -> None:
    import json
    import os
    import subprocess
    import sys

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "runtime.toml").write_text(
        """
[cache_guard]
hit_warn = 0.91
[cache_health]
breaker_trigger_runs = 7
[interop]
watch_poll_s = 12.5
[run_cleanup]
stale_run_inspect_hours = 36.0
[feishu]
ws_watchdog_poll_s = 41
interrupt_notify_timeout_s = 2.5
cross_sync_max_chars = 12345
audit_dir = "custom/audit"
[dsh]
sessions_root = "/tmp/p1-dsh"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "LFL_RUNTIME_ROOT": str(runtime_root),
            "LFL_WORKSPACE_ROOT": str(Path(__file__).resolve().parents[2]),
            "CACHE_GUARD_HIT_WARN": "0.12",  # stale shell must not win by default
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        }
    )
    code = r'''
import json
from llm_loop.cache_guard import guard
from llm_loop.core import cache_health, interop_watch, scheduler
from llm_loop.core.loop import runner
from llm_loop.feishu import bridge, compensation, cross_sync
from llm_loop.introspection import tools_feishu_outbound
from llm_loop.tools.builtin import dsh_session_read
print(json.dumps({
  "hit_warn": guard._HIT_RATE_WARN,
  "breaker": cache_health._BREAKER_TRIGGER_RUNS,
  "poll": interop_watch._POLL_S,
  "cleanup": runner._STALE_RUN_INSPECT_HOURS,
  "schedule_parent": str(scheduler._SCHEDULE_PATH.parent),
  "watchdog": bridge._WATCHDOG_POLL_S,
  "notify": compensation._NOTIFY_TIMEOUT_S,
  "cross_chars": cross_sync._MAX_CHARS,
  "audit": str(tools_feishu_outbound._outbound_audit_path),
  "dsh": str(dsh_session_read._DSH_SESSIONS_ROOT),
}))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    values = json.loads(proc.stdout.strip().splitlines()[-1])
    assert values == {
        "hit_warn": 0.91,
        "breaker": 7,
        "poll": 12.5,
        "cleanup": 36.0,
        "schedule_parent": "data",
        "watchdog": 41,
        "notify": 2.5,
        "cross_chars": 12345,
        "audit": "custom/audit/feishu_outbound.jsonl",
        "dsh": "/tmp/p1-dsh",
    }


def test_runtime_toml_example_remains_parseable() -> None:
    from llm_loop.runtime.resolver import parse_runtime_toml

    root = Path(__file__).resolve().parents[2]
    values = parse_runtime_toml(root / "runtime.toml.example")
    assert values["CACHE_GUARD_PERF_BLOCK"] == "enforce"
    assert values["FEISHU_CROSS_SYNC"] == "1"
