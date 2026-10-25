"""测试执行通道自检谓词（EVO-20261025-d00c717d，用户批准演进）.

用途（且仅此用途）：给依赖真实 OS 语义的测试用例做**环境自检 skip**——
在 AI 工具层受限通道（sandbox-exec 嵌套 / TMPDIR 回落 / 生产 env 注入）或
干净 worktree 全量门通道里，这些用例的红是环境噪音而非代码回归（登记于
eval/rules/known_reds_current.json，RED-04 起）；检测到受限通道则带理由
skip，正常开发环境与 CI 照常全量运行，恢复全量门信噪比。

⚠️ 本模块**不是运行时安全护栏**：谓词不参与任何生产路径判定；误报的
后果只是少跑一个测试（skip），从不放宽隔离、从不放行任何操作。

谓词清单（与登记根因一一对应）：
- nested_sandbox_exec()：当前进程已被工具层 sandbox-exec 包裹（darwin），
  再起 sandbox-exec 会 `sandbox_apply: Operation not permitted`。
- tmpdir_redirected()：darwin 下 tempfile.gettempdir() 的 realpath 落在
  /private/tmp（正常 darwin 为 /private/var/folders/...；工具层沙箱的
  写域令 /var/folders 不可写、tempfile 回落 /tmp）。
- production_env_injected()：os.environ 含 LFL_MAX_ITERATIONS（生产 .env
  注入信号，评测通道环境差异用）。
- operator_mailbox_absent()：在当前有效临时根下无法构造合格 operator
  mailbox 目录（euid:egid 属主 + SGID；沙箱通道 /private/tmp 的目录组为
  wheel(0) 且非 root 无法设置 SGID），对应 mailbox ACL 用例前置不可达成。
- in_git_worktree_detached_root()：本套测试正从链接/detached worktree
  （.worktrees/、.tmp-ci/ 或 /tmp 系临时 worktree）运行，即 RULE-AI-28
  竞态规避的全量门通道，而非主检出区。
"""

from __future__ import annotations

import functools
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_PROBE_TIMEOUT_S = 5.0
# 仓库既定布局：主 worktree 下挂 .worktrees/；PLAYBOOK-worktree-lifecycle-v1
# 另登记 .tmp-ci/ 与 /tmp 系临时 worktree。
_WORKTREE_DIR_NAMES = frozenset({".worktrees", ".tmp-ci"})

# 间接引用：自测只 patch 模块别名，不污染全局 os.lstat（shutil.rmtree 内部依赖它）
_lstat = os.lstat


def _probe_nested_sandbox_exec() -> bool:
    """真实探测：受限外层下再起 sandbox-exec 会以 sandbox_apply 失败。"""
    if sys.platform != "darwin":
        return False  # Linux 无 sandbox-exec，绝不误伤
    if not (os.path.isfile(_SANDBOX_EXEC) and os.access(_SANDBOX_EXEC, os.X_OK)):
        return False
    try:
        proc = subprocess.run(
            [_SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False  # 探测自身异常不视为受限（宁可跑测试见真失败）
    if proc.returncode == 0:
        return False
    stderr = proc.stderr or ""
    return "sandbox_apply" in stderr or "Operation not permitted" in stderr


@functools.lru_cache(maxsize=1)
def nested_sandbox_exec() -> bool:
    """当前进程处于 sandbox-exec 嵌套受限环境（仅 darwin 可能为 True）。"""
    return _probe_nested_sandbox_exec()


def tmpdir_redirected() -> bool:
    """darwin 有效临时目录回落/重定向到 /private/tmp（正常为 /var/folders）。"""
    if sys.platform != "darwin":
        return False  # Linux 的 /tmp 是正常 tmpdir，不触发
    try:
        real = os.path.realpath(tempfile.gettempdir())
    except OSError:
        return False
    return real == "/private/tmp" or real.startswith("/private/tmp/")


def production_env_injected() -> bool:
    """进程环境含生产 .env 注入信号（LFL_MAX_ITERATIONS 等 LFL 运行参数）。"""
    return "LFL_MAX_ITERATIONS" in os.environ


def _probe_operator_mailbox_absent() -> bool:
    """在当前有效临时根下实测"合格 mailbox 目录"是否可构造。

    合格形态对齐 src/llm_loop/resources/task_budget_operator_mailbox.py
    的 _check_mailbox_directory：目录 + 属主 euid + 组 egid + SGID。
    沙箱通道 /private/tmp 下新建目录组继承 wheel(0)，且非 wheel 成员
    chmod(0o2750) 的 SGID 位被内核静默丢弃 → 资格不可达成。
    """
    try:
        base = Path(tempfile.mkdtemp(prefix="env-channel-mailbox-probe-"))
    except OSError:
        return False
    try:
        mailbox = base / "approval-mailbox"
        mailbox.mkdir()
        os.chmod(mailbox, 0o2750)
        st = _lstat(mailbox)
        qualified = (
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.geteuid()
            and st.st_gid == os.getegid()
            and bool(st.st_mode & stat.S_ISGID)
        )
        return not qualified
    except OSError:
        # 探测自身失败按"不缺席"处理：保持用例运行，让真实失败可见
        return False
    finally:
        shutil.rmtree(base, ignore_errors=True)


@functools.lru_cache(maxsize=1)
def operator_mailbox_absent() -> bool:
    """当前环境无法构造合格 operator mailbox（mailbox ACL 用例前置不可达成）。"""
    return _probe_operator_mailbox_absent()


def _resolve_git_path(raw: str, *, anchor: Path, toplevel: Path) -> str:
    """git rev-parse 相对路径输出按锚点目录/仓库根解析为绝对 realpath。"""
    if os.path.isabs(raw):
        return os.path.realpath(raw)
    for base in (anchor, toplevel):
        candidate = os.path.realpath(os.path.join(base, raw))
        if os.path.exists(candidate):
            return candidate
    return os.path.realpath(os.path.join(toplevel, raw))


def _probe_in_git_worktree_detached_root() -> bool:
    """本文件所在 checkout 是否为链接/detached worktree（非主检出区）。"""
    anchor = Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir"],
            cwd=anchor,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    lines = (proc.stdout or "").split()
    if proc.returncode != 0 or len(lines) != 3:
        return False
    toplevel = Path(lines[0]).resolve()
    if any(part in _WORKTREE_DIR_NAMES for part in toplevel.parts):
        return True
    real = os.path.realpath(toplevel)
    if real == "/tmp" or real.startswith("/tmp/"):
        return True
    if real == "/private/tmp" or real.startswith("/private/tmp/"):
        return True
    # 链接 worktree 的 git-dir 指向 <主树>/.git/worktrees/<name>，与
    # git-common-dir（主树 .git）不同；主树两者一致。
    git_dir = _resolve_git_path(lines[1], anchor=anchor, toplevel=toplevel)
    common_dir = _resolve_git_path(lines[2], anchor=anchor, toplevel=toplevel)
    return git_dir != common_dir


@functools.lru_cache(maxsize=1)
def in_git_worktree_detached_root() -> bool:
    """当前测试套运行在 .worktrees/.tmp-ci//tmp 系链接 worktree 通道。"""
    return _probe_in_git_worktree_detached_root()


def reset_caches() -> None:
    """清空谓词缓存（自测钩子；进程内探测只应发生一次）。"""
    nested_sandbox_exec.cache_clear()
    operator_mailbox_absent.cache_clear()
    in_git_worktree_detached_root.cache_clear()
