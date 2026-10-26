"""tests/env_channel.py 谓词自测（EVO-20261025-d00c717d）.

两层验证：
1. monkeypatch 逻辑测试——模拟受限/正常两种环境，断言谓词判定正确
   （防误伤 Linux / 正常 darwin）；
2. 真实通道实测——仅在对应通道内运行（skipif 守卫）：当前 AI 工具层
   sandbox-exec 沙箱通道即真实受限环境，直接断言谓词成立；主树/干净
   worktree 通道则断言不触发。
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

from tests import env_channel


def _fake_proc(returncode: int, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stderr=stderr)


def _patch_sandbox_exec_present(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(env_channel, "_SANDBOX_EXEC", "/usr/bin/true")
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(os, "access", lambda _p, _m: True)


# ── nested_sandbox_exec：逻辑测试（monkeypatch，通道无关） ──


def test_nested_probe_linux_never_triggers(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert env_channel._probe_nested_sandbox_exec() is False


def test_nested_probe_missing_binary_not_restricted(monkeypatch):
    _patch_sandbox_exec_present(monkeypatch)
    monkeypatch.setattr(env_channel, "_SANDBOX_EXEC", "/nonexistent-env-channel-probe")
    assert env_channel._probe_nested_sandbox_exec() is False


def test_nested_probe_success_not_restricted(monkeypatch):
    _patch_sandbox_exec_present(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc(0))
    assert env_channel._probe_nested_sandbox_exec() is False


def test_nested_probe_sandbox_apply_failure_is_restricted(monkeypatch):
    _patch_sandbox_exec_present(monkeypatch)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _fake_proc(71, "sandbox-exec: sandbox_apply: Operation not permitted"),
    )
    assert env_channel._probe_nested_sandbox_exec() is True


def test_nested_probe_operation_not_permitted_is_restricted(monkeypatch):
    _patch_sandbox_exec_present(monkeypatch)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _fake_proc(1, "Operation not permitted"),
    )
    assert env_channel._probe_nested_sandbox_exec() is True


def test_nested_probe_unrelated_failure_not_restricted(monkeypatch):
    _patch_sandbox_exec_present(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc(1, "no such file"))
    assert env_channel._probe_nested_sandbox_exec() is False


# ── tmpdir_redirected：逻辑测试 ──


def test_tmpdir_redirected_when_darwin_tmp(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/tmp")
    assert env_channel.tmpdir_redirected() is True


def test_tmpdir_not_redirected_on_normal_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/var/folders/yx/T/")
    assert env_channel.tmpdir_redirected() is False


def test_tmpdir_never_redirected_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/tmp")
    assert env_channel.tmpdir_redirected() is False


# ── production_env_injected ──


def test_production_env_injected_false_without_marker(monkeypatch):
    monkeypatch.delenv("LFL_MAX_ITERATIONS", raising=False)
    assert env_channel.production_env_injected() is False


def test_production_env_injected_true_with_marker(monkeypatch):
    monkeypatch.setenv("LFL_MAX_ITERATIONS", "120")
    assert env_channel.production_env_injected() is True


# ── operator_mailbox_absent：逻辑测试（monkeypatch ACL 语义） ──


def _patch_mailbox_probe(monkeypatch, tmp_path, *, gid: int, mode: int) -> None:
    base = tmp_path / "probe-base"
    base.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: str(base))
    # 只 patch 模块级 _lstat 别名：不污染全局 os.lstat（shutil.rmtree 依赖它）
    monkeypatch.setattr(
        env_channel, "_lstat",
        lambda _p: SimpleNamespace(
            st_mode=stat.S_IFDIR | mode, st_uid=os.geteuid(), st_gid=gid,
        ),
    )


def test_mailbox_absent_when_sgid_dropped_and_gid_inherited(monkeypatch, tmp_path):
    # 沙箱通道实测形态：/private/tmp 下 gid=wheel(0)，chmod(0o2750) 的 SGID 被丢弃
    _patch_mailbox_probe(monkeypatch, tmp_path, gid=0, mode=0o750)
    assert env_channel._probe_operator_mailbox_absent() is True


def test_mailbox_not_absent_when_qualified(monkeypatch, tmp_path):
    _patch_mailbox_probe(monkeypatch, tmp_path, gid=os.getegid(), mode=0o2750)
    assert env_channel._probe_operator_mailbox_absent() is False


def test_mailbox_probe_fail_open_on_oserror(monkeypatch, tmp_path):
    def _boom(*_a, **_k):
        raise OSError("probe failure")

    monkeypatch.setattr(tempfile, "mkdtemp", _boom)
    assert env_channel._probe_operator_mailbox_absent() is False


# ── in_git_worktree_detached_root：逻辑测试（monkeypatch git 输出） ──


def _patch_git(monkeypatch, *, toplevel: str, git_dir: str, common_dir: str) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=f"{toplevel}\n{git_dir}\n{common_dir}\n",
        ),
    )


def test_worktree_predicate_main_tree_false(monkeypatch):
    _patch_git(monkeypatch, toplevel="/repo", git_dir=".git", common_dir=".git")
    assert env_channel._probe_in_git_worktree_detached_root() is False


def test_worktree_predicate_dot_worktrees_true(monkeypatch):
    _patch_git(
        monkeypatch,
        toplevel="/repo/.worktrees/gate-20261025",
        git_dir="/repo/.git/worktrees/gate-20261025",
        common_dir="/repo/.git",
    )
    assert env_channel._probe_in_git_worktree_detached_root() is True


def test_worktree_predicate_tmp_ci_true(monkeypatch):
    _patch_git(
        monkeypatch,
        toplevel="/repo/.tmp-ci/gate-run",
        git_dir="/repo/.git/worktrees/gate-run",
        common_dir="/repo/.git",
    )
    assert env_channel._probe_in_git_worktree_detached_root() is True


def test_worktree_predicate_git_failure_false(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stderr="fatal", stdout=""),
    )
    assert env_channel._probe_in_git_worktree_detached_root() is False


# ── 真实通道实测（skipif 守卫：只在对应通道断言对应事实） ──


@pytest.mark.skipif(
    not env_channel.nested_sandbox_exec(),
    reason="仅真实工具层 sandbox-exec 沙箱通道实测（当前 AI 通道即沙箱）",
)
def test_real_sandbox_channel_predicates_hold():
    assert env_channel.nested_sandbox_exec() is True
    assert env_channel.tmpdir_redirected() is True
    assert env_channel.operator_mailbox_absent() is True


@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="仅非沙箱环境实测防误伤（正常 darwin/Linux 临时目录语义）",
)
def test_normal_channel_tmpdir_not_redirected():
    assert env_channel.tmpdir_redirected() is False


@pytest.mark.skipif(
    not env_channel.in_git_worktree_detached_root(),
    reason="仅干净 worktree 门通道实测谓词成立",
)
def test_real_worktree_channel_predicate_holds():
    assert env_channel.in_git_worktree_detached_root() is True


@pytest.mark.skipif(
    env_channel.in_git_worktree_detached_root(),
    reason="主树检出通道实测谓词不触发",
)
def test_main_tree_worktree_predicate_does_not_fire():
    assert env_channel.in_git_worktree_detached_root() is False
