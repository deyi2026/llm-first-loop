"""修1-修6: restart_mirror.sh 加固静态断言.

背景（EXPERIENCE 2026-09-09 假 armed 回执事故——stdout 回执随宿主死亡）:
- 修1 RESTART_WAIT_IDLE 长任务保护移植到位（web/feishu/all 三分支均 precheck）
- 修2 all 分支失败补偿：web 失败不短路吞掉 feishu 恢复
- 修3 可移植进程脱离（_spawn_detached: python setsid+execvp），服务启动不再裸 nohup&
- 修4 回执落盘（_write_receipt → data/restart-receipt.{json,log}）
- 修5 stop 判定源：web=端口∪argv 且等 PID 退出；feishu=心跳 pid（新鲜度门）∪argv
"""
import os
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restart_mirror.sh"


def _src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_bash_syntax_and_shellcheck_clean():
    r = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_wait_idle_precheck_on_all_restart_branches():
    src = _src()
    assert "RESTART_WAIT_IDLE" in src
    case_body = src.split("\ncase ", 1)[1]
    for branch in ("web)", "feishu)", "all)"):
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert "_restart_precheck" in body, f"{branch} 分支未接 _restart_precheck"
    # Web-capable branches add artifact fail-fast before the existing long-task precheck.
    for branch in ("web)", "all)"):
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert body.index("_webui_artifact_preflight") < body.index("_restart_precheck")


def test_restart_precheck_guards_web_whole_run_leases_not_only_feishu_heartbeat():
    src = _src()
    assert "_web_run_busy()" in src
    run_body = src.split("_web_run_busy()", 1)[1].split("\n}", 1)[0]
    assert "active_run_locks" in run_body
    assert '"$RUNTIME_ROOT/data/sessions"' in run_body

    busy_body = src.split("_restart_busy()", 1)[1].split("\n}", 1)[0]
    assert '[[ "$target" == "web" || "$target" == "all" ]]' in busy_body
    assert "_web_run_busy" in busy_body

    precheck = src.split("_restart_precheck()", 1)[1].split("\n}", 1)[0]
    assert "RESTART_FORCE_ACTIVE_RUNS" in precheck
    assert "Web active run fail-closed" in precheck
    assert "_web_run_recovery_ready" in precheck
    assert "缺少 open llm.partial_checkpoint" in precheck
    assert '[[ "$target" == "web" || "$target" == "all" ]]' in precheck


def test_emergency_active_run_restart_requires_durable_open_checkpoint():
    src = _src()
    assert "_web_run_recovery_ready()" in src
    body = src.split("_web_run_recovery_ready()", 1)[1].split("\n}", 1)[0]
    assert "active_run_locks" in body
    assert "EventStore" in body
    assert 'event.type == "run.end"' in body
    assert 'event.type == "llm.partial_checkpoint"' in body
    assert "missing-open-checkpoint" in body


def test_restart_branches_pass_target_to_activity_precheck():
    src = _src()
    case_body = src.split("\ncase ", 1)[1]
    expected = {
        "web)": "_restart_precheck web",
        "feishu)": "_restart_precheck feishu",
        "all)": "_restart_precheck all",
    }
    for branch, token in expected.items():
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert token in body
        assert "active_run_precheck_failed" in body


def test_stop_source_web_port_first_and_wait_pid_exit():
    body = _src().split("_stop_web()", 1)[1].split("\n}", 1)[0]
    assert "_port_pid" in body          # 端口判定（权威锚点）
    assert "_mirror_web_pids" in body   # ∪ argv 兜底
    assert "_pid_alive" in body         # 等 PID 本身退出，不等端口腾空
    assert "拒绝启动新进程" in body     # 停失败禁止启动（防双进程）


def test_stop_source_feishu_heartbeat_pid_with_freshness_gate():
    src = _src()
    body = src.split("_feishu_pids()", 1)[1].split("\n}", 1)[0]
    assert "feishu_heartbeat.json" in body
    assert re.search(r"180", body)      # 心跳新鲜度门（防 PID 复用误杀）
    assert "xargs -r kill" not in src   # 停止路径不再用裸 pgrep|xargs kill


def test_all_branch_failure_compensation():
    src = _src()
    body = src.split("  all)", 1)[1].split("status)", 1)[0]
    assert "_start_web" in body and "_start_feishu" in body
    # web 失败仍恢复 feishu：两个 start 各自独立条件触发，无 && 短路链
    assert "_start_web && _start_feishu" not in src
    assert re.search(r"_stop_web[^\n]*&&[^\n]*_web_stopped=1", body)
    assert re.search(r"_start_feishu \|\| _rc=1", body)


def test_spawn_detached_replaces_bare_nohup():
    src = _src()
    assert "_spawn_detached" in src
    assert "os.setsid()" in src         # macOS 无 setsid(1) 的可移植替代
    assert not re.search(r'nohup "\$VENV_PY" -m', src)  # 禁新的裸 nohup 启动行


def test_receipt_persisted_to_disk_on_every_branch():
    src = _src()
    assert "_write_receipt" in src
    assert "restart-receipt.json" in src and "restart-receipt.log" in src
    for branch in ("web)", "feishu)", "all)"):
        m = re.search(re.escape(branch) + r"(?:(?!status).)*_write_receipt", src, re.S)
        assert m, f"{branch} 分支缺 _write_receipt"


def test_restart_port_frozen_for_post_unset_use():
    src = _src()
    # _start_* 会 unset WEB_PORT（set -u 陷阱）——启动后引用端口必须用冻结变量
    assert 'RESTART_PORT="$WEB_PORT"' in src
    body = src.split("\ncase ", 1)[1]
    assert 'unset WEB_PORT' in src
    assert '"$WEB_PORT"' not in body  # case 分支不得再引用可被 unset 的 WEB_PORT


def test_restart_runs_knowledge_preflight_before_any_stop():
    src = _src()
    assert "_knowledge_preflight()" in src
    assert "llm_loop.runtime.knowledge_health --preflight --initialize-baseline" in src
    assert "env -u DATA_DIR -u LFL_DATA_DIR -u EXPERIENCES_DIR -u METHODS_DIR" in src
    case_body = src.split("\ncase ", 1)[1]
    for branch, stop_token in (
        ("web)", '_stop_web "$RESTART_PORT"'),
        ("feishu)", "_feishu_stop"),
        ("all)", '_stop_web "$RESTART_PORT"'),
    ):
        body = case_body.split(branch, 1)[1]
        body = body.split(";;", 1)[0]
        assert "_knowledge_preflight" in body
        assert body.index("_knowledge_preflight") < body.index(stop_token)


# ── Gate E dual-root official canary support ──

def test_dual_root_contract_keeps_runtime_state_and_code_identity_separate():
    src = _src()
    assert 'SCRIPT_ROOT=' in src
    assert 'LFL_RESTART_RUNTIME_ROOT' in src
    assert 'LFL_RESTART_CODE_ROOT' in src
    assert 'RUNTIME_ROOT=' in src
    assert 'CODE_ROOT=' in src
    assert 'VENV_PY="$RUNTIME_ROOT/.venv/bin/python"' in src
    assert 'cd "$RUNTIME_ROOT"' in src
    assert 'PYTHONPATH="$CODE_ROOT/src"' in src
    assert 'LFL_WORKSPACE_ROOT="$CODE_ROOT"' in src
    assert 'LFL_RUNTIME_ROOT="$RUNTIME_ROOT"' in src


def test_dual_root_override_fails_closed_on_dirty_or_foreign_code_root():
    src = _src()
    assert '_validate_restart_roots' in src
    body = src.split('_validate_restart_roots()', 1)[1].split('\n}', 1)[0]
    assert 'git-common-dir' in body
    assert 'status --porcelain' in body
    assert 'CODE_ROOT' in body and 'RUNTIME_ROOT' in body
    assert '拒绝' in body


def test_restart_receipt_uses_code_root_and_records_exact_sha():
    src = _src()
    body = src.split('_write_receipt()', 1)[1].split('\n}', 1)[0]
    assert 'git -C "$CODE_ROOT" rev-parse --short HEAD' in body
    assert 'git -C "$CODE_ROOT" rev-parse HEAD' in body
    assert 'git_head_full' in body



def _init_dual_root_fixture(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    code_root = tmp_path / "code"
    runtime_root.mkdir()
    subprocess.run(["git", "init", "-q", str(runtime_root)], check=True)
    subprocess.run(["git", "-C", str(runtime_root), "config", "user.email", "dual-root@test"], check=True)
    subprocess.run(["git", "-C", str(runtime_root), "config", "user.name", "dual-root-test"], check=True)
    (runtime_root / "pyproject.toml").write_text("[project]\nname='dual-root-fixture'\nversion='0'\n", encoding="utf-8")
    (runtime_root / "src").mkdir()
    # The git fixture only needs a tracked source entry; status must remain clean.
    os.symlink(str(_SCRIPT.parents[1] / "src" / "llm_loop"), runtime_root / "src" / "llm_loop")
    subprocess.run(["git", "-C", str(runtime_root), "add", "pyproject.toml", "src/llm_loop"], check=True)
    subprocess.run(["git", "-C", str(runtime_root), "commit", "-qm", "fixture"], check=True)
    subprocess.run(["git", "-C", str(runtime_root), "worktree", "add", "-q", "--detach", str(code_root), "HEAD"], check=True)

    (runtime_root / ".venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, runtime_root / ".venv" / "bin" / "python")
    (runtime_root / ".env").write_text("WEB_PORT=48903\nWEB_HOST=127.0.0.1\n", encoding="utf-8")
    (runtime_root / "data").mkdir()
    return runtime_root, code_root


def _run_dual_status(runtime_root: Path, code_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LFL_RESTART_RUNTIME_ROOT"] = str(runtime_root)
    env["LFL_RESTART_CODE_ROOT"] = str(code_root)
    env["LFL_RESTART_CODE_ROOT_CONFIRMED"] = "1"  # T0-A3 契约: 自动化显式不同目录 CODE_ROOT 须确认
    env["LFL_RESTART_RUNTIME_ROOT_CONFIRMED"] = "1"  # R4: RUNTIME_ROOT 同契约
    return subprocess.run(
        ["bash", str(_SCRIPT), "status"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_dual_root_status_accepts_clean_same_repo_and_rejects_dirty_or_foreign(tmp_path):
    runtime_root, code_root = _init_dual_root_fixture(tmp_path)

    ok = _run_dual_status(runtime_root, code_root)
    assert ok.returncode == 0, ok.stderr + ok.stdout

    (code_root / "dirty.txt").write_text("dirty", encoding="utf-8")
    dirty = _run_dual_status(runtime_root, code_root)
    assert dirty.returncode == 2
    assert "CODE_ROOT 必须 clean" in dirty.stderr
    (code_root / "dirty.txt").unlink()

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    subprocess.run(["git", "init", "-q", str(foreign)], check=True)
    subprocess.run(["git", "-C", str(foreign), "config", "user.email", "foreign@test"], check=True)
    subprocess.run(["git", "-C", str(foreign), "config", "user.name", "foreign-test"], check=True)
    (foreign / "src").mkdir()
    os.symlink(str(_SCRIPT.parents[1] / "src" / "llm_loop"), foreign / "src" / "llm_loop")
    subprocess.run(["git", "-C", str(foreign), "add", "src/llm_loop"], check=True)
    subprocess.run(["git", "-C", str(foreign), "commit", "-qm", "foreign"], check=True)
    mismatch = _run_dual_status(runtime_root, foreign)
    assert mismatch.returncode == 2
    assert "git-common-dir 不一致" in mismatch.stderr

# ── 2026-09-16 Web V2 artifact/readiness hardening ──

def test_webui_artifact_preflight_runs_before_any_web_stop():
    """Missing ignored webui/dist must fail before a healthy Web is stopped."""
    src = _src()
    assert "_webui_artifact_preflight()" in src
    case_body = src.split("\ncase ", 1)[1]
    for branch in ("web)", "all)"):
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert "_webui_artifact_preflight" in body
        assert body.index("_webui_artifact_preflight") < body.index('_stop_web "$RESTART_PORT"')


def test_webui_artifact_preflight_checks_index_and_referenced_assets():
    src = _src()
    body = src.split("_webui_artifact_preflight()", 1)[1].split("\n}", 1)[0]
    assert "UI_V2_DIR" in body
    assert '${UI_V2_DIR:-$CODE_ROOT/webui/dist}' in body
    assert "index.html" in body
    assert "missing Web V2 asset" in body
    assert "npm run build" in body


def test_web_readiness_requires_ui_v2_not_only_auth_status():
    src = _src()
    body = src.split("_start_web()", 1)[1].split("\n}", 1)[0]
    assert "/auth/status" in body
    assert "/ui/v2/" in body
    assert "ui_code" in body
    assert "web backend ready but Web V2 unavailable" in src


def test_missing_webui_dist_fails_before_restart_side_effects(tmp_path):
    runtime_root, code_root = _init_dual_root_fixture(tmp_path)
    env = os.environ.copy()
    env["LFL_RESTART_RUNTIME_ROOT"] = str(runtime_root)
    env["LFL_RESTART_CODE_ROOT"] = str(code_root)
    env["LFL_RESTART_CODE_ROOT_CONFIRMED"] = "1"  # T0-A3 契约: 自动化显式不同目录 CODE_ROOT 须确认
    env["LFL_RESTART_RUNTIME_ROOT_CONFIRMED"] = "1"  # R4: RUNTIME_ROOT 同契约
    result = subprocess.run(
        ["bash", str(_SCRIPT), "web"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "Web V2 artifact preflight failed" in result.stdout
    receipt = runtime_root / "data" / "restart-receipt.json"
    assert receipt.is_file()
    import json
    row = json.loads(receipt.read_text(encoding="utf-8"))
    assert row["action"] == "web"
    assert row["rc"] == 1
    assert row["detail"] == "webui_artifact_preflight_failed"


def test_partial_webui_dist_with_missing_hashed_asset_fails_preflight(tmp_path):
    runtime_root, code_root = _init_dual_root_fixture(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/ui/v2/assets/index-missing.js"></script>',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["LFL_RESTART_RUNTIME_ROOT"] = str(runtime_root)
    env["LFL_RESTART_CODE_ROOT"] = str(code_root)
    env["LFL_RESTART_CODE_ROOT_CONFIRMED"] = "1"  # T0-A3 契约: 自动化显式不同目录 CODE_ROOT 须确认
    env["LFL_RESTART_RUNTIME_ROOT_CONFIRMED"] = "1"  # R4: RUNTIME_ROOT 同契约
    env["UI_V2_DIR"] = str(dist)
    result = subprocess.run(
        ["bash", str(_SCRIPT), "web"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "missing Web V2 asset: assets/index-missing.js" in result.stderr
    assert "index 引用的静态资源缺失" in result.stdout

# ── 2026-09-16 P0-A shared service lifecycle authority ──

def test_service_control_binding_preflight_runs_before_any_stop():
    src = _src()
    assert "_service_control_preflight()" in src
    assert "llm_loop.runtime.service_control verify" in src
    case_body = src.split("\ncase ", 1)[1]
    for branch, stop_token in (
        ("web)", '_stop_web "$RESTART_PORT"'),
        ("feishu)", "_feishu_stop"),
        ("all)", '_stop_web "$RESTART_PORT"'),
    ):
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert "_service_control_preflight" in body
        assert body.index("_service_control_preflight") < body.index(stop_token)
    feishu_body = case_body.split("feishu)", 1)[1].split(";;", 1)[0]
    assert "_service_control_preflight feishu" in feishu_body
    assert "--skip-webui" in src


def test_status_remains_readonly_without_desired_deployment_preflight():
    src = _src()
    case_body = src.split("\ncase ", 1)[1]
    status_body = case_body.split("status)", 1)[1].split(";;", 1)[0]
    assert "_service_control_preflight" not in status_body
    assert "_status" in status_body


def test_missing_desired_deployment_fails_before_restart_after_artifact_preflight(tmp_path):
    runtime_root, code_root = _init_dual_root_fixture(tmp_path)
    dist = tmp_path / "verified-dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ok</title>", encoding="utf-8")
    env = os.environ.copy()
    env["LFL_RESTART_RUNTIME_ROOT"] = str(runtime_root)
    env["LFL_RESTART_CODE_ROOT"] = str(code_root)
    env["LFL_RESTART_CODE_ROOT_CONFIRMED"] = "1"  # T0-A3 契约: 自动化显式不同目录 CODE_ROOT 须确认
    env["LFL_RESTART_RUNTIME_ROOT_CONFIRMED"] = "1"  # R4: RUNTIME_ROOT 同契约
    env["UI_V2_DIR"] = str(dist)
    result = subprocess.run(
        ["bash", str(_SCRIPT), "web"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "service-control desired deployment binding FAILED" in result.stdout
    import json
    receipt = json.loads((runtime_root / "data" / "restart-receipt.json").read_text(encoding="utf-8"))
    assert receipt["detail"] == "service_control_binding_failed"
