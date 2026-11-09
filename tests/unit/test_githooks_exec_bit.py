"""``.githooks/`` 钩子的执行位与入库模式守卫（2026-11-10）。

背景：``core.hooksPath=.githooks`` 让仓库自带钩子生效，但 git 对「没有执行位的
钩子」是**静默跳过**——不报错、不提示，钩子等于不存在。同类降权已发生两次
（``edit_file`` 重写文件把 pre-push 落成 600；pre-commit 长期停在 711），两次都
测试全绿，因为没有任何一条断言在看权限位。

本测试把「静默失效」变成显式失败，覆盖三层，任一层缺失都意味着闸在某条路径上
不存在：

1. owner 读+执行位（0o500）：缺则 git 直接跳过钩子——唯一的真实失效面；
2. group/other 读+执行位：多 uid 执行面（CI 容器、共享 checkout、非 owner 跑 git）；
3. git 索引模式 100755：工作区 ``chmod`` 不随 clone 传播，只有索引模式决定新
   clone 与 CI checkout 拿到的权限。

反例（本测试应拦住，按 RULE-AI-35 口径）：``chmod 644 .githooks/*``、
``git update-index --chmod=-x .githooks/pre-push``、新增钩子但忘 chmod、新增钩子
但忘 git add。
"""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _ROOT / ".githooks"
# git 只按固定名调用钩子；说明类文件不参与执行，不计入降权判定。
_NON_HOOK_NAMES = {"README", "README.md"}


def _hooks() -> list[Path]:
    assert _HOOKS_DIR.is_dir(), (
        f"{_HOOKS_DIR} 缺失：core.hooksPath 将指向空目录，全部闸静默失效"
    )
    hooks = sorted(
        p
        for p in _HOOKS_DIR.iterdir()
        if p.is_file() and p.name not in _NON_HOOK_NAMES and not p.name.startswith(".")
    )
    assert hooks, f"{_HOOKS_DIR} 下没有任何钩子文件：闸已整体丢失，不该静默通过"
    return hooks


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=_ROOT, capture_output=True, text=True, check=False
    )


def _index_modes() -> dict[str, str]:
    """返回 {相对路径: 索引模式}（如 ``.githooks/pre-push`` -> ``100755``）。"""
    res = _git("ls-files", "-s", "--", ".githooks")
    assert res.returncode == 0, f"git ls-files 失败：{res.stderr}"
    modes: dict[str, str] = {}
    for line in res.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and path:
            modes[path] = parts[0]
    return modes


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 无 POSIX 执行位语义")
def test_hooks_have_owner_read_and_execute_bit() -> None:
    """owner 缺 r/x → git 静默跳过钩子（最常见、也最致命的失效）。"""
    bad = []
    for hook in _hooks():
        mode = hook.stat().st_mode
        if (mode & 0o500) != 0o500:
            bad.append(f"{hook.relative_to(_ROOT)}: {stat.filemode(mode)}（缺 owner r+x）")
    assert not bad, (
        "钩子缺 owner 读+执行位，git 会静默跳过它（不报错、不提示）：\n" + "\n".join(bad)
    )


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 无 POSIX 执行位语义")
def test_hooks_are_readable_and_executable_by_non_owner_uid() -> None:
    """711 这类「owner 能跑、group/other 不能读」在单用户机器上无感，但 CI 容器或
    以另一 uid 跑 git 时会失败；仓库既有约定是 755。"""
    bad = []
    for hook in _hooks():
        mode = hook.stat().st_mode
        if (mode & 0o055) != 0o055:
            bad.append(f"{hook.relative_to(_ROOT)}: {stat.filemode(mode)}（group/other 缺 r+x）")
    assert not bad, "钩子对非 owner 不可读/不可执行，多 uid 执行面会失效：\n" + "\n".join(bad)


def test_hooks_committed_with_executable_index_mode() -> None:
    """工作区 chmod 不进历史；只有索引模式 100755 能让新 clone / CI 拿到执行位。"""
    rels = [str(h.relative_to(_ROOT)) for h in _hooks()]
    modes = _index_modes()

    missing = [r for r in rels if r not in modes]
    assert not missing, (
        "钩子未入库：新 clone 拿不到它，闸只存在于当前这台机器：\n" + "\n".join(missing)
    )

    wrong = [f"{r}: {modes[r]}" for r in rels if modes[r] != "100755"]
    assert not wrong, (
        "钩子索引模式不是 100755（git 不记录 r/w 位，只记录执行位）：\n" + "\n".join(wrong)
    )
