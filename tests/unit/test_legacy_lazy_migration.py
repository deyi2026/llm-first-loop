"""D5（惰性迁移，复测修订版 2026-10-20）：legacy sidecar 迁移不在激活路径同步执行.

- workspace 激活只记录惰性标记（migrate fn 不被调用）
- 激活后首次 engine 使用（run 前段 reconcile，即 evidence 访问面入口）一次性补跑
- 第二次访问不重复；migrate 抛异常不阻断访问路径，且同样只尝试一次
- 工作区再次激活重新武装（保持原"每次激活迁移一次"语义）
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.engine_services.session_lifecycle import SessionLifecycle, SessionPlan


class _FakeSessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare_root(self, root: Path) -> Path:
        return root

    def activate_prepared_root(self, prepared: Path) -> None:
        self.root = Path(prepared)

    def exists(self, session_id: str) -> bool:
        return False

    def load(self, session_id: str) -> Any:
        return SimpleNamespace(session_id=session_id, messages=[])

    def save(self, sess: Any) -> None:
        return None


class _FakeHost:
    """LoopEngine 最小替身：只提供 SessionLifecycle.set_workspace/reconcile 触达面."""

    def __init__(self, tmp_path: Path, migrate_fn: Any = None) -> None:
        self.settings = SimpleNamespace(sessions_dir=str(tmp_path / "sessions"))
        self.workspace_store = None
        self.workspace_root = ""
        self.session = _FakeSessionStore(Path(tmp_path / "sessions"))
        self._workspace_epoch = 0
        self._cache_monitor = None
        self._evidence_legacy_migrate_workspace_fn = migrate_fn

    @contextmanager
    def workspace_transition(self):
        yield


def _lifecycle(host: _FakeHost) -> SessionLifecycle:
    # 测试最小替身：host 面按 SessionLifecycle 实际触达属性拼装（pyright 无法静态证明）.
    return SessionLifecycle(host)  # pyright: ignore[reportArgumentType]


def test_workspace_activation_no_longer_migrates_synchronously(tmp_path):
    calls: list[str] = []

    def migrate(root: str) -> object:
        calls.append(root)
        return "report"

    host = _FakeHost(tmp_path, migrate_fn=migrate)
    lifecycle = _lifecycle(host)
    lifecycle.set_workspace(str(tmp_path / "ws"), "wslazy")
    assert calls == [], "激活路径不得同步调用 migrate fn（D5 惰性迁移）"
    assert lifecycle._pending_legacy_migration == str(tmp_path / "ws")


def test_first_evidence_access_runs_migration_exactly_once(tmp_path):
    calls: list[str] = []

    def migrate(root: str) -> object:
        calls.append(root)
        return "report"

    host = _FakeHost(tmp_path, migrate_fn=migrate)
    lifecycle = _lifecycle(host)
    lifecycle.set_workspace(str(tmp_path / "ws"), "wslazy")
    plan1 = lifecycle.reconcile("s1")
    plan2 = lifecycle.reconcile("s2")
    assert isinstance(plan1, SessionPlan) and isinstance(plan2, SessionPlan)
    assert calls == [str(tmp_path / "ws")], "首次访问触发一次，第二次不重复"


def test_migration_failure_does_not_block_evidence_access(tmp_path):
    attempts: list[str] = []

    def boom(root: str) -> object:
        attempts.append(root)
        raise RuntimeError("legacy scan failed")

    host = _FakeHost(tmp_path, migrate_fn=boom)
    lifecycle = _lifecycle(host)
    lifecycle.set_workspace(str(tmp_path / "ws"), "wslazy")
    plan = lifecycle.reconcile("s1")
    assert isinstance(plan, SessionPlan), "migrate 抛异常不得阻断 evidence 访问路径"
    assert isinstance(lifecycle.reconcile("s2"), SessionPlan)
    assert attempts == [str(tmp_path / "ws")], "失败后同样标记完成，不重复尝试"


def test_workspace_reactivation_rearms_lazy_migration(tmp_path):
    calls: list[str] = []

    def migrate(root: str) -> object:
        calls.append(root)
        return "report"

    host = _FakeHost(tmp_path, migrate_fn=migrate)
    lifecycle = _lifecycle(host)
    lifecycle.set_workspace(str(tmp_path / "ws-a"), "wsa")
    lifecycle.reconcile("s1")
    lifecycle.set_workspace(str(tmp_path / "ws-b"), "wsb")
    lifecycle.reconcile("s2")
    assert calls == [str(tmp_path / "ws-a"), str(tmp_path / "ws-b")]


def test_rearm_during_inflight_migration_not_stranded(tmp_path):
    """修订（批次2 D5 后审）: re-arm 与在飞 _migrate_legacy_once 并发不搁浅新 flag.

    场景: 首次 reconcile 的迁移在飞（持 _legacy_migration_lock 阻塞）期间
    set_workspace re-arm 到新 workspace——re-arm 必须持同一把锁等待在飞迁移
    收尾，否则迁移完成时置 done=True 会覆盖 re-arm 的 done=False，新
    workspace 的迁移标记被搁浅（此后永不补跑）。
    """
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def slow_migrate(root: str) -> object:
        calls.append(root)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=5.0)
        return "report"

    host = _FakeHost(tmp_path, migrate_fn=slow_migrate)
    lifecycle = _lifecycle(host)
    lifecycle.set_workspace(str(tmp_path / "ws-a"), "wsa")
    done_first: list[bool] = []

    def first_reconcile() -> None:
        lifecycle.reconcile("s1")  # 触发 ws-a 迁移并在迁移内阻塞（持锁）
        done_first.append(True)

    t1 = threading.Thread(target=first_reconcile)
    t1.start()
    assert entered.wait(timeout=5.0), "首次迁移未进入"
    t2 = threading.Thread(
        target=lambda: lifecycle.set_workspace(str(tmp_path / "ws-b"), "wsb")
    )
    t2.start()
    time.sleep(0.05)  # 让 t2 到达 re-arm 点（修复后阻塞在 _legacy_migration_lock）
    release.set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    assert done_first == [True]
    assert not t1.is_alive() and not t2.is_alive()
    # 新 flag 未被在飞迁移的收尾 done=True 覆盖 → 首次访问照常补跑 ws-b
    lifecycle.reconcile("s2")
    assert calls == [str(tmp_path / "ws-a"), str(tmp_path / "ws-b")], (
        "re-arm 被在飞迁移覆盖 → ws-b 迁移被搁浅"
    )


def test_reconcile_without_activation_is_noop(tmp_path):
    calls: list[str] = []

    def migrate(root: str) -> object:
        calls.append(root)
        return "report"

    host = _FakeHost(tmp_path, migrate_fn=migrate)
    lifecycle = _lifecycle(host)
    assert isinstance(lifecycle.reconcile("s1"), SessionPlan)
    assert calls == [], "无激活标记时不触发迁移"
