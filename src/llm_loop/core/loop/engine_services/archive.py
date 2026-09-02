"""ArchiveService——压缩另存职责服务（R9-B5-W4-02d：_ArchiveMixin 退役；宿主面显式经 self._host 标注，沿 runtime_params v4 惯例）.

触发时机：context trim 时把被裁剪消息原文完整另存 ArchiveStore + context.compressed 事件；
另存/摘要失败 fail-open（如实 fault_feedback 进会话，不抛穿主循环）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm_loop.core.message import Message

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine


class ArchiveService:
    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _archive_feedback_session(self, session_id: str):
        """archive故障反馈优先复用当前run的token-bound Session；run外仍从磁盘加载。"""
        from llm_loop.core.run_context import current_session_id

        if current_session_id.get() == session_id:
            try:
                with self._host._run_state_mgr.guard:
                    active = self._host._run_sessions.get(session_id)
                if active is not None:
                    return active
            except Exception:  # noqa: BLE001 — 绑定表不可用时回退既有load路径
                logger.debug("archive故障反馈解析active session失败，回退load", exc_info=True)
        return self._host.session.load(session_id)

    def _archive_sink(self, session_id: str, msg: Message) -> None:
        """压缩另存回调（T22）: 将被丢弃的消息原文完整另存到 ArchiveStore.

        合规变体 A（方案 3 对话历史语义摘要的合规落地）: SUMMARY_MODE!=off 时，
        压缩另存后自动回填档案语义摘要（summarize_archive）——严格限定在
        RULE-AI-00 自动摘要边界内: 只作用于已压缩存档的档案条目、回填 summary 字段、
        不注入当前上下文、不丢信息、可经 search_archive(with_summary=true) 检索。
        """
        msg_seq = self._host._resolve_msg_seq(session_id, msg)

        # INJECTION-GOVERNANCE R5: identity Q&A remains exact archive truth but must
        # not become durable summary detail. Determine episode membership from the
        # canonical session sequence; no extra per-session state is introduced.
        _identity_start: int | None = None
        if msg_seq is not None:
            try:
                from llm_loop.core.identity_summary import identity_episode_start

                _identity_session = None
                try:
                    with self._host._run_state_mgr.guard:
                        _identity_session = self._host._run_sessions.get(session_id)
                except Exception:  # noqa: BLE001 — run binding unavailable: read fallback
                    _identity_session = None
                if _identity_session is None:
                    _identity_session = self._host.session.load(session_id)
                _identity_start = identity_episode_start(_identity_session.messages, msg_seq)
            except Exception:  # noqa: BLE001 — summary hygiene fail-open must not lose archive bytes
                logger.debug("identity summary episode detection failed (fail-open)", exc_info=True)
                _identity_start = None

        evidence_ref: str | None = None
        registry = getattr(self._host, "registry", None)
        try:
            if registry is not None and getattr(
                registry, "evidence_history_capture_enabled", False
            ):
                evidence_ref = registry.capture_archived_message(
                    session_id=session_id,
                    message=msg,
                    msg_seq=msg_seq,
                )
        except Exception:  # noqa: BLE001 - enforce must not shrink bytes without canonical recovery
            logger.warning("压缩消息 Evidence capture 失败；enforce 模式拒绝继续压缩", exc_info=True)
            raise

        if self._host.archive is None:
            if evidence_ref:
                self._host._event_append(
                    session_id,
                    "context.compressed",
                    {
                        "archive_ref": None,
                        "evidence_ref": evidence_ref,
                        "tool_call_id": msg.tool_call_id,
                        "msg_seq": msg_seq,
                        "chars": len(msg.content),
                    },
                )
            return
        try:
            _summary_override: str | None = None
            _facts_override: list[str] | None = None
            _paths_override: list[str] | None = None
            _summary_source_override: str | None = None
            if _identity_start is not None:
                from llm_loop.core.identity_summary import render_identity_summary_placeholder

                _summary_override = (
                    render_identity_summary_placeholder(1)
                    if msg_seq == _identity_start
                    else ""
                )
                _facts_override = []
                _paths_override = []
                _summary_source_override = "identity_filtered"

            entry = self._host.archive.archive(
                session_id,
                role=msg.role,
                source=msg.source.value,
                content=msg.content,
                tool_name=msg.tool_name,
                tool_call_id=msg.tool_call_id,
                status=msg.status.value if msg.status else None,
                reasoning_content=getattr(msg, "reasoning_content", None) or None,
                summary_override=_summary_override,
                key_facts_override=_facts_override,
                key_paths_override=_paths_override,
                summary_source_override=_summary_source_override,
            )
            # D1: context.compressed 事件（legacy archive + provider-neutral Evidence ref）.
            self._host._event_append(
                session_id,
                "context.compressed",
                {
                    "archive_ref": msg.tool_call_id or getattr(entry, "id", None),
                    "evidence_ref": evidence_ref,
                    "tool_call_id": msg.tool_call_id,
                    "msg_seq": msg_seq,
                    "chars": getattr(entry, "chars", None) or len(msg.content),
                },
            )
            # RULE-AI-00 自动摘要边界内: 压缩档案自动回填语义摘要（async 后台/off 跳过）
            if (
                _identity_start is None
                and self._host.summarizer is not None
                and getattr(self._host.summarizer, "mode", "off") != "off"
            ):
                self._host.summarizer.summarize_archive(entry.id, msg.content, self._host.archive)
        except Exception as exc:
            # R8.10/E33: archive failure is runtime state. Preserve selfheal/status/action
            # observability, but do not write program-authored fault prose into session
            # history (which would gain prompt authority on this or later turns).
            logger.warning("压缩另存/摘要失败（fail-open）", exc_info=True)
            from contextlib import suppress

            with suppress(Exception):
                self._host._fault_feedback("archive_sink", exc)  # selfheal_log side effect only
                self._host._record_program_fault("archive_sink")
                self._host._record_action("archive_sink", "fault_observed", type(exc).__name__)
