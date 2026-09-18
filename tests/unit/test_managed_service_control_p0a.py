from __future__ import annotations

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
    guard = ManagedServiceMutationGuard(data_dir, process_command_reader=commands.get)
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
    from llm_loop.runtime.service_control import run_action_worker

    store = ManagedServiceDeploymentStore(tmp_path / "data")
    dep = _deployment(tmp_path, generation=1)
    script = Path(dep.code_root) / "scripts" / "restart_mirror.sh"
    marker = Path(dep.runtime_root) / "worker-marker.txt"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s|%s|%s|%s\\n" "$1" "$LFL_RESTART_CODE_ROOT" "$LFL_RESTART_RUNTIME_ROOT" "${P0A_SHOULD_NOT_LEAK-unset}" > worker-marker.txt\n',
        encoding="utf-8",
    )
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
    guard = ManagedServiceMutationGuard(data_dir, process_command_reader=commands.get)
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
    assert deployment.code_root == str(code.resolve())
    assert deployment.runtime_root == str(runtime.resolve())
    assert len(deployment.git_head) == 40
    assert len(deployment.webui_artifact_sha256) == 64
    assert verify_deployment_binding(
        deployment,
        code_root=code,
        runtime_root=runtime,
    ) == []


def test_verify_detects_root_head_dirty_and_webui_artifact_drift(tmp_path: Path) -> None:
    import subprocess

    code, runtime = _git_deployment_fixture(tmp_path)
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)

    wrong_runtime = tmp_path / "wrong-runtime"
    wrong_runtime.mkdir()
    problems = verify_deployment_binding(
        deployment,
        code_root=code,
        runtime_root=wrong_runtime,
    )
    assert any("runtime_root mismatch" in item for item in problems)

    (code / "webui" / "dist" / "app.js").write_text("console.log('v2')\n", encoding="utf-8")
    problems = verify_deployment_binding(deployment, code_root=code, runtime_root=runtime)
    assert any("webui artifact mismatch" in item for item in problems)
    # Feishu-only restart intentionally does not depend on WebUI artifacts.
    assert verify_deployment_binding(
        deployment,
        code_root=code,
        runtime_root=runtime,
        verify_webui=False,
    ) == []

    (code / "pyproject.toml").write_text("[project]\nname='p0a'\nversion='dirty'\n", encoding="utf-8")
    problems = verify_deployment_binding(
        deployment,
        code_root=code,
        runtime_root=runtime,
        verify_webui=False,
    )
    assert "code_root tracked worktree is dirty" in problems
    subprocess.run(["git", "-C", str(code), "checkout", "--", "pyproject.toml"], check=True)

    (code / "next.txt").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(code), "add", "next.txt"], check=True)
    subprocess.run(["git", "-C", str(code), "commit", "-qm", "next"], check=True)
    problems = verify_deployment_binding(
        deployment,
        code_root=code,
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

    store = ManagedServiceDeploymentStore(tmp_path / "data")
    first = _deployment(tmp_path, generation=1)
    marker = Path(first.runtime_root) / "lifecycle-started"
    script = Path(first.code_root) / "scripts" / "restart_mirror.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'touch "$LFL_RESTART_RUNTIME_ROOT/lifecycle-started"\n'
        "sleep 0.8\n",
        encoding="utf-8",
    )
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
