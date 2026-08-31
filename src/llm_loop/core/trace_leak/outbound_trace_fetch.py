"""outbound_trace_fetch 带外化检索通道（tasks 3.8，design C3，spec 5.3.1-3）.

外部 agent 轨迹的合法进入面：**用户显式请求触发**，以 reference 层返回
（携带原始会话归属标识），不落盘为 user 消息、不获得指令权。

- 无用户显式请求时本接口零调用（事件日志可验证零注入，spec 5.3.1-3b）。
- 返回 TraceView 为 reference 层视图（build 期经既有预算链以 REFERENCE
  优先级进入附录，不触碰 user 身份）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceView:
    """外部轨迹只读视图（reference 层；携带原始会话归属标识）。"""

    ref: str
    origin_session_id: str
    content: str
    metadata: dict

    def as_reference_frame(self) -> dict:
        """以 reference 层帧形态输出（供 build 预算链消费；不获指令权）。"""
        return {
            "role": "user",  # 载体形态（对齐 memory_snapshot 先例）
            "content": self.content,
            "metadata": dict(self.metadata),
        }


_FETCH_AUDIT_LOG: list[dict] = []


def fetch_external_trace(ref: str) -> TraceView:
    """用户显式请求触发的外部轨迹检索（带外化通道）.

    ref 形态 ``external://<session_id>#<seq_range>``；返回 reference 层视图。
    本函数必须仅由用户显式请求的工具路径调用（调用方负责触发条件）；
    每次调用记录审计（供"零请求零进入"事件日志核验）。
    """
    ref = str(ref or "")
    origin_sid = "?"
    if ref.startswith("external://"):
        origin_sid = ref[len("external://"):].partition("#")[0] or "?"
    view = TraceView(
        ref=ref,
        origin_session_id=origin_sid,
        content="",  # MVP: 检索体由外部轨迹快照存储接入时填充（本期接口契约先行）
        metadata=origin_metadata(
            InjectionLayer.REFERENCE,
            injection_kind="outbound_trace_fetch",
            external_trace_ref=ref,
            external_trace_origin_session=origin_sid,
        ),
    )
    _FETCH_AUDIT_LOG.append({"ref": ref, "origin_session_id": origin_sid})
    return view


def fetch_audit_log() -> list[dict]:
    """带外检索审计（核验 spec 5.3.1-3b：无请求零进入）。"""
    return list(_FETCH_AUDIT_LOG)
