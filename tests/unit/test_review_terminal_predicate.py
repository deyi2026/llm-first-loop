"""EVO-20261108-13d53b9c：review_child 终态事件谓词（审查完成即唤醒）。

review_admission 异步审查 child 此前无法绑定 schedule 事件唤醒（subject_refs
封闭集无 review_child），父会话只能墙钟轮询——2026-11-08 实测 50 分钟漏查
status 与 25 连续 wait 零 status 两次事故。本谓词把 job_terminal 同款机制
平移到审查 child：child 进入 settled（PASS/REVISE/失败终态）即触发唤醒。
"""
from __future__ import annotations

from llm_loop.core.scheduler import EVENT_PREDICATE_KINDS
from llm_loop.factory import review_terminal_predicate
from llm_loop.tools.review_host_admission import HostReviewAdmission, _Frozen


def _authority_with(*rows: _Frozen) -> HostReviewAdmission:
    authority = HostReviewAdmission()
    for row in rows:
        authority._records[row.child_id] = row  # noqa: SLF001 — 测试装配
    return authority


def test_review_terminal_in_closed_kind_set():
    assert "review_terminal" in EVENT_PREDICATE_KINDS


def test_review_terminal_predicate_settled_vs_running():
    running = _Frozen(
        kind="full_test", parent="p1", target="t1", sha="a" * 64,
        child_id="child-r1", state="running",
    )
    settled = _Frozen(
        kind="full_test", parent="p1", target="t2", sha="b" * 64,
        child_id="child-s1", state="settled",
    )
    authority = _authority_with(running, settled)

    assert review_terminal_predicate("child-r1", _authority=authority) is False, "running 不得唤醒"
    assert review_terminal_predicate("child-s1", _authority=authority) is True, "settled 必须唤醒"
    assert review_terminal_predicate("child-unknown", _authority=authority) is False, "未知 child fail-safe"


def test_no_authority_fails_safe_not_settled():
    """P1-1（合并审查 2026-11-08）：全局未装配 HostReviewAdmission 时
    review_terminal 必须 fail-safe 判 False（不误唤醒），恒真断言已修。"""
    saved = HostReviewAdmission.current()
    try:
        HostReviewAdmission.set_authority(None)
        assert review_terminal_predicate("child-any", _authority=None) is False, (
            "无 authority（装配缺失）必须 fail-safe=False，不得唤醒"
        )
    finally:
        HostReviewAdmission.set_authority(saved)


def test_current_authority_hook_roundtrip():
    saved = HostReviewAdmission.current()
    try:
        authority = HostReviewAdmission()
        HostReviewAdmission.set_authority(authority)
        assert HostReviewAdmission.current() is authority
        # snapshot_child_state：未知 child → None（不误判 settled）
        assert authority.snapshot_child_state("nope") is None
    finally:
        HostReviewAdmission.set_authority(saved)


def test_schedule_accepts_review_child_subject_type():
    from llm_loop.tools.builtin.schedule import _SUBJECT_REF_TYPES

    assert "review_child" in _SUBJECT_REF_TYPES
