"""D1 存量存储盘点 run_inventory（design.md §2.2.2-F / spec §5.1）.

只读遍历三套存量存储（sessions / archives / compressed_archive / audit），
输出职责/规模/数据流向盘点清单 + 割裂点识别（spec §2.2 三项）。
- 目录缺失 → `dirs_missing` 如实标注 + 其余存储正常盘点；
- 损坏文件 → 跳过并标注（fail-open，不伪造规模）；
- 只读红线：盘点过程不修改任何存量文件（spec §5.1.1-3）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class InventoryReport:
    """三套存储盘点报告."""

    sessions: list[dict] = field(default_factory=list)
    archives: dict = field(default_factory=dict)
    compressed_archive: dict = field(default_factory=dict)
    action_trace: dict = field(default_factory=dict)
    event_logs: dict = field(default_factory=dict)
    gaps: list[dict] = field(default_factory=list)
    dirs_missing: list[str] = field(default_factory=list)

    def render_text(self) -> str:
        """结构化盘点报告文本（供 CLI 打印）."""
        lines: list[str] = ["【存量存储盘点】"]
        lines.append(
            f"- 会话 sessions: {len(self.sessions)} 个"
            f"（消息 {sum(s.get('message_count', 0) for s in self.sessions)} 条）"
        )
        versions: set = set()
        for s in self.sessions:
            v = s.get("version")
            if isinstance(v, (int, str)):
                versions.add(v)
        for v in sorted(versions):
            n = sum(1 for s in self.sessions if s.get("version") == v)
            lines.append(f"    - version {v}: {n} 个")
        lines.append(
            f"- 压缩档案 archives: {self.archives.get('file_count', 0)} 文件 / "
            f"{self.archives.get('entry_count', 0)} 条目"
        )
        lines.append(
            f"- 交接压缩 compressed_archive: {self.compressed_archive.get('dir_count', 0)} 目录"
        )
        lines.append(
            f"- 动作审计 action_trace: {self.action_trace.get('line_count', 0)} 行 / "
            f"{self.action_trace.get('size_bytes', 0)} 字节"
        )
        lines.append(
            f"- 事件日志 event_logs: {self.event_logs.get('file_count', 0)} 文件"
        )
        if self.dirs_missing:
            lines.append(f"- 缺失目录（如实标注）: {', '.join(self.dirs_missing)}")
        if self.gaps:
            lines.append("- 割裂点清单:")
            for g in self.gaps:
                lines.append(f"    - {g.get('point')}: {g.get('evidence', '')}")
        return "\n".join(lines)


def run_inventory(data_dir: str | Path) -> InventoryReport:
    """三套存储只读盘点（spec §5.1；对齐 spec §2.1 口径）."""
    root = Path(data_dir)
    report = InventoryReport()
    missing: list[str] = []

    # ── sessions ──
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        missing.append("sessions")
    else:
        for p in sorted(sessions_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("非对象")
                report.sessions.append(
                    {
                        "session_id": data.get("session_id", p.stem),
                        "version": data.get("version"),
                        "message_count": len(data.get("messages") or []),
                        "status": data.get("status"),
                        "title": data.get("title", ""),
                        "updated_at": data.get("updated_at", ""),
                    }
                )
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("会话文件解析失败（跳过并标注）: %s: %s", p, exc)
                report.sessions.append(
                    {"session_id": p.stem, "version": None, "message_count": 0, "broken": True}
                )

    # ── archives（压缩档案 JSONL）──
    archives_dir = root / "archives"
    if not archives_dir.is_dir():
        missing.append("archives")
    else:
        files = sorted(archives_dir.glob("*.jsonl"))
        entries = 0
        sample_fields: set[str] = set()
        for p in files:
            try:
                with p.open("r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        if isinstance(entry, dict):
                            entries += 1
                            if not sample_fields:
                                sample_fields.update(entry.keys())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("档案文件解析失败（跳过并标注）: %s: %s", p, exc)
        report.archives = {
            "file_count": len(files),
            "entry_count": entries,
            "sample_fields": sorted(sample_fields),
        }

    # ── compressed_archive（交接压缩目录）──
    compressed_dir = root / "compressed_archive"
    if not compressed_dir.is_dir():
        missing.append("compressed_archive")
    else:
        report.compressed_archive = {
            "dir_count": len([d for d in compressed_dir.iterdir() if d.is_dir()]),
        }

    # ── audit / action_trace ──
    audit_dir = root / "audit"
    trace_path = audit_dir / "action_trace.jsonl"
    if not trace_path.is_file():
        missing.append("audit/action_trace.jsonl")
    else:
        line_count = 0
        fields: set[str] = set()
        size_bytes = 0
        try:
            data = trace_path.read_bytes()
            size_bytes = len(data)
            for raw in data.decode("utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line:
                    continue
                line_count += 1
                if not fields:
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            fields.update(item.keys())
                    except json.JSONDecodeError:
                        pass  # 单行非 JSON 跳过（fail-open：损坏行不伪造字段集）
        except OSError as exc:
            logger.warning("action_trace 读取失败（跳过并标注）: %s: %s", trace_path, exc)
        report.action_trace = {
            "line_count": line_count,
            "fields": sorted(fields),
            "size_bytes": size_bytes,
            # 割裂点 A 实证：字段集不含 session_id（status.py to_dict 未输出）
            "has_session_id": "session_id" in fields,
        }

    # ── event_logs（D1 新增单一真相源目录）──
    event_logs_dir = root / "event_logs"
    if event_logs_dir.is_dir():
        report.event_logs = {
            "file_count": len(list(event_logs_dir.glob("*.jsonl"))),
        }
    else:
        report.event_logs = {"file_count": 0}

    # ── 割裂点清单（对齐 spec §2.2 三项）──
    trace_fields = report.action_trace.get("fields") or []
    report.gaps = [
        {
            "point": "割裂点 A: action_trace 无 session_id 关联",
            "evidence": f"字段集 {trace_fields}（实测缺 session_id）",
        },
        {
            "point": "割裂点 B: 超长原文与 session 松散关联",
            "evidence": "压缩档案经 tool_call_id 关联，无统一事件承载引用契约",
        },
        {
            "point": "割裂点 C: 无统一事件序",
            "evidence": "三套存储无统一 seq 事件序，无法按序重放还原",
        },
    ]

    report.dirs_missing = missing
    return report
