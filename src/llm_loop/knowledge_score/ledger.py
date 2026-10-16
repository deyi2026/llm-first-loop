"""独立打分明细账本: data/knowledge_scores/ledger.jsonl.

写入纪律复用 use_ledger.py 的**公开**原语（append_ledger_line /
ensure_appendable_tail / read_ledger_entries——单行 JSON + 行级完整性凭据
+ fsync + torn-tail 先隔离再追加），本模块补齐：
- 自持目录级 flock 单写者锁（.score.lock，模式对齐 experiences/store.py
  _file_lock 的跨进程临界区纪律，但不 import 其私有实现）
- ledger_seq 单调水位（先数行后追加，锁内完成）
- 行构造器（成功行 / error 行），schema 字符串 "knowledge-score/v1"
- latest_writeback_failed（P2-5）：识别「打分成功仅写回失败」的 slot
  （按最新行判定），供 CLI 重跑只补写回 sidecar、不重打分

行字段（成功行）: schema/ts/scorer_model/kind/ref/version/slot_id/slot_key/
decision_reported/top_level/top_label/expected/confidence/
p_evidence_sufficient/probabilities/adopted/writeback_target/ledger_seq/
integrity。error 行同骨架，error 字段载明原因、adopted=false、
writeback_target 为空。
"""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path

from llm_loop.timekeeping import system_local_now
from llm_loop.use_ledger import (
    append_ledger_line,
    count_valid_lines,
    ensure_appendable_tail,
    read_ledger_entries,
)

SCHEMA_KNOWLEDGE_SCORE = "knowledge-score/v1"
# P2-5: 「打分成功、仅写回 sidecar 失败」行的 error 前缀——CLI 写回失败时
# 按此前缀落账，latest_writeback_failed 按此前缀识别补写回目标。
WRITEBACK_FAILED_PREFIX = "writeback failed"
_LOCK_FILENAME = ".score.lock"
_PROCESS_LOCK = threading.RLock()


@contextmanager
def _dir_lock(directory: Path):
    """目录级单写者锁（POSIX flock + 进程内 RLock；锁失败 fail-closed）。"""
    directory.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        if fcntl is None:  # 非 POSIX 运行时退化：仅进程内互斥
            yield
            return
        handle = None
        try:
            handle = (directory / _LOCK_FILENAME).open("a", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise RuntimeError(f"score ledger lock unavailable: {exc}") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


class KnowledgeScoreLedger:
    """打分明细账本（路径默认 <root>/data/knowledge_scores/ledger.jsonl）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.dir = self.path.parent

    @classmethod
    def for_root(cls, root: str | Path) -> KnowledgeScoreLedger:
        return cls(Path(root) / "data" / "knowledge_scores" / "ledger.jsonl")

    def append(self, entry: dict) -> dict:
        """锁内原子追加一行（补 ledger_seq + 行级完整性凭据 + fsync）。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        with _dir_lock(self.dir):
            ensure_appendable_tail(self.path)
            row = dict(entry)
            row.setdefault("schema", SCHEMA_KNOWLEDGE_SCORE)
            row.setdefault("ts", system_local_now().isoformat())
            row["ledger_seq"] = count_valid_lines(self.path) + 1
            return append_ledger_line(self.path, row)

    def read(self) -> list[dict]:
        """读取全部完好条目（旧→新）；损坏行留给 append 前的隔离守卫。"""
        return read_ledger_entries(self.path)

    def covered_slot_keys(self) -> set[str]:
        """已有成功打分记录的 slot_key 集合（error 行不算——允许重试）。"""
        keys: set[str] = set()
        for row in self.read():
            if str(row.get("error") or ""):
                continue
            key = str(row.get("slot_key") or row.get("slot_id") or "")
            if key:
                keys.add(key)
        return keys

    def latest_writeback_failed(self) -> dict[str, dict]:
        """slot_key → 该 slot 最新行且为「打分成功仅写回失败」的行（P2-5）。

        语义（自定，写清）: 只认「同 slot 最新一行 error 以
        WRITEBACK_FAILED_PREFIX 开头、且带完整打分结果（top_level ≥ 0 且
        probabilities 非空）」的 slot——即打分已成功落账、但从未成功写回过
        sidecar 的项。更早的写回失败行被后续成功行自然覆盖（后见者为准），
        避免旧结果回退覆盖新打分。返回结果供 CLI 重跑时仅补写回、不重打分。
        """
        latest: dict[str, dict] = {}
        for row in self.read():
            key = str(row.get("slot_key") or row.get("slot_id") or "")
            if key:
                latest[key] = row  # 后见者覆盖：每 slot 只看最新行
        pending: dict[str, dict] = {}
        for key, row in latest.items():
            top = row.get("top_level")
            probs = row.get("probabilities")
            if not str(row.get("error") or "").startswith(WRITEBACK_FAILED_PREFIX):
                continue
            if not isinstance(top, int) or top < 0:
                continue
            if not isinstance(probs, dict) or not probs:
                continue
            pending[key] = row
        return pending


def build_success_entry(
    *,
    scorer_model: str,
    kind: str,
    ref: str,
    version: str,
    slot_id: str,
    slot_key: str,
    decision_reported: str,
    top_level: int,
    top_label: str,
    expected: float,
    confidence: float,
    p_evidence_sufficient: float,
    probabilities: dict,
    adopted: bool,
    writeback_target: str = "",
    error: str = "",
) -> dict:
    return {
        "schema": SCHEMA_KNOWLEDGE_SCORE,
        "ts": system_local_now().isoformat(),
        "scorer_model": str(scorer_model or ""),
        "kind": str(kind or ""),
        "ref": str(ref or ""),
        "version": str(version or ""),
        "slot_id": str(slot_id or ""),
        "slot_key": str(slot_key or ""),
        "decision_reported": str(decision_reported or ""),
        "top_level": int(top_level),
        "top_label": str(top_label or ""),
        "expected": float(expected),
        "confidence": float(confidence),
        "p_evidence_sufficient": float(p_evidence_sufficient),
        "probabilities": {str(k): float(v) for k, v in probabilities.items()},
        "adopted": bool(adopted),
        "writeback_target": str(writeback_target or ""),
        "error": str(error or ""),
    }


def build_error_entry(
    *,
    scorer_model: str,
    kind: str,
    ref: str,
    version: str,
    slot_id: str,
    slot_key: str,
    decision_reported: str,
    error: str,
) -> dict:
    entry = build_success_entry(
        scorer_model=scorer_model,
        kind=kind,
        ref=ref,
        version=version,
        slot_id=slot_id,
        slot_key=slot_key,
        decision_reported=decision_reported,
        top_level=-1,
        top_label="",
        expected=0.0,
        confidence=0.0,
        p_evidence_sufficient=0.0,
        probabilities={},
        adopted=False,
        writeback_target="",
        error=error,
    )
    return entry
