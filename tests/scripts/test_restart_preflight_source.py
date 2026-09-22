"""T0-A3: restart_mirror.sh CODE_ROOT 来源判定（环境残留防误用）+ PREFLIGHT_ONLY.

复现 2026-09-16 17:22 事故: 会话环境残留 LFL_RESTART_CODE_ROOT 指向旧 worktree，
自动化通道（FORCE=1 / 非交互）必须直接 abort，除非显式 CONFIRMED=1。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restart_mirror.sh"
_SCRIPT_DIR = _SCRIPT.parent.resolve()
RESIDUE_MARKER = "[A3-RESIDUE]"  # R4 参数化后的稳定残留标记（含两个根变量）


def _run(extra_env: dict[str, str], timeout: int = 60, target: str = "preflight") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LFL_RESTART")}
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPT), target],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_bash_syntax_still_clean():
    r = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_static_source_check_and_preflight_mode_present():
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "_code_root_source_check" in src
    assert "_runtime_root_source_check" in src  # R4: RUNTIME_ROOT 同判
    assert "LFL_RESTART_CODE_ROOT_CONFIRMED" in src
    assert "LFL_RESTART_RUNTIME_ROOT_CONFIRMED" in src
    assert RESIDUE_MARKER in src
    assert "preflight)" in src  # PREFLIGHT_ONLY 分支存在
    # 嵌套禁令进入 dual-root 校验
    assert "嵌套" in src


def test_automation_residual_env_aborts(tmp_path: Path):
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT_DIR),
        "LFL_RESTART_CODE_ROOT": str(tmp_path),  # 残留值 ≠ 脚本目录
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert RESIDUE_MARKER in out
    assert "CONFIRMED" in out


def test_residual_env_with_explicit_confirmed_passes_source_check(tmp_path: Path):
    r = _run({
        # R4: RUNTIME_ROOT 指向脚本仓根（== SCRIPT_ROOT）→ 默认来源路径
        "LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT.parents[1]),
        "LFL_RESTART_CODE_ROOT": str(tmp_path),
        "LFL_RESTART_CODE_ROOT_CONFIRMED": "1",
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    # 来源判定必须放行（无残留标记）；后续校验可能因 tmp_path 非 worktree 失败，属预期
    assert RESIDUE_MARKER not in out or "显式确认" in out
    assert "拒绝重启" not in out


def test_script_dir_default_no_prompt():
    r = _run({"LFL_RESTART_RUNTIME_ROOT": str(_SCRIPT.parents[1]), "RESTART_PREFLIGHT_ONLY": "1"})
    out = r.stdout + r.stderr
    # 脚本目录默认来源: 不触发残留路径; 通过或因本地 dirty 停在校验（非来源判定）
    assert "拒绝重启" not in out
    assert r.returncode in (0, 1, 2)


def test_automation_residual_runtime_root_aborts(tmp_path: Path):
    """R4: ambient LFL_RESTART_RUNTIME_ROOT 残留（≠脚本目录）同样必须 abort."""
    residual = tmp_path / "residual-runtime"
    residual.mkdir()  # _resolve_root 要求目录存在，残留路径死于来源判定而非解析
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(residual),
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "LFL_RESTART_RUNTIME_ROOT" in out
    assert "拒绝重启" in out
    # MIRROR_DIR=RUNTIME_ROOT → audit 落在残留根下的 data/audit（不污染真实仓）
    audit = residual / "data" / "audit" / "restart_preflight.log"
    assert audit.is_file()
    last = audit.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "var=LFL_RESTART_RUNTIME_ROOT" in last


def test_runtime_root_confirmed_passes_source_check(tmp_path: Path):
    """R4: RUNTIME_ROOT 残留 + CONFIRMED=1 → 显式确认放行（受控路径语义）."""
    residual = tmp_path / "residual-runtime"
    residual.mkdir()
    r = _run({
        "LFL_RESTART_RUNTIME_ROOT": str(residual),
        "LFL_RESTART_RUNTIME_ROOT_CONFIRMED": "1",
        "RESTART_PREFLIGHT_ONLY": "1",
    })
    out = r.stdout + r.stderr
    assert "显式确认" in out
    assert "拒绝重启" not in out


def test_mutating_root_abort_writes_whitelisted_receipt(tmp_path: Path):
    """S1: 变更目标的根来源中止必须落 durable 回执（R1 白名单标记）。

    2026-09-22 13:20 事故回归：A3 中止 exit 2 但不写回执 → worker 按无回执
    fail-closed keep → 屏障卡死、消息排队无自动恢复。修复后预检链的回执
    义务前移到根检查：先 _write_receipt("root_source_aborted") 再 exit 2。
    只读目标（preflight/status）保持零写入。
    """
    import json as _json
    import shutil as _shutil

    runtime = tmp_path / "runtime-root"
    venv_bin = runtime / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    # _write_receipt 只用 stdlib（datetime/json），系统 python3 即可承载
    (venv_bin / "python").symlink_to(_shutil.which("python3"))
    foreign = tmp_path / "foreign-code"  # 非 git、异仓族 → 来源判定硬拒
    foreign.mkdir()
    r = _run(
        {
            "LFL_RESTART_RUNTIME_ROOT": str(runtime),
            "LFL_RESTART_CODE_ROOT": str(foreign),
        },
        target="web",
    )
    assert r.returncode == 2
    receipt = runtime / "data" / "restart-receipt.json"
    assert receipt.is_file(), "根来源中止必须落回执（R1 消费依赖）"
    rec = _json.loads(receipt.read_text(encoding="utf-8"))
    assert rec["action"] == "web"
    assert rec["rc"] == 2
    assert rec["detail"] == "root_source_aborted"


@pytest.mark.parametrize("env_var", ["LFL_RESTART_CODE_ROOT", "LFL_RESTART_RUNTIME_ROOT"])
def test_same_repo_worktree_root_defers_to_verify(tmp_path: Path, env_var: str):
    """S2: 同 Git 仓族的环境根只告警放行，裁决移交 service-control 绑定核验。

    2026-09-22 13:20 事故根因：受控 dual-root 重启（代码 worktree + 镜像主根）
    与会话残留共用「环境根 ≠ 脚本目录」这一形态，A3 无法区分，靠 CONFIRMED
    硬门反而把滚动升级（旧控制器不带 CONFIRMED）砖死。降级后：同仓族
    （--git-common-dir 相同）→ 告警 + 审计 outcome=deferred-to-verify，由
    desired 部署绑定核验裁决；异仓族仍硬拒（见上一测试）。

    断言走到 dual-root 校验（.venv 缺失 → dual_root_rejected 回执）即证明
    来源判定已放行——旧语义在此处只会输出 root_source_aborted。
    """
    import json as _json
    import subprocess as _sp

    sibling = tmp_path / "sibling-worktree"
    _sp.run(
        ["git", "-C", str(_SCRIPT.parents[1]), "worktree", "add", "--detach", str(sibling), "HEAD"],
        check=True,
        capture_output=True,
    )
    try:
        r = _run({env_var: str(sibling)}, target="web")
        out = r.stdout + r.stderr
        assert "拒绝重启" not in out, "同仓族环境根不得在来源判定处硬拒"
        assert "同 Git 仓族" in out, "必须留下告警（非静默放行）"
        # MIRROR_DIR=RUNTIME_ROOT：RUNTIME_ROOT 变体的审计/回执落在 sibling 根下
        state_root = sibling if env_var == "LFL_RESTART_RUNTIME_ROOT" else _SCRIPT.parents[1]
        audit = state_root / "data" / "audit" / "restart_preflight.log"
        last = audit.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert f"var={env_var}" in last
        assert "outcome=deferred-to-verify" in last
        # 放行后死于 dual-root 校验（sibling 无 .venv），且按 S1 落白名单回执
        assert r.returncode == 2
        receipt = state_root / "data" / "restart-receipt.json"
        rec = _json.loads(receipt.read_text(encoding="utf-8"))
        assert rec["action"] == "web"
        assert rec["detail"] == "dual_root_rejected"
    finally:
        _sp.run(
            ["git", "-C", str(_SCRIPT.parents[1]), "worktree", "remove", "--force", str(sibling)],
            check=False,
            capture_output=True,
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
