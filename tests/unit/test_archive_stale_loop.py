"""ArchiveStaleLoop（web 常驻自动归档）口径测试.

覆盖: 到期判定（无状态/未到期/到期/状态损坏 fail-open）、禁用开关
（显式 False + 环境变量总关闭 + PYTEST_CURRENT_TEST 守卫）、端到端线程
（归档 + 指针清理 + 状态落盘 + 重启不重复跑）、单轮异常写错误态不外抛。
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

from llm_loop.core.session import SessionStore
from llm_loop.timekeeping import system_local_now
from llm_loop.workspace.archive_stale import ArchiveStaleLoop


def _make_session(data_dir: Path, *, age: timedelta, title: str = "旧会话") -> str:
    part = data_dir / "sessions"
    part.mkdir(parents=True, exist_ok=True)
    store = SessionStore(part, identity_root=data_dir / "sessions")
    sid = store.create()
    p = part / f"{sid}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["updated_at"] = (system_local_now() - age).isoformat(timespec="microseconds")
    data["title"] = title
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return sid


def _status(data_dir: Path, sid: str) -> str:
    p = data_dir / "sessions" / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8"))["status"]


def test_due_logic_from_state_file(tmp_path):
    loop = ArchiveStaleLoop(tmp_path, enabled=True)
    now = system_local_now()
    assert loop.is_due(now) is True  # 无状态 → 到期
    loop.save_state(last_run=now, next_due=now + timedelta(hours=1), summary={"counts": {}})
    assert loop.is_due(now) is False  # next_due 在未来 → 未到期
    assert loop.is_due(now + timedelta(hours=2)) is True  # 越过 next_due → 到期
    loop.state_path.write_text("{broken json", encoding="utf-8")
    assert loop.is_due(now) is True  # 状态损坏视为无状态（fail-open 补跑）


def test_disabled_by_env_and_pytest_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_ARCHIVE_STALE_AUTO", "0")
    assert ArchiveStaleLoop(tmp_path).enabled is False  # 环境变量总关闭
    monkeypatch.setenv("LFL_ARCHIVE_STALE_AUTO", "1")
    loop = ArchiveStaleLoop(tmp_path)  # enabled=None：pytest 守卫下仍自禁用
    assert loop.enabled is False
    loop.run()  # 立即返回，不产生任何状态/报告
    assert not loop.state_path.exists()
    assert not (tmp_path / "reports").exists()


def test_auto_loop_archives_and_persists_state(tmp_path):
    data_dir = tmp_path / "data"
    sid = _make_session(data_dir, age=timedelta(days=6))
    store = SessionStore(data_dir / "sessions", identity_root=data_dir / "sessions")
    store.set_shared_current(sid)

    loop = ArchiveStaleLoop(
        data_dir, days=5, tick_s=3600.0, initial_delay_s=0.0, enabled=True,
    )
    loop.start()
    try:
        for _ in range(200):  # 最多 10s：首轮应在毫秒级完成
            if loop.state_path.exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("自动归档未在 10s 内完成首轮")
    finally:
        loop.stop()
        loop.join(timeout=5)

    assert _status(data_dir, sid) == "archived"
    assert store.get_shared_current() is None  # 指针清理口径与 CLI 一致
    state = json.loads(loop.state_path.read_text(encoding="utf-8"))
    assert state["summary"]["counts"]["archived"] == 1
    assert state["summary"]["exit_code"] == 0
    assert state["days"] == 5
    # 重启语义：next_due 在未来 → 新循环实例不再到期（不重复跑）
    again = ArchiveStaleLoop(data_dir, days=5, enabled=True)
    assert again.is_due() is False


def test_run_once_due_records_error_without_raising(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"  # conftest isolated_data_dir 已建好并隔离 DATA_DIR
    import llm_loop.workspace.archive_stale as mod

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "run_archive_stale", _boom)
    loop = ArchiveStaleLoop(data_dir, days=5, enabled=True)
    summary = loop.run_once_due()  # 异常被吞，记入状态
    assert summary is not None and "RuntimeError: boom" in summary["error"]
    state = json.loads(loop.state_path.read_text(encoding="utf-8"))
    assert "RuntimeError" in state["summary"]["error"]
    assert loop.run_once_due() is None  # 错误也占用一个周期，不重试风暴
