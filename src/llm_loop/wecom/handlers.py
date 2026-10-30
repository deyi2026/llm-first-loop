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
from collections import deque
from pathlib import Path

from llm_loop.core.loop import LoopEngine

from .messages import WeComMessage, WeComReplyFn
from .session_map import WeComSessionMap

logger = logging.getLogger(__name__)

# ── 防回灌（P1，2026-10）──
# 协议事实（官方 path/101463 原文）：aibot_msg_callback 的 from 结构仅含
# userid，没有飞书式 sender_type 来源标记——帧层无法判定"机器人自身消息"，
# handlers 的 sender_type=="app" 分支对真实帧恒 False。若企微把机器人自己在
# 群里的发言回推给桥（群聊场景可能），无防护会形成 回调→推理→回复→再回调
# 的无限回灌（烧 token + 刷屏）。
# 诚实兜底＝内容回声抑制：机器人发出的回复文本被原样回调回时（同会话 +
# 短时间窗内精确匹配），跳过不进引擎、不回复。不依赖任何未经证实的协议
# 假设（userid 与 aibotid 不是同一标识体系，不可比对）。
# 取舍：精确匹配（宁可漏判不误杀）——用户重复提问不受影响（问题文本与
# 机器人回复文本不同，不进回复登记表）；用户逐字粘贴机器人回复属极端场景，
# 按回声抑制（与真实回声不可区分）。
_ECHO_HISTORY_PER_CONV = 8  # 每会话登记的近期回复条数上限（防内存增长）


def _echo_window_s() -> float:
    """回声抑制时间窗（秒；env WECOM_ECHO_SUPPRESS_WINDOW_S 可覆盖，非法回退默认）."""
    try:
        return float(os.environ.get("WECOM_ECHO_SUPPRESS_WINDOW_S", "60") or 60)
    except ValueError:
        return 60.0


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
        # 回声登记表：会话键 → deque[(回复全文, 发送时间戳)]（防回灌，见模块头注释）
        self._recent_replies: dict[str, deque[tuple[str, float]]] = {}

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
        # 防回灌（协议无来源标记的诚实兜底，见模块头注释）：同会话短时间内
        # 收到与机器人近期回复精确相同的文本 → 判为回声，跳过（不进引擎、
        # 不回复——回执本身也会被回推，必须静默跳过）
        #
        # P1-2（2026-10-30 父代理+独立审查）：判定**不再限定 msg_type=="text"**。
        # 机器人实际发出的形态是 markdown（bridge.py:502），此前 markdown 帧走不到
        # 这个分支 → 落到 unsupported 分支回执"暂不支持该消息类型" → 该回执又是
        # markdown → 被服务端回推 → 无限刷屏循环（独立审查实测 3 帧回声 → 3 条新
        # 回复，无自愈）。改为：任何带文本的类型都先判回声。
        if self._is_echo(msg):
            self._audit(msg, "skip_echo_suppress", "疑似机器人回声（与本会话近期回复精确匹配），跳过防回灌")
            return
        if msg.msg_type == "text":
            self._handle_text(msg)
        elif msg.msg_type == "markdown":
            # markdown 只能由机器人发出（用户端无法发送 markdown 消息体），
            # 未命中回声也属机器人来源帧 —— 静默跳过、不回执。
            # 任何回执都会再被回推，形成循环（见上 P1-2）。
            self._audit(msg, "skip_bot_markdown", "markdown 形态消息（机器人来源），静默跳过防回灌")
            return
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
        # agent_trace_leak 3.7: 人类输入通道签发 ingress 凭据（B2 双因子判定）。
        # 企微用户消息属 §0 user truth（channel="wecom" 已入固有成员白名单）；
        # 形态对齐 feishu/handlers._run_text——不签发则 enforce 模式下 user 写入
        # 被拒，用户只能收到「[写入被拒]」回执而非 LFL 回答（2026-10-30 实测）。
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        result = self._engine.run(
            sid,
            text,
            ingress=issue_ingress("wecom"),
            # 2026-10-30 用户指令「Always_on_effort 改为 on」：请求级 reasoning 模式
            # 由 auto 改为 on——auto 只带 reasoning_effort，on 额外显式下发
            # thinking={"type":"enabled"}（client.py:2094-2110）。本 key 的订阅套餐
            # 无 GLM-5.3-FlashX 权限，企微接入固定用 minimax/MiniMax-M3.1-Flash
            # （其 reasoning_control=always_on_effort），故在此显式钉住模式。
            reasoning_mode="on",
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
        self._record_reply(msg, text)  # 已实际发出的文本才登记（防回灌回声匹配源）

    # ── 防回灌（回声登记与匹配；见模块头注释的协议依据与取舍）──
    def _record_reply(self, msg: WeComMessage, text: str) -> None:
        """登记已发送回复（会话键=回复目标 receive_id；截断后的最终全文）."""
        key = msg.reply_receive_id or msg.chat_id or msg.sender_id
        dq = self._recent_replies.setdefault(
            key, deque(maxlen=_ECHO_HISTORY_PER_CONV)
        )
        now = time.time()
        # P2-1（2026-10-30 独立审查）：登记侧 strip、匹配侧（_is_echo）也 strip ——
        # 原先登记未 strip 而匹配 strip，回复文本带首尾空白时漏判回声。
        dq.append((text.strip(), now))
        window = _echo_window_s()
        while dq and now - dq[0][1] > window:
            dq.popleft()  # 惰性清理过期项（防长会话内存缓慢增长）
        # P2-2（2026-10-30 独立审查）：条目过期清空后顺手删会话键 —— 否则
        # _recent_replies 的键随会话数无界增长（每键上限 8 条）。
        if not dq:
            self._recent_replies.pop(key, None)

    def _is_echo(self, msg: WeComMessage) -> bool:
        """是否疑似机器人回声：同会话 + 时间窗内 + 与近期回复全文精确相同.

        边界（如实）：群聊回声携带同一 chatid → 可匹配；单聊回声的
        from.userid 归属协议未记载（若记为机器人自身 userid 则键不匹配、
        本抑制不生效）——已知局限，宁可漏判不误杀，待真实回声帧样例再扩展。
        """
        text = msg.text.strip()
        if not text:
            return False
        key = msg.chat_id or msg.sender_id
        entries = self._recent_replies.get(key)
        if not entries:
            return False
        now = time.time()
        window = _echo_window_s()
        return any(now - ts <= window and rtext == text for rtext, ts in entries)

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
