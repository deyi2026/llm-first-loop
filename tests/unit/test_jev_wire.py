"""EVO-20261015 (P1a): Jev wire 契约单元测试——DESIGN §8.2/§8.3 逐条锚定。"""
from __future__ import annotations

import pytest

from llm_loop.knowledge.jev.wire import (
    PROB_SUM_TOLERANCE,
    QuestionSpec,
    build_request,
    normalize_response,
    request_hashes,
)


def _choice(name: str = "premise_linux") -> QuestionSpec:
    return QuestionSpec(
        name=name,
        type="choice",
        instructions="根据 task_snapshot 判断前提。",
        criteria={"yes": "支持", "no": "反对", "unknown": "证据不足"},
    )


def _request(questions: dict[str, QuestionSpec]) -> dict:
    return build_request(
        model="jev-1.13.0",
        state={"subject_ref": "experience:x", "subject_hash": "sha256:x"},
        questions=questions,
    )


def _answer(answer="yes", probs=None, confidence=0.9):
    # EVO-20261015（P1b-OR R1 根因修复）：官方逐题值字段名为 choice，非自造 answer 键。
    return {
        "choice": answer,
        "probabilities": probs or {"yes": 0.9, "no": 0.05, "unknown": 0.05},
        "confidence": confidence,
    }


class TestBuildRequest:
    def test_minimal_form_matches_contract(self):
        req = _request({"premise_linux": _choice()})
        assert set(req) == {"model", "state", "questions"}
        q = req["questions"]["premise_linux"]
        assert set(q) == {"type", "instructions", "criteria"}

    def test_rejects_blank_model_and_empty_questions(self):
        with pytest.raises(ValueError):
            build_request(model=" ", state={}, questions={"a": _choice()})
        with pytest.raises(ValueError):
            build_request(model="m", state={}, questions={})

    def test_choice_requires_criteria(self):
        with pytest.raises(ValueError):
            QuestionSpec(name="x", type="choice", instructions="i").to_wire()


class TestPerQuestionValidation:
    def test_valid_choice_keeps_distribution_and_p_selected_separate(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "jev-res", "answers": {"premise_linux": _answer(confidence=0.77)},
                 "usage": {"total_tokens": 90}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "valid"
        assert a.confidence == pytest.approx(0.77)
        assert a.p_selected == pytest.approx(0.9)
        assert a.confidence != a.p_selected  # 分开存（§8.3）

    def test_semantic_unknown_is_valid_not_contract_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(
                answer="unknown", probs={"yes": 0.05, "no": 0.05, "unknown": 0.90},
                confidence=0.9)}, "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        summary = resp.summary()
        assert summary["valid"] == 1 and summary["contract_invalid"] == 0
        assert summary["semantic_unknown"] == 1  # 两者分开统计（§8.3）

    def test_missing_question_is_missing_not_batch_failure(self):
        req = _request({"premise_linux": _choice(), "premise_2": _choice("premise_2")})
        resp = normalize_response(
            request=req,
            raw={"model": "m",
                 "answers": {"premise_linux": _answer()},  # premise_2 缺席
                 "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        s = resp.summary()
        assert s == {"valid": 1, "missing": 1, "contract_invalid": 0, "semantic_unknown": 0}
        assert resp.answers["premise_2"].answer is None

    def test_prob_sum_off_tolerance_is_contract_invalid_with_nulls(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(
                probs={"yes": 0.7, "no": 0.1, "unknown": 0.1})}, "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "contract_invalid"
        assert a.confidence is None  # 不填 0.5（§8.3）
        assert a.p_selected is None
        assert any("probability_sum_off" in r for r in a.invalid_reasons)

    def test_probability_sum_within_tolerance_is_valid(self):
        req = _request({"premise_linux": _choice()})
        drift = PROB_SUM_TOLERANCE / 2
        probs = {"yes": 0.9 + drift, "no": 0.05, "unknown": 0.05}
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(probs=probs)},
                 "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        assert resp.answers["premise_linux"].status == "valid"

    def test_non_finite_probability_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(
                probs={"yes": float("nan"), "no": 0.05, "unknown": 0.05})},
                 "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "contract_invalid"
        assert "probability_not_finite_or_out_of_unit" in a.invalid_reasons
        assert a.p_selected is None  # P2-5：此前写法恒真，收紧

    def test_confidence_out_of_range_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(confidence=1.5)},
                 "usage": {}},
            transport_status="ok",
        )
        assert resp.answers["premise_linux"].status == "contract_invalid"

    def test_choice_not_in_options_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(answer="maybe")},
                 "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "contract_invalid"
        assert "choice_not_in_options" in a.invalid_reasons

    def test_probabilities_keyset_mismatch_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer(
                probs={"yes": 1.0, "no": 0.0})}, "usage": {}},
            transport_status="ok",
        )
        assert "probabilities_keyset_mismatch" in resp.answers["premise_linux"].invalid_reasons

    def test_noul_without_confidence_is_valid(self):
        # §8.1：Noul 没有同名 confidence——不因缺它判无效。
        q = QuestionSpec(name="caveat", type="noul", instructions="提取 caveat", criteria={})
        req = _request({"caveat": q})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"caveat": {"noul": 0.87}},
                 "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        a = resp.answers["caveat"]
        assert a.status == "valid"
        assert a.confidence is None

    def test_noul_non_number_invalid(self):
        # 官方 noul 为 0-1 数值（TypeSafe primitives：the number is the answer and the
        # certainty in one）；非数值/越界按契约无效。
        q = QuestionSpec(name="caveat", type="noul", instructions="提取", criteria={})
        req = _request({"caveat": q})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"caveat": {"noul": "macOS 未验证"}}, "usage": {}},
            transport_status="ok",
        )
        assert resp.answers["caveat"].status == "contract_invalid"
        assert "noul_out_of_unit_or_not_finite" in resp.answers["caveat"].invalid_reasons
        over = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"caveat": {"noul": 1.5}}, "usage": {}},
            transport_status="ok",
        )
        assert over.answers["caveat"].status == "contract_invalid"

    def test_score_requires_finite_answer(self):
        q = QuestionSpec(name="cov", type="score", instructions="评分", criteria={})
        req = _request({"cov": q})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"cov": {"score": 0.6, "confidence": 0.8}},
                 "usage": {}},
            transport_status="ok",
        )
        assert resp.answers["cov"].status == "valid"
        resp2 = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"cov": {"score": "high", "confidence": 0.8}},
                 "usage": {}},
            transport_status="ok",
        )
        assert resp2.answers["cov"].status == "contract_invalid"


class TestUsageAndModel:
    def test_usage_missing_is_unknown_not_zero(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer()}},
            transport_status="ok",
        )
        assert resp.usage.status == "unknown"
        assert resp.usage.total_tokens is None  # 不计 0（§8.3）

    def test_usage_partial_fields_unknown(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"premise_linux": _answer()},
                 "usage": {"input_tokens": 10}},
            transport_status="ok",
        )
        assert resp.usage.status == "unknown"
        assert resp.usage.reason == "usage_fields_incomplete"

    def test_resolved_model_missing_recorded(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"answers": {"premise_linux": _answer()}, "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        assert resp.resolved_model is None
        assert "resolved_model_missing" in resp.batch_invalid_reasons

    def test_response_not_object_all_questions_invalid(self):
        req = _request({"premise_linux": _choice(), "q2": _choice("q2")})
        resp = normalize_response(request=req, raw="garbage", transport_status="ok")
        s = resp.summary()
        assert s["contract_invalid"] == 2
        assert resp.usage.status == "unknown"
        assert "response_not_object" in resp.batch_invalid_reasons


class TestHashes:
    def test_request_hashes_stable_and_question_scoped(self):
        req1 = _request({"premise_linux": _choice()})
        req2 = _request({"premise_linux": _choice()})
        req3 = _request({"other_premise": _choice("other_premise")})
        assert request_hashes(req1) == request_hashes(req2)
        assert request_hashes(req1)["questions_map_hash"] != request_hashes(req3)["questions_map_hash"]


class TestReviewFindings:
    """代码闸审查 P1-4/P2-2 的钉子测试。"""

    def test_per_question_facts_carry_54_fields(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "jev-res", "answers": {"premise_linux": _answer()},
                 "usage": {"total_tokens": 1}},
            transport_status="ok",
        )
        facts = resp.answers["premise_linux"].to_facts(resolved_model="jev-res")
        assert facts["question_type"] == "choice"
        assert facts["question_schema_version"] == "jev-wire/v1"
        assert facts["options_hash"].startswith("sha256:")
        assert facts["resolved_model"] == "jev-res"  # §5.4：逐题也绑定 resolved model

    def test_missing_question_facts_still_carry_identity_fields(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req, raw={"model": "m", "answers": {}, "usage": {}},
            transport_status="ok",
        )
        facts = resp.answers["premise_linux"].to_facts()
        assert facts["status"] == "missing"
        assert facts["question_type"] == "choice"
        assert facts["options_hash"].startswith("sha256:")

    def test_unknown_question_type_is_contract_invalid_not_crash(self):
        # P2-2：公共 API 对未知题型不抛裸 KeyError。
        # build_request 在构造面就拒绝未知题型（to_wire ValueError）；
        # normalize_response 是导出的公共 API——手工构造请求防手绕，仍须不崩。
        req = {"model": "m", "state": {"subject_ref": "x"},
               "questions": {"weird": {"type": "quantum", "instructions": "i",
                                       "criteria": {}}}}
        resp = normalize_response(
            request=req, raw={"model": "m", "answers": {"weird": {"choice": "x"}},
                              "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["weird"]
        assert a.status == "contract_invalid"
        assert "unknown_question_type" in a.invalid_reasons


class TestOfficialAnswerFieldNames:
    """EVO-20261015（P1b-OR R1 根因修复）钉子：官方逐题值字段名 choice/score/noul。

    R1（§11.6）6/6 题 contract_invalid 的根因是旧实现读自造的 answer 键
    （DESIGN 附录 C v0.8.8）。本组钉住：仅存在旧键时必须显式 invalid，
    不允许静默通过；官方字段可用时不受旧键干扰。
    """

    def test_legacy_answer_key_without_choice_is_contract_invalid(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m",
                 "answers": {"premise_linux": {
                     "answer": "yes",  # 旧实现的误读键：官方契约无此字段
                     "probabilities": {"yes": 0.9, "no": 0.05, "unknown": 0.05},
                     "confidence": 0.9}},
                 "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "contract_invalid"
        assert "choice_not_in_options" in a.invalid_reasons

    def test_legacy_answer_key_is_ignored_when_choice_present(self):
        req = _request({"premise_linux": _choice()})
        resp = normalize_response(
            request=req,
            raw={"model": "m",
                 "answers": {"premise_linux": {
                     "answer": "no",  # 干扰项：取值必须来自 choice，不读旧键
                     "choice": "yes",
                     "probabilities": {"yes": 0.9, "no": 0.05, "unknown": 0.05},
                     "confidence": 0.9}},
                 "usage": {}},
            transport_status="ok",
        )
        a = resp.answers["premise_linux"]
        assert a.status == "valid"
        assert a.answer == "yes"

    def test_score_reads_official_score_field_and_rejects_legacy_key(self):
        q = QuestionSpec(name="cov", type="score", instructions="评分", criteria={})
        req = _request({"cov": q})
        ok = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"cov": {"score": 0.6, "confidence": 0.8}},
                 "usage": {}},
            transport_status="ok",
        )
        assert ok.answers["cov"].status == "valid"
        legacy = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"cov": {"answer": 0.6, "confidence": 0.8}},
                 "usage": {}},
            transport_status="ok",
        )
        assert legacy.answers["cov"].status == "contract_invalid"

    def test_noul_reads_official_number_field_and_rejects_legacy_key(self):
        q = QuestionSpec(name="nx", type="noul", instructions="i", criteria={})
        req = _request({"nx": q})
        ok = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"nx": {"noul": 0.42}}, "usage": {}},
            transport_status="ok",
        )
        assert ok.answers["nx"].status == "valid"
        assert ok.answers["nx"].confidence is None
        legacy = normalize_response(
            request=req,
            raw={"model": "m", "answers": {"nx": {"answer": "文本"}}, "usage": {}},
            transport_status="ok",
        )
        assert legacy.answers["nx"].status == "contract_invalid"
