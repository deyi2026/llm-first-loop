"""企微消息处理（M0-5，平移 feishu/handlers.py 问答路径）.

文本 → 会话映射 → LoopEngine.run → 回复原会话（绑定同一次回调的 req_id——
企微协议硬要求，飞书侧无此字段）。
回复体由 bridge 侧构造（markdown），本模块只做内容预算（20480 字节协议上限）。
审计落盘 data/audit/wecom_audit.jsonl（fail-open）。

线程边界（设计文档 §4.4）：本模块全部方法运行在 worker 线程（bridge
_worker_loop 内），绝不在 SDK 回调（asyncio loop 线程）内执行——LLM 推理
可达分钟级，阻塞 loop 会停发心跳被服务端断开（飞书桥实测事故）。
"""

import json
import logging
import os
import time
from pathlib import Path

from llm_loop.core.loop import LoopEngine

from .messages import WeComMessage, WeComReplyFn
from .session_map import WeComSessionMap

logger = logging.getLogger(__name__)


class WeComMessageHandler:
    """企微消息处理：类型分发 → 引擎执行 → 回复（绑定 req_id）."""

    def __init__(
        self,
        engine: LoopEngine,
        session_map: WeComSessionMap,
        reply_fn: WeComReplyFn,
        *,
        audit_dir: str | None = None,
        chunk_limit: int = 20480,
    ) -> None:
        self._engine = engine
        self._session_map = session_map
        self._reply_fn = reply_fn
        self._chunk_limit = chunk_limit  # markdown.content 协议字节上限（设计文档 §2.2）
        self._audit_path = Path(audit_dir or self._default_audit_dir()) / "wecom_audit.jsonl"
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _default_audit_dir() -> str:
        return os.environ.get("DATA_DIR", "./data") + "/audit"

    # ── 入口 ──
    def handle(self, msg: WeComMessage) -> None:
        """消息入口：防循环 + 类型分发 + 执行 + 回复."""
        # 防循环：机器人自身消息不处理
        if msg.sender_type == "app":
            self._audit(msg, "skip_bot_self", "机器人自身消息跳过")
            return
        if msg.msg_type == "text":
            self._handle_text(msg)
        elif msg.msg_type in ("image", "video", "mixed", "voice", "file"):
            # M0 暂不接附件（M1-3 落地 download_file→vision）；显式回执不支持，
            # 不静默丢弃（video 是 SDK 会静默吞掉的类型，本侧必须可见）
            self._audit(msg, "unsupported", f"msgtype={msg.msg_type}")
            self._reply(msg, "暂不支持该消息类型（附件能力后续开放）。")
        else:
            self._audit(msg, "unsupported", f"msgtype={msg.msg_type}")
            self._reply(msg, "暂不支持该消息类型。")

    # ── 文本 ──
    def _handle_text(self, msg: WeComMessage) -> None:
        text = msg.text.strip()
        if not text:
            return
        self._audit(msg, "text", text[:200])
        sid = self._session_map.get_or_create(self._map_key(msg))
        result = self._engine.run(
            sid,
            text,
            user_metadata=(
                {"human_turn_source_id": f"wecom:{msg.message_id}"} if msg.message_id else None
            ),
        )
        answer = result.final_answer or "(空回答)"
        if getattr(result, "provider_output_truncated", result.truncated):
            answer += "\n（回答被截断）"
        if result.verification_note:
            answer += f"\n[声明提示] {result.verification_note}"
        self._reply(msg, answer)
        self._audit(msg, "answer", f"sid={sid[:8]}; chars={len(answer)}")

    # ── 回复 ──
    def _reply(self, msg: WeComMessage, text: str) -> None:
        """回复回调（绑定 msg.req_id；内容超协议字节预算时截断并如实标注）."""
        budget = max(self._chunk_limit, 200)
        encoded = text.encode("utf-8")
        if len(encoded) > budget:
            # 按字符边界截断（不切断多字节字符）
            text = encoded[:budget].decode("utf-8", errors="ignore") + "\n（超长截断）"
        if self._reply_fn is None:
            logger.warning("reply_fn 未装配，回复丢弃（req_id=%s）: %s", msg.req_id, text[:100])
            return
        self._reply_fn(msg.req_id, msg.reply_receive_id, text, msg.reply_receive_id_type)

    # ── 辅助 ──
    @staticmethod
    def _map_key(msg: WeComMessage) -> str:
        """会话映射键：群聊 g:{chatid} / 单聊 p:{userid}（与 session_map 一致）."""
        return WeComSessionMap.group_key(msg.chat_id) if msg.chat_id else WeComSessionMap.p2p_key(
            msg.sender_id
        )

    def _audit(self, msg: WeComMessage, kind: str, detail: str) -> None:
        """审计落盘（fail-open：写失败仅记日志，不阻断消息链路）."""
        record = {
            "ts": time.time(),
            "req_id": msg.req_id,
            "message_id": msg.message_id,
            "kind": kind,
            "chat_id": msg.chat_id,
            "sender_id": msg.sender_id,
            "msg_type": msg.msg_type,
            "detail": detail,
        }
        try:
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("企微审计落盘失败（fail-open）: %s", exc)
