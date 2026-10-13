"""Phase3 M3（G3）：会话副作用登记与停止四态数据面.

事实基线（M0 报告审查修订版 §3-5 / §4）：
- 停止回收已有两层——in-flight `terminate_session` 与会话级 cancel hook
  （factory.py:731 注册 JobRegistry.cancel_session）。M3 不新增回收机制。
- 缺的是「可枚举」：run 停止时，哪些外部副作用已被停止、哪些无法自动撤销
  （external_unknown），无独立查询面。

本模块只做登记与状态，不做撤销动作（撤销仍走既有机制）：
- SideEffectRegistry：进程单例（JobRegistry.instance 同型），按 data_dir 持久化
  side_effects.json（flock + 重读合并 + tempfile + os.replace，终审 P1-4 对齐
  ScheduleStore/human_turn_queue 的跨进程纪律；锁文件 <path>.lock）。
- 工具 opt-in：类属性 side_effect_kind（与 terminate_session 同构的最小侵入）；
  登记失败 fail-open 不阻断工具（观测面）。revocable=True 表示既有停止机制可
  回收（bg job/subagent）；False 表示不可自动撤销（浏览器 mutation/外发/写文件）。
- StopRecord：requested/dispatched_stopped/local_terminated 时间戳 +
  stop_run_generation（run 绑定，终审 P1-3：新 run 启动清空旧停止记录，
  消除陈旧记录被误读为当前 run 状态）。
- 四态查询（组合而非状态机迁移）：查询时对 job 类 revocable 项做惰性终态
  结算（P1-3：自然完成的 job 不再永远挂 active）。
- 空清单显式「无已知外部副作用」；确认只走人工（无 TTL，D5）。

D6 红线：登记项 detail 不含消息/页面正文（只含目标标识：job_id/url/name/命令头）。
"""
from __future__ import annotations

import contextlib
import fcntl
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

_FILENAME = "side_effects.json"
_VERSION = 1
# 事实源对齐（终审 P0-2 同源）：job_registry 本地终态 + external_execution durable
_JOB_TERMINAL_STATES = {"completed", "failed", "killed", "orphaned"}


def _now() -> float:
    return time.time()


class SideEffectError(RuntimeError):
    """持久化失败（分级语义同 QueuePersistError；停止路径 fail-open 使用）."""

    def __init__(self, stage: str, detail: str = "") -> None:
        super().__init__(f"side effect store persist {stage}: {detail}")
        self.stage = stage


class SideEffectRegistry:
    """进程级单例：会话副作用登记 + 停止记录（只登记，不撤销）."""

    _instance: SideEffectRegistry | None = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> SideEffectRegistry:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, data_dir: str | None = None) -> None:
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._seq = 0
        self._stops: dict[str, dict[str, Any]] = {}
        # 停止记录删除墓碑：内存 pop 后磁盘合并时不再「复活」（clear 语义
        # 需要跨实例传播；items 无删除路径，不需要墓碑）。
        self._removed_stops: set[str] = set()
        self._path: Path | None = None
        if data_dir:
            self.configure(data_dir)

    def configure(self, data_dir: str) -> None:
        """绑定存储目录（factory 装配时调用；测试可重复 configure 到 tmp 目录）."""
        with self._lock:
            self._path = Path(data_dir).expanduser() / _FILENAME
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    # ── 持久化（flock + 重读合并 + tempfile + replace，异常分级）──────────
    # 终审 P1-4：旧版「tempfile+replace、不持锁、不重读」在多进程并发写时
    # 后写者整文件覆盖——丢对方登记。现与 ScheduleStore/human_turn_queue 同款：
    # 独立锁文件互斥；临界区内重读磁盘做 id 级合并（后写内存态胜，磁盘独有
    # 条目保留）；seq 取两侧最大+1。

    def _merge_disk_locked(self) -> None:
        """已持锁路径内：重读磁盘并合并（内存新态胜；磁盘独有条目保回内存）."""
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 磁盘侧损坏按无磁盘态处理（内存态胜）
            logger.warning("side_effects 磁盘文件损坏，按内存态重写", exc_info=True)
            return
        disk_items = list(data.get("items", []))
        disk_stops = dict(data.get("stops", {}))
        disk_seq = int(data.get("seq", 0) or 0)
        # 墓碑并集传播（另一实例的 clear 也能被本实例看见并尊重）
        self._removed_stops |= set(data.get("removed_stops", []))
        mine_ids = {it.get("id") for it in self._items}
        self._items = list(self._items) + [
            it for it in disk_items if it.get("id") not in mine_ids
        ]
        for sid, rec in disk_stops.items():
            if sid in self._removed_stops:
                continue  # 已被 clear：磁盘残留不复活
            mine = self._stops.get(sid)
            if not mine or float(rec.get("requested_at", 0) or 0) > float(
                mine.get("requested_at", 0) or 0
            ):
                self._stops[sid] = rec
        self._seq = max(self._seq, disk_seq)

    def _save(self) -> None:
        if self._path is None:
            return  # 未 configure（如裸单测）：内存模式，不持久化
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        tmp = None
        try:
            with open(lock_path, "a+", encoding="utf-8") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    self._merge_disk_locked()
                    self._seq += 1
                    payload = {
                        "version": _VERSION,
                        "seq": self._seq,
                        "items": self._items,
                        "stops": self._stops,
                        "removed_stops": sorted(self._removed_stops),
                    }
                    fd, tmp = tempfile.mkstemp(
                        dir=self._path.parent, prefix=_FILENAME, suffix=".tmp"
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    os.replace(tmp, self._path)
                    tmp = None
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except SideEffectError:
            raise
        except BaseException as exc:  # noqa: BLE001 — 分级持久化异常（含锁文件 IO）
            stage = (
                "commit_outcome_uncertain"
                if tmp is None and os.path.exists(self._path)
                else "definitely_not_committed"
            )
            raise SideEffectError(stage, str(exc)) from exc
        finally:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            self._items, self._seq, self._stops = [], 0, {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = list(data.get("items", []))
            self._seq = int(data.get("seq", len(self._items)))
            self._stops = dict(data.get("stops", {}))
            self._removed_stops = set(data.get("removed_stops", []))
        except Exception:  # noqa: BLE001 — 损坏文件按空表起步（观测数据，非 SoT）
            self._items, self._seq, self._stops = [], 0, {}
            self._removed_stops = set()

    def _persist_best_effort(self, where: str) -> None:
        try:
            self._save()
        except SideEffectError as exc:  # 观测面 fail-open，但必须留痕（终审 P2-3）
            logger.warning("side_effects 持久化失败（fail-open, at=%s）: %s", where, exc)

    # ── 副作用登记（登记失败 fail-open 不阻断工具）─────────────────────

    def register(
        self,
        session_id: str,
        tool: str,
        target: str,
        kind: str,
        *,
        revocable: bool,
        detail: str = "",
    ) -> str | None:
        """登记一次外部副作用. target=目标标识（job_id/url/文件路径/命令头，D6 安全）."""
        with self._lock:
            # P1-4 根因修正：实例本地 seq 跨实例/跨进程会撞 id（两个实例各自的
            # 第一条都叫 se-1，合并时互认对方是自己的旧条目）。id 加唯一片段，
            # seq 只作版本号不再当身份。
            self._seq += 1
            eff_id = f"se-{self._seq}-{uuid.uuid4().hex[:6]}"
            # Phase4 M2（§4.2 CK-B④，审查 P1-2）：登记戳当前 run_generation（来自
            # run_context；无上下文=空串）——打断判定的副作用面按代次过滤，防跨
            # run 陈旧未结算项静默阻断在途打断能力。纯增字段，旧数据无此键=空。
            try:
                from llm_loop.core.run_context import current_run_generation

                _reg_gen = current_run_generation.get()
            except Exception:  # noqa: BLE001 — 登记面不因观测戳失败
                _reg_gen = ""
            self._items.append(
                {
                    "id": eff_id,
                    "session_id": session_id,
                    "tool": tool,
                    "target": str(target)[:200],
                    "kind": kind,
                    "revocable": bool(revocable),
                    "detail": str(detail)[:200],
                    "run_generation": _reg_gen,
                    "created_at": _now(),
                    "settled_at": None,   # 自然完成/已被停止回收的时间
                    "confirmed_at": None,  # 人工确认（仅 external_unknown 用）
                    "confirmed_by": None,
                }
            )
            try:
                self._save()
            except SideEffectError as exc:
                logger.warning("side_effects 登记持久化失败（fail-open）: %s", exc)
                return None
            return eff_id

    def settle(self, eff_id: str, *, reason: str = "settled") -> bool:
        """副作用已结束（自然完成或被停止机制回收）."""
        with self._lock:
            for it in self._items:
                if it.get("id") == eff_id and not it.get("settled_at"):
                    it["settled_at"] = _now()
                    it["settle_reason"] = reason[:60]
                    self._persist_best_effort("settle")
                    return True
            return False

    def settle_session_stopped(self, session_id: str, reason: str = "stop_dispatched") -> int:
        """停止派发后：revocable 项视为已回收（由既有 hook 机制执行）."""
        n = 0
        with self._lock:
            for it in self._items:
                if (
                    it.get("session_id") == session_id
                    and it.get("revocable")
                    and not it.get("settled_at")
                ):
                    it["settled_at"] = _now()
                    it["settle_reason"] = reason[:60]
                    n += 1
            if n:
                self._persist_best_effort("settle_session_stopped")
        return n

    def _lazy_settle_jobs(self, session_id: str) -> int:
        """查询时惰性结算：job 类 revocable 项若已终态则置 settled（终审 P1-3：
        自然完成的 job 不该永远挂在 active 清单里）。只读 JobRegistry snapshot."""
        n = 0
        try:
            from llm_loop.tools.builtin.job_registry import JobRegistry

            jr = JobRegistry.instance()
        except Exception:  # noqa: BLE001 — 无 job 服务时跳过惰性结算
            return 0
        with self._lock:
            for it in self._items:
                if (
                    it.get("session_id") == session_id
                    and it.get("revocable")
                    and not it.get("settled_at")
                    and str(it.get("kind", "")) in ("process_bg", "dsh_bg")
                    and str(it.get("target", "")).startswith("job:")
                ):
                    job_id = str(it["target"]).split(":", 1)[1].split(" ", 1)[0]
                    snap = jr.snapshot(job_id) or {}
                    if str(snap.get("state", "")).lower() in _JOB_TERMINAL_STATES:
                        it["settled_at"] = _now()
                        it["settle_reason"] = "job_terminal"
                        n += 1
            if n:
                self._persist_best_effort("lazy_settle_jobs")
        return n

    def confirm_external(
        self, eff_id: str, confirmed_by: str, note: str = "", session_id: str = ""
    ) -> bool:
        """人工确认 external_unknown 已处置（无 TTL 自动确认；D5）.

        session_id 非空时校验归属（终审 P2-5：会话 A 不能确认会话 B 的副作用）。
        """
        with self._lock:
            for it in self._items:
                if it.get("id") == eff_id:
                    if session_id and it.get("session_id") != session_id:
                        return False
                    it["confirmed_at"] = _now()
                    it["confirmed_by"] = str(confirmed_by)[:60]
                    it["confirm_note"] = str(note)[:200]
                    self._persist_best_effort("confirm_external")
                    return True
            return False

    def clear_stops(self, session_id: str) -> None:
        """新 run 启动时清空该会话旧停止记录（终审 P1-3：停止记录绑定 run 生命周期）.

        记入墓碑：后续任何实例的磁盘合并不把该记录复活（clear 必须跨实例传播）。
        """
        with self._lock:
            if session_id in self._stops or session_id not in self._removed_stops:
                self._stops.pop(session_id, None)
                self._removed_stops.add(session_id)
                self._persist_best_effort("clear_stops")

    def snapshot(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(it) for it in self._items if it.get("session_id") == session_id]

    # ── 停止记录 ─────────────────────────────────────────────────────

    def record_stop_requested(
        self, session_id: str, reason: str = "", *, run_generation: str | None = None
    ) -> None:
        with self._lock:
            rec = self._stops.setdefault(session_id, {})
            rec["requested_at"] = _now()
            rec["reason"] = reason[:120]
            rec["stop_run_generation"] = str(run_generation) if run_generation else rec.get(
                "stop_run_generation", ""
            )
            self._removed_stops.discard(session_id)  # 新停止记录解除墓碑
            self._persist_best_effort("record_stop_requested")

    def record_stop_dispatched(self, session_id: str, stopped_count: int) -> None:
        with self._lock:
            rec = self._stops.setdefault(session_id, {})
            rec["dispatched_stopped_at"] = _now()
            rec["dispatched_stopped_count"] = int(stopped_count)
            self._persist_best_effort("record_stop_dispatched")

    def record_local_terminated(
        self, session_id: str, *, run_generation: str | None = None
    ) -> None:
        """run 本地终态时刻（runner done/error 出口写入；精确终止侧口径）.

        只标注「已存在的停止记录」：无停止请求（或新 run 已清空旧记录）时跳过
        ——否则被停 run 的晚到终态回调会重建孤儿记录，被下一轮误读（终审 P1-3
        回归实测）。run_generation 非空时还须与 stop_run_generation 一致。
        """
        with self._lock:
            rec = self._stops.get(session_id)
            if not rec or not rec.get("requested_at"):
                return
            if run_generation and rec.get("stop_run_generation") not in ("", run_generation):
                return
            rec["terminated_at"] = _now()
            self._persist_best_effort("record_local_terminated")

    def stop_record(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._stops.get(session_id, {}))

    def stop_state(
        self, session_id: str, *, run_alive: Callable[[], bool] | None = None
    ) -> dict[str, Any]:
        """四态组合查询（非状态机迁移；组合规则见 docs/phase3-m0-baseline.md §5）.

        - 空清单（无未决副作用）才声明 no_known_external_side_effects=True。
        - external_unknown 只含「不可撤销且未人工确认」项；确认只走 confirm。
        - 停止记录携带 stop_run_generation（审计用；新 run 启动会清空旧记录）。
        """
        self._lazy_settle_jobs(session_id)
        rec = self.stop_record(session_id)
        effects = self.snapshot(session_id)
        external_unknown = [
            {
                "id": it["id"],
                "tool": it["tool"],
                "target": it["target"],
                "kind": it["kind"],
                "created_at": it["created_at"],
                "confirmed_at": it.get("confirmed_at"),
                "confirm_note": it.get("confirm_note"),
                "manual_check_hint": (
                    "该类副作用不可自动撤销；请人工核验目标侧状态后在 confirm 端点登记"
                ),
            }
            for it in effects
            if not it.get("revocable") and not it.get("settled_at")
        ]
        # 未决副作用（含 revocable 仍活跃）：为空才说「无已知外部副作用」——
        # 一个在跑的后台 job 就足以让该声明为假（诚实优先于观感）。
        active_effects = [it for it in effects if not it.get("settled_at")]
        alive = bool(run_alive()) if run_alive else False
        return {
            "state": (
                "idle" if not rec else ("dispatched_stopped" if alive else "local_terminated")
            ),
            "run_alive": alive,
            "requested_at": rec.get("requested_at"),
            "stop_run_generation": rec.get("stop_run_generation", ""),
            "dispatched_stopped_at": rec.get("dispatched_stopped_at"),
            "dispatched_stopped_count": rec.get("dispatched_stopped_count", 0),
            "local_terminated_at": rec.get("terminated_at"),
            "external_unknown": external_unknown,
            "external_unknown_count": len(external_unknown),
            "external_all_confirmed": all(e["confirmed_at"] for e in external_unknown),
            "active_effects_count": len(active_effects),
            "no_known_external_side_effects": len(active_effects) == 0,
        }
