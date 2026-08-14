"""LoopEngine 压缩另存 mixin（M53 延续：_archive_sink 从 engine.py 拆出，纯重构行为零变化）.

触发时机：context trim 时把被裁剪消息原文完整另存 ArchiveStore + context.compressed 事件；
另存/摘要失败 fail-open（如实 fault_feedback 进会话，不抛穿主循环）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm_loop.core.message import Message

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine


class _ArchiveMixin:

    def _archive_sink(self: LoopEngine, session_id: str, msg: Message) -> None:
        """压缩另存回调（T22）: 将被丢弃的消息原文完整另存到 ArchiveStore.

        合规变体 A（方案 3 对话历史语义摘要的合规落地）: SUMMARY_MODE!=off 时，
        压缩另存后自动回填档案语义摘要（summarize_archive）——严格限定在
        RULE-AI-00 自动摘要边界内: 只作用于已压缩存档的档案条目、回填 summary 字段、
        不注入当前上下文、不丢信息、可经 search_archive(with_summary=true) 检索。
        """
        if self.archive is None:
            return
        try:
            entry = self.archive.archive(
                session_id,
                role=msg.role,
                source=msg.source.value,
                content=msg.content,
                tool_name=msg.tool_name,
                tool_call_id=msg.tool_call_id,
                status=msg.status.value if msg.status else None,
                reasoning_content=getattr(msg, "reasoning_content", None) or None,
            )
            # D1: context.compressed 事件（与原文另存同一事务点，fail-open）——
            # archive_ref 优先 tool_call_id（与 web 展开端点 get_by_tool_call_id 契约一致）
            self._event_append(
                session_id,
                "context.compressed",
                {
                    "archive_ref": msg.tool_call_id or getattr(entry, "id", None),
                    "tool_call_id": msg.tool_call_id,
                    "msg_seq": self._resolve_msg_seq(session_id, msg),
                    "chars": getattr(entry, "chars", None) or len(msg.content),
                },
            )
            # RULE-AI-00 自动摘要边界内: 压缩档案自动回填语义摘要（async 后台/off 跳过）
            if (
                self.summarizer is not None
                and getattr(self.summarizer, "mode", "off") != "off"
            ):
                self.summarizer.summarize_archive(entry.id, msg.content, self.archive)
        except Exception as exc:
            # C3（PREFERENCE_1）: 压缩另存/摘要失败如实注入会话（AI 可感知，不静默——
            # 被压缩消息可能无法找回）。注入失败静默（尽力而为）。
            logger.warning("压缩另存/摘要失败（fail-open）", exc_info=True)
            from contextlib import suppress

            with suppress(Exception):
                s = self.session.load(session_id)
                s.messages.append(self._fault_feedback("archive_sink", exc))
                self.session.save(s)
