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

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

QUEUE_FILENAME = "human_turn_queue.json"
QUEUE_VERSION = 1
# claimed 悬挂回滚阈值：前端领取后应在数秒内发起正式 chat 请求；
# 60s 覆盖慢网络与短暂卡顿，同时避免崩溃标签长时间阻塞队列。
CLAIM_TIMEOUT_S = 60.0


def _now() -> float:
    return time.time()


class HumanTurnQueue:
    """会话级 human turn 队列（进程内单实例 + JSON 文件持久化）.

    线程安全：所有公开方法在 _lock 内完成"读改写"，落盘为原子写
    （tempfile + os.replace），多进程/多实例不保证跨进程互斥（8903 单进程契约）。
    """

    def __init__(
        self,
        data_dir: str | Path,
        claim_timeout_s: float = CLAIM_TIMEOUT_S,
        claim_state_probe: Callable[[str, str], str] | None = None,
    ) -> None:
        self._path = Path(data_dir) / QUEUE_FILENAME
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        self._seq = 0
        self._claim_timeout_s = claim_timeout_s
        self._claim_state_probe = claim_state_probe
        self._load()

    # ------------------------------------------------------------------ 持久化

    def _load(self) -> None:
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

    def _save(self) -> None:
        payload = {"version": QUEUE_VERSION, "items": self._items}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=QUEUE_FILENAME, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ 内部

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
        return [
            it
            for it in self._items
            if it.get("session_id") == session_id and it.get("status") in ("queued", "claimed")
        ]

    @staticmethod
    def _public(it: dict[str, Any]) -> dict[str, Any]:
        """对外视图：剥离内部 _seq."""
        return {k: v for k, v in it.items() if not k.startswith("_")}

    # ------------------------------------------------------------------ 公开 API

    def enqueue(
        self,
        session_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str = "auto",
        attachment_facts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """入队：冻结本条事实并落盘；返回完整条目（含 queue_id）."""
        now = _now()
        with self._lock:
            self._seq += 1
            item = {
                "queue_id": f"q_{uuid.uuid4().hex[:12]}",
                "_seq": self._seq,
                "session_id": session_id,
                "message": message,
                "attachments": list(attachments or []),
                "attachment_facts": list(attachment_facts or []),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "reasoning_mode": reasoning_mode,
                "created_at": now,
                "status": "queued",
            }
            self._items.append(item)
            self._save()
            return self._public(item)

    def list_active(self, session_id: str) -> list[dict[str, Any]]:
        """会话的活跃队列（queued+claimed，FIFO 序）；顺带触发 reaper."""
        with self._lock:
            self._reap_stale_claims_locked(_now())
            return [self._public(it) for it in self._active_items_locked(session_id)]

    def cancel(self, session_id: str, queue_id: str) -> bool:
        """取消一条排队项（queued→cancelled；claimed 不可取消：已进入发送流程）."""
        with self._lock:
            for it in self._items:
                if it.get("queue_id") == queue_id and it.get("session_id") == session_id:
                    if it.get("status") != "queued":
                        return False
                    it["status"] = "cancelled"
                    it["terminal_at"] = _now()
                    self._save()
                    return True
            return False

    def dispatch_claim(self, session_id: str, claimed_by: str = "web") -> dict[str, Any] | None:
        """原子领取队首 queued 项（FIFO）：标记 claimed；无可派发项返回 None."""
        with self._lock:
            self._reap_stale_claims_locked(_now())
            pending = sorted(self._active_items_locked(session_id), key=lambda x: (x.get("created_at", 0), int(x.get("_seq", 0))))
            for it in pending:
                if it.get("status") == "queued":
                    it["status"] = "claimed"
                    it["claimed_at"] = _now()
                    it["claimed_by"] = claimed_by
                    self._clear_recovery_fields(it)
                    self._save()
                    return self._public(it)
            return None

    def claimed_item(self, session_id: str, queue_id: str) -> dict[str, Any] | None:
        """Return one currently claimed frozen handoff fact without mutating it."""
        with self._lock:
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
        with self._lock:
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

    def mark_terminal(
        self, session_id: str, queue_id: str, status: str, run_error: str | None = None
    ) -> bool:
        """run 终态回写：claimed → completed | failed."""
        if status not in ("completed", "failed"):
            raise ValueError(f"unsupported terminal status: {status}")
        with self._lock:
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

    def compact(self, keep_n: int = 500) -> None:
        """终态条目滚动清理（保最近 keep_n 条终态历史）."""
        with self._lock:
            if len(self._items) <= keep_n:
                return
            actives = [it for it in self._items if it.get("status") in ("queued", "claimed")]
            terminals = [it for it in self._items if it not in actives]
            self._items = actives + terminals[-keep_n:]
            self._save()
