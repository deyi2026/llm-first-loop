"""lifecycle_agency 分组4: update 单语义动作 + 缺省代次 + 实际生效身份（AC-11/12/13）.

覆盖 L12/L13/L14/L15：模型表达一次"更新 + 代码根"即可完成"固化期望部署 + 物理
生效"，无需自行编排 publish/restart 两步；缺条件时返回缺哪一项具体条件。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from llm_loop.runtime import service_control as sc
from llm_loop.runtime.service_control import (
    ManagedServiceDeploymentStore,
    build_deployment,
)
from llm_loop.tools.builtin.service_control import ServiceControlTool


def _git_fixture(tmp_path: Path, *, name: str = "git-code") -> tuple[Path, Path]:
    code = tmp_path / name
    runtime = tmp_path / f"{name}-runtime"
    code.mkdir()
    runtime.mkdir()
    subprocess.run(["git", "init", "-q", str(code)], check=True)
    subprocess.run(["git", "-C", str(code), "config", "user.email", "fixture@test"], check=True)
    subprocess.run(["git", "-C", str(code), "config", "user.name", "fixture"], check=True)
    (code / ".gitignore").write_text("webui/dist/\n", encoding="utf-8")
    (code / "pyproject.toml").write_text("[project]\nname='fx'\nversion='0'\n", encoding="utf-8")
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


def _git_head(code: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(code), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _store_with_initial_desired(tmp_path: Path, code: Path, runtime: Path) -> ManagedServiceDeploymentStore:
    store = ManagedServiceDeploymentStore(runtime / "data")
    store.compare_and_swap(
        build_deployment(code_root=code, runtime_root=runtime, generation=1),
        expected_generation=0,
    )
    return store


def _write_live_manifests(runtime: Path, head: str, services: tuple[str, ...]) -> None:
    runtime_dir = runtime / "data" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for service in services:
        (runtime_dir / f"runtime_manifest.{service}.json").write_text(
            json.dumps({"pid": 1, "git_head": head, "started_at": "2026-09-22T00:00:00+00:00"}),
            encoding="utf-8",
        )


def _tool(store: ManagedServiceDeploymentStore, spawned: list[str]) -> ServiceControlTool:
    return ServiceControlTool(
        store=store,
        worker_spawner=lambda action_id: spawned.append(action_id),
        session_id_getter=lambda: "session-update",
    )


def test_update_single_action_publishes_and_restarts(tmp_path: Path) -> None:
    """AC-13: 一次 update 完成固化期望部署 + 物理生效受理."""
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    spawned: list[str] = []
    result = _tool(store, spawned).execute(
        action="update", code_root=str(code), reason="上线 cache-hit 修复"
    )
    assert result.status.value == "success", result.content
    # 固化期望部署：generation +1，git_head/产物 hash 如实回报。
    desired = store.read()
    assert desired is not None and desired.generation == 2
    assert desired.git_head == _git_head(code)
    body = json.loads(result.content)
    assert body["updated"]["generation"] == 2
    assert body["updated"]["git_head"] == desired.git_head
    assert body["updated"]["webui_artifact_sha256"] == desired.webui_artifact_sha256
    # 物理生效已受理（异步 worker 已 spawn），action durable。
    assert len(spawned) == 1
    receipt = store.read_action(spawned[0])
    assert receipt is not None
    assert receipt.target == "all"  # code_root 路径不含服务名 → all
    assert receipt.deployment_generation == 2


def test_update_accepts_explicit_restart_target(tmp_path: Path) -> None:
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    spawned: list[str] = []
    result = _tool(store, spawned).execute(
        action="update", code_root=str(code), reason="只更新 web", restart_target="web"
    )
    assert result.status.value == "success", result.content
    assert store.read_action(spawned[0]).target == "web"


def test_update_derives_target_from_code_root_name(tmp_path: Path) -> None:
    code, runtime = _git_fixture(tmp_path, name="feishu-code")
    store = _store_with_initial_desired(tmp_path, code, runtime)
    spawned: list[str] = []
    result = _tool(store, spawned).execute(
        action="update", code_root=str(code), reason="按路径推导目标"
    )
    assert result.status.value == "success", result.content
    assert store.read_action(spawned[0]).target == "feishu"


def test_update_requires_code_root_and_reason(tmp_path: Path) -> None:
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    tool = _tool(store, [])
    missing_root = tool.execute(action="update", reason="x")
    assert missing_root.status.value == "failure"
    assert "code_root" in missing_root.content
    missing_reason = tool.execute(action="update", code_root=str(code))
    assert missing_reason.status.value == "failure"
    assert "reason" in missing_reason.content


def test_update_reports_artifact_missing_with_path(tmp_path: Path) -> None:
    """AC-13: 产物缺失是可修复状态 → 回报缺失清单，而非笼统拒绝."""
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    import shutil

    shutil.rmtree(code / "webui" / "dist")
    result = _tool(store, []).execute(
        action="update", code_root=str(code), reason="缺失产物"
    )
    assert result.status.value == "failure"
    assert "artifact_missing" in result.content
    assert "webui/dist" in result.content
    assert store.read().generation == 1  # 未推进 desired


def test_update_generation_conflict_returns_current_value(tmp_path: Path) -> None:
    """AC-11: 代次冲突时返回当前值，可直接重试."""
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    result = _tool(store, []).execute(
        action="update", code_root=str(code), reason="并发冲突", expected_generation=99
    )
    assert result.status.value == "failure"
    assert "generation_conflict" in result.content
    assert "current=1" in result.content
    assert store.read().generation == 1


def test_update_reports_live_identity_unchanged(tmp_path: Path) -> None:
    """AC-12: 目标 live 身份已是本次 desired → 明确提示版本不会改变."""
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    _write_live_manifests(runtime, _git_head(code), ("web", "feishu", "learning"))
    spawned: list[str] = []
    result = _tool(store, spawned).execute(
        action="update", code_root=str(code), reason="同版本重发"
    )
    assert result.status.value == "success", result.content
    body = json.loads(result.content)
    assert "live_identity_hint" in body
    assert "不会改变其运行版本" in body["live_identity_hint"]


def test_cli_publish_defaults_to_current_generation(tmp_path: Path) -> None:
    """L14/AC-11: CLI publish 的 --expected-generation 缺省自动取当前代."""
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    rc = sc.main(
        ["publish", "--code-root", str(code), "--runtime-root", str(runtime)]
    )
    assert rc == 0
    desired = store.read()
    assert desired is not None and desired.generation == 2


def test_cli_publish_conflict_returns_current_value(
    tmp_path: Path, capsys
) -> None:
    code, runtime = _git_fixture(tmp_path)
    store = _store_with_initial_desired(tmp_path, code, runtime)
    rc = sc.main(
        [
            "publish",
            "--code-root",
            str(code),
            "--runtime-root",
            str(runtime),
            "--expected-generation",
            "99",
        ]
    )
    assert rc == 9
    err = capsys.readouterr().err
    assert "generation_conflict" in err
    assert '"current": 1' in err
    assert store.read().generation == 1