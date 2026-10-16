"""--all-pending 扫描：use ledger 中尚无对应打分记录的使用回执。

数据源（只读，绝不修改/隔离这两个账本）：
- <root>/experiences/usage.jsonl（experience-use/v1|v2）
- <root>/data/methods/usage.jsonl（method-use/v1|v2）

去重键（slot 级）：使用回执的 slot_id；无 slot_id 的行（legacy/归属未定）
用合成键 noslot:<kind>:<ref>:<ledger行序>。同 slot 多次提交（修订链）只取
链尾（ledger_seq 最大者）——评价以最新提交为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm_loop.knowledge_score.ledger import KnowledgeScoreLedger
from llm_loop.use_ledger import read_ledger_entries


@dataclass(frozen=True)
class PendingUse:
    """一条待打分的使用回执（含其归属卡片定位信息）。"""

    kind: str  # "experience" | "method"
    ref: str  # experience:<stem> / method:<id>
    use_entry: dict
    slot_key: str
    source_ledger: str
    ledger_seq: int


def _entry_ref(kind: str, row: dict) -> str:
    if kind == "method":
        return str(row.get("method_ref") or "")
    return str(row.get("experience_ref") or row.get("ref") or "")


def _slot_key(kind: str, row: dict, seq_fallback: int) -> str:
    slot = str(row.get("slot_id") or "").strip()
    if slot:
        return slot
    ref = _entry_ref(kind, row)
    return f"noslot:{kind}:{ref}:{seq_fallback}"


def load_use_receipts(root: str | Path) -> list[PendingUse]:
    """读取两侧 use ledger 全部完好回执（含 legacy 行），按文件序展开。"""
    root = Path(root)
    sources = (
        ("experience", root / "experiences" / "usage.jsonl"),
        ("method", root / "data" / "methods" / "usage.jsonl"),
    )
    pending: list[PendingUse] = []
    for kind, path in sources:
        if not path.is_file():
            continue
        for position, row in enumerate(read_ledger_entries(path), start=1):
            if not isinstance(row, dict):
                continue
            ref = _entry_ref(kind, row)
            if not ref:
                continue
            seq = row.get("ledger_seq", position)
            pending.append(
                PendingUse(
                    kind=kind,
                    ref=ref,
                    use_entry=row,
                    slot_key=_slot_key(kind, row, position),
                    source_ledger=str(path),
                    ledger_seq=int(seq or position),
                )
            )
    return pending


def scan_pending(
    root: str | Path,
    *,
    score_ledger: KnowledgeScoreLedger | None = None,
    limit: int | None = None,
) -> list[PendingUse]:
    """有使用回执但尚无对应打分记录（slot 级去重）的条目，旧→新。"""
    root = Path(root)
    if score_ledger is None:
        score_ledger = KnowledgeScoreLedger.for_root(root)
    covered = score_ledger.covered_slot_keys()
    grouped: dict[str, PendingUse] = {}
    order: list[str] = []
    for item in load_use_receipts(root):
        if item.slot_key in covered:
            continue
        if item.slot_key not in grouped:
            order.append(item.slot_key)
        grouped[item.slot_key] = item  # 同 slot 修订链：保留链尾（后见者）
    result = [grouped[key] for key in order]
    if limit is not None and limit >= 0:
        result = result[:limit]
    return result
