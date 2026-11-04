"""EVO-20261104-305716fa：长会话重复探索根因修复的行为锚点测试.

E1 reuse 感知压缩 / E2 快照内嵌真实内容 / E3 恢复账本优先 / E4 密度校准持久化
/ E5 参数级重复熔断与停滞口径。全部针对 2026-11-04 会话 6c13edc8 的量化病灶：
read_evidence 517/1262、148/348 证据反复重读、内嵌 assistant 353 条/0 字符、
effective_budget(34206) < tool_schema(76193 chars)、stagnation_rate 仅 0.02。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from llm_loop.core.loop.engine_services.compaction_gate import (
    _recent_assistant_from_manifest,
    compaction_source_wire,
    note_archive_batch_entry,
    render_gate_notice_text,
    write_compaction_manifest,
    write_gate_state,
)
from llm_loop.core.loop.engine_services.token_budget import ProjectionDensityTracker
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.message import (
    RecoverabilityStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.introspection.evaluator import SelfEvaluator

# ---------------------------------------------------------------- E1：reuse 感知压缩

def _host_with_cache(compact_event_seq: int = 0):
    state = SimpleNamespace(
        longrun_read_cache={},
        compact_event_seq=compact_event_seq,
        repeat_guard={},
        _record_action=lambda *a, **k: None,
    )
    host = SimpleNamespace(_run_state=lambda: state)
    return host, state


def test_e1_reuse_stub_same_compaction_epoch(tmp_path):
    args = {"evidence_ref": "evidence://v1/aaa", "start": 0, "limit": 10}
    host, _state = _host_with_cache(compact_event_seq=3)
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    cycle._remember_continuity_read(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="r1", name="read_evidence", arguments=args),
        ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="body",
            tool_call_id="r1",
            tool_name="read_evidence",
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref="evidence://v1/aaa",
        ),
    )
    reused = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="r2", name="read_evidence", arguments=dict(args))
    )
    assert reused is not None
    assert reused.source_execution_performed is False
    assert "compact_event_seq=3" in reused.content


def test_e1_reuse_invalidated_after_compaction_epoch_advances(tmp_path):
    args = {"evidence_ref": "evidence://v1/bbb", "start": 0, "limit": 10}
    host, state = _host_with_cache(compact_event_seq=7)
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    cycle._remember_continuity_read(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="r1", name="read_evidence", arguments=args),
        ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="body",
            tool_call_id="r1",
            tool_name="read_evidence",
            recoverability_status=RecoverabilityStatus.RECORDED,
            evidence_ref="evidence://v1/bbb",
        ),
    )
    # 压缩发生：epoch 前进 → 原读结果已离开模型上下文 → 桩失效，回退物理重读
    state.compact_event_seq = 8
    reused = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="r2", name="read_evidence", arguments=dict(args))
    )
    assert reused is None


def test_e1_cache_without_epoch_still_reusable_backward_compatible():
    # 溢出交接恢复的旧缓存条目无 compact_event_seq 字段 → 维持既有复用语义
    args = {"evidence_ref": "evidence://v1/ccc", "start": 0, "limit": 5}
    host, state = _host_with_cache(compact_event_seq=2)
    state.longrun_read_cache = {
        f"{k}": v for k, v in []
    }
    from llm_loop.core.longrun_continuity import canonical_read_key

    state.longrun_read_cache[canonical_read_key("read_evidence", args)] = {
        "tool": "read_evidence",
        "arguments": dict(args),
        "evidence_ref": "evidence://v1/ccc",
        "source_version_token": "",
        "artifact_ref": "",
    }
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    reused = cycle._continuity_reuse_result(  # pyright: ignore[reportPrivateUsage]
        ToolCall(id="r2", name="read_evidence", arguments=dict(args))
    )
    assert reused is not None


# ---------------------------------------------------------------- E2：内嵌真实内容

def test_e2_reasoning_only_assistant_embeds_reasoning_tail(tmp_path):
    engine = SimpleNamespace()
    msg = SimpleNamespace(
        role="assistant",
        content="",
        reasoning_content="R" * 3000 + "结论：套件数断言口径过时。",
        tool_calls=None,
        metadata={},
        ts=1793759000.0,
    )
    entry = {"id": "ARC-1", "chars": 0, "sha256": "", "file": None}
    note_archive_batch_entry(engine, "sess-e2", msg, entry, 42)
    batch = engine._compaction_manifest_batches["sess-e2"]  # pyright: ignore[reportAttributeAccessIssue]
    assert len(batch) == 1
    e = batch[0]
    assert e["original"]  # 非空：内嵌 reasoning 尾段
    assert e["chars"] > 0
    assert e["chars"] <= 1600
    assert e["embedded_source"] == "reasoning_tail"
    assert "结论：套件数断言口径过时。" in e["original"]


def test_e2_manifest_coverage_reports_embedded_chars_truthfully(tmp_path):
    engine = SimpleNamespace()
    engine._compaction_manifest_batches = {
        "sess-e2b": [
            {
                "session_id": "sess-e2b",
                "msg_seq": 1,
                "role": "assistant",
                "ts": None,
                "chars": 0,  # 旧口径只数 content → 0（病灶：353 条/0 字符）
                "sha256": "",
                "archive_entry_id": "ARC-A",
                "archive_file": None,
                "evidence_ref": None,
                "protocol_state_ref": None,
                "original": "已核事实：reuse 桩不感知压缩。",
                "embedded_source": "reasoning_tail",
            },
            {
                "session_id": "sess-e2b",
                "msg_seq": 2,
                "role": "tool",
                "ts": None,
                "chars": 500,
                "sha256": "",
                "archive_entry_id": "ARC-B",
                "archive_file": None,
                "evidence_ref": None,
            },
        ]
    }
    # write_compaction_manifest 期望的 batch 布局：直接给 entries 列表更简单——
    # 这里绕过 batches 属性，构造等价 entries。
    entries = engine._compaction_manifest_batches["sess-e2b"]
    ref = write_compaction_manifest(str(tmp_path), "sess-e2b", entries)
    assert ref is not None
    with open(ref["path"], encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["coverage"]["embedded_chars"] == len("已核事实：reuse 桩不感知压缩。")
    assert manifest["coverage"]["embedded_msgs"] == 1
    assert manifest["assistant_entries"][0]["embedded_source"] == "reasoning_tail"
    # E2 恢复端：wire 直接携带最近 assistant 结论
    recent = _recent_assistant_from_manifest(ref["path"])
    assert len(recent) == 1
    assert "reuse 桩不感知压缩" in recent[0]["text"]
    assert recent[0]["source"] == "reasoning_tail"


def test_e2_wire_embeds_recent_assistant_and_e3_ledger_reader(tmp_path):
    session_id = "sess-wire"
    entries = [
        {
            "session_id": session_id,
            "msg_seq": 1,
            "role": "assistant",
            "ts": None,
            "chars": 0,
            "sha256": "",
            "archive_entry_id": None,
            "archive_file": None,
            "evidence_ref": None,
            "original": "根因：密度 fallback 0.6 触发高频压缩。",
            "embedded_source": "reasoning_tail",
        }
    ]
    ref = write_compaction_manifest(str(tmp_path), session_id, entries)
    assert ref is not None
    state = {
        "pending": True,
        "manifest_sha256": ref["sha256"],
        "manifest_rel_path": ref["rel_path"],
        "total_archived": 1,
        "source_message_range": ref["source_message_range"],
    }
    write_gate_state(str(tmp_path), session_id, state)
    engine = SimpleNamespace(settings=SimpleNamespace(data_dir=str(tmp_path)))
    wire = compaction_source_wire(engine, session_id)
    assert wire is not None
    payload = json.loads(wire["content"].split("] ", 1)[1])
    assert payload["ledger_reader"] == {"tool": "task_state", "action": "read"}  # E3
    assert len(payload["recent_assistant"]) == 1
    assert "密度 fallback" in payload["recent_assistant"][0]["text"]


# ---------------------------------------------------------------- E3：账本优先指引

def test_e3_gate_notice_mentions_ledger_first():
    text = render_gate_notice_text(None, attempt=1)
    assert "账本优先" in text
    assert "task_state(action=save)" in text


# ---------------------------------------------------------------- E4：密度持久化

def test_e4_density_tracker_persists_across_instances(tmp_path):
    store = tmp_path / "runtime" / "projection_density.json"
    first = ProjectionDensityTracker(
        store_path=str(store), min_samples=8, save_every=1
    )
    for _ in range(10):
        first.observe(
            "minimax",
            "MiniMax-M3.1-Flash",
            "openai",
            provider_visible_chars=2680,
            prompt_tokens=1000,
        )  # 实测密度 2.68 chars/token
    # 进程内已测得；决策走 observed_lower_bound
    dec = first.decision("minimax", "MiniMax-M3.1-Flash", "openai", fallback_chars_per_token=0.6)
    assert dec is not None and dec.source == "observed_lower_bound"

    # 冷启动新实例：从持久化初值得出同一结论（不再退回 0.6 fallback）
    second = ProjectionDensityTracker(store_path=str(store), min_samples=8)
    dec2 = second.decision("minimax", "MiniMax-M3.1-Flash", "openai", fallback_chars_per_token=0.6)
    assert dec2 is not None and dec2.source == "observed_lower_bound"
    assert dec2.chars_per_token == dec.chars_per_token

    # 无持久化的全新表面仍走 configured_fallback（保守语义不变）
    third = ProjectionDensityTracker(store_path=None)
    dec3 = third.decision("p", "m", "w", fallback_chars_per_token=0.6)
    assert dec3 is None or dec3.source == "configured_fallback"


def test_e4_corrupt_store_fails_open(tmp_path):
    store = tmp_path / "projection_density.json"
    store.write_text("{not json", encoding="utf-8")
    tracker = ProjectionDensityTracker(store_path=str(store))
    dec = tracker.decision("p", "m", "w", fallback_chars_per_token=0.6)
    assert dec is None or dec.source == "configured_fallback"


# ---------------------------------------------------------------- E5：重复熔断 + 停滞口径

def _guard_result(cycle, call, i):
    result = ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"body-{i}",
        tool_call_id=call.id,
        tool_name=call.name,
        recoverability_status=RecoverabilityStatus.RECORDED,
    )
    cycle._maybe_repeat_guard_hint(call, result)  # pyright: ignore[reportPrivateUsage]
    return result


def test_e5_repeat_guard_fires_once_at_third_identical_call():
    host, _ = _host_with_cache()
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    args = {"evidence_ref": "evidence://v1/ddd", "start": 0, "limit": 10}
    call = ToolCall(id="g1", name="read_evidence", arguments=args)
    r1 = _guard_result(cycle, call, 1)
    r2 = _guard_result(cycle, call, 2)
    r3 = _guard_result(cycle, call, 3)
    assert "repeat_guard" not in r1.content
    assert "repeat_guard" not in r2.content
    assert "[repeat_guard]" in r3.content
    r4 = _guard_result(cycle, call, 4)
    assert r4.content.count("repeat_guard") == 0  # 每键一次，不反复打扰


def test_e5_failure_results_do_not_count():
    host, _ = _host_with_cache()
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    args = {"evidence_ref": "evidence://v1/fff", "start": 0, "limit": 10}
    call = ToolCall(id="g9", name="read_evidence", arguments=args)
    failed = ToolResult(
        status=ToolResultStatus.FAILURE,
        content="failed",
        tool_call_id=call.id,
        tool_name=call.name,
    )
    for _ in range(5):
        cycle._maybe_repeat_guard_hint(call, failed)  # pyright: ignore[reportPrivateUsage]
    assert host._run_state().repeat_guard == {}


def test_e5_same_evidence_ref_different_ranges_hint_at_fifth():
    host, _ = _host_with_cache()
    cycle = ToolCycleService(host)  # pyright: ignore[reportArgumentType]
    last = None
    for i in range(5):
        args = {"evidence_ref": "evidence://v1/eee", "start": i * 100, "limit": 100}
        call = ToolCall(id=f"g{i}", name="read_evidence", arguments=args)
        last = _guard_result(cycle, call, i)
    assert last is not None
    assert "同一" in last.content and "evidence_ref" in last.content


def test_e5_stagnation_metric_counts_interleaved_param_repeats():
    # A→B→A→B 交替：连续口径 0 次；参数级口径必须捕捉到
    ev = SelfEvaluator.__new__(SelfEvaluator)
    ev._min_samples = 3
    ev._span = 50
    trace = []
    for i in range(6):
        trace.append({"phase": "action.tool_loop", "action_type": "tool_call", "detail": f"toolA|args{i % 2}"})
    metric = ev._metric_stagnation_rate(trace)
    assert metric.value is not None and metric.value > 0
    assert "全重复口径" in metric.note and "交错重复" in metric.note


def test_e5_stagnation_metric_distinct_actions_stay_clean():
    ev = SelfEvaluator.__new__(SelfEvaluator)
    ev._min_samples = 3
    ev._span = 50
    trace = [
        {"phase": "action.tool_loop", "action_type": "tool_call", "detail": f"toolX|args{i}"}
        for i in range(8)
    ]
    metric = ev._metric_stagnation_rate(trace)
    assert metric.value == 0.0
