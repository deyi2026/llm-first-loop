"""Human Turn Queue：生成中排队的 Human Turn 的后端 durable 事实源.

设计契约（feature/webui-human-turn-queue-20260910）：
- 队列是后端 durable 事实：JSON 落盘，刷新/切会话/多标签/进程重启不丢不串。
- 入队时冻结本条事实：session_id / message / attachment refs+facts / model /
  reasoning_effort / created_at / queue_id——后续派发只消费冻结值，不读前端内存。
- 状态机：queued → claimed（dispatch 原子领取）→ completed | failed；
  queued → cancelled（用户取消）。
- FIFO：按 created_at 升序派发，同毫秒按入队序号 tie-break。
- claimed reaper：CLAIM_TIMEOUT_S 只表示“需要核验”，不是 run 死亡证明。超时后先
  读取机械 run/事件事实：active 保持 claimed；未开始才回滚 queued；已落 human ingress
  但无 run.end 进入 recovery_required（禁止整轮自动重发）；已有 run.end 则收敛终态。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

try:
    import fcntl  # noqa: F401 — POSIX 跨进程写互斥（Windows 等平台退化为实例内锁）
except ImportError:  # pragma: no cover
    fcntl = None

logger = logging.getLogger(__name__)

QUEUE_FILENAME = "human_turn_queue.json"
QUEUE_VERSION = 1
# claimed 悬挂回滚阈值：前端领取后应在数秒内发起正式 chat 请求；
# 60s 覆盖慢网络与短暂卡顿，同时避免崩溃标签长时间阻塞队列。
CLAIM_TIMEOUT_S = 60.0
INTERJECT_RECEIPT_VISIBLE_S = 8.0
# 终态滚动历史上限（compact 保最近 N 条终态）。可观测性 M1b：全局聚合视图的
# 数据窗口即此值——端点以 window_terminal_cap 如实标注（B5：防误读全历史）。
TERMINAL_HISTORY_KEEP_N = 500


def _now() -> float:
    return time.time()


class QueuePersistError(RuntimeError):
    """持久化失败分级（Phase3 D2 二分，对齐 schedule 的同名取舍）.

    stage:
      - ``definitely_not_committed``：临时文件写入失败，目标文件必然未变；
      - ``commit_outcome_uncertain``：rename 失败，内存态与磁盘态无法裁决。
    调用方（Web 端点）必须以 503 + 错误码如实透出，不得静默吞掉或假装成功。
    """

    def __init__(self, stage: str, detail: str = "") -> None:
        super().__init__(f"human turn queue persist {stage}: {detail}")
        self.stage = stage


class HumanTurnQueue:
    """会话级 human turn 队列（JSON 文件持久化为 durable 事实）.

    并发契约：读方法在实例内 _lock 下近似一致；写方法（enqueue/dispatch/
    release/cancel/interject 域/终态/compact）经 _exclusive_locked 全局互斥
    ——实例内 threading 锁 + 跨进程 flock + 锁内以磁盘 fresh reload 为起点，
    共享 data_dir 的多进程写互斥且单赢家（fcntl 不可用平台如实退化为实例
    内锁）。落盘为原子写（tempfile + os.replace）。
    """

    def __init__(
        self,
        data_dir: str | Path,
        claim_timeout_s: float = CLAIM_TIMEOUT_S,
        claim_state_probe: Callable[[str, str], str] | None = None,
        workspace_scope: str | None = None,
        legacy_scope_resolver: Callable[[str], str | None] | None = None,
        scope_provider: Callable[[], tuple[str | None, int | None]] | None = None,
    ) -> None:
        self._path = Path(data_dir) / QUEUE_FILENAME
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        self._seq = 0
        self._claim_timeout_s = claim_timeout_s
        self._claim_state_probe = claim_state_probe
        # M0 workspace/epoch 绑定（SA-RESUME-20261125）：本进程归属工作区根
        # （与 engine.workspace_root 同源）。非空时 enqueue 给条目盖章
        # workspace_scope，dispatch_claim 按 expected_workspace_scope 过滤——
        # 共享 data_dir 的多进程互不派发对方工作区的条目。升级前存量条目无
        # 盖章，仅在 legacy_scope_resolver（装配方经 SessionStore 既有
        # identity owner 机制组装）机械证明归属本工作区时可领取；未知/歧义/
        # 他区一律 HOLD 留队（fail-closed，不自动分配）。缺省 None=遗留行为
        # 不变（不盖章、不过滤、不解析）。
        self._workspace_scope = str(workspace_scope) if workspace_scope else None
        self._legacy_scope_resolver = legacy_scope_resolver
        # SA-SCOPE-HOTFIX-20261125（实机 q_c8a77451fdfb/q_a26bb24ce757 错章
        # EVO worktree 缺陷根治）：队列单例按 data_dir 缓存可跨 workspace 切换
        # 长寿命——构造时冻结 scope 在切换后成为"历史工作区"导致错章/错滤。
        # scope_provider 每次盖章实时读引擎当前 (workspace_root, epoch)，单例
        # 不再冻结动态 workspace；provider 异常 fail-closed（返回无章 → 领取
        # 侧按 legacy/无章路径裁决）。缺省退化为构造时冻结值（遗留兼容）。
        self._scope_provider = scope_provider

        # 进程启动期一次性重启恢复（live handoff 死亡 → durable queued 意图）；
        # 运行期 fresh reload 不做此重排（见 _recover_process_restart）。
        # P1-1（full_test 审查 subagent_48c95c6191a6）：构造期 load+恢复写
        # 同样纳入全局互斥——多进程构造竞态下无锁 _save 会以 stale 视图覆盖
        # 他进程刚写入的条目/领取事实。_exclusive_locked = flock + fresh
        # reload，恢复写全局单赢家（恢复语义不变：活性证明通过则保留 pending）。
        with self._exclusive_locked():
            self._recover_process_restart()

    def _current_scope_epoch(self) -> tuple[str | None, int | None]:
        """当前可信 (workspace_scope, epoch)：优先 scope_provider 实时读取，
        调用方应在 engine.workspace_snapshot 内调用保证原子一致；provider
        异常 → (None, None)（fail-closed：不盖章，交由领取侧裁决）；无
        provider → 构造时冻结值（遗留行为不变）。"""
        if self._scope_provider is not None:
            try:
                scope, epoch = self._scope_provider()
                return (
                    str(scope) if scope else None,
                    int(epoch) if epoch is not None else None,
                )
            except Exception:  # noqa: BLE001 — 读取失败不虚构归属
                logger.exception("queue scope_provider failed; treat as unbound")
                return (None, None)
        return (self._workspace_scope, None)

    # ------------------------------------------------------------------ 持久化

    def _load(self) -> None:
        """纯磁盘投影（fresh reload 路径）：JSON→内存，无任何语义迁移.

        interject_pending 是进程本地 live-run handoff——fresh reload 若顺带
        重排会把 live handoff 破坏成 queued（重复派发）。重启/孤儿恢复独立：
        重启走 _recover_process_restart（仅构造期一次性）；孤儿走既有
        reap_orphan_interjects 活性证明路径。"""
        if not self._path.exists():
            self._items = []
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = raw.get("items", [])
            assert isinstance(items, list)
        except Exception:  # noqa: BLE001 — 损坏文件如实降级为空队列并告警（不中断服务）
            logger.exception("human turn queue 文件损坏，按空队列处理: %s", self._path)
            items = []
        self._items = [it for it in items if isinstance(it, dict)]
        self._seq = max((int(it.get("_seq", 0)) for it in self._items), default=0)

    def _recover_process_restart(self) -> None:
        """进程启动期一次性重启恢复（构造时调用；持调用方锁）.

        interject_pending is a process-local live-run handoff. 恢复前经既有
        claim_state_probe（runner 活性 + 跨进程 lease 的机械事实）做活性/归属
        证明：证明 run 仍 active → 保留 live handoff（同进程多实例构造或
        接管窗口，绝不因刷新重排）；无法证明（not_started/unknown/未注入）
        → 信箱不可达，恢复 durable queued 意图。运行期 fresh reload 绝不
        调用此方法；孤儿回收另有 reap_orphan_interjects 活性证明路径。
        """
        recovered_pending = False
        for it in self._items:
            if it.get("status") != "interject_pending":
                continue
            if self._probe_claim_state(
                str(it.get("session_id")), str(it.get("queue_id"))
            ) == "active":
                continue  # 活性证明通过：run 仍在，保留 pending 不重排
            it["status"] = "queued"
            it["requeued_at"] = _now()
            it["requeued_from"] = "interject_process_restart"
            recovered_pending = True
        if recovered_pending:
            self._save()

    def _save(self) -> None:
        payload = {"version": QUEUE_VERSION, "items": self._items}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=QUEUE_FILENAME, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except BaseException as exc:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            # D2 二分（Phase3 §4.4，对齐 schedule 持久化分级）：临时文件创建/写入
            # 失败 ⇒ 目标文件必然未变 ⇒ definitely_not_committed；磁盘上无半写状态。
            raise QueuePersistError("definitely_not_committed", str(exc)) from exc
        try:
            os.replace(tmp, self._path)
        except BaseException as exc:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            # D2 二分：rename 失败时内存态已更新而磁盘旧文件可能已被替换或未替换，
            # 调用方不得假设任何一侧 ⇒ commit_outcome_uncertain（如实标注，不假装闭环）。
            raise QueuePersistError("commit_outcome_uncertain", str(exc)) from exc

    # ------------------------------------------------------------------ 内部

    @contextmanager
    def _exclusive_locked(self) -> Iterator[None]:
        """写侧全局互斥：实例内 threading 锁 + 跨进程 flock + 锁内 fresh reload.

        持久化是全文件覆盖写（tempfile+os.replace），实例内存是全量权威——
        共享 data_dir 的多进程（如多 workspace web 进程）若各自持 stale 内存
        视图互相覆盖，会丢他实例刚写入的条目/领取事实；仅靠实例内锁或原子
        replace 都不构成全局单赢家。写路径统一契约：flock 互斥 → 以磁盘
        fresh reload 为起点 → 读改写 → 原子替换落盘。锁文件与队列文件同
        目录（``human_turn_queue.json.lock``）。fcntl 不可用平台退化为实例
        内锁（契约如实降级，不虚称跨进程安全；8903 单进程部署不受影响）。
        """
        with self._lock:
            # 锁文件先于队列文件创建：新 data_dir 下 os.open 直接 ENOENT，
            # 故先确保目录存在（_save 自带 mkdir，但锁打开在 _save 之前）。
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(
                str(self._path.parent / (QUEUE_FILENAME + ".lock")),
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            try:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                self._load()  # fresh reload：磁盘为权威起点，防 stale 视图覆盖
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    def _probe_claim_state(self, session_id: str, queue_id: str) -> str:
        """Return one closed mechanical claim state; uncertainty fails closed."""
        probe = self._claim_state_probe
        if probe is None:
            return "unknown"
        try:
            state = str(probe(session_id, queue_id) or "unknown")
        except Exception:  # noqa: BLE001 - unknown must never become permission to replay
            logger.warning(
                "human turn claim state probe failed; keep claimed: sid=%s qid=%s",
                session_id,
                queue_id,
                exc_info=True,
            )
            return "unknown"
        if state not in {"not_started", "active", "ingress_open", "completed", "failed", "unknown"}:
            logger.warning("unknown human turn claim state %r; keep claimed", state)
            return "unknown"
        return state

    @staticmethod
    def _clear_recovery_fields(it: dict[str, Any]) -> None:
        it.pop("recovery_state", None)
        it.pop("recovery_required", None)

    def _reap_stale_claims_locked(self, now: float) -> None:
        """Reconcile stale claims from mechanical run facts; timeout alone never replays."""
        changed = False
        for it in self._items:
            if it.get("status") != "claimed":
                continue
            claimed_at = float(it.get("claimed_at") or 0)
            if not claimed_at or now - claimed_at <= self._claim_timeout_s:
                continue
            sid = str(it.get("session_id") or "")
            qid = str(it.get("queue_id") or "")
            state = self._probe_claim_state(sid, qid)
            if state == "not_started":
                it["status"] = "queued"
                it.pop("claimed_at", None)
                it.pop("claimed_by", None)
                self._clear_recovery_fields(it)
                it["requeued_at"] = now
                changed = True
            elif state in {"completed", "failed"}:
                it["status"] = state
                it["terminal_at"] = now
                it["reconciled_at"] = now
                it["reconciled_from"] = "durable_run_end"
                self._clear_recovery_fields(it)
                changed = True
            else:
                recovery_required = state == "ingress_open"
                if (
                    it.get("recovery_state") != state
                    or bool(it.get("recovery_required")) != recovery_required
                ):
                    it["recovery_state"] = state
                    it["recovery_required"] = recovery_required
                    changed = True
        if changed:
            self._save()

    def _active_items_locked(self, session_id: str) -> list[dict[str, Any]]:
        now = _now()
        out: list[dict[str, Any]] = []
        for it in self._items:
            if it.get("session_id") != session_id:
                continue
            status = it.get("status")
            if status in ("queued", "claimed", "interject_pending"):
                out.append(it)
                continue
            if status == "interject_received":
                received_at = float(it.get("received_at") or 0)
                if received_at and now - received_at <= INTERJECT_RECEIPT_VISIBLE_S:
                    out.append(it)
        return out

    @staticmethod
    def _public(it: dict[str, Any]) -> dict[str, Any]:
        """对外视图：剥离内部 _seq；附 Phase3 G1 分级回执派生字段.

        grade 优先级（机械判据，不做语义判断）：
        denied > requeued > applied > continued_before_final > received >
        accepted(=interject_pending 受理≠生效) > queued > cancelled/completed/failed。
        """
        view = {k: v for k, v in it.items() if not k.startswith("_")}
        status = str(view.get("status") or "")
        if status == "interject_denied":
            grade, reason = "denied", str(view.get("deny_reason") or "")
        elif status == "queued" and view.get("requeued_from"):
            grade, reason = "requeued", str(view.get("requeued_from"))
        elif view.get("applied_at"):
            grade, reason = "applied", str(view.get("applied_detail") or "")
        elif view.get("cbf_at"):
            grade, reason = "continued_before_final", str(view.get("cbf_detail") or "")
        elif status == "interject_received":
            grade, reason = "received", ""
        elif status == "interject_pending":
            grade, reason = "accepted", "受理≠生效：已进入 live run 信箱，等待轮边界"
        else:
            grade, reason = status or "unknown", ""
        view["grade"] = grade
        view["grade_reason"] = reason
        return view

    # ------------------------------------------------------------------ 公开 API

    def enqueue(
        self,
        session_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
        model: str | None = None,
        model_change: bool = False,
        reasoning_effort: str | None = None,
        reasoning_mode: str = "auto",
        attachment_facts: list[dict[str, Any]] | None = None,
        origin: str = "",
        origin_operation_id: str = "",
    ) -> dict[str, Any]:
        """入队：冻结本条事实并落盘；返回完整条目（含 queue_id）.

        origin/origin_operation_id（SPEC-20260923-queue-recovery）：机械来源
        标记（如 barrier_window + 屏障操作号），供恢复重排等下游按事实筛选；
        缺省为空，旧语义不变。
        """
        now = _now()
        with self._exclusive_locked():
            return self._enqueue_locked(session_id, message, attachments, model,
                                        model_change, reasoning_effort, reasoning_mode,
                                        attachment_facts, origin, origin_operation_id, now)

    def _enqueue_locked(
        self,
        session_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None,
        model: str | None,
        model_change: bool,
        reasoning_effort: str | None,
        reasoning_mode: str,
        attachment_facts: list[dict[str, Any]] | None,
        origin: str,
        origin_operation_id: str,
        now: float,
    ) -> dict[str, Any]:
        """enqueue 写体（调用方必须已持有 _exclusive_locked；不可重入——
        SA-LIGHT-COORDINATOR-P0-LIVE-WIRING：enqueue_once 复用本写体避免
        在锁内二次获取 threading.Lock 造成死锁）。"""
        self._seq += 1
        item = {
            "queue_id": f"q_{uuid.uuid4().hex[:12]}",
            "_seq": self._seq,
            "session_id": session_id,
            "message": message,
            "attachments": list(attachments or []),
            "attachment_facts": list(attachment_facts or []),
            "model": model,
            "model_change": bool(model_change),
            "reasoning_effort": reasoning_effort,
            "reasoning_mode": reasoning_mode,
            "created_at": now,
            "status": "queued",
        }
        if origin:
            item["origin"] = str(origin)
        if origin_operation_id:
            item["origin_operation_id"] = str(origin_operation_id)
        # SA-SCOPE-HOTFIX-20261125：动态盖章——每次入队实时取当前
        # (scope, epoch)（provider 模式），单例跨 workspace 切换不再
        # 错章；无 provider 退化为构造冻结值（遗留兼容）。epoch 仅记账
        # （审计/追溯），不作领取阻断——同 owner 返回按新执行快照重验。
        _stamp_scope, _stamp_epoch = self._current_scope_epoch()
        if _stamp_scope:
            item["workspace_scope"] = _stamp_scope
        if _stamp_epoch is not None:
            item["workspace_epoch"] = _stamp_epoch
        self._items.append(item)
        self._save()
        return self._public(item)

    def enqueue_once(
        self,
        session_id: str,
        message: str,
        *,
        origin: str = "",
        origin_operation_id: str = "",
    ) -> dict[str, Any]:
        """幂等入队（SA-LIGHT-COORDINATOR-P0-LIVE-WIRING）：同键查重+入队在
        同一 _exclusive_locked 临界区（flock+fresh reload 原子事务）.

        键 = (session_id, origin, origin_operation_id) 的活跃条目：
        - 无命中 → 正常入队（返回 {"item": …, "duplicate": False, "conflict": False}）；
        - 命中且 message 相同 → duplicate=True（不重复入队，返回既有条目）；
        - 命中但 message 不同 → conflict=True（拒绝覆盖，返回既有条目供对账）。
        查重与写入共享队列全局互斥——多实例/多进程/并发线程同键恰一条目，
        不会因 snapshot 读取与 enqueue 写入之间的窗口产生双投。
        """
        with self._exclusive_locked():
            self._reap_stale_claims_locked(_now())
            for it in self._items:
                if (
                    it.get("session_id") == session_id
                    and it.get("origin") == (origin or None)
                    and it.get("origin_operation_id") == (origin_operation_id or None)
                    and it.get("status")
                    in ("queued", "claimed", "interject_pending")
                ):
                    existing = self._public(it)
                    if str(it.get("message") or "") == str(message):
                        return {
                            "item": existing,
                            "duplicate": True,
                            "conflict": False,
                        }
                    return {
                        "item": existing,
                        "duplicate": False,
                        "conflict": True,
                    }
            item = self._enqueue_locked(
                session_id,
                message,
                None,
                None,
                False,
                None,
                "auto",
                None,
                origin,
                origin_operation_id,
                _now(),
            )
            return {"item": item, "duplicate": False, "conflict": False}

    def list_active(self, session_id: str) -> list[dict[str, Any]]:
        """会话的活跃队列（queued+claimed，FIFO 序）；顺带触发 reaper."""
        with self._exclusive_locked():
            self._reap_stale_claims_locked(_now())
            return [self._public(it) for it in self._active_items_locked(session_id)]

    def snapshot_items(self) -> list[dict[str, Any]]:
        """全量快照（公共视图，含终态；恢复扫描等下游用，不触发 reaper）.

        SA-LIGHT-COORDINATOR-P0-LIVE-WIRING：改走 _exclusive_locked（flock+
        fresh reload）——旧实现仅实例内存锁，跨实例/跨进程场景读到的是构造
        时刻的陈旧内存视图（不重载），共享 data_dir 下派工查重会漏掉他实例
        刚写入的条目。现与写路径同一全局互斥+磁盘权威起点，快照即全局一致。
        """
        with self._exclusive_locked():
            return [self._public(it) for it in self._items]

    def cancel(self, session_id: str, queue_id: str) -> bool:
        """取消一条排队项（queued→cancelled；claimed 不可取消：已进入发送流程）."""
        return self.cancel_with_item(session_id, queue_id) is not None

    def cancel_with_item(
        self, session_id: str, queue_id: str, *, cancelled_by: str = "system"
    ) -> dict[str, Any] | None:
        """Atomically cancel one still-queued item and return its frozen facts.

        cancelled_by（SPEC-20260923-queue-recovery）：机械取消方标记——
        用户主动取消（端点传 "user"）与系统路径取消可区分，恢复重排只认后者。
        """
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "queued":
                        return None
                    it["status"] = "cancelled"
                    it["terminal_at"] = _now()
                    it["cancelled_by"] = str(cancelled_by or "system")
                    self._save()
                    return self._public(it)
            return None

    def claim_interject(
        self, session_id: str, queue_id: str, *, run_generation: str = ""
    ) -> dict[str, Any] | None:
        """queued→interject_pending for an exact live-run handoff.

        run_generation 记录认领时的 live 代次，供 reap_orphan_interjects
        判孤儿（与 queue-interject 端点 CAS 判据同构）；缺省不记录（旧调用
        语义不变）。
        """
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "queued":
                        return None
                    it["status"] = "interject_pending"
                    it["interject_requested_at"] = _now()
                    if run_generation:
                        it["interject_run_generation"] = str(run_generation)
                    self._save()
                    return self._public(it)
            return None

    def release_interject(
        self,
        session_id: str,
        queue_id: str,
        *,
        reason: str = "interject_handoff_rejected",
    ) -> bool:
        """Rollback a mailbox handoff that never reached a live run."""
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "interject_pending":
                        return False
                    it["status"] = "queued"
                    it["requeued_at"] = _now()
                    it["requeued_from"] = reason
                    self._save()
                    return True
            return False

    def reap_orphan_interjects(
        self, runs_alive: Callable[[str], str | None]
    ) -> list[str]:
        """Requeue interject_pending items whose live run no longer exists.

        enqueue_interjection 返回 True 后 run 若在轮边界消费 mailbox 前终止，
        该项将停在 interject_pending；此前只有进程重启的 _load() 会恢复。本
        回收以 runs_alive 探测的代次事实为准：无 live run，或代次已换 →
        回滚 queued（audit 标记 interject_run_ended）。与 _load() 同一取舍：
        宁可承受 ack 失败窗口下的重复投递，也不让用户消息静默滞留（消息必达
        优先，queue_recovery 机械边界同构）。
        """
        requeued: list[str] = []
        for it in self.snapshot_items():
            if it.get("status") != "interject_pending":
                continue
            sid = str(it.get("session_id") or "")
            claimed_gen = str(it.get("interject_run_generation") or "")
            alive = runs_alive(sid)
            if alive is not None and (claimed_gen == "" or alive == claimed_gen):
                continue  # run 仍在且代次吻合：交给轮边界消费
            if self.release_interject(sid, str(it.get("queue_id") or ""), reason="interject_run_ended"):
                requeued.append(str(it.get("queue_id") or ""))
        return requeued

    def mark_interject_received(
        self,
        session_id: str,
        queue_id: str,
        *,
        consumed_via: str = "",
        interrupt_receipt: bool = False,
    ) -> bool:
        """Mark the exact point where the engine worker consumed the human steer.

        Phase4 M3 四桶机械归属（§7）：consumed_via∈{round_start, final_gate,
        gap_harvest}（engine 消费点戳）+ interrupt_receipt（本轮回执含
        interrupted_for_interjection）→ 分桶由 aggregate 派生，不在标记时判断
        （戳记只记事实，不解释）。
        """
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "interject_pending":
                        return False
                    it["status"] = "interject_received"
                    it["received_at"] = _now()
                    if consumed_via:
                        it["consumed_via"] = consumed_via
                    if interrupt_receipt:
                        it["interrupt_receipt"] = True
                    it["terminal_at"] = it["received_at"]
                    self._save()
                    return True
            return False

    def mark_interject_denied(
        self, session_id: str, queue_id: str, reason: str = "ingress_denied"
    ) -> bool:
        """G1 denied 终态：ingress 守卫拒绝（此前被拒项静默滞留 pending 后被
        reaper 误标为 interject_run_ended 回滚，与孤儿无法区分）.

        仅 interject_pending 可达（与 mark_interject_received 同一 CAS 形态）；
        终态 interject_denied + deny_reason，不回滚排队（守卫拒绝=不可投递）。
        """
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "interject_pending":
                        return False
                    it["status"] = "interject_denied"
                    it["deny_reason"] = reason
                    it["denied_at"] = _now()
                    it["terminal_at"] = it["denied_at"]
                    self._save()
                    return True
            return False

    def record_interject_applied(
        self, session_id: str, queue_id: str, detail: str = ""
    ) -> bool:
        """G1 applied 事实：包含该消息的模型决策产生了首个动作（工具派发）或
        因插话改变了终答。机械判据（Phase3 §7.1），非状态迁移——在
        interject_received 终态上追加 applied_at/applied_detail（幂等：首个
        事实生效，后续不覆盖）。"""
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "interject_received" or it.get("applied_at"):
                        return False
                    it["applied_at"] = _now()
                    it["applied_detail"] = detail
                    self._save()
                    return True
            return False

    def record_interject_cbf(self, session_id: str, queue_id: str, detail: str = "") -> bool:
        """G1 continued_before_final 事实：终答结算边界拦截到的插话续跑."""
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "interject_received" or it.get("cbf_at"):
                        return False
                    it["cbf_at"] = _now()
                    it["cbf_detail"] = detail
                    self._save()
                    return True
            return False

    @staticmethod
    def _same_workspace_scope(a: str, b: str) -> bool:
        """workspace_scope 比较统一 realpath 归一（registry path 与 engine
        workspace_root 可能存在 symlink/尾斜杠差异，字面量比较会误判错投）。"""
        try:
            return os.path.realpath(str(a)) == os.path.realpath(str(b))
        except OSError:
            return str(a) == str(b)

    def _hold_locked(self, it: dict[str, Any], reason: str) -> None:
        """队首 HOLD 留队：写可查询原因（幂等——同因不重复落盘）。条目保持
        queued 原样，快照端点经 hold_reason 查询阻断事实。"""
        if it.get("hold_reason") != reason:
            it["hold_reason"] = reason
            self._save()

    def dispatch_claim(
        self,
        session_id: str,
        claimed_by: str = "web",
        *,
        expected_workspace_scope: str | None = None,
    ) -> dict[str, Any] | None:
        """原子领取会话队首 queued 项（严格 FIFO）：标记 claimed；无可派发项返回 None.

        expected_workspace_scope（M0 workspace 绑定，P1-1/P1-2/P1-3 收口）：
        非空时只对会话队首（最早 queued 项）做 scope 裁决——
        - 队首绑定其他工作区 → 本轮整段不领取（队首阻断，绝不越过队首取
          后续项；P1-3：continue 越过队首会破坏会话内 FIFO，两个领取方
          可各领一条造成乱序投递）。条目原样留队（不删不改不落盘：归属
          经既有 workspace_scope 字段即可查询；落盘会引入 stale 实例覆盖
          他实例 claimed 事实的风险）；
        - 队首无 workspace_scope（升级前存量）→ 仅当 legacy_scope_resolver
          机械证明归属本工作区时可领取（领取时回填盖章防重复解析漂移）；
          未知/歧义/他区 → HOLD 留队并写 hold_reason 供快照端点查询
          （P1-2 fail-closed：共享 data_dir 下无绑定条目归属 UNKNOWN，
          不能自动分配；该原因属运行时证明事实，不落盘不可查）；
        - 队首匹配或经证明归属 → 领取，清除 hold_reason。
        队首非 queued（claimed 等在途）同样本轮不领取（FIFO 语义：队首
        未结算时不越过）。缺省 None=不过滤（遗留调用行为不变）。
        """
        with self._exclusive_locked():
            self._reap_stale_claims_locked(_now())
            active = sorted(self._active_items_locked(session_id), key=lambda x: (x.get("created_at", 0), int(x.get("_seq", 0))))
            if not active:
                return None
            head = active[0]
            if head.get("status") != "queued":
                # 队首在途（claimed/interject_pending/interject_received 展示
                # 窗口）：未结算不越过——本轮整段不派发（浏览器与后台同约束），
                # 队首终态/release 后下轮自然轮到后续条目。
                return None
            if expected_workspace_scope:
                item_scope = str(head.get("workspace_scope") or "")
                if item_scope:
                    if not self._same_workspace_scope(item_scope, expected_workspace_scope):
                        return None  # 队首绑定他区：原样留队（不落盘），不越过
                else:
                    owner_scope: str | None = None
                    resolver = self._legacy_scope_resolver
                    if resolver is not None:
                        try:
                            owner_scope = resolver(session_id) or None
                        except Exception:  # noqa: BLE001 — 未知/多归属/删除等
                            # SessionStore 证明失败：fail-closed HOLD，不自动分配
                            logger.exception(
                                "legacy scope resolver failed: sid=%s", session_id[:8]
                            )
                            owner_scope = None
                    if owner_scope is None:
                        self._hold_locked(head, "queue_hold_legacy_owner_unresolved")
                        return None
                    if not self._same_workspace_scope(owner_scope, expected_workspace_scope):
                        self._hold_locked(head, "queue_hold_legacy_owner_other_workspace")
                        return None
                    head["workspace_scope"] = expected_workspace_scope
            head["status"] = "claimed"
            head["claimed_at"] = _now()
            head["claimed_by"] = claimed_by
            head.pop("hold_reason", None)
            self._clear_recovery_fields(head)
            self._save()
            return self._public(head)

    def claimed_item(self, session_id: str, queue_id: str) -> dict[str, Any] | None:
        """Return one currently claimed frozen handoff fact without mutating it."""
        with self._exclusive_locked():
            self._reap_stale_claims_locked(_now())
            for it in self._items:
                if (
                    it.get("queue_id") == queue_id
                    and it.get("session_id") == session_id
                    and it.get("status") == "claimed"
                ):
                    return self._public(it)
            return None

    def release(self, session_id: str, queue_id: str) -> bool:
        """领取方未能发起正式 run（如 session_busy 竞态）→ 回滚 queued 保持 FIFO."""
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "claimed":
                        return False
                    it["status"] = "queued"
                    it.pop("claimed_at", None)
                    it.pop("claimed_by", None)
                    self._clear_recovery_fields(it)
                    self._save()
                    return True
            return False

    def interject_pressure(self, session_id: str) -> dict[str, Any]:
        """R2③（antidrift_impl 批1）只读统计：等待投递集计数与最早入队时间.

        DC-1 术语映射口径：{queued, interject_pending} 即 HEAD 状态机中
        "已入队、尚未进入模型上下文"的全部机械状态；interject_received 为
        投递完成终态，不构成等待压力。不改任何既有状态转移。
        """
        with self._lock:
            count = 0
            oldest: float | None = None
            for it in self._items:
                if it.get("session_id") != session_id:
                    continue
                if it.get("status") not in ("queued", "interject_pending"):
                    continue
                count += 1
                created = it.get("created_at")
                if isinstance(created, (int, float)) and (
                    oldest is None or float(created) < oldest
                ):
                    oldest = float(created)
            return {"count": count, "oldest_enqueued_at": oldest}

    def mark_terminal(
        self, session_id: str, queue_id: str, status: str, run_error: str | None = None
    ) -> bool:
        """run 终态回写：claimed → completed | failed."""
        if status not in ("completed", "failed"):
            raise ValueError(f"unsupported terminal status: {status}")
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "claimed":
                        return False
                    it["status"] = status
                    it["terminal_at"] = _now()
                    self._clear_recovery_fields(it)
                    if run_error:
                        it["run_error"] = run_error
                    self._save()
                    return True
            return False

    def mark_resumed_once(self, queue_id: str, job_id: str) -> dict[str, Any]:
        """一次性原子接续标记（SA-PR145-FINAL-ATOMIC-RESUME）.

        在 _exclusive_locked（flock+fresh reload 全局互斥）内核验并标记
        ``resumed_job_id``——接续幂等权威面在队列条目自身（cards 审计附件
        不可作权威、best-effort 写非原子）：
        - 首次标记并成功落盘 → ``{"marked": True}``（调用方此后才允许 poke）；
        - 已标记同 job → ``duplicate=True``（不重放唤醒）；
        - 已标记异 job → ``conflict=True``（一卡一 Job）；
        - 持久化失败 → 内存标记回滚 + ``persist_uncertain=True``（fail-closed：
          未确认落盘不触发唤醒；磁盘若实际已写，fresh reload 后重入走
          duplicate 分支同样不重放——双保险幂等）；
        - queue_id 不存在 → ``missing=True``。
        """
        with self._exclusive_locked():
            for it in self._items:
                if it.get("queue_id") != queue_id:
                    continue
                resumed = str(it.get("resumed_job_id") or "")
                if resumed:
                    return {
                        "marked": False,
                        "duplicate": True,
                        "conflict": resumed != str(job_id),
                        "resumed_job_id": resumed,
                    }
                it["resumed_job_id"] = str(job_id)
                try:
                    self._save()
                except QueuePersistError as exc:
                    it.pop("resumed_job_id", None)
                    return {
                        "marked": False,
                        "duplicate": False,
                        "persist_uncertain": True,
                        "error": str(exc),
                    }
                return {"marked": True, "duplicate": False}
            return {"marked": False, "duplicate": False, "missing": True}

    def compact(self, keep_n: int = TERMINAL_HISTORY_KEEP_N) -> None:
        """终态条目滚动清理（保最近 keep_n 条终态历史）."""
        with self._exclusive_locked():
            if len(self._items) <= keep_n:
                return
            actives = [
                it
                for it in self._items
                if it.get("status") in ("queued", "claimed", "interject_pending")
            ]
            terminals = [it for it in self._items if it not in actives]
            self._items = actives + terminals[-keep_n:]
            self._save()

    # ── Phase3 M2（G2）：插话三口径时延聚合（只读，不产生写副作用）──

    @staticmethod
    def _pct(sorted_vals: list[float], p: float) -> float | None:
        """最近邻序法百分位（机械可复算；n=0 → None，不造数）."""
        if not sorted_vals:
            return None
        k = max(1, min(len(sorted_vals), int((p * len(sorted_vals) + 0.999999) // 1)))
        return sorted_vals[k - 1]

    def _interject_metric_rows(
        self, session_id: str | None
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """构建插话终态样本行（单一实现；session_id=None 即跨 session 全量）.

        行结构与分桶口径被单 session / 全局两个视图共用（单一事实源）；
        返回 (rows, sessions)——sessions 为样本来源 session_id 集合（全局视图
        sessions_in_window 的事实源；单 session 视图忽略之）。
        """
        rows: list[dict[str, Any]] = []
        sessions: set[str] = set()
        with self._lock:
            items = [dict(it) for it in self._items]
        for it in items:
            if session_id is not None and it.get("session_id") != session_id:
                continue
            if it.get("status") != "interject_received":
                continue
            c = it.get("created_at")
            a = it.get("interject_requested_at")
            r = it.get("received_at")
            if not (c and a and r):
                continue
            row: dict[str, Any] = {
                "queue_id": it.get("queue_id"),
                "grade": self._public(it).get("grade"),
                "t_ack_ms": round((a - c) * 1000, 1),
                "t_persist_ms": round((r - a) * 1000, 1),
                "t_effect_ms": round((r - c) * 1000, 1),
                "t_applied_ms": (
                    round((it["applied_at"] - c) * 1000, 1) if it.get("applied_at") else None
                ),
            }
            # Phase4 M3 四桶机械归属（§7）：interruptible=本轮含打断回执；
            # 其余按消费点：final_gate→llm_stream；gap_harvest→idle；
            # round_start/无戳记（老数据）→natural_boundary（轮转消费缺省）。
            # Phase5 M2（设计 §2.2.3）：llm_stream_interrupt（流内插话打断收割）
            # 判序最前——先于 interrupt_receipt，防跨轮残值 True 劫持新桶样本
            # （该消费点 interrupt_receipt 恒 False，双保险）。
            # 可观测性 M1a（2026-10-14，G1 修复）：sync_window_poll（Phase6 M1
            # 同步窗口轮询收割，engine L2080/L2094 写入、receipt 恒 False）独立
            # 成桶——精确值 consumed_via 优先于布尔标记 interrupt_receipt，与
            # 上面同理；此前落 else 误归 natural_boundary，两桶同时失真
            # （docs/ANALYSIS-20261014-observability-m0-findings.md §3-G1）。
            if it.get("consumed_via") == "llm_stream_interrupt":
                bucket = "llm_stream_interrupt"
            elif it.get("consumed_via") == "sync_window_poll":
                bucket = "sync_window_poll"
            elif it.get("interrupt_receipt"):
                bucket = "interruptible"
            elif it.get("consumed_via") == "final_gate":
                bucket = "llm_stream"
            elif it.get("consumed_via") == "gap_harvest":
                bucket = "idle"
            else:
                bucket = "natural_boundary"
            row["bucket"] = bucket
            rows.append(row)
            sid = str(it.get("session_id") or "")
            if sid:
                sessions.add(sid)
        return rows, sessions

    def _interject_percentile_block(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in ("t_ack_ms", "t_persist_ms", "t_effect_ms", "t_applied_ms"):
            vals = sorted(row[key] for row in rows if row.get(key) is not None)
            out[f"p50_{key}"] = self._pct(vals, 0.50)
            out[f"p95_{key}"] = self._pct(vals, 0.95)
        return out

    # 可观测性 M1c 修订（2026-10-14，§9 结构性零落地）：两桶 n=0 的成因是
    # 部署拓扑使然而非采样不足——后端为口径单一来源，前端仅渲染。
    # - sync_window_poll：web 页面自动化通道已剥离退役（2026-10-14），
    #   本部署不存在此消费路径；
    # - llm_stream：当前拓扑（流式 provider + Phase5 流内检查点默认开）下
    #   final_gate 收割窗被检查点先占（实测竞速窗上界 <350ms），无样本为
    #   健康形态。该属性是拓扑推断而非物理定律：若检查点关闸/切非流式
    #   provider，final_gate 会重新收割样本（n>0 时前端照常显示统计，
    #   标注自然不出现）。
    STRUCTURAL_ZERO_BUCKETS: ClassVar[dict[str, str]] = {
        "sync_window_poll": (
            "同步窗口轮询通道已随 web 页面自动化通道退役（2026-10-14 剥离）；"
            "当前部署不存在此消费路径，无样本为预期形态"
        ),
        "llm_stream": (
            "当前拓扑（流式 provider + Phase5 流内检查点默认开）下 final_gate "
            "保守等待的竞速窗被检查点先占收割（实测上界 <350ms）；无样本为"
            "健康形态，非采样不足"
        ),
    }

    def _interject_bucket_block(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        # Phase4 M3 分桶汇总（§7 验收面）：每桶 n/p50/p95，样本不足 5 标注
        # insufficient_sample（诚实口径，不冒充达标）。
        buckets_out: dict[str, Any] = {}
        # Phase5 M2：汇总桶序追加 llm_stream_interrupt（打断收割路径，独立统计，
        # 与保守等待路径 llm_stream 分开，不互相冒充；合并视图另列总口径）。
        # 可观测性 M1a：追加 sync_window_poll（M0 评审 B7 六桶全列口径）。
        # M1c 修订：每桶追加 structural_zero/zero_reason（§9 结构性零口径）。
        for b in (
            "interruptible",
            "natural_boundary",
            "llm_stream",
            "llm_stream_interrupt",
            "sync_window_poll",
            "idle",
        ):
            effs = sorted(
                row["t_effect_ms"]
                for row in rows
                if row.get("bucket") == b and row.get("t_effect_ms") is not None
            )
            buckets_out[b] = {
                "n": len(effs),
                "p50_t_effect_ms": self._pct(effs, 0.50),
                "p95_t_effect_ms": self._pct(effs, 0.95),
                "insufficient_sample": len(effs) < 5,
                "structural_zero": b in self.STRUCTURAL_ZERO_BUCKETS,
                "zero_reason": self.STRUCTURAL_ZERO_BUCKETS.get(b),
            }
        return buckets_out

    def aggregate_interject_metrics(self, session_id: str) -> dict[str, Any]:
        """三口径时延（ms）+ P50/P95（Phase3 §7.1，端侧零改动）.

        口径（全部由已有时间戳机械推导，无墙钟注入）：
        - t_ack_ms    = interject_requested_at - created_at（入队→HTTP 受理）
        - t_persist_ms= received_at - interject_requested_at（受理→进入会话历史，
                        含轮边界等待与 session 写盘；即「回执≠生效」的差值本体）
        - t_effect_ms = received_at - created_at（入队→生效端到端）
        - t_applied_ms= applied_at - created_at（入队→首个动作；未 applied 无值）
        只统计 interject_received* 终态项；denied/requeued 不混入（口径含混即失真）。
        """
        rows, _sessions = self._interject_metric_rows(session_id)
        out: dict[str, Any] = {
            "session_id": session_id,
            "n": len(rows),
            "items": rows,
        }
        out.update(self._interject_percentile_block(rows))
        out["buckets"] = self._interject_bucket_block(rows)
        return out

    def aggregate_interject_metrics_global(self) -> dict[str, Any]:
        """可观测性 M1b（B1/B5）：跨 session 合并的全局聚合（只读，零写副作用）.

        - 桶口径/三口径/百分位与单 session 视图同一实现（_interject_metric_rows
          单一事实源）；不含逐条 items——合并视图不做 per-session 明细（B1 YAGNI，
          明细走既有单 session 端点）。
        - window_terminal_cap=TERMINAL_HISTORY_KEEP_N：compact 终态滚动上限即
          本视图天然数据窗口（最近 N 条终态，非全历史）；消费端须标注防误读（B5）。
        - n=0 → p50/p95=null、sessions_in_window=0，不造数（同单 session 口径）。
        """
        rows, sessions = self._interject_metric_rows(None)
        out: dict[str, Any] = {
            "scope": "global",
            "session_id": None,
            "n": len(rows),
            "sessions_in_window": len(sessions),
            "window_terminal_cap": TERMINAL_HISTORY_KEEP_N,
        }
        out.update(self._interject_percentile_block(rows))
        out["buckets"] = self._interject_bucket_block(rows)
        return out
