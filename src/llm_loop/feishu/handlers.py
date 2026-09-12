"""飞书消息处理（M42，薄壳适配器）.

文本 → 会话映射 → LoopEngine.run → 回复原会话；长回复 markdown 分段。
M46：挂钩 Typing reaction 回执（FEISHU_TYPING_ACK）+ 流式状态卡（FEISHU_STREAMING），
对齐 本地既有实现 ws_bridge/streaming_card 算法思路；失败 fail-open 回退既有路径。
附件/图片复用 M39 web/upload_handlers + vision（不复制不重写）；失败如实 fail-open。
审计落盘 data/audit/feishu_audit.jsonl（fail-open）。
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lark_oapi

from llm_loop.core.loop import LoopEngine
from llm_loop.core.loop.runner import CANCEL_REASON_USER_STOP

logger = logging.getLogger(__name__)

# G4: 长回复折叠阈值（回复长度超过则首段发摘要卡 + 完整内容全量分段推送）
_FOLD_THRESHOLD = 2000
_FOLDED_MAX = 20  # F4: 折叠全文暂存上限（有界防膨胀）
_CARD_UPDATE_MIN_INTERVAL_S = 1.0  # F6: 状态卡更新最小间隔（工具密集时合并中间态）
_FOLD_EXPAND_CMD = "展开全文"  # F4: 用户取回全文指令

# 控制指令集合。只有 /stop 属于 out-of-band fast-lane；/continue 会创建一个
# 正常的新 user turn，必须继续经过单 worker 串行入口，禁止旁路线程直接跑推理。
STOP_COMMAND = "/stop"
CONTINUE_COMMAND = "/continue"
CONTROL_COMMANDS = {STOP_COMMAND, CONTINUE_COMMAND}
FASTLANE_CONTROL_COMMANDS = {STOP_COMMAND}
# 停止收口恢复指引（spec 5.1.1-7；仅飞书端 user_stop 取消追加，全局 _CANCELLED_ANSWER 不变）
_STOP_RESUME_HINT = "\n\n可发送 /continue 或重新发送消息恢复任务。"
# user_stop 待收口登记时间窗（覆盖最坏收口时长；超窗惰性剔除）
_USER_STOP_PENDING_WINDOW_S = 120.0


def _fallback_receipt_line(result: Any) -> str:
    """Render one current-run fallback fact; never persists it into conversation history."""
    fb = getattr(result, "fallback_receipt", None)
    if not isinstance(fb, dict) or not fb:
        return ""
    return (
        f"\n[模型降级: {fb.get('from', '?')}→{fb.get('to', '?')}, "
        f"原因: {fb.get('reason', 'unknown')}]"
    )


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
        typing_ack: bool = True,  # M46：FEISHU_TYPING_ACK
        streaming: bool = True,  # M46：FEISHU_STREAMING
        cross_sync: Any | None = None,  # 2026-08-15 跨端同步（Web→飞书推送；None=不启用）
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
        self._cross_sync = cross_sync
        self._streaming = streaming
        # 优雅退出保护：处理中计数（信号触发退出时等待正在进行的 run 完成，避免中断丢回复）
        self._busy_lock = threading.Lock()
        self._busy_count = 0
        # P1-11(2026-08-16): 正在处理的会话 id 集合（跨端同步按会话精确跳过——
        # 只防桥自己的回答被当 Web 增量重复推，其他会话照常实时同步）
        self._processing_sids: set[str] = set()
        # 中断补偿（COMP）：当前处理中会话 sid（受 _busy_lock 保护，供 bridge 生成 context_ref）
        self._processing_sid: str = ""
        # H-UI(2026-08-14): 当前活动状态卡（引擎动作观察者实时更新；None=未建卡/已结束）
        self._active_status_card: Any | None = None
        # F4(2026-08-14): 折叠全文暂存（key=ts，值=全文；有界最近 _FOLDED_MAX 条；"展开全文"取回）
        self._folded_store: dict[str, str] = {}
        # F6(2026-08-14): 状态卡更新节流时间戳（观察者内更新）
        self._card_update_ts: float = 0.0
        # user_stop 待收口登记（双键 sid/回复目标 → 受理时刻；bridge 中断补偿判定
        # 经 is_user_stop_pending fail-open 查询，spec 4.5.3 防重复补偿）
        self._user_stop_pending: dict[str, float] = {}
        self._user_stop_pending_lock = threading.Lock()
        # C-G5: 重启授权守卫（懒构造；engine 依赖注入，异常 fail-open 不阻断消息链路）
        self._restart_guard_svc: Any | None = None

    def current_processing_sid(self) -> str:
        """当前处理中会话 sid（只读；bridge 中断补偿 context_ref 数据源）."""
        with self._busy_lock:
            return self._processing_sid

    def _attach_action_observer(self) -> None:
        """H-UI: 引擎动作 → 状态卡实时更新（对齐 DeepSeek Harness 动作显示条）.

        thinking/tool_call/tool_result/answer 事件更新状态卡文本；未建卡/已熔断 →
        不注入（零回归）；观察者内部异常由引擎 fail-open 兜底。
        无 set_action_observer 能力的引擎（测试 Stub/外部实现）→ 直接跳过。
        """
        engine = self._engine
        if not hasattr(engine, "set_action_observer"):
            return
        card = self._active_status_card
        if card is None or not card.active:
            engine.set_action_observer(None)
            return

        def observer(event_type: str, payload: dict) -> None:
            # F6(2026-08-14): 节流——同一引擎 run 内相邻更新最小间隔（工具密集时
            # 合并中间态，防 cardkit 更新风暴；间隔内事件丢弃最新内容留待下个事件）
            now = time.monotonic()
            last = getattr(handler_self, "_card_update_ts", 0.0)
            if now - last < _CARD_UPDATE_MIN_INTERVAL_S:
                return
            handler_self._card_update_ts = now
            if event_type == "thinking":
                card.update("💭 思考中…")
            elif event_type == "tool_call":
                name = str(payload.get("tool_name", ""))
                args = str(payload.get("args_summary", ""))[:60]
                card.update(f"🔧 正在调用 {name}（{args}）")
            elif event_type == "tool_result":
                card.update(f"✅ {payload.get('tool_name', '')} 完成")
            elif event_type == "answer":
                card.update("✍️ 正在生成回答…")
            # done 不更新（_close_status_card 定稿已有）

        handler_self = self
        engine.set_action_observer(observer)

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
        # F4: "展开全文"取回最近折叠回复（不走引擎）
        if text.strip() == _FOLD_EXPAND_CMD:
            self._reply_folded_full(msg)
            return
        # M50（design §六）: 飞书 /model 指令拦截（与 CLI 共用同一套处理逻辑）
        if self._try_handle_model_command(msg, text):
            return
        # M55: 飞书 /new·/clear 会话指令拦截（对齐 Web 快捷命令, founder 实测缺口）
        if self._try_handle_session_command(msg, text):
            return
        # EVO-20260817 飞书审批 UX（方案 A）: 审批列表/批准/拒绝指令（私聊 + open_id 白名单）
        if self._try_handle_approval_command(msg, text):
            return
        # 飞书 /stop·/continue 推理控制指令（审批之后、引擎推理路径之前，spec 5.1.1-9）
        if self._try_handle_stop_command(msg, text):
            return
        if self._try_handle_continue_command(msg, text):
            return
        # Explicit /continue may leave one pending confirmation frame. Ordinary
        # natural-language turns are not interpreted against historical Goal state:
        # only a reply to that already-pending control frame is consumed here.
        if self._try_restart_gate(msg, text):
            return
        self._run_with_processing_actions(msg, self._run_text, text)

    def handle_recall(self, fact: dict) -> dict:
        """Apply one Feishu recall fact without equating recall with run cancellation."""
        message_id = str(fact.get("message_id") or "")
        if not message_id:
            return {"status": "invalid_source", "session_id": "", "event_id": ""}
        if bool(fact.get("queue_removed")):
            result = {"status": "queue_withdrawn", "session_id": "", "event_id": ""}
        else:
            result = self._engine.session.retract_message_by_source_id(
                f"feishu:{message_id}",
                session_id_hint=str(fact.get("session_id_hint") or ""),
                actor="unknown",  # SDK recalled_v1 exposes no actor/open_id; never fabricate one.
                reason=f"feishu_recalled:{str(fact.get('recall_type') or 'unknown')}",
                retracted_at=str(fact.get("recall_time") or ""),
            )
        try:
            _write_audit_line(
                self._audit_path,
                {
                    "ts": time.time(),
                    "message_id": message_id,
                    "kind": "message_recall",
                    "chat_id": str(fact.get("chat_id") or ""),
                    "sender_id": "",
                    "detail": (
                        f"status={result.get('status', 'unknown')};"
                        f"recall_type={str(fact.get('recall_type') or '')};"
                        f"session_id={str(result.get('session_id') or '')[:8]}"
                    ),
                },
            )
        except OSError as exc:
            logger.warning("撤回审计落盘失败（fail-open）: %s", exc)
        return result

    def _try_handle_approval_command(self, msg: FeishuMessage, text: str) -> bool:
        """EVO-20260817: 飞书文本指令审批（替代终端 evolve-review，方案 A）.

        指令: 审批列表 / 批准 EVO-xxx / 拒绝 EVO-xxx [理由：…]。
        安全: 私聊（非群）+ open_id 白名单（feishu_session_map p: 前缀）。
        Returns: True=已处理；False=非审批指令走原路径。
        """
        from llm_loop.feishu.approval import handle_approval

        try:
            return handle_approval(self._engine, msg, text, self._reply_fn)
        except Exception as exc:  # noqa: BLE001 — 审批异常不阻断消息处理
            logger.exception("飞书审批指令处理异常: %s", exc)
            self._reply(msg, f"⚠️ 审批指令处理异常：{type(exc).__name__}，请重试或走 CLI。")
            return True

    def _try_handle_stop_command(self, msg: FeishuMessage, text: str) -> bool:
        """飞书 /stop 停止指令拦截（spec 5.1.1-1/2/3/4/8/9）.

        目标会话经 SessionMap.get() 只读定位（不新建映射，spec 5.1.3-4）；
        仅作用于发起消息映射的会话（隔离，spec 4.3.1）。
        Returns: True=已处理；False=非 /stop 指令走原路径。
        """
        if text.strip().lower() != STOP_COMMAND:
            return False
        try:
            runner = getattr(self._engine, "runner", None)
            if runner is None or not getattr(runner, "enabled", False):
                self._reply(msg, "停止能力未启用（后台 run 执行器未装配）。")
                self._audit(msg, "stop_degraded", "runner disabled")
                return True
            sid = self._session_map.get(self._map_key(msg))
            if not sid or not runner.cancel(sid, CANCEL_REASON_USER_STOP):
                self._reply(msg, "当前没有进行中的推理。")
                self._audit(msg, "stop_noop", f"sid={sid[:8] if sid else 'unmapped'}")
                return True
            self._user_stop_register(sid, msg)
            self._reply(msg, "停止已受理，本轮推理将在稍后终止；终止后可发送 /continue 或重发消息恢复。")
            self._audit(msg, "stop_accepted", f"sid={sid[:8]} reason=user_stop")
            return True
        except Exception as exc:  # noqa: BLE001 — fail-open（spec 4.2.4，指令文本不漏入引擎）
            logger.exception("飞书 /stop 指令处理异常: %s", exc)
            self._reply(msg, f"⚠️ 指令处理异常（{type(exc).__name__}），请重试。")
            self._audit(msg, "stop_error", str(exc)[:200])
            return True

    def _try_handle_continue_command(self, msg: FeishuMessage, text: str) -> bool:
        """飞书 /continue 恢复指令拦截（spec 5.2.1-1/2/3/4/5）.

        忙会话拒绝（防并发双轮）→ 空会话防呆（不空转）→ 恢复轮经既有
        _run_with_processing_actions 包装（状态卡/footer/跨端基线一致）。
        Returns: True=已处理；False=非 /continue 指令走原路径。
        """
        if text.strip().lower() != CONTINUE_COMMAND:
            return False
        try:
            runner = getattr(self._engine, "runner", None)
            if runner is None or not getattr(runner, "enabled", False):
                self._reply(msg, "恢复能力未启用（后台 run 执行器未装配）。")
                self._audit(msg, "continue_degraded", "runner disabled")
                return True
            sid = self._session_map.get_or_create(self._map_key(msg))
            if runner.is_running(sid) or runner.is_sync_active(sid):
                self._reply(msg, "推理进行中，请先发送 /stop 终止当前推理。")
                self._audit(msg, "continue_busy", f"sid={sid[:8]}")
                return True
            sess = self._engine.session.load(sid)
            if not sess.messages:
                self._reply(msg, "当前会话无可恢复内容（会话为空）。")
                self._audit(msg, "continue_empty", f"sid={sid[:8]}")
                return True
            # 续聊前现场预检（CONT）：只读对账 + 锚点来源，如实外显（ADR-6/FTR-CONT-1）；
            # 不改变引擎对账行为——实际确定性修复仍由 engine.run ingress 承担。
            self._audit_resume_prep(sid, msg)
            # C-G5 重启授权守卫（T5.4）：恢复会话 ≠ 同意重跑任务（spec 5.2.1-5，
            # 原注释"/continue 本身就是恢复授权"作废）。completed → 拒绝；已开始
            # 未完成 → 确认帧挂起；无已开始任务/守卫 fail-open → 既有直跑零变化。
            # 保持 USER_INSTRUCTION provenance，不向 prompt 注入程序撰写的恢复说明。
            guard_decision = self._check_restart_guard(sid, msg)
            if guard_decision == "handled":
                return True
            self._run_with_processing_actions(msg, self._run_text, text)
            self._audit(msg, "continue_accepted", f"sid={sid[:8]}")
            return True
        except Exception as exc:  # noqa: BLE001 — fail-open（spec 5.2.3-4，指令文本不漏入引擎）
            logger.exception("飞书 /continue 指令处理异常: %s", exc)
            self._reply(msg, f"⚠️ 指令处理异常（{type(exc).__name__}），请重发恢复。")
            self._audit(msg, "continue_error", str(exc)[:200])
            return True

    def _restart_guard(self) -> Any:
        """C-G5: 重启授权守卫懒构造（engine 注入审计；守卫自身零状态跨消息复用）."""
        if self._restart_guard_svc is None:
            from llm_loop.feishu.restart_guard import RestartGuardService

            self._restart_guard_svc = RestartGuardService(self._engine)
        return self._restart_guard_svc

    def _check_restart_guard(self, sid: str, msg: FeishuMessage) -> str:
        """C-G5 /continue 守卫三分支（T5.4）：deny 回执 / confirm 挂起 / 其余放行.

        Returns: "handled"（已处置勿再执行 run）| "passthrough"（维持既有直跑）。
        守卫异常 fail-open 留痕后放行（宁可多问不可误跑的对偶：守卫故障不阻断恢复）。
        """
        try:
            decision = self._restart_guard().check_restart(sid)
        except Exception as exc:  # noqa: BLE001 — 授权硬边界异常时不得静默启动
            logger.exception("重启守卫判定异常（本次不启动）: %s", exc)
            self._audit(msg, "restart_guard_error", f"stage=check_restart; error={str(exc)[:150]}")
            self._reply(
                msg,
                "[重启确认] 当前无法可靠核验任务状态，本次未恢复执行；请稍后重新发送 /continue。",
            )
            return "handled"
        if decision.kind == "deny":
            self._reply(
                msg,
                f"任务已完成（{decision.goal_id}），不再自动重跑；"
                "如需重做请发送 /new 后发起新任务。",
            )
            self._audit(msg, "restart_denied", f"goal_id={decision.goal_id}; reason={decision.reason}")
            return "handled"
        if decision.kind == "confirm":
            self._push_restart_confirm(msg, decision)
            return "handled"
        return "passthrough"

    def _try_restart_gate(self, msg: FeishuMessage, text: str) -> bool:
        """Consume only replies to an already-pending explicit /continue frame.

        P1-A: ordinary text (including ``继续`` / ``重跑这个任务``) must reach the
        model unchanged. Goal/task history is factual state, not a program-side intent
        classifier. Pending explicit-control approval remains a scoped UI protocol.
        """
        try:
            guard = self._restart_guard()
            sid = self._session_map.get_or_create(self._map_key(msg))
            grant = guard.match_reply(sid, text)
            if grant.ok and grant.decision == "approved":
                # Execute the queued genuine explicit command, not the approval word.
                # The latter is control-plane consent and may otherwise reach the LLM
                # without its confirmation-frame referent.
                queued = str(getattr(grant, "command_text", "") or "/continue")
                self._run_with_processing_actions(msg, self._run_text, queued)
                return True
            if grant.decision in ("denied", "consumed", "timeout"):
                self._reply_restart_unexecuted(msg, grant)
                return True
            # none/mismatch is not task semantics; the genuine user turn proceeds to LLM.
            return False
        except Exception as exc:  # noqa: BLE001 — control-plane failure must not swallow user input
            logger.exception("重启确认应答判定异常（fail-open 放行）: %s", exc)
            self._audit(msg, "restart_guard_error", f"stage=pending_reply; error={str(exc)[:150]}")
            return False

    def _reply_restart_unexecuted(self, msg: FeishuMessage, grant: Any) -> None:
        """授权应答未放行回执（denied 拒绝确认 / consumed 票据已失效，spec 5.2.1-2c/3a）."""
        if grant.decision == "denied":
            grant_reason = getattr(grant, "reason", "")
            if grant_reason == "completed":
                reason = "任务已完成，无需重启"
            elif grant_reason == "state_unknown":
                reason = "任务状态无法可靠复核，本次不执行；如需恢复请重新发送 /continue"
            else:
                reason = "已收到拒绝，本次任务不执行"
            self._reply(msg, f"[重启守卫] {reason}（goal_id={grant.goal_id or '未知'}）。")
            return
        if grant.decision == "timeout":
            self._reply(msg, "[重启守卫] 上一条 /continue 授权已过期，本次不执行；如需恢复请重新发送 /continue。")
            return
        self._reply(
            msg,
            "[重启守卫] 该授权已使用过（一次性有效），本次不执行；如需再次恢复请发送 /continue。",
        )

    def _push_restart_confirm(self, msg: FeishuMessage, decision: Any) -> None:
        """确认帧推送（含任务标识/进度锚点/待续概要）；帧缺失走兜底文案（run 不启动）."""
        from llm_loop.feishu.restart_guard import confirmation_frame_text

        frame = getattr(decision, "frame", None)
        if frame is None:
            self._reply(
                msg,
                "[重启确认] 任务状态待确认，本次未恢复执行；如需继续请重新发送 /continue。",
            )
            return
        self._reply(msg, confirmation_frame_text(frame))

    def _audit_resume_prep(self, sid: str, msg: FeishuMessage) -> None:
        """续聊前现场预检并如实审计（只读；异常 fail-open 仅标注 none/unknown）."""
        from llm_loop.feishu.resume import ResumeCoordinator

        try:
            prep = ResumeCoordinator().prepare_resume(sid, self._engine)
            anchor_source = prep.anchor_source
            repair_status = prep.repair_status
        except Exception as exc:  # noqa: BLE001 — 预检失败不阻断续聊
            logger.warning("续聊现场预检失败（fail-open）: %s", exc)
            anchor_source = "none"
            repair_status = "unknown"
        self._audit(
            msg,
            "continue_resume",
            f"sid={sid[:8]};anchor_source={anchor_source};repair_status={repair_status}",
        )

    def _user_stop_register(self, sid: str, msg: FeishuMessage) -> None:
        """user_stop 待收口登记（sid + 回复目标双键；bridge 补偿判定查询，design §2.1.3-5）."""
        now = time.time()
        with self._user_stop_pending_lock:
            self._user_stop_pending[sid] = now
            self._user_stop_pending[msg.reply_receive_id] = now

    def _user_stop_clear(self, sid: str, msg: FeishuMessage) -> None:
        """收口回复发出后移除登记（时间窗兜底由读取侧惰性剔除）."""
        with self._user_stop_pending_lock:
            self._user_stop_pending.pop(sid, None)
            self._user_stop_pending.pop(msg.reply_receive_id, None)

    def is_user_stop_pending(self, chat_id: str) -> bool:
        """该飞书会话是否存在未收口的用户主动停止（bridge 中断补偿判定，fail-open 查询）."""
        now = time.time()
        with self._user_stop_pending_lock:
            stale = [
                k for k, ts in self._user_stop_pending.items()
                if now - ts > _USER_STOP_PENDING_WINDOW_S
            ]
            for k in stale:
                self._user_stop_pending.pop(k, None)
            return chat_id in self._user_stop_pending

    def _try_handle_session_command(self, msg: FeishuMessage, text: str) -> bool:
        """M55: 飞书会话指令拦截（/new 新会话 /clear 继续但开新上下文）.

        Returns:
            True → 已处理；False → 非会话指令，继续走原路径。
        """
        cmd = text.strip().lower()
        if cmd not in {"/new", "/clear"}:
            return False
        key = self._map_key(msg)
        # M55-fix: force_new=True 跳过 owner 跨端共享与旧映射复用,真正创建新 session;
        # 否则 owner 路径会被 get_shared_current() 拉回老 session → /clear 失效。
        # M52-fix: inherit_model_override=True 继承旧会话模型覆盖（不回落装配默认），
        # 故不再先 remove(key)（get_or_create 需读取旧映射拿旧 sid）。
        new_sid = self._session_map.get_or_create(
            key, force_new=True, inherit_model_override=True
        )
        # 审计落盘（如实记录新会话 ID 前 8 位）
        self._audit(msg, "session_new", f"{cmd} → {new_sid[:8]}")
        if cmd == "/new":
            self._reply(msg, "已新建会话。旧会话已保留，可经 CLI/Web 端查看。")
        else:
            self._reply(msg, "已开启新上下文（旧会话保留）。")
        return True

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

    def _run_text(self, msg: FeishuMessage, text: str) -> str:
        """文本引擎执行 + 回复（M46：_run_with_processing_actions 包内）."""
        sid = self._session_map.get_or_create(self._map_key(msg))
        self._attach_action_observer()  # H-UI: 状态卡实时动作显示
        try:
            # agent_trace_leak 3.7: 人类输入通道签发 ingress 凭据（B2 双因子判定）
            from llm_loop.core.trace_leak.ingress_token import issue_ingress

            result = self._engine.run(
                sid,
                text,
                ingress=issue_ingress("feishu"),
                user_metadata=(
                    {"human_turn_source_id": f"feishu:{msg.message_id}"}
                    if msg.message_id
                    else None
                ),
            )
        finally:
            if hasattr(self._engine, "set_action_observer"):
                self._engine.set_action_observer(None)
        answer = result.final_answer or "(空回答)"
        if result.truncated:
            answer += "\n（回答被截断）"
        if result.verification_note:
            answer += f"\n[声明提示] {result.verification_note}"
        # 停止收口恢复指引分流（3.6，design D5）：仅 user_stop 取消在飞书端追加指引；
        # 全局 _CANCELLED_ANSWER 保持不变（Web 端共用，零回归）
        _stopped_by_user = getattr(result, "cancel_reason", "") == CANCEL_REASON_USER_STOP
        if _stopped_by_user:
            answer += _STOP_RESUME_HINT
        # P2-4: 公式降级提示（飞书卡片不支持 KaTeX/LaTeX 渲染，如实告知）
        try:
            from llm_loop.feishu.card_utils import detect_math_formula

            if detect_math_formula(answer):
                answer += "\n（公式请于 Web 端查看）"
        except Exception:  # noqa: BLE001 — 检测失败 fail-open
            pass
        answer += _fallback_receipt_line(result)
        # M51: 回复下方标注实际生成模型（provider/model，如实透传）
        if getattr(result, "model_used", ""):
            footer = f"\n—— {result.model_used}"
            # M52: footer 附带本轮 token 用量（0 = provider 未提供时不显示）
            if getattr(result, "tokens_in", 0) or getattr(result, "tokens_out", 0):
                from llm_loop.core.loop import format_tokens

                footer += f" · {format_tokens(result.tokens_in)}入/{format_tokens(result.tokens_out)}出"
            # P2-3: footer 附带工具调用次数（无工具调用不追加）
            n_tools = len(getattr(result, "tool_calls", None) or [])
            if n_tools > 0:
                footer += f" · 🔧 工具调用 {n_tools} 次"
            answer += footer
        # 2026-08-15 跨端同步：桥自身输出完成后刷新基线（Web 端增量才推送，不重复推自己）
        # P1-11(2026-08-16): 前移到 run 返回后立即执行——原实现在 _reply_chunked 之后，
        # 回答落盘与基线刷新之间存在秒级窗口，跨端同步轮询（1.5s）会插入其中把
        # 桥自己的回答当"Web 侧增量"重复推送一条 [跨端同步]（用户反馈重复）。
        if self._cross_sync is not None:
            self._cross_sync.mark_processed(sid)
        self._reply_chunked(msg, answer)
        # 收口回复已发出 → 移除 user_stop 待收口登记（bridge 补偿判定随之失效）
        if _stopped_by_user:
            self._user_stop_clear(sid, msg)
        return answer

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

        if not vision_enabled(settings=getattr(self._engine, "settings", None)):
            self._reply(msg, "视觉识别未配置（MINIMAX_API_KEY 缺失），图片已跳过。")
            return
        try:
            text = describe_image(
                data, settings=getattr(self._engine, "settings", None)
            )
        except Exception as exc:  # 识别失败如实降级（无伪造描述）
            logger.info("feishu image vision failed (%s), OCR fallback: %s", filename, exc)
            # 2026-08-20（借鉴 SYAGI）: vision 全失败 → 飞书 OCR 文字兑底（诚实标注来源）
            ocr_lines: list[str] = []
            rest_client = self._rest_client
            if rest_client is not None and data:
                try:
                    ocr_lines = rest_client.ocr_image(data)
                except Exception as oexc:  # noqa: BLE001 — OCR 失败如实 fail-open
                    logger.warning("feishu image ocr failed: %s", oexc)
            body = "\n".join(ocr_lines).strip()
            if not body:
                self._audit(msg, "attachment_error", str(exc)[:200])
                self._reply(msg, f"图片识别失败（{type(exc).__name__}: {exc}），图片已跳过。")
                return
            self._inject_and_reply(msg, f"[附件 图片 {filename} OCR 文字提取]\n{body}")
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

    def _run_inject(self, msg: FeishuMessage, prefix: str) -> str:
        """附件注入引擎执行 + 回复（M46：_run_with_processing_actions 包内）."""
        sid = self._session_map.get_or_create(self._map_key(msg))
        self._attach_action_observer()  # H-UI: 状态卡实时动作显示
        try:
            # agent_trace_leak 3.7: 用户上传动作触发（user truth 派生输入）签发凭据
            from llm_loop.core.trace_leak.ingress_token import issue_ingress

            result = self._engine.run(sid, prefix, ingress=issue_ingress("feishu"))
        finally:
            if hasattr(self._engine, "set_action_observer"):
                self._engine.set_action_observer(None)
        reply = result.final_answer or "(空回答)"
        # P2-4: 公式降级提示（飞书卡片不支持 KaTeX/LaTeX 渲染，如实告知）
        try:
            from llm_loop.feishu.card_utils import detect_math_formula

            if detect_math_formula(reply):
                reply += "\n（公式请于 Web 端查看）"
        except Exception:  # noqa: BLE001 — 检测失败 fail-open
            pass
        reply += _fallback_receipt_line(result)
        # M51: 回复下方标注实际生成模型
        if getattr(result, "model_used", ""):
            footer = f"\n—— {result.model_used}"
            # M52: footer 附带本轮 token 用量
            if getattr(result, "tokens_in", 0) or getattr(result, "tokens_out", 0):
                from llm_loop.core.loop import format_tokens

                footer += f" · {format_tokens(result.tokens_in)}入/{format_tokens(result.tokens_out)}出"
            # P2-3: footer 附带工具调用次数（无工具调用不追加）
            n_tools = len(getattr(result, "tool_calls", None) or [])
            if n_tools > 0:
                footer += f" · 🔧 工具调用 {n_tools} 次"
            reply += footer
        self._reply_chunked(msg, reply)
        return reply

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
        # P1-11: 处理中的会话 id（跨端同步按会话跳过——get_or_create 幂等, 与 fn 内部一致）
        proc_sid = self._session_map.get_or_create(self._map_key(msg))
        with self._busy_lock:
            self._busy_count += 1
            self._processing_sids.add(proc_sid)
            self._processing_sid = proc_sid
        reaction_id = ""
        card = None
        if self._typing_ack and self._rest_client is not None and msg.message_id:
            try:
                reaction_id = self._rest_client.add_typing_reaction(msg.message_id)
            except Exception as exc:  # noqa: BLE001 — 回执失败静默（fail-open）
                logger.debug("feishu typing reaction add error: %s", exc)
        if self._streaming and self._lark_client is not None:
            card = self._try_start_status_card(msg)
        self._active_status_card = card  # H-UI: 引擎动作观察者读取当前卡
        answer = ""
        try:
            answer = fn(msg, payload) or ""
        except Exception as exc:  # 失败如实反馈，不静默降级
            logger.exception("feishu message handle failed")
            self._audit(msg, error_kind, str(exc)[:200])
            self._reply(msg, f"[程序异常] 消息处理失败（{type(exc).__name__}: {exc}）。")
        finally:
            self._active_status_card = None  # H-UI: 清理当前卡引用
            with self._busy_lock:
                self._busy_count -= 1
                self._processing_sids.discard(proc_sid)
                if self._processing_sid == proc_sid:
                    self._processing_sid = ""
            # 处理结束 → 状态卡定稿（回填回复摘要）+ 删除 Typing reaction（best-effort）
            self._close_status_card(card, msg, answer)
            if reaction_id and self._rest_client is not None:
                try:
                    self._rest_client.remove_reaction(msg.message_id, reaction_id)
                except Exception as exc:  # noqa: BLE001 — 删除失败静默
                    logger.debug("feishu typing reaction remove error: %s", exc)

    def wait_until_idle(self, timeout_s: float = 30.0) -> bool:
        """等待正在处理的消息完成（优雅退出保护，避免进程退出中断 engine.run 丢回复）."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._busy_lock:
                if self._busy_count <= 0:
                    return True
            time.sleep(0.5)
        return False

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

    def _close_status_card(self, card, msg: FeishuMessage, answer: str = "") -> None:
        """处理完成 → 状态卡定稿（回填回复摘要 + ✅ + 关 streaming_mode），best-effort.

        P2-2: 透传回复摘要首行（≤80 字符）作为状态卡内容回填，
        建立"状态卡 → 分段消息"视觉关联；answer 为空走既有无参 close 路径（零回归）。
        """
        if card is None:
            return
        try:
            summary = (answer or "").strip().splitlines()[0][:80] if (answer or "").strip() else ""
            ok = card.close(content=summary) if summary else card.close()
            if ok:
                self._audit(msg, "status_card_close", "状态卡定稿（摘要已回填）" if summary else "状态卡定稿（✅ 处理完成）")
            else:
                self._audit(msg, "status_card_fallback", "定稿失败（卡保持处理中态）")
        except Exception as exc:  # noqa: BLE001 — 定稿失败不阻断主流程
            logger.debug("feishu status card close error: %s", exc)

    # ── 长回复分段 ──
    def _reply_chunked(self, msg: FeishuMessage, text: str, *, force_full: bool = False) -> None:
        """长回复按 markdown 感知分段（fence 闭合重开），逐段发送（不丢失内容）.

        2026-08-15 用户需求：默认不折叠——超过 `_FOLD_THRESHOLD` 也直接全量分段推送
        （分块输出）；`FEISHU_FOLD_LONG_REPLY=1` 选择加入旧折叠行为（F4：暂存全文 +
        摘要卡 + 「展开全文」取回，`force_full=True` 展开路径跳过折叠）。
        摘要卡/暂存失败 fail-open 回退既有全量分段路径（不丢内容）。
        """
        fold_enabled = os.environ.get("FEISHU_FOLD_LONG_REPLY", "0") == "1"
        if len(text) <= self._chunk_limit:
            if fold_enabled and len(text) > _FOLD_THRESHOLD and not force_full:
                self._fold_and_notify(msg, text)
                return
            self._reply(msg, text)
            return
        if fold_enabled and len(text) > _FOLD_THRESHOLD and not force_full:
            self._fold_and_notify(msg, text)
            return
        for part in self._chunk_markdown(text, self._chunk_limit):
            self._reply(msg, part)

    def _fold_and_notify(self, msg: FeishuMessage, text: str) -> None:
        """F4: 暂存全文 + 发摘要卡（引导「展开全文」取回）.

        暂存/摘要失败 fail-open：回退既有全量分段路径（不丢内容）。
        """
        try:
            from llm_loop.feishu.card_utils import build_summary_card

            key = f"{time.time():.6f}"
            self._folded_store[key] = text
            while len(self._folded_store) > _FOLDED_MAX:
                self._folded_store.pop(next(iter(self._folded_store)))
            self._reply(msg, build_summary_card(text))
        except Exception:  # noqa: BLE001 — 折叠失败回退全量
            logger.debug("feishu fold failed, fallback full")
            if len(text) <= self._chunk_limit:
                self._reply(msg, text)
            else:
                for part in self._chunk_markdown(text, self._chunk_limit):
                    self._reply(msg, part)

    def _reply_folded_full(self, msg: FeishuMessage) -> None:
        """F4: 「展开全文」取回最近折叠回复（分段发送）."""
        if not self._folded_store:
            self._reply(msg, "当前没有可展开的折叠回复（最近回复较短或已过期）。")
            return
        key = next(reversed(self._folded_store))
        full = self._folded_store.pop(key)
        self._audit(msg, "fold_expand", f"len={len(full)}")
        self._reply_chunked(msg, full, force_full=True)

    @staticmethod
    def _chunk_markdown(text: str, limit: int) -> list[str]:
        """markdown 感知分段（对齐 本地既有实现 markdown_chunker 算法思路）.

        切点按行；代码 fence 内切段自动补闭合并在下一段开头重开（含语言标签）。
        表格感知：以 `|` 开头的连续行序列视为表格块（fence 内不触发表格态），
        表格行内不切段；当切点落在表格块中间时，从表格块起点回溯，
        将整表（含表头）归入下一段，避免表格语法被分段劈裂。
        各段拼接（剥离 fence/表格修复对后）= 原回复内容，无丢失。
        """
        parts: list[str] = []
        in_fence = False
        in_table = False
        table_start = 0  # 当前表格块在 buf 中的起点偏移（未在表格中时无效）
        buf = ""
        buf_bytes = 0  # F3: 当前段字节数（UTF-8；中文 3 字节/字，字符上限会触飞书 150KB 物理上限）
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
            is_table_line = (not in_fence) and stripped.startswith("|")
            if is_table_line and not in_table:
                in_table = True
                table_start = len(buf)
            elif not is_table_line:
                in_table = False
            line_bytes = len(line.encode("utf-8"))
            if buf and buf_bytes + line_bytes > limit:
                if in_fence:
                    buf += "```\n"  # 闭合 fence
                    parts.append(buf)
                    buf = "```\n"  # 重开 fence
                elif in_table:
                    # 切点落在表格块中间：回溯到表格起点，整表（含表头）归入下一段
                    prefix = buf[:table_start]
                    if prefix:
                        parts.append(prefix)
                    buf = buf[table_start:]
                    table_start = 0
                else:
                    parts.append(buf)
                    buf = ""
            buf += line
            buf_bytes += line_bytes
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
                "ts": time.time(),  # P1-2-R1: 审计时间戳（断线时刻时间对齐回归分析数据源）
                "message_id": msg.message_id,
                "kind": kind,
                "chat_id": msg.chat_id,
                "sender_id": msg.sender_id,
                "detail": detail,
            }
            _write_audit_line(self._audit_path, record)
        except OSError as exc:  # fail-open：审计落盘失败不阻断
            logger.warning("审计落盘失败（fail-open）: %s", exc)


def _write_audit_line(path: Path, record: dict) -> None:
    """审计单条落盘（模块级函数，便于 fail-open 测试注入）."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
