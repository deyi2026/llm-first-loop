"""工具参数鲁棒归一化（2026-08-20 审计: EVO-20260820-6857bf41 同类风险批量修复）.

背景: 模型常把 schema 声明为 array/object 的参数传成字符串（含 JSON 数组字符串、
逗号分隔串、残缺串）。若实现直接按迭代器消费，字符串会被按字符拆开 → 静默垃圾
（如 acceptance="a,b" 变成 ['a',',','b']），与 architecture_status.dimensions
同类的"假正确"问题。本模块提供共享归一化，统一处理 string↔list/dict。
"""

from __future__ import annotations

import json
import re
from typing import Any


def coerce_str_list(value: Any) -> list[str]:
    """把 array 型参数归一化为干净字符串列表（绝不抛异常）.

    处理形态:
    - list/tuple → 逐项 str + strip + 去空
    - JSON 数组字符串（'["a","b"]'，含残缺）→ json.loads 优先，失败退拆分
    - 逗号/空白分隔串（"a,b"）→ 拆分
    - 单个字符串（"a"）→ 单元素列表
    - None/其他 → 空列表
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [parsed]
        except Exception:  # noqa: BLE001 — 非 JSON，按分隔串/单串处理
            items = re.split(r"[,，\s]+", s)
    else:
        return []
    cleaned = [re.sub(r'^[\[\"\s]+|[\"\]\s]+$', '', str(x)) for x in items]
    return [x for x in cleaned if x]


def coerce_obj(value: Any) -> dict:
    """把 object 型参数归一化为 dict（JSON 字符串/残缺串尽量解析，失败给空 dict）."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001 — 无法解析 → 空 dict（不静默存字符串）
            return {}
    return {}
