"""DSH-PLUGINS-20260816 ②: schedule 工具 + 调度线程测试."""

from __future__ import annotations

import json
import time
from pathlib import Path

from llm_loop.core.scheduler import SchedulerThread, ScheduleStore
from llm_loop.tools.builtin.schedule import ScheduleTool


def _store(tmp_path: Path) -> ScheduleStore:
    return ScheduleStore(path=tmp_path / "schedule.json")


def test_schedule_after(tmp_path):
    """after 注册: 返回 sid + 持久化."""
    st = _store(tmp_path)
    sid = st.add("检查任务", after=60)
    assert sid.startswith("sched-")
    entries = st.list()
    assert len(entries) == 1
    assert entries[0]["message"] == "检查任务"
    assert entries[0]["trigger_at"] > time.time() + 50  # ~60s 后


def test_schedule_due_and_trigger(tmp_path):
    """到点触发: 单次删除."""
    st = _store(tmp_path)
    sid = st.add("立即提醒", after=0)
    due = st.due()
    assert len(due) == 1 and due[0].sid == sid
    st.mark_triggered(sid)
    assert st.list() == []  # 单次触发后删除


def test_schedule_repeat(tmp_path):
    """重复提醒: 按间隔重排直到 max_count."""
    st = _store(tmp_path)
    sid = st.add("周期汇报", after=0, repeat_interval=10, max_count=3)
    now = time.time()
    for i in range(3):
        due = st.due(now=now)  # 到点
        assert len(due) == 1
        st.mark_triggered(sid, now=now)
        if i < 2:
            assert len(st.list()) == 1  # 未达上限保留
        now += 10  # 推进一个周期
    assert st.list() == []  # 达上限删除


def test_schedule_persist_restart(tmp_path):
    """持久化: 新实例加载（模拟进程重启）."""
    p = tmp_path / "schedule.json"
    st1 = ScheduleStore(path=p)
    st1.add("重启保留", after=300)
    st2 = ScheduleStore(path=p)
    entries = st2.list()
    assert len(entries) == 1
    assert entries[0]["message"] == "重启保留"


def test_schedule_cancel(tmp_path):
    """取消提醒."""
    st = _store(tmp_path)
    sid = st.add("将被取消", after=60)
    assert st.cancel(sid) is True
    assert st.list() == []
    assert st.cancel(sid) is False  # 不存在


def test_schedule_tool_register(tmp_path):
    """工具层: after 注册成功回执."""
    tool = ScheduleTool(store=_store(tmp_path))
    r = tool.execute(message="60秒后提醒", after=60)
    assert r.status.value == "success"
    assert "已注册" in r.content and "sched-" in r.content


def test_schedule_tool_missing_message(tmp_path):
    """工具层: 缺 message 失败."""
    tool = ScheduleTool(store=_store(tmp_path))
    r = tool.execute(after=60)
    assert r.status.value == "failure"
    assert "缺少必填参数" in r.content


def test_schedule_tool_bad_at(tmp_path):
    """工具层: at 格式非法失败."""
    tool = ScheduleTool(store=_store(tmp_path))
    r = tool.execute(message="坏时间", at="not-a-time")
    assert r.status.value == "failure"
    assert "at 时间格式非法" in r.content


def test_scheduler_thread_notify(tmp_path):
    """线程: 到点触发写 interop notify 文件（协调通道定时化）."""

    import llm_loop.core.scheduler as mod

    # 用 tmp inbox 注入（monkeypatch 模块级 inbox 路径）
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    orig = mod.SchedulerThread._notify_via_interop

    def fake_notify(entry):
        (inbox / f"{entry.sid}.json").write_text(
            json.dumps({"sid": entry.sid, "body": entry.message}), encoding="utf-8"
        )

    st = ScheduleStore(path=tmp_path / "sched.json")
    sid = st.add("线程提醒", after=0)
    SchedulerThread._notify_via_interop = staticmethod(fake_notify)
    try:
        th = SchedulerThread(st, tick_interval=0.05)
        th.start()
        time.sleep(0.3)
        th.stop()
        files = list(inbox.iterdir())
        assert len(files) == 1
        assert json.loads(files[0].read_text(encoding="utf-8"))["sid"] == sid
        assert st.list() == []  # 触发后删除
    finally:
        SchedulerThread._notify_via_interop = orig


def test_multi_store_no_overwrite(tmp_path):
    """审查中危: 多实例（模拟多进程）add 不互相覆盖——修复前后写覆盖先写丢条目."""
    p = tmp_path / "schedule.json"
    s1 = ScheduleStore(p)
    s2 = ScheduleStore(p)  # 独立实例 = 模拟另一个进程
    sid1 = s1.add("proc1 提醒", after=60)
    sid2 = s2.add("proc2 提醒", after=120)
    # s1 重新加载（或另一实例）应看到两条
    s3 = ScheduleStore(p)
    assert s3.cancel(sid1) is True
    assert s3.cancel(sid2) is True, "s2 的条目被覆盖丢失（多进程覆盖 bug）"


def test_mark_triggered_persists_deletion(tmp_path):
    """审查中危: 触发删除后磁盘同步（不读回已删条目）."""
    p = tmp_path / "schedule.json"
    s = ScheduleStore(p)
    sid = s.add("立即", after=0)
    s.mark_triggered(sid)
    s2 = ScheduleStore(p)  # 重新加载
    assert s2.list() == []


def test_multi_store_mark_no_resurrect(tmp_path):
    """审查中危: 多实例场景触发删除不复活（磁盘删除语义跨实例一致）."""
    p = tmp_path / "schedule.json"
    s1 = ScheduleStore(p)
    s2 = ScheduleStore(p)
    sid = s1.add("立即", after=0)
    s1.mark_triggered(sid)
    s3 = ScheduleStore(p)
    assert s3.list() == [], "已删除条目被合并读回（resurrect）"


def test_schedule_cancel_tool(tmp_path):
    """审查 P2: schedule_cancel 工具可取消已注册提醒."""
    from llm_loop.tools.builtin.schedule import ScheduleCancelTool, ScheduleTool
    st = ScheduleTool(store=ScheduleStore(tmp_path / "s.json"))
    r = st.execute(message="测试提醒", after=60)
    assert r.status.value == "success"
    sid = r.content.split("已注册提醒 ")[1].split(":")[0]
    ct = ScheduleCancelTool(store=ScheduleStore(tmp_path / "s.json"))
    r2 = ct.execute(sid=sid)
    assert r2.status.value == "success" and "已取消" in r2.content
    r3 = ct.execute(sid=sid)
    assert r3.status.value == "failure" and "不存在" in r3.content
    r4 = ct.execute(sid="")
    assert r4.status.value == "failure" and "缺少必填" in r4.content
