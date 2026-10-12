"""提权闭环 EscalationStore（用户需求 2026-09-23 + EVO-20260923-c58a0bb1 配套）.

灾难性安全硬阻断（CatastrophicGuard / FR-SAFE-01）保持程序级 fail-closed，
但**确属必要**的被阻断操作新增人工提权通道，形成闭环:

    AI: escalation_request(command, justification)
      → 写 pending 请求（先验证该命令确实会被硬阻断，防通道滥用）
    Web 面板: 弹窗展示命令原文 + 理由 → 人工 批准/拒绝
      → decide() 落决定；批准时铸造一次性令牌（TTL 默认 10 分钟）
    AI: escalation_wait(request_id) 轮询等待决定（无需用户手动转述）
      → 批准 → 返回令牌；拒绝 → 返回理由
    AI: execute_command(command, escalation_token=<令牌>)
      → registry 灾难层 consume() 校验（令牌绑定工具名 + 命令 SHA256，
        单次使用、过期即废）→ 通过则放行本次，并落审计事件

边界纪律（与 T5a 一致）:
- 提权只绕过**灾难性硬阻断**这一层；EXEC_MODE 分级、共享服务控制权
  （managed_service_guard）等独立边界不受令牌影响，仍按各自规则裁决。
- 令牌不可移植: 绑定批准时的精确命令文本（SHA256），改一个字符即废。
- 全量审计: 创建/决定/消耗/过期均追加 escalation_log.jsonl。

并发: 文件级 flock + 进程内 threading.Lock 双保险（web 线程与引擎线程
可能同进程也可能跨进程，flock 覆盖跨进程，threading.Lock 覆盖同进程
同文件描述符语义差异）。原子写: 临时文件 + os.replace。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import secrets
import stat
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

_PROC_LOCK = threading.Lock()

_STATUS_FLOW = {"pending", "approved", "denied", "consumed", "expired"}


def _now() -> str:
    return system_local_now().isoformat()


def _public(rec: dict) -> dict:
    """对外视图（剥除令牌——令牌只回给请求方 wait 结果，永不经 web 面板）。"""
    out = dict(rec)
    out.pop("token", None)
    return out


class EscalationStore:
    """提权请求/决定/令牌的持久存储（data/audit/escalation_requests.json）."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(".lock")
        self._log_path = self._path.parent / "escalation_log.jsonl"

    # ── 基础 IO ──
    @staticmethod
    def _private_fd(path: Path, flags: int) -> int:
        """Open only an owner-controlled, non-symlink file, mode 0600.

        Pre-existing 0644 records are repaired on the opened inode before
        reading their potentially live approval token.
        """
        fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
            ):
                raise PermissionError("escalation file ownership/type invalid")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _private_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        info = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o022
        ):
            raise PermissionError("escalation audit directory not owner-controlled")

    def _load(self) -> list[dict]:
        try:
            fd = self._private_fd(self._path, os.O_RDONLY)
        except FileNotFoundError:
            return []
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            raw = f.read()
        try:
            data = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("escalation state corrupt; refusing overwrite") from exc
        if not isinstance(data, list):
            raise ValueError("escalation state not a list; refusing overwrite")
        return data

    def _save(self, records: list[dict]) -> None:
        self._private_parent()
        # Explicit O_EXCL | O_NOFOLLOW durable-create primitive is both
        # race-safe and visible to the repository durability-write scanner.
        tmp = self._path.with_name(
            f".{self._path.name}.{secrets.token_hex(16)}.tmp"
        )
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(records, ensure_ascii=False, indent=1))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        finally:
            tmp.unlink(missing_ok=True)

    def _log(self, event: str, rec: dict, extra: dict | None = None) -> None:
        try:
            self._private_parent()
            line = {
                "ts": _now(),
                "event": event,
                "id": rec.get("id", ""),
                "tool_name": rec.get("tool_name", ""),
                "command_sha256": rec.get("command_sha256", ""),
                "status": rec.get("status", ""),
            }
            if extra:
                line.update(extra)
            with os.fdopen(
                self._private_fd(self._log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT),
                "a", encoding="utf-8",
            ) as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("提权审计写失败（不影响主流程）", exc_info=True)

    def _mutate(self, fn) -> list[dict]:
        """锁内 读-改-写（flock 跨进程 + 进程锁跨线程）。"""
        self._private_parent()
        with _PROC_LOCK, os.fdopen(
            self._private_fd(self._lock_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT),
            "a", encoding="utf-8",
        ) as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                records = self._load()
                records = fn(records) or records
                self._save(records)
                return records
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    # ── 对外 API ──
    def create(
        self,
        *,
        tool_name: str,
        command: str,
        justification: str,
        session_id: str = "",
        requested_by: str = "ai",
    ) -> dict:
        """创建提权申请（同会话同命令的 pending 请求幂等复用）。"""
        sha = hashlib.sha256(command.encode("utf-8")).hexdigest()
        created: dict | None = None

        def _fn(records: list[dict]) -> list[dict]:
            nonlocal created
            for r in records:
                if (
                    r.get("status") == "pending"
                    and r.get("command_sha256") == sha
                    and r.get("session_id") == session_id
                ):
                    created = r
                    return records  # 幂等复用已有 pending
            rid = "ESC-" + system_local_now().strftime("%Y%m%d") + "-" + secrets.token_hex(4)
            rec = {
                "id": rid,
                "tool_name": tool_name,
                "command": command,
                "command_sha256": sha,
                "justification": justification[:2000],
                "session_id": session_id,
                "requested_by": requested_by,
                "status": "pending",
                "created_at": _now(),
                "decided_at": "",
                "consumed_at": "",
                "decided_by": "",
                "decision_note": "",
                "token": "",
                "token_expires_at": "",
            }
            records.append(rec)
            created = rec
            self._log("request_created", rec)
            return records

        self._mutate(_fn)
        if created is not None:
            return _public(created)
        return {"status": "pending", "command_sha256": sha, "session_id": session_id}

    def get(self, rid: str) -> dict | None:
        for r in self._load():
            if r.get("id") == rid:
                return r
        return None

    def list(self, status: str = "", limit: int = 50) -> list[dict]:
        out = []
        for r in reversed(self._load()):  # 新→旧
            if status and r.get("status") != status:
                continue
            out.append(_public(r))
            if len(out) >= limit:
                break
        return out

    def pending_count(self) -> int:
        return sum(1 for r in self._load() if r.get("status") == "pending")

    def decide(
        self,
        rid: str,
        decision: str,
        *,
        decided_by: str = "web_panel",
        note: str = "",
        ttl_minutes: int = 10,
    ) -> tuple[dict | None, str]:
        """人工决定（仅 pending 可决；approved 铸造一次性令牌 + TTL）。"""
        if decision not in ("approved", "denied"):
            return None, f"非法决定值: {decision}"

        result: dict | None = None
        reason = ""

        def _fn(records: list[dict]) -> list[dict]:
            nonlocal result, reason
            for r in records:
                if r.get("id") != rid:
                    continue
                if r.get("status") != "pending":
                    reason = f"请求当前状态为 {r.get('status')}，仅 pending 可审批"
                    return records
                r["status"] = decision
                r["decided_at"] = _now()
                r["decided_by"] = decided_by
                r["decision_note"] = note[:1000]
                if decision == "approved":
                    r["token"] = secrets.token_urlsafe(24)
                    r["token_expires_at"] = (
                        system_local_now() + timedelta(minutes=max(1, int(ttl_minutes)))
                    ).isoformat()
                result = r
                self._log("decided", r, {"decision": decision, "note": note[:300]})
                return records
            reason = f"请求不存在: {rid}"
            return records

        self._mutate(_fn)
        return (_public(result) if result is not None else None), reason

    def wait_for_decision(self, rid: str, timeout_s: float, poll_s: float = 2.0) -> dict | None:
        """轮询等待决定（AI 侧闭环接收——批准/拒绝/超时返回当前态）。"""
        deadline = time.monotonic() + max(0.0, timeout_s)
        interval = max(0.5, min(poll_s, 2.0))
        while True:
            rec = self.get(rid)
            if rec is None or rec.get("status") != "pending":
                return rec
            if time.monotonic() >= deadline:
                return rec
            time.sleep(interval)

    def consume(self, token: str, tool_name: str, command: str) -> tuple[dict | None, str]:
        """消耗一次性令牌（成功 = 本次灾难层放行；失败给出精确原因）。"""
        sha = hashlib.sha256(command.encode("utf-8")).hexdigest()

        result: dict | None = None
        reason = ""

        def _fn(records: list[dict]) -> list[dict]:
            nonlocal result, reason
            hit = next((r for r in records if r.get("token") and r.get("token") == token), None)
            if hit is None:
                reason = "令牌不存在（或从未批准）"
                return records
            if hit.get("status") == "consumed":
                reason = f"令牌已使用过（单次有效，请求 {hit.get('id')}）"
                return records
            if hit.get("status") != "approved":
                reason = f"请求状态为 {hit.get('status')}，非 approved"
                return records
            exp = str(hit.get("token_expires_at") or "")
            if exp:
                try:
                    if datetime.fromisoformat(exp) < system_local_now():
                        hit["status"] = "expired"
                        self._log("token_expired", hit)
                        reason = f"令牌已过期（{exp}）"
                        return records
                except ValueError:
                    pass
            if hit.get("tool_name") != tool_name:
                reason = f"令牌绑定的工具是 {hit.get('tool_name')}，不是 {tool_name}"
                return records
            if hit.get("command_sha256") != sha:
                reason = "命令与审批时不一致（令牌绑定批准时的精确命令文本，不可移植）"
                return records
            hit["status"] = "consumed"
            hit["consumed_at"] = _now()
            self._log("token_consumed", hit, {"tool_name_at_use": tool_name})
            result = hit
            return records

        self._mutate(_fn)
        return (_public(result) if result is not None else None), reason
