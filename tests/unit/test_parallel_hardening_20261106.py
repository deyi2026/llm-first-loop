"""并行处理完善建议④⑤ 测试（2026-11-06）。"""
from __future__ import annotations

import pytest

from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool


class _FakeRunner:
    def __init__(self, started: dict | None = None) -> None:
        self.calls: list[dict] = []
        self._started = started or {"accepted": True, "child_id": "child-x"}

    def start(self, task=None, **kwargs):
        self.calls.append(dict(kwargs, task=task))
        return self._started


@pytest.mark.parametrize("bad", [0, 201, "x", -1])
def test_spawn_max_rounds_rejects_out_of_range(bad):
    tool = SpawnSubAgentTool(_FakeRunner())
    result = tool.execute(task="do something", max_rounds=bad)
    assert "max_rounds" in result.content
    assert not tool._runner.calls


def test_spawn_max_rounds_passthrough():
    runner = _FakeRunner()
    tool = SpawnSubAgentTool(runner)
    result = tool.execute(task="do something", max_rounds=25)
    assert runner.calls and runner.calls[0]["max_rounds"] == 25
    assert result.content


def test_spawn_without_max_rounds_keeps_callface():
    # 既有调用面零变化：未声明 max_rounds 时该键不出现（tests/test_write_scope_spawn.py 契约）。
    runner = _FakeRunner()
    tool = SpawnSubAgentTool(runner)
    tool.execute(task="do something")
    assert runner.calls and "max_rounds" not in runner.calls[0]


def test_review_rate_limited_returns_structured_retry(monkeypatch):
    import llm_loop.tools.review_host_admission as admission_mod

    class _AlwaysLimited:
        def start(self, task=None, **kwargs):
            return {"accepted": False, "detail": "HTTP 429 rate limit exceeded"}

    admission = admission_mod.HostReviewAdmission()
    admission._runner = _AlwaysLimited()  # 注入 fake runner
    sleeps: list[float] = []
    monkeypatch.setattr(admission_mod.time, "sleep", lambda s: sleeps.append(s))
    out = admission._spawn_reviewer("parent-1", "task", "full_test")
    assert out["accepted"] is False
    assert out["reviewer_failure"] == "reviewer_rate_limited"
    assert out["retry_after_s"] is None
    assert "retry_hint" in out and "窗口" in out["retry_hint"]

def test_runner_start_accepts_max_rounds_kwarg():
    """P1 证据：SubAgentRunner.start 的签名接受 max_rounds（None 透传安全）。"""
    import inspect

    from llm_loop.subagent.runner import SubAgentRunner

    params = inspect.signature(SubAgentRunner.start).parameters
    assert "max_rounds" in params
    assert params["max_rounds"].default is None
