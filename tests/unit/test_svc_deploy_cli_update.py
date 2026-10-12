"""svc_deploy N2（tasks 8.2 / T2）：CLI 一键部署入口 `update`（别名 `deploy`）。

覆盖：
- AC-8  单次调用后 desired generation 恰好 +1，且存在来源可区分的 restart 动作
- AC-9  脏 tracked 树 → 结构化拒绝；git stash list / HEAD / git status 前后不变
- AC-10 并发推进 desired 后调用一键 → generation 冲突且未执行物理重启
- AC-11 publish 成功而受理失败 → 回执含已发布 generation/git_head 与继续路径
- AC-12 一键通道不跳过等待与屏障（动作链含 waiting 阶段，屏障托管）
- AC-13 干净树判定机械可验：仅 ignored 产物差异不判脏；tracked 改动判脏
- AC-15 CLI `update` 与工具面 action=update 同语义、`deploy` 为显式别名、共用单点判据
- INV-1 CAS 不减弱（无无条件推进 desired 的入口）
- INV-4 脏树零自动修复
- INV-13 一键不绕防护（等待阶段不执行脚本、不绕屏障）

本文件为纯新增；不修改任何既有测试文件。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.admission_barrier import AdmissionBarrierRegistry
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore

_RESTART_SCRIPT = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    'printf \'%s\\n\' "${LFL_RESTART_ACTION_ID:-}" > "$LFL_RESTART_RUNTIME_ROOT/executed_action_id.txt"\n'
    'mkdir -p "$LFL_RESTART_RUNTIME_ROOT/data/runtime"\n'
    'head=$(git -C "$LFL_RESTART_CODE_ROOT" rev-parse HEAD)\n'
    'started=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\n'
    'svcs="${1:-all}"\n'
    'if [ "$svcs" = "all" ]; then svcs="web feishu learning"; fi\n'
    "for svc in $svcs; do\n"
    '  printf \'{"pid": 1, "git_head": "%s", "started_at": "%s"}\\n\' "$head" "$started"'
    ' > "$LFL_RESTART_RUNTIME_ROOT/data/runtime/runtime_manifest.$svc.json"\n'
    "done\n"
)


@pytest.fixture()
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_REQUESTER_EXIT_TIMEOUT_S", 0.3)
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(sc, "_STALE_WAITING_MARGIN_S", 0.0)
    monkeypatch.setattr(sc, "_VERIFY_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_VERIFY_TIMEOUT_S", 0.3)


def _make_repo(root: Path) -> Path:
    """真实 git worktree + webui/dist（ignored）+ restart_mirror.sh 夹具。"""
    (root / "webui" / "dist").mkdir(parents=True, exist_ok=True)
    (root / "webui" / "dist" / "index.html").write_text("<html>v1</html>\n", encoding="utf-8")
    (root / ".gitignore").write_text("webui/dist/\ndata/\n", encoding="utf-8")
    (root / "app.py").write_text("print('v1')\n", encoding="utf-8")
    script = root / "scripts" / "restart_mirror.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_RESTART_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "svc@test.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "svc-test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def _git_state(root: Path) -> tuple[str, str, str]:
    def _run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return _run("stash", "list"), _run("rev-parse", "HEAD"), _run(
        "status", "--porcelain", "--untracked-files=no"
    )


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _actions(store: ManagedServiceDeploymentStore) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(store.actions_dir.glob("*.json"))
    ]


def _update_argv(
    root: Path,
    *,
    subcommand: str = "update",
    extra: list[str] | None = None,
) -> list[str]:
    argv = [
        subcommand,
        "--code-root",
        str(root),
        "--runtime-root",
        str(root),
        "--data-dir",
        str(root / "data"),
        # GOAL-20261008-f143e051：CLI 默认 detach worker；本文件全部用例
        # 断言"CLI 返回时已终态"的内联端到端语义 → 显式 --wait。
        "--wait",
    ]
    return argv + list(extra or [])


# --------------------------------------------------------------------------
# AC-8 / AC-12 / AC-15 / INV-13：一键链路端到端
# --------------------------------------------------------------------------


def test_cli_update_publishes_and_restarts_in_a_single_audited_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fast_waits: None,
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    data = code / "data"
    store = ManagedServiceDeploymentStore(data)
    assert store.read() is None

    observed: list[str] = []
    original_mark = sc._mark_action

    def _spy_mark(store_, action, *, status, **kwargs):  # type: ignore[no-untyped-def]
        observed.append(status)
        return original_mark(store_, action, status=status, **kwargs)

    monkeypatch.setattr(sc, "_mark_action", _spy_mark)

    rc = sc.main(_update_argv(code))
    assert rc == 0

    accepted, final = _json_lines(capsys.readouterr().out)
    assert accepted["ok"] is True
    assert accepted["origin"] == "update"
    assert accepted["generation"] == 1
    assert accepted["target"] == "feishu"  # 缺省目标由 code_root 路径名推导

    # AC-8：desired generation 恰好 +1（0 → 1），且动作来源可区分。
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1
    records = _actions(store)
    assert len(records) == 1
    assert records[0]["origin"] == "update"
    assert records[0]["status"] == "succeeded"
    assert records[0]["deployment_generation"] == 1

    # AC-12 / INV-13：动作链确实经过等待阶段再进入物理执行，未被绕过。
    assert "waiting_for_idle" in observed
    assert "running" in observed
    assert observed.index("waiting_for_idle") < observed.index("running")

    # 屏障托管：终态 succeeded 后释放该服务的准入屏障。
    barrier = AdmissionBarrierRegistry(data)
    assert barrier.blocked("feishu") is None

    # 控制面注入的 action_id 与回执一致（受控重启链路，非直连脚本）。
    assert (
        (code / "executed_action_id.txt").read_text(encoding="utf-8").strip()
        == accepted["action_id"]
    )

    # 成功路径不产生 next_step。
    assert final["ok"] is True
    assert final["status"] == "succeeded"
    assert final["next_step"] == []


def test_cli_deploy_alias_uses_the_same_update_branch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    """AC-15：`deploy` 是 `update` 的显式别名，走同一分支与同一套机械边界。"""
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")

    rc = sc.main(_update_argv(code, subcommand="deploy"))
    assert rc == 0

    accepted, final = _json_lines(capsys.readouterr().out)
    assert accepted["origin"] == "update"
    assert accepted["generation"] == 1
    assert final["status"] == "succeeded"
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1
    assert [record["origin"] for record in _actions(store)] == ["update"]


def test_cli_update_advances_generation_by_exactly_one_per_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    """AC-8：连调两次（第二次缺省 expected-generation）→ 每次恰好 +1。"""
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")

    assert sc.main(_update_argv(code)) == 0
    capsys.readouterr()
    first = store.read()
    assert first is not None and first.generation == 1

    assert sc.main(_update_argv(code)) == 0
    capsys.readouterr()
    second = store.read()
    assert second is not None and second.generation == 2

    records = _actions(store)
    assert len(records) == 2
    assert sorted(record["deployment_generation"] for record in records) == [1, 2]
    assert {record["origin"] for record in records} == {"update"}


# --------------------------------------------------------------------------
# AC-9 / AC-13 / INV-4：脏树拒绝与零自动修复
# --------------------------------------------------------------------------


def test_cli_update_rejects_dirty_tracked_tree_without_repairing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")

    (code / "app.py").write_text("print('dirty')\n", encoding="utf-8")
    before = _git_state(code)
    assert before[2], "夹具必须先把 tracked 树改脏"

    rc = sc.main(_update_argv(code))
    assert rc == 10
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert payload["error"] == "dirty_worktree"
    # AC-13：判定依据（既有 build_deployment 的原文）写入回执。
    assert "tracked worktree must be clean" in payload["detail"]
    assert payload["next_step"][0]["problem_kind"] == "tracked_worktree_dirty"
    assert payload["next_step"][0]["exit_action"] == ""

    # INV-4：不 stash / 不 commit / 不 checkout —— git 状态逐字节不变。
    assert _git_state(code) == before
    # 未出 desired：拒绝发生在任何写路径之前。
    assert store.read() is None
    assert not (code / "executed_action_id.txt").exists()


def test_cli_update_allows_ignored_artifact_change_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    """AC-13：仅 ignored 产物（webui/dist）差异不判脏；tracked 差异才判脏。"""
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")

    (code / "webui" / "dist" / "index.html").write_text("<html>v2</html>\n", encoding="utf-8")
    assert _git_state(code)[2] == ""

    rc = sc.main(_update_argv(code))
    assert rc == 0
    accepted, final = _json_lines(capsys.readouterr().out)
    assert accepted["generation"] == 1
    assert final["status"] == "succeeded"
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1


def test_cli_update_reports_missing_artifact_before_publishing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    """AC-9 同族：产物缺失是模型可修复状态 → 结构化原因 + 同源下一步。"""
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")
    shutil.rmtree(code / "webui" / "dist")

    rc = sc.main(_update_argv(code))
    assert rc == 10
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert payload["error"] == "artifact_missing"
    assert payload["missing"] and payload["missing"][0].endswith("webui/dist")
    assert payload["next_step"][0]["problem_kind"] == "webui_artifact_unavailable"
    assert store.read() is None
    assert not (code / "executed_action_id.txt").exists()


def test_cli_update_treats_empty_artifact_dir_as_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    """AC-13：存在但为空的产物目录同样判缺失（机械可观测的判定依据）。"""
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")
    shutil.rmtree(code / "webui" / "dist")
    (code / "webui" / "dist").mkdir()

    rc = sc.main(_update_argv(code))
    assert rc == 10
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["error"] == "artifact_missing"
    assert payload["missing"] and payload["missing"][0].endswith("webui/dist")
    assert store.read() is None


# --------------------------------------------------------------------------
# AC-10 / INV-1：CAS 冲突短路
# --------------------------------------------------------------------------


def test_cli_update_generation_conflict_short_circuits_before_any_restart(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    store = ManagedServiceDeploymentStore(code / "data")
    existing = sc.build_deployment(code_root=code, runtime_root=code, generation=1)
    store.compare_and_swap(existing, expected_generation=0)

    rc = sc.main(_update_argv(code, extra=["--expected-generation", "0"]))
    assert rc == 9
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert payload["error"] == "generation_conflict"
    assert payload["current"] == 1
    assert payload["next_step"][0]["exit_action"] == "publish"

    # INV-1：无无条件推进 desired 的入口——冲突时 desired 原样。
    current = store.read()
    assert current is not None
    assert current.generation == 1
    assert current.deployment_id == existing.deployment_id
    # AC-10：未执行物理重启（脚本零副作用标记）。
    assert not (code / "executed_action_id.txt").exists()
    assert _actions(store) == []


# --------------------------------------------------------------------------
# AC-11：publish 成功而受理失败 → partial 如实回报
# --------------------------------------------------------------------------


def test_cli_update_partial_reports_published_half_and_continuation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fast_waits: None
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    data = code / "data"
    store = ManagedServiceDeploymentStore(data)
    # 预先占用 feishu 屏障，使 publish 之后的 accept_restart 必然冲突。
    AdmissionBarrierRegistry(data).establish(
        "feishu", operation_id="svc-foreign-owner", reason="restart"
    )

    rc = sc.main(_update_argv(code, extra=["--target", "feishu"]))
    assert rc == 8
    payload = _json_lines(capsys.readouterr().err)[-1]
    assert payload["ok"] is False
    assert "barrier conflict" in payload["error"]
    # AC-11：如实回报「已发布的一半」。
    assert payload["generation"] == 1
    assert len(payload["git_head"]) == 40
    assert payload["next_step"][0]["exit_action"] == "publish"

    published = store.read()
    assert published is not None
    assert published.generation == 1
    assert published.git_head == payload["git_head"]
    # 物理重启未发生（受理失败在任何 lease 内执行之前）。
    assert not (code / "executed_action_id.txt").exists()


# --------------------------------------------------------------------------
# AC-12 / INV-13：等待与屏障不可绕过
# --------------------------------------------------------------------------


def test_cli_update_waits_for_idle_and_never_runs_script_when_target_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fast_waits: None,
) -> None:
    code = _make_repo(tmp_path / "feishu-code")
    data = code / "data"
    store = ManagedServiceDeploymentStore(data)
    # 飞书桥有在飞消息 → 目标明确 busy。
    (data).mkdir(parents=True, exist_ok=True)
    (data / "feishu_heartbeat.json").write_text(
        json.dumps({"processing_msg_id": "msg-1", "queue_depth": 1}), encoding="utf-8"
    )
    monkeypatch.setattr(sc, "_IDLE_POLL_S", 0.02)
    monkeypatch.setattr(sc, "_IDLE_TIMEOUT_S", 0.1)

    rc = sc.main(_update_argv(code, extra=["--target", "feishu"]))
    assert rc == 1

    accepted, final = _json_lines(capsys.readouterr().out)
    assert accepted["ok"] is True
    assert final["ok"] is False
    assert final["status"] == "failed"
    assert "target still busy" in final["detail"]

    # INV-13：等待超时不等于放行——脚本从未执行（零物理副作用）。
    assert not (code / "executed_action_id.txt").exists()
    # waiting → failed 证明物理执行未开始，按既有语义释放本目标屏障。
    assert AdmissionBarrierRegistry(data).blocked("feishu") is None
    # 但 desired 已推进（publish 是受理之前的一半，如实保留）。
    deployment = store.read()
    assert deployment is not None
    assert deployment.generation == 1