"""D1 存量迁移与回滚编排（design.md §2.2.2-E / spec §5.5）.

`run_migration`: 备份（迁移前将源 session JSON 复制到备份区）→ 逐会话生成事件日志
（幂等：已迁移且校验通过的会话跳过）→ 每会话迁移后 `reconcile` 校验 → 汇总报告
（通过+失败=总数闭环）。迁移不删源（spec §5.5.1-6）。

`run_rollback`: 从备份区恢复源数据（逐字节一致）；`remove_events=True` 时清除
迁移生成的事件日志（由操作者显式确认），False 时保留。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.event_log.model import (
    EVENT_CONTEXT_COMPRESSED,
    EVENT_MESSAGE_APPENDED,
    EVENT_SESSION_CREATED,
    build_message_payload,
)
from llm_loop.event_log.reconcile import reconcile
from llm_loop.event_log.replay import _TOP_LEVEL_DEFAULTS, replay_session
from llm_loop.event_log.store import EventStore

logger = logging.getLogger(__name__)

# 压缩标注消息识别标记（实测存量会话 content 形态，spec §1.2.6-3）
_COMPRESSED_MARKERS = ("已压缩", "已另存", "中间省略")

# session.created payload 承载的顶层字段（与 Session.to_dict() 对齐）
_TOP_FIELDS = (
    "version",
    "title",
    "created_at",
    "updated_at",
    "status",
    "parent_id",
    "branch_id",
    "branch_summary",
    "model_override",
    "pinned",
    "channel",
)


@dataclass
class MigrationReport:
    """迁移报告（通过+失败=总数闭环）."""

    sessions_total: int
    migrated: int
    skipped_existing: int
    failed: list[dict] = field(default_factory=list)
    backup_dir: str = ""
    elapsed_s: float = 0.0

    def render_text(self) -> str:
        lines = ["【事件日志迁移报告】"]
        lines.append(
            f"- 会话总数: {self.sessions_total} / 迁移通过: {self.migrated} / "
            f"幂等跳过: {self.skipped_existing} / 失败: {len(self.failed)}"
        )
        if self.failed:
            lines.append("- 失败清单（如实标注）:")
            for f in self.failed:
                lines.append(f"    - {f.get('session_id')}: {f.get('reason')}")
        lines.append(f"- 备份区: {self.backup_dir or '（未生成）'}")
        lines.append(f"- 耗时: {self.elapsed_s:.2f}s")
        return "\n".join(lines)


def run_migration(
    sessions_dir: str | Path,
    event_logs_dir: str | Path,
    *,
    backup_dir: str | Path | None = None,
    force: bool = False,
) -> MigrationReport:
    """存量会话 → 事件日志迁移（备份→迁移→校验闭环，幂等）.

    Args:
        sessions_dir: 源会话目录（data/sessions）.
        event_logs_dir: 事件日志目录（data/event_logs）.
        backup_dir: 备份区（默认 event_logs_dir/_backup/<ts>/）.
        force: True 时跳过幂等检查强制重建（先清除既有事件文件，append-only 语义下
            用于修复不一致；默认 False 对已迁移会话幂等跳过）.

    Returns:
        迁移报告（migrated/skipped_existing/failed 闭环对账）.
    """
    start = time.monotonic()
    sessions_root = Path(sessions_dir)
    logs_root = Path(event_logs_dir)

    if not sessions_root.is_dir():
        return MigrationReport(
            sessions_total=0,
            migrated=0,
            skipped_existing=0,
            failed=[{"session_id": "", "reason": f"会话目录不存在: {sessions_root}"}],
            elapsed_s=0.0,
        )

    # ── 备份先行（备份失败 → 中止迁移）──
    if backup_dir is None:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_dir = logs_root / "_backup" / ts
    backup_root = Path(backup_dir)
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return MigrationReport(
            sessions_total=0,
            migrated=0,
            skipped_existing=0,
            failed=[{"session_id": "", "reason": f"备份区不可写（中止迁移）: {exc}"}],
            elapsed_s=time.monotonic() - start,
        )

    session_files = sorted(sessions_root.glob("*.json"))
    total = len(session_files)
    migrated = 0
    skipped = 0
    failed: list[dict] = []
    store = EventStore(logs_root)

    for p in session_files:
        sid = p.stem
        try:
            source = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(source, dict):
                raise ValueError("会话文件非对象")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            failed.append({"session_id": sid, "reason": f"源文件解析失败: {exc}"})
            continue

        # 备份源文件到备份区（复制，源不动）
        try:
            backup_sessions = backup_root / "sessions"
            backup_sessions.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup_sessions / p.name)
        except OSError as exc:
            failed.append({"session_id": sid, "reason": f"备份失败: {exc}"})
            continue

        # 幂等：事件日志存在且校验通过 → 跳过（不产生重复事件）
        if not force and store.exists(sid) and _verify_passed(store, sid, source):
            skipped += 1
            continue

        # 强制/修复：清除既有事件文件后重建
        if force and store.exists(sid):
            try:
                store._path(sid).unlink()  # noqa: SLF001 — 修复语义需重建
            except OSError as exc:
                failed.append({"session_id": sid, "reason": f"清除既有事件失败: {exc}"})
                continue

        try:
            _generate_events(store, sid, source)
            if not _verify_passed(store, sid, source):
                failed.append(
                    {"session_id": sid, "reason": "迁移后校验不一致（差异详见 event-verify）"}
                )
                continue
            migrated += 1
        except Exception as exc:  # noqa: BLE001 — 单会话失败不中断整体（fail-open）
            failed.append({"session_id": sid, "reason": f"迁移异常: {type(exc).__name__}: {exc}"})
            continue

    return MigrationReport(
        sessions_total=total,
        migrated=migrated,
        skipped_existing=skipped,
        failed=failed,
        backup_dir=str(backup_root),
        elapsed_s=time.monotonic() - start,
    )


def _generate_events(store: EventStore, session_id: str, source: dict) -> None:
    """按源会话生成事件日志（session.created + message.appended + context.compressed）."""
    # 顶层字段缺省按读路径语义补默认（对齐 Session.load 的缺省向后兼容）：
    # v3 旧会话缺 pinned/channel/model_override 键 → 事件承载默认值而非 None，
    # 保证重放视图与 Session.load().to_dict() 逐字段一致（spec §5.4.1-1）。
    payload = {
        k: source.get(k, _TOP_LEVEL_DEFAULTS.get(k)) for k in _TOP_FIELDS
    }
    payload["version"] = source.get("version", _TOP_LEVEL_DEFAULTS.get("version", 4))
    store.append(session_id, EVENT_SESSION_CREATED, payload)

    messages = source.get("messages") or []
    archives_dir = Path(store._dir).parent / "archives"  # noqa: SLF001
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        store.append(
            session_id,
            EVENT_MESSAGE_APPENDED,
            build_message_payload(
                index=i,
                role=m.get("role", ""),
                content=m.get("content", ""),
                source=m.get("source", "user"),
                tool_call_id=m.get("tool_call_id"),
                status=m.get("status"),
                tool_name=m.get("tool_name"),
                error_detail=m.get("error_detail"),
                tool_calls=m.get("tool_calls"),
                reasoning_content=m.get("reasoning_content"),
                metadata=m.get("metadata") or {},
            ),
        )
        # 压缩标注消息：追加 context.compressed 引用契约（archive_ref=tool_call_id）
        if _is_compressed_marker(m.get("content", "")):
            tool_call_id = m.get("tool_call_id")
            chars = _lookup_archive_chars(archives_dir, session_id, tool_call_id)
            if chars is None:
                chars = len(m.get("content", ""))
            store.append(
                session_id,
                EVENT_CONTEXT_COMPRESSED,
                {
                    "archive_ref": tool_call_id,
                    "tool_call_id": tool_call_id,
                    "msg_seq": i,
                    "chars": chars,
                },
            )


def _verify_passed(store: EventStore, session_id: str, source: dict) -> bool:
    """重放事件日志并与源逐字段比对（纯只读）."""
    events = store.read(session_id)
    if not events:
        return False
    derived = replay_session(events)
    if derived.get("exists") is False:
        return False
    report = reconcile(derived, source)
    return report.passed


def _is_compressed_marker(content: str) -> bool:
    if not content:
        return False
    return any(marker in content for marker in _COMPRESSED_MARKERS)


def _lookup_archive_chars(archives_dir: Path, session_id: str, tool_call_id) -> int | None:
    """从 archives/<session_id>.jsonl 按 tool_call_id 取原文长度（fail-open，找不到返回 None）."""
    if not tool_call_id:
        return None
    p = archives_dir / f"{session_id}.jsonl"
    if not p.is_file():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("tool_call_id") == tool_call_id:
                    chars = entry.get("chars")
                    if isinstance(chars, int):
                        return chars
                    content = entry.get("content")
                    if isinstance(content, str):
                        return len(content)
                    return None
    except OSError as exc:
        logger.warning("档案读取失败（fail-open）: %s: %s", p, exc)
    return None


def run_rollback(
    backup_dir: str | Path,
    event_logs_dir: str | Path,
    *,
    session_ids: list[str] | None = None,
    remove_events: bool = False,
) -> dict:
    """从备份区恢复源数据（逐字节一致）；可选清除迁移生成的事件日志.

    Args:
        backup_dir: 备份区（_backup/<ts>/，内含 sessions/*.json）.
        event_logs_dir: 事件日志目录（其父级推导恢复目标 sessions 目录）.
        session_ids: 指定会话（None = 恢复全部备份）.
        remove_events: True 时清除对应事件日志（由操作者显式确认），False 保留.

    Returns:
        恢复结果 {"restored": [...], "events_removed": [...], "errors": [...]}.
    """
    backup_root = Path(backup_dir)
    logs_root = Path(event_logs_dir)
    restore_dir = logs_root.parent / "sessions"
    backup_sessions = backup_root / "sessions"
    restored: list[str] = []
    events_removed: list[str] = []
    errors: list[str] = []

    if not backup_sessions.is_dir():
        return {"restored": [], "events_removed": [], "errors": [f"备份区无会话数据: {backup_root}"]}

    ids = set(session_ids) if session_ids else None
    for p in sorted(backup_sessions.glob("*.json")):
        sid = p.stem
        if ids is not None and sid not in ids:
            continue
        try:
            restore_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, restore_dir / p.name)
            restored.append(sid)
        except OSError as exc:
            errors.append(f"{sid}: 恢复失败: {exc}")

    if remove_events:
        for sid in restored:
            try:
                ev_path = logs_root / f"{sid}.jsonl"
                if ev_path.exists():
                    ev_path.unlink()
                    events_removed.append(sid)
            except OSError as exc:
                errors.append(f"{sid}: 清除事件日志失败: {exc}")

    return {
        "restored": restored,
        "events_removed": events_removed,
        "errors": errors,
    }
