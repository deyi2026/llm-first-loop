"""超预算拒绝回执的「可复制分批计划」（2026-11-02 实测需求）.

背景：一次 34 提交的 git_push 审查，冻结 material 达 813k 字符，
`reviewer_duration_precheck` 在 est≈7974s > 3600s 直接拒绝，回执只有
"narrow it with scope=patch paths=[...]"，操作者只能手工猜 paths 拆了 5 批
（约 1.5 小时）。本改动只让回执可执行——**仍然拒绝**，不新增任何放行面。

这里锁四件事：
1. 装箱不丢段、不重段、保序；
2. 每批 est ≤ ceiling（oversized 段单独成批并标注）；
3. 拒绝回执仍 `accepted=False`，并带 `split_plan` 与可复制的 paths 文本；
4. 没有段落视图时（如 article_publish）不给计划——不伪造。
"""

from __future__ import annotations

from typing import cast

from llm_loop.tools.review_host_admission import (
    _SPLIT_PLAN_MAX_BATCHES,
    HostReviewAdmission,
    _split_plan,
    _split_plan_tail,
    _split_plan_text,
)


def _sections(*pairs: tuple[str, int]) -> list[tuple[str, int]]:
    return list(pairs)


def test_plan_keeps_every_section_once_and_in_order() -> None:
    sections = _sections(
        ("committed:a.py", 100), ("committed:b.py", 100),
        ("working:c.py", 100), ("untracked:d.txt", 100),
    )
    plan = _split_plan(sections, ceiling_chars=250)
    packed = [path for item in plan for path in item["paths"]]
    assert packed == ["a.py", "b.py", "c.py", "d.txt"]  # 保序、不丢、不重
    assert [item["batch"] for item in plan] == [1, 2]  # 贪心：250+250


def test_each_batch_within_ceiling_except_flagged_oversized() -> None:
    sections = _sections(
        ("committed:small.py", 120), ("committed:huge.py", 900),
        ("committed:tail.py", 120),
    )
    plan = _split_plan(sections, ceiling_chars=300)
    assert [item["oversized"] for item in plan] == [False, True, False]
    for item in plan:
        if not item["oversized"]:
            assert item["est_chars"] <= 300
    assert plan[1]["paths"] == ["huge.py"]


def test_plan_caps_batch_count_instead_of_overpacking() -> None:
    sections = _sections(*[(f"committed:f{i}.py", 200) for i in range(40)])
    plan = _split_plan(sections, ceiling_chars=200)  # 每段自成一档
    assert len(plan) == _SPLIT_PLAN_MAX_BATCHES
    assert all(item["est_chars"] <= 200 for item in plan)


def test_plan_text_is_copy_pasteable() -> None:
    plan = _split_plan(_sections(("committed:a.py", 100)), ceiling_chars=300)
    text = _split_plan_text(plan)
    assert "batch1" in text
    assert "paths=['a.py']" in text
    assert "est=100chars" in text


class _Stub:
    """只需要 _audit_reviewer_unavailable + _plan_tail 的替身：不碰 runner/记录."""

    _plan_tail = staticmethod(_split_plan_tail)

    def _audit_reviewer_unavailable(self, *args, **kwargs) -> None:
        return None


def test_duration_refusal_still_refuses_and_carries_plan() -> None:
    sections = _sections(("committed:a.py", 400_000), ("committed:b.py", 413_000))
    estimated, deadline, refusal = HostReviewAdmission._duration_gate(
        cast("HostReviewAdmission", _Stub()), "parent", "git_push", 813_000, sections
    )
    assert estimated > 3600 and deadline > 0
    assert refusal is not None
    # 仍然拒绝：这条改动只让回执可执行，不产生任何放行
    assert refusal["accepted"] is False
    assert refusal["reviewer_failure"] == "reviewer_duration_precheck"
    assert "qualification" not in refusal
    plan = refusal["split_plan"]
    assert [item["paths"] for item in plan] == [["a.py"], ["b.py"]]
    assert "paths=['a.py']" in refusal["reason"]
    assert "全部 PASS 才构成该项资格" in refusal["reason"]


def test_refusal_without_sections_does_not_fabricate_plan() -> None:
    receipt = HostReviewAdmission._duration_gate(
        cast("HostReviewAdmission", _Stub()), "parent", "git_push", 813_000, None
    )[2]
    assert receipt is not None and receipt["accepted"] is False
    assert "split_plan" not in receipt
    assert "split_plan" not in receipt["reason"]
