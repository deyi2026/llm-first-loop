"""任务重启授权守卫（G5 / C-G5，spec 5.2 / design B-1~B-3）.

用户规则（2026-09-02 口谕）："过去的任务，已经做过的，不应该起；就算有
未完成的任务需要起也要问了用户才起。"——恢复类入口必须过授权门：

- ``check_restart``：仅显式 /continue 控制入口判定（deny/confirm/allow，只读）；
- 普通自然语言（包括“继续/重跑”）不再进入本服务，交由模型依据最近交互判断；
- ``match_reply`` / ``consume_grant``：显式 /continue 确认帧的一次性票据（frame_id 用后即焚），
  授权到达时刻复核终态（等待期已 completed → 转拒绝，spec 5.2.3-3）；
- 显式重跑 completed → 拒绝并引导按新任务建模（新 goal_id、旧终态只读，D11）。

判定口径（spec 5.2.1，术语 spec"completed"= 账本 done/complete）：查询异常 →
confirm(state_unknown)（决策 3，宁可多问不可误跑）；无活跃 goal/无已开始任务 →
allow；goal complete 或全任务终态 → deny(completed)；已开始未完成 → confirm。

审计（经注入 audit_fn 落 action_trace.jsonl，fail-open）：restart.confirm /
restart.denied / restart.authorization / restart.guard_error。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger(__name__)

STATE_UNKNOWN = "state_unknown"
DEF_CONFIRM_TTL_S = 24 * 3600.0
_STARTED_STATUSES = ("in_progress", "blocked", "done")

_APPROVE_WORDS = (
    "同意",
    "继续",
    "确认",
    "好的",
    "可以",
    "开始吧",
    "做吧",
    "执行吧",
    "恢复执行",
    "approve",
    "yes",
    "ok",
)
_DENY_WORDS = (
    "拒绝",
    "不同意",
    "不要",
    "不要继续",
    "不继续",
    "不可以",
    "不行",
    "不执行",
    "取消",
    "停止",
    "先不",
    "deny",
    "no",
)

AuditFn = Any  # (phase, action_type, detail) -> None


def confirm_ttl_s() -> float:
    """确认帧等待超时窗口（env ``LFL_RESTART_CONFIRM_TTL_S``，默认 24h，非法回退默认）."""
    raw = os.environ.get("LFL_RESTART_CONFIRM_TTL_S", "").strip()
    if not raw:
        return DEF_CONFIRM_TTL_S
    try:
        val = float(raw)
    except ValueError:
        logger.warning("LFL_RESTART_CONFIRM_TTL_S 非法（%r），回退默认 24h", raw)
        return DEF_CONFIRM_TTL_S
    return val if val > 0 else DEF_CONFIRM_TTL_S


def classify_reply(text: str) -> str:
    """Pending control-frame reply classifier: exact allowlist, no prose semantics.

    This runs only after a real ``/continue`` confirmation frame exists.  Exact-match
    semantics are deliberate: ordinary prose containing words such as ``继续`` or
    ``同意`` must never become an authorization token by substring accident.
    """
    low = text.strip().lower().strip("。.!！?？,，;；")
    if not low:
        return "none"
    if low in _DENY_WORDS:
        return "deny"
    if low in _APPROVE_WORDS:
        return "approve"
    return "refer" if low.startswith("frame:") else "none"


@dataclass(frozen=True)
class RestartConfirmationFrame:
    """确认帧/通知帧（design §2.3.2；spec 6.3：任务标识 + 进度锚点 + 待续概要）."""

    frame_id: str
    goal_id: str
    task_summary: str
    anchor_source: str
    current_sub_item: str
    next_step: str
    pending_summary: str
    created_at: str


@dataclass(frozen=True)
class RestartDecision:
    """显式 /continue 判定结果：allow 直跑 / deny 拒绝 / confirm 确认帧挂起."""

    kind: str
    goal_id: str = ""
    reason: str = ""  # deny: "completed"；confirm: STATE_UNKNOWN / "unfinished" / "frame_invalid"
    frame: RestartConfirmationFrame | None = None


@dataclass(frozen=True)
class GrantResult:
    """授权应答处置结果（B-2）."""

    ok: bool
    decision: str  # approved | denied | timeout | mismatch | consumed | none
    session_id: str = ""
    goal_id: str = ""
    frame_id: str = ""
    command_text: str = ""  # approved 时执行最初排队的显式控制命令（当前仅 /continue）
    reason: str = ""  # denied 细分：user（用户拒绝）/ completed（授权时刻复核已终态）


@dataclass(frozen=True)
class PendingEntry:
    """pending 确认帧登记（对齐 ``_user_stop_pending`` 先例：锁保护 + 惰性超时剔除）."""

    session_id: str
    goal_id: str
    created_at: float
    expiry_s: float
    command_text: str = "/continue"
    consumed: bool = False


@dataclass(frozen=True)
class _GoalSnapshot:
    """活跃 goal 终态快照（只读查询产物；error 非空 = 状态未知）."""

    session_id: str = ""
    error: str = ""
    goal_id: str = ""
    goal_status: str = ""
    task_summary: str = ""
    all_terminal: bool = False
    started: bool = False
    summary_unknown: bool = False  # 任务列表读取失败 → 待续概要须如实标注"状态未知"


def frame_complete(frame: RestartConfirmationFrame | None) -> bool:
    """帧完整性校验：缺任务标识或缺进度信息 → 无效不上送（spec 6.3-1/3、5.2.1-5 禁止项）."""
    if frame is None or not frame.goal_id.strip():
        return False
    return bool(
        frame.pending_summary.strip() or frame.current_sub_item.strip() or frame.next_step.strip()
    )


def confirmation_frame_text(frame: RestartConfirmationFrame) -> str:
    """确认帧用户文案（程序来源前缀 + 知情决定要素：标识/锚点/待续/授权问句）."""
    return (
        f"[重启确认] 任务 {frame.goal_id} 已开始且尚未完成，需你授权后才继续执行。\n"
        f"任务：{frame.task_summary or frame.goal_id}\n"
        f"进度锚点[{frame.anchor_source}]：当前 {frame.current_sub_item or '（无）'}；"
        f"下一步 {frame.next_step or '（无）'}\n"
        f"{frame.pending_summary}\n"
        f"回复「同意」授权继续执行；回复「拒绝」则本次不执行。"
    )


class RestartGuardService:
    """重启授权守卫（feishu 服务层；只读查询，不改 goal/task 账本）."""

    def __init__(
        self, engine: Any, *, audit_fn: AuditFn | None = None, ttl_s: float | None = None
    ) -> None:
        self._engine = engine
        self._audit_fn = audit_fn
        self._ttl_s = ttl_s if ttl_s is not None and ttl_s > 0 else confirm_ttl_s()
        self._pending: dict[str, PendingEntry] = {}
        self._lock = threading.Lock()

    # ── 判定入口（B-1 / B-3）──

    def check_restart(self, session_id: str) -> RestartDecision:
        """显式 /continue 入口的只读状态判定；查询异常 → confirm 兜底."""
        snap = self._query_goal_state(session_id)
        verdict = self._judge_snapshot(snap)
        if verdict is not None:
            return self._attach_unknown_frame(session_id, verdict, snap)
        return self._build_confirm(session_id, snap)

    def _judge_snapshot(self, snap: _GoalSnapshot) -> RestartDecision | None:
        """终态判定状态机（design §2.1.3.3）；返回 None = 已开始未完成（待 notify/confirm 分流）."""
        if snap.error:
            return RestartDecision(kind="confirm", goal_id=snap.goal_id, reason=STATE_UNKNOWN)
        if not snap.goal_id:
            return RestartDecision(kind="allow")  # 无活跃 goal → 维持现状直跑
        if snap.goal_status == "complete" or snap.all_terminal:
            self._audit("restart.denied", f"goal_id={snap.goal_id}; reason=completed")
            return RestartDecision(kind="deny", goal_id=snap.goal_id, reason="completed")
        if not snap.started:
            return RestartDecision(kind="allow")  # 无已开始任务（goal 活跃但任务全 pending/无任务）
        return None

    def _attach_unknown_frame(
        self, session_id: str, verdict: RestartDecision, snap: _GoalSnapshot
    ) -> RestartDecision:
        """state_unknown 兜底：goal 已知时补"状态未知"标注帧（spec 6.3-2）；否则纯 confirm."""
        if verdict.reason != STATE_UNKNOWN:
            return verdict
        frame = self._make_frame(session_id, snap, STATE_UNKNOWN) if snap.goal_id else None
        if frame is not None and frame_complete(frame):
            self._audit(
                "restart.confirm",
                f"frame_id={frame.frame_id}; goal_id={frame.goal_id}; "
                f"anchor_source={frame.anchor_source}; state={STATE_UNKNOWN}",
            )
            self._register(session_id, snap.goal_id, frame.frame_id)
            return replace(verdict, frame=frame)
        self._audit(
            "restart.confirm",
            f"frame_id=-; goal_id={snap.goal_id or '-'}; anchor_source={STATE_UNKNOWN}; state={STATE_UNKNOWN}",
        )
        return verdict

    # ── 只读状态查询（GoalStore/TaskStore 异常内部消化 → 状态未知）──

    def _query_goal_state(self, session_id: str) -> _GoalSnapshot:
        from llm_loop.introspection.goal import GoalStore

        try:
            # strict_session=True（CR-R1.1 会话隔离读取）：禁跨会话全局回退——
            # 新会话/无 goal 会话不得误见其它会话的 goal（否则全新任务被误 deny/notify）
            goal = GoalStore(self._audit_dir()).get(
                prefer_session_id=session_id, strict_session=True
            )
        except Exception as exc:  # noqa: BLE001 — 决策 3：查询异常按状态未知兜底
            logger.warning("重启守卫 goal 查询失败（按状态未知兜底）: %s", exc)
            self._audit("restart.guard_error", f"stage=goal_query; error={str(exc)[:150]}")
            return _GoalSnapshot(session_id=session_id, error=str(exc)[:200])
        if not goal or not goal.get("id"):
            return _GoalSnapshot(session_id=session_id)
        return self._query_task_state(session_id, goal)

    def _query_task_state(self, session_id: str, goal: dict) -> _GoalSnapshot:
        from llm_loop.introspection.task_store import TERMINAL_STATUSES, TaskStore

        base = _GoalSnapshot(
            session_id=session_id,
            goal_id=str(goal.get("id", "")),
            goal_status=str(goal.get("status", "")),
            task_summary=str(goal.get("objective", "")),
        )
        try:
            tasks = TaskStore(self._audit_dir()).list_for_goal(base.goal_id)
        except Exception as exc:  # noqa: BLE001 — 任务读取失败 → 状态未知（goal 已知）
            logger.warning("重启守卫任务查询失败（按状态未知兜底）: %s", exc)
            self._audit("restart.guard_error", f"stage=task_query; error={str(exc)[:150]}")
            return replace(base, error=str(exc)[:200], summary_unknown=True)
        if not tasks:
            return base
        all_terminal = all(t.status in TERMINAL_STATUSES for t in tasks)
        started = any(t.status in _STARTED_STATUSES for t in tasks)
        return replace(base, all_terminal=all_terminal, started=started)

    def _audit_dir(self) -> str:
        settings = getattr(self._engine, "settings", None)
        ad = getattr(settings, "audit_dir", None)
        return "data/audit" if ad is None else str(ad)

    # ── 帧构造（B-2 / T5.2）──

    def _build_confirm(self, session_id: str, snap: _GoalSnapshot) -> RestartDecision:
        """confirm 分支：生成确认帧 → 完整性校验 → 审计 restart.confirm + 登记 pending."""
        frame = self._make_frame(session_id, snap, "")
        if not frame_complete(frame):
            logger.warning("重启确认帧不完整（缺任务标识/进度信息），未上送: goal=%s", snap.goal_id)
            return RestartDecision(kind="confirm", goal_id=snap.goal_id, reason="frame_invalid")
        self._audit(
            "restart.confirm",
            f"frame_id={frame.frame_id}; goal_id={frame.goal_id}; "
            f"anchor_source={frame.anchor_source}; state=unfinished",
        )
        self._register(session_id, snap.goal_id, frame.frame_id)
        return RestartDecision(
            kind="confirm", goal_id=snap.goal_id, reason="unfinished", frame=frame
        )

    def _make_frame(
        self, session_id: str, snap: _GoalSnapshot, state_note: str
    ) -> RestartConfirmationFrame:
        """帧装配：锚点复用 ResumeAnchorReader（三层降级）；待续概要 frontier 聚合一句话."""
        anchor_source, current, nxt = self._read_anchor_parts(session_id, state_note)
        return RestartConfirmationFrame(
            frame_id=uuid.uuid4().hex,
            goal_id=snap.goal_id,
            task_summary=snap.task_summary,
            anchor_source=anchor_source,
            current_sub_item=current,
            next_step=nxt,
            pending_summary=self._frontier_summary(snap, state_note),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        )

    def _read_anchor_parts(self, session_id: str, state_note: str) -> tuple[str, str, str]:
        """锚点读取（只读复用，三层降级 execution-cursor→checkpoint→none）；未知如实标注."""
        if state_note == STATE_UNKNOWN:
            return STATE_UNKNOWN, "状态未知", "状态未知"
        from llm_loop.feishu.resume import ResumeAnchorReader

        try:
            anchor = ResumeAnchorReader().read_anchor(session_id, self._audit_dir())
        except Exception as exc:  # noqa: BLE001 — 锚点读取失败如实降级 none
            logger.warning("重启确认帧锚点读取失败（降级 none）: %s", exc)
            return "none", "", ""
        if anchor is None:
            return "none", "", ""
        return anchor.source, anchor.current_sub_item, anchor.next_step

    def _frontier_summary(self, snap: _GoalSnapshot, state_note: str) -> str:
        """待续概要聚合一句话（design §2.1.3.3）；任务库不可读时如实标注"状态未知"."""
        if state_note == STATE_UNKNOWN or snap.summary_unknown:
            return "待续概要：状态未知（任务库读取异常，如实标注；确认后可继续）"
        try:
            from llm_loop.introspection.task_store import TaskStore

            fr = TaskStore(self._audit_dir()).compute_frontier(snap.goal_id)
        except Exception as exc:  # noqa: BLE001 — frontier 失败如实标注不阻断
            logger.warning("待续概要聚合失败（如实标注状态未知）: %s", exc)
            return "待续概要：状态未知（任务库读取异常，如实标注；确认后可继续）"
        doing = fr.get("in_progress") or []
        first = ""
        if doing:
            entry = doing[0]
            task = entry.get("task") if isinstance(entry, dict) else getattr(entry, "task", None)
            first = str(getattr(task, "title", "") or "")
        return (
            f"待续 {fr.get('open_count', 0)} 项：in_progress {first or '（无）'}；"
            f"ready {len(fr.get('ready') or [])} 项；blocked {len(fr.get('blocked') or [])} 项"
        )

    # ── 授权应答与票据（B-2 / T5.3，D7 一次性票据）──

    def match_reply(self, session_id: str, text: str) -> GrantResult:
        """Consume approval language only inside an existing scoped /continue frame.

        P1-A ordering is deliberate: without a pending control frame this function does
        not classify ordinary user prose at all. A natural-language ``继续/可以`` must
        therefore reach the model without producing a program intent or mismatch event.
        """
        with self._lock:
            now = time.time()
            had_expired = any(
                e.session_id == session_id and not e.consumed and now - e.created_at > e.expiry_s
                for e in self._pending.values()
            )
            self._purge_expired_locked(now)
            found = next(
                (
                    (fid, entry)
                    for fid, entry in self._pending.items()
                    if entry.session_id == session_id and not entry.consumed
                ),
                None,
            )
        if found is None:
            # Only an expired explicit control frame permits reply classification here.
            # With no such frame, ordinary user prose is not semantically inspected.
            if had_expired and classify_reply(text) != "none":
                return GrantResult(ok=False, decision="timeout", session_id=session_id)
            return GrantResult(ok=False, decision="none", session_id=session_id)
        intent = classify_reply(text)
        if intent == "none":
            return GrantResult(ok=False, decision="none", session_id=session_id)
        frame_id, entry = found
        if intent == "refer":
            self._audit(
                "restart.authorization",
                f"frame_id={frame_id}; decision=mismatch; goal_id={entry.goal_id}",
            )
            return GrantResult(
                ok=False,
                decision="mismatch",
                session_id=session_id,
                goal_id=entry.goal_id,
                frame_id=frame_id,
            )
        if intent == "deny":
            self._remove(frame_id)
            self._audit(
                "restart.authorization",
                f"frame_id={frame_id}; decision=denied; goal_id={entry.goal_id}",
            )
            return GrantResult(
                ok=False,
                decision="denied",
                session_id=session_id,
                goal_id=entry.goal_id,
                frame_id=frame_id,
                reason="user",
            )
        return self._approve(session_id, frame_id, entry)

    def _approve(self, session_id: str, frame_id: str, entry: PendingEntry) -> GrantResult:
        """同意后复核终态；已完成或复核未知都不得启动。"""
        completed = self._recheck_completed(entry.goal_id)
        if completed is True:
            self._remove(frame_id)
            self._audit(
                "restart.authorization",
                f"frame_id={frame_id}; decision=denied; goal_id={entry.goal_id}; reason=completed",
            )
            return GrantResult(
                ok=False,
                decision="denied",
                session_id=session_id,
                goal_id=entry.goal_id,
                frame_id=frame_id,
                reason="completed",
            )
        if completed is None:
            self._remove(frame_id)
            self._audit(
                "restart.authorization",
                f"frame_id={frame_id}; decision=denied; goal_id={entry.goal_id}; reason={STATE_UNKNOWN}",
            )
            return GrantResult(
                ok=False,
                decision="denied",
                session_id=session_id,
                goal_id=entry.goal_id,
                frame_id=frame_id,
                reason=STATE_UNKNOWN,
            )
        grant = self.consume_grant(frame_id)
        if grant.ok:
            self._audit(
                "restart.authorization",
                f"frame_id={frame_id}; decision=approved; goal_id={entry.goal_id}",
            )
        return grant

    def consume_grant(self, frame_id: str) -> GrantResult:
        """一次性票据消费（用后即焚）；重复消费返回 consumed，不二次放行（D7）."""
        with self._lock:
            self._purge_expired_locked(time.time())
            entry = self._pending.get(frame_id)
            if entry is None:
                return GrantResult(ok=False, decision="mismatch")
            if entry.consumed:
                return GrantResult(
                    ok=False,
                    decision="consumed",
                    session_id=entry.session_id,
                    goal_id=entry.goal_id,
                    frame_id=frame_id,
                    command_text=entry.command_text,
                )
            self._pending[frame_id] = replace(entry, consumed=True)
            return GrantResult(
                ok=True,
                decision="approved",
                session_id=entry.session_id,
                goal_id=entry.goal_id,
                frame_id=frame_id,
                command_text=entry.command_text,
            )

    def _recheck_completed(self, goal_id: str) -> bool | None:
        """复核终态（只读）：True=完成，False=未完成，None=状态无法可靠读取。"""
        from llm_loop.introspection.task_store import TERMINAL_STATUSES

        try:
            from llm_loop.introspection.goal import GoalStore

            goal = GoalStore(self._audit_dir()).get(goal_id=goal_id)
            if goal and goal.get("status") == "complete":
                return True
            from llm_loop.introspection.task_store import TaskStore

            tasks = TaskStore(self._audit_dir()).list_for_goal(goal_id)
        except Exception as exc:  # noqa: BLE001 — 授权硬边界不可把未知状态当未完成
            logger.warning("授权复核终态失败（状态未知，本次不启动）: %s", exc)
            self._audit("restart.guard_error", f"stage=grant_recheck; error={str(exc)[:150]}")
            return None
        return bool(tasks and all(t.status in TERMINAL_STATUSES for t in tasks))

    # ── pending 登记（对齐 _user_stop_pending：锁 + 惰性超时剔除；同会话至多一帧）──

    def _register(self, session_id: str, goal_id: str, frame_id: str) -> None:
        now = time.time()
        with self._lock:
            for fid in [f for f, e in self._pending.items() if e.session_id == session_id]:
                self._pending.pop(fid, None)  # 同会话至多一帧（防串话第一道闸）
            self._pending[frame_id] = PendingEntry(
                session_id=session_id,
                goal_id=goal_id,
                created_at=now,
                expiry_s=self._ttl_s,
                command_text="/continue",
            )

    def _find_pending(self, session_id: str) -> tuple[str, PendingEntry] | None:
        with self._lock:
            self._purge_expired_locked(time.time())
            for fid, entry in self._pending.items():
                if entry.session_id == session_id and not entry.consumed:
                    return fid, entry
        return None

    def _purge_expired_locked(self, now: float) -> None:
        """惰性剔除过期帧；剔除即超时失效留痕（任务保持不执行，不降级自动执行）."""
        expired = [
            (fid, e)
            for fid, e in self._pending.items()
            if now - e.created_at > e.expiry_s and not e.consumed
        ]
        for fid, entry in expired:
            self._pending.pop(fid, None)
            self._audit(
                "restart.authorization",
                f"frame_id={fid}; decision=timeout; goal_id={entry.goal_id}",
            )

    def _remove(self, frame_id: str) -> None:
        with self._lock:
            self._pending.pop(frame_id, None)

    def pending_frame_count(self) -> int:
        """pending 帧数量（含已消费未清理条目；测试/观测用，只读）."""
        with self._lock:
            self._purge_expired_locked(time.time())
            return len(self._pending)

    # ── 审计（fail-open：审计异常不阻断判定主流程）──

    def _audit(self, action_type: str, detail: str) -> None:
        try:
            if self._audit_fn is not None:
                self._audit_fn("restart_guard", action_type, detail)
                return
            record = getattr(self._engine, "_record_action", None)
            if callable(record):
                record("restart_guard", action_type, detail)
        except Exception as exc:  # noqa: BLE001 — 审计失败不阻断守卫主流程
            logger.debug("restart guard audit failed: %s", exc)
