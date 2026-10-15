"""EVO-20261015 (P1a): Jev(TypeSafe systemone) 官方 wire 契约——仅契约与规范化，无传输。

DESIGN-20261014-jev §8.2/§8.3 的实现锚定：
- 请求形态 model/state/questions；同一 state 可配多道独立命名题（Choice/Score/Noul）。
- 响应规范化保留 resolved model、每题 choice/probabilities/confidence、usage、物理尝试身份。
- EVO-20261015（P1b-OR R1 根因修复）：官方逐题值字段名是 choice/score/noul
  （choice=string∈options；score=number 刻度位；noul=number 0-1，无 confidence）。
  旧实现读自造的 answer 键导致 §11.6 轮 6/6 题 contract_invalid（DESIGN 附录 C v0.8.8）。
- 逐题校验：缺某题只使该题 missing/contract_invalid，不把整批伪称全成功。
- schema-invalid 保留无效事实与 null，不填 confidence=0.5；usage 缺失为 unknown 不计 0。
- 语义 unknown（合法选项）与 contract-invalid（协议失败）分开统计。
- confidence 与 p_selected 分开存；校准优先检查完整概率分布。

本模块不 import 任何网络库、不构造 HTTP 调用；endpoint 仅作为契约事实常量记录。
数值容差由本契约固定（PROB_SUM_TOLERANCE/VALUE_EPS）并被测试钉住。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

WIRE_SCHEMA_VERSION = "jev-wire/v1"
#: §8.1 官方契约事实（非本机实测）；alias 可能漂移，一切判断绑定响应的 resolved model。
CONTRACT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
CONTRACT_MODEL_ALIAS = "jev-1.13.0"

#: 概率分布和的固定容差（§8.3"数值容差由契约固定并测试"）。
PROB_SUM_TOLERANCE = 1e-6
#: 单值边界容差：概率/confidence 允许 [0-eps, 1+eps] 的表示误差。
VALUE_EPS = 1e-9

QUESTION_TYPES = frozenset({"choice", "score", "noul"})
#: 语义 unknown 是 Choice 的合法选项（§8.3），不是协议失败。
SEMANTIC_UNKNOWN_OPTION = "unknown"

#: 每题状态：valid | missing（响应缺该题）| contract_invalid（校验失败）。
QUESTION_STATUS_VALID = "valid"
QUESTION_STATUS_MISSING = "missing"
QUESTION_STATUS_CONTRACT_INVALID = "contract_invalid"


def canonical_json(payload: Any) -> str:
    """请求/响应哈希的规范序列化（键序稳定，无关空白）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_of(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QuestionSpec:
    """一道独立命名题（逻辑原子）。依赖上游答案的题不得混入同一独立批（§8.4）。"""

    name: str
    type: str  # choice | score | noul
    instructions: str
    criteria: dict[str, str] = field(default_factory=dict)  # 选项/刻度描述（自定义判据）

    def to_wire(self) -> dict[str, Any]:
        if self.type not in QUESTION_TYPES:
            raise ValueError(f"unknown question type: {self.type!r}")
        if self.type == "choice" and not self.criteria:
            raise ValueError("choice question requires criteria options")
        return {
            "type": self.type,
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }

    def options(self) -> tuple[str, ...]:
        return tuple(sorted(self.criteria.keys()))


@dataclass(frozen=True)
class NormalizedAnswer:
    """单题规范化结果。invalid 时 answer/probabilities/confidence 保持 None（不填 0.5）。"""

    name: str
    status: str
    answer: str | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    #: p_selected = 所选选项的分布概率；与 confidence 分开存（§8.3）。
    p_selected: float | None = None
    invalid_reasons: tuple[str, ...] = ()
    #: §5.4 逐题最小字段：question_type / question_schema_version / options_hash。
    question_type: str = ""
    schema_version: str = WIRE_SCHEMA_VERSION
    options_hash: str = ""

    def to_facts(self, *, resolved_model: str | None = None) -> dict[str, Any]:
        return {
            "question_instance_id": self.name,
            "question_type": self.question_type,
            "question_schema_version": self.schema_version,
            "options_hash": self.options_hash,
            "resolved_model": resolved_model,
            "status": self.status,
            "answer": self.answer,
            "probabilities": self.probabilities,
            "confidence": self.confidence,
            "p_selected": self.p_selected,
            "invalid_reasons": list(self.invalid_reasons),
            # 语义 unknown 合法 ≠ contract-invalid；两者由 status 本身区分。
            "semantic_unknown": self.answer == SEMANTIC_UNKNOWN_OPTION
            and self.status == QUESTION_STATUS_VALID,
        }


def _options_hash(spec: QuestionSpec) -> str:
    return _sha256_of({"options": list(spec.options())})


def _invalid(name: str, spec: QuestionSpec, reasons: tuple[str, ...]) -> NormalizedAnswer:
    return NormalizedAnswer(
        name=name, status=QUESTION_STATUS_CONTRACT_INVALID,
        invalid_reasons=reasons,
        question_type=spec.type, options_hash=_options_hash(spec),
    )


@dataclass(frozen=True)
class UsageFacts:
    """usage 缺失为 unknown，不计 0（§8.3）。"""

    status: str  # valid | unknown
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reason: str = ""

    def to_facts(self) -> dict[str, Any]:
        return {
            "usage_status": self.status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_reason": self.reason,
        }


@dataclass(frozen=True)
class NormalizedResponse:
    resolved_model: str | None
    answers: dict[str, NormalizedAnswer]
    usage: UsageFacts
    transport_status: str
    raw_hash: str
    batch_invalid_reasons: tuple[str, ...] = ()

    def summary(self) -> dict[str, int]:
        """语义 unknown 与 contract-invalid 分开统计（§8.3）。"""
        semantic_unknown = sum(
            1 for a in self.answers.values() if a.to_facts()["semantic_unknown"]
        )
        return {
            "valid": sum(1 for a in self.answers.values() if a.status == QUESTION_STATUS_VALID),
            "missing": sum(1 for a in self.answers.values() if a.status == QUESTION_STATUS_MISSING),
            "contract_invalid": sum(
                1 for a in self.answers.values() if a.status == QUESTION_STATUS_CONTRACT_INVALID
            ),
            "semantic_unknown": semantic_unknown,
        }


def build_request(
    *,
    model: str,
    state: dict[str, Any],
    questions: dict[str, QuestionSpec],
) -> dict[str, Any]:
    """构建官方请求形态（§8.2）。state/questions 由 policy 层负责投影与守卫。"""
    if not str(model or "").strip():
        raise ValueError("model is required")
    if not questions:
        raise ValueError("at least one question is required")
    return {
        "model": str(model),
        "state": dict(state),
        "questions": {name: q.to_wire() for name, q in questions.items()},
    }


def request_hashes(request: dict[str, Any]) -> dict[str, str]:
    """§5.4 每个物理尝试的最小身份：request_hash + questions_map_hash。"""
    return {
        "request_hash": _sha256_of(request),
        "questions_map_hash": _sha256_of(request.get("questions", {})),
    }


def _finite_in_unit(v: Any, eps: float = VALUE_EPS) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
        and -eps <= float(v) <= 1.0 + eps
    )


def _validate_choice(
    name: str, spec: QuestionSpec, raw: Any
) -> NormalizedAnswer:
    reasons: list[str] = []
    if not isinstance(raw, dict):
        return _invalid(name, spec, ("answer_not_object",))
    answer = raw.get("choice")
    probabilities = raw.get("probabilities")
    confidence = raw.get("confidence")
    options = spec.options()

    answer_valid = isinstance(answer, str) and answer in options
    if not answer_valid:
        reasons.append("choice_not_in_options")

    probs_ok = False
    if isinstance(probabilities, dict):
        if set(probabilities.keys()) != set(options):
            reasons.append("probabilities_keyset_mismatch")
        else:
            values_ok = all(_finite_in_unit(v) for v in probabilities.values())
            if not values_ok:
                reasons.append("probability_not_finite_or_out_of_unit")
            else:
                total = sum(float(v) for v in probabilities.values())
                if abs(total - 1.0) > PROB_SUM_TOLERANCE:
                    reasons.append(f"probability_sum_off_by_{abs(total - 1.0):.3e}")
                else:
                    probs_ok = True
    else:
        reasons.append("probabilities_missing_or_not_object")

    confidence_valid = _finite_in_unit(confidence) if confidence is not None else False
    if not confidence_valid:
        reasons.append("confidence_missing_or_out_of_range")

    # Runtime guards above establish these types; keep the narrowing explicit
    # for static analysis without accepting any additional wire payloads.
    if (
        answer_valid and probs_ok and confidence_valid
        and isinstance(probabilities, dict)
        and isinstance(confidence, (int, float))
    ):
        unit_probs = {k: min(1.0, max(0.0, float(v))) for k, v in probabilities.items()}
        return NormalizedAnswer(
            name=name,
            status=QUESTION_STATUS_VALID,
            answer=answer,
            probabilities=unit_probs,
            confidence=min(1.0, max(0.0, float(confidence))),
            p_selected=unit_probs[answer],
            question_type=spec.type, options_hash=_options_hash(spec),
        )
    # 无效即保留 null 与原始无效事实，不填 confidence=0.5（§8.3）。
    return _invalid(name, spec, tuple(reasons))


def _validate_score(name: str, spec: QuestionSpec, raw: Any) -> NormalizedAnswer:
    if not isinstance(raw, dict):
        return _invalid(name, spec, ("answer_not_object",))
    answer = raw.get("score")
    confidence = raw.get("confidence")
    reasons: list[str] = []
    score_ok = (
        isinstance(answer, (int, float))
        and not isinstance(answer, bool)
        and math.isfinite(float(answer))
    )
    if not score_ok:
        reasons.append("score_not_finite_number")
    conf_ok = _finite_in_unit(confidence) if confidence is not None else False
    if not conf_ok:
        reasons.append("confidence_missing_or_out_of_range")
    if score_ok and conf_ok and isinstance(confidence, (int, float)):
        return NormalizedAnswer(
            name=name, status=QUESTION_STATUS_VALID, answer=str(answer),
            confidence=min(1.0, max(0.0, float(confidence))),
            question_type=spec.type, options_hash=_options_hash(spec),
        )
    return _invalid(name, spec, tuple(reasons))


def _validate_noul(name: str, spec: QuestionSpec, raw: Any) -> NormalizedAnswer:
    # §8.1：Noul 没有同名 confidence——不要求、不因缺它判无效。
    if not isinstance(raw, dict):
        return _invalid(name, spec, ("answer_not_object",))
    # EVO-20261015（P1b-OR R1 根因修复）：官方逐题值字段为 noul（数值 0-1，
    # "the number is the answer and the certainty in one"）；不是自造的 answer 字符串。
    # 值域 [0,1] 按官方契约执行（审查 P2-2：声明与行为不得分叉）。
    noul = raw.get("noul")
    if not isinstance(noul, (int, float)) or isinstance(noul, bool) or not _finite_in_unit(noul):
        return _invalid(name, spec, ("noul_out_of_unit_or_not_finite",))
    return NormalizedAnswer(
        name=name, status=QUESTION_STATUS_VALID, answer=str(noul),
        question_type=spec.type, options_hash=_options_hash(spec),
    )


_VALIDATORS = {
    "choice": _validate_choice,
    "score": _validate_score,
    "noul": _validate_noul,
}


def normalize_response(
    *,
    request: dict[str, Any],
    raw: Any,
    transport_status: str,
) -> NormalizedResponse:
    """按请求的 questions 逐题校验响应；缺题只标 missing，不整批失败（§8.3）。"""
    questions: dict[str, QuestionSpec] = {}
    for name, wire in (request.get("questions") or {}).items():
        questions[name] = QuestionSpec(
            name=name,
            type=str(wire.get("type") or ""),
            instructions=str(wire.get("instructions") or ""),
            criteria=dict(wire.get("criteria") or {}),
        )
    batch_reasons: list[str] = []
    if not isinstance(raw, dict):
        return NormalizedResponse(
            resolved_model=None,
            answers={
                n: NormalizedAnswer(
                    name=n, status=QUESTION_STATUS_CONTRACT_INVALID,
                    invalid_reasons=("response_not_object",),
                    question_type=questions[n].type,
                    options_hash=_options_hash(questions[n]),
                )
                for n in questions
            },
            usage=UsageFacts(status="unknown", reason="response_not_object"),
            transport_status=transport_status,
            raw_hash=_sha256_of(raw if isinstance(raw, (dict, list)) else str(raw)),
            batch_invalid_reasons=("response_not_object",),
        )
    raw_answers = raw.get("answers")
    if not isinstance(raw_answers, dict):
        raw_answers = {}
        batch_reasons.append("answers_missing_or_not_object")
    resolved = raw.get("model")
    if not isinstance(resolved, str) or not resolved.strip():
        resolved = None
        batch_reasons.append("resolved_model_missing")

    normalized: dict[str, NormalizedAnswer] = {}
    for name, spec in questions.items():
        if name not in raw_answers:
            normalized[name] = NormalizedAnswer(
                name=name, status=QUESTION_STATUS_MISSING,
                invalid_reasons=("question_absent_from_response",),
                question_type=spec.type, options_hash=_options_hash(spec),
            )
            continue
        validator = _VALIDATORS.get(spec.type)
        # 未知题型按 contract_invalid 处理（P2-2：公共 API 不抛裸 KeyError）。
        normalized[name] = (
            validator(name, spec, raw_answers[name]) if validator
            else _invalid(name, spec, ("unknown_question_type",))
        )

    raw_usage = raw.get("usage")
    if isinstance(raw_usage, dict):
        def _tok(key: str) -> int | None:
            v = raw_usage.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return v
            return None

        usage = UsageFacts(
            status="valid" if _tok("total_tokens") is not None else "unknown",
            input_tokens=_tok("input_tokens"),
            output_tokens=_tok("output_tokens"),
            total_tokens=_tok("total_tokens"),
            reason="" if _tok("total_tokens") is not None else "usage_fields_incomplete",
        )
    else:
        usage = UsageFacts(status="unknown", reason="usage_missing")

    return NormalizedResponse(
        resolved_model=resolved,
        answers=normalized,
        usage=usage,
        transport_status=transport_status,
        raw_hash=_sha256_of(raw),
        batch_invalid_reasons=tuple(batch_reasons),
    )
