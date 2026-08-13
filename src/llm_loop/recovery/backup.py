"""备份归档数据模型与备份存储组件（design §2.3.2.4/§2.3.2.5 / spec §4.4/§6）.

BackupArchive：备份归档数据模型（spec §6.1/§6.2 字段统一），payload 原文存储不改写。
BackupStore：备份存储（写入/读取/列出/标记/清理/状态统计 + 文件名 sanitize + 路径安全），
操作 data/.recovery/ 目录。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm_loop.recovery.policy import RetryPolicy


@dataclass
class BackupArchive:
    """备份归档数据模型（spec §6.1/§6.2 字段统一）.

    - source_id：来源标识（session_id 或 "memory"）。
    - backup_at：ISO 时间戳。
    - target_type："session" | "memory_stats"。
    - payload：待写入原文（不摘要/改写/压缩，spec §4.2.2 规则 3）。
    - retry_count：转备份前已重试次数。
    - trigger_point："initial_save" | "loop_end_save" | "memory_flush"。
    - recovered：恢复状态（默认 False）。
    """

    source_id: str
    backup_at: str
    target_type: str
    payload: str
    retry_count: int
    trigger_point: str
    recovered: bool = False

    @property
    def backup_id(self) -> str:
        """生成文件名 <source_id>.<YYYYMMDDHHMMSS>.<target_type>.pending.json."""
        safe_id = BackupStore.sanitize_source_id(self.source_id)
        ts = datetime.fromisoformat(self.backup_at).strftime("%Y%m%d%H%M%S")
        return f"{safe_id}.{ts}.{self.target_type}.pending.json"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "backup_at": self.backup_at,
            "target_type": self.target_type,
            "payload": self.payload,
            "retry_count": self.retry_count,
            "trigger_point": self.trigger_point,
            "recovered": self.recovered,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BackupArchive:
        return cls(
            source_id=data["source_id"],
            backup_at=data["backup_at"],
            target_type=data["target_type"],
            payload=data["payload"],
            retry_count=data["retry_count"],
            trigger_point=data["trigger_point"],
            recovered=data.get("recovered", False),
        )


class BackupStore:
    """备份存储组件，操作 data/.recovery/ 目录.

    - save_archive：写入 .pending.json（文件名 sanitize + 路径安全）。
    - get_archive：读取并解析（损坏返回 None）。
    - list_pending：列出待恢复备份（recovered=False，按时间排序）。
    - mark_recovered：标记已恢复（不删除文件）。
    - cleanup：清理超期超量（删最旧 + action_trace 留痕）。
    - status_summary：供 architecture_status 感知。
    """

    _MAX_SOURCE_ID_LEN = 128

    def __init__(self, recovery_dir: str | Path) -> None:
        self._dir = Path(recovery_dir)

    @staticmethod
    def sanitize_source_id(source_id: str) -> str:
        """kebab-case + 拒绝路径穿越 + 截断长度（spec §4.3.1）."""
        s = re.sub(r"[^a-zA-Z0-9._-]", "-", source_id)
        s = re.sub(r"-+", "-", s).strip("-_.")
        if not s:
            s = "unnamed"
        s = s[: BackupStore._MAX_SOURCE_ID_LEN]
        return s

    def save_archive(self, archive: BackupArchive) -> str:
        """写入备份归档文件，返回 backup_id."""
        self._dir.mkdir(parents=True, exist_ok=True)
        backup_id = archive.backup_id
        path = self._dir / backup_id
        path.write_text(
            json.dumps(archive.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return backup_id

    def get_archive(self, backup_id: str) -> BackupArchive | None:
        """读取并解析备份归档（不存在/损坏返回 None）."""
        path = self._dir / backup_id
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BackupArchive.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def list_pending(self, target_type: str | None = None) -> list[BackupArchive]:
        """列出待恢复备份（recovered=False，按 backup_at 排序）."""
        if not self._dir.exists():
            return []
        result: list[BackupArchive] = []
        for p in self._dir.glob("*.pending.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                archive = BackupArchive.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            if archive.recovered:
                continue
            if target_type is not None and archive.target_type != target_type:
                continue
            result.append(archive)
        result.sort(key=lambda a: a.backup_at)
        return result

    def mark_recovered(self, backup_id: str) -> bool:
        """标记备份为已恢复（更新文件内 recovered=True，不删除文件）."""
        path = self._dir / backup_id
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["recovered"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            return False

    def status_summary(self) -> dict:
        """返回 {pending_count, oldest_backup_at, by_type}（如实，不伪造）."""
        if not self._dir.exists():
            return {"pending_count": 0, "oldest_backup_at": None, "by_type": {"session": 0, "memory_stats": 0}}
        pending = self.list_pending()
        by_type: dict[str, int] = {"session": 0, "memory_stats": 0}
        for a in pending:
            by_type[a.target_type] = by_type.get(a.target_type, 0) + 1
        oldest = pending[0].backup_at if pending else None
        return {"pending_count": len(pending), "oldest_backup_at": oldest, "by_type": by_type}

    def cleanup(self) -> dict:
        """清理超期超量备份（删最旧 + action_trace 留痕，不静默删除）.

        返回 {"pruned": N}。
        """
        if not self._dir.exists():
            return {"pruned": 0}
        now = datetime.now().astimezone()
        cutoff = now.timestamp() - RetryPolicy.RETENTION_PERIOD_DAYS * 86400
        pruned = 0

        # 按文件分组（source_id + target_type）
        groups: dict[str, list[tuple[Path, BackupArchive]]] = {}
        for p in self._dir.glob("*.pending.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                archive = BackupArchive.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            key = f"{archive.source_id}.{archive.target_type}"
            groups.setdefault(key, []).append((p, archive))

        for _key, items in groups.items():
            items.sort(key=lambda x: x[1].backup_at)
            # 超期清理
            for path, archive in list(items):
                try:
                    ts = datetime.fromisoformat(archive.backup_at).timestamp()
                except ValueError:
                    continue
                if ts < cutoff:
                    try:
                        path.unlink()
                        pruned += 1
                        items.remove((path, archive))
                    except OSError:
                        pass  # 清理失败如实跳过（fail-open，不中断主循环）
            # 超量清理（保留 MAX_PER_TARGET 份最旧）
            while len(items) > RetryPolicy.MAX_PER_TARGET:
                path, _archive = items.pop(0)
                try:
                    path.unlink()
                    pruned += 1
                except OSError:
                    pass  # 清理失败如实跳过（fail-open，不中断主循环）

        return {"pruned": pruned}
