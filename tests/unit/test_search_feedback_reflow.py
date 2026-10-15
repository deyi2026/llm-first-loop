"""TASK-ac085ab1-003 P1 查询回流: 短卡反馈注释 + 三侧端到端（method/experience/rule）.

验收（设计草案 v3 P1 行）: 任务 A 反馈落账后，任务 B 首次相关查询能读到该反馈
——对 Method、经验、规则三者分别成立；保留精确读取与继续检索能力；反馈注释
不改规则排序与权威。全部 tmp 隔离夹具。
"""

from __future__ import annotations

import hashlib

from llm_loop.event_log.store import EventStore
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.settlement import (
    RuleFeedbackProjection,
    SettlementItem,
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
    "## 其他\n\n"
    "非规则配置节。\n"
)


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "回流夹具经验",
        "scenario": "场景",
        "root_cause": "",
        "solution": "解法（当前性验证：先 grep -n 解法关键字 src/ 确认仍适用）",
        "evidence": "",
        "tags": [],
        "source": {},
    }
    fields.update(overrides)
    return ExperienceDocument(**fields)


# ── method 侧：任务A落账 → 任务B首次查询可见 ──


def test_end_to_end_method_feedback_reflow_to_next_task_query(tmp_path):
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="reflow method", description="reflow fixture", body=_CONTRACT_BODY,
    )
    ref = record.method_ref
    version = store.get(ref).content_hash
    events = EventStore(tmp_path / "events")

    # 任务 A：结算落账（applied + helped）
    receipt = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="applied", benefit="helped",
                read_version=version, note="短路径减少了返工",
            )
        ],
        method_store=store, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    assert receipt["counts"]["committed"] == 1

    # 任务 B：首次相关查询（发现查询）
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=store)
    rows = searcher.search(kind="method", query="reflow", session_id="sess-B")
    assert rows
    row = rows[0]
    assert row["key"] == ref
    assert row["usage_net"] == 1  # 声明净分可见（注明为声明口径）
    assert row["benefit_counts"]["helped"] == 1  # 分项反馈可见
    assert row["feedback_version_state"] == "current"
    assert row["read_entry"] == ref  # 当前版本与读取入口
    assert row["feedback_watermark"] >= 1

    # 任务 B：精确读取入口仍可用
    exact = searcher.search(kind="method", query=ref, session_id="sess-B")
    assert exact and exact[0].get("hydrated") is not None or exact[0]["content_hash"]


def test_end_to_end_method_negative_feedback_recent_issue_visible(tmp_path):
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="mislead method", description="misleading fixture", body=_CONTRACT_BODY,
    )
    ref = record.method_ref
    events = EventStore(tmp_path / "events")
    submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=ref, decision="rejected", benefit="hindered",
                note="Trigger 与任务不符，走了弯路",
            )
        ],
        method_store=store, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    # 第二个工作单元再次 rejected → 净分 -2 触发既有 threshold_alert 机制
    submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="rejected", benefit="hindered")],
        method_store=store, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A2", episode_ref="episode:sess-A:2:bb",
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=store)
    rows = searcher.search(kind="method", query="mislead", session_id="sess-B")
    row = rows[0]
    assert row["usage_net"] == -2
    assert row["usage_net_detail"] == "a0/n0/r2"
    assert row["recent_issue"] == "Trigger 与任务不符，走了弯路"  # 近因问题摘要
    assert row["pending_disposition"] is True  # 净分告警仍由既有机制触发


def test_method_feedback_marks_stale_after_card_edit(tmp_path):
    """卡片正文修订后：旧反馈保留原版本归属，不冒充当前版本评价."""
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="stale method", description="stale fixture", body=_CONTRACT_BODY,
    )
    ref = record.method_ref
    events = EventStore(tmp_path / "events")
    submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision="applied", benefit="helped")],
        method_store=store, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    # 修订同一张卡正文 → content_hash 变化（旧反馈保留原版本归属）
    method_md = next((tmp_path / "methods" / record.method_id).glob("METHOD.md"))
    method_md.write_text(
        method_md.read_text(encoding="utf-8").replace(
            "description: stale fixture", "description: stale fixture revised"
        ),
        encoding="utf-8",
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=store)
    rows = searcher.search(kind="method", query="stale", session_id="sess-B")
    assert rows
    assert rows[0]["key"] == ref
    assert rows[0]["feedback_version_state"] == "stale_after_card_edit"


# ── experience 侧 ──


def test_end_to_end_experience_feedback_reflow_to_next_task_query(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(_make_doc(title="经验回流夹具"))
    stem = filename.removesuffix(".md")
    ref = f"experience:{stem}"
    version = hashlib.sha256(store.get(stem).to_md().encode("utf-8")).hexdigest()
    events = EventStore(tmp_path / "events")

    receipt = submit_settlement_batch(
        items=[
            SettlementItem(
                kind="experience", ref=ref, decision="adapted", benefit="neutral",
                read_version=version, note="原场景与本次场景差异较大",
            )
        ],
        method_store=None, experience_store=store, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    assert receipt["counts"]["committed"] == 1

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    rows = searcher.search(kind="experience", query="回流", session_id="sess-B")
    assert rows
    row = rows[0]
    assert row["key"] == ref
    assert row["usage_net"] == 1
    assert row["benefit_counts"]["neutral"] == 1
    assert row["read_entry"] == ref

    # 精确读取入口仍可用（hydrated）
    exact = searcher.search(kind="experience", query=ref, session_id="sess-B")
    assert exact and exact[0].get("hydrated") is True


def test_experience_lesson_side_keeps_reflow(tmp_path):
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(
        _make_doc(title="教训回流夹具", record_kind="lesson", verification_state="unverified")
    )
    stem = filename.removesuffix(".md")
    ref = f"experience:{stem}"
    events = EventStore(tmp_path / "events")
    submit_settlement_batch(
        items=[SettlementItem(kind="lesson", ref=ref, decision="not_applicable", benefit="mixed")],
        method_store=None, experience_store=store, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    rows = searcher.search(kind="lesson", query="教训", session_id="sess-B")
    assert rows
    assert rows[0]["benefit_counts"]["mixed"] == 1


# ── rule 侧：EventStore 投影注释通道 ──


def test_end_to_end_rule_feedback_reflow_to_next_task_query(tmp_path):
    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    events = EventStore(tmp_path / "events")
    events_dir = tmp_path / "events"

    # 任务 A：规则执行反馈落账（EventStore 回执）
    submit_settlement_batch(
        items=[
            SettlementItem(
                kind="rule", ref="RULE-AI-18", decision="applied", benefit="helped",
                note="按稳定 ref 读取，避免重复检索", read_version="rv1",
            )
        ],
        method_store=None, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A",
    )

    # 任务 B：首次相关查询（精确水合）
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        rule_path=rules,
        rule_feedback_projection=RuleFeedbackProjection(events_dir),
    )
    rows = searcher.search(kind="rule", query="RULE-AI-18", session_id="sess-B")
    assert rows and rows[0].get("hydrated") is True
    row = rows[0]
    assert row["rule_feedback_count"] == 1
    assert row["rule_feedback_watermark"]
    assert row["rule_feedback_source"] == "eventstore_projection"
    assert row["authority"] == "rule_sot"  # 规则权威不被反馈改变

    # 任务 B：宽查询短卡同样携带注释，且不改排序（无注释行保持原序在前）
    broad = searcher.search(kind="rule", query="检索 留痕", session_id="sess-B")
    assert broad
    assert broad[0]["rule_ref"] == "RULE-AI-18"


def test_rule_annotation_channel_is_absent_without_projection_or_feedback(tmp_path):
    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    EventStore(tmp_path / "events")  # 空 event_logs_dir：无反馈无读取

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", rule_path=rules)
    rows = searcher.search(kind="rule", query="RULE-AI-29", session_id="sess-B")
    assert rows and rows[0].get("hydrated") is True
    assert "rule_feedback_count" not in rows[0]  # 无投影 → 零行为

    with_projection = RecordSearcher(
        audit_dir=tmp_path / "audit",
        rule_path=rules,
        rule_feedback_projection=RuleFeedbackProjection(tmp_path / "events"),
    )
    rows2 = with_projection.search(kind="rule", query="RULE-AI-29", session_id="sess-B")
    assert "rule_feedback_count" not in rows2[0]  # 无反馈无读取 → 不附加字段


def test_rule_pending_count_visible_when_read_but_not_settled(tmp_path):
    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    events = EventStore(tmp_path / "events")

    sink_calls: list[dict] = []

    def sink(payload: dict) -> None:
        sink_calls.append(dict(payload))
        events.append(payload["session_id"], "knowledge.read", payload)

    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        rule_path=rules,
        knowledge_read_sink=sink,
        rule_feedback_projection=RuleFeedbackProjection(tmp_path / "events"),
    )
    searcher.search(kind="rule", query="RULE-AI-18", session_id="sess-B")  # 读取
    assert sink_calls  # 打点到达事件流

    rows = searcher.search(kind="rule", query="检索 留痕", session_id="sess-B")
    row = next(r for r in rows if r["rule_ref"] == "RULE-AI-18")
    assert row["rule_pending_count"] == 1  # 读到未回记 → pending 对模型可见


# ── 保留继续检索能力 ──


def test_reflow_annotation_does_not_break_normal_search_surfaces(tmp_path):
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="surface method", description="surface fixture", body=_CONTRACT_BODY,
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=store)
    # 空查询列表、宽词发现、精确水合三条面都保持既有形态
    assert isinstance(searcher.search(kind="method", query="", session_id="s"), list)
    assert isinstance(searcher.search(kind="method", query="surface", session_id="s"), list)
    exact = searcher.search(kind="method", query=record.method_ref, session_id="s")
    assert exact and exact[0]["projection_complete"] is True


# ── 模型可见渲染（工具层 run_search_records）──


def test_model_visible_rendering_carries_feedback_and_rule_channel(tmp_path):
    from llm_loop.core.message import ToolResultStatus
    from llm_loop.introspection.tools_status import run_search_records

    rules = tmp_path / "ai_rules.md"
    rules.write_text(_RULES_MD, encoding="utf-8")
    events = EventStore(tmp_path / "events")

    # method 侧落账
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="render method", description="render fixture", body=_CONTRACT_BODY,
    )
    submit_settlement_batch(
        items=[
            SettlementItem(
                kind="method", ref=record.method_ref, decision="applied",
                benefit="helped", note="渲染验证",
            )
        ],
        method_store=store, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A", episode_ref="episode:sess-A:1:aa",
    )
    # rule 侧落账 + 一次未回记读取
    submit_settlement_batch(
        items=[
            SettlementItem(
                kind="rule", ref="RULE-AI-18", decision="applied", benefit="helped",
                note="按 ref 读取", read_version="rv1",
            )
        ],
        method_store=None, experience_store=None, event_store=events,
        session_id="sess-A", work_unit_id="TASK-A",
    )

    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit",
        method_store=store,
        rule_path=rules,
        rule_feedback_projection=RuleFeedbackProjection(tmp_path / "events"),
    )
    class _Adapter:
        def __call__(self, **kw):
            return searcher.search(**kw)

        @property
        def last_diagnostics(self):
            return getattr(searcher, "last_diagnostics", None)

    result = run_search_records(
        None, _Adapter(), {"kind": "method", "query": "render", "limit": 5},
        lambda: "sess-B",
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "benefit=helped×1" in result.content  # 分项反馈模型可见
    assert "usage_net=+1" in result.content
    # TASK-fdc7603b-001 B 线：净分展示必须标注"声明净分"（设计草案 v3 :22）
    assert "（声明净分，非独立验证）" in result.content

    rule_result = run_search_records(
        None, _Adapter(), {"kind": "rule", "query": "RULE-AI-18", "limit": 5},
        lambda: "sess-B",
    )
    assert rule_result.status is ToolResultStatus.SUCCESS
    assert "rule_feedback[feedback_count=1" in rule_result.content
    # TASK-fdc7603b-001 C 线：渲染披露双水位（feedback_watermark + indexed_watermark）
    assert "feedback_watermark=" in rule_result.content
    assert "indexed_watermark=" in rule_result.content
    assert "authority=rule_sot" in rule_result.content  # 权威标注保留


def test_legacy_fallback_net_annotation_is_labeled_declared_net(tmp_path):
    """TASK-fdc7603b-001 B 线：无 usage_feedback 的旧 store 走 search.py 回退净分
    注释路径（_annotate_usage → usage_net → row_annotation），渲染同样标注
    "声明净分"——两条渲染路径口径一致。"""
    from llm_loop.introspection.tools_status import _usage_net_part

    class _LegacyStore:
        """无 usage_feedback 属性的旧 store 形态（仅有 usage_net）。"""

        def usage_net(self, ref):  # noqa: ARG002
            return {
                "net": 2, "applied": 2, "not_applicable": 0, "rejected": 0,
                "unrecognized": 0, "anchor": "ledger_full", "disproven": False,
            }

    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=_LegacyStore())
    rows = searcher._annotate_usage(
        [{"key": "method:legacy-x", "kind": "method", "summary": "legacy",
          "status": "active", "ts": ""}],
        side="method",
    )
    assert rows[0]["usage_net"] == 2  # 回退路径仍附净分字段
    assert rows[0]["usage_net_detail"] == "a2/n0/r0"
    part = _usage_net_part(rows[0])
    assert "usage_net=+2 [a2/n0/r0]" in part
    assert "声明净分" in part  # legacy 回退路径同样明确声明净分口径
