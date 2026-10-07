"""EVO-20261007-8057c39a: grant_lost_owner_dead 立即降级 + 可再锚定 payload。

2026-10-07 双 sid 实证：grant 丢失（owner 会话进程已死）且 ledger 恢复失败是
确定性终态，6 次瞬态退避（~30 分钟）无一自愈。新语义：立即降级为通知并携带
原始调度规格，供下一会话 re-issue schedule。
"""

import json
from types import SimpleNamespace

from llm_loop.core.schedule_delivery import ScheduleWakeDelivery
from llm_loop.core.scheduler import ScheduleStore


def test_owner_dead_degrades_immediately_without_transient_backoff(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.json")
    sid = store.add(
        "复查 evolution 执行状态",
        after=0,
        wake=True,
        session_id="dead-owner-session",
    )
    records: list[tuple] = []
    delivery = ScheduleWakeDelivery(
        store,
        SimpleNamespace(),
        data_dir=str(tmp_path),
        record_action=lambda *args: records.append(args),
    )

    entry = store.claim_due("engine-owner-dead")[0]
    outcome = delivery(entry)

    # degrade 返回 True → 调用方 mark_triggered 消费条目（终态语义不变）。
    assert outcome is True
    row = store.list()[0]
    assert row["wake_started_at"] == 0
    # 关键断言：未写任何退避状态（旧行为会写 wake_wait_reason=grant_lost_owner_dead
    # 并递增 retry_count 走 6 轮退避）。
    assert not row.get("wake_wait_reason")
    assert row.get("retry_count", 0) == 0
    assert row.get("wake_delivery_state") != "waiting_human"

    # 降级通知走 interop LFL inbox（_notify_via_interop 的落盘路径），
    # 下一 run 读取 pending 投影回显；此处直接断言落盘 payload。
    notify_files = list(
        (tmp_path / "interop" / "lfl_to_dsh" / "pending").glob("*.json")
    )
    assert len(notify_files) == 1
    payload = json.loads(notify_files[0].read_text(encoding="utf-8"))
    assert payload["wake_degraded_reason"] == "grant_lost_owner_dead"
    reanchor = payload["wake_degraded_payload"]
    assert reanchor["sid"] == sid
    assert reanchor["session_id"] == "dead-owner-session"
    assert reanchor["reason"] == "grant_lost_owner_dead"
    assert reanchor["message"] == "复查 evolution 执行状态"
    assert "trigger_at" in reanchor
    assert "repeat_interval" in reanchor
    assert "max_count" in reanchor
    assert any(r[1] == "degraded_to_notify" for r in records)
