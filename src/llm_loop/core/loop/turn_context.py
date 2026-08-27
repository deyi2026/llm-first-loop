"""Turn Context Snapshot（EVO-20260827-ed4c1350 批次1 / P0-A）.

user-turn 级上下文快照 mixin——统一"turn 边界一次生成、turn 内全部 tool
rounds 字节复用"的注入生命周期（取代 round 级重复检索注入）。
背景: 09c44093 实测 67 条/54.6K 字符 persisted_injection 膨胀（同帧 x18、
experience 类 x10），根因 = 检索挂 round 循环内 + 尾部 8 条文本比对幂等
窗口被 round 内消息滑出。本 mixin 的幂等是 turn_ref + injection_kind
身份级全局查重（重试/恢复 run 不膨胀）。
"""

from __future__ import annotations

import hashlib
import logging

from llm_loop.core.message import Message, MessageSource
from llm_loop.memory.retrieve import build_memory_messages

logger = logging.getLogger(__name__)


class _TurnContextMixin:
    """turn 级上下文快照（memory_snapshot 首个成员; experience tip 见 tool_exec）.

    依赖宿主（LoopEngine）属性/方法（mixin 惯例运行时解析）:
    memory / semantic_retriever / _runtime_memory_top_k() / _fault_feedback() /
    _record_program_fault() / _append_message_event()
    """

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
        # T5(GPT 复审): 操作幂等——消息幂等 ≠ 操作幂等。重入若本 turn 已持久化
        # snapshot，直接返回不检索不 mark_injected（防污染 memory 使用统计：
        # 12 次重入曾致 search/mark_injected 各 12 次而消息仅 1 条）。
        for _m in getattr(sess, "messages", []) or []:
            _md = getattr(_m, "metadata", None) or {}
            if (
                _md.get("injection_kind") == "memory_snapshot"
                and _md.get("turn_ref") == turn_ref
            ):
                return []
        try:
            memory_msgs = build_memory_messages(
                user_text,
                self.memory,
                top_k=self._runtime_memory_top_k(),
                semantic_retriever=self.semantic_retriever,
                session_id=sess.session_id,
            )
        except Exception as exc:  # noqa: BLE001 — 记忆失败不阻塞（FR-MEM-03）
            memory_msgs = [self._fault_feedback("memory", exc)]
            self._record_program_fault("memory")
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
                    _wrapped = (
                        wrap_injection(_c) if _d.get("role") == "system" else _c
                    )  # 无 anchor: 持久化体字节稳定（anchor 含每轮变化内容）
                    _persist_msg = Message(
                        role="user",
                        content=_wrapped,
                        source=MessageSource.USER,
                        metadata={
                            "persisted_injection": True,
                            "injection_kind": "memory_snapshot",
                            "turn_ref": turn_ref,
                            "query_fp": query_fp,
                        },
                    )
                    sess.messages.append(_persist_msg)
                    self._append_message_event(sess, _persist_msg)
        except Exception:  # noqa: BLE001 — 持久化失败 fail-open（build 回退动态注入）
            logger.warning("memory turn 快照持久化失败（fail-open）", exc_info=True)
        return memory_msgs
