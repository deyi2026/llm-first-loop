"""打分结果写回——sidecar 方案（version 调查结论，见交付报告）。

调查结论：卡片 version = 整文件内容哈希（经验卡 _payload_sha256(doc.to_md())、
方法卡 sha256(METHOD.md raw)），slot_id/回执抵扣/usage_feedback 的
current_version 匹配全部依赖该哈希。写回 front matter 会改变 version，
使既有回执全部退化为 stale_after_card_edit / no_current_version_match——
破坏回执对应关系。因此选择 sidecar：

    data/knowledge_scores/cards/<卡slug>.json

同字段更新（last_scored_at/scorer_model/top_level/top_label/expected/
confidence/p_evidence_sufficient/probabilities/evidence_level:
independently_evaluated），附有界 history（cap=8，P2-5(b) 按 slot_id
去重：同 slot 重打分更新条目而非追加；不同 slot 各占一条）。webui 后续
从 sidecar join 展示；卡片文件零触碰。

写回纪律（自持实现，不 import store.py 私有函数）：目录 flock 单写者 +
tmp 文件独占创建 + 原子 rename + 目录 fsync。
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from llm_loop.timekeeping import system_local_now

SIDECAR_SCHEMA = "knowledge-score-sidecar/v1"
HISTORY_CAP = 8
_LOCK_FILENAME = ".cards.lock"
_PROCESS_LOCK = threading.RLock()


@contextmanager
def _dir_lock(directory: Path):
    """目录级单写者锁（POSIX flock + 进程内 RLock；失败 fail-closed）。"""
    directory.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        if fcntl is None:
            yield
            return
        handle = None
        try:
            handle = (directory / _LOCK_FILENAME).open("a", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise RuntimeError(f"sidecar lock unavailable: {exc}") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def sidecar_path(cards_dir: str | Path, slug: str) -> Path:
    """sidecar 路径；slug 只禁路径分隔符/前导点，保留 CJK（经验卡 stem 含中文）。"""
    safe = str(slug or "").replace("/", "-").replace("\\", "-").lstrip(".")
    if not safe:
        raise ValueError(f"invalid card slug: {slug!r}")
    return Path(cards_dir) / f"{safe}.json"


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp_exclusive(target: Path, payload: str) -> Path:
    """独占创建 tmp 文件并 fsync；目标目录内完成，rename 原子生效。"""
    tmp = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_sidecard(
    cards_dir: str | Path,
    *,
    card,
    result,
    slot_id: str = "",
    use_ts: str = "",
) -> dict:
    """写回/更新一张卡的 sidecar（幂等：同卡更新而非堆积重复块；history
    按 slot_id 去重——同 slot 重打分只更新该 slot 的条目，cap 不变）。

    仅在采纳判定通过后由调用方调用（p_evidence_sufficient ≥ 0.5 且
    confidence ≥ 0.5）；不满足时调用方只落 ledger、卡片与 sidecar 均不动。
    """
    cards_dir = Path(cards_dir)
    target = sidecar_path(cards_dir, card.slug)
    cards_dir.mkdir(parents=True, exist_ok=True)
    now = system_local_now().isoformat()
    with _dir_lock(cards_dir):
        existing = _read_json(target)
        history = [
            h for h in existing.get("history", []) if isinstance(h, dict)
        ]
        # P2-5(b): history 按 slot_id 去重——同 slot 重打分时更新该条目而非
        # 追加（无 slot_id 的 legacy 行不参与去重，保持逐条追加）。
        dedup_slot = str(slot_id or "")
        if dedup_slot:
            history = [
                h for h in history if str(h.get("slot_id") or "") != dedup_slot
            ]
        history.append(
            {
                "ts": now,
                "slot_id": str(slot_id or ""),
                "use_ts": str(use_ts or ""),
                "top_level": int(result.top_level),
                "expected": round(float(result.expected), 4),
                "confidence": round(float(result.confidence), 4),
                "p_evidence_sufficient": round(
                    float(result.p_evidence_sufficient), 4
                ),
            }
        )
        payload = {
            "schema": SIDECAR_SCHEMA,
            "kind": card.kind,
            "ref": card.ref,
            "card_version_at_scoring": card.version,
            "last_scored_at": now,
            "scorer_model": result.model,
            "top_level": int(result.top_level),
            "top_label": result.top_label,
            "expected": round(float(result.expected), 4),
            "confidence": round(float(result.confidence), 4),
            "p_evidence_sufficient": round(
                float(result.p_evidence_sufficient), 4
            ),
            "probabilities": {
                str(k): round(float(v), 4) for k, v in result.probabilities.items()
            },
            "evidence_level": "independently_evaluated",
            "scored_slots": len(history),
            "history": history[-HISTORY_CAP:],
        }
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        tmp = _write_temp_exclusive(target, body)
        try:
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        _fsync_directory(cards_dir)
    return payload
