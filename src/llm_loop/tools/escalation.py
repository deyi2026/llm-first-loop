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
import hmac
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


# 2026-10-25 红队补洞（P0-5）：审批状态文件曾可被 agent 直接改写（data/audit 在
# 工作区内），agent 自己把 status 改成 approved 即绕过人工审批。签名密钥只存在
# 服务进程内存里，不落盘、不进子进程环境；重启后旧记录因签名不符被忽略，
# 未决请求需重新发起（fail-closed，人工审批本来就是短时交互）。
_STATE_SIGNING_KEY = secrets.token_bytes(32)


def _record_mac(rec: dict) -> str:
    payload = {k: v for k, v in rec.items() if k != "sig"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_STATE_SIGNING_KEY, raw, hashlib.sha256).hexdigest()


def _parse_ts(value: str) -> datetime | None:
    """ISO 时间解析；naive 时间按本地时区补齐（防 naive/aware 比较 TypeError）."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=system_local_now().tzinfo)
    return dt


def _public(rec: dict) -> dict:
    """对外视图（剥除令牌——令牌只回给请求方 wait 结果，永不经 web 面板）."""
    out = dict(rec)
    out.pop("token", None)
    # P0-5 展示-审批绑定字段兜底：旧记录缺 command_sha256/command_len 时按
    # command 原文派生（sha256 确定性，读时派生与写时一致），web 端无需特判。
    command = out.get("command")
    if isinstance(command, str):
        if not out.get("command_sha256"):
            out["command_sha256"] = hashlib.sha256(command.encode("utf-8")).hexdigest()
        if not isinstance(out.get("command_len"), int):
            out["command_len"] = len(command)
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
        valid: list[dict] = []
        dropped = 0
        for rec in data:
            if isinstance(rec, dict) and hmac.compare_digest(
                str(rec.get("sig") or ""), _record_mac(rec)
            ):
                valid.append(rec)
            else:
                dropped += 1
        if dropped:
            logger.warning(
                "escalation 状态含 %d 条未签名/签名不符记录，已忽略（防手工伪造审批）", dropped
            )
        return valid

    def _save(self, records: list[dict]) -> None:
        self._private_parent()
        for rec in records:
            if isinstance(rec, dict):
                rec["sig"] = _record_mac(rec)
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
        """创建提权申请（同会话同命令的 pending 请求幂等复用）.

        哈希基准契约：``command`` 即令牌绑定的**精确命令文本**（SHA256，改一字符即废）。
        argv 结构化执行类申请**必须提交 ``shlex.join(argv)`` 规范化文本**——上游
        ``execute_command.py`` 以 ``shlex.join(argv)`` 为守卫与令牌校验的统一哈希
        基准；此处若提交其他拼法（如手工空格拼接、repr、json），审批落库的哈希
        与执行侧实际基准不一致，令牌在 consume/consume_for_execution 时必然校验
        失败（fail-closed，放行永远不会发生，只是浪费一轮人工审批）。
        """
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
                "command_len": len(command),  # P0-5 展示-审批绑定（截断展示时 UI 可对齐真实长度）
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
        decided_by: str = "",
        note: str = "",
        ttl_minutes: int = 10,
        expected_sha256: str = "",
        channel: str = "",
    ) -> tuple[dict | None, str]:
        """人工决定（仅 pending 可决；approved 铸造一次性令牌 + TTL）.

        P0-5（安全审查建议书 2026-10-25 S0-2）:
        - decided_by / channel 由调用方**服务端派生**后传入（web 端点按
          浏览器会话/回环派生；本层不猜来源，缺省空串如实留空，不再伪造
          "web_panel" 假身份）。
        - expected_sha256: 展示-审批绑定（防 TOCTOU）。非空时必须等于记录的
          command_sha256，否则拒绝（stale_review）。为空 = 旧调用方兼容：
          内部用记录自身 sha 填充（等价于对当前记录自证；不放宽 web 端点
          "必填且一致"的校验）。
        """
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
                rec_sha = str(r.get("command_sha256") or "")
                expected = (expected_sha256 or "").strip().lower()
                if not expected:
                    expected = rec_sha.lower()  # 旧调用方兼容：以记录自身 sha 填充
                if expected != rec_sha.lower():
                    reason = (
                        "stale_review: expected_sha256 与待审记录的 command_sha256 不一致"
                        "（展示-审批绑定失败，请重新打开详情后再审批）"
                    )
                    return records
                r["status"] = decision
                r["decided_at"] = _now()
                r["decided_by"] = decided_by
                r["decision_channel"] = channel
                r["decision_note"] = note[:1000]
                if decision == "approved":
                    r["token"] = secrets.token_urlsafe(24)
                    r["token_expires_at"] = (
                        system_local_now() + timedelta(minutes=max(1, int(ttl_minutes)))
                    ).isoformat()
                result = r
                self._log(
                    "decided",
                    r,
                    {"decision": decision, "note": note[:300], "decided_by": decided_by, "channel": channel},
                )
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
        """消耗一次性令牌（成功 = 本次灾难层放行；失败给出精确原因）.

        ``command`` 口径与 create() 契约一致：argv 类申请传 ``shlex.join(argv)``。
        """
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
                exp_dt = _parse_ts(exp)
                if exp_dt is None:
                    # 过期时间戳格式损坏不阻断消费：跳过过期判定，由下方工具名/命令哈希强绑定校验兜底（fail-closed 不依赖该字段）
                    pass
                elif exp_dt < system_local_now():
                    hit["status"] = "expired"
                    self._log("token_expired", hit)
                    reason = f"令牌已过期（{exp}）"
                    return records
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

    # ── P2-3（安全建议书 2026-10-25）: 执行侧三重绑定消费 ──

    def consume_for_execution(
        self, escalation_id: str, token: str, command_sha256: str
    ) -> tuple[dict | None, str]:
        """按 (提权请求 id, 令牌, 命令哈希) 三重绑定校验并一次性消费令牌.

        与既有 consume() 的差异（既有方法语义不变，registry 层继续使用）:
        - 显式绑定 escalation_id：拿 A 记录的令牌无法冒充 B 记录（consume 只按
          令牌反查，本方法要求 id 与令牌同源同记录）；
        - 直接以调用方算好的 command_sha256 对账——argv 结构化执行模式下哈希
          基准为 shlex.join(argv) 的字符串（与 create() 时登记的文本对齐）。

        校验链: 请求存在 → 令牌与记录匹配（constant-time）→ 未使用 →
        决定为 approved → 未过期 → 命令哈希一致。任一失败：记录不变、阻断
        保持，返回**可对外**的精确原因（不含令牌本体）。成功：记录置
        consumed（单次有效）并追加 token_consumed 审计（via 字段区分通道）。
        """
        escalation_id = str(escalation_id or "").strip()
        token = str(token or "")
        want_sha = str(command_sha256 or "").strip().lower()
        if not escalation_id or not token or not want_sha:
            return None, "提权参数不完整（escalation_id / token / command_sha256 均不可为空）"

        result: dict | None = None
        reason = ""

        def _fn(records: list[dict]) -> list[dict]:
            nonlocal result, reason
            hit = next((r for r in records if r.get("id") == escalation_id), None)
            if hit is None:
                reason = f"提权请求不存在: {escalation_id}"
                return records
            stored_token = str(hit.get("token") or "")
            if not stored_token or not secrets.compare_digest(stored_token, token):
                reason = "令牌与提权请求不匹配（不泄露令牌本体）"
                return records
            if hit.get("status") == "consumed":
                reason = "令牌已使用过（单次有效）"
                return records
            if hit.get("status") != "approved":
                reason = f"请求决定状态为 {hit.get('status')}，非 approved"
                return records
            exp = str(hit.get("token_expires_at") or "")
            if exp:
                exp_dt = _parse_ts(exp)
                if exp_dt is None:
                    # 与 consume() 同语义：过期字段损坏不单独放行/阻断，
                    # 由上方状态判定与下方命令哈希强绑定兜底（fail-closed）。
                    pass
                elif exp_dt < system_local_now():
                    hit["status"] = "expired"
                    self._log("token_expired", hit)
                    reason = f"令牌已过期（{exp}）"
                    return records
            if str(hit.get("command_sha256") or "").lower() != want_sha:
                reason = "命令与审批时不一致（令牌绑定批准时的精确命令文本，不可移植）"
                return records
            hit["status"] = "consumed"
            hit["consumed_at"] = _now()
            self._log("token_consumed", hit, {"via": "consume_for_execution"})
            result = hit
            return records

        self._mutate(_fn)
        return (_public(result) if result is not None else None), reason
