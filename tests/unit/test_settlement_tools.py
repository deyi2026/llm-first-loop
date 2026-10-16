"""TASK-ac085ab1-004 受限结算通道工具面: settlement_pending / settlement_submit.

设计来源: docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3（「待结算清单的
生成机制」「幂等键与重复结算」「收尾可靠性与操作成本」）。工具层是薄适配，
语义断言对齐 test_settlement_receipts.py 的核心口径：
- 清单生成与回执抵扣（读取事件 → pending → 结算 → 抵扣）
- 自报条目校验失败回 failed（不静默丢弃）
- 批量部分成功（committed/failed 三分回执逐条呈现）
- 降级窗口标注（degraded(session) / unresolved 不抵扣确定任务）
- 通道缺件零行为（EventStore 关闭/会话不可归属 → 不伪造不落账）
- 规则条目路径（rule_lookup 存在性校验 + EventStore 回执去重）
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.config import Settings
from llm_loop.core.message import ToolResultStatus
from llm_loop.event_log.store import EventStore
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.rule_index import RuleIndex
from llm_loop.introspection.settlement import (
    KNOWLEDGE_READ_EVENT_TYPE,
    RULE_FEEDBACK_EVENT_TYPE,
    SettlementChannel,
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
    "任务收尾须回记使用反馈。\n"
)


def _method_store(tmp_path: Path) -> tuple[MethodStore, str]:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="settlement tool fixture method", description="settlement tool fixture",
        body=_CONTRACT_BODY,
    )
    return store, record.method_ref


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "结算工具夹具经验",
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


def _rule_lookup(tmp_path: Path):
    path = tmp_path / "ai_rules.md"
    path.write_text(_RULES_MD, encoding="utf-8")
    index = RuleIndex(path)
    return lambda ref: bool(index.search(str(ref), 1))


def _host(tmp_path: Path, *, rules: bool = False, audit_dir=None) -> CorrectionToolRegistry:
    """构造带结算通道的修正工具注册表（session 经 ctx 字段回退注入）."""
    ctx = CorrectionContext()
    ctx.session_id = "sess-1"
    events = EventStore(tmp_path / "events")
    method_store, _ref = _method_store(tmp_path)
    experience_store, _stem = _experience_store(tmp_path)
    ctx.settlement = SettlementChannel(
        event_store=events,
        method_store=method_store,
        experience_store=experience_store,
        rule_lookup=_rule_lookup(tmp_path) if rules else None,
        # P-SET-7 装配面：EventStore 同源目录——确定任务 slot 规则回执跨会话查重
        event_logs_dir=tmp_path / "events",
    )
    # audit_dir 是 Registry 层能力（krate_autorun 可观测性测试用），Context 不管落盘
    return CorrectionToolRegistry(ctx, audit_dir=audit_dir)


def _emit_read(events: EventStore, session: str, *, kind: str, ref: str, version: str) -> None:
    events.append(
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


def _payload(result) -> dict:
    """回执正文 = header 行（+成本观察行）+ JSON 载荷（末行）."""
    return json.loads(str(result.content).rsplit("\n", 1)[1])


# ── 待结算清单：生成与抵扣 ──


def test_pending_tool_lists_reads_then_offsets_after_settlement(tmp_path):
    host = _host(tmp_path)
    method_store, ref = _method_store(tmp_path)
    events = host.ctx.settlement.event_store
    version = method_store.get(ref).content_hash
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)

    result = host.execute("settlement_pending", {"work_unit_id": "TASK-A"})
    assert result.status == ToolResultStatus.SUCCESS
    assert "结算成本观察" in result.content  # 成本观察随清单回执
    pending = _payload(result)
    assert {(i["kind"], i["ref"]) for i in pending["items"]} == {("method", ref)}
    assert pending["attribution"] == "task(TASK-A)"
    assert "不覆盖" in pending["coverage_boundary"]  # 覆盖边界声明随回执

    settled = host.execute(
        "settlement_submit",
        {
            "work_unit_id": "TASK-A",
            "items": [
                {
                    "kind": "method", "ref": ref, "decision": "applied",
                    "benefit": "helped", "read_version": version, "note": "有效",
                }
            ],
        },
    )
    assert settled.status == ToolResultStatus.SUCCESS
    assert _payload(settled)["counts"]["committed"] == 1

    after = _payload(host.execute("settlement_pending", {"work_unit_id": "TASK-A"}))
    assert after["items"] == []  # 回执抵扣后清单清空
    assert after["settled_count"] == 1


def test_pending_tool_degraded_session_window_annotation(tmp_path):
    host = _host(tmp_path)
    method_store, ref = _method_store(tmp_path)
    _emit_read(
        host.ctx.settlement.event_store, "sess-1",
        kind="method", ref=ref, version=method_store.get(ref).content_hash,
    )

    result = host.execute("settlement_pending", {})
    assert result.status == ToolResultStatus.SUCCESS
    pending = _payload(result)
    assert pending["attribution"] == "degraded(session)"  # 缺 work_unit_id 降级标注


def test_pending_tool_self_reported_no_contact_two_columns(tmp_path):
    host = _host(tmp_path)

    result = host.execute(
        "settlement_pending", {"self_reported_no_contact": True}
    )
    pending = _payload(result)
    assert pending["none_columns"] == {
        "event_source_no_contact": True,
        "model_self_reported_no_contact": True,
    }


# ── 批量提交：三分回执 / 自报校验 / 部分成功 / 上限 ──


def test_submit_tool_partial_success_three_way_receipts(tmp_path):
    host = _host(tmp_path, rules=True)
    method_store, ref = _method_store(tmp_path)
    version = method_store.get(ref).content_hash

    result = host.execute(
        "settlement_submit",
        {
            "work_unit_id": "TASK-A",
            "items": [
                {
                    "kind": "method", "ref": ref, "decision": "applied",
                    "benefit": "helped", "read_version": version,
                },
                {"kind": "method", "ref": "method:missing", "decision": "applied"},
                {
                    "kind": "rule", "ref": "RULE-AI-18", "decision": "applied",
                    "benefit": "helped", "read_version": "v1",
                },
            ],
        },
    )
    assert result.status == ToolResultStatus.SUCCESS
    receipt = _payload(result)
    assert receipt["counts"] == {"committed": 2, "pending": 0, "failed": 1}
    statuses = [r["status"] for r in receipt["receipts"]]
    assert statuses == ["committed", "failed", "committed"]
    assert "reason" in receipt["receipts"][1]  # failed 条目给原因，不静默丢弃
    for row in (receipt["receipts"][0], receipt["receipts"][2]):
        assert row["slot_id"] and row["submission_hash"] and row["revision"] == 1
    assert receipt["settlement_calls"] >= 1  # 结算成本观察随回执
    assert "settlement_rounds" in receipt


def test_submit_tool_self_reported_missing_ref_fails_with_reason(tmp_path):
    host = _host(tmp_path)

    result = host.execute(
        "settlement_submit",
        {
            "work_unit_id": "TASK-A",
            "items": [
                {
                    "kind": "experience", "ref": "experience:ghost",
                    "decision": "applied", "self_reported": True,
                }
            ],
        },
    )
    # 零 committed → 工具层 FAILURE；逐条事实在 receipts 内
    assert result.status == ToolResultStatus.FAILURE
    receipt = _payload(result)
    assert receipt["receipts"][0]["status"] == "failed"
    assert "self_reported" in receipt["receipts"][0]["reason"]


def test_submit_tool_over_cap_rejects_whole_batch_without_truncation(tmp_path):
    host = _host(tmp_path)
    method_store, ref = _method_store(tmp_path)
    items = [
        {"kind": "method", "ref": ref, "decision": "applied"} for _ in range(33)
    ]

    result = host.execute("settlement_submit", {"work_unit_id": "TASK-A", "items": items})
    assert result.status == ToolResultStatus.FAILURE
    assert "超上限 32" in result.content
    assert "不截断" in result.content
    # 整批拒绝：不落任何账
    assert not (tmp_path / "methods" / "usage.jsonl").exists()


def test_submit_tool_empty_items_is_param_error(tmp_path):
    host = _host(tmp_path)

    result = host.execute("settlement_submit", {"items": []})
    assert result.status == ToolResultStatus.FAILURE
    assert "非空数组" in result.content


def test_submit_tool_unresolved_does_not_offset_definite_task(tmp_path):
    host = _host(tmp_path)
    method_store, ref = _method_store(tmp_path)
    events = host.ctx.settlement.event_store
    version = method_store.get(ref).content_hash
    _emit_read(events, "sess-1", kind="method", ref=ref, version=version)

    degraded = host.execute(
        "settlement_submit",
        {"items": [{"kind": "method", "ref": ref, "decision": "applied", "read_version": version}]},
    )
    assert degraded.status == ToolResultStatus.SUCCESS
    assert _payload(degraded)["attribution"] == "degraded(session)"

    pending = _payload(host.execute("settlement_pending", {"work_unit_id": "TASK-B"}))
    assert any(i["ref"] == ref for i in pending["items"])  # unresolved 不抵扣确定任务


def test_submit_tool_same_content_retry_is_idempotent(tmp_path):
    host = _host(tmp_path)
    method_store, ref = _method_store(tmp_path)
    args = {
        "work_unit_id": "TASK-A",
        "items": [{"kind": "method", "ref": ref, "decision": "applied", "note": "重试我"}],
    }

    first = _payload(host.execute("settlement_submit", args))
    second = _payload(host.execute("settlement_submit", args))
    assert second["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True
    assert (
        second["receipts"][0]["submission_hash"]
        == first["receipts"][0]["submission_hash"]
    )


# ── 规则条目路径 ──


def test_submit_tool_rule_item_settles_via_rule_lookup_and_dedupes(tmp_path):
    host = _host(tmp_path, rules=True)
    events = host.ctx.settlement.event_store
    args = {
        "work_unit_id": "TASK-A",
        "items": [
            {
                "kind": "rule", "ref": "RULE-AI-18", "decision": "applied",
                "benefit": "helped", "read_version": "v1", "note": "触发并遵守",
            }
        ],
    }

    first = _payload(host.execute("settlement_submit", args))
    second = _payload(host.execute("settlement_submit", args))
    assert first["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True

    rule_events = [
        e for e in events.read("sess-1") if e.type == RULE_FEEDBACK_EVENT_TYPE
    ]
    assert len(rule_events) == 1  # 去重后只落一条
    assert rule_events[0].payload["attribution"] == "task(TASK-A)"


def test_submit_tool_rule_item_unknown_ref_fails_via_rule_lookup(tmp_path):
    host = _host(tmp_path, rules=True)

    result = host.execute(
        "settlement_submit",
        {
            "work_unit_id": "TASK-A",
            "items": [{"kind": "rule", "ref": "RULE-AI-9999", "decision": "applied"}],
        },
    )
    assert result.status == ToolResultStatus.FAILURE
    receipt = _payload(result)
    assert receipt["receipts"][0]["status"] == "failed"
    assert "rule_lookup" in receipt["receipts"][0]["reason"]


def test_submit_tool_rule_dedup_spans_sessions_via_channel_logs_dir(tmp_path):
    """P-SET-7 工具面端到端：通道 event_logs_dir 装配后跨会话重提幂等.

    旧行为：同 (slot, submission_hash) 在另一会话重提追加重复
    rule.feedback 事件且返回非幂等 committed（查重只扫当前会话）。
    """
    host = _host(tmp_path, rules=True)
    events = host.ctx.settlement.event_store
    args = {
        "work_unit_id": "TASK-A",
        "items": [
            {
                "kind": "rule", "ref": "RULE-AI-18", "decision": "applied",
                "benefit": "helped", "read_version": "v1", "note": "跨会话重试",
            }
        ],
    }

    first = _payload(host.execute("settlement_submit", args))
    host.ctx.session_id = "sess-2"  # 另一会话重提（同工作单元、同内容）
    second = _payload(host.execute("settlement_submit", args))

    assert first["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True
    total = sum(
        1
        for sid in ("sess-1", "sess-2")
        for e in events.read(sid)
        if e.type == RULE_FEEDBACK_EVENT_TYPE
    )
    assert total == 1  # 不追加重复事件


# ── 通道缺件零行为 ──


def test_channel_not_assembled_is_zero_behavior(tmp_path):
    ctx = CorrectionContext()
    ctx.session_id = "sess-1"
    host = CorrectionToolRegistry(ctx)  # settlement 未装配（None）

    pending = host.execute("settlement_pending", {"work_unit_id": "TASK-A"})
    submit = host.execute(
        "settlement_submit", {"items": [{"kind": "method", "ref": "method:x", "decision": "applied"}]}
    )
    for result in (pending, submit):
        assert result.status == ToolResultStatus.FAILURE
        assert "结算通道不可用" in result.content
    assert not (tmp_path / "events").exists()  # 零行为：未落任何文件


def test_session_unattributable_is_zero_behavior(tmp_path):
    host = _host(tmp_path)
    host.ctx.session_id = ""  # 会话不可归属

    result = host.execute("settlement_pending", {})
    assert result.status == ToolResultStatus.FAILURE
    assert "会话不可归属" in result.content


def test_tool_defs_registered_in_module_surface():
    from llm_loop.introspection import registry_experience

    names = {td["name"] for td in registry_experience.tool_defs()}
    assert {"settlement_pending", "settlement_submit"} <= names
    for td in registry_experience.tool_defs():
        if td["name"] in {"settlement_pending", "settlement_submit"}:
            assert td.get("compact_description")


# ── factory 装配面 ──


def _settings(tmp_path, **overrides) -> Settings:
    fields = {
        "llm_api_key": "k",
        "llm_base_url": "https://x/v1",
        "llm_model": "m",
        "data_dir": str(tmp_path / "data"),
        "self_inspection_enabled": True,
        "extract_enabled": False,
    }
    fields.update(overrides)
    return Settings(**fields)


def test_factory_assembles_settlement_channel_and_tools(tmp_path):
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    assert engine.correction_ctx.settlement is not None  # EventStore 默认启用
    # P-SET-7 装配面：通道携带 EventStore 同源事件目录（跨会话规则查重数据源）
    assert engine.correction_ctx.settlement.event_logs_dir
    names = set(engine.registry.names())
    assert "settlement_pending" in names
    assert "settlement_submit" in names


def test_factory_zero_config_settlement_tools_noop(tmp_path):
    """零配置（无会话上下文）：工具已注册但零行为——不伪造清单、不落账."""
    from llm_loop.core.message import ToolCall
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    pending = engine.registry.execute(
        ToolCall(id="t1", name="settlement_pending", arguments={})
    )
    assert pending.status == ToolResultStatus.FAILURE
    assert "会话不可归属" in pending.content


def test_factory_event_log_disabled_settlement_channel_not_assembled(tmp_path):
    from llm_loop.factory import build_engine

    engine = build_engine(
        _settings(tmp_path, event_log_enabled=False)  # type: ignore[arg-type]
    )
    assert engine.correction_ctx.settlement is None
    result = engine.corrections.execute("settlement_pending", {"work_unit_id": "T"})
    assert result.status == ToolResultStatus.FAILURE
    assert "结算通道不可用" in result.content


# ── K-Rate 闭环接线：settlement_submit → 自动触发 score+index ──
# 审查 P1-2：删除调用点整行时必须红——此前全套件对此静默。


def _krate_args(host, store, ref) -> dict:
    events = host.ctx.settlement.event_store
    version = store.get(ref).content_hash
    _emit_read(events, "sess-krate", kind="method", ref=ref, version=version)
    return {
        "work_unit_id": "TASK-KRATE",
        "items": [{
            "kind": "method", "ref": ref, "decision": "applied",
            "benefit": "helped", "evidence_level": "model_declared",
        }],
    }


def test_submit_tool_wires_krate_autorun_only_on_committed(tmp_path, monkeypatch):
    """接线正向断言：committed>0 触发一次；幂等重试 committed=0 不再触发."""
    from llm_loop.introspection import registry_experience as re_mod

    host = _host(tmp_path)
    store, ref = _method_store(tmp_path)
    calls = []

    def _rec(h, repo_root=None):
        calls.append(repo_root)
        return "spawned_pid=1"

    monkeypatch.setattr(re_mod, "_spawn_krate_autorun", _rec)
    # 负例（不存在 ref → failed → committed=0，不触发）
    bare = {
        "work_unit_id": "TASK-KRATE-BARE",
        "items": [{
            "kind": "method", "ref": "method:no-such-ref-krate", "decision": "applied",
            "benefit": "helped", "evidence_level": "model_declared",
        }],
    }
    zero = host.execute("settlement_submit", bare)
    assert _payload(zero)["counts"]["committed"] == 0
    assert calls == []
    # 正例：有 read 事件 → committed=1，触发一次（生产路径 repo_root=None）
    args = _krate_args(host, store, ref)
    first = host.execute("settlement_submit", args)
    assert first.status == ToolResultStatus.SUCCESS
    assert _payload(first)["counts"]["committed"] == 1
    assert calls == [None]
    # 幂等重试仍属 committed（idempotent 语义）：再次触发，锁保证串行幂等
    retry = host.execute("settlement_submit", args)
    assert _payload(retry)["receipts"][0]["idempotent"] is True
    assert calls == [None, None]


def test_submit_tool_receipt_survives_krate_spawn_failure(tmp_path, monkeypatch):
    """fail-open 主断言：Popen 抛异常时结算回执仍 SUCCESS 且 committed 完整."""
    from llm_loop.introspection import registry_experience as re_mod

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # 穿透守卫触达 Popen
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)
    host = _host(tmp_path, audit_dir=tmp_path / "audit")
    store, ref = _method_store(tmp_path)
    args = _krate_args(host, store, ref)

    def _boom(*a, **k):
        raise RuntimeError("spawn exploded")

    monkeypatch.setattr(re_mod.subprocess, "Popen", _boom)
    result = host.execute("settlement_submit", args)
    assert result.status == ToolResultStatus.SUCCESS  # 回执不受 hook 故障影响
    payload = _payload(result)
    assert payload["counts"]["committed"] == 1
    lines = (tmp_path / "audit/self_correction_log.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    krate = [json.loads(l) for l in lines if json.loads(l)["tool_name"] == "krate_autorun"]
    # 两条均为预期：hook 内部 fail-open 记 failed；调用点记触发结果 triggered
    assert [(k["result_status"], k["arguments"]) for k in krate] == [
        ("failed", {"error": "spawn exploded"}),
        ("triggered", {"result": "spawn_failed"}),
    ]
