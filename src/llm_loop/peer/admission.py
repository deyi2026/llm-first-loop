"""不可变准入记录（副作用前落盘）。

设计 §5.7 闸序：``闸1 认证 → 闸2 策略 → 闸3 授权 → 准入落盘 → 执行 → 回执``。
admission 文件用 ``O_EXCL`` 创建：同一 task_id 只能有一个结论，重复写入必须失败而不是覆盖
（覆盖会让"已拒绝"被改写成"已准入"，是审计绕过）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import AdmissionRecord

_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789-_."


class AdmissionStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "admissions"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not task_id or len(task_id) > 128 or any(ch not in _SAFE for ch in task_id):
            raise ValueError(f"非法 task_id: {task_id!r}")
        return self.dir / f"{task_id}.json"

    def write(self, record: AdmissionRecord) -> AdmissionRecord:
        path = self._path(record.task_id)
        payload = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = self.get_by_task(record.task_id)
            if existing is not None and existing.to_dict() == record.to_dict():
                return existing
            raise PeerError("idempotency_conflict", f"admission 已存在: {record.task_id}") from None
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return record

    def get_by_task(self, task_id: str) -> AdmissionRecord | None:
        try:
            raw = json.loads(self._path(task_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise PeerError("executor_internal_error", f"admission 不可读: {exc}") from exc
        return AdmissionRecord.from_dict(raw)

    def count_admitted(self) -> int:
        """已准入次数（≈ 执行尝试次数，单调不减）。

        由审计目录派生而不另起计数器：单一真值，不会与审计漂移。读不出的记录
        按"已准入"计（fail-closed：宁可高报执行次数，也不让一次执行从统计里消失）。
        """
        total = 0
        for path in self.dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                total += 1
                continue
            if raw.get("verdict") == "admitted":
                total += 1
        return total

    def get(self, admission_id: str) -> AdmissionRecord | None:
        for path in self.dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PeerError("executor_internal_error", f"admission 不可读: {exc}") from exc
            if raw.get("admission_id") == admission_id:
                return AdmissionRecord.from_dict(raw)
        return None
