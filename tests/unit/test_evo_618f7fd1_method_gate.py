"""Method tool-trace facts remain available without a compulsory reminder."""

from llm_loop.core.loop.engine_services.method_injection import scan_method_use_ledger


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
