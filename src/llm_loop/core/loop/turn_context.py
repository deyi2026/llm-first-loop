"""Turn Context Snapshot（EVO-20260827-ed4c1350 批次1 / P0-A）.

user-turn 级上下文快照 mixin——统一"turn 边界一次生成、turn 内全部 tool
rounds 字节复用"的注入生命周期（取代 round 级重复检索注入）。
背景: 09c44093 实测 67 条/54.6K 字符 persisted_injection 膨胀（同帧 x18、
experience 类 x10），根因 = 检索挂 round 循环内 + 尾部 8 条文本比对幂等
窗口被 round 内消息滑出。本 mixin 的幂等是 turn_ref + injection_kind
身份级全局查重（重试/恢复 run 不膨胀）。
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.reference_injection import (
    DEFAULT_REFERENCE_AUTO_TURNS,
    reference_auto_decision,
    seen_injection_set,
)
from llm_loop.memory.retrieve import build_memory_messages

if TYPE_CHECKING:
    from collections.abc import Callable

    from llm_loop.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class _TurnContextMixin:
    """turn 级上下文快照（memory_snapshot 首个成员; experience tip 见 tool_exec）.

    依赖宿主（LoopEngine）属性/方法（mixin 惯例运行时解析）:
    memory / semantic_retriever / _runtime_memory_top_k() / _fault_feedback() /
    _record_program_fault() / _append_message_event()
    """

    if TYPE_CHECKING:
        # 宿主属性声明（LoopEngine.__init__/各 mixin 提供；err1210.py TYPE_CHECKING 先例）
        memory: MemoryStore
        semantic_retriever: Any | None
        _runtime_memory_top_k: Callable[[], int]
        _fault_feedback: Callable[[str, Exception], Message]
        _record_program_fault: Callable[[str], None]
        _append_message_event: Callable[[Any, Message], None]
        _record_action: Callable[[str, str, str], None]

    def _inject_turn_memory_snapshot(
        self, sess, user_text: str, turn_ref: int
    ) -> list[Message]:
        """memory 检索 user-turn 级快照（run 入口 = turn 边界执行一次）.

        本 turn 全部 tool rounds 复用同一字节（不重检索不重追加），下一
        user message 才生成新 snapshot。动态入参（top_k 等）在 turn 入口
        取值一次——快照语义，run 中途 adjust_strategy 下一 turn 生效。
        fail-open: 检索异常 → fault feedback + 程序故障计数（不阻塞 run）；
        持久化异常由 build 回退路径兜底（返回值仍供动态注入）。
        返回: 检索结果（供 build fail-open 回退；正常路径已持久化）。
        """
        # R3: 操作幂等覆盖“本轮因 K 门/去重而零注入”的路径；否则同 turn 重入会
        # 反复检索却没有 snapshot 消息可作为幂等证据。该标记仅在 in-memory Session
        # 上存活，真实跨 compact/restart 的 seen SoT 仍是持久 message metadata。
        if getattr(sess, "_memory_reference_checked_turn_ref", None) == turn_ref:
            return []
        sess._memory_reference_checked_turn_ref = turn_ref
        for _m in getattr(sess, "messages", []) or []:
            _md = getattr(_m, "metadata", None) or {}
            if (
                _md.get("injection_kind") == "memory_snapshot"
                and _md.get("turn_ref") == turn_ref
            ):
                return []

        _policy_messages = list(getattr(sess, "messages", []) or [])
        _auto_turns = int(
            getattr(
                getattr(self, "settings", None),
                "reference_auto_turns",
                DEFAULT_REFERENCE_AUTO_TURNS,
            )
        )
        _policy = reference_auto_decision(_policy_messages, auto_turns=_auto_turns)
        if _policy.human_turn_no == 0 and str(user_text or "").strip():
            # Direct/internal callers may invoke this helper before appending the user
            # message; production engine appends first. Use a synthetic view only for
            # gate calculation, never persist/duplicate the user text.
            # agent_trace_leak 2.2: 经单一真相源构造（生产代码零手工 origin_layer
            # 字面量）；本合成视图 never persist，仅 gate 计算，行为零变化。
            _policy = reference_auto_decision(
                _policy_messages
                + [
                    {
                        "role": "user",
                        "content": user_text,
                        "metadata": origin_metadata(InjectionLayer.USER_INSTRUCTION),
                    }
                ],
                auto_turns=_auto_turns,
            )
        if not _policy.allow_catalog:
            with contextlib.suppress(Exception):
                self._record_action(
                    "action.reference_auto_gate",
                    "suppressed",
                    f"source=memory;human_turn={_policy.human_turn_no};task_switch=0",
                )
            return []
        _seen = seen_injection_set(getattr(sess, "messages", []) or [])
        _suppressed: list[dict[str, str]] = []
        try:
            memory_msgs = build_memory_messages(
                user_text,
                self.memory,
                top_k=self._runtime_memory_top_k(),
                semantic_retriever=self.semantic_retriever,
                session_id=sess.session_id,
                seen_reference_keys=_seen,
                emit_seen_refs=_policy.task_switch,
                suppressed_out=_suppressed,
            )
            for _dup in _suppressed:
                with contextlib.suppress(Exception):
                    self._record_action(
                        "injection_duplicate_suppressed",
                        "suppressed",
                        f"source={_dup.get('source', 'memory')};ref={_dup.get('ref', '')};key={_dup.get('key', '')}",
                    )
        except Exception as exc:  # noqa: BLE001 — 记忆失败不阻塞（FR-MEM-03）
            # R8.10/E33: memory backend faults stay observable/retrievable; they are not
            # semantic memory and must never become a current-turn memory_snapshot prompt.
            self._fault_feedback("memory", exc)  # selfheal_log side effect only
            self._record_program_fault("memory")
            memory_msgs = []
        if not memory_msgs:
            return memory_msgs
        try:
            from llm_loop.core.loop.focus import wrap_injection

            query_fp = hashlib.sha1(
                (user_text or "").encode("utf-8", "replace")
            ).hexdigest()[:12]
            # 幂等: 同 turn 同 kind 已持久化 → 跳过（run 重入/重试不膨胀）
            _dup = any(
                (getattr(_pm, "metadata", None) or {}).get("turn_ref") == turn_ref
                and (getattr(_pm, "metadata", None) or {}).get("injection_kind")
                == "memory_snapshot"
                for _pm in sess.messages
            )
            if not _dup:
                for _m in memory_msgs:
                    _c = str(getattr(_m, "content", "") or "")
                    if not _c:
                        continue
                    _d = _m.to_llm_dict()
                    _layer = (
                        InjectionLayer.STATUS
                        if getattr(_m, "source", None) == MessageSource.SYSTEM
                        else InjectionLayer.REFERENCE
                    )
                    _wrapped = (
                        wrap_injection(_c, layer=_layer)
                        if _d.get("role") == "system"
                        else _c
                    )  # 无 anchor: 持久化体字节稳定（anchor 含每轮变化内容）
                    _ref_md = dict(getattr(_m, "metadata", None) or {})
                    _persist_msg = Message(
                        role="user",
                        content=_wrapped,
                        source=MessageSource.USER,
                        metadata=origin_metadata(
                            _layer,
                            injection_kind="memory_snapshot",
                            persisted_injection=True,
                            turn_ref=turn_ref,
                            query_fp=query_fp,
                            reference_keys=list(_ref_md.get("reference_keys") or []),
                            reference_full_keys=list(_ref_md.get("reference_full_keys") or []),
                            reference_source=_ref_md.get("reference_source", "memory"),
                            reference_frame_count=int(_ref_md.get("reference_frame_count") or 0),
                            **(
                                {
                                    k: _ref_md[k]
                                    for k in (
                                        "reference_key",
                                        "reference_ref",
                                        "reference_full",
                                        "reference_duplicate",
                                    )
                                    if k in _ref_md
                                }
                            ),
                        ),
                    )
                    sess.messages.append(_persist_msg)
                    self._append_message_event(sess, _persist_msg)
        except Exception:  # noqa: BLE001 — 持久化失败 fail-open（build 回退动态注入）
            logger.warning("memory turn 快照持久化失败（fail-open）", exc_info=True)
        return memory_msgs
