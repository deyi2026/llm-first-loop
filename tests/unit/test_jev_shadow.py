"""EVO-20261015 (P1a): shadow runner 测试——不改检索输出、fail-open、单次尝试（§6.3/§5.4）。"""
from __future__ import annotations

import json

from llm_loop.knowledge.jev import (
    JevShadowRunner,
    MockJevTransport,
    OutboundPolicy,
    PolicyGuard,
    QuestionSpec,
)
from llm_loop.knowledge.jev.shadow import EVENT_KIND, TASK_BENEFIT


def _question() -> QuestionSpec:
    return QuestionSpec(
        name="premise_linux", type="choice", instructions="判断前提",
        criteria={"yes": "支持", "no": "反对", "unknown": "证据不足"},
    )


def _runner(transport, events, policy=None):
    return JevShadowRunner(
        transport=transport,
        guard=PolicyGuard(policy=policy or OutboundPolicy(max_requests=3)),
        event_append=lambda s, k, p: events.append({"session": s, "kind": k, "payload": p}),
        session_id="sess-1", run_ref="run-1",
    )


def _judge(runner, allowlist=frozenset({"target_os", "source_ref", "source_excerpt"})):
    return runner.judge_premises(
        subject_ref="experience:x", subject_hash="sha256:x",
        task_snapshot={"target_os": "linux", "source_ref": "e://1",
                       "source_excerpt": "Ubuntu 22.04 实测"},
        allowlist=allowlist, questions={"premise_linux": _question()},
    )


class TestRecordedEvent:
    def test_minimal_fields_per_attempt_and_question(self):
        events: list[dict] = []
        transport = MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved",
            "answers": {"premise_linux": {
                "choice": "yes",
                "probabilities": {"yes": 0.9, "no": 0.05, "unknown": 0.05},
                "confidence": 0.9}},
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        })
        out = _judge(_runner(transport, events))
        assert out.status == "recorded"
        assert events and events[0]["kind"] == EVENT_KIND
        p = events[0]["payload"]
        # §5.4 每个物理尝试最小字段（含发出时间，审查 P1-4）
        for key in ("attempt_id", "request_hash", "questions_map_hash",
                    "t_queued", "t_sent", "t_end", "transport_status",
                    "attempt_seq", "usage"):
            assert key in p, key
        # §5.4 每个逻辑题最小字段（审查 P1-4 补全 4 项）
        q = p["questions"]["premise_linux"]
        for key in ("question_instance_id", "question_type", "question_schema_version",
                    "options_hash", "resolved_model", "status", "answer",
                    "probabilities", "confidence", "p_selected"):
            assert key in q, key
        assert p["resolved_model"] == "jev-1.13.0-resolved"  # 绑定 resolved model
        assert p["task_benefit"] == TASK_BENEFIT == "not_evaluated"
        assert p["baseline_unchanged"] is True and p["ordering_effect"] == "none"

    def test_attempt_id_unique_per_judgment(self):
        events: list[dict] = []
        runner = _runner(MockJevTransport(script=[
            {"model": "m", "answers": {}, "usage": {}}] * 2), events)
        o1 = _judge(runner)
        o2 = _judge(runner)
        assert o1.attempt_id != o2.attempt_id


class TestFailOpenAndNoRetry:
    def test_transport_error_single_attempt_no_exception(self):
        events: list[dict] = []
        transport = MockJevTransport(script=[RuntimeError("connection refused")])
        runner = _runner(transport, events)
        out = _judge(runner)
        assert out.status == "transport_failed"
        assert out.transport_status == "transport_error"
        assert transport.attempt_count() == 1  # 无重试（§8.4）
        assert events[0]["payload"]["status"] == "transport_failed"

    def test_timeout_single_attempt(self):
        events: list[dict] = []
        transport = MockJevTransport(default_response={"model": "m"}, latency_s=5.0)
        runner = _runner(transport, events)
        out = _judge(runner)
        assert out.status == "transport_failed"
        assert out.transport_status == "timeout"
        assert transport.attempt_count() == 1

    def test_event_append_failure_observable_not_silent(self):
        # P1-5：事件落库失败此前静默——event_persisted=False 显式可观测。
        def boom(s, k, p):
            raise OSError("eventstore down")
        runner = JevShadowRunner(
            transport=MockJevTransport(default_response={"model": "m", "answers": {}}),
            guard=PolicyGuard(), event_append=boom, session_id="s", run_ref="r",
        )
        out = _judge(runner)
        assert out.status == "recorded"  # 判断事实仍返回；事件失败不阻断
        assert out.event_persisted is False  # 但不静默：持久化丢失可见

    def test_event_persisted_true_on_success(self):
        events: list[dict] = []
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "m", "answers": {}, "usage": {}}), events))
        assert out.status == "recorded"
        assert out.event_persisted is True

    def test_budget_refusal_no_transport_attempt(self):
        events: list[dict] = []
        transport = MockJevTransport(default_response={"model": "m"})
        runner = _runner(transport, events, policy=OutboundPolicy(max_requests=0))
        out = _judge(runner)
        assert out.status == "budget_refused"
        assert transport.attempt_count() == 0  # 拒绝在发送前
        assert events[0]["payload"]["status"] == "budget_refused"

    def test_projection_unsafe_no_transport(self):
        events: list[dict] = []
        transport = MockJevTransport(default_response={"model": "m"})
        runner = _runner(transport, events)
        # allowlist 放进一个红线键 → 投影含 rules → 守卫拒绝
        out = runner.judge_premises(
            subject_ref="experience:x", subject_hash="sha256:x",
            task_snapshot={"rules": "RULE-AI-01 全文"},
            allowlist=frozenset({"rules"}),
            questions={"premise_linux": _question()},
        )
        assert out.status == "projection_unsafe"
        assert transport.attempt_count() == 0


class TestNoRetrievalSurface:
    """§6.3/§11 验收：OFF/shadow 检索输出一致——runner 无修改检索输出的 API 面，且未被任何检索路径引用。"""

    def test_runner_api_has_no_candidate_or_ordering_surface(self):
        import inspect
        for name, member in inspect.getmembers(JevShadowRunner, inspect.isfunction):
            params = inspect.signature(member).parameters
            joined = " ".join(params).lower()
            banned = ("candidate", "ranking", "rerank", "sort_list", "result_set")
            assert not any(word in joined for word in banned), (
                f"{name} exposes retrieval surface: {list(params)}"
            )

    def test_event_payload_carries_no_candidate_list(self):
        # P2-5：原"baseline 逐字节不变"测试恒真（baseline 从未进入 runner），删除；
        # 真实保障机制 = (a) runner API 无候选集面（上一个测试）+ (b) src 无 live 接线
        # （test_jev_fixtures.py 守卫）+ (c) 事件载荷本身不携带候选集/重排指令。
        events: list[dict] = []
        baseline = [{"ref": "experience:a", "title": "A"}]
        _judge(_runner(MockJevTransport(default_response={"model": "m"}), events))
        text = json.dumps(events[0]["payload"], ensure_ascii=False)
        assert "candidates" not in text
        assert baseline[0]["title"] not in text  # 基线内容不进事件

    def test_shadow_payload_carries_no_reordering_instruction(self):
        events: list[dict] = []
        _judge(_runner(MockJevTransport(default_response={
            "model": "m", "answers": {"premise_linux": {
                "choice": "no", "probabilities": {"yes": 0.05, "no": 0.9, "unknown": 0.05},
                "confidence": 0.9}}, "usage": {}}), events))
        text = json.dumps(events[0]["payload"], ensure_ascii=False)
        assert "reorder" not in text and "rerank" not in text
        assert events[0]["payload"]["ordering_effect"] == "none"


class TestRawAnswersExcerpt:
    """R1 教训（DESIGN v0.8.8）：逐题无效时事件/outcome 持久化官方 answers 原文摘录。

    §11.6 轮 6/6 题 contract_invalid 却无可诊断 raw（仅 hash）——本组钉住：
    无效即摘录、全 valid 不复制 payload。
    """

    def test_invalid_question_persists_raw_answers_excerpt(self):
        events = []
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved",
            "answers": {"premise_linux": {
                "choice": "maybe",  # 不在 options → contract_invalid
                "probabilities": {"yes": 0.34, "no": 0.33, "unknown": 0.33},
                "confidence": 0.5}},
            "usage": {}}), events))
        assert out.status == "recorded"
        assert out.raw_answers_excerpt and "maybe" in out.raw_answers_excerpt
        payload_excerpt = events[0]["payload"]["raw_answers_excerpt"]
        assert payload_excerpt and "maybe" in payload_excerpt

    def test_missing_answer_object_persists_empty_answers_excerpt(self):
        events = []
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved", "answers": {}}), events))
        assert out.status == "recorded"
        # answers 为空 dict：缺题批量无效，摘录为空对象的规范序列化 "{}"
        assert out.raw_answers_excerpt == "{}"
        assert events[0]["payload"]["raw_answers_excerpt"] == "{}"

    def test_raw_without_answers_key_yields_empty_excerpt(self):
        events = []
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved"}), events))
        assert out.status == "recorded"
        # 早退分支：raw 无 answers 键（批级无效）→ 摘录空串不抛错
        assert out.raw_answers_excerpt == ""
        assert events[0]["payload"]["raw_answers_excerpt"] == ""

    def test_excerpt_is_capped_and_truncation_marked(self):
        events = []
        huge = "x" * 9000
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved",
            "answers": {"premise_linux": {
                "choice": "maybe",  # 无效触发摘录
                "probabilities": {"yes": 0.34, "no": 0.33, "unknown": 0.33},
                "confidence": 0.5,
                "noise": huge}},  # 超限内容验证截断
            "usage": {}}), events))
        excerpt = events[0]["payload"]["raw_answers_excerpt"]
        assert out.raw_answers_excerpt == excerpt
        assert len(excerpt) <= 4096 + 30  # cap + 截断标注上限
        assert "truncated(" in excerpt
        assert excerpt.startswith('{"premise_linux"')  # 前缀保真

    def test_all_valid_omits_excerpt(self):
        events = []
        out = _judge(_runner(MockJevTransport(default_response={
            "model": "jev-1.13.0-resolved",
            "answers": {"premise_linux": {
                "choice": "yes",
                "probabilities": {"yes": 0.9, "no": 0.05, "unknown": 0.05},
                "confidence": 0.9}},
            "usage": {"total_tokens": 1}}), events))
        assert out.status == "recorded"
        assert out.raw_answers_excerpt == ""
        assert events[0]["payload"]["raw_answers_excerpt"] == ""
