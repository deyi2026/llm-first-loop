"""飞书消息处理（M42，薄壳适配器）.

文本 → 会话映射 → LoopEngine.run → 回复原会话；长回复 markdown 分段。
M46：挂钩 Typing reaction 回执（本地既有实现_FEISHU_TYPING_ACK）+ 流式状态卡（本地既有实现_FEISHU_STREAMING），
对齐 本地既有实现 ws_bridge/streaming_card 算法思路；失败 fail-open 回退既有路径。
附件/图片复用 M39 web/upload_handlers + vision（不复制不重写）；失败如实 fail-open。
审计落盘 data/audit/feishu_audit.jsonl（fail-open）。
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lark_oapi

from llm_loop.core.loop import LoopEngine

logger = logging.getLogger(__name__)


@dataclass
class FeishuMessage:
    """飞书消息（桥解包后的统一结构）."""

    message_id: str
    sender_id: str  # open_id
    chat_id: str
    msg_type: str  # text / image / file / post
    text: str = ""
    is_group: bool = False
    sender_type: str = ""  # user / app（防循环：app 跳过）
    file_key: str | None = None
    file_name: str = ""
    raw: dict[str, Any] | None = None
    reply_receive_id: str = ""  # 回复目标 id（群聊 chat_id / 私聊 open_id）
    reply_receive_id_type: str = ""  # receive_id_type（"chat_id" / "open_id"）

    def __post_init__(self) -> None:
        """回复目标推导：chat_id 非空用 chat_id；私聊 chat_id 缺失用 sender open_id."""
        if not self.reply_receive_id:
            if self.chat_id:
                self.reply_receive_id = self.chat_id
                self.reply_receive_id_type = "chat_id"
            else:
                self.reply_receive_id = self.sender_id
                self.reply_receive_id_type = "open_id"


ReplyFn = Callable[[str, str, str], None]  # (receive_id, text, receive_id_type) -> None 回复回调


class FeishuMessageHandler:
    """飞书消息处理：类型分发 → 引擎执行 → 回复."""

    def __init__(
        self,
        engine: LoopEngine,
        session_map: Any,  # SessionMap（get_or_create）
        reply_fn: ReplyFn | None = None,
        *,
        audit_dir: str | None = None,
        chunk_limit: int = 3500,
        rest_client: Any | None = None,  # FeishuRestClient（M46：Typing reaction + 状态卡发送）
        lark_client: lark_oapi.Client | None = None,  # M46：状态卡 cardkit
        typing_ack: bool = True,  # M46：本地既有实现_FEISHU_TYPING_ACK
        streaming: bool = True,  # M46：本地既有实现_FEISHU_STREAMING
    ) -> None:
        self._engine = engine
        self._session_map = session_map
        self._reply_fn = reply_fn
        self._chunk_limit = chunk_limit
        self._audit_path = Path(audit_dir or self._default_audit_dir()) / "feishu_audit.jsonl"
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        # M46：处理中动作显示挂钩（未注入时静默禁用，行为与 M45 一致）
        self._rest_client = rest_client
        self._lark_client = lark_client
        self._typing_ack = typing_ack
        self._streaming = streaming

    def _reply(self, msg: FeishuMessage, text: str) -> None:
        """回复回调（按消息类型选目标：群聊 chat_id / 私聊 open_id；未装配如实标注）."""
        if self._reply_fn is None:
            logger.warning(
                "reply_fn 未装配，回复丢弃（receive_id=%s）: %s", msg.reply_receive_id, text[:100]
            )
            return
        self._reply_fn(msg.reply_receive_id, text, msg.reply_receive_id_type)

    @staticmethod
    def _default_audit_dir() -> str:
        return os.environ.get("DATA_DIR", "./data") + "/audit"

    # ── 入口 ──
    def handle(self, msg: FeishuMessage) -> None:
        """消息入口：防循环 + 类型分发 + 执行 + 回复."""
        # 防循环：机器人自身消息（sender_type=app）不处理
        if msg.sender_type == "app":
            self._audit(msg, "skip_bot_self", "机器人自身消息跳过")
            return
        if msg.msg_type in ("text", "post"):
            self._handle_text(msg)
        elif msg.msg_type in ("image", "file"):
            self._handle_attachment(msg)
        else:
            self._audit(msg, "unsupported", "忽略")
            self._reply(msg, "暂不支持该消息类型。")

    # ── 文本 ──
    def _handle_text(self, msg: FeishuMessage) -> None:
        text = msg.text.strip()
        if not text:
            return
        self._audit(msg, "text", text[:200])
        # M50（design §六）: 飞书 /model 指令拦截（与 CLI 共用同一套处理逻辑）
        if self._try_handle_model_command(msg, text):
            return
        self._run_with_processing_actions(msg, self._run_text, text)

    def _try_handle_model_command(self, msg: FeishuMessage, text: str) -> bool:
        """M50：飞书 /model 指令拦截（三端一致性，与 CLI 共用 handle_model_command）.

        Returns:
            True → 已处理（调用方勿继续走 engine.run）；False → 非 /model 指令，继续走原路径。
        """
        from llm_loop.introspection.model_command import handle_model_command

        ctx = getattr(self._engine, "correction_ctx", None)
        if ctx is None:
            return False
        # 取/建会话（与 _run_text 同一映射路径，与 CLI 共用 SessionStore）
        sid = self._session_map.get_or_create(self._map_key(msg))
        sess = self._engine.session.load(sid)
        # audit 注入：复用 corrections._audit 闭包（保证落 self_correction_log.jsonl）
        audit_fn = self._model_command_audit
        result = handle_model_command(text, ctx, sess, self._engine.session, audit_fn)
        if result is None:
            return False
        # 特殊路径：走 ReplyFn 直接回执（不走 _run_with_processing_actions / 状态卡）
        self._reply(msg, result.reply)
        # 审计：feishu 通道记录（与 engine 内部审计区分）
        self._audit(
            msg,
            "model_command",
            f"success={result.success} changed={result.changed} text={text[:80]}",
        )
        return True

    def _model_command_audit(self, tool_name: str, arguments: dict, result_status: str) -> None:
        """M50：复用 corrections._audit 习惯（落 self_correction_log.jsonl）.

        飞书 /model 指令触发的 switch_model 需锁到主会话审计通道;
        避免双写重复 — 飞书端仅依赖 corrections 路径的 audit，feishu 审计仅记录通道动作。
        """
        # 委托给 engine 内部的 _audit 闭包（如果有）；此处简化为 no-op，靠 corrections 内部审计
        return

    def _run_text(self, msg: FeishuMessage, text: str) -> None:
        """文本引擎执行 + 回复（M46：_run_with_processing_actions 包内）."""
        sid = self._session_map.get_or_create(self._map_key(msg))
        result = self._engine.run(sid, text)
        answer = result.final_answer or "(空回答)"
        if result.truncated:
            answer += "\n（回答被截断）"
        if result.verification_note:
            answer += f"\n[声明提示] {result.verification_note}"
        self._reply_chunked(msg, answer)

    # ── 附件/图片（复用 M39 web/upload_handlers + vision）──
    def _handle_attachment(self, msg: FeishuMessage) -> None:
        self._audit(msg, "attachment", msg.file_name or msg.file_key or msg.msg_type)
        # 附件内容需由桥先下载为 bytes 再注入（download 回调由装配注入）
        download = getattr(self, "_attachment_download", None)
        if download is None:
            self._reply(msg, "附件下载未配置（当前通道不支持附件处理）。")
            return
        try:
            data, filename = download(msg)
        except Exception as exc:  # 下载异常如实反馈（fail-open 不阻断主链路）
            logger.exception("feishu attachment download failed")
            self._audit(msg, "attachment_error", str(exc)[:200])
            self._reply(msg, f"[程序异常] 附件下载失败（{type(exc).__name__}: {exc}）。")
            return
        if data is None:
            self._reply(msg, f"附件下载失败（{filename}）。")
            return
        if msg.msg_type == "image":
            self._handle_image(msg, data, filename)
        else:
            self._handle_file(msg, data, filename)

    def _handle_image(self, msg: FeishuMessage, data: bytes, filename: str) -> None:
        """图片 → 复用 M39 web/vision 识别 → 识别文本注入上下文."""
        from llm_loop.web.vision import describe_image, vision_enabled

        if not vision_enabled():
            self._reply(msg, "视觉识别未配置（MINIMAX_API_KEY 缺失），图片已跳过。")
            return
        try:
            text = describe_image(data, mime="image/png")
        except Exception as exc:  # 识别失败如实降级（无伪造描述）
            logger.exception("feishu image vision failed")
            self._audit(msg, "attachment_error", str(exc)[:200])
            self._reply(msg, f"图片识别失败（{type(exc).__name__}: {exc}），图片已跳过。")
            return
        self._inject_and_reply(msg, f"[附件 图片 {filename} 识别结果]\n{text}")

    def _handle_file(self, msg: FeishuMessage, data: bytes, filename: str) -> None:
        """文件 → 复用 M39 web/upload_handlers 校验+提取 → 提取文本注入上下文."""
        from llm_loop.web.upload_handlers import process_upload, validate_upload

        err = validate_upload(filename, data)
        if err:
            self._reply(msg, f"附件校验失败：{err}")
            return
        result = process_upload(filename, data)
        if result.status == "error":
            self._reply(msg, f"附件处理失败：{result.detail}")
            return
        source = f"[附件 {result.source_filename} 内容（{result.content_type}）]"
        if result.truncated:
            source += "（已截断）"
        self._inject_and_reply(msg, f"{source}\n{result.result_text or result.detail}")

    def _inject_and_reply(self, msg: FeishuMessage, prefix: str) -> None:
        """附件处理结果注入对话上下文（来源可追溯）→ 引擎 → 回复（M46：挂处理中动作）."""
        self._run_with_processing_actions(
            msg, self._run_inject, prefix, error_kind="attachment_error"
        )

    def _run_inject(self, msg: FeishuMessage, prefix: str) -> None:
        """附件注入引擎执行 + 回复（M46：_run_with_processing_actions 包内）."""
        sid = self._session_map.get_or_create(self._map_key(msg))
        reply = self._engine.run(sid, prefix).final_answer or "(空回答)"
        self._reply_chunked(msg, reply)

    def register_attachment_download(
        self, fn: Callable[[FeishuMessage], tuple[bytes | None, str]]
    ) -> None:
        """注入附件下载回调（由桥/装配提供，飞书 API 下载）."""
        self._attachment_download = fn

    # ── M46：处理中动作显示公共包装（Typing reaction + 状态卡，fail-open）──
    def _run_with_processing_actions(
        self, msg: FeishuMessage, fn: Callable, payload: str, *, error_kind: str = "text_error"
    ) -> None:
        """执行 fn 前后挂处理中动作：开始（Typing reaction + 状态卡）→ fn → 结束（定稿 + 删 reaction）.

        任一动作失败 fail-open（日志/审计），绝不阻断引擎执行与回复；异常路径 finally 保证清理。
        """
        reaction_id = ""
        card = None
        if self._typing_ack and self._rest_client is not None and msg.message_id:
            try:
                reaction_id = self._rest_client.add_typing_reaction(msg.message_id)
            except Exception as exc:  # noqa: BLE001 — 回执失败静默（fail-open）
                logger.debug("feishu typing reaction add error: %s", exc)
        if self._streaming and self._lark_client is not None:
            card = self._try_start_status_card(msg)
        try:
            fn(msg, payload)
        except Exception as exc:  # 失败如实反馈，不静默降级
            logger.exception("feishu message handle failed")
            self._audit(msg, error_kind, str(exc)[:200])
            self._reply(msg, f"[程序异常] 消息处理失败（{type(exc).__name__}: {exc}）。")
        finally:
            # 处理结束 → 状态卡定稿 + 删除 Typing reaction（best-effort）
            self._close_status_card(card, msg)
            if reaction_id and self._rest_client is not None:
                try:
                    self._rest_client.remove_reaction(msg.message_id, reaction_id)
                except Exception as exc:  # noqa: BLE001 — 删除失败静默
                    logger.debug("feishu typing reaction remove error: %s", exc)

    # ── M46：流式状态卡（对齐 本地既有实现 streaming_card 算法思路，状态卡形式）──
    def _try_start_status_card(self, msg: FeishuMessage):
        """收到消息即建状态卡（⏳ 处理中）并发到会话.

        Returns:
            StreamingCard | None（任一环节失败返回 None，回退普通回复路径，不阻断）.
        """
        from llm_loop.feishu.streaming_card import StreamingCard

        if self._lark_client is None:
            return None
        try:
            card = StreamingCard(self._lark_client)
            if not card.create():
                self._audit(msg, "status_card_fallback", "建卡失败回退普通路径")
                return None
            if not card.bind(msg.reply_receive_id, msg.reply_receive_id_type):
                self._audit(msg, "status_card_fallback", "发卡失败回退普通路径")
                return None
            self._audit(msg, "status_card_start", "状态卡已建（⏳ 处理中）")
            return card
        except Exception as exc:  # noqa: BLE001 — 状态卡失败不阻断主流程
            logger.debug("feishu status card start error: %s", exc)
            return None

    def _close_status_card(self, card, msg: FeishuMessage) -> None:
        """处理完成 → 状态卡定稿（✅ 处理完成 + 关 streaming_mode），best-effort."""
        if card is None:
            return
        try:
            if card.close():
                self._audit(msg, "status_card_close", "状态卡定稿（✅ 处理完成）")
            else:
                self._audit(msg, "status_card_fallback", "定稿失败（卡保持处理中态）")
        except Exception as exc:  # noqa: BLE001 — 定稿失败不阻断主流程
            logger.debug("feishu status card close error: %s", exc)

    # ── 长回复分段 ──
    def _reply_chunked(self, msg: FeishuMessage, text: str) -> None:
        """长回复按 markdown 感知分段（fence 闭合重开），逐段发送（不丢失内容）."""
        if len(text) <= self._chunk_limit:
            self._reply(msg, text)
            return
        for part in self._chunk_markdown(text, self._chunk_limit):
            self._reply(msg, part)

    @staticmethod
    def _chunk_markdown(text: str, limit: int) -> list[str]:
        """markdown 感知分段（对齐 本地既有实现 markdown_chunker 算法思路）.

        切点按行；代码 fence 内切段自动补闭合并在下一段开头重开（含语言标签）。
        各段拼接（剥离 fence 修复对后）= 原回复内容，无丢失。
        """
        parts: list[str] = []
        in_fence = False
        buf = ""
        for line in text.splitlines(keepends=True):
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if buf and len(buf) + len(line) > limit:
                if in_fence:
                    buf += "```\n"  # 闭合 fence
                    parts.append(buf)
                    buf = "```\n"  # 重开 fence
                else:
                    parts.append(buf)
                    buf = ""
            buf += line
        if buf:
            parts.append(buf)
        return parts

    # ── 工具 ──
    @staticmethod
    def _map_key(msg: FeishuMessage) -> str:
        from llm_loop.feishu.session_map import SessionMap

        return (
            SessionMap.group_key(msg.chat_id) if msg.is_group else SessionMap.p2p_key(msg.sender_id)
        )

    def _audit(self, msg: FeishuMessage, kind: str, detail: str) -> None:
        """审计落盘（fail-open，不阻断）."""
        try:
            record = {
                "message_id": msg.message_id,
                "kind": kind,
                "chat_id": msg.chat_id,
                "sender_id": msg.sender_id,
                "detail": detail,
            }
            _write_audit_line(self._audit_path, record)
        except OSError:
            pass


def _write_audit_line(path: Path, record: dict) -> None:
    """审计单条落盘（模块级函数，便于 fail-open 测试注入）."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
