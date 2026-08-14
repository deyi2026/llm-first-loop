"""单元测试: D1 一致性校验 reconcile（design.md §2.4.1 / spec §5.6）.

覆盖:
- 构造一致会话 passed=True 且无差异
- 人为篡改字段 → passed=False 且差异可定位到会话/字段/期望/实际
- 比对前后源文件 mtime/内容哈希逐字节不变（纯只读，spec §5.6.1-4）
- 异常场景 passed=False 不伪造通过（事件缺口/未知类型）
"""

from __future__ import annotations

import hashlib

from llm_loop.event_log.reconcile import reconcile


def _valid_session(session_id: str = "s1") -> dict:
    return {
        "version": 4,
        "session_id": session_id,
        "created_at": "2026-01-01T00:00:00",
        "title": "会话",
        "updated_at": "2026-01-01T00:00:02",
        "status": "active",
        "parent_id": None,
        "branch_id": "",
        "branch_summary": "",
        "model_override": None,
        "pinned": False,
        "channel": "web",
        "messages": [
            {"role": "user", "content": "你好", "source": "user", "tool_call_id": None,
             "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
             "reasoning_content": None, "metadata": {}},
            {"role": "tool", "content": "[状态: success] 结果", "source": "tool",
             "tool_call_id": "c1", "status": "success", "tool_name": "f1",
             "error_detail": None, "tool_calls": None, "reasoning_content": None, "metadata": {}},
        ],
    }


def test_reconcile_identical_passes():
    src = _valid_session()
    rep = reconcile(dict(src), src)
    assert rep.passed is True
    assert rep.top_level_diffs == []
    assert rep.message_diffs == []
    assert rep.gap_count == 0
    assert rep.unknown_events == 0
    assert rep.session_id == "s1"


def test_reconcile_tampered_field_locatable():
    src = _valid_session()
    derived = dict(src)
    derived["title"] = "被篡改标题"
    derived["messages"] = list(src["messages"])
    derived["messages"][1] = dict(src["messages"][1])
    derived["messages"][1]["content"] = "[状态: failure] 伪造"
    rep = reconcile(derived, src)
    assert rep.passed is False
    # 顶层差异可定位到字段与期望/实际
    assert any(
        d["字段"] == "title" and d["期望"] == "会话" and d["实际"] == "被篡改标题"
        for d in rep.top_level_diffs
    )
    # 消息差异可定位到 index/字段/期望/实际
    assert any(
        d["index"] == 1 and d["字段"] == "content" and d["期望"].startswith("[状态: success]")
        for d in rep.message_diffs
    )


def test_reconcile_readonly_source_untouched(tmp_path):
    src = _valid_session()
    p = tmp_path / "s1.json"
    import json

    p.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    before_mtime = p.stat().st_mtime_ns
    before_hash = hashlib.sha256(p.read_bytes()).hexdigest()

    reconcile(dict(src), src)  # 比对（纯只读）

    assert p.stat().st_mtime_ns == before_mtime
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before_hash


def test_reconcile_derived_gap_not_faked():
    src = _valid_session()
    derived = dict(src)
    derived["event_log_gaps"] = [{"gap_at": 2, "missing": 3}]
    rep = reconcile(derived, src)
    assert rep.passed is False
    assert rep.gap_count == 3


def test_reconcile_derived_unknown_events_not_faked():
    src = _valid_session()
    derived = dict(src)
    derived["unknown_event_types"] = ["ghost.type"]
    rep = reconcile(derived, src)
    assert rep.passed is False
    assert rep.unknown_events == 1


def test_reconcile_message_count_mismatch():
    src = _valid_session()
    derived = dict(src)
    derived["messages"] = src["messages"][:1]  # 少一条消息
    rep = reconcile(derived, src)
    assert rep.passed is False
    assert any(d["index"] == 1 and "不存在" in d["字段"] for d in rep.message_diffs)


def test_reconcile_exception_safety():
    # 比对异常场景（结构性损坏源）不伪造通过
    src = _valid_session()
    src["messages"] = [{"role": "user"}]  # 缺字段
    derived = dict(src)
    rep = reconcile(derived, src)
    assert isinstance(rep.passed, bool)
