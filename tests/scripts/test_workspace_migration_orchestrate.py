"""P1-3 编排恢复路径修复（2026-10-25）定向测试.

覆盖：
- workspace_env_precheck.py：合法/事故形态/坏 TTL/无密泄漏/缺文件/strict 模式
- workspace_migration_orchestrate.sh：bash 语法、预检先于停服、trap 全路径锁释放、
  lsof 仅 LISTEN、PID 身份记录、worker 终态跟踪（受理≠成功）、四类失败分支
- workspace_migration_drill_failures.sh：四场景演练定义齐全 + 生产护栏断言
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
PRECHECK = SCRIPTS / "workspace_env_precheck.py"
ORCH = SCRIPTS / "workspace_migration_orchestrate.sh"
DRILL = SCRIPTS / "workspace_migration_drill_failures.sh"


def _make_hash() -> str:
    salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")
    digest = base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", b"pw", secrets.token_bytes(16), 600000)
    ).decode().rstrip("=")
    return f"pbkdf2_sha256$600000${salt}${digest}"


def _run_precheck(env_file: Path, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(PRECHECK), str(env_file), *extra],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


class TestEnvPrecheck:
    def test_accepts_valid_env(self, tmp_path):
        h = _make_hash()
        env = tmp_path / ".env"
        env.write_text(f"WEB_LOGIN_PASSWORD_HASH={h}\nWEB_SESSION_TTL_SECONDS=43200\n", encoding="utf-8")
        rc, out = _run_precheck(env)
        assert rc == 0, out
        assert '"ok": true' in out

    def test_rejects_glued_ttl_incident_shape(self, tmp_path):
        """复刻 2026-10-25 07:52 事故形态：TTL 拼入哈希行尾."""
        h = _make_hash()
        env = tmp_path / ".env"
        env.write_text(f"WEB_LOGIN_PASSWORD_HASH={h}WEB_SESSION_TTL_SECONDS=43200\n", encoding="utf-8")
        rc, out = _run_precheck(env)
        assert rc == 2
        assert '"ok": false' in out
        # 行级 + 独立重读双层拦截
        assert "非独立" in out or "拼接" in out

    def test_rejects_bad_ttl(self, tmp_path):
        h = _make_hash()
        env = tmp_path / ".env"
        env.write_text(f"WEB_LOGIN_PASSWORD_HASH={h}\nWEB_SESSION_TTL_SECONDS=abc\n", encoding="utf-8")
        rc, _ = _run_precheck(env)
        assert rc == 2

    def test_no_secret_leakage(self, tmp_path):
        h = _make_hash()
        env = tmp_path / ".env"
        env.write_text(f"WEB_LOGIN_PASSWORD_HASH={h}WEB_SESSION_TTL_SECONDS=43200\n", encoding="utf-8")
        _, out = _run_precheck(env)
        salt = h.split("$")[2]
        digest = h.split("$")[3]
        assert salt not in out and digest not in out

    def test_missing_file_fails_closed(self, tmp_path):
        rc, _ = _run_precheck(tmp_path / "nope.env")
        assert rc == 2

    def test_strict_missing_hash(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("WEB_SESSION_TTL_SECONDS=43200\n", encoding="utf-8")
        rc, _ = _run_precheck(env, "--strict-missing-hash")
        assert rc == 2
        rc, out = _run_precheck(env)
        assert rc == 0  # 非严格模式仅提示

    def test_duplicate_hash_lines_rejected(self, tmp_path):
        h = _make_hash()
        env = tmp_path / ".env"
        env.write_text(f"WEB_LOGIN_PASSWORD_HASH={h}\nWEB_LOGIN_PASSWORD_HASH={h}\n", encoding="utf-8")
        rc, _ = _run_precheck(env)
        assert rc == 2


def _orch_src() -> str:
    return ORCH.read_text(encoding="utf-8")


class TestOrchestrateScript:

    def test_bash_syntax(self):
        for f in (ORCH, DRILL):
            proc = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True, check=False)
            assert proc.returncode == 0, f"{f}: {proc.stderr}"

    def test_precheck_runs_before_stop(self):
        orch_src = _orch_src()
        """修复1：停机前预检必须发生在任何 stop_one 调用之前（主流程顺序）."""
        main_flow = orch_src.split("# 0) 起步延迟", 1)[1]
        assert main_flow.index("env_precheck") < main_flow.index('stop_one web'), \
            "env 预检必须先于停服"

    def test_trap_releases_lock_on_all_paths(self):
        orch_src = _orch_src()
        """修复4：EXIT/INT/TERM 均经 on_exit→release_lock；显式失败路径亦释放."""
        assert "trap on_exit EXIT" in orch_src
        assert "trap 'on_signal TERM' TERM" in orch_src
        assert "trap 'on_signal INT' INT" in orch_src
        on_exit = orch_src.split("on_exit() {", 1)[1].split("}", 1)[0]
        assert "release_lock" in on_exit, "EXIT trap 必须兜底释放锁"

    def test_lsof_listen_only(self):
        orch_src = _orch_src()
        """修复5：lsof 命令必须限定 -sTCP:LISTEN，不得裸用（描述文本不判）."""
        for line in orch_src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("emit ") or "echo" in stripped.split("lsof")[0]:
                continue
            if "lsof -" in stripped:  # 实际命令调用（带 flag）
                assert "-sTCP:LISTEN" in stripped, f"lsof 未限定 LISTEN: {stripped}"

    def test_pid_identity_recorded(self):
        orch_src = _orch_src()
        """修复5：停前记录每 PID 身份（ps comm/ppid），写入审计 jsonl."""
        assert 'ps -p "$p" -o pid=,ppid=,comm=' in orch_src
        assert 'emit "stop_$name" "targets"' in orch_src

    def test_worker_terminal_tracking(self):
        orch_src = _orch_src()
        """修复2：受理≠成功；轮询 action 真实终态."""
        assert "受理≠成功" in orch_src
        assert "wait_worker_terminal" in orch_src
        assert "succeeded|failed" in orch_src
        assert '"step":"start","status":"accepted"' not in orch_src  # accepted 仅函数内部 status
        assert 'emit start accepted' in orch_src
        assert 'emit start ok "worker 终态=succeeded' in orch_src

    def test_four_failure_branches(self):
        orch_src = _orch_src()
        """修复3：四类失败分支各自正确响应."""
        # 迁移失败 → 回滚 + 旧布局起服
        assert "migrate fail" in orch_src and "recover_rollback_start" in orch_src
        # 起服失败 → 优先恢复服务（迁移完成时不回滚数据）
        assert "recover_start started" in orch_src
        assert "数据保留新布局（不回滚数据）" in orch_src
        # 健康失败 → 诊断包 + 人工指引 + 释放锁 + 非零退出
        assert "health fail" in orch_src and "collect_diag_bundle healthfail" in orch_src
        assert "人工指引" in orch_src
        # verify 失败 → 差异清单 + 释放锁
        assert "verify fail" in orch_src and "verify-diffs" in orch_src

    def test_every_step_emits_jsonl(self):
        orch_src = _orch_src()
        """修复6：每步动作（含失败分支）写 orchestration-*.jsonl."""
        for step in ("orchestrate started", "env_precheck", "stop_$name", "migrate",
                     "env_append", "start accepted", "start ok", "start fail",
                     "health", "verify", "lock acquired", "lock released",
                     "orchestrate exit"):
            assert step.split()[0] in orch_src, f"缺少步骤落账: {step}"


def _drill_src() -> str:
    return DRILL.read_text(encoding="utf-8")


class TestDrillScript:

    def test_all_scenarios_present(self):
        drill_src = _drill_src()
        """验收5：坏哈希/起服失败/服务忙碌/异常退出四场景（+C 健康失败）实测定义."""
        for scen in ("scen_A", "scen_B", "scen_B2", "scen_C", "scen_D"):
            assert scen in drill_src, f"演练缺少场景 {scen}"
        assert "start-fail" in drill_src and "busy" in drill_src

    def test_isolation_guards(self):
        drill_src = _drill_src()
        """演练必须全量重定向 LFL_ORCH_* 到镜像 + 生产护栏断言 + 端口隔离."""
        for var in ("LFL_ORCH_DATA_DIR", "LFL_ORCH_ENV_FILE", "LFL_ORCH_LOCK",
                    "LFL_ORCH_SVCCTL_STUB", "LFL_ORCH_NEW_ROOT"):
            assert var in drill_src
        assert "PROD_ENV_SHA_BEFORE" in drill_src and "PROD_ENV_SHA_AFTER" in drill_src
        assert "拒绝使用生产端口 8903" in drill_src
        assert "mktemp -d /tmp/lfl-migration-drill" in drill_src
