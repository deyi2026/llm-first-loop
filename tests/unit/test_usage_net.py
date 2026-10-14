"""EVO-20261014-7299aec2: usage_net 净分派生视图（record_use 审计）单元测试.

覆盖预埋口径 D1-D3 的实现锚定与两个落点（命中行注记 / 回执告警段）的渲染层。
"""
from __future__ import annotations

from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.tools_status import _render_experience_record, _usage_net_part
from llm_loop.methods.store import MethodStore
from llm_loop.usage_net import (
    ALERT_NET_THRESHOLD,
    alert_section,
    breached,
    row_annotation,
    signed_net,
    summarize_since_last_transition,
)

_CONTRACT_BODY = (
    "## Trigger\n"
    "need the known-good path\n\n"
    "## Discriminator\n"
    "task matches the recorded scenario\n\n"
    "## Short path\n"
    "read -> apply -> verify\n\n"
    "## Stop conditions\n"
    "verification fails or evidence missing\n\n"
    "## Verification\n"
    "pytest green\n\n"
    "## Counterexamples\n"
    "SSR page\n"
)


# ── 纯函数：D1 机械汇总 / D2 分项 / D3 尾段锚点 ──


def _entries(*specs: tuple[str, str]) -> list[dict]:
    """(status, decision) 序列，newest-first 由调用方排列。"""
    return [{"status": s, "use_decision": d} for s, d in specs]


def test_d1_mechanical_scores_and_unverified_applied_counts_plus_one() -> None:
    summary = summarize_since_last_transition(
        _entries(("active", "applied"), ("active", "adapted"), ("active", "not_applicable"), ("active", "rejected")),
        decision_key="use_decision",
        status_key="status",
        current_status="active",
    )
    assert summary["net"] == 0  # +1 +1 -1 -1（RULE-AI-31 计分表）
    assert (summary["applied"], summary["not_applicable"], summary["rejected"]) == (2, 1, 1)
    assert summary["anchor"] == "lifecycle_status(active)"
    assert summary["disproven"] is False


def test_d1_disproven_is_correction_trigger_not_reweight() -> None:
    summary = summarize_since_last_transition(
        _entries(("active", "applied")),
        decision_key="use_decision",
        status_key="status",
        current_status="active",
        disproven=True,
    )
    assert summary["net"] == 1  # 净分不按验证态加权
    assert breached(summary) is True  # disproven 单独触发（D1 纠偏）
    assert alert_section("experience", "experience:x", summary).startswith("[threshold_alert]")


def test_d3_trailing_status_match_reanchors_at_last_transition() -> None:
    # newest-first：最后两条 archived，更早三条 active——只累计 archived 段
    summary = summarize_since_last_transition(
        _entries(("archived", "applied"), ("archived", "rejected"), ("active", "rejected"), ("active", "rejected"), ("active", "applied")),
        decision_key="use_decision",
        status_key="status",
        current_status="archived",
    )
    assert summary["net"] == 0
    assert (summary["applied"], summary["rejected"]) == (1, 1)
    assert summary["anchor"] == "lifecycle_status(archived)"


def test_d3_current_status_empty_falls_back_to_full_ledger() -> None:
    summary = summarize_since_last_transition(
        _entries(("active", "rejected"), ("active", "rejected")),
        decision_key="use_decision",
        status_key="status",
        current_status="",
    )
    assert summary["net"] == -2
    assert summary["anchor"] == "ledger_full"


def test_d2_threshold_and_disposition_semantics() -> None:
    single = summarize_since_last_transition(
        _entries(("active", "not_applicable")),
        decision_key="use_decision",
        status_key="status",
        current_status="active",
    )
    assert single["net"] == -1 and breached(single) is False  # 单次不触阈值
    # not_applicable 与 rejected 同计 -1：累计 ≤ -2 都触发提醒（RULE-AI-31 第 3 条）
    neutral_negative = summarize_since_last_transition(
        _entries(("active", "not_applicable"), ("active", "not_applicable")),
        decision_key="use_decision",
        status_key="status",
        current_status="active",
    )
    assert neutral_negative["net"] == ALERT_NET_THRESHOLD and breached(neutral_negative) is True
    rejected_negative = summarize_since_last_transition(
        _entries(("active", "rejected"), ("active", "rejected")),
        decision_key="use_decision",
        status_key="status",
        current_status="active",
    )
    assert ALERT_NET_THRESHOLD == -2
    assert rejected_negative["net"] == ALERT_NET_THRESHOLD and breached(rejected_negative) is True
    assert signed_net(rejected_negative) == "-2"
    alert = alert_section("method", "method:x", rejected_negative)
    assert "a0/n0/r2" in alert  # 分项可见（D2）
    assert "不构成弃用依据" in alert  # not_applicable 语义区分进告警文案
    assert alert_section("method", "method:x", single) == ""


def test_row_annotation_omits_keys_without_entries() -> None:
    assert row_annotation(None) == {}
    assert row_annotation({"net": 3, "applied": 3, "not_applicable": 0, "rejected": 0}) == {
        "usage_net": 3,
        "usage_net_detail": "a3/n0/r0",
    }
    alerting = row_annotation({"net": -2, "applied": 0, "not_applicable": 0, "rejected": 2})
    assert alerting["pending_disposition"] is True


# ── MethodStore.usage_net 端到端（含 lifecycle 重锚） ──


def test_method_store_usage_net_and_reanchor_after_invalidation(tmp_path: Path) -> None:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(name="net view", description="trace producer", body=_CONTRACT_BODY)
    ref = record.method_ref

    assert store.usage_net(ref) is None  # 无声明 → None，调用方不附加字段
    assert store.usage_net("method:missing") is None

    store.record_use(ref, episode_ref="episode:e1", decision="rejected", note="n1")
    store.record_use(ref, episode_ref="episode:e2", decision="rejected", note="n2")
    store.record_use(ref, episode_ref="episode:e3", decision="applied", note="n3")
    before = store.usage_net(ref)
    assert before is not None
    assert before["net"] == -1  # -2 + 1（candidate 状态尾段累计）

    # 两条 rejected 来自 ≥2 episode → 独立处置依据成立，invalidated 允许
    invalidated = store.update_status(ref, "invalidated")
    assert invalidated.status == "invalidated"
    after = store.usage_net(ref)
    assert after is not None
    assert after["net"] == 0  # D3：transition 后旧累计不进入新锚点窗口
    assert after["anchor"] == "lifecycle_status(invalidated)"

    store.record_use(ref, episode_ref="episode:e4", decision="applied", note="n4")
    post = store.usage_net(ref)
    assert post is not None and post["net"] == 1  # 只累计 invalidated 之后的声明


# ── ExperienceStore.usage_net 端到端（含 disproven 触发与重锚） ──


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "净分视图",
        "scenario": "场景",
        "root_cause": "",
        "solution": "解法",
        "evidence": "",
        "tags": [],
        "source": {},
    }
    fields.update(overrides)
    return ExperienceDocument(**fields)


def test_experience_store_usage_net_alert_and_reanchor(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc())
    ref = f"experience:{filename}"

    store.record_use(filename, use_decision="rejected", note="n1", episode_ref="episode:e1")
    store.record_use(filename, use_decision="rejected", note="n2", episode_ref="episode:e2")

    summary = store.usage_net(ref)
    assert summary is not None
    assert summary["net"] == -2 and summary["disproven"] is False
    assert breached(summary) is True

    assert store.update_status(filename, "archived") is True
    reanchored = store.usage_net(ref)
    assert reanchored is not None
    assert reanchored["net"] == 0  # archived 后尾段为空
    assert reanchored["anchor"] == "lifecycle_status(archived)"

    store.record_use(filename, use_decision="not_applicable", note="n3", episode_ref="episode:e3")
    tail = store.usage_net(ref)
    assert tail is not None and tail["net"] == -1  # not_applicable 计 -1（RULE-AI-31）
    assert (tail["applied"], tail["not_applicable"], tail["rejected"]) == (0, 1, 0)


def test_experience_store_usage_net_disproven_current_doc_triggers(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "exp")
    filename = store.save(_make_doc(verification_state="disproven"))
    store.record_use(filename, use_decision="applied", note="n1", episode_ref="episode:e1")
    summary = store.usage_net(f"experience:{filename}")
    assert summary is not None
    assert summary["net"] == 1  # 未验证/被证伪的 applied 仍机械 +1（D1）
    assert summary["disproven"] is True and breached(summary) is True


# ── 渲染层：命中行 / 回执告警格式 ──


def test_render_usage_net_part_and_experience_thin_row() -> None:
    assert _usage_net_part({}) == ""
    part = _usage_net_part({"usage_net": 3, "usage_net_detail": "a4/n1/r0"})
    assert part == " | usage_net=+3 [a4/n1/r0]"
    breach_part = _usage_net_part({"usage_net": -2, "usage_net_detail": "a0/n0/r2", "pending_disposition": True})
    assert "usage_net=-2" in breach_part and "pending_disposition=true" in breach_part

    thin = _render_experience_record(
        {
            "kind": "experience",
            "summary": "标题",
            "experience_ref": "experience:doc-1.md",
            "status": "active",
            "record_kind": "experience",
            "verification_state": "unverified",
            "task_applicability": "not_evaluated",
            "scenario": "场景",
            "usage_net": 3,
            "usage_net_detail": "a4/n1/r0",
        },
        "experience",
    )
    assert "usage_net=+3 [a4/n1/r0]" in thin

    hydrated = _render_experience_record(
        {
            "kind": "experience",
            "summary": "标题",
            "experience_ref": "experience:doc-1.md",
            "status": "active",
            "hydrated": True,
            "usage_net": -2,
            "usage_net_detail": "a0/n0/r2",
            "pending_disposition": True,
        },
        "experience",
    )
    assert "usage_net=-2" in hydrated
    assert "pending_disposition=true" in hydrated


def test_alert_section_content_contract() -> None:
    summary = {"net": -3, "applied": 1, "not_applicable": 0, "rejected": 4, "unrecognized": 0,
               "anchor": "lifecycle_status(active)", "disproven": False}
    text = alert_section("method", "method:abc", summary)
    assert text.startswith("[threshold_alert] method method:abc")
    assert "a1/n0/r4" in text
    assert "处置决策仍归模型" in text
    assert "不构成弃用依据" in text
