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
import fcntl
import json
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_VALID_ROLES = {"orchestrator", "worker", "disabled"}
_DEFAULT_ROLE = "disabled"
_OP_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ORIGIN = "coordinator_light"
_DISPATCH_GUARD = threading.Lock()


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
    poke: Callable[[str], bool],
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
    lock_path = cards_dir / ".dispatch.lock"

    with _DISPATCH_GUARD:  # 进程内串行化：查重+入队必须原子（否则并发双投）
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            entries = [
                it
                for it in queue.snapshot_items()
                if it.get("origin") == _ORIGIN
                and it.get("origin_operation_id") == operation_id
            ]
            if entries:
                entry = entries[0]
                if str(entry.get("message") or "") != message:
                    return {
                        "accepted": False,
                        "conflict": True,
                        "card_id": operation_id,
                        "reason": "operation_id 已以不同载荷派工（拒绝覆盖，409 语义）",
                    }
                return {
                    "accepted": True,
                    "duplicate": True,
                    "card_id": operation_id,
                    "queue_id": entry.get("queue_id"),
                    "queue_status": entry.get("status"),
                    "queued": True,
                    "poked": False,
                }
            item = queue.enqueue(
                target,
                message,
                origin=_ORIGIN,
                origin_operation_id=operation_id,
            )
            # 审计附件 best-effort（队列条目 message 自足，附件缺失不影响执行）
            card_path = cards_dir / f"{operation_id}.json"
            with contextlib.suppress(OSError):
                _atomic_write_json(
                    card_path, {**payload, "queue_id": item.get("queue_id")}
                )
            poked = bool(poke(target))
            return {
                "accepted": True,
                "duplicate": False,
                "card_id": operation_id,
                "queue_id": item.get("queue_id"),
                "queued": True,
                "poked": poked,
            }
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def resume_on_approval(
    store: Any,
    request_id: str,
    *,
    poke: Callable[[str], bool],
    require_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R33：真实审批 approved → 只读核验 + 上下文绑定核验 + 来源会话唤醒.

    - status!=approved（denied/expired/consumed/revoked/…）→ 统一不唤醒；
    - require_binding（如 {"goal_id","workspace_scope","operation_id"}）：记录
      缺字段或与期望不符 → 不唤醒（approved 只是核验+唤醒信号，绑定缺失/
      错配不得触发目标会话动作）；
    - 只调 store.get（只读投影），绝不 consume/签发——令牌链路零触碰。
    """
    rec = store.get(str(request_id or ""))
    if rec is None:
        return {"verified": False, "poked": False, "reason": "unknown_request"}
    status = str(rec.get("status") or "")
    if status != "approved":
        return {"verified": True, "status": status, "poked": False,
                "reason": "not_approved"}
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
    poke: Callable[[str], bool],
    require_binding: bool = False,
    current_run_generation: str | None = None,
) -> dict[str, Any]:
    """R34/R35：Job 权威回执接续——形状校验 + exit0 + 精确 SHA + 代次绑定分别核验.

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
    if not _is_sha256(artifact_sha):
        return {"poked": False, "reason": "invalid artifact_sha256（须 64-hex）"}
    if not _is_sha256(expected_sha256):
        return {"poked": False, "reason": "invalid expected_sha256（须 64-hex）"}
    if artifact_sha != expected_sha256:
        return {"poked": False, "reason": "artifact sha mismatch"}

    poked = bool(poke(owner))
    return {"poked": poked, "verified": True}
