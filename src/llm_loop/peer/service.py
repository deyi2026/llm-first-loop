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
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from typing import Any

from .admission import AdmissionStore
from .artifacts import ArtifactStore
from .errors import PeerError
from .executor import ExecOutcome, Executor
from .kinds import get_kind, manifest_kinds
from .models import AdmissionRecord, GrantRecord, TaskRecord, iso, utcnow
from .policy import evaluate
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
        clock: Any = utcnow,
    ) -> None:
        self._store = store
        self._admissions = admissions
        self._executor = Executor(artifacts=artifacts, node_id=node_id)
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
        self._clock = clock

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
            "kinds": manifest_kinds(self._enabled_kinds),
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

        return self._submit_new(shape, digest, requested_by=requested_by or shape.get("requested_by"))

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
        try:
            grant = self._select_grant()
        except PeerError as exc:
            return self._deny(task, None, exc)
        if self.health() == "degraded":
            return self._deny(
                task, grant, PeerError("executor_unhealthy", "executor health=degraded")
            )
        running = self._running_count()
        try:
            evaluate(
                kind=shape["kind"],
                params=shape["params"],
                grant=grant,
                supervised=False,
                running_tasks=running,
                now=self._clock(),
            )
        except PeerError as exc:
            return self._deny(task, grant, exc)

        self._store.put_task(task)
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

    def _execute(self, task: TaskRecord) -> TaskRecord:
        grant = self._store.get_grant(task.grant_id) if task.grant_id else None
        allowed_paths = tuple(grant.allowed_paths) if grant else ()
        try:
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
        self, task: TaskRecord, state: str, *, allow_terminal_rewrite: bool = False, **changes: Any
    ) -> TaskRecord:
        updated = task.with_updates(state=state, updated_at=iso(self._clock()), **changes)
        return self._store.put_task(
            updated, expected_state=task.state, allow_terminal_rewrite=allow_terminal_rewrite
        )

    def _running_count(self) -> int:
        total = 0
        for state in ("admitted", "queued", "running"):
            total += len(self._store.list_tasks(node_id=self._node_id, state=state, limit=10_000))
        return total

    # ---- 中断恢复 ----------------------------------------------------------
    def recover_interrupted(self) -> list[TaskRecord]:
        """重启恢复：把上次进程留下的中间态收敛到可解释状态，**绝不自动重跑**。

        - ``admitted`` / ``queued``：动作尚未开始（``_execute`` 只在 ``running`` 之后调用），
          收敛为 ``failed/crashed``，额度不回滚。
        - ``running``：幂等只读 kind → ``failed/crashed``；非幂等 → ``unknown_outcome``
          （可能已产生部分副作用，既不能声称失败，也不能声称成功）。

        返回被改写的任务，供启动日志与验收脚本核对。调用方为进程启动路径
        （``scripts/peer_serve.py`` / ``web`` 挂载），不在请求路径上。
        """
        recovered: list[TaskRecord] = []
        for state in ("admitted", "queued", "running"):
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
        # 独立审查第 4 轮 P1-1（2026-11-08）：续约流程（G4/D10）保留旧租约、
        # 新建 active 租约——按最早 expires_at 全量排序会把保留的 exhausted/
        # 早期租约永远排在前面，续约后所有调度恒 grant_exhausted 拒绝。
        # 修正：仍有额度的 active 租约绝对优先（同层内最早到期）；退而求
        # 其次是额度耗尽的 active/exhausted（让闸2 产生具体拒绝码）。
        active = [g for g in usable if g.state == "active"]
        with_quota = [g for g in active if g.tasks_used < g.max_tasks_total]
        pool = with_quota or active or usable
        pool.sort(key=lambda g: g.expires_at)
        return pool[0]

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
        # 广播，也是服务端准入边界——提交未启用的 kind 必须在闸前拒绝，
        # 而不是广告关了、执行照收。
        if enabled_kinds is not None and str(payload["kind"]) not in enabled_kinds:
            raise PeerError("policy_task_kind_not_allowed", f"kind not enabled: {payload['kind']}")
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
