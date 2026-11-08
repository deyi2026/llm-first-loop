"""Peer 任务编排（受控端）：manifest 构建 + 提交/准入/执行/回执。

顺序（本身是安全属性，DESIGN §5.4「先落盘准入、后动作」）：
  1. 形状校验（task-submit）             → ``params_schema_invalid``
  2. 幂等查账（effect_id）               → 同 digest 返回原回执；异 digest ``idempotency_conflict``
  3. 选租约（唯一的 active+未过期+有余量）→ ``grant_not_found``
  4. 闸2/闸3（policy.evaluate）          → 拒绝则落 denied 准入 + denied 任务
  5. 落 submitted 任务 → 落 admitted 准入 → 消耗租约额度（CAS）
  6. queued → running → 执行 → succeeded / failed（失败带封闭 reason_code）
  7. 返回 receipt（形状对齐 receipt.schema.json，additionalProperties=false）

已知边界：
- 首切片同步执行（只读 kind 毫秒级）；HTTP 层不得据此假定可阻塞等待大任务。
- 额度在准入后、动作前消耗；执行崩溃不回滚额度（宁可少用，不可超用）。
- 未实现 ``blocked``（人工确认）状态的生产者，故 ``blocked_timeout`` 回收器留给后续切片。
- 审计写失败一律 ``audit_unavailable`` 拒绝：宁可拒绝执行，不可无审计地执行。
- 中断恢复只做状态收敛（``failed/crashed`` 或 ``unknown_outcome``），绝不自动重跑。
- 监督通道（T9-b）：``supervised_only`` kind 在提交时停在 ``awaiting_supervision``，
  由本机 TTY 逐次确认（``peer.operator``）后才重新准入并执行。HTTP 面没有批准入口。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from .admission import AdmissionStore
from .artifacts import ArtifactStore
from .errors import PeerError
from .executor import ExecOutcome, Executor
from .kinds import EXECUTABLE_KINDS, get_kind, manifest_kinds
from .models import (
    SLOT_STATES,
    AdmissionRecord,
    GrantRecord,
    TaskRecord,
    iso,
    now_local,
    parse_ts,
)
from .operator import OperatorChannel, SupervisionTicket
from .policy import evaluate, precheck
from .suggestions import REASON_SUGGESTIONS

PEER_API = "1"
_SUBMIT_FIELDS = frozenset(
    {
        "schema",
        "effect_id",
        "kind",
        "params",
        "expect",
        "deadline_s",
        "idempotency_hint",
        "artifact_accept",
        "requested_by",
    }
)
_REQUIRED_SUBMIT_FIELDS = frozenset({"schema", "effect_id", "kind", "params", "deadline_s"})
_EXPECT_VALUES = frozenset({"summary", "artifact", "file_effect"})
_GRANT_ID_PREFIX = "gr_"


def params_digest(kind: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"kind": kind, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PeerService:
    def __init__(
        self,
        *,
        store: Any,
        admissions: AdmissionStore,
        artifacts: ArtifactStore,
        node_id: str,
        display_name: str | None = None,
        display_protocol: str = "none",
        role: str = "executor",
        health: str | None = None,
        max_concurrency: int = 1,
        audit_watermark_pct: int = 90,
        enabled_kinds: set[str] | None = None,
        write_root: str | None = None,
        supervision_enabled: bool = False,
        supervision_ttl_s: int = 300,
        clock: Any = now_local,
    ) -> None:
        self._store = store
        self._admissions = admissions
        self._executor = Executor(artifacts=artifacts, node_id=node_id, write_root=write_root)
        self._artifacts = artifacts
        self._node_id = node_id
        self._display_name = display_name
        self._display_protocol = display_protocol
        self._role = role
        self._health_override = health
        self._max_concurrency = int(max_concurrency)
        # 水位只有一处真值：manifest 播报值和 health() 判定必须同源，否则
        # "播报 50 却按 1 判" 就是对端按错阈值排期的隐患。
        self._audit_watermark_pct = max(50, min(99, int(audit_watermark_pct)))
        self._enabled_kinds = enabled_kinds
        self._write_root = write_root
        self._supervision_enabled = bool(supervision_enabled)
        self._supervision_ttl_s = max(1, int(supervision_ttl_s))
        self._operator = OperatorChannel(store.root, clock=clock)
        self._clock = clock
        # manifest 是控制端轮询的读路径，而 OperatorChannel.available() 会
        # mkdir/chmod/write-probe（写文件！）。缓存"最近一次探测"给它用，
        # 写路径（hold/issue/resume）一律 force 重新探测，不吃缓存。
        self._supervision_probe: tuple[float, bool] | None = None

    # ---- 健康 --------------------------------------------------------------
    def health(self) -> str:
        """``ok`` / ``degraded``：显式覆盖优先，否则按 data 分区水位判定。

        判定失败按 ``degraded``（fail-closed：读不出磁盘状态就不宣称健康）。
        degraded 时 manifest 照实播报，且拒绝新任务（``executor_unhealthy``）。
        """
        if self._health_override is not None:
            return self._health_override
        try:
            usage = shutil.disk_usage(self._store.root)
        except OSError:
            return "degraded"
        pct = int(usage.used * 100 / max(1, usage.total))
        return "degraded" if pct >= self._audit_watermark_pct else "ok"

    # ---- 监督通道 ----------------------------------------------------------
    def _supervision_ready(self, *, force: bool = False) -> bool:
        """D5 三条件：开关打开 + 写域已配 + 票据目录可用（可写且属主正确）。

        ``force=False`` 时复用 2s 内的探测结果（manifest 轮询不放大成写盘风暴）；
        ``force=True`` 用于所有真正要签发/消费票据的写路径。
        """
        if not (self._supervision_enabled and self._write_root):
            return False
        now = time.monotonic()
        cached = self._supervision_probe
        if not force and cached is not None and now - cached[0] < 2.0:
            return cached[1]
        ok = self._operator.available()
        self._supervision_probe = (now, ok)
        return ok

    # ---- manifest ---------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        grant = self.active_grant()
        payload: dict[str, Any] = {
            "schema": "lfl.peer.v1",
            "peer_api": PEER_API,
            "node_id": self._node_id,
            "role": self._role,
            "health": self.health(),
            "display_protocol": self._display_protocol,
            "desktop": {
                "screenshot": False,
                "inject_click": False,
                "inject_type": False,
                "focus_probe": False,
            },
            "kinds": manifest_kinds(
                self._enabled_kinds, supervised_ready=self._supervision_ready()
            ),
            "limits": {
                "max_concurrency": max(1, min(16, self._max_concurrency)),
                "audit_watermark_pct": max(50, min(99, self._audit_watermark_pct)),
            },
            "observed_at": iso(self._clock()),
            "grant": self._grant_brief(grant),
        }
        if self._display_name:
            payload["display_name"] = self._display_name
        return payload

    @staticmethod
    def _grant_brief(grant: GrantRecord | None) -> dict[str, Any] | None:
        if grant is None:
            return None
        if not grant.grant_id.startswith(_GRANT_ID_PREFIX):
            return None  # manifest 只播报符合契约形态的 grant_id
        remaining = max(0, int(grant.max_tasks_total) - int(grant.tasks_used))
        return {
            "grant_id": grant.grant_id,
            "expires_at": grant.expires_at,
            "tasks_remaining": remaining,
        }

    # ---- 提交 --------------------------------------------------------------
    def submit(self, payload: dict[str, Any], *, requested_by: str | None = None) -> dict[str, Any]:
        from llm_loop.peer.kinds import KINDS

        # None=按注册表 default_enabled（与 manifest 广播口径一致），非"不限制"。
        enabled = self._enabled_kinds
        if enabled is None:
            enabled = {k for k, spec in KINDS.items() if spec.default_enabled}
        shape = self._validate_submit(payload, enabled_kinds=enabled)
        digest = params_digest(shape["kind"], shape["params"])

        replay = self._store.find_task_by_effect(self._node_id, shape["effect_id"])
        if replay is not None:
            if replay.kind == shape["kind"] and replay.params_digest == digest:
                return self.receipt(replay)
            raise PeerError("idempotency_conflict", f"effect_id reused: {shape['effect_id']}")

        # requested_by 只认认证层注入值：回退到控制端可控的 payload 字段等于身份可伪造。
        return self._submit_new(shape, digest, requested_by=requested_by)

    def _submit_new(
        self, shape: dict[str, Any], digest: str, *, requested_by: str | None
    ) -> dict[str, Any]:
        spec = get_kind(shape["kind"])
        now = iso(self._clock())
        task = TaskRecord(
            task_id=f"task_{uuid.uuid4().hex[:20]}",
            effect_id=shape["effect_id"],
            node_id=self._node_id,
            kind=shape["kind"],
            params=shape["params"],
            expect=tuple(shape.get("expect") or ("summary",)),
            deadline_s=int(shape["deadline_s"]),
            state="submitted",
            idempotency_class=spec.idempotency_class if spec else "non_idempotent",
            supervised_only=bool(spec.supervised_only) if spec else True,
            created_at=now,
            updated_at=now,
            requested_by=requested_by,
            params_digest=digest,
        )

        # D6（独立审查 P1-2，2026-11-08）：O_EXCL 占坑先于一切副作用。
        # 并发同 effect_id 只有一个提交能占坑；后来者等待占坑方落任务并
        # 返回幂等回执（或 fail-closed 冲突），杜绝 check-then-act 双执行。
        claimed = self._store.claim_effect(
            self._node_id, shape["effect_id"], task.task_id, now_iso=now
        )
        if claimed is not None:
            return self._resolve_effect_claim(claimed, shape, digest)

        try:
            return self._submit_claimed(task, shape, digest, spec)
        except OSError:
            # 落盘基础设施失败（如磁盘满）：回滚占坑，允许同 effect_id 重试。
            self._store.release_effect(self._node_id, shape["effect_id"])
            raise

    def _resolve_effect_claim(
        self, claimed_task_id: str, shape: dict[str, Any], digest: str
    ) -> dict[str, Any]:
        import time as _time

        if claimed_task_id:
            for _ in range(50):  # 占坑方 put_task 可能尚未可见：短暂等待
                existing = self._store.get_task(claimed_task_id)
                if existing is not None:
                    if existing.kind == shape["kind"] and existing.params_digest == digest:
                        return self.receipt(existing)
                    raise PeerError(
                        "idempotency_conflict", f"effect_id reused: {shape['effect_id']}"
                    )
                _time.sleep(0.02)
        raise PeerError("idempotency_conflict", f"effect_id already claimed: {shape['effect_id']}")

    def _submit_claimed(
        self, task: TaskRecord, shape: dict[str, Any], digest: str, spec: Any
    ) -> dict[str, Any]:
        now = iso(self._clock())
        # 能力播报 ⊆ 可执行 只约束 manifest（D5），不在提交口一刀切：注册表里
        # 登记但本环境无 handler 的 kind（desktop.*）放行到执行器，由协议闸给出
        # DESIGN §9 T9 要求的具体原因（wayland→unsupported_display_protocol，
        # x11→handler_missing），而不是提前糊成一句 policy_task_kind_not_allowed。
        # 有人在场通道开着才走等待态；关着就走普通路径，让 policy 给出精确原因
        # （租约不许该 kind → policy_task_kind_not_allowed；租约允许但需人确认
        # → requires_supervised_execution）。
        if task.supervised_only and self._supervision_ready(force=True):
            return self._hold_for_supervision(task)
        try:
            grant = self._select_grant()
        except PeerError as exc:
            return self._deny(task, None, exc)
        if self.health() == "degraded":
            return self._deny(
                task, grant, PeerError("executor_unhealthy", "executor health=degraded")
            )
        # submitted 也占并发名额（SLOT_STATES）：只看 running 会让并发闸失效。
        slots = self._slot_count()
        try:
            evaluate(
                kind=shape["kind"],
                params=shape["params"],
                grant=grant,
                supervised=False,
                running_tasks=slots,
                now=self._clock(),
            )
        except PeerError as exc:
            return self._deny(task, grant, exc)

        # 落盘与并发上限在同一次 compare-and-write 内裁决（不是先查后写）。
        try:
            self._store.put_task(task, max_running=grant.max_concurrency)
        except PeerError as exc:
            return self._deny(task, grant, exc, write_audit=True, persist=False)
        try:
            admission = self._write_admission(
                AdmissionRecord(
                    admission_id=f"adm_{uuid.uuid4().hex[:16]}",
                    task_id=task.task_id,
                    node_id=self._node_id,
                    kind=task.kind,
                    effect_id=task.effect_id,
                    verdict="admitted",
                    decided_at=now,
                    params_digest=digest,
                    grant_id=grant.grant_id,
                )
            )
        except PeerError as exc:
            # 审计不可用：动作尚未开始 → 按拒绝收敛，不消耗额度、不执行任何工具
            return self._deny(task, grant, exc, write_audit=False, persist=False)
        task = task.with_updates(admission_id=admission.admission_id, grant_id=grant.grant_id)
        try:
            self._store.consume_grant(grant.grant_id, expected_tasks_used=grant.tasks_used)
        except PeerError as exc:
            failed = self._transition(task, "failed", reason_code=exc.reason_code)
            return self.receipt(failed)

        task = self._transition(task, "admitted")
        task = self._transition(task, "queued")
        task = self._transition(task, "running")
        return self.receipt(self._execute(task))

    def _deny(
        self,
        task: TaskRecord,
        grant: GrantRecord | None,
        exc: PeerError,
        *,
        write_audit: bool = True,
        persist: bool = True,
        decided_by: str = "peer_admission",
    ) -> dict[str, Any]:
        if persist:
            self._store.put_task(task)
        if write_audit:
            try:
                self._write_admission(
                    AdmissionRecord(
                        admission_id=f"adm_{uuid.uuid4().hex[:16]}",
                        task_id=task.task_id,
                        node_id=self._node_id,
                        kind=task.kind,
                        effect_id=task.effect_id,
                        verdict="denied",
                        decided_at=iso(self._clock()),
                        params_digest=task.params_digest or "",
                        grant_id=grant.grant_id if grant else None,
                        reason_code=exc.reason_code,
                        decided_by=decided_by,
                    )
                )
            except PeerError as audit_exc:
                # 审计不可用优先于原拒绝原因：没有审计记录就说不清"为什么拒了"
                exc = audit_exc
        denied = self._transition(task, "denied", reason_code=exc.reason_code)
        return self.receipt(denied)

    def _write_admission(self, record: AdmissionRecord) -> AdmissionRecord:
        """审计落盘失败 → ``audit_unavailable``（不是 500，也不是静默放行）。"""
        try:
            return self._admissions.write(record)
        except OSError as exc:
            raise PeerError("audit_unavailable", f"admission write failed: {exc}") from exc

    def _execute(
        self, task: TaskRecord, *, ticket: SupervisionTicket | None = None
    ) -> TaskRecord:
        grant = self._store.get_grant(task.grant_id) if task.grant_id else None
        allowed_paths = tuple(grant.allowed_paths) if grant else ()
        try:
            if task.supervised_only:
                # 执行前重判（D6 第 5 步）：没有票据就不执行，票据与参数不符也不执行。
                ticket = ticket or self._operator.consume(
                    task.task_id, params_digest=task.params_digest or ""
                )
                if ticket.params_digest != task.params_digest:
                    raise PeerError("supervision_ticket_mismatch", "票据与任务参数摘要不符")
            outcome: ExecOutcome = self._executor.run(
                kind=task.kind,
                params=task.params,
                allowed_paths=allowed_paths,
                display_protocol=self._display_protocol,
            )
        except PeerError as exc:
            return self._transition(task, "failed", reason_code=exc.reason_code)
        except Exception:  # noqa: BLE001 - 未预期异常必须落成可解释失败，不吞成 succeeded
            return self._transition(task, "failed", reason_code="executor_internal_error")
        result: dict[str, Any] = {"summary": outcome.summary[:2000]}
        if outcome.artifacts:
            result["artifacts"] = list(outcome.artifacts)
        return self._transition(task, "succeeded", result=result)

    # ---- 查询/产物（HTTP 面用） -------------------------------------------
    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._store.get_task(task_id)

    def get_task_for(self, node_id: str, task_id: str) -> TaskRecord:
        """回执可见性：请求方（requested_by）或执行节点本人可读，其余按不存在处理。

        T4 实现只比对 ``task.node_id``（= 执行节点），导致跨节点派单方永远读不到
        自己的回执（T5 客户端联调暴露）。这里以服务端权威写入的 requested_by 为准；
        旧数据没有 requested_by 时退化为执行节点，保持单节点自测语义。
        """
        task = self._store.get_task(task_id)
        if task is None or (task.requested_by or task.node_id) != node_id:
            raise PeerError("params_schema_invalid", f"unknown task_id: {task_id}")
        return task

    def read_artifact(self, ref: str) -> bytes:
        return self._artifacts.read(ref)

    def quarantine_artifact(self, ref: str) -> list[TaskRecord]:
        """产物被篡改 → 引用过它的 ``succeeded`` 任务转 ``failed``。

        fail-closed：内容寻址的 ref 与盘上字节不符，说明这份产物不可信；把它
        当成功继续交付等于对外担保了被改过的字节。只收敛本节点任务，不跨节点。
        """
        moved: list[TaskRecord] = []
        for task in self._store.list_tasks(node_id=self._node_id, state="succeeded", limit=10_000):
            result = task.result or {}
            refs = [
                item.get("ref")
                for item in (result.get("artifacts", []) if isinstance(result, dict) else [])
                if isinstance(item, dict)
            ]
            if ref in refs:
                moved.append(
                    self._transition(
                        task,
                        "failed",
                        allow_terminal_rewrite=True,
                        reason_code="artifact_digest_mismatch",
                    )
                )
        return moved

    def artifact_visible_to(self, node_id: str, ref: str) -> bool:
        """只有本请求方任务的回执引用过的 ref 才可见（防按 digest 拉别人产物）。"""
        for task in self._store.list_tasks(limit=10_000):
            if (task.requested_by or task.node_id) != node_id:
                continue
            result = task.result or {}
            for artifact in result.get("artifacts", []) if isinstance(result, dict) else []:
                if artifact.get("ref") == ref:
                    return True
        return False

    # ---- 回执 --------------------------------------------------------------
    def receipt(self, task: TaskRecord) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema": "lfl.peer.v1",
            "task_id": task.task_id,
            "effect_id": task.effect_id,
            "state": task.state,
            "idempotency_class": task.idempotency_class,
            "attempt": max(1, int(task.attempt)),
            "executor": {"node_id": self._node_id, "health": self.health()},
            "observed_at": iso(self._clock()),
        }
        for key in ("admission_id", "grant_id", "reason_code", "blocked_reason", "result"):
            value = getattr(task, key)
            if value is not None:
                receipt[key] = value
        if task.reason_code:
            suggestion = REASON_SUGGESTIONS.get(task.reason_code)
            if suggestion:
                receipt["suggested_next"] = suggestion
        return receipt

    # ---- 内部 --------------------------------------------------------------
    def _transition(
        self,
        task: TaskRecord,
        state: str,
        *,
        allow_terminal_rewrite: bool = False,
        max_running: int | None = None,
        **changes: Any,
    ) -> TaskRecord:
        updated = task.with_updates(state=state, updated_at=iso(self._clock()), **changes)
        return self._store.put_task(
            updated,
            expected_state=task.state,
            allow_terminal_rewrite=allow_terminal_rewrite,
            max_running=max_running,
        )

    def _slot_count(self) -> int:
        total = 0
        for state in SLOT_STATES:
            total += len(self._store.list_tasks(node_id=self._node_id, state=state, limit=10_000))
        return total

    # ---- 监督通道：等待 / 列表 / 确认 / 拒绝 -------------------------------
    def _hold_for_supervision(self, task: TaskRecord) -> dict[str, Any]:
        """D5 第二/三行：能力已宣告但未就绪 → 拒；就绪 → 停在等待确认态。

        提交阶段先做一次"不含是否有人确认"的全部预判，注定失败的任务不占用人的注意力。
        """
        if not self._supervision_ready(force=True):
            return self._deny(
                task, None, PeerError("requires_supervised_execution", task.kind)
            )
        try:
            grant = self._select_grant()
            if self.health() == "degraded":
                raise PeerError("executor_unhealthy", "执行器健康水位不足")
            precheck(
                kind=task.kind,
                params=task.params,
                grant=grant,
                running_tasks=self._slot_count(),
                now=self._clock(),
            )
            self._store.put_task(task, max_running=grant.max_concurrency)
        except PeerError as exc:
            return self._deny(task, None, exc)
        return self.receipt(self._transition(task, "awaiting_supervision"))

    def list_supervised(self) -> list[dict[str, Any]]:
        """本节点等待人工确认的任务；顺带收敛过期等待（懒回收，不依赖常驻定时器）。"""
        self.expire_supervision()
        now = self._clock()
        rows: list[dict[str, Any]] = []
        for task in self._store.list_tasks(
            node_id=self._node_id, state="awaiting_supervision", limit=10_000
        ):
            expires_at = self._supervision_deadline(task)
            rows.append(
                {
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "effect_id": task.effect_id,
                    "params": dict(task.params),
                    "params_digest": task.params_digest,
                    "created_at": task.created_at,
                    "expires_at": iso(expires_at),
                    "remaining_s": max(0, int((expires_at - now).total_seconds())),
                }
            )
        return rows

    def expire_supervision(self) -> list[str]:
        # 不因"当前开关关着"就跳过：上次运行留下的等待态必须能按 TTL 收敛，
        # 否则关掉开关反而让它们变成永不终结的僵尸（独立审查 P2-4）。
        now = self._clock()
        expired: list[str] = []
        for task in self._store.list_tasks(
            node_id=self._node_id, state="awaiting_supervision", limit=10_000
        ):
            deadline = self._supervision_deadline(task)
            if deadline > now:
                continue
            self._operator.discard(task.task_id)
            self._transition(task, "failed", reason_code="supervision_timeout")
            expired.append(task.task_id)
        return expired

    def issue_supervision_ticket(
        self, task_id: str, *, issued_by: str
    ) -> SupervisionTicket:
        """签发票据（本机 CLI 专用）。TTL 取任务 deadline 与全局上限的较小值。"""
        task = self._get_waiting(task_id)
        if not self._supervision_ready(force=True):
            raise PeerError("supervision_channel_unavailable", "监督三条件未同时成立")
        digest = task.params_digest or ""
        try:
            # 未消费且未过期的票据可复用：确认因瞬时前提失败（如 executor_unhealthy）
            # 后重试，不必"先删票再签票"，也不撞 issue 的存在性检查（审查 P2-7）。
            return self._operator.load(task_id, params_digest=digest)
        except PeerError as exc:
            if exc.reason_code == "supervision_ticket_expired":
                self._operator.discard(task_id)
            elif exc.reason_code != "supervision_ticket_missing":
                raise
        return self._operator.issue(
            task_id=task.task_id,
            node_id=task.node_id,
            kind=task.kind,
            params_digest=digest,
            issued_by=issued_by,
            ttl_s=min(int(task.deadline_s), self._supervision_ttl_s),
        )

    def reject_supervised(self, task_id: str, *, decided_by: str) -> dict[str, Any]:
        task = self._get_waiting(task_id)
        self._operator.discard(task_id)
        return self._deny(
            task,
            None,
            PeerError("execution_not_authorized", f"supervision rejected by {decided_by}"),
            persist=False,
            decided_by=decided_by,
        )

    def resume_supervised(self, task_id: str, *, decided_by: str) -> dict[str, Any]:
        """D6：载入票据 → 验未消费/未过期 → 重算 digest → 重判 → 消费 → 执行。

        任务超龄或票据不可用时把等待态收敛为 ``failed`` 并返回回执——
        不让异常穿透到 HTTP/CLI 层（那里只能给 500，说不清"没执行"）。
        """
        task = self._get_waiting(task_id)
        if self._clock() >= self._supervision_deadline(task):
            self._operator.discard(task_id)
            return self._fail_waiting(
                task, PeerError("supervision_timeout", "等待人工确认超龄"), decided_by=decided_by
            )
        grant = self._select_grant()
        if self.health() == "degraded":
            raise PeerError("executor_unhealthy", "执行器健康水位不足")
        precheck(
            kind=task.kind,
            params=task.params,
            grant=grant,
            supervised=self._supervision_ready(force=True),
            running_tasks=self._slot_count(),
            now=self._clock(),
        )
        # 票先验后用：load 只校验存在/未过期/摘要匹配（不搬文件）。真正的一次性消费
        # 放到额度 CAS 与状态转换全部成功之后（_execute 内），避免"票烧了、任务没跑"。
        try:
            self._operator.load(task_id, params_digest=task.params_digest or "")
        except PeerError as exc:
            return self._fail_waiting(task, exc, decided_by=decided_by)
        admission = self._write_admission(
            AdmissionRecord(
                admission_id=f"adm_{uuid.uuid4().hex[:16]}",
                task_id=task.task_id,
                node_id=self._node_id,
                kind=task.kind,
                effect_id=task.effect_id,
                verdict="admitted",
                decided_at=iso(self._clock()),
                params_digest=task.params_digest or "",
                grant_id=grant.grant_id,
                decided_by=decided_by,
            )
        )
        task = task.with_updates(
            admission_id=admission.admission_id,
            grant_id=grant.grant_id,
            policy_decision="admitted",
            lease_expires_at=grant.expires_at,
        )
        # 并发裁决落在 store 的同一临界区（put_task(max_running)），
        # 两个并发确认不会都读到"空槽"然后一起进 running。
        try:
            task = self._transition(task, "admitted", max_running=grant.max_concurrency)
        except PeerError as exc:
            return self.receipt(self._transition(task, "failed", reason_code=exc.reason_code))
        try:
            self._store.consume_grant(grant.grant_id, expected_tasks_used=grant.tasks_used)
        except PeerError as exc:
            return self.receipt(self._transition(task, "failed", reason_code=exc.reason_code))
        task = self._transition(task, "queued")
        task = self._transition(task, "running", max_running=grant.max_concurrency)
        return self.receipt(self._execute(task))

    def _supervision_deadline(self, task: TaskRecord) -> datetime:
        """等待态超龄时刻：进入等待态时落 ``updated_at``，TTL 从那时起算。"""
        return parse_ts(task.updated_at) + timedelta(seconds=self._supervision_ttl_s)

    def _fail_waiting(
        self, task: TaskRecord, exc: PeerError, *, decided_by: str
    ) -> dict[str, Any]:
        """等待态失败：动作未开始，收敛 ``failed``；审计写不进去时优先报审计原因。"""
        code = exc.reason_code
        try:
            self._write_admission(
                AdmissionRecord(
                    admission_id=f"adm_{uuid.uuid4().hex[:16]}",
                    task_id=task.task_id,
                    node_id=self._node_id,
                    kind=task.kind,
                    effect_id=task.effect_id,
                    verdict="denied",
                    decided_at=iso(self._clock()),
                    params_digest=task.params_digest or "",
                    reason_code=code,
                    decided_by=decided_by,
                )
            )
        except PeerError as audit_exc:
            code = audit_exc.reason_code
        failed = self._transition(task, "failed", reason_code=code)
        return self.receipt(failed)

    def _get_waiting(self, task_id: str) -> TaskRecord:
        task = self._store.get_task(task_id)
        if task is None:
            raise PeerError("task_not_found", f"unknown task_id: {task_id}")
        if task.node_id != self._node_id:
            raise PeerError("task_not_found", f"task {task_id} 不属于本节点")
        if task.state != "awaiting_supervision":
            raise PeerError("idempotency_conflict", f"task {task_id} state={task.state}")
        return task

    # ---- 中断恢复 ----------------------------------------------------------
    def recover_interrupted(self) -> list[TaskRecord]:
        """重启恢复：把上次进程留下的中间态收敛到可解释状态，**绝不自动重跑**。

        - ``submitted`` / ``admitted`` / ``queued``：动作尚未开始（``_execute`` 只在 ``running`` 之后调用），
          收敛为 ``failed/crashed``，额度不回滚。``submitted`` 也占并发名额（见 ``SLOT_STATES``），
          不收敛就会永久吃掉一个槽位。
        - ``awaiting_supervision`` **不在此扫描集合**（DESIGN-20261108 D2）：它是副作用
          之前的等待态，重启后保留等待，过期由 ``expire_supervision`` 按 TTL 单独收尾。
          判成 failed 会让"人回来点确认"永远不可能，也违背"只是暂停"的语义。
        - ``running``：幂等只读 kind → ``failed/crashed``；非幂等 → ``unknown_outcome``
          （可能已产生部分副作用，既不能声称失败，也不能声称成功）。

        返回被改写的任务，供启动日志与验收脚本核对。调用方为进程启动路径
        （``scripts/peer_serve.py`` / ``web`` 挂载），不在请求路径上。
        """
        recovered: list[TaskRecord] = []
        for state in ("submitted", "admitted", "queued", "running"):
            for task in self._store.list_tasks(node_id=self._node_id, state=state, limit=10_000):
                if state == "running" and task.idempotency_class != "idempotent":
                    recovered.append(self._transition(task, "unknown_outcome", reason_code="crashed"))
                else:
                    recovered.append(self._transition(task, "failed", reason_code="crashed"))
        return recovered

    def _select_grant(self) -> GrantRecord:
        grants = self._store.list_grants(self._node_id)
        # 只做"挑哪张租约"，不做有效性裁决：撤销/过期/用尽/配额一律交给闸2 判定，
        # 这样 denied 回执里的 reason_code 才是可解释的具体原因（而非笼统的 not_found）。
        usable = [
            g
            for g in grants
            if g.state in ("active", "exhausted") and not g.revoked_at and g.expires_at
        ]
        if not usable:
            # "从没有过租约" 与 "租约被撤" 对控制端是两种动作：后者要停止重试并告警。
            revoked = [g for g in grants if g.revoked_at or g.state == "revoked"]
            if revoked:
                raise PeerError("grant_revoked", f"grant revoked for {self._node_id}")
            raise PeerError("grant_not_found", f"no active grant for {self._node_id}")
        # 多张租约时优先"真能用"的：撤销/过期/用尽仍留在 usable 里，只为 denied 原因可解释。
        # 若把它们排在可执行租约之前，会出现"明明有额度却报 grant_exhausted/expired"。
        live = [g for g in usable if self._selectable(g, self._clock())]
        pool = live or usable
        pool.sort(key=lambda g: g.expires_at)
        return pool[0]

    @staticmethod
    def _selectable(grant: GrantRecord, now: datetime) -> bool:
        """能否被优先选中：未撤销、未过期、额度未用尽；时间戳不可解析按不可用处理。"""
        if grant.state != "active" or grant.revoked_at or not grant.expires_at:
            return False
        try:
            expires_at = parse_ts(grant.expires_at)
        except ValueError:
            return False
        if expires_at <= now:
            return False
        return grant.tasks_used < grant.max_tasks_total

    def active_grant(self) -> GrantRecord | None:
        try:
            return self._select_grant()
        except PeerError:
            return None

    @staticmethod
    def _validate_submit(payload: dict[str, Any], *, enabled_kinds: frozenset[str] | set[str] | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise PeerError("params_schema_invalid", "payload must be an object")
        extra = sorted(set(payload) - _SUBMIT_FIELDS)
        if extra:
            raise PeerError("params_schema_invalid", f"unexpected fields: {extra}")
        missing = sorted(_REQUIRED_SUBMIT_FIELDS - set(payload))
        if missing:
            raise PeerError("params_schema_invalid", f"missing fields: {missing}")
        if payload["schema"] != "lfl.peer.v1":
            raise PeerError("params_schema_invalid", "schema mismatch")
        effect_id = payload["effect_id"]
        # 独立审查第 6 轮 P1-2（2026-11-08）：schema 允许 A-Z 与 ':'，但落盘
        # _safe_name 只收 [a-z0-9-_.]——合法输入会撞未处理 ValueError→500。
        # 服务端在入口收紧到与磁盘一致的字符集（fail-closed 拒绝，回执可解释）。
        effect_id_re = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]{7,127}$")
        if not isinstance(effect_id, str) or not 8 <= len(effect_id) <= 128 or not effect_id_re.fullmatch(effect_id):
            raise PeerError(
                "params_schema_invalid",
                "bad effect_id（须为 ^[a-z0-9][a-z0-9._-]{7,127}$，与磁盘键字符集一致）",
            )
        if not isinstance(payload["kind"], str) or get_kind(payload["kind"]) is None:
            raise PeerError("policy_task_kind_not_allowed", str(payload.get("kind")))
        # 独立审查第 6 轮 P1-1（2026-11-08）：enabled_kinds 不只过滤 manifest
        # 广播，也是服务端准入边界——"广告关了、执行照收"是真实缺口。
        # 边界只对**可执行** kind 生效：注册表里登记但本环境无 handler 的 kind
        # （desktop.*）放行到执行器，由协议闸给出 DESIGN §9 T9 要求的精确原因
        # （wayland→unsupported_display_protocol，x11→handler_missing），
        # 而不是在入口糊成 policy_task_kind_not_allowed。
        kind_name = str(payload["kind"])
        if (
            enabled_kinds is not None
            and kind_name in EXECUTABLE_KINDS
            and kind_name not in enabled_kinds
        ):
            raise PeerError("policy_task_kind_not_allowed", f"kind not enabled: {kind_name}")
        params = payload["params"]
        if not isinstance(params, dict) or len(params) > 32:
            raise PeerError("params_schema_invalid", "params must be an object with <=32 keys")
        deadline = payload["deadline_s"]
        if isinstance(deadline, bool) or not isinstance(deadline, int) or not 5 <= deadline <= 3600:
            raise PeerError("params_schema_invalid", "deadline_s must be int in [5,3600]")
        expect = payload.get("expect") or []
        if not isinstance(expect, list) or len(expect) > 4 or not set(expect) <= _EXPECT_VALUES:
            raise PeerError("params_schema_invalid", f"bad expect: {expect!r}")
        return payload
