"""restart_mirror.sh 的企微（wecom）服务分支契约。

背景（独立审查 P1-1）：service_control.build_restart_plan（runtime/service_control.py）
把 target 原样传给 <code_root>/scripts/restart_mirror.sh；该脚本的 case 分派原本
只有 preflight|web|feishu|learning|all|status，wecom 落到默认分支 → exit 1 且**无回执**
→ _consume_restart_failure_receipt 无法证明零副作用 → 准入屏障 fail-closed keep
→ wecom 屏障卡死；走 update 则 publish 半程成功、restart 半程失败 → 半应用状态。

本文件锁住：wecom 分支存在且与 feishu 同构（停止/启动/回执/忙闲判定），
并用 /tmp 副本做真干跑（kill 被替换为 no-op，绝不触碰在服企微桥）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "restart_mirror.sh"

_KILL_TERM = 'kill -TERM "$pid" 2>/dev/null || true'
_KILL_KILL = 'kill -KILL "$pid" 2>/dev/null || true'
_SPAWN = (
    '_spawn_detached data/wecom_bridge.log "$VENV_PY" '
    "-m llm_loop.runtime.launch wecom"
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_wecom_branch_exists_in_case_dispatch() -> None:
    script = _script_text()
    assert "  wecom)" in script
    # 用法文案必须列出 wecom（否则运维无从得知该分支存在）
    assert "{web|feishu|learning|wecom|all|status}" in script


def test_wecom_has_stop_and_start_helpers() -> None:
    script = _script_text()
    assert "_wecom_pids() {" in script
    assert "_wecom_stop() {" in script
    assert "_start_wecom() {" in script
    assert "_wecom_heartbeat_busy() {" in script


def test_wecom_start_uses_runtime_launch_and_heartbeat_readiness() -> None:
    """启动必须走 runtime.launch（刷新 runtime_manifest.wecom.json），
    就绪判定用心跳（pid 匹配 + state ∈ connected/authenticated）。"""
    script = _script_text()
    block = script.split("_start_wecom() {", 1)[1].split("_start_learning() {", 1)[0]
    assert "-m llm_loop.runtime.launch wecom" in block
    assert "data/wecom_heartbeat.json" in block
    assert "'connected','authenticated'" in block


def test_wecom_stop_uses_dual_sided_argv_probe() -> None:
    """停止的进程发现必须双面：runtime.launch 形态 + llm_loop.wecom 回滚形态。"""
    script = _script_text()
    block = script.split("_wecom_pids() {", 1)[1].split("_wecom_stop() {", 1)[0]
    assert r"llm_loop\.runtime\.launch wecom" in block
    assert r"llm_loop\.wecom" in block
    stop_block = script.split("_wecom_stop() {", 1)[1].split("_start_wecom() {", 1)[0]
    assert "kill -TERM" in stop_block and "kill -KILL" in stop_block


def test_wecom_receipt_cases_cover_wecom() -> None:
    """三处写回执的 case 都必须覆盖 wecom（回执格式是被上游解析的契约）。"""
    script = _script_text()
    assert "web|feishu|learning|wecom|all)" in script
    assert script.count("web|feishu|learning|wecom|all)") >= 3


def test_wecom_branch_is_not_in_all_batch() -> None:
    """all 分支**不得**包含 wecom：单机器人同一时刻只允许一个长连接，
    批量重启 web/feishu 不应连带踢掉在服的企微长连接。"""
    script = _script_text()
    case_body = script.split("\ncase ", 1)[1]
    all_body = case_body.split("\n  all)", 1)[1].split(";;", 1)[0]
    assert "wecom" not in all_body


def test_wecom_dry_run_writes_wecom_receipt_instead_of_default_usage(
    tmp_path: Path,
) -> None:
    """真干跑：副本里 kill → no-op、启动 → sleep，执行 wecom 分支。

    核心契约（本次修复的回归点）：wecom 被 case 分派接管，**不再**掉进默认
    分支的「用法: … ; exit 1」。旧行为的关键差异是**没有回执**（默认分支
    直接 exit 1），而准入屏障靠回执证明零副作用 —— 所以本断言锁定的是
    「回执存在且 action=wecom」。

    绝不执行原脚本的 stop/start（在服企微桥不得被误杀）。
    """
    copy = tmp_path / "restart_mirror_dry.sh"
    text = SCRIPT.read_text(encoding="utf-8")
    text = text.replace(_KILL_TERM, "echo DRY_NO_KILL_TERM")
    text = text.replace(_KILL_KILL, "echo DRY_NO_KILL_KILL")
    text = text.replace(
        _SPAWN,
        '_spawn_detached data/wecom_bridge.log "$VENV_PY" '
        '-c "import time; time.sleep(1)"',
    )
    copy.write_text(text, encoding="utf-8")

    # 两个根指向真实仓库：脚本按 RUNTIME_ROOT 推导 VENV_PY、CODE_ROOT 需为
    # Git worktree；同根不触发 dual-root 分支。回执落在仓库 data/ —— 测完必须
    # 清理（陈旧回执会被 service_control._consume_restart_failure_receipt 误消费）。
    receipt_path = ROOT / "data" / "restart-receipt.json"
    receipt_path.unlink(missing_ok=True)
    try:
        proc = subprocess.run(
            ["bash", str(copy), "wecom"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin",
                "HOME": str(tmp_path),
                "LFL_RESTART_AUTHORITY": "service_control",
                "LFL_RESTART_RUNTIME_ROOT": str(ROOT),
                "LFL_RESTART_CODE_ROOT": str(ROOT),
                "LFL_RESTART_CODE_ROOT_CONFIRMED": "1",
                "LFL_RESTART_RUNTIME_ROOT_CONFIRMED": "1",
            },
        )
        out = proc.stdout + proc.stderr
        # 没有落到默认分支的用法文案（核心回归断言）
        assert "用法:" not in out, out
        # 回执落盘且 action=wecom —— 旧行为下这里根本不会有回执
        assert receipt_path.is_file(), out
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert data.get("action") == "wecom", data
        # 干跑保护：有在服桥时 kill 被替换为 no-op（证明未误杀真实进程）
        if "DRY_NO_KILL_TERM" in out:
            assert "DRY_NO_KILL_KILL" in out
    finally:
        receipt_path.unlink(missing_ok=True)
