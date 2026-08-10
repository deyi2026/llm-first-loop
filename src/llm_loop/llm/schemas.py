"""tools 参数构造与响应解析（design.md §2.1.3.2 机制一 / 约束 C4/C5）.

- 约束 C4: tools 参数 JSON Schema（type: function, function: {name, description, parameters}）
- 约束 C5: 流式响应中 tool_calls 以 delta 分片到达（按 index 标识归属），
  此处实现按 index 聚合 id/name/arguments 分片
"""

from __future__ import annotations

import json
from typing import Any


def build_tools_schema(tool_defs: list[dict]) -> list[dict]:
    """将工具定义转为 LLM tools 参数（JSON Schema，约束 C4）.

    tool_defs 每项形如 {"name": str, "description": str, "parameters": dict}。
    """
    result: list[dict] = []
    for t in tool_defs:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )
    return result


class ToolCallDeltaAggregator:
    """流式 tool_calls delta 聚合器（约束 C5）.

    OpenAI SSE delta 形态:
      {"index": 0, "id": "call_xxx", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\""}}
      {"index": 0, "function": {"arguments": "data/notes.txt\"}"}}
    同一 index 的多个 delta 分片需归并拼装 id/name/arguments。
    """

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, Any]] = {}

    def add_delta(self, delta: dict) -> None:
        """归并一个 delta 分片（按 index）."""
        index = int(delta.get("index", 0))
        part = self._parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
        tc_id = delta.get("id")
        if tc_id:
            part["id"] = tc_id
        fn = delta.get("function") or {}
        if fn.get("name"):
            part["name"] = fn["name"]
        args = fn.get("arguments")
        if args:
            part["arguments"] += str(args)

    def finish(self) -> list[dict]:
        """聚合完成，返回 [{id, name, arguments(解析后 dict)}]（按 index 排序）.

        id 为空 → 该声明不可执行（约束 C1），由循环如实反馈；
        此处保留原始 arguments 字符串供校验。
        """
        calls: list[dict] = []
        for idx in sorted(self._parts):
            part = self._parts[idx]
            raw_args = part["arguments"].strip()
            parsed: Any = {}
            if raw_args:
                try:
                    parsed = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed = {"_raw_arguments": raw_args}
            calls.append(
                {
                    "id": part["id"],
                    "name": part["name"],
                    "arguments": parsed,
                    "_arguments_raw": raw_args,
                }
            )
        return calls
