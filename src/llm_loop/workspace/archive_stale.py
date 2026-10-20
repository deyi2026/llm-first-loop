"""archive-stale 核心例程与 web 常驻自动归档循环.

`run_archive_stale` 是 CLI（``lfl archive-stale``）与 web 服务后台线程共用的唯一实现，
判定语义、副作用与恢复路径见 docs/RUNBOOK-20261021-archive-stale.md；
`ArchiveStaleLoop` 挂在 web 服务进程里按周期自动真跑（非 dry-run）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from llm_loop.core.session import SessionMutationBusyError, SessionStore
from llm_loop.event_log.session_types import SessionIdConflictError
from llm_loop.timekeeping import system_local_now
from llm_loop.workspace.store import WorkspaceStore

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 5
DEFAULT_TICK_S = 300.0
DEFAULT_PERIOD_S = 86400.0
STATE_FILENAME = "auto_state.json"


class ArchiveStaleFatalError(RuntimeError):
    """致命错误（工作区注册表读取失败等）；CLI 映射为退出码 2."""


@dataclass
class ArchiveStaleResult:
    """单轮 archive-stale 的结构化结果：CLI 据此打印/退出，自动线程据此写状态."""

    counts: dict[str, int] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)
    exit_code: int = 0
    report_path: Path | None = None


def run_archive_stale(
    data_dir: Path | str,
    *,
    days: int = DEFAULT_DAYS,
    dry_run: bool = False,
    report_path: Path | str | None = None,
    anchor: datetime | None = None,
    log: Callable[[str], None] | None = None,
) -> ArchiveStaleResult:
    """单轮批量归档（CLI 与自动线程唯一实现）.

    - 锚点 = 本轮启动时刻；过期 = updated_at 严格早于 锚点-<days> 天（恰好等于不过期）
    - 范围 = 工作区注册表全部未退休工作区分区（data/sessions/<ws-id>）；注册表为空回退平铺根
    - 只处理 status=active 且未 pinned 的会话，最老优先
    - 运行中（busy）/ 身份冲突 / 并发消失逐条跳过并报告，不中断批次
    - 归档成功后若该工作区 shared_current 指针指向此会话则清空（防跨端解析到归档态）
    - jsonl 报告逐行落盘（含 0 候选轮次）；存在 error 行 → exit_code=1
    """
    emit = log if log is not None else (lambda _msg: None)
    data_dir = Path(data_dir)
    sessions_root = data_dir / "sessions"
    if anchor is None:
        anchor = system_local_now()
    cutoff = anchor - timedelta(days=days)

    # 分区枚举：注册表未退休工作区；注册表为空回退平铺根目录（未分区布局）
    try:
        workspaces = WorkspaceStore(data_dir).list()
    except Exception as exc:  # noqa: BLE001 — 注册表损坏时不进入半执行状态
        raise ArchiveStaleFatalError(str(exc)) from exc
    if workspaces:
        partitions = [(ws.id, sessions_root / ws.id) for ws in workspaces]
    else:
        partitions = [("", sessions_root)]

    report = (
        Path(report_path)
        if report_path
        else data_dir / "reports" / "archive_stale" / f"{anchor.strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    report.parent.mkdir(parents=True, exist_ok=True)

    counts = {"dry-run": 0, "archived": 0, "busy": 0, "identity_conflict": 0,
              "missing": 0, "error": 0, "pointer_cleared": 0}
    rows: list[dict] = []

    def _parse_updated_at(text: str) -> datetime | None:
        try:
            return datetime.fromisoformat(str(text))
        except (TypeError, ValueError):
            return None

    emit(f"[archive-stale] 锚点 {anchor.isoformat(timespec='seconds')} | 阈值 {days} 天"
         f" | 分区 {len(partitions)} 个（{'dry-run' if dry_run else '执行'}）")
    for ws_id, part_dir in partitions:
        if not part_dir.is_dir():
            continue
        # identity_root 取 sessions 根：owner key = <ws-id>，与引擎挂载口径一致
        store = SessionStore(part_dir, identity_root=sessions_root)
        candidates = []
        for meta in store.list_sessions(include_archived=False):
            if meta.status != "active" or getattr(meta, "pinned", False):
                continue
            updated = _parse_updated_at(meta.updated_at)
            if updated is None:
                counts["error"] += 1
                rows.append({"workspace": ws_id, "session_id": meta.session_id,
                             "title": meta.title, "updated_at": meta.updated_at,
                             "action": "error", "error": "unparseable updated_at"})
                emit(f"  [错误] {meta.session_id[:10]} | updated_at 无法解析: {meta.updated_at!r}")
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=anchor.tzinfo)  # 无时区按本地处理
            if updated < cutoff:
                candidates.append((updated, meta))
        candidates.sort(key=lambda pair: pair[0])
        for updated, meta in candidates:
            sid = meta.session_id
            age_days = (anchor - updated).total_seconds() / 86400.0
            row = {"workspace": ws_id, "session_id": sid, "title": meta.title,
                   "updated_at": meta.updated_at, "age_days": round(age_days, 2)}
            if dry_run:
                action = "dry-run"
            else:
                try:
                    ok = store.archive(sid)
                except SessionMutationBusyError as exc:
                    action, row["error"] = "busy", str(exc)[:200]
                except SessionIdConflictError as exc:
                    action, row["error"] = "identity_conflict", str(exc)[:200]
                except Exception as exc:  # noqa: BLE001 — 单条异常不中断批次
                    action, row["error"] = "error", f"{type(exc).__name__}: {exc}"[:200]
                else:
                    action = "archived" if ok else "missing"
                    if action == "archived" and store.get_shared_current() == sid:
                        store.clear_shared_current()
                        counts["pointer_cleared"] += 1
            counts[action] += 1
            row["action"] = action
            rows.append(row)
            flag = {"dry-run": "候选", "archived": "已归档", "busy": "跳过(运行中)",
                    "identity_conflict": "跳过(身份冲突)", "missing": "跳过(已消失)",
                    "error": "错误"}[action]
            emit(f"  [{flag}] {sid[:10]} | {meta.title[:30]} | 更新于 {str(meta.updated_at)[:19]}"
                 f" | 距今 {age_days:.1f} 天")

    with report.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = counts["dry-run"] + counts["archived"] + counts["busy"] + counts["identity_conflict"] + counts["missing"] + counts["error"]
    emit(f"[archive-stale] 完成: 候选/处置 {total} 条 | 归档 {counts['archived']}"
         f" | busy {counts['busy']} | 身份冲突 {counts['identity_conflict']}"
         f" | 消失 {counts['missing']} | 错误 {counts['error']} | 指针清理 {counts['pointer_cleared']}")
    emit(f"[archive-stale] 报告: {report}")
    return ArchiveStaleResult(
        counts=counts,
        rows=rows,
        exit_code=1 if counts["error"] else 0,
        report_path=report,
    )


def _env_number(name: str, default: float, *, integer: bool = False) -> float:
    """读环境变量数值；缺失/非法回退默认值并告警（不抛出，调度配置坏值不致命）."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        logger.warning("忽略非法环境变量 %s=%r，使用默认 %s", name, raw, default)
        return float(default)
    return round(value) if integer else value


class ArchiveStaleLoop(threading.Thread):
    """daemon 线程：挂在 web 服务里按周期自动真跑 archive-stale.

    - 到期判定基于持久状态文件 auto_state.json（next_due）——服务重启不重复跑
    - 异常不外抛：写错误态（summary.error）并把下一轮顺延一个完整周期
    - 配置（构造参数 None 时读环境变量）: LFL_ARCHIVE_STALE_AUTO（总开关，默认开）、
      LFL_ARCHIVE_STALE_DAYS（默认 5）、LFL_ARCHIVE_STALE_TICK_S（默认 300）、
      LFL_ARCHIVE_STALE_PERIOD_S（默认 86400）；PYTEST_CURRENT_TEST 下默认自禁用
    """

    def __init__(
        self,
        data_dir: Path | str,
        *,
        days: int | None = None,
        tick_s: float | None = None,
        period_s: float | None = None,
        initial_delay_s: float = 60.0,
        enabled: bool | None = None,
        clock: Callable[[], datetime] = system_local_now,
    ) -> None:
        super().__init__(name="archive-stale-loop", daemon=True)
        self.data_dir = Path(data_dir)
        self.days = max(int(_env_number("LFL_ARCHIVE_STALE_DAYS", DEFAULT_DAYS, integer=True)
                            if days is None else days), 1)
        self.tick_s = max(float(_env_number("LFL_ARCHIVE_STALE_TICK_S", DEFAULT_TICK_S)
                                if tick_s is None else tick_s), 1.0)
        self.period_s = max(float(_env_number("LFL_ARCHIVE_STALE_PERIOD_S", DEFAULT_PERIOD_S)
                                  if period_s is None else period_s), 1.0)
        self.initial_delay_s = max(float(initial_delay_s), 0.0)
        self.clock = clock
        if enabled is None:
            enabled = (
                os.environ.get("LFL_ARCHIVE_STALE_AUTO", "1").strip() != "0"
                and not os.environ.get("PYTEST_CURRENT_TEST")
            )
        self.enabled = bool(enabled)
        self._stop_event = threading.Event()

    @property
    def state_path(self) -> Path:
        return self.data_dir / "reports" / "archive_stale" / STATE_FILENAME

    def stop(self) -> None:
        self._stop_event.set()

    def load_state(self) -> dict:
        """读取持久状态；缺失/损坏一律视为无状态（fail-open：到期补跑一轮）."""
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, *, last_run: datetime, next_due: datetime, summary: dict) -> None:
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_run": last_run.isoformat(timespec="seconds"),
            "next_due": next_due.isoformat(timespec="seconds"),
            "days": self.days,
            "period_s": self.period_s,
            "summary": summary,
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def is_due(self, now: datetime | None = None) -> bool:
        state = self.load_state()
        raw = state.get("next_due")
        if not raw:
            return True
        try:
            next_due = datetime.fromisoformat(str(raw))
        except ValueError:
            return True
        now = now if now is not None else self.clock()
        if next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=now.tzinfo)
        return now >= next_due

    def run_once_due(self) -> dict | None:
        """到期则真跑一轮并写状态；未到期返回 None；任何异常记入状态不外抛."""
        if not self.is_due():
            return None
        started = self.clock()
        summary: dict
        try:
            result = run_archive_stale(self.data_dir, days=self.days, log=logger.info)
            summary = {"counts": dict(result.counts), "exit_code": result.exit_code,
                       "report": str(result.report_path) if result.report_path else None}
            logger.info("archive-stale auto: %s", summary)
        except Exception as exc:  # noqa: BLE001 — 调度线程必须自愈，不能因单轮异常退出
            logger.warning("archive-stale auto run failed", exc_info=True)
            summary = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        self.save_state(last_run=started, next_due=started + timedelta(seconds=self.period_s),
                        summary=summary)
        return summary

    def run(self) -> None:  # pragma: no cover - 线程调度由 main/wait 循环驱动
        if not self.enabled:
            return
        if self._stop_event.wait(self.initial_delay_s):
            return
        while not self._stop_event.is_set():
            try:
                self.run_once_due()
            except Exception:  # noqa: BLE001
                logger.warning("archive-stale loop iteration failed", exc_info=True)
            if self._stop_event.wait(self.tick_s):
                return
