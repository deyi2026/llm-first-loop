"""2026-08-20 审计修复: array/object 参数归一化（EVO-20260820-6857bf41 同类批量）.

模型常把 array 传成字符串（含 JSON 数组串/逗号串/残缺串）→ 修复前按字符迭代
产生静默垃圾（acceptance/tags/parameters_hint）。共享归一化统一处理。
"""

from __future__ import annotations

from llm_loop.tools.arg_coerce import coerce_obj, coerce_str_list


def test_coerce_str_list_handles_all_forms():
    # 列表 → 清洗
    assert coerce_str_list([" a ", "b"]) == ["a", "b"]
    # JSON 数组字符串
    assert coerce_str_list('["x","y"]') == ["x", "y"]
    # 残缺 JSON 数组字符串（实测形态: 缺尾括号）→ 提取
    assert coerce_str_list('["x", "y"') == ["x", "y"]
    # 逗号分隔串
    assert coerce_str_list("x,y") == ["x", "y"]
    # 单个字符串 → 单元素
    assert coerce_str_list("single") == ["single"]
    # None/空 → 空列表
    assert coerce_str_list(None) == []
    assert coerce_str_list("") == []
    # 非列表非串（数字）→ 空
    assert coerce_str_list(123) == []


def test_coerce_obj_handles_json_string():
    assert coerce_obj({"a": 1}) == {"a": 1}
    assert coerce_obj('{"a":1}') == {"a": 1}
    assert coerce_obj("not json") == {}  # 不静默存字符串
    assert coerce_obj(None) == {}
