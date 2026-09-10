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
    assert 'web)     _restart_precheck' in script
    assert '_stop_web "$RESTART_PORT"' in script
    assert "web 停止失败，跳过启动（防双进程）" in script
    assert 'all)     _restart_precheck' in script
    # Regression: port release alone must never be the stop-complete condition.
    stop_block = script.split("_stop_web() {", 1)[1].split("_start_web() {", 1)[0]
    assert "_pid_alive" in stop_block
    assert "kill -KILL" in stop_block
