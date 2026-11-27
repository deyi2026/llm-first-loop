"""轻量主统筹 P0：确定性派工与权威回执接续（真实队列接线版）.

设计依据：docs/design/DESIGN-20261126-light-coordinator-p0-v2.1.md（R31-R35）；
集成修正（SA-LIGHT-COORDINATOR-P0-INTEGRATION-CORRECTION-20261126）五项收口：
1. 任务卡真实进入 HumanTurnQueue（enqueue→claim→Runner.start→terminal receipt
   复用既有权威链路；cards/*.json 仅审计附件，队列条目 message 自足承载载荷，
   poke 只是加速信号、失败由 fallback/tick 兜底，不再产生死卡）；
2. 幂等收敛到队列权威+派工锁（同键同载荷=duplicate、异载荷=conflict 拒绝、
   8 并发恰一条目；原子写 tmp 名含 tid 防 same-pid 覆盖；重启经队列文件重载
   恢复，不依赖进程内存）；
3. 审批 approved 增加上下文绑定核验（goal/scope/operation 期望不符不唤醒；
   撤销/过期/消费由 status!=approved 统一拒绝；令牌链路零触碰不变）；
4. Job 记录形状校验（owner 非空字符串、exit_code 严格 int——bool False 不等价
   0、artifact/expected/binding 必须 64-hex 精确 SHA；Reviewer 文字 PASS 不构成
   绑定不变；未知形状 fail-closed）；
5. R31 fail-closed：无显式配置=disabled（普通聊天原行为），orchestrator 必须
   可信服务端显式指派；本模块只产出队列条目（无工具执行面），端点层不给
   长命令/等待/Git/部署。

持久化语义（durability 候选，登记面见 function_size_baseline.json）：卡片写盘
tempfile+os.replace 原子替换；派工查重/入队经进程锁+cards 目录 flock 串行化，
队列侧复用 HumanTurnQueue flock+fresh-reload 全局互斥与严格 FIFO。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class CoordinatorDispatchBody(BaseModel):
    """POST /dispatch 请求体（模块级：FastAPI get_type_hints 需全局可解析——
    局部类会降级为 query 参数导致 422）。"""

    operation_id: str
    target_session: str
    payload: dict = {}


class CoordinatorResumeApprovalBody(BaseModel):
    """POST /resume-approval 请求体（同上，模块级）。"""

    request_id: str
    require_binding: dict = {}


class CoordinatorResumeJobBody(BaseModel):
    """POST /resume-job 请求体（模块级）：真实 JobRegistry 权威接续."""

    job_id: str
    queue_id: str
    expected_sha256: str  # 精确候选绑定（对照派工卡 payload_declared）

_VALID_ROLES = {"orchestrator", "worker", "disabled"}
_DEFAULT_ROLE = "disabled"
_OP_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ORIGIN = "coordinator_light"


def resolve_role(settings: dict[str, Any] | None) -> str:
    """R31：角色从可信服务端配置读取；无显式配置=disabled（fail-closed）.

    普通聊天默认原行为——只有显式 coordinator_light_role 才进入本链路；
    orchestrator/worker 必须显式指派。非法值 fail-closed（ValueError）。
    """
    raw = (settings or {}).get("coordinator_light_role")
    role = str(raw) if raw else _DEFAULT_ROLE
    if role not in _VALID_ROLES:
        raise ValueError(
            f"coordinator_light_role 非法: {role!r}（合法: {sorted(_VALID_ROLES)}）"
        )
    return role


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子替换写（tmp 名含 pid+tid 防同进程并发覆盖；os.replace 原子替换）."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def dispatch_task_card(
    card: dict[str, Any],
    *,
    inbox_dir: Path,
    poke: Callable[[str], object],
    settings: dict[str, Any] | None = None,
    queue: Any = None,
) -> dict[str, Any]:
    """R32 确定性直达（真实队列接线版）：任务卡 enqueue 进 HumanTurnQueue 权威
    + 目标 Worker 即时唤醒（零模型调用）.

    - queue 必填：orchestrator 派工必须有队列权威承载（否则拒绝——card-only
      派工不可领取、不可恢复，是集成修正前的核心缺口）；
    - 幂等收敛到队列权威：同 operation_id 活跃条目存在 → 同载荷 duplicate
      （不重复入队/唤醒）、异载荷 conflict 拒绝（409 语义，不误吞）；
    - message=完整载荷 canonical JSON（Worker 侧不依赖卡片文件）；cards/*.json
      为审计附件（best-effort，含 queue_id 回链）；poke 失败不产生死卡——
      条目已在队列，fallback/tick 同一原子入口兜底；重启后队列文件重载恢复；
    - role=disabled 明确拒绝（人工应急回退语义）。
    """
    role = resolve_role(settings)
    if role == "disabled":
        return {
            "accepted": False,
            "reason": "coordinator_light_role=disabled（人工应急回退，不派工）",
        }
    operation_id = str(card.get("operation_id") or "")
    target = str(card.get("target_session") or "")
    if not operation_id or not _OP_ID_RE.match(operation_id):
        return {"accepted": False, "reason": "invalid operation_id"}
    if not target:
        return {"accepted": False, "reason": "missing target_session"}
    if queue is None:
        return {
            "accepted": False,
            "reason": "missing queue authority（派工必须进入 HumanTurnQueue 真实队列，"
            "card-only 投递不可领取不可恢复，拒绝）",
        }

    payload = dict(card)
    payload["card_id"] = operation_id
    payload["role"] = role
    message = _canonical(payload)
    cards_dir = Path(inbox_dir) / "cards"

    # SA-LIGHT-COORDINATOR-P0-LIVE-WIRING：查重+入队收敛到队列 enqueue_once
    # 单一原子事务（flock+fresh reload 全局互斥）——旧实现 snapshot_items 读
    # 与 enqueue 写之间存在跨锁窗口（多实例下可双投），现由队列侧原子保证。
    outcome = queue.enqueue_once(
        target,
        message,
        origin=_ORIGIN,
        origin_operation_id=operation_id,
    )
    entry = outcome["item"]
    if outcome["conflict"]:
        return {
            "accepted": False,
            "conflict": True,
            "card_id": operation_id,
            "queue_id": entry.get("queue_id"),
            "reason": "operation_id 已以不同载荷派工（拒绝覆盖，409 语义）",
        }
    if outcome["duplicate"]:
        return {
            "accepted": True,
            "duplicate": True,
            "card_id": operation_id,
            "queue_id": entry.get("queue_id"),
            "queue_status": entry.get("status"),
            "queued": True,
            "poked": False,
        }
    item = entry
    # 审计附件 best-effort（队列条目 message 自足，附件缺失不影响执行）
    card_path = cards_dir / f"{operation_id}.json"
    with contextlib.suppress(OSError):
        _atomic_write_json(card_path, {**payload, "queue_id": item.get("queue_id")})
    poked = bool(poke(target))
    return {
        "accepted": True,
        "duplicate": False,
        "card_id": operation_id,
        "queue_id": item.get("queue_id"),
        "queued": True,
        "poked": poked,
    }


def resume_on_approval(
    store: Any,
    request_id: str,
    *,
    poke: Callable[[str], object],
    require_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R33：真实审批 approved → 只读核验 + 上下文绑定核验 + 来源会话唤醒.

    - status!=approved（denied/expired/consumed/revoked/…）→ 统一不唤醒；
    - require_binding（如 {"goal_id","workspace_scope","operation_id"}）：
      **None/空=fail-closed 不唤醒**（SA-LIVE-RECEIPT-AUTHORITY 边界②：
      无受信绑定不得触发目标会话动作——唤醒是副作用，缺绑定即拒绝）；
      显式给出时逐键核验，记录缺字段或与期望不符 → 不唤醒（approved 只是
      核验+唤醒信号，绑定缺失/错配不得触发目标会话动作）；
    - 只调 store.get（只读投影），绝不 consume/签发——令牌链路零触碰。
    """
    rec = store.get(str(request_id or ""))
    if rec is None:
        return {"verified": False, "poked": False, "reason": "unknown_request"}
    status = str(rec.get("status") or "")
    if status != "approved":
        return {"verified": True, "status": status, "poked": False,
                "reason": "not_approved"}
    if not require_binding:
        return {
            "verified": True,
            "status": status,
            "poked": False,
            "reason": "binding_required（未提供受信绑定，fail-closed 不唤醒）",
        }
    origin = str(rec.get("session_id") or "")
    if not origin:
        return {"verified": True, "status": status, "poked": False,
                "reason": "missing_origin_session"}
    if require_binding:
        for key, expected in require_binding.items():
            actual = rec.get(key)
            if actual is None or str(actual) != str(expected):
                return {
                    "verified": True,
                    "status": status,
                    "poked": False,
                    "reason": f"binding mismatch: {key}（记录缺失或与期望不符）",
                }
    poked = bool(poke(origin))
    return {"verified": True, "status": status, "poked": poked}


def resume_on_job(
    job_record: Any,
    *,
    expected_sha256: str,
    poke: Callable[[str], object],
    require_binding: bool = False,
    current_run_generation: str | None = None,
    require_artifact: bool = True,
) -> dict[str, Any]:
    """R34/R35：Job 权威回执接续——形状校验 + exit0 + 精确 SHA + 代次绑定分别核验.

    - require_artifact=True（产物型 Job/CI，默认）：artifact_sha256 必须存在
      且与 expected 一致；require_artifact=False（**进程型 Job**，来自
      derive_job_receipt_from_registry）：进程事实无产物账，精确候选绑定由
      expected_sha256 对照派工卡 payload_declared.candidate_sha256 在上游
      核对，此处只核 exit0 与代次/owner 绑定（不虚产物事实）。

    - **authority 门槛（SA-LIVE-RECEIPT-AUTHORITY 边界①）**：只接受
      authority="job_authority" 的真实 Job 记录；队列终态投影（derive_job_receipt
      产出 authority="queue_terminal"）**只回队列状态、不唤醒**——队列
      completed≠CI/合并凭证，伪造/派工声明 SHA 不构成接续依据；
    - 形状 fail-closed：非 dict、owner_session 非非空字符串、exit_code 非严格
      int（bool False 不等价 0）、artifact/expected 非 64-hex → 一律不唤醒；
    - require_binding=True（收口类 Job）：binding/candidate 必须 64-hex 精确
      SHA——Reviewer 文字 PASS 或任意非空值不构成绑定；
    - bound_run_generation 与 current_run_generation 同时存在且不等 → 旧代次
      不重放；
    - artifact SHA 与 expected 不匹配 → 不唤醒（权威缺失标记不可用）。
    """
    if not isinstance(job_record, dict):
        return {"poked": False, "reason": "invalid job record（必须为 dict）"}
    if str(job_record.get("authority") or "") != "job_authority":
        return {
            "poked": False,
            "verified": False,
            "reason": "not a real Job authority record（队列终态/派工声明≠CI/合并凭证，不唤醒）",
            "queue_status": job_record.get("queue_status"),
        }
    owner = job_record.get("owner_session")
    if not isinstance(owner, str) or not owner:
        return {"poked": False, "reason": "missing/invalid owner_session"}

    bound_gen = job_record.get("bound_run_generation")
    if (
        bound_gen is not None
        and current_run_generation is not None
        and str(bound_gen) != str(current_run_generation)
    ):
        return {
            "poked": False,
            "reason": f"stale run_generation（绑定 {bound_gen} ≠ 当前 {current_run_generation}，不重放）",
        }

    if require_binding and not _is_sha256(
        job_record.get("binding_sha256") or job_record.get("candidate_sha256")
    ):
        return {
            "poked": False,
            "reason": "missing/invalid precise binding（须 64-hex SHA；文字 PASS 不构成绑定）",
        }

    exit_code = job_record.get("exit_code")
    if type(exit_code) is not int:
        return {"poked": False, "reason": f"invalid exit_code（须严格 int，得 {exit_code!r}）"}
    if exit_code != 0:
        return {"poked": False, "reason": f"job not exit0（exit={exit_code!r}）"}

    artifact_sha = job_record.get("artifact_sha256")
    if require_artifact:
        if not _is_sha256(artifact_sha):
            return {"poked": False, "reason": "invalid artifact_sha256（须 64-hex）"}
        if not _is_sha256(expected_sha256):
            return {"poked": False, "reason": "invalid expected_sha256（须 64-hex）"}
        if artifact_sha != expected_sha256:
            return {"poked": False, "reason": "artifact sha mismatch"}
    else:
        # 进程型 Job：无产物账；expected_sha256 仍须为合法 SHA（上游对照
        # 派工声明 candidate），不虚产物事实
        if not _is_sha256(expected_sha256):
            return {"poked": False, "reason": "invalid expected_sha256（须 64-hex）"}

    poked = bool(poke(owner))
    return {"poked": poked, "verified": True}


def derive_job_receipt(
    queue: Any,
    queue_id: str,
    *,
    expected_workspace_scope: str | None = None,
) -> dict[str, Any]:
    """从 HumanTurnQueue 权威事实派生**队列终态投影**（SA-LIVE-RECEIPT-AUTHORITY）.

    边界①（权威区分，fail-closed）：
    - 只认 origin=coordinator_light 的队列项（他源条目不可派生 Job 回执）；
    - expected_workspace_scope 非空时绑定核验：条目 workspace_scope 与当前
      进程可信 scope 不符 → 拒绝（跨工作区投递/陈旧单例盖章不可采信）；
    - payload 内 candidate/artifact/bound_run_generation/owner_session 是
      **派工声明**（payload_declared），不是实际 Job/产物权威——回执单独
      分组，消费方不得当作 CI/合并凭证；
    - authority="queue_terminal"：本投影只证明队列终态（completed→队列语义
      exit0 / failed→1），**不构成真实 Job exit0 或 CI/合并凭证**；接续唤醒
      须由 resume_on_job 对 authority="job_authority" 的真实 Job 记录核验。
    """
    for it in queue.snapshot_items():
        if it.get("queue_id") != queue_id:
            continue
        if str(it.get("origin") or "") != _ORIGIN:
            return {
                "found": False,
                "job_record": None,
                "reason": "origin mismatch（非 coordinator_light 派工项，不可派生 Job 回执）",
            }
        item_scope = str(it.get("workspace_scope") or "") or None
        if expected_workspace_scope and not item_scope:
            return {
                "found": False,
                "job_record": None,
                "reason": "missing workspace_scope（条目无盖章，归属不明不可采信）",
            }
        if expected_workspace_scope and item_scope:
            try:
                _same = os.path.realpath(item_scope) == os.path.realpath(
                    expected_workspace_scope
                )
            except OSError:
                _same = item_scope == expected_workspace_scope
            if not _same:
                return {
                    "found": False,
                    "job_record": None,
                    "reason": (
                        f"workspace mismatch（条目 {item_scope!r} ≠ 当前可信 "
                        f"{expected_workspace_scope!r}，不可采信）"
                    ),
                }
        status = str(it.get("status") or "")
        payload: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(str(it.get("message") or ""))
            if isinstance(parsed, dict):
                payload = parsed
        receipt: dict[str, Any] = {
            "queue_id": queue_id,
            "authority": "queue_terminal",
            # 权威面：队列机械事实
            "queue_status": status,
            "terminal_at": it.get("terminal_at"),
            "run_error": it.get("run_error"),
            "claimed_by": it.get("claimed_by"),
            "workspace_scope": item_scope,
            "workspace_epoch": it.get("workspace_epoch"),
            "session_id": it.get("session_id"),
            # 派工声明面（payload_declared）：非实际 Job/产物权威，消费方
            # 不得当作 CI/合并凭证
            "payload_declared": {
                "owner_session": payload.get("owner_session") or it.get("session_id"),
                "card_id": payload.get("card_id"),
                "candidate_sha256": payload.get("candidate_sha256"),
                "artifact_sha256": payload.get("artifact_sha256"),
                "bound_run_generation": payload.get("bound_run_generation"),
            },
        }
        if status == "completed":
            receipt["queue_exit_semantics"] = 0
        elif status == "failed":
            receipt["queue_exit_semantics"] = 1
        else:
            receipt["queue_exit_semantics"] = None
            receipt["not_terminal"] = True
        return {"found": True, "job_record": receipt}
    return {"found": False, "job_record": None}


def derive_job_receipt_from_registry(
    registry: Any,
    job_id: str,
    *,
    owner_session: str = "",
    expected_workspace_scope: str | None = None,
) -> dict[str, Any]:
    """从 JobRegistry/ExternalExecutionJournal 真实权威派生 Job 回执.

    SA-LIVE-RECEIPT-AUTHORITY（主筹 2026-11-27 08:14 指正）：JobRegistry 是
    既有真实 Job 终态权威（factory.job_terminal_predicate 同源）；本函数只做
    只读投影——authority="job_authority"，state/exit_code 来自进程事实，
    owner_session 经 owner-scoped snapshot 绑定（跨 owner 不可见），workspace
    绑定同口径 realpath 归一。产物 SHA 不属于进程 Job 事实（journal 无产物
    账）——精确候选绑定由派工卡 payload_declared 承载、接续时与 expected
    对照（resume_on_job(require_artifact=False)）。重启后本地 handle 丢失，
    仅 durable 孤儿可见（无 liveness/exit 事实）→ fail-closed 不派生。
    """
    snap = registry.snapshot(str(job_id), session_id=str(owner_session or ""))
    if not isinstance(snap, dict) or not snap:
        return {
            "found": False,
            "job_record": None,
            "reason": "job not found in registry（owner-scoped 或重启后无可信终态事实）",
        }
    item_scope = str(snap.get("workspace_root") or "") or None
    if expected_workspace_scope and item_scope:
        try:
            same = os.path.realpath(item_scope) == os.path.realpath(
                expected_workspace_scope
            )
        except OSError:
            same = item_scope == expected_workspace_scope
        if not same:
            return {
                "found": False,
                "job_record": None,
                "reason": (
                    f"workspace mismatch（job {item_scope!r} ≠ 可信 "
                    f"{expected_workspace_scope!r}）"
                ),
            }
    exit_code = snap.get("exit_code")
    state = str(snap.get("state") or "")
    receipt: dict[str, Any] = {
        "authority": "job_authority",
        "job_kind": "process",
        "job_id": str(job_id),
        "job_state": state,
        "exit_code": exit_code if isinstance(exit_code, int) else None,
        "owner_session": str(snap.get("session_id") or owner_session),
        "workspace_root": item_scope,
        "bound_run_generation": snap.get("origin_run_generation"),
        "durable": bool(snap.get("durable")),
    }
    if state not in {"completed", "failed", "killed", "orphaned"}:
        receipt["not_terminal"] = True
    return {"found": True, "job_record": receipt}


def verify_coordinator_access(settings: Any, token_header: Any) -> dict[str, Any]:
    """服务端可信身份核验（SA-LIGHT-COORDINATOR-P0-LIVE-WIRING）.

    双开关 fail-closed：coordinator_light_role 必须显式配置为合法角色（缺省
    空=disabled，普通部署端点整体不存在语义）；coordinator_light_token 必须
    配置且请求头恒时匹配（secrets.compare_digest，防时序侧信道）。任何一项
    不满足即拒绝——普通聊天路径不经过本核验，行为不变。
    """
    import secrets as _secrets

    role = ""
    token_expected = ""
    if isinstance(settings, dict):
        role = str(settings.get("coordinator_light_role") or "")
        token_expected = str(settings.get("coordinator_light_token") or "")
    else:
        role = str(getattr(settings, "coordinator_light_role", "") or "")
        token_expected = str(getattr(settings, "coordinator_light_token", "") or "")
    if not token_expected:
        return {"allowed": False, "status": 403, "reason": "coordinator disabled（未配置访问令牌）"}
    if role not in _VALID_ROLES or role == "disabled":
        return {"allowed": False, "status": 403, "reason": f"coordinator role disabled/illegal: {role!r}"}
    if not isinstance(token_header, str) or not _secrets.compare_digest(token_header, token_expected):
        return {"allowed": False, "status": 401, "reason": "invalid coordinator token"}
    return {"allowed": True, "role": role}


def _resume_binding_or_rejection(
    request: Any, body: Any
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """resume-approval 绑定构造与强制核验（自 build_coordinator_light_router 抽出）.

    SA-LIVE-RECEIPT-AUTHORITY 边界②（主筹 2026-11-26 21:32 收紧）：可信
    workspace_scope **强制覆盖**请求值（请求不得指定他区 scope——单例陈旧
    盖章缺陷的运行面约束）；必需绑定键（owner/goal/代次/待办）缺失 →
    rejection（fail-closed：审批接续无完整上下文本就不应发生）。
    """
    binding = dict(getattr(body, "require_binding", None) or {})
    engine = getattr(request.app.state, "engine", None)
    trusted_scope = str(getattr(engine, "workspace_root", "") or "")
    if trusted_scope:
        binding["workspace_scope"] = trusted_scope
    missing_required = [
        k
        for k in ("owner_session", "goal_id", "bound_run_generation", "card_id")
        if k not in binding
    ]
    if missing_required:
        return None, JSONResponse(content={
            "ok": False,
            "verified": True,
            "poked": False,
            "reason": (
                f"missing required binding keys: {missing_required}"
                "（审批接续须显式 owner/goal/代次/待办绑定，fail-closed）"
            ),
        })
    return binding, None


def _resume_job_from_registry(
    request: Any,
    body: CoordinatorResumeJobBody,
    queue: Any,
    poke: Callable[[str], object],
) -> JSONResponse:
    """resume-job 端点主体（自 build_coordinator_light_router 抽出）.

    队列项权威（origin/scope 绑定+派工声明 candidate）→ JobRegistry
    owner-scoped snapshot（authority="job_authority"）→ 未终态只回状态不
    唤醒 → exit0+candidate 对照通过 → resume_on_job 唤醒 owner（进程型
    require_artifact=False，无产物账不虚产物事实）。
    """
    engine = getattr(request.app.state, "engine", None)
    trusted_scope = str(getattr(engine, "workspace_root", "") or "") or None
    derived = derive_job_receipt(queue, body.queue_id, expected_workspace_scope=trusted_scope)
    if not derived.get("found"):
        return JSONResponse(
            content={"ok": False, "error": "queue_item_not_found", "reason": derived.get("reason")},
            status_code=404,
        )
    declared = derived["job_record"].get("payload_declared") or {}
    owner = str(declared.get("owner_session") or derived["job_record"].get("session_id") or "")
    candidate = str(declared.get("candidate_sha256") or "")
    if not _is_sha256(candidate):
        return JSONResponse(
            content={"ok": False, "error": "派工卡无合法 candidate 绑定，不可接续（fail-closed）"},
            status_code=409,
        )
    if candidate != body.expected_sha256:
        return JSONResponse(
            content={"ok": False, "error": "candidate mismatch（派工声明≠期望候选）"},
            status_code=409,
        )
    from llm_loop.tools.builtin.job_registry import JobRegistry

    jr = derive_job_receipt_from_registry(
        JobRegistry.instance(),
        body.job_id,
        owner_session=owner,
        expected_workspace_scope=trusted_scope,
    )
    if not jr.get("found"):
        return JSONResponse(
            content={"ok": False, "error": "job_not_found", "reason": jr.get("reason")},
            status_code=404,
        )
    receipt = jr["job_record"]
    if receipt.get("not_terminal"):
        return JSONResponse(content={
            "ok": True,
            "resumed": False,
            "reason": "job not terminal（只回状态不唤醒）",
            "job_state": receipt.get("job_state"),
            "queue_status": derived["job_record"].get("queue_status"),
        })
    # 绑定凭据：candidate 已与派工声明对照一致（409 早退兜底），填入
    # receipt 供 require_binding 精确 SHA 核验（绑定源=派工卡声明）。
    receipt["candidate_sha256"] = candidate
    outcome = resume_on_job(
        receipt,
        expected_sha256=body.expected_sha256,
        poke=lambda sid: poke(sid),
        require_binding=True,
        require_artifact=False,
    )
    return JSONResponse(content={"ok": bool(outcome.get("poked")), **outcome})


def _dispatch_card_response(
    request: Any,
    body: CoordinatorDispatchBody,
    queue: Any,
    poke: Callable[[str], object],
) -> JSONResponse:
    """dispatch 端点主体：真实 dispatch_task_card（队列 enqueue_once 单事务）."""
    engine = getattr(request.app.state, "engine", None)
    settings = getattr(engine, "settings", None)
    # 元字段权威：payload 不得覆盖 operation_id/target_session（否则
    # 幂等键与派工声明漂移，回执对不上账）
    result = dispatch_task_card(
        {
            **dict(body.payload),
            "operation_id": body.operation_id,
            "target_session": body.target_session,
        },
        inbox_dir=Path(_coordinator_data_dir(request)) / "coordinator_light",
        poke=lambda sid: poke(sid),
        settings={
            "coordinator_light_role": str(getattr(settings, "coordinator_light_role", "") or ""),
        },
        queue=queue,
    )
    status_code = 409 if result.get("conflict") else 200
    return JSONResponse(content={"ok": bool(result.get("accepted")), **result}, status_code=status_code)


def _job_receipt_response(request: Any, queue: Any, queue_id: str) -> JSONResponse:
    """job/{queue_id} 端点主体：队列终态投影（authority=queue_terminal）."""
    engine = getattr(request.app.state, "engine", None)
    trusted_scope = str(getattr(engine, "workspace_root", "") or "") or None
    result = derive_job_receipt(queue, queue_id, expected_workspace_scope=trusted_scope)
    if not result.get("found"):
        return JSONResponse(
            content={"ok": False, "error": "job_not_found", "reason": result.get("reason")},
            status_code=404,
        )
    return JSONResponse(content={"ok": True, **result})


def _coordinator_data_dir(request: Any) -> str:
    engine = getattr(request.app.state, "engine", None)
    return str(getattr(getattr(engine, "settings", None), "data_dir", "./data"))


def build_coordinator_light_router(
    queue_from: Callable[[Any], Any] | None = None,
    poke_from: Callable[[Any], Callable[[str], object]] | None = None,
):
    """真实 HTTP 入口（SA-LIGHT-COORDINATOR-P0-LIVE-WIRING）：本模块此前的
    src 无 caller——现以 FastAPI router 接线既有 HTTP→queue→Worker 链路.

    依赖注入（R9-P2-06a 断环）：queue_from(request)→HumanTurnQueue 单例、
    poke_from(request)→poke 函数由装配方（routes._build_coordinator_router）
    注入——本模块不反向 import routes，消除 coordinator_light<->preview_routes
    <->routes runtime 环。两者缺省 None=fail-closed（端点返回 503 not_wired，
    不静默自造依赖）。

    - POST /api/v1/coordinator/light/dispatch：真实调用 dispatch_task_card
      （queue=请求侧 HumanTurnQueue 单例，poke=既有 _poke_queue_fallback）；
    - POST /api/v1/coordinator/light/resume-approval：真实 EscalationStore
      （data/audit/escalation_requests.json 权威记录）→ resume_on_approval；
    - GET  /api/v1/coordinator/light/job/{queue_id}：derive_job_receipt 从
      队列权威事实派生回执（不另建账本）。
    全部端点先过 verify_coordinator_access（401/403 fail-closed）；
    coordinator_light CI 自动接续接口本版明确未实现（返回 not_implemented，
    不假造）。
    """
    from llm_loop.tools.escalation import EscalationStore

    router = APIRouter(prefix="/api/v1/coordinator/light")

    def _guard(request: Any) -> JSONResponse | None:
        engine = getattr(request.app.state, "engine", None)
        outcome = verify_coordinator_access(getattr(engine, "settings", None), request.headers.get("X-Coordinator-Token"))
        if outcome.get("allowed"):
            return None
        return JSONResponse(content={"ok": False, "error": outcome.get("reason")}, status_code=int(outcome.get("status") or 403))

    def _queue_from(request: Any) -> Any:
        if queue_from is None:
            return None  # 未注入依赖：fail-closed（端点 503 not_wired）

        return queue_from(request)

    def _poke_of(request: Any) -> Callable[[str], object] | None:
        if poke_from is None:
            return None

        return poke_from(request)

    def _data_dir(request: Any) -> str:
        engine = getattr(request.app.state, "engine", None)
        return str(getattr(getattr(engine, "settings", None), "data_dir", "./data"))

    @router.post("/dispatch")
    def light_dispatch(body: CoordinatorDispatchBody, request: Request) -> Response:
        denied = _guard(request)
        if denied is not None:
            return denied
        queue = _queue_from(request)
        poke = _poke_of(request)
        if queue is None or poke is None:
            return JSONResponse(
                content={"ok": False, "error": "not_wired（queue/poke 依赖未注入，fail-closed）"},
                status_code=503,
            )
        return _dispatch_card_response(request, body, queue, poke)

    @router.post("/resume-approval")
    def light_resume_approval(body: CoordinatorResumeApprovalBody, request: Request) -> Response:
        denied = _guard(request)
        if denied is not None:
            return denied
        poke = _poke_of(request)
        if poke is None:
            return JSONResponse(
                content={"ok": False, "error": "not_wired（poke 依赖未注入，fail-closed）"},
                status_code=503,
            )

        binding, rejection = _resume_binding_or_rejection(request, body)
        if rejection is not None:
            return rejection
        store = EscalationStore(Path(_data_dir(request)) / "audit" / "escalation_requests.json")
        result = resume_on_approval(
            store,
            body.request_id,
            poke=lambda sid: poke(sid),
            require_binding=binding or None,
        )
        return JSONResponse(content={"ok": bool(result.get("verified")), **result})

    @router.get("/job/{queue_id}")
    def light_job_receipt(queue_id: str, request: Request) -> Response:
        denied = _guard(request)
        if denied is not None:
            return denied
        queue = _queue_from(request)
        if queue is None:
            return JSONResponse(
                content={"ok": False, "error": "not_wired（queue 依赖未注入，fail-closed）"},
                status_code=503,
            )
        return _job_receipt_response(request, queue, queue_id)

    @router.post("/resume-job")
    def light_resume_job(body: CoordinatorResumeJobBody, request: Request) -> Response:
        """真实 JobRegistry 权威接续（SA-LIVE-RECEIPT-AUTHORITY 主链条）.

        1) 队列项权威：origin/scope 绑定 + 派工声明 candidate（精确候选绑定源）；
        2) JobRegistry owner-scoped snapshot：authority="job_authority" 进程
           终态事实（与 factory.job_terminal_predicate 同源）；
        3) 未终态只回状态不唤醒；exit0+candidate 对照通过 → 唤醒 owner 会话
           （进程型 require_artifact=False，无产物账不虚产物事实）。
        """
        denied = _guard(request)
        if denied is not None:
            return denied
        queue = _queue_from(request)
        poke = _poke_of(request)
        if queue is None or poke is None:
            return JSONResponse(
                content={"ok": False, "error": "not_wired（queue/poke 依赖未注入，fail-closed）"},
                status_code=503,
            )
        return _resume_job_from_registry(request, body, queue, poke)

    @router.post("/ci-continue")
    def light_ci_continue(request: Request) -> Response:
        denied = _guard(request)
        if denied is not None:
            return denied
        return JSONResponse(
            content={"ok": False, "error": "not_implemented（可信 CI 自动接续接口本版未实现，不假造）"},
            status_code=501,
        )

    return router
