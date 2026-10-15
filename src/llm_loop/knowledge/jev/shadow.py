"""EVO-20261015 (P1a): Jev shadow runner——只记录判断，不改检索输出。

DESIGN-20261014-jev §6.3/§5.4：
- shadow：只记录判断，现有排序/呈现不变；必须与 OFF 同样保留基线候选集。
- 本 runner 的公共 API 不接受也不返回任何候选集/排序——无修改检索输出的面。
- 每个物理尝试/每个逻辑题的最小字段照 §5.4 落 knowledge.jev_shadow 事件。
- fail-open：一切内部失败只进事件与 outcome.status，不向调用方抛异常。
- 无重试（§8.4）：传输失败即单次尝试终态；attempt_seq 不回退。
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_loop.knowledge.jev.policy import (
    EST_OUTPUT_TOKENS_PER_QUESTION,
    BudgetRefused,
    PolicyGuard,
    ProjectionUnsafe,
    assert_projection_safe,
    build_projection,
    estimate_input_tokens,
)
from llm_loop.knowledge.jev.transport import (
    TRANSPORT_ERROR,
    TRANSPORT_TIMEOUT,
    JevTransport,
    JevTransportError,
)
from llm_loop.knowledge.jev.wire import (
    CONTRACT_MODEL_ALIAS,
    QUESTION_STATUS_VALID,
    WIRE_SCHEMA_VERSION,
    NormalizedResponse,
    QuestionSpec,
    build_request,
    normalize_response,
    request_hashes,
)

#: answers 原文摘录的固定截断上限（R1 教训，DESIGN v0.8.8：raw 丢弃即不可诊断；
#: 上限防事件无限膨胀，超出以 ...truncated(N chars) 标注）。
RAW_ANSWERS_EXCERPT_CAP = 4096

EVENT_KIND = "knowledge.jev_shadow"

#: 结算口径：shadow 判断不产生业务效果（§6.3），故恒为 not_evaluated。
TASK_BENEFIT = "not_evaluated"


@dataclass(frozen=True)
class ShadowOutcome:
    """一次 shadow 判断的完整事实（含失败/拒绝——失败也是事实，不静默）。"""

    status: str  # recorded | budget_refused | projection_unsafe | transport_failed | internal_error
    attempt_id: str
    subject_ref: str
    run_ref: str
    resolved_model: str | None = None
    transport_status: str = ""
    questions: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    request_hash: str = ""
    questions_map_hash: str = ""
    error_detail: str = ""
    #: 事件是否成功落库（event_append 返回/异常）；False=审计持久化丢失，不静默。
    event_persisted: bool = False
    #: shadow 不改基线：恒 True，进事件供审计对照。
    baseline_unchanged: bool = True
    ordering_effect: str = "none"
    #: R1 教训（DESIGN v0.8.8）：任一题非 valid 或批级无效时，官方 answers 原文
    #: 的有界摘录（RAW_ANSWERS_EXCERPT_CAP 截断）；全 valid 时为空串。
    raw_answers_excerpt: str = ""


def _raw_answers_excerpt(raw: Any, cap: int = RAW_ANSWERS_EXCERPT_CAP) -> str:
    """官方 answers map 的有界规范摘录；解析失败返回空串（fail-open，不阻断事实）。"""
    try:
        answers = raw.get("answers") if isinstance(raw, dict) else None
        if not isinstance(answers, dict):
            return ""
        text = json.dumps(answers, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - 摘录失败不改变判断事实本身
        return ""
    if len(text) <= cap:
        return text
    return text[:cap] + f"...truncated({len(text)} chars)"


class JevShadowRunner:
    """逐次判断的 shadow 执行器。事件经注入的 event_append 落 EventStore。

    event_append 签名对齐既有 knowledge.* 观测链：(session_id, kind, payload)。
    event_append 自身失败按 fail-open 处理：判断事实仍返回（status 不因事件层
    失败翻转为假失败），持久化结果显式落在 outcome.event_persisted（False 即
    审计持久化丢失，调用方可观测——不静默）。
    """

    def __init__(
        self,
        *,
        transport: JevTransport,
        guard: PolicyGuard,
        event_append: Callable[[str, str, dict[str, Any]], Any] | None,
        session_id: str,
        run_ref: str,
        model_alias: str = CONTRACT_MODEL_ALIAS,
    ) -> None:
        self.transport = transport
        self.guard = guard
        self.event_append = event_append
        self.session_id = str(session_id)
        self.run_ref = str(run_ref)
        self.model_alias = str(model_alias)

    def _emit(self, payload: dict[str, Any]) -> bool:
        if self.event_append is None:
            return False
        try:
            self.event_append(self.session_id, EVENT_KIND, payload)
            return True
        except Exception:  # noqa: BLE001 - fail-open：事件失败不阻断、不改调用方真相
            return False

    def judge_premises(
        self,
        *,
        subject_ref: str,
        subject_hash: str,
        task_snapshot: dict[str, Any],
        allowlist: frozenset[str] | set[str],
        questions: dict[str, QuestionSpec],
    ) -> ShadowOutcome:
        """对一组独立原子题做一次 shadow 判断（一次物理尝试，无重试）。"""
        attempt_id = f"jev-attempt-{uuid.uuid4().hex[:16]}"
        base = {
            "attempt_id": attempt_id,
            "run_ref": self.run_ref,
            "subject_ref": subject_ref,
            "subject_hash": subject_hash,
            "wire_schema_version": WIRE_SCHEMA_VERSION,
            "retry_enabled": self.guard.policy.retry_enabled,
            "cost_source": self.guard.policy.cost_source,
            "task_benefit": TASK_BENEFIT,
            "baseline_unchanged": True,
            "ordering_effect": "none",
            "policy": self.guard.policy.to_facts(),
        }
        try:
            state = build_projection(
                subject_ref=subject_ref,
                subject_hash=subject_hash,
                task_snapshot=task_snapshot,
                allowlist=allowlist,
            )
            request = build_request(
                model=self.model_alias, state=state, questions=questions
            )
            assert_projection_safe(request)
            hashes = request_hashes(request)
            est_tokens = estimate_input_tokens(request)
            try:
                ticket = self.guard.acquire(
                    question_count=len(questions),
                    est_input_tokens=est_tokens,
                    est_output_tokens=EST_OUTPUT_TOKENS_PER_QUESTION * len(questions),
                )
            except BudgetRefused as refused:
                payload = {
                    **base,
                    **refused.facts,
                    "status": "budget_refused",
                    "error_detail": refused.reason,
                    **hashes,
                }
                persisted = self._emit(payload)
                return ShadowOutcome(
                    status="budget_refused", attempt_id=attempt_id,
                    subject_ref=subject_ref, run_ref=self.run_ref,
                    request_hash=hashes["request_hash"],
                    questions_map_hash=hashes["questions_map_hash"],
                    error_detail=refused.reason, event_persisted=persisted,
                )

            t_queued = time.monotonic()
            transport_status = ""
            try:
                t_sent = time.monotonic()  # §5.4：发出时间与入队/结束分开
                response = self.transport.send(
                    request, deadline_s=float(ticket["deadline_s"])
                )
                transport_status = "ok"
            except Exception as exc:  # noqa: BLE001 - 传输面任何失败都是 transport_failed
                if isinstance(exc, JevTransportError):
                    transport_status = (
                        TRANSPORT_TIMEOUT if exc.kind == "timeout" else TRANSPORT_ERROR
                    )
                    detail = f"{exc.kind}: {exc.detail}"
                else:
                    # 传输实现缺陷泄漏的原始异常：仍按传输失败归类，记录异常类型。
                    transport_status = TRANSPORT_ERROR
                    detail = f"unclassified:{type(exc).__name__}: {exc}"
                payload = {
                    **base,
                    "status": "transport_failed",
                    "transport_status": transport_status,
                    "error_detail": detail,
                    "t_queued": t_queued,
                    "t_sent": t_sent,
                    "t_end": time.monotonic(),
                    "attempt_seq": ticket["attempt_seq"],
                    **hashes,
                }
                persisted = self._emit(payload)
                return ShadowOutcome(
                    status="transport_failed", attempt_id=attempt_id,
                    subject_ref=subject_ref, run_ref=self.run_ref,
                    transport_status=transport_status,
                    request_hash=hashes["request_hash"],
                    questions_map_hash=hashes["questions_map_hash"],
                    error_detail=detail, event_persisted=persisted,
                )
            t_end = time.monotonic()

            normalized: NormalizedResponse = normalize_response(
                request=request, raw=response, transport_status=transport_status
            )
            question_facts = {
                name: ans.to_facts(resolved_model=normalized.resolved_model)
                for name, ans in normalized.answers.items()
            }
            # R1 教训（DESIGN v0.8.8）：任一题非 valid 或批级无效时持久化 answers
            # 原文摘录，避免"判定值被丢弃后不可诊断"重演；全 valid 不复制 payload。
            needs_excerpt = bool(normalized.batch_invalid_reasons) or any(
                ans.status != QUESTION_STATUS_VALID
                for ans in normalized.answers.values()
            )
            raw_excerpt = _raw_answers_excerpt(response) if needs_excerpt else ""
            payload = {
                **base,
                "status": "recorded",
                "transport_status": normalized.transport_status,
                "resolved_model": normalized.resolved_model,
                "batch_invalid_reasons": list(normalized.batch_invalid_reasons),
                "t_queued": t_queued,
                "t_sent": t_sent,
                "t_end": t_end,
                "attempt_seq": ticket["attempt_seq"],
                "usage": normalized.usage.to_facts(),
                "questions": question_facts,
                "summary": normalized.summary(),
                "raw_response_hash": normalized.raw_hash,
                "raw_answers_excerpt": raw_excerpt,
                **hashes,
            }
            persisted = self._emit(payload)
            return ShadowOutcome(
                status="recorded", attempt_id=attempt_id,
                subject_ref=subject_ref, run_ref=self.run_ref,
                resolved_model=normalized.resolved_model,
                transport_status=normalized.transport_status,
                questions=question_facts,
                usage=normalized.usage.to_facts(),
                summary=normalized.summary(),
                raw_answers_excerpt=raw_excerpt,
                request_hash=hashes["request_hash"],
                questions_map_hash=hashes["questions_map_hash"],
                event_persisted=persisted,
            )
        except ProjectionUnsafe as unsafe:
            payload = {**base, "status": "projection_unsafe",
                       "error_detail": str(unsafe)}
            persisted = self._emit(payload)
            return ShadowOutcome(
                status="projection_unsafe", attempt_id=attempt_id,
                subject_ref=subject_ref, run_ref=self.run_ref,
                error_detail=str(unsafe), event_persisted=persisted,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open：内部失败不抛给调用方
            payload = {**base, "status": "internal_error",
                       "error_detail": f"{type(exc).__name__}: {exc}"}
            persisted = self._emit(payload)
            return ShadowOutcome(
                status="internal_error", attempt_id=attempt_id,
                subject_ref=subject_ref, run_ref=self.run_ref,
                error_detail=f"{type(exc).__name__}: {exc}",
                event_persisted=persisted,
            )
