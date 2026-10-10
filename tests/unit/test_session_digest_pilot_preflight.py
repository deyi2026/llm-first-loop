"""Provider-free real LoopEngine check; fake answers are never scored as benefit."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from llm_loop.core.loop.engine_services.knowledge_runtime import _risk_for
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.introspection.corrections import CorrectionToolRegistry
from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor
from tests.unit.test_err1210_recovery import _mk, _resp

_FIXTURE = Path(__file__).parents[1] / "fixtures/knowledge_consumption/paired-digest-pilot-20261010.json"
_PILOT = json.loads(_FIXTURE.read_text())


@pytest.mark.parametrize("row", _PILOT["rows"], ids=lambda row: row["row_id"])
def test_each_frozen_row_enters_normal_engine_and_only_canary_reaches_wire(tmp_path, monkeypatch, row):
    case = next(c for c in _PILOT["cases"] if c["case_id"] == row["case_id"])
    prompt = case["prompt"]
    assert hashlib.sha256(prompt.encode()).hexdigest() == case["prompt_sha256"]
    assert _risk_for(prompt) == "low"
    requested = []

    def search(*, kind, query, **_kwargs):
        requested.append((kind, query))
        return [h for h in _PILOT["fixture_hints"] if h["kind"] == kind]

    engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("offline transport sentinel")])
    sid = engine.session.create()
    engine.settings = replace(
        engine.settings, tool_runtime=replace(
            engine.settings.tool_runtime,
            knowledge_advisor_mode=row["mode"],
            knowledge_advisor_sessions=sid if row["arm"] == "B" else "",
        ),
    )
    engine.corrections = cast(
        CorrectionToolRegistry,
        SimpleNamespace(build_knowledge_advisor=lambda mode: KnowledgeAdvisor(search, mode=mode)),
    )
    result = engine.run(sid, prompt, ingress=issue_ingress("web"))
    assert result.final_answer == "offline transport sentinel"
    assert len(fake.calls) == 1
    assert len(requested) == 3 and {kind for kind, _ in requested} == {"method", "experience", "lesson"}
    assert {query for _, query in requested} == {" ".join(prompt.split())[:240]}
    wire = fake.calls[0]["messages"]
    assert wire[-1]["role"] == "user" and wire[-1]["content"].startswith(prompt)
    assert ("[资料·记忆/经验]" in wire[-1]["content"]) == (row["arm"] == "B")
    assert not any("independent_oracle" in json.dumps(m) for m in wire)
    saved = engine.session.load(sid)
    assert not any("[资料·记忆/经验]" in m.content for m in saved.messages)
    # A sentinel response confirms control flow only; no task-success/benefit assessment.
