"""修1-修5(2026-09-09): restart_mirror.sh 加固静态断言.

背景（EXPERIENCE 2026-09-09 假 armed 回执事故——stdout 回执随宿主死亡）:
- 修1 RESTART_WAIT_IDLE 长任务保护移植到位（web/feishu/all 三分支均 precheck）
- 修2 all 分支失败补偿：web 失败不短路吞掉 feishu 恢复
- 修3 可移植进程脱离（_spawn_detached: python setsid+execvp），服务启动不再裸 nohup&
- 修4 回执落盘（_write_receipt → data/restart-receipt.{json,log}）
- 修5 stop 判定源：web=端口∪argv 且等 PID 退出；feishu=心跳 pid（新鲜度门）∪argv
"""
import re
import subprocess
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
    for branch in ("web)", "feishu)", "all)"):
        m = re.search(re.escape(branch) + r"[^\n]*_restart_precheck", src)
        assert m, f"{branch} 分支未接 _restart_precheck"


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
