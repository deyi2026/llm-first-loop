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
- 未实现 ``blocked``（人工确认）与 ``unknown_outcome`` 的自动判定，留给后续切片。
"""

from __future__ import annotations

import hashlib
import json
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
        health: str = "ok",
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
        self._health = health
        self._max_concurrency = int(max_concurrency)
        self._audit_watermark_pct = int(audit_watermark_pct)
        self._enabled_kinds = enabled_kinds
        self._clock = clock

    # ---- manifest ---------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        grant = self.active_grant()
        payload: dict[str, Any] = {
            "schema": "lfl.peer.v1",
            "peer_api": PEER_API,
            "node_id": self._node_id,
            "role": self._role,
            "health": self._health,
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
        shape = self._validate_submit(payload)
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
        admission = self._admissions.write(
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

    def _deny(self, task: TaskRecord, grant: GrantRecord | None, exc: PeerError) -> dict[str, Any]:
        self._store.put_task(task)
        self._admissions.write(
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
        denied = self._transition(task, "denied", reason_code=exc.reason_code)
        return self.receipt(denied)

    def _execute(self, task: TaskRecord) -> TaskRecord:
        grant = self._store.get_grant(task.grant_id) if task.grant_id else None
        allowed_paths = tuple(grant.allowed_paths) if grant else ()
        try:
            outcome: ExecOutcome = self._executor.run(
                kind=task.kind, params=task.params, allowed_paths=allowed_paths
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
            "executor": {"node_id": self._node_id, "health": self._health},
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
    def _transition(self, task: TaskRecord, state: str, **changes: Any) -> TaskRecord:
        updated = task.with_updates(state=state, updated_at=iso(self._clock()), **changes)
        return self._store.put_task(updated, expected_state=task.state)

    def _running_count(self) -> int:
        total = 0
        for state in ("admitted", "queued", "running"):
            total += len(self._store.list_tasks(node_id=self._node_id, state=state, limit=10_000))
        return total

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
            raise PeerError("grant_not_found", f"no active grant for {self._node_id}")
        usable.sort(key=lambda g: g.expires_at)
        return usable[0]

    def active_grant(self) -> GrantRecord | None:
        try:
            return self._select_grant()
        except PeerError:
            return None

    @staticmethod
    def _validate_submit(payload: dict[str, Any]) -> dict[str, Any]:
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
        if not isinstance(effect_id, str) or not 8 <= len(effect_id) <= 128:
            raise PeerError("params_schema_invalid", "bad effect_id")
        if not isinstance(payload["kind"], str) or get_kind(payload["kind"]) is None:
            raise PeerError("policy_task_kind_not_allowed", str(payload.get("kind")))
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
