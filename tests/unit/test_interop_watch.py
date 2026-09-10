"""协调 inbox 主动感知测试（EVO-20260817-6efeb7a0）.

覆盖: 首轮基线不刷屏 / 新消息通知 / 去重 / coordinate wakeup 触发与限频 /
notify 类不触发 wakeup / 坏文件 fail-open。
"""

from __future__ import annotations

import json
import time
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
    # notify 类永不触发（即使限频已过——模拟重置限频；与时钟原点解耦）
    w._last_wakeup = time.monotonic() - w._wakeup_min_interval - 1.0
    _write(inbox, "e.json", topic="notify")
    w.poll_once()
    assert len(wakeups) == 1
    # 限频过后 coordinate 再次触发
    w._last_wakeup = time.monotonic() - w._wakeup_min_interval - 1.0
    _write(inbox, "f.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 2


def test_wakeup_first_fire_regardless_of_uptime(tmp_path, monkeypatch):
    """回归(2026-09-10 CI): uptime < 限频窗的机器首条 coordinate 必须唤醒.

    旧实现 _last_wakeup 哨兵 0.0 与 time.monotonic()（原点=开机时刻）耦合：
    GitHub runner 每作业全新 VM，pytest 时 uptime 常 < 300s → 首轮唤醒被
    静默限频（CI 掷硬币红绿）。冻结时钟=10s 直接编码该场景。
    """
    import time as _time
    import types

    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    wakeups: list[list[str]] = []
    monkeypatch.setattr(
        "llm_loop.core.interop_watch.time",
        types.SimpleNamespace(
            monotonic=lambda: 10.0,  # 冻结 uptime=10s < 300s
            time=_time.time,  # startup_cleanup/backlog 仍走真实墙钟
        ),
    )
    w = _watcher(
        inbox,
        wakeup_enabled=True,
        wakeup_fn=lambda n: wakeups.append(n),
        wakeup_min_interval_s=300,
    )
    w.poll_once()  # 基线
    _write(inbox, "u.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 1  # uptime=10s < 300s，首条仍须唤醒
    # 同一冻结时钟内限频仍生效（不重复唤醒）
    _write(inbox, "v.json", topic="coordinate")
    w.poll_once()
    assert len(wakeups) == 1


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


# ── EVO-20260825 任务9（§5.4）: 启动巡检清理 + pending 堆积告警 ──


def _write_full(inbox: Path, name: str, *, topic: str, ts: float) -> None:
    (inbox / name).write_text(
        json.dumps(
            {"id": name, "topic": topic, "status": "pending", "body": "x", "ts": ts}
        ),
        encoding="utf-8",
    )


def test_startup_cleanup_moves_stale_job_sched(tmp_path, monkeypatch):
    """任务9.1（§5.4.1-3）: 启动巡检迁移超过 TTL 的 job/sched 到 pending/processed/.

    近 TTL 内的消息保留；非 job/sched（coordinate）不清理（协议消息待消费）。"""
    import time

    import llm_loop.core.interop_watch as iw

    monkeypatch.setattr(iw, "_PENDING_TTL_HOURS", 24.0)
    monkeypatch.setattr(iw, "_PENDING_CLEANUP_ON_START", True)
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    now = time.time()
    _write_full(inbox, "old-job.json", topic="job", ts=now - 48 * 3600)
    _write_full(inbox, "old-sched.json", topic="sched", ts=now - 50 * 3600)
    _write_full(inbox, "recent-job.json", topic="job", ts=now - 3600)
    _write_full(inbox, "coord.json", topic="coordinate", ts=now - 100 * 3600)

    _watcher(inbox)._startup_cleanup()

    assert not (inbox / "old-job.json").exists(), "过期 job 应迁移出 pending/"
    assert not (inbox / "old-sched.json").exists(), "过期 sched 应迁移出 pending/"
    proc = inbox / "processed"
    assert any(p.name == "old-job.json" for p in proc.rglob("*.json"))
    assert any(p.name == "old-sched.json" for p in proc.rglob("*.json"))
    assert (inbox / "recent-job.json").exists(), "近 TTL 内消息保留待消费"
    assert (inbox / "coord.json").exists(), "非 job/sched 消息不参与启动清理"


def test_pending_backlog_warns(tmp_path, monkeypatch, caplog):
    """任务9.2（§5.4.1-2）: pending 堆积超上限 → WARN（去抖：超限期间仅告警一次）."""
    import llm_loop.core.interop_watch as iw

    monkeypatch.setattr(iw, "_PENDING_MAX", 3)
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    for i in range(5):
        _write(inbox, f"m{i}.json")
    w = _watcher(inbox)
    with caplog.at_level("WARNING", logger="llm_loop.core.interop_watch"):
        w.poll_once()
        w.poll_once()
    assert any("pending 堆积" in r.message for r in caplog.records), "超限应 WARN"
    assert sum("pending 堆积" in r.message for r in caplog.records) == 1, "去抖：仅告警一次"


def test_pending_backlog_blocked_diagnosis(tmp_path, monkeypatch, caplog):
    """任务9.2: 堆积超 2× 上限 → 附加"消费疑似阻塞"诊断（含最新文件龄）."""
    import llm_loop.core.interop_watch as iw

    monkeypatch.setattr(iw, "_PENDING_MAX", 2)
    inbox = tmp_path / "pending"
    inbox.mkdir(parents=True)
    for i in range(6):
        _write(inbox, f"n{i}.json")
    w = _watcher(inbox)
    with caplog.at_level("WARNING", logger="llm_loop.core.interop_watch"):
        w.poll_once()
    assert any("消费疑似阻塞" in r.message for r in caplog.records)
