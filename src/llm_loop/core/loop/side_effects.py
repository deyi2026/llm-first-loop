"""Phase3 M3（G3）：会话副作用登记与停止四态数据面.

事实基线（M0 报告审查修订版 §3-5 / §4）：
- 停止回收已有两层——in-flight `terminate_session` 与会话级 cancel hook
  （factory.py:731 注册 JobRegistry.cancel_session）。M3 不新增回收机制。
- 缺的是「可枚举」：run 停止时，哪些外部副作用已被停止、哪些无法自动撤销
  （external_unknown），无独立查询面。

本模块只做登记与状态，不做撤销动作（撤销仍走既有机制）：
- SideEffectRegistry：进程单例（JobRegistry.instance 同型），按 data_dir 持久化
  side_effects.json（tempfile+os.replace，与 human_turn_queue 同纪律）。
- 工具 opt-in：类属性 side_effect_kind（与 terminate_session 同构的最小侵入）；
  registry.execute 派发时登记。revocable=True 表示既有停止机制可回收
  （bg job/subagent）；False 表示不可自动撤销（浏览器 mutation/外发消息/文件写）。
- StopRecord：requested/dispatched_stopped 时间戳（runner.cancel 写入）。
- 四态查询（组合而非状态机迁移，避免引入新的必达语义）：
  requested → dispatched_stopped → local_terminated(+external_unknown|confirmed)。
  禁 TTL 自动转 confirmed（D5）；空清单显式「无已知外部副作用」。

D6 红线：登记项 detail 不含消息/页面正文（只含目标标识：job_id/url/name/命令头）。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

_FILENAME = "side_effects.json"
_VERSION = 1


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
        self._path: Path | None = None
        if data_dir:
            self.configure(data_dir)

    def configure(self, data_dir: str) -> None:
        """绑定存储目录（factory 装配时调用；测试可重复 configure 到 tmp 目录）."""
        with self._lock:
            self._path = Path(data_dir).expanduser() / _FILENAME
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    # ── 持久化（与 human_turn_queue 同纪律：tempfile+replace，异常分级）──

    def _save(self) -> None:
        if self._path is None:
            return  # 未 configure（如裸单测）：内存模式，不持久化
        payload = {"version": _VERSION, "seq": self._seq, "items": self._items, "stops": self._stops}
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=_FILENAME, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except BaseException as exc:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            raise SideEffectError("definitely_not_committed", str(exc)) from exc
        try:
            os.replace(tmp, self._path)
        except BaseException as exc:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            raise SideEffectError("commit_outcome_uncertain", str(exc)) from exc

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            self._items, self._seq, self._stops = [], 0, {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = list(data.get("items", []))
            self._seq = int(data.get("seq", len(self._items)))
            self._stops = dict(data.get("stops", {}))
        except Exception:  # noqa: BLE001 — 损坏文件按空表起步（观测数据，非 SoT）
            self._items, self._seq, self._stops = [], 0, {}

    # ── 副作用登记（registry.execute 派发时调用；登记失败 fail-open 不阻断工具）──

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
            self._seq += 1
            eff_id = f"se-{self._seq}"
            self._items.append(
                {
                    "id": eff_id,
                    "session_id": session_id,
                    "tool": tool,
                    "target": str(target)[:200],
                    "kind": kind,
                    "revocable": bool(revocable),
                    "detail": str(detail)[:200],
                    "created_at": _now(),
                    "settled_at": None,   # 自然完成/已被停止回收的时间
                    "confirmed_at": None,  # 人工确认（仅 external_unknown 用）
                    "confirmed_by": None,
                }
            )
            try:
                self._save()
            except SideEffectError:
                return None  # fail-open：登记失败不阻断工具执行（观测面尽力而为）
            return eff_id

    def settle(self, eff_id: str, *, reason: str = "settled") -> bool:
        """副作用已结束（自然完成或被停止机制回收）."""
        with self._lock:
            for it in self._items:
                if it.get("id") == eff_id and not it.get("settled_at"):
                    it["settled_at"] = _now()
                    it["settle_reason"] = reason[:60]
                    try:
                        self._save()
                    except SideEffectError:
                        pass
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
                try:
                    self._save()
                except SideEffectError:
                    pass
        return n

    def confirm_external(self, eff_id: str, confirmed_by: str, note: str = "") -> bool:
        """人工确认 external_unknown 已处置（无 TTL 自动确认；D5）."""
        with self._lock:
            for it in self._items:
                if it.get("id") == eff_id:
                    it["confirmed_at"] = _now()
                    it["confirmed_by"] = str(confirmed_by)[:60]
                    it["confirm_note"] = str(note)[:200]
                    try:
                        self._save()
                    except SideEffectError:
                        pass
                    return True
            return False

    def snapshot(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(it) for it in self._items if it.get("session_id") == session_id]

    # ── 停止记录（runner.cancel 写入；四态组合的数据源之一）──

    def record_stop_requested(self, session_id: str, reason: str = "") -> None:
        with self._lock:
            rec = self._stops.setdefault(session_id, {})
            rec["requested_at"] = _now()
            rec["reason"] = reason[:120]
            try:
                self._save()
            except SideEffectError:
                pass  # fail-open：停止主链路优先，记录尽力而为

    def record_stop_dispatched(self, session_id: str, stopped: int) -> None:
        with self._lock:
            rec = self._stops.setdefault(session_id, {})
            rec["dispatched_stopped_at"] = _now()
            rec["dispatched_stopped_count"] = int(stopped)
            try:
                self._save()
            except SideEffectError:
                pass

    def record_local_terminated(self, session_id: str) -> None:
        """run 本地终态时刻（runner done/error 出口写入；精确终止侧口径）."""
        with self._lock:
            rec = self._stops.setdefault(session_id, {})
            rec["terminated_at"] = _now()
            try:
                self._save()
            except SideEffectError:
                pass

    def stop_record(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._stops.get(session_id, {}))

    # ── 四态组合查询（纯函数式组合，不做状态迁移）──

    def stop_state(
        self,
        session_id: str,
        *,
        run_alive: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """组合四态（requested/dispatched_stopped/local_terminated + external）.

        run_alive：调用方提供「该会话 run 是否仍在跑」的判定（runner 视角）。
        无停止记录时返回 idle（未请求停止）；这是查询面不是状态机——
        每个时间戳来自其真实发生点，组合规则机械透明。
        """
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
        if not rec.get("requested_at"):
            state = "idle"
        elif alive:
            state = "dispatched_stopped" if rec.get("dispatched_stopped_at") else "requested"
        else:
            state = "local_terminated"
        return {
            "session_id": session_id,
            "state": state,
            "requested_at": rec.get("requested_at"),
            "dispatched_stopped_at": rec.get("dispatched_stopped_at"),
            "dispatched_stopped_count": rec.get("dispatched_stopped_count"),
            "run_alive": alive,
            "local_terminated_at": (
                None if alive else rec.get("requested_at") and (rec.get("terminated_at") or _last_terminal_hint(rec))
            ),
            "external_unknown": external_unknown,
            "external_unknown_count": len(external_unknown),
            "external_all_confirmed": all(e["confirmed_at"] for e in external_unknown),
            "active_effects_count": len(active_effects),
            "no_known_external_side_effects": len(active_effects) == 0,
        }


def _last_terminal_hint(rec: dict[str, Any]) -> float | None:
    """run 已不活跃时的本地终止参考时刻（=派发时刻；精确终态时刻由调用方补写）."""
    return rec.get("dispatched_stopped_at") or rec.get("requested_at")
