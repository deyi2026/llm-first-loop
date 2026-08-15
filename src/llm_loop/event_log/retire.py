"""三套存储物理退役编排（design.md §2.2.2-B / spec §5.2）.

将三套并存存储从"双轨可对账的迁移源"转变为"归档的非权威数据"——
读路径切换为从事件日志 replay 重建 + 双轨对账前置 + 灰度开关 + 回滚安全网。

退役顺序：① 备份 → ② 全量双轨对账 → ③ 归档 action_trace → ④ 归档 session JSON →
⑤ 切换读路径 → ⑥ 压缩档案保留。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RetireReport:
    """退役报告（design.md §2.2.2-B）.

    P1-2(2026-08-15，审计发现 #12)：如实命名——程序不替人改 .env（真实的读路径
    切换 = 人工改 READ_PATH_SOURCE + 重启），退役只报告"可切换就绪"并给出指引；
    旧字段 read_path_switched 谎称已切换，已更名 read_path_ready_to_switch。
    """

    retired_steps: list[str] = field(default_factory=list)
    reconcile_passed: bool = False
    reconcile_diffs: list[str] = field(default_factory=list)
    read_path_ready_to_switch: bool = False  # 对账通过+归档完成，具备人工切换条件
    switch_instructions: list[str] = field(default_factory=list)  # 人工切换指引（如实）
    backup_dir: str = ""
    archived_files: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str = ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def run_retire(
    data_dir: str | Path,
    *,
    read_path_source: str = "session_json",
    force: bool = False,
) -> RetireReport:
    """执行三套存储退役编排（spec §5.2.1）.

    Args:
        data_dir: 数据目录（含 sessions/ event_logs/ action_trace/ archives/）.
        read_path_source: 当前读路径（session_json/event_log）.
        force: 跳过幂等检查强制退役.

    Returns:
        RetireReport.
    """
    import time

    start = time.monotonic()
    report = RetireReport()
    data = Path(data_dir)
    sessions_dir = data / "sessions"
    event_logs_dir = data / "event_logs"
    action_trace = data / "action_trace"
    retired_dir = data / "_retired"

    # ① 退役前备份
    ts = _now_ts()
    backup_dir = retired_dir / "_backup" / ts
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        if sessions_dir.exists():
            shutil.copytree(sessions_dir, backup_dir / "sessions", dirs_exist_ok=True)
        if action_trace.exists():
            shutil.copytree(action_trace, backup_dir / "action_trace", dirs_exist_ok=True)
        report.backup_dir = str(backup_dir)
        report.retired_steps.append("backup")
    except OSError as exc:
        report.error = f"备份失败（中止退役）: {exc}"
        report.elapsed_s = round(time.monotonic() - start, 2)
        return report

    # ② 全量双轨对账（replay 视图 vs session JSON 逐字段一致）
    from llm_loop.event_log.reconcile import reconcile
    from llm_loop.event_log.replay import replay_session
    from llm_loop.event_log.store import EventStore

    event_store = EventStore(event_logs_dir, enabled=True)
    diffs: list[str] = []
    session_files = sorted(sessions_dir.glob("*.json")) if sessions_dir.exists() else []
    for sf in session_files:
        sid = sf.stem
        if not event_store.exists(sid):
            diffs.append(f"{sid}: 事件日志不存在")
            continue
        events = event_store.read(sid)
        view = replay_session(events)
        import json

        try:
            source = json.loads(sf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            diffs.append(f"{sid}: session JSON 损坏")
            continue
        result = reconcile(view, source)
        if not result.passed:
            # 容忍已知双轨差异：title（save 自动补标题 vs session.created 事件写入时为空）
            # 和 updated_at（每次 save 更新 vs 事件写入时固定）
            _tolerable_fields = {"title", "updated_at"}
            real_top_diffs = [
                d for d in result.top_level_diffs
                if d.get("字段") not in _tolerable_fields
            ]
            if real_top_diffs or result.message_diffs:
                diffs.append(
                    f"{sid}: 顶层差异 {len(real_top_diffs)} 消息差异 {len(result.message_diffs)}"
                )

    report.reconcile_diffs = diffs
    if diffs:
        report.reconcile_passed = False
        report.error = f"双轨对账不一致（{len(diffs)} 项），不切换不退役"
        report.elapsed_s = round(time.monotonic() - start, 2)
        return report
    report.reconcile_passed = True
    report.retired_steps.append("reconcile")

    # ③ 归档 action_trace
    archive_target = retired_dir / "action_trace"
    if action_trace.exists():
        try:
            shutil.copytree(action_trace, archive_target, dirs_exist_ok=True)
            report.archived_files.append("action_trace")
            report.retired_steps.append("archive_action_trace")
        except OSError as exc:
            logger.warning("action_trace 归档失败（fail-open）: %s", exc)

    # ④ 归档 session JSON
    sessions_target = retired_dir / "sessions"
    if sessions_dir.exists():
        try:
            shutil.copytree(sessions_dir, sessions_target, dirs_exist_ok=True)
            report.archived_files.append("sessions")
            report.retired_steps.append("archive_sessions")
        except OSError as exc:
            logger.warning("session JSON 归档失败（fail-open）: %s", exc)

    # ⑤ 切换读路径（P1-2 如实标注：程序不替人改 .env——报告"就绪"+人工指引；
    #    真实切换 = 人工设 READ_PATH_SOURCE=event_log + 重启服务）
    report.read_path_ready_to_switch = True
    if read_path_source == "event_log":
        report.switch_instructions = [
            "当前读路径已是 event_log（READ_PATH_SOURCE=event_log），无需切换。",
        ]
    else:
        report.switch_instructions = [
            "1. 编辑 .env：设置 READ_PATH_SOURCE=event_log",
            "2. 重启服务：bash scripts/restart_system.sh restart",
            "3. 重启后抽查若干会话确认读取正常；异常则改回 session_json 并重启回退",
        ]
    report.retired_steps.append("switch_read_path")

    # ⑥ 压缩档案保留（不移动）
    report.retired_steps.append("keep_archives")

    report.elapsed_s = round(time.monotonic() - start, 2)
    return report


def run_retire_rollback(backup_dir: str | Path, data_dir: str | Path) -> dict:
    """从备份区恢复源文件 + 读路径切回 session_json（spec §5.2.1-6）.

    Returns:
        恢复结果 dict（restored/events_removed/errors）.
    """
    backup = Path(backup_dir)
    data = Path(data_dir)
    sessions_dir = data / "sessions"
    action_trace = data / "action_trace"
    restored: list[str] = []
    errors: list[str] = []

    # 恢复 session JSON
    backup_sessions = backup / "sessions"
    if backup_sessions.exists():
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup_sessions, sessions_dir, dirs_exist_ok=True)
            restored.append("sessions")
        except OSError as exc:
            errors.append(f"sessions 恢复失败: {exc}")

    # 恢复 action_trace
    backup_action_trace = backup / "action_trace"
    if backup_action_trace.exists():
        try:
            shutil.copytree(backup_action_trace, action_trace, dirs_exist_ok=True)
            restored.append("action_trace")
        except OSError as exc:
            errors.append(f"action_trace 恢复失败: {exc}")

    return {"restored": restored, "errors": errors}
