"""Mirror restart script must probe the public readiness endpoint under browser auth."""

from pathlib import Path


def test_mirror_web_readiness_uses_public_auth_status() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/restart_mirror.sh").read_text(encoding="utf-8")
    assert '"http://$check_host:$check_port/auth/status"' in script
    assert '"http://$WEB_HOST:$WEB_PORT/auth/status"' in script
    assert '"http://$check_host:$check_port/health"' not in script
    assert '"http://$WEB_HOST:$WEB_PORT/health"' not in script


def test_mirror_restart_waits_for_process_exit_not_only_port_release() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/restart_mirror.sh").read_text(encoding="utf-8")
    assert "_mirror_web_pids()" in script
    assert 'kill -0 "$1"' in script
    assert "旧 PID 全部退出" in script
    assert "拒绝启动新进程" in script
    # 51e4d9a 五项加固后（细化断言见 tests/scripts/test_restart_mirror_hardening.py）：
    # case 块改用冻结的 RESTART_PORT（_start_* 会 unset WEB_PORT，set -u 陷阱），
    # web 分支仍必须先停后启，且停止失败必须跳过启动（防双进程）。
    assert 'web)     _webui_artifact_preflight' in script
    assert '_stop_web "$RESTART_PORT"' in script
    assert "web 停止失败，跳过启动（防双进程）" in script
    assert 'all)     _webui_artifact_preflight' in script
    case_body = script.split("\ncase ", 1)[1]
    for branch in ("web)", "all)"):
        body = case_body.split(branch, 1)[1].split(";;", 1)[0]
        assert body.index("_webui_artifact_preflight") < body.index("_restart_precheck") < body.index('_stop_web "$RESTART_PORT"')
    # Regression: port release alone must never be the stop-complete condition.
    stop_block = script.split("_stop_web() {", 1)[1].split("_start_web() {", 1)[0]
    assert "_pid_alive" in stop_block
    assert "kill -KILL" in stop_block


def test_mirror_direct_path_is_marked_non_authoritative() -> None:
    """L16/tasks 8.1: 直连脚本回执显式非权威且指向 service_control 权威入口."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/restart_mirror.sh").read_text(encoding="utf-8")
    assert "direct-non-authoritative" in script
    assert 'RESTART_AUTHORITY="service_control"' in script
    assert "LFL_RESTART_ACTION_ID" in script
    assert "service_control(action=restart|update)" in script
    # 只标注、不新增拦截门禁：authority 分支内不得出现硬拒 exit。
    assert len(script.split('if [[ "$RESTART_AUTHORITY" != "service_control" ]]', 1)) == 2
    branch = script.split('if [[ "$RESTART_AUTHORITY" != "service_control" ]]', 1)[1]
    assert "exit" not in branch.split("esac", 1)[0]


def test_mirror_dsh_env_is_independent_of_caller_home_and_path() -> None:
    """Operator sandboxes must not become the long-lived LFL service identity."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/restart_mirror.sh").read_text(encoding="utf-8")
    block = script.split("_prep_dsh_env() {", 1)[1].split("\n}\n", 1)[0]

    assert "pwd.getpwuid(os.getuid()).pw_dir" in block
    assert 'export HOME="$account_home"' in block
    assert "DARWIN_USER_TEMP_DIR" in block
    assert 'export TMPDIR="$account_tmp"' in block
    assert 'dsh_bin_dir="$account_home/.local/dsh/bin"' in block
    assert 'export PATH="$dsh_bin_dir:$PATH"' in block
    assert 'export DSH_HOME="$MIRROR_DIR/data/dsh-home"' in block

    # Regression for 2026-09-11: the function used to export DSH_HOME and then
    # immediately unset it, leaving a service launched from MCP Console pointed
    # at the temporary sandbox HOME instead of the mirror DSH home.
    for line in block.splitlines():
        if line.strip().startswith("unset "):
            assert "DSH_HOME" not in line


def test_stop_failure_paths_export_non_not_started_stage_fact() -> None:
    """N-1 修复（lifecycle_agency_review OQ-11 裁定·需改造）.

    停止尝试已发生（TERM/KILL 已发出）⇒ 物理副作用已产生 ⇒ stage_fact 不得
    残留默认 not_started——否则 worker 按"零副作用"自动释放屏障（fail-open）。
    单服务三分支的 stop 失败 then-分支、all 分支 elif 链的 else 兜底，共 4 处。
    """
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "restart_mirror.sh").read_text(encoding="utf-8")

    # 单服务分支：stop 失败分支体（marker → else 之间）必须 export stop_failed
    for marker in (
        'if ! _stop_web "$RESTART_PORT"; then',
        "if ! _feishu_stop; then",
        "if ! _learning_stop; then",
    ):
        assert marker in script, marker
        failure_branch = script.split(marker, 1)[1].split("\n            else", 1)[0]
        assert "export LFL_RESTART_STAGE_FACT=stop_failed" in failure_branch, marker

    # all 分支：elif 链必须带 else（三停全败 ⇒ stop_failed，不得残留 not_started）
    all_branch = script.split("\n  all)", 1)[1].split("\n  status)", 1)[0]
    chain = all_branch.split('if [[ "$_learning_stopped" -eq 1 ]]; then', 1)[1]
    assert 'export LFL_RESTART_STAGE_FACT=web_stopped' in chain
    else_tail = chain.split('export LFL_RESTART_STAGE_FACT=web_stopped', 1)[1]
    assert "else" in else_tail.split("fi", 1)[0]
    assert "export LFL_RESTART_STAGE_FACT=stop_failed" in else_tail.split("fi", 1)[0]
