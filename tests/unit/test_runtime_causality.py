from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.loop.engine import LoopEngine
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMResponse
from llm_loop.runtime.causality import (
    build_runtime_causal_snapshot,
    effective_generation_contract,
    source_tree_fingerprint,
)
from llm_loop.tools.registry import ToolRegistry


@dataclass
class _CaptureLLM:
    calls: list[tuple[list[dict], list[dict]]]
    provider: str = "fake"
    model: str = "m"
    max_tokens: int = 8192
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    min_p: float = 0.0
    wire_protocol: str = "openai"
    send_tool_choice: bool = True
    reasoning_split: bool = False
    api_key: str = "SHOULD-NOT-LEAK"

    def chat_stream(self, messages, tools, **kwargs):
        del kwargs
        self.calls.append((messages, tools))

        def _gen():
            yield from ()
            return LLMResponse(content="done", tool_calls=[], provider="fake")

        return _gen()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )


def _run_once(tmp_path: Path, *, events: bool) -> tuple[list[dict], list[dict], list[Any]]:
    settings = _settings(tmp_path)
    event_store = EventStore(tmp_path / "events") if events else None
    sessions = SessionStore(tmp_path / "sessions", event_store=event_store)
    llm = _CaptureLLM([])
    engine = LoopEngine(
        llm_client=llm,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        event_store=event_store,
    )
    result = engine.run_single("same human input")
    assert result.final_answer == "done"
    messages, tools = llm.calls[0]
    saved = event_store.read(result.session_id) if event_store is not None else []
    return messages, tools, saved


def test_causal_recording_is_provider_payload_neutral(tmp_path: Path) -> None:
    with_events = _run_once(tmp_path / "on", events=True)
    without_events = _run_once(tmp_path / "off", events=False)
    assert with_events[0] == without_events[0]
    assert with_events[1] == without_events[1]

    assert not [event for event in with_events[2] if event.type == "request.attempt"]
    meta = next(event for event in with_events[2] if event.type == "request.meta")
    assert meta.payload["attempt_kind"] == "primary"
    assert str(meta.payload["attempt_id"]).startswith("attempt-")
    assert meta.payload["provider_structure_fp"]
    assert meta.payload["influence"]["ingress"]["storage_messages"] >= 1
    assert meta.payload["influence"]["history"]["effective_budget"] > 0
    assert "recent_continuity" in meta.payload["influence"]


def test_runtime_snapshot_is_startup_only_and_prompt_neutral(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    registry = ToolRegistry()
    prompt_before = build_system_prompt()
    schema_before = registry.schemas(lazy=settings.tool_schema_lazy)
    first = build_runtime_causal_snapshot(settings, registry)
    second = build_runtime_causal_snapshot(settings, registry)
    assert first.snapshot_id == second.snapshot_id
    assert first.source_tree_fp == source_tree_fingerprint()
    assert len(first.source_tree_fp) == 64
    assert build_system_prompt() == prompt_before
    assert registry.schemas(lazy=settings.tool_schema_lazy) == schema_before


def test_generation_contract_is_mechanical_and_secret_free() -> None:
    llm = _CaptureLLM([])
    fact = effective_generation_contract(llm)
    assert fact == {
        "provider": "fake",
        "model": "m",
        "max_tokens": 8192,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
        "send_tool_choice": True,
        "reasoning_split": False,
    }
    assert "api_key" not in fact
    assert "SHOULD-NOT-LEAK" not in repr(fact)
