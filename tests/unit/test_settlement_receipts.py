"""TASK-ac085ab1-002 P0 模型收尾: knowledge_read 打点、待结算清单、批量结算回执.

设计来源: docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3（待结算清单的
生成机制 / 幂等键与重复结算 / 收尾可靠性与操作成本）。全部 tmp 隔离夹具。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from llm_loop.event_log.store import EventStore
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.settlement import (
    KNOWLEDGE_READ_EVENT_TYPE,
    RULE_FEEDBACK_EVENT_TYPE,
    RuleFeedbackProjection,
    SettlementItem,
    build_pending_settlement,
    submit_settlement_batch,
)
from llm_loop.methods.store import MethodStore

_CONTRACT_BODY = (
    "## Trigger\nneed the known-good path\n\n"
    "## Discriminator\ntask matches the recorded scenario\n\n"
    "## Short path\nread -> apply -> verify\n\n"
    "## Stop conditions\nverification fails or evidence missing\n\n"
    "## Verification\npytest green\n\n"
    "## Counterexamples\nSSR page\n"
)

_RULES_MD = (
    "# Rules\n\n"
    "## RULE-AI-18 检索留痕\n\n"
    "检索知识库须留痕并按稳定 ref 读取。\n\n"
    "## RULE-AI-29 反馈\n\n"
    "任务收尾须回记使用反馈。\n\n"
    "## 其他节\n\n"
    "不是规则。\n"
)


def _method_store(tmp_path: Path) -> tuple[MethodStore, str]:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="settlement fixture method", description="settlement fixture",
        body=_CONTRACT_BODY,
    )
    return store, record.method_ref


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "结算夹具经验",
        "scenario": "场景",
        "root_cause": "",
        "solution": "解法（当前性验证：先 grep -n 解法关键字 src/ 确认仍适用）",
        "evidence": "",
        "tags": [],
        "source": {},
    }
    fields.update(overrides)
    return ExperienceDocument(**fields)


def _experience_store(tmp_path: Path) -> tuple[ExperienceStore, str]:
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(_make_doc())
    return store, filename.removesuffix(".md")


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, payload: dict) -> None:
        self.events.append(dict(payload))


def _searcher(
    tmp_path: Path,
    *,
    method_store=None,
    experience_store=None,
    sink=None,
    rule_projection=None,
    rule_path: Path | None = None,
) -> RecordSearcher:
    return RecordSearcher(
        audit_dir=tmp_path / "audit",
        method_store=method_store,
        experience_store=experience_store,
        rule_path=rule_path,
        knowledge_read_sink=sink,
        rule_feedback_projection=rule_projection,
    )


# ── knowledge_read 打点：精确水合成功路径 ──


def test_exact_method_hydration_emits_knowledge_read_with_same_snapshot_version(tmp_path):
    store, ref = _method_store(tmp_path)
    sink = _Sink()
    searcher = _searcher(tmp_path, method_store=store, sink=sink)
    rows = searcher.search(kind="method", query=ref, session_id="sess-1")

    assert rows and rows[0]["content_hash"]
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["kind"] == "method"
    assert event["ref"] == ref
    # 版本哈希取自构成本次回执的同一份内容快照
    assert event["version"] == rows[0]["content_hash"]
    assert event["session_id"] == "sess-1"
    assert event["semantics"] == "exact_content_returned_to_caller"


def test_broad_method_query_does_not_emit_knowledge_read(tmp_path):
    store, ref = _method_store(tmp_path)
    sink = _Sink()
    searcher = _searcher(tmp_path, method_store=store, sink=sink)
    searcher.search(kind="method", query="settlement fixture", session_id="sess-1")

    assert sink.events == []  # 泛查询不打点


def test_exact_experience_hydration_emits_knowledge_read(tmp_path):
    store, stem = _experience_store(tmp_path)
    sink = _Sink()
    searcher = _searcher(tmp_path, experience_store=store, sink=sink)
    rows = searcher.search(kind="experience", query=f"experience:{stem}", session_id="sess-1")

    assert rows
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["kind"] in {"experience", "lesson"}
    assert event["ref"] == f"experience:{stem}"
    doc = store.get(stem)
    assert event["version"] == hashlib.sha256(doc.to_md().encode("utf-8")).hexdigest()


def test_exact_rule_hydration_emits_knowledge_read(tmp_path):
    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    sink = _Sink()
    searcher = _searcher(tmp_path, sink=sink, rule_path=rules)
    rows = searcher.search(kind="rule", query="RULE-AI-18", session_id="sess-1")

    assert rows and rows[0].get("hydrated") is True
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["kind"] == "rule"
    assert event["ref"] == "RULE-AI-18"
    assert event["version"] == hashlib.sha256(
        rows[0]["content"].encode("utf-8")
    ).hexdigest()


def test_broad_rule_query_does_not_emit_knowledge_read(tmp_path):
    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    sink = _Sink()
    searcher = _searcher(tmp_path, sink=sink, rule_path=rules)
    searcher.search(kind="rule", query="反馈 收尾", session_id="sess-1")

    assert sink.events == []


# ── 待结算清单 = 读取事件 − 持久化结算回执 ──


def _emit_read(event_store: EventStore, session: str, *, kind: str, ref: str, version: str) -> None:
    event_store.append(
        session,
        KNOWLEDGE_READ_EVENT_TYPE,
        {
            "schema": "knowledge-read/v1",
            "kind": kind,
            "ref": ref,
            "version": version,
            "session_id": session,
            "run": "run-1",
            "semantics": "exact_content_returned_to_caller",
        },
    )


def test_pending_list_is_reads_minus_receipts_by_triple(tmp_path):
    method_store, ref = _method_store(tmp_path)
    experience_store, stem = _experience_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash
    exp_version = hashlib.sha256(experience_store.get(stem).to_md().encode()).hexdigest()
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)
    _emit_read(events, "sess-1", kind="experience", ref=f"experience:{stem}", version=exp_version)

    pending = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=experience_store,
        session_id="sess-1",
        work_unit_id="TASK-A",
    )
    items = {(i["kind"], i["ref"]) for i in pending["items"]}
    assert items == {("method", ref), ("experience", f"experience:{stem}")}
    assert pending["attribution"] == "task(TASK-A)"
    assert "不覆盖" in pending["coverage_boundary"]  # 自带覆盖边界声明

    # 结算 method 条目后重查：method 不再 pending，experience 仍在
    receipt = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="applied", benefit="helped",
                read_version=version, note="有效",
            )
        ],
        method_store=method_store,
        experience_store=experience_store,
        event_store=events,
        session_id="sess-1",
        work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )
    assert receipt["counts"]["committed"] == 1

    pending_after = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=experience_store,
        session_id="sess-1",
        work_unit_id="TASK-A",
    )
    items_after = {(i["kind"], i["ref"]) for i in pending_after["items"]}
    assert items_after == {("experience", f"experience:{stem}")}


def test_pending_list_none_is_presented_in_two_columns(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")

    pending = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=None,
        session_id="sess-1",
        work_unit_id="TASK-A",
    )

    assert pending["items"] == []
    assert pending["none_columns"]["event_source_no_contact"] is True
    assert pending["none_columns"]["model_self_reported_no_contact"] is False
    # 两列语义分开呈现：事件源无接触 ≠ 模型自报无接触
    assert "event_source_no_contact" in pending["none_columns"]


def test_pending_list_falls_back_to_tool_trace_when_events_missing(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")  # 无 knowledge_read 事件
    trace = [
        {
            "name": "search_records",
            "arguments": {"kind": "method", "query": ref},
            "status": "success",
        },
        {
            "name": "search_records",
            "arguments": {"kind": "method", "query": "broad keywords"},
            "status": "success",
        },
    ]

    pending = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=None,
        session_id="sess-1",
        work_unit_id="TASK-A",
        tool_trace=trace,
    )

    assert pending["read_source"] == "tool_trace_non_authoritative"
    assert pending["items"]
    assert pending["items"][0]["read_version"] == "unknown"
    assert pending["items"][0]["source"] == "tool_trace_non_authoritative"


def test_pending_list_attribution_degrades_to_session_window(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)

    pending = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=None,
        session_id="sess-1",
    )

    assert pending["attribution"] == "degraded(session)"


# ── 批量结算逐条回执 ──


def test_batch_settlement_per_item_receipts_committed_and_failed(tmp_path):
    method_store, ref = _method_store(tmp_path)
    experience_store, stem = _experience_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash

    receipt = submit_settlement_batch(
        items=[
            SettlementItem(kind="method", ref=ref, decision="applied", benefit="helped", read_version=version),
            SettlementItem(kind="method", ref="method:missing", decision="applied"),
            SettlementItem(kind="experience", ref=f"experience:{stem}", decision="not_applicable", benefit="neutral"),
        ],
        method_store=method_store,
        experience_store=experience_store,
        event_store=events,
        session_id="sess-1",
        work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )

    statuses = [r["status"] for r in receipt["receipts"]]
    assert statuses[0] == "committed"
    assert statuses[1] == "failed"  # ref 不存在 → failed + 原因，其余条目继续
    assert "reason" in receipt["receipts"][1]
    assert statuses[2] == "committed"
    assert receipt["counts"] == {"committed": 2, "pending": 0, "failed": 1}
    first = receipt["receipts"][0]
    assert first["slot_id"] and first["submission_hash"] and first["revision"] == 1
    assert "ledger_watermark" in first


def test_batch_retry_same_content_folds_into_existing_receipt(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    items = [
        SettlementItem(
            kind="method", ref=ref, decision="applied", benefit="helped",
                note="retry me",
        )
    ]
    first = submit_settlement_batch(
        items=items, method_store=method_store, experience_store=None,
        event_store=events, session_id="sess-1", work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )
    second = submit_settlement_batch(
        items=items, method_store=method_store, experience_store=None,
        event_store=events, session_id="sess-1", work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )
    assert second["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True  # 同内容重试返回同一回执
    assert second["receipts"][0]["submission_hash"] == first["receipts"][0]["submission_hash"]
    lines = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert lines.count("\n") == 1


def test_unknown_write_result_returns_pending_with_lookup_hint(tmp_path, monkeypatch):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    from llm_loop.methods.store import MethodCommitUncertainError

    def _raise_uncertain(*args, **kwargs):
        raise MethodCommitUncertainError(
            "durability fence failed", method_ref=ref, operation="record_use",
            expected_sha256="x", visible_state="matches",
        )

    monkeypatch.setattr(method_store, "record_use", _raise_uncertain)

    receipt = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied")],
        method_store=method_store, experience_store=None,
        event_store=events, session_id="sess-1", work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )

    assert receipt["receipts"][0]["status"] == "pending"  # 未知 ≠ 失败 ≠ 成功
    assert "submission_hash" in receipt["receipts"][0]["hint"]


def test_settlement_call_and_round_counts_enter_receipt(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    base = dict(
        method_store=method_store, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A",
        episode_ref="episode:sess-1:1:aa",
    )
    first = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", note="n1")], **base,
    )
    assert first["settlement_calls"] == 1
    assert first["settlement_rounds"] == 0  # 无 run 绑定时回合数如实为 0

    second = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="adapted", note="n2")],
        run_id="run-2", **base,
    )
    assert second["settlement_calls"] == 2  # 本工作单元第 2 次结算调用
    third = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", note="n3")],
        run_id="run-2", **base,
    )
    assert third["settlement_calls"] == 3
    assert third["settlement_rounds"] == 1  # 同 run 内多次结算仍计 1 个回合占用


def test_unresolved_attribution_receipt_does_not_offset_definite_task(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)

    # 降级窗口（无工作单元）先结算 → 回执标 attribution=unresolved
    degraded = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", read_version=version)],
        method_store=method_store, experience_store=None,
        event_store=events, session_id="sess-1", episode_ref="episode:sess-1:1:aa",
    )
    assert degraded["attribution"] == "degraded(session)"
    assert degraded["receipts"][0]["status"] == "committed"

    pending = build_pending_settlement(
        event_store=events,
        method_store=method_store,
        experience_store=None,
        session_id="sess-1",
        work_unit_id="TASK-B",  # 确定任务：不抵扣
    )
    assert any(i["ref"] == ref for i in pending["items"])  # 仍未结算


def test_cross_task_receipt_does_not_offset_other_task(tmp_path):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)
    submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", read_version=version)],
        method_store=method_store, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A", episode_ref="episode:sess-1:1:aa",
    )
    pending_b = build_pending_settlement(
        event_store=events, method_store=method_store, experience_store=None,
        session_id="sess-1", work_unit_id="TASK-B",
    )
    assert any(i["ref"] == ref for i in pending_b["items"])  # A 的回执不能满足 B


def test_self_reported_item_validates_ref_and_fails_with_reason(tmp_path):
    method_store, ref = _method_store(tmp_path)
    experience_store, _stem = _experience_store(tmp_path)
    events = EventStore(tmp_path / "events")
    receipt = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="not_applicable",
                self_reported=True, note="模型自报条目",
            ),
            SettlementItem(
                kind="experience", ref="experience:ghost", decision="applied",
                self_reported=True,
            ),
        ],
        method_store=method_store, experience_store=experience_store, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A", episode_ref="episode:sess-1:1:aa",
    )
    assert receipt["receipts"][0]["status"] == "committed"
    assert method_store.usage_entries(ref)[-1].get("self_reported") is True
    assert receipt["receipts"][1]["status"] == "failed"
    assert "self_reported" in receipt["receipts"][1]["reason"]


# ── 规则侧 EventStore 回执与投影 ──


def test_rule_feedback_settles_to_eventstore_and_dedupes(tmp_path):
    events = EventStore(tmp_path / "events")
    items = [
        SettlementItem(
            kind="rule", ref="RULE-AI-18", decision="applied", benefit="helped",
            note="触发并遵守", read_version="v1",
        )
    ]
    first = submit_settlement_batch(
        items=items, method_store=None, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    second = submit_settlement_batch(
        items=items, method_store=None, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    assert first["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True

    rule_events = [
        e for e in events.read("sess-1") if e.type == RULE_FEEDBACK_EVENT_TYPE
    ]
    assert len(rule_events) == 1  # 去重后只落一条
    payload = rule_events[0].payload
    assert payload["ref"] == "RULE-AI-18"
    assert payload["slot_id"] and payload["submission_hash"]
    assert payload["attribution"] == "task(TASK-A)"


def test_rule_feedback_counts_offset_pending_reads(tmp_path):
    events = EventStore(tmp_path / "events")
    _emit_read(events, "sess-1", kind="rule", ref="RULE-AI-18", version="v1")
    pending = build_pending_settlement(
        event_store=events, method_store=None, experience_store=None,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    assert any(i["ref"] == "RULE-AI-18" for i in pending["items"])
    submit_settlement_batch(
        items=[SettlementItem(kind="rule", ref="RULE-AI-18", decision="applied", read_version="v1")],
        method_store=None, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    pending_after = build_pending_settlement(
        event_store=events, method_store=None, experience_store=None,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    assert not any(i["ref"] == "RULE-AI-18" for i in pending_after["items"])


def test_rule_feedback_projection_aggregates_receipts_and_pending(tmp_path):
    events = EventStore(tmp_path / "events")
    _emit_read(events, "sess-1", kind="rule", ref="RULE-AI-18", version="v1")
    submit_settlement_batch(
        items=[
            SettlementItem(
                kind="rule", ref="RULE-AI-18", decision="applied", benefit="hindered",
                note="触发条件与任务不符", read_version="v1",
            )
        ],
        method_store=None, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    _emit_read(events, "sess-1", kind="rule", ref="RULE-AI-29", version="v2")

    projection = RuleFeedbackProjection(tmp_path / "events")
    data18 = projection("RULE-AI-18")
    assert data18["rule_feedback_count"] == 1
    assert data18["rule_recent_issue"] == "触发条件与任务不符"
    assert data18["rule_pending_count"] == 0
    assert data18["rule_feedback_watermark"]  # 反馈水位非空

    data29 = projection("RULE-AI-29")
    assert data29["rule_feedback_count"] == 0
    assert data29["rule_pending_count"] == 1  # 读到未回记 → pending

    assert projection("RULE-AI-99") is None  # 无反馈无读取 → 不附加字段


def test_rule_feedback_projection_reads_segment_layout(tmp_path):
    events = EventStore(tmp_path / "events")
    _emit_read(events, "sess-2", kind="rule", ref="RULE-AI-18", version="v1")
    # 直接写一个多段布局文件（<sid>/<seq>.jsonl）
    seg_dir = tmp_path / "events" / "sess-3"
    seg_dir.mkdir(parents=True)
    (seg_dir / "1.jsonl").write_text(
        json.dumps(
            {
                "event_id": "e1", "session_id": "sess-3", "seq": 1,
                "type": RULE_FEEDBACK_EVENT_TYPE,
                "ts": "2026-10-15T00:00:00",
                "payload": {"ref": "RULE-AI-18", "submission_hash": "h1", "slot_id": "s1",
                            "decision": "applied", "benefit": "helped", "note": ""},
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    projection = RuleFeedbackProjection(tmp_path / "events")
    data = projection("RULE-AI-18")
    assert data["rule_feedback_count"] == 1
    assert data["rule_pending_count"] == 1  # sess-2 的读取未回记


# ── P1 修复回归（独立审查回执 20261015-ac085ab1 REQUEST_CHANGES）──


def test_unattributed_method_tasks_do_not_collapse_into_one_slot_chain(tmp_path):
    """P1-1：wu/episode 皆空时不伪造 episode 哨兵，不并入同一伪 slot 修订链.

    审查探针 P2/P2b/P2c 场景：两个不同 session、wu 与 episode 皆空、不同
    提交内容，旧行为把它们并入同一 ``episode:unset`` 伪 slot（revision=2、
    互为 supersedes、链头统计塌缩为 1）。
    """
    method_store, ref = _method_store(tmp_path)
    events_a = EventStore(tmp_path / "events-a")
    events_b = EventStore(tmp_path / "events-b")
    version = method_store.get(ref).content_hash

    first = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="applied", benefit="helped",
                read_version=version, note="任务甲的评价",
            )
        ],
        method_store=method_store, experience_store=None, event_store=events_a,
        session_id="sess-a",
    )
    second = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="applied", benefit="hindered",
                read_version=version, note="任务乙的评价",
            )
        ],
        method_store=method_store, experience_store=None, event_store=events_b,
        session_id="sess-b",
    )

    assert first["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["status"] == "committed"
    # 显式 unresolved 路径：slot=''，不伪造 slot 身份
    assert first["receipts"][0]["slot_id"] == ""
    assert second["receipts"][0]["slot_id"] == ""
    assert second["receipts"][0].get("idempotent") is not True
    assert second["receipts"][0]["revision"] == 1  # 不并入同一修订链

    raw = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert "episode:unset" not in raw  # 不伪造 episode 溯源
    entries = method_store.usage_entries(ref)
    assert len(entries) == 2
    for entry in entries:
        assert entry["work_unit_binding"] == "unresolved"
        assert entry["work_unit_id"] == ""
        assert entry["episode_ref"] == ""
        assert entry["slot_id"] == ""
        assert entry["revision"] == 1
        assert entry["supersedes"] == ""
    # 链头统计：两条无归属评价仍是两条，不塌缩为 1
    from llm_loop.use_ledger import dedupe_slot_heads

    assert len(dedupe_slot_heads(entries)) == 2


def test_experience_settlement_uses_episode_attribution_when_provided(tmp_path):
    """P1-2：显式提供 episode_ref 时 experience 侧落 episode 归属而非 unresolved.

    与 method 侧层级一致（显式 > episode 回退 > unresolved）；审查探针 P3 证实
    旧行为丢弃 episode_ref、直接落 binding=unresolved、slot=''。
    """
    experience_store, stem = _experience_store(tmp_path)
    events = EventStore(tmp_path / "events")

    receipt = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="experience", ref=f"experience:{stem}",
                decision="applied", benefit="helped",
            )
        ],
        method_store=None, experience_store=experience_store, event_store=events,
        session_id="sess-1", episode_ref="episode:sess-1:2:bb",
    )

    assert receipt["receipts"][0]["status"] == "committed"
    entry = experience_store.usage_entries(f"experience:{stem}")[-1]
    assert entry["work_unit_binding"] == "episode_fallback"
    assert entry["work_unit_id"] == "episode:sess-1:2:bb"
    assert entry["episode_ref"] == "episode:sess-1:2:bb"
    assert entry["slot_id"]  # 有归属即有 slot


def test_settled_count_counts_offset_unique_keys_not_read_events(tmp_path):
    """P1-3：settled_count 按唯一键计被抵扣数；重复读取事件不虚增已结算数.

    审查探针 P1 场景：同 key 3 次读取、零回执时旧行为 settled_count=2（读取
    事件数 − 待结算键数的单位混用），虚报 2 条已结算。
    """
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    version = method_store.get(ref).content_hash
    for _ in range(3):
        _emit_read(events, "sess-1", kind="method", ref=ref, version=version)

    pending = build_pending_settlement(
        event_store=events, method_store=method_store, experience_store=None,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    assert len(pending["items"]) == 1  # 同 key 3 次读取 → 1 个待结算键
    assert pending["settled_count"] == 0  # 零回执 ⇒ 不得报 settled=2

    submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", read_version=version)],
        method_store=method_store, experience_store=None, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A", episode_ref="episode:sess-1:1:aa",
    )
    settled_after = build_pending_settlement(
        event_store=events, method_store=method_store, experience_store=None,
        session_id="sess-1", work_unit_id="TASK-A",
    )
    assert settled_after["items"] == []
    assert settled_after["settled_count"] == 1  # 被抵扣的唯一键数 = 1（非 3）
