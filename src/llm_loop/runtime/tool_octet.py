"""Tool octet 观测流（M2-G1）：模块级 sink 持有 + terminal receipt 记录 observer.

纯观测模块、无业务依赖；落盘 writer 单一 SoT 是
introspection.status.ArchitectureStatusProvider._write_audit（经 factory 装配
注入其薄公共入口 append_audit_line），本模块不自建任何 open/append 实现。

冻结契约（design M2-R1/M3-R1/勘误二）:
- record_tool_octet 冻结 API 不加 sink 参数；调用点不依赖 ArchitectureStatusProvider；
- 未注册 sink 时 observer 静默丢弃该条（fail-open）；
- 开关门控在 observer 首行（env LFL_TOOL_OCTET，默认 0=关），装配不判环境；
- args_digest 输入 = canonical 化 arguments（sort_keys）；result_digest 输入 =
  ToolResult.content 全文（hash 前绝不截断）；digest 为 one-way 摘要，
  非 secret-redaction / 安全边界（低熵原文可被字典枚举，禁止称"不可逆脱敏"）；
- ts = observer 记录 terminal receipt 的时刻（datetime.now(UTC).isoformat()，
  与仓库 _now() 同语义）——非并发工具真实完成绝对先后；
- route_context 由本模块内部取 RouteContext 进程级单例，调用方不传；
- 缺 tool_call_id 的输入不入本流；fail-open 全吞、无 failure 计数器。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime

from llm_loop.runtime.route_context import get_route_context

OctetSink = Callable[[str, dict], None]

_STREAM = "tool_octet.jsonl"

_SINK: OctetSink | None = None


def register_octet_sink(fn: OctetSink | None) -> None:
    """模块级 sink 注册（factory 装配一次性调用；传 None 注销）."""
    global _SINK
    _SINK = fn


def get_octet_sink() -> OctetSink | None:
    """读取当前 sink（observer 内部取用；未注册返回 None）."""
    return _SINK


def _now() -> str:
    """仓库 _now() 同语义：UTC ISO8601，observer receipt 时刻."""
    return datetime.now(UTC).isoformat()


def _digest(text: str | None) -> str | None:
    """one-way 摘要（≥128bit）：全文 hash 前绝不截断；None → None."""
    if text is None:
        return None
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def record_tool_octet(
    *,
    session_id: str,
    round_index: int,
    tool_call_id: str,
    tool_name: str,
    args: dict,
    status: str,
    duration_ms: float | None = None,
    result_content: str | None = None,
    reason_code: str | None = None,
) -> None:
    """记录一条 terminal tool receipt 观测（顶层恰好 8 逻辑字段，冻结 schema）.

    fail-open 全吞：任何异常静默降级，绝不向上抛、绝不改变调用方控制流。
    """
    if os.environ.get("LFL_TOOL_OCTET", "0") != "1":
        return
    if not tool_call_id:  # 缺 id 的协议异常输入不入本流（design §1.2）
        return
    try:
        args_canonical = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        ctx = get_route_context()
        record = {
            "ts": _now(),
            "session_id": session_id,
            "round_index": round_index,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args_digest": _digest(args_canonical),
            "route_context": {"instance": ctx.instance, "zone": ctx.zone, "route": ctx.route},
            "outcome": {
                "status": status,
                "duration_ms": duration_ms,
                "result_digest": _digest(result_content),
                "reason_code": reason_code,
            },
        }
        sink = get_octet_sink()
        if sink is None:  # 未注册：静默丢弃（fail-open）
            return
        sink(_STREAM, record)
    except Exception:  # noqa: BLE001 — fail-open 全吞（无计数器，冻结裁决）
        return
