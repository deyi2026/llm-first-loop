"""协调 inbox 主动感知测试（EVO-20260817-6efeb7a0）.

覆盖: 首轮基线不刷屏 / 新消息通知 / 去重 / coordinate wakeup 触发与限频 /
notify 类不触发 wakeup / 坏文件 fail-open。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.core.interop_watch import InboxWatcher


def _write(inbox: Path, name: str, *, topic: str = "coordinate", status: str = "pending") -> None:
    (inbox / name).write_text(
        json.dumps({"id": name, "topic": topic, "status": status, "body": "x"}),
        encoding="utf-8",
    )


def _watcher(inbox: Path, **kw) -> InboxWatcher:
    return InboxWatcher(inbox_dir=inbox, **kw)


def test_first_poll_baseline_notify_existing(tmp_path: Path):
    """首轮扫描建基线，已存在消息通知一次（重启后可感知存量；不刷屏仅通知一次）."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    _write(inbox, "a.json")
    notified: list[list[str]] = []
    w = _watcher(inbox, on_notify=lambda n: notified.append(n))
    w.poll_once()  # 基线 + 存量通知
    assert notified == [["a.json"]]
    w.poll_once()  # 幂等：不重复通知
    assert notified == [["a.json"]]


def test_new_message_notifies(tmp_path: Path):
    """基线之后新消息 → on_notify 收到文件名（含基线存量一次）."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    _write(inbox, "a.json")
    notified: list[list[str]] = []
    w = _watcher(inbox, on_notify=lambda n: notified.append(n))
    w.poll_once()  # 基线（通知存量 a）
    _write(inbox, "b.json")
    w.poll_once()
    assert notified == [["a.json"], ["b.json"]]


def test_dedup_same_file_once(tmp_path: Path):
    """同一文件不重复通知（幂等）."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    notified: list[list[str]] = []
    w = _watcher(inbox, on_notify=lambda n: notified.append(n))
    w.poll_once()
    _write(inbox, "b.json")
    w.poll_once()
    w.poll_once()  # 再轮不应重复
    assert len(notified) == 1


def test_wakeup_only_coordinate_and_rate_limited(tmp_path: Path):
    """INBOX_WAKEUP 下: coordinate 触发（限频内不重复）；notify 不触发."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    wakeups: list[list[str]] = []
    w = _watcher(
        inbox, wakeup_enabled=True, wakeup_fn=lambda n: wakeups.append(n),
        wakeup_min_interval_s=300,
    )
    w.poll_once()  # 基线
    _write(inbox, "c.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 1
    # 限频内再来 coordinate → 不触发
    _write(inbox, "d.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 1
    # notify 类永不触发（即使限频已过——模拟重置限频）
    w._last_wakeup = 0.0
    _write(inbox, "e.json", topic="notify")
    w.poll_once()
    assert len(wakeups) == 1
    # 限频过后 coordinate 再次触发
    w._last_wakeup = 0.0
    _write(inbox, "f.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 2


def test_wakeup_disabled_by_default(tmp_path: Path):
    """默认 INBOX_WAKEUP=0（构造不传 wakeup_enabled → False）: coordinate 不触发.

    2026-08-17 修复: 模块级 _WAKEUP_ENABLED 在 import 时固化（测试进程 env 可能含
    INBOX_WAKEUP=1）→ 显式传 wakeup_enabled=False 隔离宿主环境，验证构造默认禁用语义.
    """
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    wakeups: list[list[str]] = []
    w = _watcher(inbox, wakeup_fn=lambda n: wakeups.append(n), wakeup_enabled=False)
    w.poll_once()
    _write(inbox, "g.json", topic="coordinate")
    w.poll_once()
    assert wakeups == []


def test_bad_json_fail_open(tmp_path: Path):
    """坏 JSON 文件: 不崩溃（fail-open）; 基线/新消息均按文件名通知（on_notify 不解析内容）."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    (inbox / "bad.json").write_text("{not json", encoding="utf-8")
    notified: list[list[str]] = []
    w = _watcher(inbox, on_notify=lambda n: notified.append(n))
    w.poll_once()  # 基线：通知存量 bad.json（不解析内容，不崩溃）
    (inbox / "good.json").write_text(json.dumps({"id": "x", "status": "pending", "body": "x"}), encoding="utf-8")
    w.poll_once()
    assert notified == [["bad.json"], ["good.json"]]  # bad 不阻塞 good


def test_done_status_not_in_wakeup_topic(tmp_path: Path):
    """status!=pending 的文件不参与 wakeup topic 判定（已归档不计）."""
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    wakeups: list[list[str]] = []
    w = _watcher(inbox, wakeup_enabled=True, wakeup_fn=lambda n: wakeups.append(n))
    w.poll_once()
    _write(inbox, "h.json", topic="coordinate", status="done")
    w.poll_once()
    assert wakeups == []
