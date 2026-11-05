#!/usr/bin/env python3
"""一次性存量迁移：压缩确认门 gate_state.json 收敛（EVO-20261105-7eb1e99f(c)）.

背景：shadow/off 模式下确认门通知不注入模型，确认结构上不可能发生，但
gate_state.json 照常落盘并按 attempt/rounds 机械升级，escalated 后永久残留
（2026-11-05 实测累计 70 个，人工清理 3 个后余 67 个）。运行时修复
（shadow 不落盘 + factory TTL 收割）只管增量，存量走本脚本一次性收敛。

分类规则（保守，与建议一致）：
  - pending（pending=True）            → 保留（活确认门）
  - degraded（status=degraded）        → 保留（完整性观察，非确认门）
  - confirmed（consumed_at 且非上述）  → 归档后删除
  - superseded（superseded=True）      → 归档后删除
  - escalated（escalated=True，含 shadow/off 伪升级遗留）→ 归档后删除
  - 不可解析/未知形态                  → 保留，逐条列出待人工判定

归档：data/compaction_snapshots/_migrated-<date>.jsonl，逐文件记录
  original_path（相对 data 根）+ content_digest（状态字段投影）+
  sha256（原文件字节级哈希，审计可复核）+ 归档时间与原因分类。
幂等：归档键=文件 sha256；已归档未删除的残留（中断重跑）只补删除不重复
  归档；已删除的文件自然不再出现。

用法：
  python scripts/migrate_compaction_gate_states.py             # dry-run（默认，只读）
  python scripts/migrate_compaction_gate_states.py --execute   # 实际归档+删除
  python scripts/migrate_compaction_gate_states.py --data-dir D

真实执行须由主会话在独立审查后决定（本脚本在仓库内，先 dry-run 看清单）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

KEEP_CLASSES = ("pending", "degraded", "unknown")
_DIGEST_FIELDS = (
    "session_id",
    "status",
    "pending",
    "escalated",
    "superseded",
    "confirmed_hint",
    "delivery_mode",
    "reason",
    "superseded_reason",
    "attempt",
    "rounds_open",
    "stale_events",
    "compaction_event_id",
    "manifest_sha256",
    "manifest_rel_path",
    "created_at",
    "consumed_at",
    "superseded_at",
    "escalated_at",
    "degraded_at",
    "batch_size",
)


def classify_gate_state(payload: object) -> str:
    """按状态分类单个 gate_state.json 载荷（保守：认不出的一律 unknown→保留）."""
    if not isinstance(payload, dict):
        return "unknown"
    if payload.get("pending"):
        return "pending"
    if payload.get("status") == "degraded":
        return "degraded"
    if payload.get("superseded"):
        return "superseded"
    if payload.get("escalated"):
        return "escalated"
    if payload.get("consumed_at"):
        return "confirmed"
    return "unknown"


def content_digest(payload: dict) -> dict:
    """状态字段投影（原内容摘要）：只取分类与审计相关字段，缺省略."""
    digest = {k: payload[k] for k in _DIGEST_FIELDS if k in payload}
    digest.setdefault("confirmed_hint", bool(payload.get("consumed_at")))
    return digest


def scan_gate_files(snapshots_root: Path) -> list[dict]:
    """只读扫描并分类；返回逐文件记录（含年龄），不触碰任何文件."""
    now = time.time()
    records: list[dict] = []
    if not snapshots_root.is_dir():
        return records
    for state_file in sorted(snapshots_root.glob("*/gate_state.json")):
        rec: dict = {
            "path": state_file,
            "rel_path": state_file.relative_to(snapshots_root.parent).as_posix(),
            "age_hours": None,  # 窄复审 P2-5：stat 失败不中断扫描
            "cls": "unknown",
            "payload": None,
        }
        try:
            raw = state_file.read_bytes()
            rec["age_hours"] = round((now - state_file.stat().st_mtime) / 3600, 1)
            rec["sha256"] = hashlib.sha256(raw).hexdigest()
            payload = json.loads(raw.decode("utf-8"))
            rec["cls"] = classify_gate_state(payload)
            if isinstance(payload, dict):
                rec["payload"] = payload
        except (OSError, ValueError):
            rec["cls"] = "unknown"
        records.append(rec)
    return records


def archive_path(snapshots_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return snapshots_root / f"_migrated-{stamp}.jsonl"


def archived_shas(archive: Path) -> set[str]:
    """幂等键全集（窄复审 P2-5）：扫全部 _migrated-*.jsonl，跨日重跑/跨午夜
    不重复归档已记录 sha。"""
    shas: set[str] = set()
    for archive_file in sorted(archive.parent.glob("_migrated-*.jsonl")):
        if not archive_file.is_file():
            continue
        for line in archive_file.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("sha256"):
                shas.add(row["sha256"])
    return shas


def execute_migration(records: list[dict], snapshots_root: Path) -> dict[str, int]:
    """归档后删除终态类文件（幂等：sha 已在归档则只删不重复归档）."""
    stats = {"archived": 0, "deleted": 0, "delete_skipped_archived": 0, "errors": 0}
    archive = archive_path(snapshots_root)
    known = archived_shas(archive)
    for rec in records:
        if rec["cls"] in KEEP_CLASSES or "sha256" not in rec:
            continue
        try:
            if rec["sha256"] not in known:
                row = {
                    "migrated_at": datetime.now(UTC).isoformat(),
                    "reason_class": rec["cls"],
                    "original_path": rec["rel_path"],
                    "content_digest": content_digest(rec["payload"] or {}),
                    "sha256": rec["sha256"],
                    "evo": "EVO-20261105-7eb1e99f",
                }
                with archive.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                known.add(rec["sha256"])
                stats["archived"] += 1
            else:
                stats["delete_skipped_archived"] += 1
            rec["path"].unlink()
            stats["deleted"] += 1
        except OSError:
            stats["errors"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="data 根目录（默认 <repo>/data）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际归档+删除（默认 dry-run 只读，不写任何文件）",
    )
    args = parser.parse_args(argv)
    snapshots_root = args.data_dir / "compaction_snapshots"
    records = scan_gate_files(snapshots_root)

    keep = [r for r in records if r["cls"] in KEEP_CLASSES]
    purge = [r for r in records if r["cls"] not in KEEP_CLASSES]
    print(f"[migrate-compaction-gates] root={snapshots_root} total={len(records)}")
    by_cls: dict[str, int] = {}
    for r in records:
        by_cls[r["cls"]] = by_cls.get(r["cls"], 0) + 1
    print(f"  分类计数: {json.dumps(by_cls, ensure_ascii=False, sort_keys=True)}")
    print(f"  保留（pending/degraded/unknown）: {len(keep)}")
    for r in keep:
        print(f"    KEEP  {r['cls']:<9} age={r['age_hours']}h {r['rel_path']}")
    print(f"  归档后删除（confirmed/superseded/escalated）: {len(purge)}")
    for r in purge:
        digest = content_digest(r.get("payload") or {})
        print(
            f"    PURGE {r['cls']:<9} age={r['age_hours']}h "
            f"delivery_mode={digest.get('delivery_mode')} sha={r.get('sha256', '?')[:12]} "
            f"{r['rel_path']}"
        )
    if not args.execute:
        print("  [dry-run] 只读模式：未写归档、未删除任何文件（--execute 才会执行）")
        return 0
    stats = execute_migration(records, snapshots_root)
    print(f"  [execute] {json.dumps(stats, ensure_ascii=False, sort_keys=True)}")
    print(f"  归档文件: {archive_path(snapshots_root)}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
