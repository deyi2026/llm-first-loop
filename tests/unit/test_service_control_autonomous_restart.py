"""S4（简化包 2026-09-22 下午二）：LFL 自主重启闭环的三个机械不变量。

* S4a 物理重启 rc/输出不受调用方 stdio 生死影响：inline CLI（S3）把
  restart_mirror 的 stdout 继承给调用方管道——2026-09-22 15:12 gen66 事故
  （svc-8011bb79，rc=-13 SIGPIPE，回执未写、web 停后未起、屏障死窗）证明
  管道读端先死会把脚本杀死在第一次写输出上。不变量：脚本输出必须落
  per-action durable 日志，rc 必须是脚本自身退出状态。
* S4b 终态 owner 的屏障可被后续 restart 接管：§8.3 docstring 承诺
  "until an operator or a follow-up operation handles them"，但
  accept_restart 对屏障冲突一律拒绝，模型无自恢复路径。不变量：owner
  动作已终态（failed/succeeded）→ 新动作接管（留审计）；owner 非终态或
  未知 → 仍 fail-closed 拒绝。
* S4c 模型侧 publish：ServiceControlTool 增加 publish 动作，复用 CLI 的
  全部机械边界（干净 git 树 + webui 产物 hash + generation CAS），模型可
  自主完成 build→publish→restart→verify 闭环。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.service_control import (
    ManagedServiceDeploymentStore,
    run_action_worker,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool


def _git_fixture(tmp_path: Path, *, script_body: str | None = None) -> None:
    """Clean git repo with webui/dist and a restart_mirror.sh fixture."""
    dist = tmp_path / "webui" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html>fixture</html>\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    script = scripts / "restart_mirror.sh"
    script.write_text(script_body or "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@test.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )


def _publish_gen1(tmp_path: Path) -> sc.ManagedServiceDeployment:
    deployment = sc.build_deployment(
        code_root=str(tmp_path), runtime_root=str(tmp_path), generation=1
    )
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.compare_and_swap(deployment, expected_generation=0)
    return deployment


# ---------------------------------------------------------------------------
# S4a: durable stdio for the physical restart subprocess
# ---------------------------------------------------------------------------

_CHILD_RUN_WORKER = """
import sys
from pathlib import Path
from llm_loop.runtime.service_control import (
    ManagedServiceDeploymentStore,
    run_action_worker,
)
store = ManagedServiceDeploymentStore(sys.argv[1])
raise SystemExit(run_action_worker(store, sys.argv[2]) or 0)
"""


def test_physical_restart_survives_dead_caller_stdout_pipe(tmp_path: Path) -> None:
    """Incident repro: caller's stdout pipe dies before the script writes.

    The physical restart must complete (or fail) on its own terms: output
    lands in the per-action durable log and the recorded rc is the script's
    own exit status, never a pipe-signal artifact like -13.
    """
    _git_fixture(
        tmp_path,
        script_body="#!/usr/bin/env bash\nset -euo pipefail\necho attempt-output\nexit 3\n",
    )
    deployment = _publish_gen1(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    action = store.accept_restart(
        target="all", expected_generation=deployment.generation, requester_session_id=""
    )
    # Child process reproduces the inline CLI under a dead stdout pipe: the
    # parent closes the read end immediately, so any inherited write SIGPIPEs.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD_RUN_WORKER,
            str(tmp_path / "data"),
            action.action_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(sc.__file__).resolve().parents[2]),
        },
        cwd=str(tmp_path),
    )
    proc.stdout.close()  # type: ignore[union-attr]
    proc.stderr.close()  # type: ignore[union-attr]
    proc.wait(timeout=30)

    final = store.read_action(action.action_id)
    assert final is not None
    assert final.status == "failed", final.detail
    # The script exited 3; the recorded rc must be 3, not -13 (SIGPIPE).
    assert "rc=-13" not in final.detail, final.detail
    assert "rc=3" in final.detail, final.detail
    # Full output is durably recoverable per attempt, independent of caller stdio.
    log_path = tmp_path / "data" / "service-control-restart-logs" / f"{action.action_id}.log"
    assert log_path.is_file(), "per-action restart log missing"
    assert "attempt-output" in log_path.read_text(encoding="utf-8")


def test_restart_log_path_cited_in_failure_detail(tmp_path: Path) -> None:
    """Failure detail must point operators/models at the durable log."""
    _git_fixture(
        tmp_path,
        script_body="#!/usr/bin/env bash\nset -euo pipefail\necho boom\nexit 4\n",
    )
    deployment = _publish_gen1(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    action = store.accept_restart(
        target="all", expected_generation=deployment.generation, requester_session_id=""
    )
    rc = run_action_worker(store, action.action_id)
    assert rc != 0
    final = store.read_action(action.action_id)
    assert final is not None
    assert f"{action.action_id}.log" in (final.detail or "")


# ---------------------------------------------------------------------------
# S4b: barrier takeover by a follow-up restart action
# ---------------------------------------------------------------------------

def _fail_action_keep_barriers(
    store: ManagedServiceDeploymentStore, action_id: str
) -> None:
    """Reproduce the incident shape: running -> failed keeps barriers (§8.3)."""
    store.update_action(action_id, status="running", detail="")
    store.update_action(action_id, status="failed", detail="restart_mirror rc=-13")


def test_new_restart_adopts_barriers_of_terminal_failed_owner(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    deployment = _publish_gen1(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    first = store.accept_restart(
        target="all", expected_generation=deployment.generation, requester_session_id=""
    )
    _fail_action_keep_barriers(store, first.action_id)
    assert store.barriers.blocked("web") is not None  # kept fail-closed

    # Follow-up operation handles them (§8.3 docstring promise, made mechanical).
    second = store.accept_restart(
        target="all", expected_generation=deployment.generation, requester_session_id=""
    )

    for service in ("web", "feishu", "learning"):
        barrier = store.barriers.blocked(service)
        assert barrier is not None
        assert barrier.operation_id == second.action_id
    # Append-only adoption audit trail (previous owner must stay attributable).
    audit = tmp_path / "data" / "audit" / "service_barrier_adoptions.jsonl"
    assert audit.is_file()
    lines = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x]
    assert len(lines) == 3
    assert {line["previous_owner"] for line in lines} == {first.action_id}
    assert {line["operation_id"] for line in lines} == {second.action_id}


def test_new_restart_still_conflicts_with_non_terminal_owner(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    deployment = _publish_gen1(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    store.accept_restart(
        target="all", expected_generation=deployment.generation, requester_session_id=""
    )  # stays "accepted" (non-terminal): a live operation owns the barriers

    # Existing contract: barrier conflicts surface as DeploymentGenerationConflictError.
    with pytest.raises(sc.DeploymentGenerationConflictError):
        store.accept_restart(
            target="all",
            expected_generation=deployment.generation,
            requester_session_id="",
        )
    # Rejection leaves a durable failed acceptance record (auditability).
    actions = sorted(store.actions_dir.glob("*.json"))
    assert actions
    rejected = [
        sc.ServiceControlAction.from_dict(json.loads(p.read_text(encoding="utf-8")))
        for p in actions
    ]
    assert any(a.status == "failed" for a in rejected)


def test_new_restart_still_conflicts_with_unknown_owner(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    deployment = _publish_gen1(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    # Foreign/corrupt ownership stays operator-only (fail-closed).
    store.barriers.establish("web", operation_id="svc-nonexistent0000", reason="restart")
    with pytest.raises(sc.DeploymentGenerationConflictError):
        store.accept_restart(
            target="web",
            expected_generation=deployment.generation,
            requester_session_id="",
        )


# ---------------------------------------------------------------------------
# S4c: model-facing publish action
# ---------------------------------------------------------------------------

def _tool(store: ManagedServiceDeploymentStore) -> ServiceControlTool:
    return ServiceControlTool(
        store=store, worker_spawner=lambda action_id: None, session_id_getter=lambda: "sess"
    )


def test_tool_publish_advances_desired_generation(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = _tool(store)

    result = tool.execute(action="publish", code_root=str(tmp_path), expected_generation=0)
    assert result.status == "success", result.content
    body = json.loads(result.content)
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1
    assert deployment.code_root == str(tmp_path.resolve())
    assert body["published"]["generation"] == 1
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert deployment.git_head == head


def test_tool_publish_rejects_stale_expected_generation(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = _tool(store)
    assert tool.execute(action="publish", code_root=str(tmp_path), expected_generation=0).status == "success"

    result = tool.execute(action="publish", code_root=str(tmp_path), expected_generation=0)
    assert result.status == "failure", result.content
    assert "expected=0 current=1" in result.content


def test_tool_publish_rejects_dirty_worktree(tmp_path: Path) -> None:
    _git_fixture(tmp_path)
    (tmp_path / "webui" / "dist" / "index.html").write_text(
        "<html>drifted</html>\n", encoding="utf-8"
    )
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = _tool(store)

    result = tool.execute(action="publish", code_root=str(tmp_path), expected_generation=0)
    assert result.status == "failure", result.content
    assert "clean" in result.content
    assert store.read() is None
