"""M1 T02 real-shape contract: inner process effect survives shell status masking."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import run_pilot as rp
import telemetry as tl


def main() -> None:
    task = {
        "id": "t02_retry_transient",
        "first_tools": ["command"],
        "expected_failures": [
            {"tool_class": "command", "check_id": "t02.gen", "exit_code": 1}
        ],
        "effect_probe": {
            "kind": "process_exit",
            "check_id": "t02.gen",
            "target_basename": "gen.py",
            "tool_class": "command",
        },
    }
    with tempfile.TemporaryDirectory(prefix="agentpilot-t02-red-") as td:
        ws = Path(td)
        # Keep the task source identical in semantics: no embedded telemetry/probe code.
        (ws / "gen.py").write_text(
            "import os, json\n"
            "if not os.path.exists('.ran_once'):\n"
            "    open('.ran_once','w').write('1')\n"
            "    raise SystemExit('transient: first run always fails (race with indexer)')\n"
            "json.dump({'ok': True, 'n': 42}, open('result.json','w'))\n"
            "print('done')\n"
        )
        env = rp._prepare_effect_probe(task, ws, dict(os.environ))
        assert not (ws / ".agentpilot-effects").exists()
        assert not any(x.name.startswith(".agentpilot-effect") for x in ws.iterdir())

        # Reproduce the real LFL shape: inner gen.py exits 1, but the shell command
        # masks it by running a succeeding echo afterwards, so outer rc == 0.
        first = subprocess.run(
            ["/bin/zsh", "-c", 'python3 gen.py; echo "EXIT=$?"'],
            cwd=ws, env=env, capture_output=True, text=True, check=False,
        )
        assert first.returncode == 0, first
        second = subprocess.run(
            ["/bin/zsh", "-c", 'python3 gen.py; echo "EXIT=$?"'],
            cwd=ws, env=env, capture_output=True, text=True, check=False,
        )
        assert second.returncode == 0, second

        effects, status = rp._collect_task_effects(task, ws)
        assert status == "ok", (status, effects)
        assert [e["exit_code"] for e in effects] == [1, 0], effects
        assert all(e["check_id"] == "t02.gen" for e in effects), effects

        # Raw tool receipts deliberately look successful and contain no failure marker.
        # The score must come from the structured effect receipt, not prose parsing.
        events = {
            "t0": "",
            "turns": [],
            "source": "real-shape-fixture",
            "calls": [
                {"name": "execute_command", "classes": ["command"],
                 "args": '{"command":"python3 gen.py; echo EXIT=$?"}',
                 "ok": True, "result": "masked outer success", "turn": 1,
                 "result_truncated": False},
                {"name": "execute_command", "classes": ["command"],
                 "args": '{"command":"python3 gen.py; echo EXIT=$?"}',
                 "ok": True, "result": "masked outer success", "turn": 2,
                 "result_truncated": False},
            ],
        }
        score = tl.score_fcr(
            {"name": "execute_command", "args": {"command": "python3 gen.py"}, "ok_signal": True},
            events,
            task,
            task_effects=effects,
            task_effects_status=status,
        )
        assert score["expected_failure_count"] == 1, score
        assert score["confirmed_repair_count"] == 1, score
        assert score["unexpected_failure_count"] == 0, score
        assert score["expected_failure_unresolvable_count"] == 0, score

    print("T02 EFFECT RECEIPT REAL-SHAPE PASS")


if __name__ == "__main__":
    main()
