"""D4 pre-step 过滤钩子测试（spec §5.4 / design.md §2.2.2-D）.

全走 tmp_path（M64 防污染真实 data/）。
"""

from __future__ import annotations

from llm_loop.event_log.hooks import (
    DesensitizeRule,
    FilterRule,
    HookChain,
    HookRegistry,
    TransformRule,
)
from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore


def _make_event(**kwargs) -> Event:
    defaults = {
        "event_id": "e1",
        "session_id": "s1",
        "seq": 1,
        "type": "message.appended",
        "ts": "2026-08-14T00:00:00+00:00",
        "payload": {"index": 0, "role": "user", "content": "secret data"},
    }
    defaults.update(kwargs)
    return Event(**defaults)


# ── 钩子链默认空 ──


def test_empty_chain_zero_behavior():
    """钩子链默认空 → process 返回 (event, []) 零行为."""
    chain = HookChain([])
    event = _make_event()
    processed, audits = chain.process(event)
    assert processed is event
    assert audits == []


# ── filter 动作 ──


def test_filter_drop():
    """filter 匹配 → 丢弃返回 None + 审计标记."""
    reg = HookRegistry()
    reg.register("drop-user", priority=10, action_type="filter", rule=FilterRule(match={"type": "message.appended"}))
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    assert processed is None
    assert len(audits) == 1
    assert audits[0].action_type == "filter"


def test_filter_no_match_keep():
    """filter 不匹配 → 保留事件."""
    reg = HookRegistry()
    reg.register("drop-tool", priority=10, action_type="filter", rule=FilterRule(match={"type": "tool.result"}))
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    assert processed is not None
    assert processed.payload["content"] == "secret data"


# ── desensitize 动作 ──


def test_desensitize_mask():
    """desensitize mask → 字段替换为脱敏值."""
    reg = HookRegistry()
    reg.register(
        "mask-content", priority=10, action_type="desensitize",
        rule=DesensitizeRule(target_fields=["payload.content"], method="mask", replacement="***"),
    )
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    assert processed.payload["content"] == "***"
    assert len(audits) == 1


def test_desensitize_delete():
    """desensitize delete → 字段删除."""
    reg = HookRegistry()
    reg.register(
        "del-content", priority=10, action_type="desensitize",
        rule=DesensitizeRule(target_fields=["payload.content"], method="delete"),
    )
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    assert "content" not in processed.payload


# ── transform 动作 ──


def test_transform():
    """transform → 字段替换为转换后值 + transformed_from 标记."""
    reg = HookRegistry()
    reg.register(
        "upper", priority=10, action_type="transform",
        rule=TransformRule(target_fields=["payload.content"], transform_fn=str.upper, rule_name="uppercase"),
    )
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    assert processed.payload["content"] == "SECRET DATA"
    assert audits[0].transformed_from == "uppercase"


# ── 优先级 ──


def test_priority_order():
    """多钩子按 priority 升序执行."""
    reg = HookRegistry()

    reg.register("h2", priority=20, action_type="transform",
                 rule=TransformRule(target_fields=["payload.content"], transform_fn=lambda x: x + "+2", rule_name="h2"))
    reg.register("h1", priority=10, action_type="transform",
                 rule=TransformRule(target_fields=["payload.content"], transform_fn=lambda x: x + "+1", rule_name="h1"))
    chain = reg.chain()
    event = _make_event()
    processed, _ = chain.process(event)
    # h1 先执行（priority 10），然后 h2（priority 20）
    assert processed.payload["content"] == "secret data+1+2"


# ── fail-open ──


def test_hook_exception_fail_open():
    """钩子执行异常 → fail-open 保留原始事件 + 审计标注."""
    reg = HookRegistry()

    def bad_fn(x):
        raise RuntimeError("bad transform")

    reg.register("bad", priority=10, action_type="transform",
                 rule=TransformRule(target_fields=["payload.content"], transform_fn=bad_fn))
    chain = reg.chain()
    event = _make_event()
    processed, audits = chain.process(event)
    # fail-open：原始事件保留
    assert processed is not None
    assert processed.payload["content"] == "secret data"
    assert any(a.fail_open for a in audits)


# ── EventStore.append 钩子链挂接 ──


def test_store_append_with_filter(tmp_path):
    """EventStore.append 挂接钩子链：filter 丢弃 → 事件不进日志."""
    reg = HookRegistry()
    reg.register("drop-all", priority=10, action_type="filter", rule=FilterRule(match={"type": "message.appended"}))
    chain = reg.chain()
    store = EventStore(tmp_path / "event_logs", enabled=True, hook_chain=chain)
    result = store.append("s1", "message.appended", {"content": "test"})
    assert result is None  # 被过滤
    assert store.read("s1") == []  # 文件可能被 open 创建为空，但无事件


def test_store_append_with_desensitize(tmp_path):
    """EventStore.append 挂接钩子链：desensitize → 脱敏后事件落盘."""
    reg = HookRegistry()
    reg.register("mask", priority=10, action_type="desensitize",
                 rule=DesensitizeRule(target_fields=["payload.content"], method="mask", replacement="***"))
    chain = reg.chain()
    store = EventStore(tmp_path / "event_logs", enabled=True, hook_chain=chain)
    store.append("s1", "message.appended", {"content": "secret"})
    events = store.read("s1")
    assert len(events) == 1
    assert events[0].payload["content"] == "***"


def test_store_append_no_chain_zero_regression(tmp_path):
    """钩子链 None → EventStore.append 行为与 D1 逐字节一致（零回归）."""
    store = EventStore(tmp_path / "event_logs", enabled=True)
    store.append("s1", "message.appended", {"content": "test"})
    events = store.read("s1")
    assert len(events) == 1
    assert events[0].payload["content"] == "test"


def test_hook_audit_no_payload(tmp_path):
    """审计记录不含原始 payload 敏感内容（spec §6.3-3）."""
    reg = HookRegistry()
    reg.register("drop", priority=10, action_type="filter", rule=FilterRule(match={"type": "message.appended"}))
    chain = reg.chain()
    store = EventStore(tmp_path / "event_logs", enabled=True, hook_chain=chain)
    store.append("s1", "message.appended", {"content": "sensitive"})
    audit_path = tmp_path / "event_logs" / "_hook_audit.jsonl"
    assert audit_path.exists()
    audit_content = audit_path.read_text(encoding="utf-8")
    assert "sensitive" not in audit_content  # 原始 payload 不在审计
