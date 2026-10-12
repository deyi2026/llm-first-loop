"""Offline-only execution-knowledge smoke: provider, tool and usage fences.

Do not send these cases to the deployed Web endpoint.  They intentionally use
the real LoopEngine with a FakeLLM, an EMPTY tool registry and an isolated
pytest fixture data root. The CLI wrapper additionally kills the whole worker
process group at its wall deadline.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from collections import Counter
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any

import pytest

from llm_loop.config import ToolRuntimeSettings
from llm_loop.core.message import ToolCall
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.registry import ToolRegistry


@dataclass(frozen=True)
class _SmokeLimits:
    provider_calls: int = 1
    physical_tools: int = 0
    iterations: int = 1
    input_tokens: int = 2_000
    output_tokens: int = 128
    request_bytes: int = 80_000
    child_wall_seconds: float = 20.0


_LIMITS = _SmokeLimits()


class _BoundedFakeProvider:
    """Check *before* provider dispatch, then verify explicit synthetic usage."""

    def __init__(self, responder: Any) -> None:
        self.responder = responder
        self.calls = 0

    def chat(
        self, messages: list[dict], tools: list[dict], *,
        timeout_s: float | None = None, model: str | None = None,
    ) -> LLMResponse:
        self.calls += 1
        assert self.calls <= _LIMITS.provider_calls, "smoke provider call budget exceeded"
        assert not tools, "smoke must never advertise callable tools"
        assert len(json.dumps(messages, ensure_ascii=False).encode()) <= _LIMITS.request_bytes
        response = self.responder(
            messages, tools, timeout_s=timeout_s, model=model,
        )
        assert not response.tool_calls, "smoke rejects hallucinated tool calls"
        assert 0 < response.prompt_tokens <= _LIMITS.input_tokens, (
            "provider usage unavailable or input budget exceeded"
        )
        assert 0 <= response.completion_tokens <= _LIMITS.output_tokens, (
            "output token budget exceeded"
        )
        return response


def _build_bounded(
    *, build_test_engine: Any, fake_settings: Any, monkeypatch: Any,
    tmp_path: Any, mode: str, scripted: LLMResponse,
) -> tuple[Any, Any, _BoundedFakeProvider, EventStore, list[str]]:
    engine, fake = build_test_engine([scripted])
    engine.settings = replace(
        engine.settings,
        max_iterations=_LIMITS.iterations,
        tool_runtime=replace(ToolRuntimeSettings(), knowledge_advisor_mode=mode),
    )
    # Dynamic strategy enforces a minimum of five for user-requested changes.
    # This is a strictly offline test-only fixed Settings value, not a new
    # production policy or a covert adjust_strategy override.
    assert engine.runtime is not None
    engine.runtime._settings = engine.settings
    assert engine._runtime_max_iterations() == _LIMITS.iterations

    # Real registry is deliberately replaced, rather than merely telling the
    # model not to use tools. A hallucinated tool must have no executable owner.
    engine.registry = ToolRegistry()
    assert engine.registry.schemas() == []
    executed: list[str] = []

    def forbidden_execute(*args: Any, **kwargs: Any) -> Any:
        executed.append("execute_many")
        raise AssertionError("physical tool execution forbidden by smoke harness")

    monkeypatch.setattr(engine.registry, "execute_many", forbidden_execute)
    original_chat = fake.chat
    budget = _BoundedFakeProvider(original_chat)
    monkeypatch.setattr(fake, "chat", budget.chat)

    def network_denied(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("offline smoke attempted network access")

    # Fixture construction happens before network denial. Actual model/tool
    # execution never has a socket path, even if someone changes FakeLLM.
    monkeypatch.setattr(socket.socket, "connect", network_denied)
    events = EventStore(tmp_path / "smoke-event-log")
    engine._event_store = events
    hints: list[str] = []
    assert engine.corrections is not None

    def records(*, kind: str, **_unused: Any) -> list[dict[str, str]]:
        hints.append(kind)
        if kind == "method":
            return [{"method_ref": "method:offline-known", "name": "pytest repair",
                     "status": "candidate"}]
        if kind == "experience":
            return [{"experience_ref": "experience:offline-known", "record_kind": "experience",
                     "verification_state": "verified", "summary": "pytest failure",
                     "status": "active"}]
        return []

    engine.corrections._search_records_fn = records
    return engine, fake, budget, events, executed


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_offline_web_one_provider_no_tools_and_no_reference(
    build_test_engine: Any, fake_settings: Any,
    monkeypatch: Any, tmp_path: Any, mode: str,
) -> None:
    start = monotonic()
    engine, fake, budget, events, executed = _build_bounded(
        build_test_engine=build_test_engine,
        fake_settings=fake_settings,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        mode=mode,
        scripted=LLMResponse(
            content="离线测试已完成", tool_calls=[], provider="fake",
            prompt_tokens=120, completion_tokens=6,
        ),
    )
    sid = engine.session.create()
    result = engine.run(sid, "pytest pytest pytest", ingress=issue_ingress("web"))
    counts = Counter(event.type for event in events.read(sid))

    assert result.final_answer == "离线测试已完成"
    assert budget.calls == 1 and len(fake.calls) == 1
    assert fake.calls[0]["tools"] == []
    assert len(executed) <= _LIMITS.physical_tools
    assert counts["knowledge.discovery"] == (1 if mode == "shadow" else 0)
    assert counts["knowledge.reference_prepared"] == 0
    assert counts["tool.execution.started"] == 0
    assert counts["provider.call.opened"] == counts["provider.call.settled"]
    assert not list(tmp_path.rglob("schedule.json"))
    assert monotonic() - start < _LIMITS.child_wall_seconds


def test_provider_usage_and_call_caps_fail_closed() -> None:
    gate = _BoundedFakeProvider(
        lambda _m, _t, **_kw: LLMResponse(
            content="not allowed", tool_calls=[], provider="fake",
            prompt_tokens=_LIMITS.input_tokens + 1,
            completion_tokens=1,
        )
    )
    with pytest.raises(AssertionError, match="input budget"):
        gate.chat([], [])
    with pytest.raises(AssertionError, match="call budget"):
        gate.chat([], [])


def test_tool_projection_cap_rejects_nonempty_tool_schema_before_dispatch() -> None:
    gate = _BoundedFakeProvider(lambda *_a, **_kw: pytest.fail("provider must not run"))
    with pytest.raises(AssertionError, match="never advertise callable tools"):
        gate.chat([], [{"type": "function", "function": {"name": "schedule"}}])
    assert gate.calls == 1


def test_hallucinated_schedule_is_rejected_before_loop_tool_execution() -> None:
    gate = _BoundedFakeProvider(
        lambda _m, _t, **_kw: LLMResponse(
            content="", provider="fake",
            tool_calls=[ToolCall(
                id="offline-never-execute",
                name="schedule",
                arguments={"wake": True, "after": 5, "message": "unsafe"},
            )],
            prompt_tokens=50,
            completion_tokens=15,
        )
    )
    with pytest.raises(AssertionError, match="hallucinated tool calls"):
        gate.chat([{"role": "user", "content": "pytest pytest pytest"}], [])


def test_parent_wall_watchdog_terminates_descendant_group(tmp_path: Any) -> None:
    from scripts.shadow_smoke_offline import _run_isolated

    marker = tmp_path / "unwanted-grandchild-survived"
    grandchild = (
        "import time; from pathlib import Path; "
        f"time.sleep(1); Path({str(marker)!r}).write_text('ran')"
    )
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);"
        "time.sleep(10)"
    )
    start = monotonic()
    code, output = _run_isolated(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        env={"PATH": ""},
        timeout_seconds=0.25,
    )
    assert code == 124 and "hard wall deadline" in output
    assert monotonic() - start < 3
    # A lingering grandchild would make this marker in one second. The entire
    # POSIX child session was signalled, not just the parent Python process.
    time.sleep(1.05)
    assert not marker.exists()
