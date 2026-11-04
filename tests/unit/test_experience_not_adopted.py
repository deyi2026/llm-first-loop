"""EVO-20261104-e5f79db8: experience 侧第三态 not_adopted + 采纳证据强制 +
「声明净分 / 独立核验净分」分离。

三条契约锚定：
1. use_decision 增加 not_adopted（卡适用且正确、但本轮未执行），计 0 分，
   与 not_applicable（卡不适用）、rejected（卡错误引导）三义分离；
2. applied/adapted 必须附非空 evidence_refs（采纳证据强制），否则落账失败；
3. usage_net 同时给出声明净分（net/net_declared）与独立核验净分（net_verified，
   只计 evidence_level=independently_evaluated 的声明）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.settlement import SettlementItem, submit_settlement_batch
from llm_loop.methods.store import MethodStore
from llm_loop.usage_net import detail, row_annotation, summarize_since_last_transition

_CONTRACT_BODY = (
    "## Trigger\nneed the known-good path\n\n"
    "## Discriminator\ntask matches the recorded scenario\n\n"
    "## Short path\nread -> apply -> verify\n\n"
    "## Stop conditions\nverification fails or evidence missing\n\n"
    "## Verification\npytest green\n\n"
    "## Counterexamples\nSSR page\n"
)


def _experience_store(tmp_path: Path) -> tuple[ExperienceStore, str]:
    store = ExperienceStore(tmp_path / "experiences")
    doc = ExperienceDocument(
        title="not_adopted 夹具经验",
        scenario="场景",
        root_cause="",
        solution="解法",
        evidence="",
        tags=[],
        source={},
    )
    filename = store.save(doc)
    return store, filename.removesuffix(".md")


def _summarize(entries: list[dict], *, disproven: bool = False) -> dict:
    # 夹具补 status=active：summarize 按 current_status 重锚，缺 status 会被截断。
    entries = [{"status": "active", **e} for e in entries]
    return summarize_since_last_transition(
        entries,
        decision_key="use_decision",
        status_key="status",
        current_status="active",
        disproven=disproven,
    )


# ── 契约 2：采纳证据强制 ──


def test_applied_without_evidence_refs_is_rejected(tmp_path: Path) -> None:
    store, stem = _experience_store(tmp_path)
    with pytest.raises(ValueError, match="采纳证据强制"):
        store.record_use(stem, use_decision="applied")
    with pytest.raises(ValueError, match="采纳证据强制"):
        store.record_use(stem, use_decision="adapted", evidence_refs=["   "])


def test_applied_with_evidence_refs_marks_application_proven(tmp_path: Path) -> None:
    store, stem = _experience_store(tmp_path)
    entry = store.record_use(stem, use_decision="applied", evidence_refs=["episode:s1:1:aa"])
    assert entry["application_proven"] is True
    assert entry["evidence_refs"] == ["episode:s1:1:aa"]


def test_not_adopted_needs_no_evidence_refs(tmp_path: Path) -> None:
    """第三态本质是"没执行"，不该被采纳证据强制反向逼出假引用。"""
    store, stem = _experience_store(tmp_path)
    entry = store.record_use(stem, use_decision="not_adopted", note="卡正确，本轮未走到该路径")
    assert entry["use_decision"] == "not_adopted"
    assert entry["application_proven"] is False
    assert entry["evidence_refs"] == []


def test_unknown_decision_still_rejected(tmp_path: Path) -> None:
    store, stem = _experience_store(tmp_path)
    with pytest.raises(ValueError, match="use_decision must be one of"):
        store.record_use(stem, use_decision="skipped", evidence_refs=["episode:x"])


# ── 契约 1+3：净分语义 ──


def test_not_adopted_counts_zero_and_is_not_unrecognized() -> None:
    entries = [
        {"use_decision": "applied", "evidence_level": "model_declared"},
        {"use_decision": "not_adopted"},
        {"use_decision": "not_adopted"},
        {"use_decision": "rejected"},
    ]
    summary = _summarize(entries)
    assert summary["applied"] == 1
    assert summary["rejected"] == 1
    assert summary["not_adopted"] == 2
    assert summary["unrecognized"] == 0
    assert summary["net"] == 0
    assert summary["net_declared"] == summary["net"]


def test_detail_renders_not_adopted_only_when_present() -> None:
    with_neutral = _summarize([{"use_decision": "applied"}, {"use_decision": "not_adopted"}])
    without_neutral = _summarize([{"use_decision": "applied"}])
    assert detail(with_neutral) == "a1/n0/r0/d1"
    assert detail(without_neutral) == "a1/n0/r0"


def test_net_verified_only_counts_independent_evidence() -> None:
    entries = [
        {"use_decision": "applied", "evidence_level": "independently_evaluated"},
        {"use_decision": "applied", "evidence_level": "model_declared"},
        {"use_decision": "not_applicable", "evidence_level": "independently_evaluated"},
        {"use_decision": "not_adopted"},
    ]
    summary = _summarize(entries)
    assert summary["net"] == 1  # 声明净分：applied 2 - not_applicable 1
    assert summary["verified_entries"] == 2
    assert summary["net_verified"] == 0  # 独立核验：1 - 1
    annotation = row_annotation(summary)
    assert annotation["usage_net"] == 1
    assert annotation["usage_net_verified"] == 0
    assert annotation["usage_net_verified_n"] == 2
    assert annotation["usage_not_adopted"] == 1


def test_row_annotation_omits_verified_when_no_independent_evidence() -> None:
    summary = _summarize([{"use_decision": "applied", "evidence_level": "model_declared"}])
    annotation = row_annotation(summary)
    assert "usage_net_verified" not in annotation
    assert "usage_not_adopted" not in annotation


# ── 契约 1：settlement 侧 per-kind 门 ──


def _method_store(tmp_path: Path) -> tuple[MethodStore, str]:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="not_adopted fixture method",
        description="fixture",
        body=_CONTRACT_BODY,
    )
    return store, record.method_ref


def test_settlement_rejects_not_adopted_for_method(tmp_path: Path) -> None:
    method_store, method_ref = _method_store(tmp_path)
    receipt = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=method_ref, decision="not_adopted")],
        method_store=method_store,
        experience_store=None,
        event_store=EventStore(tmp_path / "events"),
        session_id="sess-1",
        episode_ref="episode:sess-1:1:aa",
    )
    item = receipt["receipts"][0]
    assert item["status"] == "failed"
    assert "仅对 kind=experience 有效" in item["reason"]


def test_settlement_accepts_not_adopted_for_experience(tmp_path: Path) -> None:
    store, stem = _experience_store(tmp_path)
    receipt = submit_settlement_batch(
        items=[SettlementItem(kind="experience", ref=f"experience:{stem}", decision="not_adopted")],
        method_store=None,
        experience_store=store,
        event_store=EventStore(tmp_path / "events"),
        session_id="sess-1",
        episode_ref="episode:sess-1:1:aa",
    )
    assert receipt["receipts"][0]["status"] == "committed"


def test_settlement_applied_without_refs_fails_with_guidance(tmp_path: Path) -> None:
    store, stem = _experience_store(tmp_path)
    receipt = submit_settlement_batch(
        items=[SettlementItem(kind="experience", ref=f"experience:{stem}", decision="applied")],
        method_store=None,
        experience_store=store,
        event_store=EventStore(tmp_path / "events"),
        session_id="sess-1",
        episode_ref="episode:sess-1:1:aa",
    )
    item = receipt["receipts"][0]
    assert item["status"] == "failed"
    assert "not_adopted" in item["reason"]
