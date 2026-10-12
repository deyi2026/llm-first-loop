"""Rule-first context-boundary authority tests.

Model-aware history budgeting is proactive, but approximate chars/token estimates are
not a second pre-provider hard authority. Actual provider overflow drives recovery.
Routing/model-resolution failure must stop before prompt/history mutation.
"""

from __future__ import annotations

import json

import pytest

from llm_loop.core.message import Message, MessageSource

from .test_model_attribution import (
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

_TINY_CTX_JSON = json.dumps(
    {
        "tiny": {
            "base_url": "https://fake.local/v1",
            "api_key_env": "",
            "models": {
                "tiny-model": {"context": 100, "thinking": False, "cost_tier": "free"},
            },
            "default_model": "tiny-model",
        },
    }
)


def test_approximate_oversize_is_not_hard_rejected_before_provider(tmp_path) -> None:
    """A tiny declared context does not let a chars/token estimate overrule provider truth."""
    settings = _settings(tmp_path, model_providers_raw=_TINY_CTX_JSON, llm_model="tiny-model")
    fake = _FakeLLMClient("tiny-model")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")

    assert result.final_answer.startswith("默认回答")
    assert len(fake.calls) == 1
    assert "[上下文超限]" not in result.final_answer


def test_under_limit_proceeds(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer.startswith("默认回答")
    assert len(fake.calls) == 1


def test_no_pool_path_still_proceeds(build_test_engine) -> None:
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"
    engine.llm_pool = None
    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer.startswith("你好")


def test_invalid_requested_model_stops_before_history_build(tmp_path, monkeypatch) -> None:
    """No valid provider route => no compaction/projection side effect on existing history."""
    settings = _settings(tmp_path, model_providers_raw=_TINY_CTX_JSON, llm_model="tiny-model")
    fake = _FakeLLMClient("tiny-model")
    pool = _make_pool(settings, fake)
    engine = _make_engine(tmp_path, pool, settings)
    sid = engine.session.create()
    sess = engine.session.load(sid)
    original = [
        Message(role="user", content="OLD-U-" + "x" * 2000, source=MessageSource.USER),
        Message(role="assistant", content="OLD-A-" + "y" * 2000, source=MessageSource.USER),
    ]
    sess.messages.extend(original)
    engine.session.save(sess)
    actions = []
    monkeypatch.setattr(engine, "_record_action", lambda *args, **kwargs: actions.append(args))

    result = engine.run(sid, "new question", model="tiny/missing-model")

    assert result.final_answer.startswith("[模型不可用]")
    assert fake.calls == []
    after = engine.session.load(sid)
    assert [m.content for m in after.messages[:2]] == [m.content for m in original]
    assert not any(a and a[0] == "overflow.compact" for a in actions)
    assert not any("自动压缩" in str(a) for a in actions)
