from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.runtime.manifest import write_manifest
from llm_loop.runtime.service_control import (
    DeploymentGenerationConflictError,
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    ManagedServiceMutationGuard,
    ServiceControlAction,
    build_deployment,
    build_restart_plan,
    build_wheel_deployment,
    deployment_identity_key,
    verify_deployment_binding,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool


def _deployment(tmp_path: Path, *, generation: int = 1) -> ManagedServiceDeployment:
    code_root = (tmp_path / "code").resolve()
    runtime_root = (tmp_path / "runtime-root").resolve()
    code_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    (code_root / "scripts").mkdir(parents=True, exist_ok=True)
    (code_root / "scripts" / "restart_mirror.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head="a" * 40,
        code_root=str(code_root),
        runtime_root=str(runtime_root),
        webui_artifact_sha256="b" * 64,
    )


def _write_live_manifest(data_dir: Path, service: str, pid: int) -> None:
    runtime = data_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    payload = {
        "service": service,
        "pid": pid,
        "workspace_root": "/qualified/code-root",
        "git_head": "a" * 40,
        "identity_ok": True,
    }
    (runtime / f"runtime_manifest.{service}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _manifest_snippet(services: str) -> str:
    """Shell fragment: 写与 desired 一致的 runtime manifest，使核验判 confirmed_ok.

    这些用例覆盖 worker 的绑定/锁语义（核验语义另有专测）。lifecycle_agency
    L6/L7 后，不产 manifest 的脚本会落到 verify_evidence_ready（判据缺失≠失败），
    而非 succeeded。
    """
    return (
        'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data/runtime"\n'
        'head=$(git -C "$LFL_RESTART_CODE_ROOT" rev-parse HEAD)\n'
        'started=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n'
        "for svc in " + services + "; do\n"
        '  printf \'{"pid": 1, "git_head": "%s", "started_at": "%s"}\\n\' "$head" "$started" '
        '> "$LFL_RESTART_RUNTIME_ROOT/data/runtime/runtime_manifest.$svc.json"\n'
        "done\n"
    )


def test_deployment_contract_is_closed_schema(tmp_path: Path) -> None:
    dep = _deployment(tmp_path)
    raw = dep.to_dict()
    assert ManagedServiceDeployment.from_dict(raw) == dep

    with pytest.raises(ValueError, match="unknown fields"):
        ManagedServiceDeployment.from_dict({**raw, "caller_cwd": "/tmp"})

    missing = dict(raw)
    missing.pop("git_head")
    with pytest.raises(ValueError, match="missing fields"):
        ManagedServiceDeployment.from_dict(missing)


def test_deployment_store_generation_cas_fails_closed(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    first = _deployment(tmp_path, generation=1)
    store.compare_and_swap(first, expected_generation=0)
    assert store.read() == first

    second = ManagedServiceDeployment(
        **{**first.to_dict(), "deployment_id": "deploy-2", "generation": 2}
    )
    with pytest.raises(DeploymentGenerationConflictError):
        store.compare_and_swap(second, expected_generation=0)
    assert store.read() == first

    store.compare_and_swap(second, expected_generation=1)
    assert store.read() == second


def test_runtime_manifest_writes_service_specific_identity(tmp_path: Path) -> None:
    out = write_manifest({"service": "web", "pid": 123}, tmp_path / "data")
    assert out.name == "runtime_manifest.json"
    specific = tmp_path / "data" / "runtime" / "runtime_manifest.web.json"
    assert json.loads(specific.read_text(encoding="utf-8")) == {"service": "web", "pid": 123}


def test_guard_blocks_exact_real_incident_kill_shape(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 58992)
    _write_live_manifest(data_dir, "feishu", 59055)
    commands = {
        58992: "/venv/bin/python -m llm_loop.runtime.launch web",
        59055: "/venv/bin/python -m llm_loop.runtime.launch feishu",
    }
    guard = ManagedServiceMutationGuard(
        data_dir,
        process_command_reader=lambda pid: commands.get(pid, ""),
    )
    decision = guard.guard(
        "cd /repo && kill -TERM 58992 59055 2>/dev/null; sleep 3; ps -p 58992,59055"
    )
    assert decision is not None
    assert decision.blocked is True
    assert "service_control" in decision.reason
    assert set(decision.services) == {"web", "feishu"}


def test_guard_blocks_previous_web_feishu_kill_shape(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 17029)
    _write_live_manifest(data_dir, "feishu", 15769)
    commands = {
        17029: "/venv/bin/python -m llm_loop.runtime.launch web",
        15769: "/venv/bin/python -m llm_loop.runtime.launch feishu",
    }
    guard = ManagedServiceMutationGuard(data_dir, process_command_reader=lambda fd: commands.get(fd, ""))
    assert guard.guard("kill -TERM 17029 15769; sleep 3") is not None


def test_guard_blocks_official_restart_and_direct_launch_from_generic_shell(tmp_path: Path) -> None:
    guard = ManagedServiceMutationGuard(tmp_path / "data", process_command_reader=lambda _pid: "")
    blocked = [
        "bash scripts/restart_mirror.sh all",
        "sh /repo/scripts/restart_system.sh restart",
        ".venv/bin/python -m llm_loop.runtime.launch web",
        "python3 -m llm_loop.runtime.launch feishu",
        "python3 -m llm_loop.runtime.launch learning",
        "python -m llm_loop.runtime.service_control publish --expected-generation 1",
    ]
    for command in blocked:
        decision = guard.guard(command)
        assert decision is not None, command
        assert decision.blocked is True, command


def test_guard_does_not_turn_generic_shell_readonly(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 111)
    guard = ManagedServiceMutationGuard(
        data_dir,
        process_command_reader=lambda pid: (
            "/venv/bin/python -m llm_loop.runtime.launch web" if pid == 111 else ""
        ),
    )
    allowed = [
        "pytest -q tests/unit/test_runtime_manifest.py",
        "git diff --check",
        "ps -p 111 -o pid,command",
        "kill -0 111",
        "kill -TERM 99999",
        "grep -n restart_mirror.sh docs/LFL-restart-guide.md",
    ]
    for command in allowed:
        assert guard.guard(command) is None, command


def test_service_control_writes_accepted_receipt_before_detached_worker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ManagedServiceDeploymentStore(data_dir)
    dep = _deployment(tmp_path)
    store.compare_and_swap(dep, expected_generation=0)
    seen: list[dict] = []

    def spawn(action_id: str) -> None:
        action = store.read_action(action_id)
        assert action is not None
        assert action.status == "accepted"
        seen.append(action.to_dict())

    tool = ServiceControlTool(
        store=store,
        worker_spawner=spawn,
        session_id_getter=lambda: "session-A",
    )
    result = tool.execute(action="restart", target="all", expected_generation=1)
    assert result.status == ToolResultStatus.SUCCESS
    assert "accepted" in result.content
    assert seen and seen[0]["requester_session_id"] == "session-A"
    assert seen[0]["deployment_generation"] == 1


def test_service_control_rejects_stale_generation_without_spawning(tmp_path: Path) -> None:
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    dep = _deployment(tmp_path)
    store.compare_and_swap(dep, expected_generation=0)
    spawned: list[str] = []
    tool = ServiceControlTool(store=store, worker_spawner=spawned.append)

    result = tool.execute(action="restart", target="web", expected_generation=0)
    assert result.status == ToolResultStatus.FAILURE
    assert "generation" in result.content.lower()
    assert spawned == []


def test_restart_plan_is_bound_only_to_desired_state_roots(tmp_path: Path) -> None:
    dep = _deployment(tmp_path)
    action = ServiceControlAction(
        schema="service-control-action/v1",
        action_id="act-1",
        action="restart",
        target="all",
        deployment_id=dep.deployment_id,
        deployment_generation=dep.generation,
        requester_session_id="session-A",
        status="accepted",
        created_at="2026-09-16T00:00:00+00:00",
        updated_at="2026-09-16T00:00:00+00:00",
        detail="",
    )
    plan = build_restart_plan(action, dep)
    assert plan.argv == ("/bin/bash", str(Path(dep.code_root) / "scripts" / "restart_mirror.sh"), "all")
    assert plan.cwd == dep.runtime_root
    assert plan.env["LFL_RESTART_CODE_ROOT"] == dep.code_root
    assert plan.env["LFL_RESTART_RUNTIME_ROOT"] == dep.runtime_root
    assert "caller_cwd" not in plan.env


def test_tool_registry_blocks_managed_service_kill_before_shell_executes(tmp_path: Path) -> None:
    from llm_loop.core.message import ToolCall
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 4242)
    guard = ManagedServiceMutationGuard(
        data_dir,
        process_command_reader=lambda pid: (
            "/venv/bin/python -m llm_loop.runtime.launch web" if pid == 4242 else ""
        ),
    )
    registry = ToolRegistry(managed_service_guard=guard)
    registry.register(ExecuteCommandTool(timeout_s=1))
    result = registry.execute(
        ToolCall(
            id="call-1",
            name="execute_command",
            arguments={"command": "kill -TERM 4242"},
        )
    )
    assert result.status == ToolResultStatus.BLOCKED
    assert "service_control" in result.content


def test_guard_allows_runtime_launch_dry_run_and_signal_zero_probes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 31337)
    guard = ManagedServiceMutationGuard(
        data_dir,
        process_command_reader=lambda pid: (
            "/venv/bin/python -m llm_loop.runtime.launch web" if pid == 31337 else ""
        ),
    )
    allowed = [
        "python3 -m llm_loop.runtime.launch web --dry-run",
        "python3 -c 'import os; os.kill(31337, 0)'",
        "pkill -0 -f 'llm_loop.runtime.launch web'",
        "bash scripts/restart_mirror.sh status",
    ]
    for command in allowed:
        assert guard.guard(command) is None, command


def test_action_worker_fails_closed_if_generation_changes_after_accept(tmp_path: Path) -> None:
    from llm_loop.runtime.service_control import run_action_worker

    store = ManagedServiceDeploymentStore(tmp_path / "data")
    first = _deployment(tmp_path, generation=1)
    store.compare_and_swap(first, expected_generation=0)
    action = store.accept_restart(
        target="all",
        expected_generation=1,
        requester_session_id="session-A",
    )
    second = ManagedServiceDeployment(
        **{**first.to_dict(), "deployment_id": "deploy-2", "generation": 2}
    )
    store.compare_and_swap(second, expected_generation=1)

    assert run_action_worker(store, action.action_id) == 3
    terminal = store.read_action(action.action_id)
    assert terminal is not None
    assert terminal.status == "failed"
    assert "stale" in terminal.detail or "no longer matches" in terminal.detail


def test_action_worker_records_success_from_desired_state_script(tmp_path: Path) -> None:
    import subprocess

    from llm_loop.runtime.service_control import run_action_worker

    code, runtime = _git_deployment_fixture(tmp_path)
    script = code / "scripts" / "restart_mirror.sh"
    marker = runtime / "worker-marker.txt"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s|%s|%s|%s\\n" "$1" "$LFL_RESTART_CODE_ROOT" "$LFL_RESTART_RUNTIME_ROOT" "${P0A_SHOULD_NOT_LEAK-unset}" > worker-marker.txt\n'
        + _manifest_snippet("web"),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(code), "add", "scripts/restart_mirror.sh"], check=True)
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "worker fixture"], check=True)
    dep = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    store = ManagedServiceDeploymentStore(runtime / "data")
    store.compare_and_swap(dep, expected_generation=0)
    action = store.accept_restart(
        target="web",
        expected_generation=1,
        requester_session_id="session-A",
    )

    import os

    os.environ["P0A_SHOULD_NOT_LEAK"] = "ambient-secret"
    try:
        assert run_action_worker(store, action.action_id) == 0
    finally:
        os.environ.pop("P0A_SHOULD_NOT_LEAK", None)
    terminal = store.read_action(action.action_id)
    assert terminal is not None and terminal.status == "succeeded"
    target, code_root, runtime_root, leaked = marker.read_text(encoding="utf-8").strip().split("|")
    assert target == "web"
    assert code_root == dep.code_root
    assert runtime_root == dep.runtime_root
    assert leaked == "unset"


def test_guard_blocks_common_shell_wrappers_and_dynamic_managed_pid_sources(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_live_manifest(data_dir, "web", 58992)
    _write_live_manifest(data_dir, "feishu", 59055)
    commands = {
        58992: "/venv/bin/python -m llm_loop.runtime.launch web",
        59055: "/venv/bin/python -m llm_loop.runtime.launch feishu",
    }
    guard = ManagedServiceMutationGuard(data_dir, process_command_reader=lambda fd: commands.get(fd, ""))
    blocked = [
        "bash -c 'kill -TERM 58992'",
        "env FOO=1 bash scripts/restart_mirror.sh all",
        "pkill -f 'llm_loop.runtime.launch'",
        "pkill -f 'llm_loop.web'",
        "killall python",
        "kill -TERM $(jq -r .pid data/runtime/runtime_manifest.web.json)",
        "kill -TERM $(jq -r .pid data/feishu_heartbeat.json)",
        "kill -TERM $(lsof -tiTCP:8903 -sTCP:LISTEN)",
        "kill -9 -1",
    ]
    for command in blocked:
        decision = guard.guard(command)
        assert decision is not None and decision.blocked, command


def test_guard_keeps_wrapped_readonly_service_observation_available(tmp_path: Path) -> None:
    guard = ManagedServiceMutationGuard(tmp_path / "data", process_command_reader=lambda _pid: "")
    allowed = [
        "env FOO=1 bash scripts/restart_mirror.sh status",
        "env FOO=1 python3 -m llm_loop.runtime.launch web --dry-run",
        "grep -n 'bash scripts/restart_mirror.sh all' docs/LFL-restart-guide.md",
        "cat data/runtime/runtime_manifest.web.json",
    ]
    for command in allowed:
        assert guard.guard(command) is None, command


def test_guard_does_not_block_textual_mentions_of_launch_or_control_cli(tmp_path: Path) -> None:
    guard = ManagedServiceMutationGuard(tmp_path / "data", process_command_reader=lambda _pid: "")
    allowed = [
        "grep -n 'python -m llm_loop.runtime.launch web' docs/LFL-restart-guide.md",
        "echo 'python3 -m llm_loop.runtime.launch feishu'",
        "grep -R 'llm_loop.runtime.service_control publish' docs tests",
    ]
    for command in allowed:
        assert guard.guard(command) is None, command


def _git_deployment_fixture(tmp_path: Path) -> tuple[Path, Path]:
    import subprocess

    code = tmp_path / "git-code"
    runtime = tmp_path / "git-runtime"
    code.mkdir()
    runtime.mkdir()
    subprocess.run(["git", "init", "-q", str(code)], check=True)
    subprocess.run(["git", "-C", str(code), "config", "user.email", "p0a@test"], check=True)
    subprocess.run(["git", "-C", str(code), "config", "user.name", "p0a-test"], check=True)
    (code / ".gitignore").write_text("webui/dist/\n", encoding="utf-8")
    (code / "pyproject.toml").write_text("[project]\nname='p0a'\nversion='0'\n", encoding="utf-8")
    (code / "scripts").mkdir()
    (code / "scripts" / "restart_mirror.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(code), "add", ".gitignore", "pyproject.toml", "scripts/restart_mirror.sh"],
        check=True,
    )
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "fixture"], check=True)
    dist = code / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>v1</html>\n", encoding="utf-8")
    (dist / "app.js").write_text("console.log('v1')\n", encoding="utf-8")
    return code, runtime


def test_publish_builds_exact_binding_and_verify_accepts_it(tmp_path: Path) -> None:
    code, runtime = _git_deployment_fixture(tmp_path)
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert deployment.generation == 1
    # EVO-20261007-9c6eccf3: code_root 绑定物化的 release checkout（固定 HEAD），
    # 开发树只作为 publish 时的代码来源，前移不再影响既有期望代。
    assert deployment.code_root == str((runtime / ".releases" / deployment.git_head).resolve())
    assert deployment.runtime_root == str(runtime.resolve())
    assert len(deployment.git_head) == 40
    assert len(deployment.webui_artifact_sha256) == 64
    assert verify_deployment_binding(
        deployment,
        code_root=Path(deployment.code_root),
        runtime_root=runtime,
    ) == []


def test_verify_detects_root_head_dirty_and_webui_artifact_drift(tmp_path: Path) -> None:
    import subprocess

    code, runtime = _git_deployment_fixture(tmp_path)
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)

    # EVO-20261007-9c6eccf3: 漂移全部改测绑定树（release checkout）——
    # runtime/head/dirty/webui 的检测语义不变，仅事实源从开发树移到绑定树。
    bound = Path(deployment.code_root)
    wrong_runtime = tmp_path / "wrong-runtime"
    wrong_runtime.mkdir()
    problems = verify_deployment_binding(
        deployment,
        code_root=bound,
        runtime_root=wrong_runtime,
    )
    assert any("runtime_root mismatch" in item for item in problems)

    (bound / "webui" / "dist" / "app.js").write_text("console.log('v2')\n", encoding="utf-8")
    problems = verify_deployment_binding(deployment, code_root=bound, runtime_root=runtime)
    assert any("webui artifact mismatch" in item for item in problems)
    # Feishu-only restart intentionally does not depend on WebUI artifacts.
    assert verify_deployment_binding(
        deployment,
        code_root=bound,
        runtime_root=runtime,
        verify_webui=False,
    ) == []

    (bound / "pyproject.toml").write_text("[project]\nname='p0a'\nversion='dirty'\n", encoding="utf-8")
    problems = verify_deployment_binding(
        deployment,
        code_root=bound,
        runtime_root=runtime,
        verify_webui=False,
    )
    assert "code_root tracked worktree is dirty" in problems
    subprocess.run(["git", "-C", str(bound), "checkout", "--", "pyproject.toml"], check=True)

    (bound / "next.txt").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(bound), "add", "next.txt"], check=True)
    subprocess.run(["git", "-C", str(bound), "commit", "-qm", "next"], check=True)
    problems = verify_deployment_binding(
        deployment,
        code_root=bound,
        runtime_root=runtime,
        verify_webui=False,
    )
    assert any("git_head mismatch" in item for item in problems)


def test_publish_rejects_tracked_dirty_tree_but_allows_ignored_webui_dist(tmp_path: Path) -> None:
    code, runtime = _git_deployment_fixture(tmp_path)
    # dist is ignored and intentionally part of deployment artifact identity, not Git cleanliness.
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert deployment.webui_artifact_sha256
    (code / "pyproject.toml").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tracked worktree must be clean"):
        build_deployment(code_root=code, runtime_root=runtime, generation=2)


def test_lifecycle_lock_serializes_publish_against_physical_restart(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys
    import time

    code, runtime = _git_deployment_fixture(tmp_path)
    marker = runtime / "lifecycle-started"
    script = code / "scripts" / "restart_mirror.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'touch "$LFL_RESTART_RUNTIME_ROOT/lifecycle-started"\n'
        + _manifest_snippet("web feishu learning")
        + "sleep 0.8\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(code), "add", "scripts/restart_mirror.sh"], check=True)
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "lifecycle fixture"], check=True)
    first = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    store = ManagedServiceDeploymentStore(runtime / "data")
    store.compare_and_swap(first, expected_generation=0)
    action = store.accept_restart(
        target="all",
        expected_generation=1,
        requester_session_id="session-A",
    )
    source_root = Path(__file__).resolve().parents[2] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from llm_loop.runtime.service_control import ManagedServiceDeploymentStore, run_action_worker; "
                "raise SystemExit(run_action_worker(ManagedServiceDeploymentStore(sys.argv[1]), sys.argv[2]))"
            ),
            str(store.data_dir),
            action.action_id,
        ],
        env=env,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "worker never entered the physical restart window"

    second = ManagedServiceDeployment(
        **{**first.to_dict(), "deployment_id": "deploy-2", "generation": 2}
    )
    started = time.monotonic()
    store.compare_and_swap(second, expected_generation=1)
    elapsed = time.monotonic() - started
    assert child.wait(timeout=5) == 0
    assert elapsed >= 0.45, f"publish did not wait for lifecycle lease: {elapsed:.3f}s"
    assert store.read() == second

# ── P0-A.1 bootstrap-audit follow-up (2026-09-16) ──


def test_missing_deployment_read_is_strictly_zero_write(tmp_path: Path) -> None:
    data_dir = tmp_path / "read-data"
    store = ManagedServiceDeploymentStore(data_dir)

    assert not data_dir.exists()
    assert store.read() is None
    assert not data_dir.exists(), "read-only missing-state lookup must not create runtime/lock files"


def test_service_control_status_on_missing_state_is_strictly_zero_write(tmp_path: Path) -> None:
    data_dir = tmp_path / "tool-status-data"
    store = ManagedServiceDeploymentStore(data_dir)
    tool = ServiceControlTool(store=store)

    result = tool.execute(action="status")
    assert result.status == ToolResultStatus.SUCCESS
    assert '"deployment": null' in result.content
    assert not data_dir.exists(), "model-visible status must be physically read-only"


def test_cli_show_and_verify_missing_state_are_strictly_zero_write(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    source_root = Path(__file__).resolve().parents[2] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    show_data = tmp_path / "cli-show-data"
    shown = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_loop.runtime.service_control",
            "show",
            "--data-dir",
            str(show_data),
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert shown.returncode == 0
    assert shown.stdout.strip() == "{}"
    assert not show_data.exists(), "CLI show must not create a state-lock directory"

    verify_data = tmp_path / "cli-verify-data"
    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_loop.runtime.service_control",
            "verify",
            "--data-dir",
            str(verify_data),
            "--code-root",
            str(tmp_path),
            "--runtime-root",
            str(tmp_path),
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert verified.returncode == 4
    assert "not published" in verified.stderr
    assert not verify_data.exists(), "CLI verify missing-state path must remain zero-write"


def test_detached_worker_uses_current_control_code_for_pre_p0a_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    from typing import Any

    import llm_loop.runtime.service_control as sc
    from llm_loop.runtime.service_control import spawn_service_control_worker

    code, runtime = _git_deployment_fixture(tmp_path)
    script = code / "scripts" / "restart_mirror.sh"
    marker = runtime / "old-target-ran.txt"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$1" > old-target-ran.txt\n'
        + _manifest_snippet("web feishu learning"),
        encoding="utf-8",
    )
    import subprocess
    subprocess.run(["git", "-C", str(code), "add", "scripts/restart_mirror.sh"], check=True)
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "old target script"], check=True)
    assert not (code / "src" / "llm_loop" / "runtime" / "service_control.py").exists()

    store = ManagedServiceDeploymentStore(runtime / "data")
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    store.compare_and_swap(deployment, expected_generation=0)
    action = store.accept_restart(
        target="all",
        expected_generation=1,
        requester_session_id="session-rollback",
    )

    captured: dict[str, Any] = {}
    original_env_builder = sc._control_subprocess_env

    def _spy(**kwargs: Any) -> dict[str, str]:
        captured.clear()
        captured.update(kwargs)
        return original_env_builder(**kwargs)

    monkeypatch.setattr(sc, "_control_subprocess_env", _spy)
    spawn_service_control_worker(store, action.action_id)
    # Controller identity must be an explicit binding decision, not an
    # accident of PYTHONPATH ordering or a site-packages editable install
    # (which would mask a pre-fix regression in some environments).
    assert captured.get("python_src") is not None, (
        "worker spawn must explicitly bind controller identity via python_src"
    )
    assert Path(str(captured["python_src"])).resolve() == (sc._control_code_root() / "src").resolve()
    deadline = time.monotonic() + 8
    terminal = None
    while time.monotonic() < deadline:
        terminal = store.read_action(action.action_id)
        if terminal is not None and terminal.status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    assert terminal is not None
    assert terminal.status == "succeeded", terminal.detail
    assert marker.read_text(encoding="utf-8").strip() == "all"


def test_worker_reverifies_dirty_target_before_old_script_execution(tmp_path: Path) -> None:
    import subprocess

    from llm_loop.runtime.service_control import run_action_worker

    code, runtime = _git_deployment_fixture(tmp_path)
    marker = runtime / "must-not-run.txt"
    script = code / "scripts" / "restart_mirror.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "touch must-not-run.txt\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(code), "add", "scripts/restart_mirror.sh"], check=True)
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "old target script"], check=True)

    store = ManagedServiceDeploymentStore(runtime / "data")
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    store.compare_and_swap(deployment, expected_generation=0)
    action = store.accept_restart(
        target="all",
        expected_generation=1,
        requester_session_id="session-dirty",
    )

    # Drift after publish/accept: generation/deployment_id still match, bytes do not
    # （EVO-20261007-9c6eccf3: 漂移改测绑定树 release checkout，开发树前移不再是失败源）。
    (Path(deployment.code_root) / "pyproject.toml").write_text(
        "[project]\nname='p0a'\nversion='dirty-after-publish'\n",
        encoding="utf-8",
    )
    rc = run_action_worker(store, action.action_id)
    terminal = store.read_action(action.action_id)

    assert rc != 0
    assert terminal is not None and terminal.status == "failed"
    assert "dirty" in terminal.detail
    assert not marker.exists(), "worker must fail before executing a drifted pre-P0-A script"


# ---------------------------------------------------------------------------
# 2026-11-02：publish 回执必须自证"上一代有没有生效过"
#
# 实测教训：先把未定稿代码 publish 成 N（desired 推进了，但没有任何服务重启
# 到它），继续改代码，再 publish 成 N+1 —— N 一天都没生效过，那次 publish 是
# 纯空转。回执当时只说"restart_required 列出的服务逐个重启"，读起来像"已经
# 部署好了"。这里锁住披露口径：ever_live 必须由**服务实际 stable_generation**
# 派生，而不是由"publish 成功"推断。
# ---------------------------------------------------------------------------


def _convergence(*stable_generations: int | None) -> dict[str, object]:
    services = {
        name: {"stable_generation": gen, "lag_generations": None, "converged": False}
        for name, gen in zip(
            ("web", "feishu", "wecom", "learning"), stable_generations, strict=True
        )
    }
    return {
        "desired_generation": 99,
        "services": services,
        "lagging": list(services),
        "read_only": True,
    }


def test_publish_receipt_flags_superseded_generation_that_never_went_live(
    tmp_path: Path,
) -> None:
    previous = _deployment(tmp_path, generation=370)

    body = ServiceControlTool._supersedes_block(previous, _convergence(369, 369, 368, 369))

    assert body["generation"] == 370
    assert body["ever_live"] is False, "没有任何服务跑到 370，就必须如实说它没生效过"
    assert "空转" in str(body["note"])


def test_publish_receipt_marks_superseded_generation_that_did_go_live(
    tmp_path: Path,
) -> None:
    previous = _deployment(tmp_path, generation=370)
    body = ServiceControlTool._supersedes_block(previous, _convergence(370, 369, 369, 370))
    assert body["ever_live"] is True


def test_publish_receipt_reads_stable_generation_not_publish_success(
    tmp_path: Path,
) -> None:
    """收敛快照读不到任何证据（stable 全 None）时不得据"publish 成功"自证生效。"""
    previous = _deployment(tmp_path, generation=370)
    body = ServiceControlTool._supersedes_block(previous, _convergence(None, None, None, None))
    assert body["ever_live"] is False


def test_publish_receipt_discloses_self_bootstrapping_provenance(tmp_path: Path) -> None:
    """回执由**本次部署之前**的进程生成：缺字段不等于特性没实现（2026-11-02 建议 3）。

    publish/restart 回执由当前在跑的旧代码组装，本次部署新增的字段要等 live 收敛
    到新代后才可能出现。没有这块披露，缺字段会被读成"特性没实现"——本轮就把它
    误读成 publish 回执丢了 supersedes。
    """
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = ServiceControlTool(store=store)

    body = json.loads(tool._publish_result(_deployment(tmp_path), "gate-note", None).content)

    provenance = body["receipt_provenance"]
    assert provenance["fields_added_by_this_deployment_may_be_absent"] is True
    assert "缺字段不等于特性没实现" in str(provenance["note"])
    # live 代码身份是派生事实：读不到就给空表，不得伪造 hash 或影响成功回执。
    assert isinstance(provenance["live_code_heads"], dict)
    assert "lagging" in str(provenance["verify_after"])


def test_restart_receipt_text_also_discloses_provenance(tmp_path: Path) -> None:
    """restart 回执是纯文本，同一披露必须也出现在这一侧，否则只有 publish 有。"""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(_deployment(tmp_path), expected_generation=0)
    spawned: list[str] = []
    tool = ServiceControlTool(store=store, worker_spawner=spawned.append)

    result = tool.execute(action="restart", target="feishu", expected_generation=1)

    assert result.status == ToolResultStatus.SUCCESS
    assert spawned, "受理后必须真的派发 worker"
    assert "本回执由本次部署之前的进程生成" in result.content


# ── DESIGN-20261107 §3.2（v0.2）：deployment schema v2 双部署身份 ──────────
# wheel_release 身份：version + wheel_sha256 + release_dir + package manifest，
# 绝不伪造 git_head；source checkout 语义与 v1 完全一致（保留原逻辑）。


def _wheel_release_layout(tmp_path: Path, version: str = "0.6.40", name: str = "lfl-home") -> Path:
    """构造最小可核验的 LFL_HOME wheel release 布局（安装器产物形态）。"""
    import hashlib as _hl

    lfl_home = (tmp_path / name).resolve()
    release = lfl_home / "releases" / f"LFL-{version}"
    release.mkdir(parents=True, exist_ok=True)
    wheel_name = f"llm_first_loop-{version}-py3-none-any.whl"
    payload = b"fake-wheel-bytes-for-layout"
    (release / wheel_name).write_bytes(payload)
    digest = _hl.sha256(payload).hexdigest()
    (release / ".installer-wheel.sha256").write_text(
        f"{digest}  {wheel_name}\n", encoding="ascii"
    )
    (lfl_home / ".LFL-active-version").write_text(version + "\n", encoding="ascii")
    return lfl_home


def test_deployment_v2_wheel_release_identity_roundtrip(tmp_path: Path) -> None:
    lfl_home = _wheel_release_layout(tmp_path)
    dep = build_wheel_deployment(
        lfl_home,
        data_dir=lfl_home / "data",
        webui_artifact_sha256="c" * 64,
        generation=3,
    )
    assert dep.schema == "lfl.managed-service-deployment/v2"
    assert dep.artifact_kind == "wheel_release"
    assert dep.version == "0.6.40"
    assert dep.wheel_sha256 and len(dep.wheel_sha256) == 64
    assert dep.release_dir == str(lfl_home / "releases" / "LFL-0.6.40")
    assert dep.runtime_root == str(lfl_home)
    assert dep.data_dir == str(lfl_home / "data")
    # git_head 不参与 wheel 身份（空），且不伪造。
    assert dep.git_head == ""
    # v2 是 closed schema：roundtrip 稳定、unknown 字段拒绝。
    raw = dep.to_dict()
    assert ManagedServiceDeployment.from_dict(raw) == dep
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict({**raw, "git_head": "a" * 40})
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict({**raw, "extra": "x"})


def test_deployment_v2_wheel_release_rejects_incomplete_identity(
    tmp_path: Path,
) -> None:
    lfl_home = _wheel_release_layout(tmp_path)
    dep = build_wheel_deployment(
        lfl_home,
        data_dir=lfl_home / "data",
        webui_artifact_sha256="c" * 64,
        generation=1,
    )
    raw = dep.to_dict()
    for missing in ("version", "wheel_sha256", "release_dir", "artifact_kind", "data_dir"):
        stripped = {k: v for k, v in raw.items() if k != missing}
        with pytest.raises(ValueError):
            ManagedServiceDeployment.from_dict(stripped)
    bad_sha = {**raw, "wheel_sha256": "not-hex"}
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict(bad_sha)
    bad_release = {**raw, "release_dir": "relative/path"}
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict(bad_release)
    bad_version = {**raw, "version": "0.6"}
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict(bad_version)
    with_code_root = {**raw, "code_root": "/somewhere"}
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict(with_code_root)


def test_deployment_v2_source_checkout_keeps_v1_semantics_plus_data_dir(
    tmp_path: Path,
) -> None:
    dep = _deployment(tmp_path, generation=2)
    assert dep.schema == "managed-service-deployment/v1"
    assert dep.artifact_kind == "source_checkout"  # v1 读入默认 source 身份
    # v1 序列化保持逐字节兼容（磁盘既有状态零回归）。
    assert set(dep.to_dict()) == {
        "schema", "deployment_id", "generation", "git_head",
        "code_root", "runtime_root", "webui_artifact_sha256",
    }
    # v2 source：v1 字段 + artifact_kind + data_dir；git_head 仍强制 40hex。
    v2 = ManagedServiceDeployment.from_dict(
        {
            **dep.to_dict(),
            "schema": "lfl.managed-service-deployment/v2",
            "artifact_kind": "source_checkout",
            "data_dir": str(tmp_path / "data"),
        }
    )
    assert v2.artifact_kind == "source_checkout"
    assert v2.data_dir == str(tmp_path / "data")
    assert v2.git_head == dep.git_head
    with pytest.raises(ValueError):
        ManagedServiceDeployment.from_dict(
            {
                **dep.to_dict(),
                "schema": "lfl.managed-service-deployment/v2",
                "artifact_kind": "source_checkout",
                "data_dir": str(tmp_path / "data"),
                "git_head": "zz",
            }
        )


def test_build_wheel_deployment_reads_real_lfl_home_identity(tmp_path: Path) -> None:
    lfl_home = _wheel_release_layout(tmp_path)
    dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256="c" * 64, generation=1
    )
    # wheel_sha256 等于清单记录且文件实际摘要一致。
    import hashlib as _hl

    wheel = lfl_home / "releases/LFL-0.6.40/llm_first_loop-0.6.40-py3-none-any.whl"
    assert dep.wheel_sha256 == _hl.sha256(wheel.read_bytes()).hexdigest()


def test_build_wheel_deployment_fails_closed_on_broken_layout(tmp_path: Path) -> None:
    # 指针损坏 → 拒绝，不猜版本。
    lfl_home = _wheel_release_layout(tmp_path, name="bad-pointer")
    (lfl_home / ".LFL-active-version").write_text("garbage\n", encoding="ascii")
    with pytest.raises(ValueError):
        build_wheel_deployment(
            lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256="c" * 64, generation=1
        )
    # 清单摘要与实际字节不符 → 拒绝（完整性失败）。
    lfl_home2 = _wheel_release_layout(tmp_path, name="tampered-wheel")
    wheel = lfl_home2 / "releases/LFL-0.6.40/llm_first_loop-0.6.40-py3-none-any.whl"
    wheel.write_bytes(b"tampered-bytes")
    with pytest.raises(ValueError):
        build_wheel_deployment(
            lfl_home2, data_dir=lfl_home2 / "data", webui_artifact_sha256="c" * 64, generation=1
        )
    # release 目录缺失（指针指向不存在版本）→ 拒绝。
    lfl_home3 = _wheel_release_layout(tmp_path, name="missing-release")
    (lfl_home3 / ".LFL-active-version").write_text("9.9.9\n", encoding="ascii")
    with pytest.raises(ValueError):
        build_wheel_deployment(
            lfl_home3, data_dir=lfl_home3 / "data", webui_artifact_sha256="c" * 64, generation=1
        )


def test_deployment_identity_key_separates_source_and_wheel(tmp_path: Path) -> None:
    lfl_home = _wheel_release_layout(tmp_path)
    wheel_dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256="c" * 64, generation=1
    )
    source_dep = _deployment(tmp_path)
    assert deployment_identity_key(source_dep) == "a" * 40
    key = deployment_identity_key(wheel_dep)
    assert key.startswith("wheel:0.6.40@")
    assert wheel_dep.wheel_sha256[:12] in key
    # source 与 wheel 的身份键永不碰撞为同一形态。
    assert deployment_identity_key(source_dep) != key


def _wheel_binding_layout(tmp_path: Path, name: str) -> tuple[Path, str]:
    """构造带 site-packages WebUI dist 树的 wheel 布局，返回 (lfl_home, webui_sha)。"""
    from llm_loop.runtime.service_control import _tree_sha256

    lfl_home = _wheel_release_layout(tmp_path, name=name)
    dist = (
        lfl_home
        / "releases/LFL-0.6.40/venv/lib/python3.13/site-packages/llm_loop/webui/dist"
    )
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    return lfl_home, _tree_sha256(dist)


def test_verify_deployment_binding_accepts_intact_wheel_release(tmp_path: Path) -> None:
    lfl_home, webui_sha = _wheel_binding_layout(tmp_path, "binding-ok")
    dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256=webui_sha, generation=1
    )
    problems = verify_deployment_binding(
        dep, code_root=lfl_home, runtime_root=lfl_home
    )
    assert problems == []


def test_verify_deployment_binding_reports_wheel_failures_precisely(
    tmp_path: Path,
) -> None:
    lfl_home, webui_sha = _wheel_binding_layout(tmp_path, "binding-bad")
    dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256=webui_sha, generation=1
    )
    # wheel 字节被替换 → 完整性失配（不静默通过）。
    wheel = lfl_home / "releases/LFL-0.6.40/llm_first_loop-0.6.40-py3-none-any.whl"
    original = wheel.read_bytes()
    wheel.write_bytes(original + b"x")
    problems = verify_deployment_binding(
        dep, code_root=lfl_home, runtime_root=lfl_home
    )
    assert any("wheel_sha256_mismatch" in p for p in problems)
    wheel.write_bytes(original)
    # 活动指针漂移 → 指针失配。
    (lfl_home / ".LFL-active-version").write_text("0.0.1\n", encoding="ascii")
    problems = verify_deployment_binding(
        dep, code_root=lfl_home, runtime_root=lfl_home
    )
    assert any("active_pointer_mismatch" in p for p in problems)
    (lfl_home / ".LFL-active-version").write_text("0.6.40\n", encoding="ascii")
    # WebUI 资产树失配 → 资产失配（wheel 布局同样不豁免 WebUI 绑定）。
    dist_index = (
        lfl_home
        / "releases/LFL-0.6.40/venv/lib/python3.13/site-packages/llm_loop/webui/dist/index.html"
    )
    dist_index.write_text("<html>tampered</html>", encoding="utf-8")
    problems = verify_deployment_binding(
        dep, code_root=lfl_home, runtime_root=lfl_home
    )
    assert any("webui_artifact_mismatch" in p for p in problems)


def test_store_roundtrips_wheel_deployment_with_generation_cas(tmp_path: Path) -> None:
    """publish/update 通路对 v2 wheel deployment 零差别开放（CAS 语义不变）。"""
    lfl_home = _wheel_release_layout(tmp_path, name="store-roundtrip")
    dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256="c" * 64, generation=1
    )
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(dep, expected_generation=0)
    assert store.read() == dep
    # 期望代不匹配依旧拒绝（generation CAS 语义对 wheel 一致）。
    with pytest.raises(DeploymentGenerationConflictError):
        store.compare_and_swap(
            dataclasses.replace(dep, generation=2, deployment_id=dep.deployment_id),
            expected_generation=5,
        )


# ── P1-1（审查 b7691f4e）：两个 wheel 比较分支的 live release_version 语义 ──
# 审查定性纠正：live["build"] 在 base 即映射自 manifest build_identity（base
# L2223），两个分支功能上同源；真实缺陷是零测试+隐式跨行耦合。以下测试锁定
# 统一语义（manifest build_identity.release_version == desired.version），并
# 支撑单一 helper 重构后保持绿。


def _write_wheel_live_manifest(
    data_dir: Path, service: str, pid: int, release_version: str | None
) -> None:
    runtime = data_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "service": service,
        "pid": pid,
        "started_at": "2026-11-07T10:00:00+00:00",
        "workspace_root": "/lfl-home",
        "identity_ok": True,
    }
    if release_version is not None:
        release = data_dir.parent / "releases/LFL-0.6.40"
        wheel = release / "llm_first_loop-0.6.40-py3-none-any.whl"
        import hashlib

        payload["python_executable"] = str(release / "venv/bin/python")
        payload["data_dir"] = str(data_dir)
        payload["build_identity"] = {
            "artifact_kind": "wheel_release", "release_version": release_version,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "release_dir": str(release),
            "package_root": str(release / "venv/lib/python3.13/site-packages/llm_loop"),
        }
    (runtime / f"runtime_manifest.{service}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _wheel_store_with_desired(tmp_path: Path, name: str = "p1-1"):
    lfl_home = _wheel_release_layout(tmp_path, name=name)
    dep = build_wheel_deployment(
        lfl_home, data_dir=lfl_home / "data", webui_artifact_sha256="c" * 64, generation=1
    )
    store = ManagedServiceDeploymentStore(lfl_home / "data")
    store.compare_and_swap(dep, expected_generation=0)
    return store, dep


def test_compose_identity_view_wheel_branch_uses_manifest_release_version(
    tmp_path: Path,
) -> None:
    """compose wheel 分支：live 版本取 manifest build_identity.release_version。"""
    import os

    from llm_loop.runtime.service_control import compose_service_identity_view

    store, dep = _wheel_store_with_desired(tmp_path)
    live_pid = os.getpid()  # pytest 进程自身，保证 pid_alive
    _write_wheel_live_manifest(tmp_path / "p1-1" / "data", "web", live_pid, "0.6.40")
    view = compose_service_identity_view(store)
    web = view["services"]["web"]
    assert web["live"]["matches_desired_generation"] is True
    evidence = web["live"]["matches_desired_generation_evidence"]
    assert evidence["artifact_kind"] == "wheel_release"
    assert evidence["desired_version"] == dep.version == "0.6.40"
    assert evidence["live_release_version"] == "0.6.40"
    assert web["restart_required"] is False


def test_compose_identity_view_wheel_branch_missing_and_mismatch_release(
    tmp_path: Path,
) -> None:
    """缺 build_identity → live_release_version_missing；不等 → mismatch。"""
    from llm_loop.runtime.service_control import compose_service_identity_view

    store, _ = _wheel_store_with_desired(tmp_path)
    data_dir = tmp_path / "p1-1" / "data"
    # manifest 存在但无 build_identity（source 风格 manifest 落在 wheel 部署下）。
    _write_wheel_live_manifest(data_dir, "feishu", 4_194_303, None)
    view = compose_service_identity_view(store)
    feishu = view["services"]["feishu"]
    assert any("live_release_version_missing" in r for r in feishu["reasons"])
    # 有 build_identity 但版本不等于 desired。
    _write_wheel_live_manifest(data_dir, "feishu", 4_194_303, "0.6.39")
    view = compose_service_identity_view(store)
    feishu = view["services"]["feishu"]
    assert any(
        "live_release_version_mismatch" in r and "0.6.39" in r and "0.6.40" in r
        for r in feishu["reasons"]
    )


def test_verify_restart_targets_wheel_branch_compares_release_version(
    tmp_path: Path,
) -> None:
    """_verify_restart_targets wheel 分支：与 compose 同源比对 release_version。"""
    import os

    from llm_loop.runtime.service_control import _verify_restart_targets

    store, dep = _wheel_store_with_desired(tmp_path, name="p1-1-verify")
    data_dir = tmp_path / "p1-1-verify" / "data"
    live_pid = os.getpid()
    restarted_at = "2026-11-07T09:00:00+00:00"
    # 版本一致 → confirmed_ok。
    _write_wheel_live_manifest(data_dir, "web", live_pid, "0.6.40")
    verdict, summary, healthy = _verify_restart_targets(
        store, dep, ["web"], restarted_at
    )
    assert verdict == "confirmed_ok"
    assert "web" in healthy
    # 缺 build_identity → 明确失败证据（release_version_missing）。
    _write_wheel_live_manifest(data_dir, "web", live_pid, None)
    verdict, summary, healthy = _verify_restart_targets(
        store, dep, ["web"], restarted_at
    )
    assert verdict == "confirmed_fail"
    assert "release_version_missing" in summary
    # 版本不等于 desired → release_version_mismatch。
    _write_wheel_live_manifest(data_dir, "web", live_pid, "0.6.39")
    verdict, summary, healthy = _verify_restart_targets(
        store, dep, ["web"], restarted_at
    )
    assert verdict == "confirmed_fail"
    assert "release_version_mismatch" in summary and "0.6.39" in summary

