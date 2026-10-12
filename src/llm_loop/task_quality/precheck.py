"""路径 A：参数预检 + 引导反馈（design.md §2.1 / spec §5.1）.

自实现最小 JSON Schema validator（避免 jsonschema 第三方依赖），递归校验：
- required 必填缺失
- type 类型不匹配
- enum 枚举非法
- 嵌套对象/数组递归（路径定位到 steps[2].executor）
- 递归深度上限 max_depth 防恶意深嵌套

插入位置: ToolRegistry.execute 步骤 1 之后、步骤 2 灾难性安全检查之前；
预检失败返回字段级引导反馈，不进入安全检查与真实执行。
fail-open: schema 缺失/校验异常 → 跳过预检放行（不阻断主循环）。
时延: 纯内存 < 50ms（spec §4.1.1）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from llm_loop.task_quality.models import FieldError, PreCheckResult

logger = logging.getLogger(__name__)

# JSON Schema type 与 Python 类型的映射（宽松判定：int 兼容 bool 除外）
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


class PreCheckLayer:
    """参数预检层（工具调用前拦截参数错误，返回字段级引导反馈）."""

    def __init__(
        self,
        *,
        max_depth: int = 10,
        event_store: Any | None = None,
        session_id: str = "",
        enabled_fn: Any | None = None,  # D3: 动态开关回调（None=恒开；False=放行零回归）
    ) -> None:
        self._max_depth = max_depth
        self._event_store = event_store
        self._session_id = session_id
        self._enabled_fn = enabled_fn

    def check(self, arguments: dict, schema: dict) -> PreCheckResult:
        """校验参数（schema 缺失/异常/开关关闭 fail-open 放行）.

        Args:
            arguments: 工具调用参数（dict）。
            schema: 工具 parameters schema（JSON Schema 子集）。

        Returns:
            PreCheckResult（valid=True 放行 / valid=False + FieldError 清单）。
        """
        # D3: 动态开关关闭 → 恒放行（零回归）
        if self._enabled_fn is not None:
            try:
                if not self._enabled_fn():
                    return PreCheckResult(valid=True)
            except Exception:  # noqa: BLE001 — 开关读取异常放行
                return PreCheckResult(valid=True)
        start = time.perf_counter()
        # fail-open: schema 缺失/非 dict → 跳过预检放行
        if not schema or not isinstance(schema, dict):
            return PreCheckResult(valid=True)

        errors: list[FieldError] = []
        try:
            self._validate_value(arguments, schema, "$", errors, depth=0)
        except RecursionError:
            errors.append(
                FieldError("$", "object", type(arguments).__name__,
                           f"参数嵌套深度超限（上限 {self._max_depth}）")
            )
        except Exception as exc:  # noqa: BLE001 — 校验异常 fail-open
            logger.warning("参数预检异常（fail-open 放行）: %s", exc)
            return PreCheckResult(valid=True)

        duration_ms = (time.perf_counter() - start) * 1000
        result = PreCheckResult(valid=not errors, errors=tuple(errors))
        # 预检失败事件落盘（不含参数明文，仅字段错误摘要）
        if not result.valid and self._event_store is not None:
            try:
                self._event_store.append(
                    self._session_id,
                    "task.precheck.failed",
                    {
                        "field_errors": [
                            {"field_path": e.field_path, "expected": e.expected_type,
                             "actual": e.actual_type}
                            for e in result.errors
                        ],
                        "duration_ms": round(duration_ms, 2),
                    },
                )
            except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open
                logger.warning("预检失败事件落盘失败（fail-open）", exc_info=True)
        return result

    def _validate_value(
        self,
        value: Any,
        schema: dict,
        path: str,
        errors: list[FieldError],
        *,
        depth: int,
    ) -> None:
        """递归校验单值（JSON Schema 子集: type/required/enum/properties/items）."""
        if depth > self._max_depth:
            errors.append(
                FieldError(path, "object", type(value).__name__,
                           f"嵌套深度超限（上限 {self._max_depth}）")
            )
            return

        # enum 校验
        if "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
            errors.append(
                FieldError(path, f"enum {schema['enum']}", type(value).__name__,
                           f"value {value!r} not in enum {schema['enum']}")
            )
            return  # 枚举非法不再继续其他校验

        # type 校验
        declared = schema.get("type")
        if declared:
            if isinstance(declared, list):
                ok = any(self._type_matches(value, t) for t in declared)
            else:
                ok = self._type_matches(value, declared)
            if not ok:
                errors.append(
                    FieldError(path, str(declared), type(value).__name__,
                               f"类型不匹配（期望 {declared}，实际 {type(value).__name__}）")
                )
                return

        # 嵌套: object → properties / array → items
        if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
            props = schema["properties"]
            # required 必填
            for req in schema.get("required", []) or []:
                if req not in value:
                    errors.append(
                        FieldError(f"{path}.{req}" if path != "$" else req,
                                   "required", "missing", f"字段 '{req}' required but missing")
                    )
            # 逐属性递归
            for key, val in value.items():
                if key in props:
                    child_path = f"{path}.{key}" if path != "$" else key
                    self._validate_value(val, props[key], child_path, errors, depth=depth + 1)
        elif isinstance(value, list) and isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                self._validate_value(
                    item, schema["items"], f"{path}[{i}]", errors, depth=depth + 1
                )

    @staticmethod
    def _type_matches(value: Any, declared: str) -> bool:
        """宽松类型匹配（int 兼容 bool 除外——JSON 里 bool 是 bool）."""
        if declared == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if declared == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if declared == "string":
            return isinstance(value, str)
        if declared == "boolean":
            return isinstance(value, bool)
        if declared == "object":
            return isinstance(value, dict)
        if declared == "array":
            return isinstance(value, list)
        if declared == "null":
            return value is None
        return True  # 未知类型放行（fail-open）


# 协议别名（tasks.md §1.2）
PreCheckProtocol = PreCheckLayer
