"""Host-owned reviewer model policy: configurable, immutable, and fail-closed."""

from __future__ import annotations

from llm_loop.config import load_settings
from llm_loop.tools import review_host_admission as rha
from llm_loop.tools.review_host_admission import HostReviewAdmission, ReviewAdmissionTool
from tests.unit.test_review_host_admission import FakeChildRunner, _repo


class RecordingRunner(FakeChildRunner):
    def __init__(self) -> None:
        super().__init__()
        self.models: list[str] = []

    def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
        self.models.append(kwargs["model"])
        result = super().start(task, **kwargs)
        if result.get("accepted"):
            result["model"] = kwargs["model"]
        return result


def test_configured_deepseek_is_used_by_host_not_parent(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(
        reviewer_models_raw="deepseek/deepseek-v4-flash,glm/glm-5.3"
    )
    runner = RecordingRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is True
    assert runner.models == ["deepseek/deepseek-v4-flash"]
    assert receipt["reviewer_model"] == "deepseek/deepseek-v4-flash"
    assert receipt["review_budget"]["models"] == [
        "deepseek/deepseek-v4-flash", "glm/glm-5.3"
    ]
    assert host._records[receipt["child_id"]].reviewer_model == "deepseek/deepseek-v4-flash"
    assert "model" not in ReviewAdmissionTool.parameters["properties"]


def test_initial_spawn_tries_next_configured_model_on_rate_limit(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(
        reviewer_models_raw="glm/glm-5.3,deepseek/deepseek-v4-flash"
    )
    runner = RecordingRunner()
    runner.refusals = ["429 rate limit"]
    host.attach_runner(runner)
    monkeypatch.setattr(rha.time, "sleep", lambda _: None)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is True
    assert runner.models == ["glm/glm-5.3", "deepseek/deepseek-v4-flash"]
    assert receipt["reviewer_model"] == "deepseek/deepseek-v4-flash"
    assert host._records[receipt["child_id"]].reviewer_model == "deepseek/deepseek-v4-flash"


def test_invalid_explicit_model_list_does_not_silently_fallback(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    for raw in ("glm/glm-5.3,,deepseek/deepseek-v4-flash", "deepseek-v4-flash", "bad/model\nother"):
        host = HostReviewAdmission(reviewer_models_raw=raw)
        runner = RecordingRunner()
        host.attach_runner(runner)
        receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
        assert receipt["accepted"] is False
        assert receipt["reason"] == "reviewer_models_invalid"
        assert runner.models == []


def test_unconfigured_reviewer_models_denies_start(tmp_path) -> None:  # noqa: ANN001
    """P0：生产不写死 Reviewer 模型。未配置 ⇒ DENIED 且不 spawn 任何 child。"""
    repo = _repo(tmp_path)
    host = HostReviewAdmission()  # 不传模型：等价于 operator 未配置
    runner = RecordingRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is False
    assert receipt["reason"] == "reviewer_models_unconfigured"
    assert runner.models == []
    assert host._records == {}


def test_reviewer_models_from_settings_not_global_env(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LFL_REVIEWER_MODELS", "glm/glm-5.3")
    settings = load_settings({
        "LLM_API_KEY": "test-placeholder",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LFL_REVIEWER_MODELS": "deepseek/deepseek-v4-flash,glm/glm-5.3",
    })
    assert settings.reviewer_models_raw == "deepseek/deepseek-v4-flash,glm/glm-5.3"


def test_resolved_model_mismatch_refuses_review(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")

    class WrongModelRunner(RecordingRunner):
        def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
            result = super().start(task, **kwargs)
            result["model"] = "glm/glm-5.3"
            return result

    runner = WrongModelRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is False
    assert receipt["reason"] == "reviewer_model_mismatch"
    assert host._records == {}


def test_factory_attaches_host_configured_reviewer_chain() -> None:
    from llm_loop.factory import _configure_review_admission

    class Registry:
        def set_review_admission(self, authority):  # noqa: ANN001, ANN201
            self.authority = authority

    settings = load_settings({
        "LLM_API_KEY": "test-placeholder",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LFL_REVIEWER_MODELS": "deepseek/deepseek-v4-flash,glm/glm-5.3",
    })
    registry = Registry()
    previous = HostReviewAdmission.current()
    try:
        host = _configure_review_admission(registry, object(), settings)
        assert registry.authority is host
        assert HostReviewAdmission.current() is host
        assert host._reviewer_models == (
            "deepseek/deepseek-v4-flash", "glm/glm-5.3"
        )
    finally:
        HostReviewAdmission.set_authority(previous)


def test_missing_resolved_model_is_denied_even_if_child_started(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")

    class MissingModelRunner(RecordingRunner):
        def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
            result = super().start(task, **kwargs)
            result.pop("model", None)
            return result

    runner = MissingModelRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is False
    assert receipt["reason"] == "reviewer_model_mismatch"
    assert host._records == {}


def test_invalid_model_config_keeps_empty_chain_and_fails_closed() -> None:
    """非法配置同样不得回填任何内置模型链（P0：模型身份只来自 operator 配置）。"""
    host = HostReviewAdmission(reviewer_models_raw="bad/model,,other/model")
    assert host._reviewer_model_error == "reviewer_models_invalid"
    assert host._reviewer_models == ()


def test_preflight_budget_covers_smallest_configured_fallback() -> None:
    host = HostReviewAdmission(reviewer_models_raw="glm/glm-5.3,deepseek/deepseek-v4-flash")

    class BudgetRunner(RecordingRunner):
        def child_input_budget_chars(self, model_ref, *, chars_per_token=None):  # noqa: ANN001, ANN201, ARG002
            return 120_000 if model_ref.startswith("glm/") else 2_000

    host.attach_runner(BudgetRunner())
    chars, model_budget, cap = host._input_budget("x" * 3_000)
    assert chars == 3_000
    assert model_budget == 2_000
    assert cap == 1_960  # fail before an oversized fallback could be launched


def test_async_retry_switches_model_and_updates_frozen_record(tmp_path) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(
        reviewer_models_raw="glm/glm-5.3,deepseek/deepseek-v4-flash"
    )

    class SequenceRunner(RecordingRunner):
        def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
            result = super().start(task, **kwargs)
            if result.get("accepted"):
                result["child_id"] = f"child-{len(self.models)}"
            return result

    runner = SequenceRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is True
    child_id = receipt["child_id"]
    retry = host._respawn_reviewer("parent", child_id, "reviewer_rate_limited", 240)
    assert retry is not None
    assert retry["qualification"] == "pending"
    assert retry["auto_retry"]["model"] == "deepseek/deepseek-v4-flash"
    assert runner.models == ["glm/glm-5.3", "deepseek/deepseek-v4-flash"]
    assert host._records[child_id].reviewer_model == "deepseek/deepseek-v4-flash"
    assert host._records[child_id].live_child_id == "child-2"


def test_async_retry_advances_after_initial_fallback(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw=(
        "glm/glm-5.3,deepseek/deepseek-v4-flash,minimax/MiniMax-M3.1-Flash"
    ))

    class SequenceRunner(RecordingRunner):
        def start(self, task: str, **kwargs):  # noqa: ANN001, ANN201
            result = super().start(task, **kwargs)
            if result.get("accepted"):
                result["child_id"] = f"child-{len(self.models)}"
            return result

    runner = SequenceRunner()
    runner.refusals = ["429 rate limit"]
    host.attach_runner(runner)
    monkeypatch.setattr(rha.time, "sleep", lambda _: None)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is True
    assert receipt["reviewer_model"] == "deepseek/deepseek-v4-flash"
    retry = host._respawn_reviewer("parent", receipt["child_id"], "reviewer_timeout", 240)
    assert retry is not None and retry["qualification"] == "pending"
    assert runner.models == [
        "glm/glm-5.3", "deepseek/deepseek-v4-flash", "minimax/MiniMax-M3.1-Flash"
    ]
    assert host._records[receipt["child_id"]].reviewer_model == "minimax/MiniMax-M3.1-Flash"


def test_real_subagent_runner_attests_configured_model(tmp_path) -> None:  # noqa: ANN001
    from llm_loop.core.run_context import current_session_id
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.subagent.runner import SubAgentRunner
    from llm_loop.tools.registry import ToolRegistry
    from tests.unit.test_review_host_runner_live import _HostTaskFakeLLM, _resolver_for

    repo = _repo(tmp_path)
    llm = _HostTaskFakeLLM()  # deterministic fake, no provider/network
    event_store = EventStore(tmp_path / "events", enabled=True)
    runner = SubAgentRunner(
        llm=llm, registry=ToolRegistry(),
        session_store=SessionStore(tmp_path / "sessions", event_store=event_store),
        max_iterations=1, llm_resolver=_resolver_for(llm),
    )
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is True  # requires real runner's model echo
    assert receipt["reviewer_model"] == "deepseek/deepseek-v4-flash"
    token = current_session_id.set("parent")
    try:
        for _ in range(100):
            ok, _, state = runner.result_current(receipt["child_id"], wait_seconds=0.05)
            assert ok
            if state["state"] != "running":
                break
        else:
            raise AssertionError("reviewer child did not settle")
    finally:
        current_session_id.reset(token)
    assert host.poll("parent", receipt["child_id"])["qualification"] == "REVISE"


def test_model_chain_exhaustion_never_repeats_same_model(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """P1-3：列表耗尽后不得 clamp 回末位重试同一 model。"""
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="glm/glm-5.3")
    runner = RecordingRunner()
    runner.refusals = [
        "1311 当前订阅套餐暂未开放该模型权限",
        "1311 当前订阅套餐暂未开放该模型权限",
    ]
    host.attach_runner(runner)
    monkeypatch.setattr(rha.time, "sleep", lambda _: None)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    assert receipt["accepted"] is False
    assert receipt["reviewer_failure"] == "reviewer_models_exhausted"
    assert runner.models == ["glm/glm-5.3"]  # 同一 model 只尝试一次
    assert host._records == {}


def test_async_retry_at_chain_tail_entitlement_fails_closed(tmp_path) -> None:  # noqa: ANN001
    """P1-3：链尾 + 无权限(1311) ⇒ 直接 fail closed，不得重试同一 model。"""
    from dataclasses import replace

    repo = _repo(tmp_path)
    host = HostReviewAdmission(
        reviewer_models_raw="glm/glm-5.3,deepseek/deepseek-v4-flash"
    )
    runner = RecordingRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    child = receipt["child_id"]
    host._records[child] = replace(
        host._records[child], reviewer_model="deepseek/deepseek-v4-flash",
    )
    assert host._respawn_reviewer("parent", child, "reviewer_model_entitlement", 600.0) is None
    assert runner.models == ["glm/glm-5.3"]


def test_async_retry_at_chain_tail_rate_limit_retries_same_model(tmp_path) -> None:  # noqa: ANN001
    """链尾 + 429/超时属瞬时故障：允许同一 model 有界重试一次（P1-3 只管无权限）。"""
    from dataclasses import replace

    repo = _repo(tmp_path)
    host = HostReviewAdmission(
        reviewer_models_raw="glm/glm-5.3,deepseek/deepseek-v4-flash"
    )
    runner = RecordingRunner()
    host.attach_runner(runner)
    receipt = host.start("parent", "full_test", workdir=str(repo), command="pytest -q")
    child = receipt["child_id"]
    host._records[child] = replace(
        host._records[child], reviewer_model="deepseek/deepseek-v4-flash",
    )
    retry = host._respawn_reviewer("parent", child, "reviewer_rate_limited", 600.0)
    assert retry is not None
    # 链尾重试仍用同一个（最后一个）model，不消耗也不回退列表。
    assert retry["auto_retry"]["model"] == "deepseek/deepseek-v4-flash"
    assert runner.models == ["glm/glm-5.3", "deepseek/deepseek-v4-flash"]


def test_pass_denied_when_provider_observed_model_missing(tmp_path) -> None:  # noqa: ANN001
    """P1-1：PASS 文本 + 缺失 provider 自报 model ⇒ DENIED（不能用 label 自证）。"""
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")
    runner = FakeChildRunner()
    runner.observed_model = ""
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    polled = host.poll("author-1", issued["child_id"])
    assert polled["qualification"] == "DENIED"
    assert polled["reason"] == "reviewer_model_unattested"


def test_pass_denied_on_requested_a_responded_b(tmp_path) -> None:  # noqa: ANN001
    """P1-1 负向：请求 deepseek、provider 实际回 glm ⇒ DENIED reviewer_model_mismatch。"""
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")
    runner = FakeChildRunner()
    runner.observed_model = "glm/glm-5.3"
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    polled = host.poll("author-1", issued["child_id"])
    assert polled["qualification"] == "DENIED"
    assert polled["reason"] == "reviewer_model_mismatch"


def test_policy_drift_blocks_mint_and_consume(tmp_path) -> None:  # noqa: ANN001
    """P1-2：start 冻结 digest；策略漂移后既不能 mint 新资格，也不能消费旧 grant。"""
    repo = _repo(tmp_path)
    host = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")
    runner = FakeChildRunner()
    host.attach_runner(runner)

    # (a) 漂移发生在 mint 之前 ⇒ poll DENIED review_policy_changed
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    child = issued["child_id"]
    assert host._records[child].policy_digest == host._policy_digest
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    host._policy_digest = "drifted-digest"
    polled = host.poll("author-1", child)
    assert polled["qualification"] == "DENIED"
    assert polled["reason"] == "review_policy_changed"

    # (b) 漂移发生在 grant 之后 ⇒ consume 拒绝旧资格
    host2 = HostReviewAdmission(reviewer_models_raw="deepseek/deepseek-v4-flash")
    runner2 = FakeChildRunner()
    host2.attach_runner(runner2)
    issued2 = host2.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    child2 = issued2["child_id"]
    runner2.answer = (
        f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued2['candidate_sha256']}"
    )
    runner2.state = "completed"
    assert host2.poll("author-1", child2)["qualification"] == "PASS"
    row = host2._records[child2]
    assert row.reviewer_observed_model == "deepseek/deepseek-v4-flash"
    host2._policy_digest = "drifted-digest"
    denied = host2._consume("author-1", "full_test", row.target, row.sha)
    assert denied.allowed is False
    assert "策略" in denied.reason
