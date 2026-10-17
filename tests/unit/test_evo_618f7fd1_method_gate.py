"""EVO-20260923-618f7fd1 ①: 方法 use 回记——收尾提醒.

机械验证（不测模型行为，只测程序面）：method_injection.scan_method_use_ledger +
build_use_reminder_message（状态层载体）。

原 ②（goal 级 method_use_gate 硬门）已于 2026-10-18 按 EVO-20261018-f4ca0fc4 删除：
与规则二十九“不设硬门”冲突，且自带 task_update(method_no_contact=true) 免费出口，
从未在生产开启。原 ③（会话开场 active 卡清单 build_active_cards_message）已于
2026-09-24 退役：弱本地模型身份轮实测被带偏（6aec21cb 凭先验自称 DeepSeek-V4，
对照 f66027f9 无附录时按证据自报正确），且无条件正文投喂违背 L2-2
retrievable != injectable。
"""
from __future__ import annotations

from llm_loop.core.injection_labels import InjectionLayer
from llm_loop.core.loop.engine_services.method_injection import (
    build_use_reminder_message,
    scan_method_use_ledger,
)
from llm_loop.core.trace_leak.invariant import metadata_satisfies_invariant

# ---------- ① 收尾提醒：tool_trace 扫描与消息载体 ----------


def test_ledger_counts_exact_hydration_only():
    rows = [
        {"id": "t1", "name": "search_records", "arguments": {"kind": "method", "query": "method:abc"}, "status": "success"},
        {"id": "t2", "name": "search_records", "arguments": {"kind": "method", "query": "导航发现"}, "status": "success"},  # 发现式查询不计
        {"id": "t3", "name": "search_records", "arguments": {"kind": "method", "query": "method:def"}, "status": "error"},  # 失败不计
        {"id": "t4", "name": "search_records", "arguments": {"kind": "experience", "query": "method:zzz"}, "status": "success"},  # 非 method kind 不计
        {"id": "t5", "name": "method_manage", "arguments": {"action": "record_use", "method_ref": "method:abc"}, "status": "success"},
        {"id": "t6", "name": "method_manage", "arguments": {"action": "save_candidate", "name": "x"}, "status": "success"},  # 非 record_use 不计
    ]
    ledger = scan_method_use_ledger(rows)
    assert ledger.hydrated == ("method:abc",)
    assert ledger.recorded == ("method:abc",)
    assert ledger.unrecorded() == ()


def test_ledger_reports_unrecorded_refs():
    rows = [
        {"name": "search_records", "arguments": {"kind": "method", "query": "method:x"}, "status": "success"},
        {"name": "search_records", "arguments": {"kind": "method", "query": "method:y"}, "status": "success"},
        {"name": "method_manage", "arguments": {"action": "record_use", "method_ref": "method:y"}, "status": "success"},
    ]
    assert scan_method_use_ledger(rows).unrecorded() == ("method:x",)


def test_reminder_message_is_status_layer_program_origin():
    msg = build_use_reminder_message(("method:x", "method:y"))
    assert msg.role == "user"
    assert msg.metadata.get("injection_kind") == "method_use_reminder"
    assert msg.metadata.get("origin_layer") == InjectionLayer.STATUS.value
    assert metadata_satisfies_invariant(msg.metadata)
    assert "method:x" in msg.content and "method:y" in msg.content


def test_reminder_never_fires_without_exact_hydration():
    rows = [{"name": "search_records", "arguments": {"kind": "method", "query": "导航"}, "status": "success"}]
    assert scan_method_use_ledger(rows).unrecorded() == ()
