"""基础工具: 注册定时提醒 / 一次性续跑 / 常驻授权的周期任务。

普通提醒是 output-side notify，不自动进入模型 prompt。wake=true 只允许当前真人 run
把同会话执行权降权委派一次；它不是未来的新真人输入，也不能递归或周期唤醒。
task_mode=task_recurring 例外：创建时一次签发 N 次常驻授权，每次到点**开新会话**
把正文发给模型执行；额度/有效期/工作目录任一不符即降级为通知。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from llm_loop.core import schedule_task_grant as task_grant
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id, current_workspace_root
from llm_loop.core.scheduler import (
    ScheduleCommitUncertainError,
    SchedulePersistError,
    ScheduleStore,
)
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id,
    current_ingress_token,
    delegate_ingress,
)

_MAX_SCHEDULE_MESSAGE_CHARS = 4000

# antidrift R1: subject_refs 引用类型封闭集（OQ4 裁定；扩展须显式登记，不加白名单）
_SUBJECT_REF_TYPES = ("job_id", "expected_generation", "action_id")


class ScheduleTool:
    name = "schedule"
    description = (
        "注册定时提醒：after（N 秒后一次）/ at（绝对时间）/ rate（每 N 秒重复，可限次数）。"
        "task_mode: remind=只通知（默认）；task_once=一次性续跑；task_recurring=常驻授权任务"
        "（到点开新会话执行，受次数/有效期/外部副作用/工作目录边界约束，用尽或过期即降级为通知）。"
        "wake=true 的一次性续跑仅在当前真实用户 run 可签发；后台续跑不能递归再唤醒；"
        "常驻授权同理由真人签发，定时会话与子代理不得递归签发。"
        "交付失败处理: 瞬态失败有界退避重试；新提醒重启后恢复已授权的一次性委派；"
        "旧提醒无持久授权时需同会话真人 re-arm，窗口内未恢复才降级为通知。"
        "何时用: 需要延迟/周期性提醒（如 60 秒后检查后台任务、每 5 分钟汇报状态）；"
        "已有周期提醒要改成自动执行时用 schedule_upgrade（保留 sid/正文/节奏）。"
        "何时不用: 即时动作直接执行；一次性协调消息走 interop。"
        "失败对策: 参数校验失败如实返回；存储失败区分 definitely_not_committed 与 "
        "commit_outcome_uncertain，后者返回 sid/current-state 机械事实并明确禁止盲重试。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "maxLength": _MAX_SCHEDULE_MESSAGE_CHARS,
                "description": (
                    "提醒/一次性续跑内容（必填，最多 4000 字符）。wake=true 时应为"
                    "「哨兵+完成判据+核验动作」：写明到点时用什么读操作（如 job_output/"
                    "ls-remote/status 查询）核验哪些完成标志，而不是可逐步重放的操作清单"
                    "——唤醒 run 看不到沉睡前的终态回执，步骤清单易被误当未完成而重放。"
                ),
            },
            "after": {
                "type": "number",
                "description": "N 秒后触发一次（默认 0=立即触发；与 at 二选一，都填以 at 为准）",
            },
            "at": {
                "type": "string",
                "description": "绝对触发时间 ISO（如 '2026-08-17T10:00:00'，本地时区）；与 after 二选一",
            },
            "repeat_interval": {
                "type": "number",
                "description": "重复间隔秒（>0 表示周期提醒）",
            },
            "max_count": {
                "type": "integer",
                "description": "最多触发次数（重复时有效，默认 1）",
            },
            "wake": {
                "type": "boolean",
                "description": (
                    "到点后自动续跑当前会话。仅当前真实用户输入触发的顶层 run 可授权；"
                    "默认 false 只通知。周期任务请用 task_mode=task_recurring。"
                ),
            },
            "task_mode": {
                "type": "string",
                "enum": ["remind", "task_once", "task_recurring"],
                "description": (
                    "任务语义（设计 §2）：remind=到点仅通知；task_once=一次性续跑"
                    "（等价 wake=true）；task_recurring=创建时签发常驻授权（N 次/有效期），"
                    "每次到点**开新会话**执行正文。不允许把 notify 当执行入口。"
                ),
            },
            "wake_fires": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "description": "task_recurring 的常驻授权总次数（= 最多触发次数，硬上限 90）；用尽即降级为通知。",
            },
            "wake_expires_in_days": {
                "type": "number",
                "maximum": 90,
                "description": "task_recurring 的授权有效期（天，硬上限 90；缺省 30）；过期未用完也降级为通知。",
            },
            "wake_external": {
                "type": "boolean",
                "description": (
                    "task_recurring 是否授权外部副作用（发布/发送/改动外部系统）。"
                    "默认 false；仅推广类任务应显式开启，知识/巡检类保持关闭。"
                ),
            },
            "wake_pool": {
                "type": "boolean",
                "description": (
                    "task_recurring 是否加入当前 Goal 的授权池：同一 Goal 下的多条常驻条目共享"
                    "一份额度/到期（首次开池定规格，后来者只能按同规格加入）。默认 false。"
                ),
            },
            "dispatch": {
                "type": "string",
                "enum": ["new_session", "session"],
                "description": "task_recurring 的投递目标，默认 new_session（开新会话，不占用原会话 run 槽）。",
            },
            "subject_refs": {
                "type": "array",
                "description": (
                    "可选自报对象引用：唤醒时程序会把这些对象的现状差量（终态/generation 前移/"
                    "动作状态，仅事实无结论）附于唤醒消息。type 为封闭枚举"
                    "（job_id/expected_generation/action_id），未知类型按参数错误拒绝。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["job_id", "expected_generation", "action_id"],
                        },
                        "id": {
                            "type": "string",
                            "description": "引用对象标识（job id / 排程时观察到的 generation 值 / action id）",
                        },
                    },
                    "required": ["type", "id"],
                },
            },
            "event_predicate": {
                "type": "string",
                "enum": ["job_terminal", "generation_reached", "action_settled"],
                "description": (
                    "Phase3 M4：事件谓词唤醒（闭集枚举）。与 after/at 超时构成双通道竞速——"
                    "先到者触发唤醒，后到者只记录不重放。要求 wake=true（谓词不携带授权语义，"
                    "授权仍由当前真人 run 的 wake_grant 链独占）且不可用于周期条目。"
                    "示例：后台 job 完成即唤醒，最多等 after 秒兜底。"
                    "可用性（终审 P2-7 留痕）：当前生产装配仅登记 job_terminal 求值器；"
                    "generation_reached/action_settled 尚无生产求值器，登记前会回退为纯超时唤醒（一次性告警）。"
                ),
            },
            "predicate_ref": {
                "type": "string",
                "description": "谓词对象引用（job_id / 目标 generation 值 / action_id），与 event_predicate 配套必填。",
            },
        },
        "required": ["message"],
    }

    def __init__(
        self,
        store: ScheduleStore | None = None,
        *,
        goal_binding_resolver: Callable[[str], tuple[str, str] | None] | None = None,
    ) -> None:
        self._store = store
        self._goal_binding_resolver = goal_binding_resolver

    def _get_store(self) -> ScheduleStore:
        if self._store is None:
            self._store = ScheduleStore()
        return self._store

    def execute(self, **kwargs) -> ToolResult:
        try:
            message = str(kwargs.get("message", "") or "").strip()
            after = float(kwargs.get("after", 0) or 0)
            at = str(kwargs.get("at", "") or "").strip()
            repeat_interval = float(kwargs.get("repeat_interval", 0) or 0)
            max_count = int(kwargs.get("max_count", 1) or 1)
            wake = bool(kwargs.get("wake", False))
            task_mode = str(kwargs.get("task_mode", "") or "").strip()
            wake_dispatch = str(kwargs.get("dispatch", "") or "").strip()
            wake_fires = int(kwargs.get("wake_fires", 0) or 0)
            wake_expires_in_days = float(kwargs.get("wake_expires_in_days", 0) or 0)
            wake_external = bool(kwargs.get("wake_external", False))
            wake_pool = bool(kwargs.get("wake_pool", False))
            subject_refs_raw = kwargs.get("subject_refs") or []
            event_predicate = str(kwargs.get("event_predicate", "") or "").strip()
            predicate_ref = str(kwargs.get("predicate_ref", "") or "").strip()
        except (TypeError, ValueError) as exc:
            # 审查低危修复: 参数类型转换异常如实返回 FAILURE（原实现直接外抛）
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] 参数类型非法: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        if not message:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'message'",
                tool_call_id="",
                tool_name=self.name,
            )
        if len(message) > _MAX_SCHEDULE_MESSAGE_CHARS:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] message 最多 {_MAX_SCHEDULE_MESSAGE_CHARS} 字符",
                tool_call_id="",
                tool_name=self.name,
            )
        if after < 0 or repeat_interval < 0:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] after/repeat_interval 必须 ≥ 0",
                tool_call_id="",
                tool_name=self.name,
            )

        # antidrift R1: subject_refs 封闭枚举校验（参数校验，非行为门禁；BindingProblemKind 同款封闭集纪律）
        if not isinstance(subject_refs_raw, list):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] subject_refs 必须为 {type,id} 对象数组",
                tool_call_id="",
                tool_name=self.name,
            )
        subject_refs: list[dict] = []
        for item in subject_refs_raw:
            if (
                not isinstance(item, dict)
                or not str(item.get("type", "") or "")
                or not str(item.get("id", "") or "")
            ):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] subject_refs 每条须含非空 type 与 id",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if str(item.get("type")) not in _SUBJECT_REF_TYPES:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[参数错误] subject_refs.type 未知类型: "
                        f"{item.get('type')}（封闭集: {'/'.join(_SUBJECT_REF_TYPES)}）"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            subject_refs.append({"type": str(item["type"]), "id": str(item["id"])})

        if task_mode and task_mode not in ("remind", "task_once", "task_recurring"):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] task_mode 未知: {task_mode}（封闭集: remind/task_once/task_recurring）",
                tool_call_id="",
                tool_name=self.name,
            )
        if wake_dispatch and wake_dispatch not in ("new_session", "session"):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] dispatch 未知: {wake_dispatch}（封闭集: new_session/session）",
                tool_call_id="",
                tool_name=self.name,
            )
        if task_mode == "task_recurring":
            wake = True
            if repeat_interval <= 0 or wake_fires < 1:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] task_recurring 需要 repeat_interval>0 且 wake_fires>=1（创建时签发常驻授权）",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if wake_fires > 90 or wake_expires_in_days > 90:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] 常驻授权硬上限：wake_fires≤90、wake_expires_in_days≤90",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if wake_expires_in_days <= 0:
                wake_expires_in_days = 30.0  # 缺省有效期：不给「永久授权」留口子
        elif task_mode == "task_once":
            wake = True
        elif task_mode == "remind":
            wake = False

        if wake and repeat_interval > 0 and task_mode != "task_recurring":
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] 周期任务需要 task_mode=task_recurring：创建时签发 N 次常驻授权，"
                    "每次到点开新会话执行；只想提醒请用 task_mode=remind（到点仅通知）"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        # 绝对时间解析（ISO，本地时区；带 Z 视为 UTC）
        at_ts: float | None = None
        if at:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(at)
                if dt.tzinfo is None:
                    dt = dt.astimezone()  # 无时区按本地
                at_ts = dt.timestamp()
            except ValueError:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] at 时间格式非法（期望 ISO 如 '2026-08-17T10:00:00'）: {at}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            # 审查低危修复: at 过去时间如实拒绝（原实现静默立即触发——"at 过去不校验"）
            import time as _time

            if at_ts < _time.time() - 5:  # 5s 容差（时钟偏差/构造-注册间隙）
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] at 时间已过去（{at}），请检查或改用 after",
                    tool_call_id="",
                    tool_name=self.name,
                )

        wake_grant = None
        wake_session_id = ""
        wake_goal_id = ""
        wake_goal_generation = ""
        if wake:
            wake_session_id = current_session_id.get()
            ingress_session_id = current_ingress_session_id.get()
            ingress = current_ingress_token.get()
            if not wake_session_id or ingress_session_id != wake_session_id or ingress is None:
                return ToolResult(
                    status=ToolResultStatus.UNAUTHORIZED,
                    content=(
                        "[schedule] wake=true 需要当前真实用户输入绑定的同会话授权；"
                        "后台/子代理/无 ingress 上下文不能创建自动续跑。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            try:
                wake_grant = delegate_ingress(ingress, entry="schedule_wake")
            except ValueError as exc:
                return ToolResult(
                    status=ToolResultStatus.UNAUTHORIZED,
                    content=f"[schedule] 自动续跑授权失败: {exc}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if self._goal_binding_resolver is not None:
                try:
                    binding = self._goal_binding_resolver(wake_session_id)
                except Exception as exc:  # noqa: BLE001 — lifecycle authority cannot be guessed
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            "[schedule] 当前 Goal 生命周期身份不可核验，未创建自动续跑；"
                            f"error={type(exc).__name__}"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                    )
                if binding is not None:
                    wake_goal_id, wake_goal_generation = binding

        wake_expires_at_ts = (
            time.time() + wake_expires_in_days * 86400.0 if wake_expires_in_days > 0 else 0.0
        )
        # Goal 级授权池：池 id 只能是当前绑定的 goal（不接受模型自报），
        # 首次开池定规格；后来者按池规格加入，不能借此抬高额度或延长有效期。
        pool_id = wake_goal_id if (wake_pool and task_mode == "task_recurring") else ""
        if wake_pool and not pool_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] wake_pool 需要 task_mode=task_recurring 且当前会话已绑定 Goal",
                tool_call_id="",
                tool_name=self.name,
            )
        pool_facts = None
        if pool_id:
            pool_facts = self._get_store().pool_facts(pool_id)
            if pool_facts is not None:
                if pool_facts.get("state") != "pending":
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=(
                            f"[schedule] Goal 授权池已关闭（{pool_facts.get('state')}）；"
                            "不会再签发新成员，请显式新建一次授权"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                    )
                pool_workdir = str(pool_facts.get("workdir") or "")
                current_workdir = str(current_workspace_root.get() or "")
                if pool_workdir and os.path.realpath(pool_workdir) != os.path.realpath(current_workdir):
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=(
                            "[schedule] 当前工作目录与授权池钉死的目录不一致，未加入池："
                            f"pool={pool_workdir}"
                        ),
                        tool_call_id="",
                        tool_name=self.name,
                    )
                wake_fires = max(1, int(pool_facts.get("fires_total") or 0))
                wake_expires_at_ts = float(pool_facts.get("expires_at") or 0.0)
                wake_external = bool(pool_facts.get("external"))

        try:
            sid = self._get_store().add(
                message, after=after, at=at_ts, repeat_interval=repeat_interval,
                max_count=max_count, wake=wake, session_id=wake_session_id,
                wake_grant=wake_grant, goal_id=wake_goal_id,
                goal_generation=wake_goal_generation,
                subject_refs=subject_refs,
                event_predicate=event_predicate,
                predicate_ref=predicate_ref,
                task_mode=task_mode,
                wake_dispatch=wake_dispatch,
                wake_fires=wake_fires,
                wake_expires_at=wake_expires_at_ts,
                wake_external=wake_external,
                wake_workdir=str(current_workspace_root.get() or os.getcwd()),
                wake_pool=pool_id,
            )
        except ValueError as exc:  # M4：闭集/授权约束在落盘前拒绝
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[schedule] 参数约束拒绝：{exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        except ScheduleCommitUncertainError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[schedule] commit_outcome_uncertain: "
                    f"sid={exc.sid}; visible_state={exc.visible_state}; "
                    "durability_confirmed=false; retry_safe=false。"
                    "当前文件可见状态已机械核对；不要直接重复注册同一提醒，"
                    "先按 sid/会话排程事实 reconcile。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except SchedulePersistError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[schedule] definitely_not_committed: "
                    f"sid={exc.sid or '-'}; "
                    f"retry_safe={'true' if exc.retry_safe else 'false'}; error={exc}"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        when = f"after {after}s" if after > 0 else (f"at {at}" if at else "immediate")
        if repeat_interval > 0:
            when += f"（每 {repeat_interval}s，最多 {max_count} 次）"
        delivery = "到点自动续跑当前会话" if wake else "到点仅发送通知"
        if task_mode == "task_recurring":
            delivery = (
                f"到点开新会话执行（常驻授权 {wake_fires} 次"
                + (f"，{wake_expires_in_days:g} 天内有效" if wake_expires_in_days > 0 else "")
                + ("，允许外部副作用" if wake_external else "，不授权外部副作用")
                + (
                    f"；已加入 Goal 授权池，共享额度 "
                    f"{int(pool_facts.get('fires_used') or 0)}/{int(pool_facts.get('fires_total') or 0)}"
                    if pool_facts
                    else ""
                )
                + "）"
            )
        content = f"[schedule] 已注册提醒 {sid}: '{message}'（{when}；{delivery}）。"
        # antidrift R5: 同会话 wake 排程的分叉选项披露（非门禁，排程已照常生效）
        if wake and wake_session_id == current_session_id.get():
            content += (
                "\n[提示] 独立验证/巡检类子任务建议排程至分叉会话"
                "（协议见 docs/wake-fork-protocol.md）；本提示为选项披露，排程已照常生效"
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )


class ScheduleCancelTool:
    """取消已注册提醒（审查 P2: 无取消工具 → 提醒只能等触发/重启清除）."""

    name = "schedule_cancel"
    description = (
        "取消已注册的定时提醒（按 sid，来自 schedule 工具回执）。"
        "何时用: 提醒不再需要/重复注册后清理。"
        "失败对策: sid 不存在如实返回。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "sid": {
                "type": "string",
                "description": "要取消的提醒 sid（schedule 工具回执中给出）",
            },
            "revoke_only": {
                "type": "boolean",
                "description": (
                    "只撤销常驻授权、保留条目：之后到点仅通知，不再开新会话执行。"
                    "默认 false（整条取消）。"
                ),
            },
        },
        "required": ["sid"],
    }

    def __init__(self, store: ScheduleStore | None = None) -> None:
        self._store = store

    def _get_store(self) -> ScheduleStore:
        if self._store is None:
            self._store = ScheduleStore()
        return self._store

    def execute(self, **kwargs) -> ToolResult:
        sid = str(kwargs.get("sid", "") or "").strip()
        if not sid:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'sid'",
                tool_call_id="",
                tool_name=self.name,
            )
        revoke_only = bool(kwargs.get("revoke_only", False))
        if revoke_only:
            try:
                revoked = self._get_store().revoke_wake_grant(sid)
            except ScheduleCommitUncertainError as exc:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "[schedule_cancel] commit_outcome_uncertain: "
                        f"sid={sid}; visible_state={exc.visible_state}; "
                        f"retry_safe={'true' if exc.retry_safe else 'false'}。"
                        "撤销授权按同 sid 幂等，可重试核对。"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
            except Exception as exc:  # noqa: BLE001 — fail-open 如实回执
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=f"[schedule_cancel] 撤销授权失败: {type(exc).__name__}: {exc}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if not revoked:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        f"[schedule_cancel] {sid} 没有可撤销的常驻授权"
                        "（sid 不存在，或该条目本来就只通知）"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[schedule_cancel] 已撤销 {sid} 的常驻授权；条目保留，"
                    "到点仅通知，不再开新会话执行"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            removed = self._get_store().cancel(sid)
        except ScheduleCommitUncertainError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[schedule_cancel] commit_outcome_uncertain: "
                    f"sid={sid}; visible_state={exc.visible_state}; "
                    "durability_confirmed=false; "
                    f"retry_safe={'true' if exc.retry_safe else 'false'}。"
                    "取消是同 sid 幂等操作，可用同一 sid 重试/核对排程事实；"
                    "不要创建替代提醒。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except SchedulePersistError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=(
                    "[schedule_cancel] definitely_not_committed: "
                    f"sid={sid}; retry_safe={'true' if exc.retry_safe else 'false'}; "
                    f"error={exc}"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open 如实回执
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[schedule_cancel] 取消失败: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        if removed:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[schedule_cancel] 已取消提醒 {sid}",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[schedule_cancel] 提醒 {sid} 不存在（可能已触发或已取消）",
            tool_call_id="",
            tool_name=self.name,
        )


class ScheduleUpgradeTool:
    """把已有周期提醒原地升级为常驻授权任务（迁移/重建授权用）。"""

    name = "schedule_upgrade"
    description = (
        "把一条已存在的周期提醒原地升级为常驻授权的自动执行任务：保留 sid、正文与节奏，"
        "只新增「N 次 / 有效期内，到点开新会话执行」的授权。"
        "何时用: 老的 notify 提醒要改成自动执行，或给已建条目补一份授权。"
        "何时不用: 新建任务直接 schedule(task_mode=task_recurring)。"
        "失败对策: sid/参数/授权不满足时如实返回；账本签发失败则条目保持原样。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "sid": {"type": "string", "description": "要升级的周期提醒 sid"},
            "wake_fires": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "description": "常驻授权总次数（硬上限 90），默认 30",
            },
            "wake_expires_in_days": {
                "type": "number",
                "maximum": 90,
                "description": "授权有效期（天，硬上限 90），默认 30",
            },
            "wake_external": {
                "type": "boolean",
                "description": "是否授权外部副作用（发布/发送/改动外部系统），默认 false",
            },
            "wake_pool": {
                "type": "boolean",
                "description": "是否加入该条目所属 Goal 的授权池，默认 false",
            },
        },
        "required": ["sid"],
    }

    def __init__(self, store: ScheduleStore | None = None) -> None:
        self._store = store

    def _get_store(self) -> ScheduleStore:
        if self._store is None:
            self._store = ScheduleStore()
        return self._store

    def execute(self, **kwargs) -> ToolResult:
        sid = str(kwargs.get("sid", "") or "").strip()
        if not sid:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'sid'",
                tool_call_id="",
                tool_name=self.name,
            )
        fires = int(kwargs.get("wake_fires") or 0) or 30
        days = float(kwargs.get("wake_expires_in_days") or 0) or 30.0
        external = bool(kwargs.get("wake_external", False))
        want_pool = bool(kwargs.get("wake_pool", False))
        if (
            fires < 1
            or fires > task_grant.MAX_WAKE_FIRES
            or days <= 0
            or days > task_grant.MAX_WAKE_EXPIRY_S / 86400.0
        ):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 常驻授权硬上限：wake_fires≤90、wake_expires_in_days≤90",
                tool_call_id="",
                tool_name=self.name,
            )
        session = current_session_id.get()
        ingress = current_ingress_token.get()
        # delegated=True 的 token 来自子代理/定时续跑，不能签发常驻授权（与 create 路径同一铁律）。
        if (
            not session
            or current_ingress_session_id.get() != session
            or ingress is None
            or getattr(ingress, "delegated", False)
        ):
            return ToolResult(
                status=ToolResultStatus.UNAUTHORIZED,
                content="[schedule_upgrade] 需要当前真实用户输入绑定的同会话、未委派授权",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            grant = delegate_ingress(ingress, entry="schedule_wake")
        except ValueError as exc:
            return ToolResult(
                status=ToolResultStatus.UNAUTHORIZED,
                content=f"[schedule_upgrade] 授权失败: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        store = self._get_store()
        row = next((entry for entry in store.list() if entry["sid"] == sid), None)
        if row is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[schedule_upgrade] {sid} 不存在",
                tool_call_id="",
                tool_name=self.name,
            )
        pool_id = str(row.get("goal_id") or "")
        if want_pool and not pool_id:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[schedule_upgrade] {sid} 未绑定 Goal，无法加入授权池",
                tool_call_id="",
                tool_name=self.name,
            )
        try:
            store.upgrade_to_standing(
                sid,
                grant=grant,
                session_id=session,
                fires=fires,
                expires_at=time.time() + days * 86400.0,
                external=external,
                workdir=str(current_workspace_root.get() or os.getcwd()),
                pool=pool_id if want_pool else "",
            )
        except KeyError:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[schedule_upgrade] {sid} 不存在",
                tool_call_id="",
                tool_name=self.name,
            )
        except ValueError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[schedule_upgrade] 拒绝升级：{exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        except Exception as exc:  # noqa: BLE001 — 如实回执
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[schedule_upgrade] 升级失败: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[schedule_upgrade] {sid} 已升级为常驻授权任务：{fires} 次 / {days:g} 天，"
                f"到点开新会话执行；外部副作用{'已授权' if external else '未授权'}"
                + (f"；已加入 Goal 授权池 {pool_id}" if want_pool and pool_id else "")
                + "。"
            ),
            tool_call_id="",
            tool_name=self.name,
        )
