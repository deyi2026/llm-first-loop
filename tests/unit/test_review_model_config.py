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


def test_invalid_model_config_preserves_nonempty_internal_invariant() -> None:
    host = HostReviewAdmission(reviewer_models_raw="bad/model,,other/model")
    assert host._reviewer_model_error == "reviewer_models_invalid"
    assert host._reviewer_models  # public start still fails closed


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
