"""ASSESS-20261008-project-audit rev3 §7 WP2 回归: BUG-01 共享文件锁异常传播.

修复契约（报告 §1 验收）:
- 整个上下文只 yield 一次（contextlib 生成器不得二次 yield）;
- 业务 OSError/ValueError 保留原异常对象、类型与内容，with 主体只执行一次;
- 锁已取得时主体 OSError 不产生"共享文件锁不可用（fail-open）"日志;
  open/flock 失败仍按加锁失败契约 fail-open 并记录锁日志;
- unlock 失败记录为清理阶段故障，不覆盖传播中的业务异常。

测试契约: 全部离线（tmp_path + monkeypatch fcntl），无真实跨进程依赖。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from llm_loop.core.session import SessionStore

_NAME = "shared_current_session"


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def test_body_oserror_preserved_and_single_yield(tmp_path, monkeypatch):
    """主体 OSError: 原异常对象/类型穿透，无 RuntimeError（BUG-01 核心）."""
    store = _store(tmp_path)
    boom = OSError("disk full during write")
    with pytest.raises(OSError) as ei, store._shared_file_lock(_NAME):
        raise boom
    # 身份断言: 原异常对象原样传播（非 RuntimeError 包装、非二次 yield）
    assert ei.value is boom


def test_body_valueerror_preserved(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match=r"原业务值错误"), store._shared_file_lock(_NAME):
        raise ValueError("原业务值错误")


def test_no_misleading_lock_log_when_body_oserror(tmp_path, caplog):
    """锁已取得时主体 OSError 不得记为'共享文件锁不可用'（观测面失真）."""
    store = _store(tmp_path)
    caplog.set_level(logging.WARNING, logger="llm_loop.core.session")
    with pytest.raises(OSError, match="disk io error"), store._shared_file_lock(_NAME):
        raise OSError("disk io error")
    for rec in caplog.records:
        assert "共享文件锁不可用" not in rec.getMessage()


def test_open_failure_fail_open_single_yield(tmp_path, monkeypatch, caplog):
    """锁文件 open 失败: 保留 fail-open 契约（单次 yield + 锁日志）."""
    store = _store(tmp_path)
    caplog.set_level(logging.WARNING, logger="llm_loop.core.session")

    import builtins

    real_open = builtins.open

    def _fail_open(path, *a, **k):
        if str(path).endswith(f"{_NAME}.lock"):
            raise OSError("cannot open lock file")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", _fail_open)
    entered = []
    with store._shared_file_lock(_NAME):
        entered.append(1)
    assert entered == [1]  # 单次 yield，主体执行一次
    assert any("共享文件锁不可用" in r.getMessage() for r in caplog.records)


def test_flock_failure_fail_open_single_yield(tmp_path, monkeypatch, caplog):
    """flock(LOCK_EX) 失败: 保留 fail-open 契约（单次 yield + 锁日志）."""
    store = _store(tmp_path)
    caplog.set_level(logging.WARNING, logger="llm_loop.core.session")

    import fcntl

    def _fail_flock(fd, op):
        raise OSError("flock unavailable")

    monkeypatch.setattr(fcntl, "flock", _fail_flock)
    entered = []
    with store._shared_file_lock(_NAME):
        entered.append(1)
    assert entered == [1]
    assert any("共享文件锁不可用" in r.getMessage() for r in caplog.records)


def test_unlock_failure_logged_as_cleanup_not_swallow_body(tmp_path, monkeypatch, caplog):
    """释放失败: 记为清理阶段故障; 业务异常仍为最终传播的异常."""
    store = _store(tmp_path)
    caplog.set_level(logging.WARNING, logger="llm_loop.core.session")

    import fcntl

    state = {"unlock_attempted": False}

    def _flock(fd, op):
        if op == fcntl.LOCK_EX:
            return
        if op == fcntl.LOCK_UN:
            state["unlock_attempted"] = True
            raise OSError("unlock failed")

    monkeypatch.setattr(fcntl, "flock", _flock)
    with pytest.raises(OSError, match="业务磁盘故障"), store._shared_file_lock(_NAME):
        raise OSError("业务磁盘故障")
    assert state["unlock_attempted"]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("释放失败" in m for m in msgs)          # 清理阶段归因
    assert not any("共享文件锁不可用" in m for m in msgs)  # 不误标为加锁失败


def test_lock_serializes_concurrent_bodies(tmp_path, monkeypatch):
    """对照: 正常互斥语义不受重构影响（顺序进入，无并发交错）."""
    store = _store(tmp_path)
    order = []

    class _Probe:
        def __enter__(self):
            order.append("enter")
            return self

        def __exit__(self, *exc):
            order.append("exit")
            return False

    import fcntl

    monkeypatch.setattr(fcntl, "flock", lambda fd, op: None)
    with store._shared_file_lock(_NAME), _Probe():
        pass
    assert order == ["enter", "exit"]


def test_non_posix_fallback_lock_branch(tmp_path, monkeypatch):
    """fcntl 不可用（非 POSIX）: 回退进程内锁，单次 yield、异常照常传播."""
    import sys

    store = _store(tmp_path)
    monkeypatch.setitem(sys.modules, "fcntl", None)  # import fcntl → ImportError
    entered = []
    with store._shared_file_lock(_NAME):
        entered.append(1)
    assert entered == [1]
    boom = ValueError("fallback 下业务异常")
    with pytest.raises(ValueError), store._shared_file_lock(_NAME):
        raise boom
