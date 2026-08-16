"""路径 A 参数预检测试（tasks.md §1.2 验收）."""

from __future__ import annotations

import time

from llm_loop.task_quality.precheck import PreCheckLayer


def _schema(**kw):
    base = {"type": "object"}
    base.update(kw)
    return base


def test_valid_passes():
    """参数合法: valid=True 放行."""
    layer = PreCheckLayer()
    r = layer.check({"timeout_s": 30, "name": "x"}, _schema(
        properties={"timeout_s": {"type": "integer"}, "name": {"type": "string"}},
        required=["name"],
    ))
    assert r.valid is True
    assert r.errors == ()


def test_type_error_field_level():
    """类型错误: 字段级错误（field_path/expected/actual/message）."""
    layer = PreCheckLayer()
    r = layer.check({"timeout_s": "abc"}, _schema(properties={"timeout_s": {"type": "integer"}}))
    assert r.valid is False
    assert len(r.errors) == 1
    e = r.errors[0]
    assert e.field_path == "timeout_s"
    assert e.expected_type == "integer"
    assert e.actual_type == "str"
    assert "类型不匹配" in e.message


def test_required_missing():
    """必填缺失: 字段 'X' required but missing."""
    layer = PreCheckLayer()
    r = layer.check({}, _schema(
        properties={"name": {"type": "string"}}, required=["name"]
    ))
    assert r.valid is False
    assert any("required but missing" in e.message and "name" in e.field_path for e in r.errors)


def test_enum_invalid():
    """枚举非法: value not in enum."""
    layer = PreCheckLayer()
    r = layer.check({"mode": "bad"}, _schema(properties={"mode": {"type": "string", "enum": ["a", "b"]}}))
    assert r.valid is False
    assert any("not in enum" in e.message and "mode" in e.field_path for e in r.errors)


def test_nested_path_location():
    """嵌套错误路径: steps[2].executor."""
    schema = _schema(properties={
        "steps": {"type": "array", "items": {"type": "object",
                 "properties": {"executor": {"type": "string"}}}}
    })
    layer = PreCheckLayer()
    r = layer.check({"steps": [{"executor": "ok"}, {"executor": "ok2"}, {"executor": 123}]}, schema)
    assert r.valid is False
    assert any("steps[2].executor" in e.field_path for e in r.errors)


def test_schema_missing_fail_open():
    """schema 缺失: fail-open 放行."""
    layer = PreCheckLayer()
    assert layer.check({"x": 1}, {}).valid is True
    assert layer.check({"x": 1}, None).valid is True  # type: ignore[arg-type]


def test_internal_error_fail_open():
    """校验异常: fail-open 放行."""
    layer = PreCheckLayer()
    # schema 含异常结构（type 非标准）→ 未知类型放行
    assert layer.check({"x": 1}, {"type": "object", "properties": {"x": {"type": "weird"}}}).valid is True


def test_depth_limit():
    """递归深度超限: 拦截 + 字段级错误."""
    layer = PreCheckLayer(max_depth=3)
    # 构造深嵌套: a{b{c{d{e}}}} = 5 层 > 3
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    schema = _schema(properties={"a": _schema(properties={"b": _schema(properties={"c": _schema(properties={"d": _schema(properties={"e": {"type": "integer"}})})})})})
    r = layer.check(deep, schema)
    assert r.valid is False
    assert any("深度超限" in e.message for e in r.errors)


def test_event_store_on_failure():
    """预检失败事件落盘（payload 含字段错误摘要，不含参数明文）."""
    events = []
    class _Store:
        def append(self, sid, etype, payload):
            events.append((etype, payload))
            return None
    layer = PreCheckLayer(event_store=_Store(), session_id="s1")
    r = layer.check({"timeout_s": "abc"}, _schema(properties={"timeout_s": {"type": "integer"}}))
    assert r.valid is False
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "task.precheck.failed"
    assert payload["field_errors"][0]["field_path"] == "timeout_s"
    assert "abc" not in str(payload)  # 不含参数明文值


def test_latency_under_50ms():
    """单次校验时延 < 50ms."""
    layer = PreCheckLayer()
    schema = _schema(properties={"items": {"type": "array", "items": {"type": "object",
                "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}}})
    args = {"items": [{"id": i, "name": f"n{i}"} for i in range(50)]}
    start = time.perf_counter()
    for _ in range(20):
        layer.check(args, schema)
    elapsed = (time.perf_counter() - start) / 20 * 1000
    assert elapsed < 50, f"时延 {elapsed:.1f}ms 超限"


def test_boolean_not_integer():
    """bool 不兼容 integer（JSON 语义）."""
    layer = PreCheckLayer()
    r = layer.check({"n": True}, _schema(properties={"n": {"type": "integer"}}))
    assert r.valid is False
