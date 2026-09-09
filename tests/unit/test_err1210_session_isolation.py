"""P2-B ERR1210 per-session isolation: bounded structural retry state only."""

from __future__ import annotations

import json
from contextlib import contextmanager

from llm_loop.core.run_context import current_session_id
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMHTTPError
from tests.unit.test_model_attribution import _FakeLLMClient, _make_engine, _make_pool, _settings

_PROVIDER_JSON = json.dumps(
    {
        "zhipu": {
            "base_url": "https://api.zhipu.local/v1",
            "api_key_env": "ZHIPU_API_KEY",
            "models": {"glm-5": {"context": 300000, "thinking": True}},
            "default_model": "glm-5",
        }
    }
)


@contextmanager
def _switch_session(sid: str):
    token = current_session_id.set(sid)
    try:
        yield sid
    finally:
        current_session_id.reset(token)


def _engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_PROVIDER_JSON, llm_model="zhipu/glm-5")
    fake = _FakeLLMClient("zhipu/glm-5")
    fake.queue(
        [
            LLMResponse(content="A-ok", tool_calls=[], provider="fake"),
            LLMResponse(content="B-ok", tool_calls=[], provider="fake"),
        ]
    )
    eng = _make_engine(tmp_path, _make_pool(settings, fake, cached={"zhipu": fake}), settings)
    return eng, fake


def _e1210():
    return LLMHTTPError("bad", status_code=400, body='{"error":{"code":"1210"}}')


def _attempt(eng, fake, sid):
    return eng._recovery._try_err1210_recovery(
        exc=_e1210(),
        sess=eng.session.load(sid),
        messages=[{"role": "user", "content": "u1"}, {"role": "user", "content": "u2"}],
        tools_param=[],
        llm_client=fake,
        chat_model_arg=None,
        timeout_s=1.0,
        session_id=sid,
    )


def test_two_sessions_have_independent_run_sequence_and_attempt_budget(tmp_path, monkeypatch):
    eng, fake = _engine(tmp_path, monkeypatch)
    sid_a = eng.session.create()
    sid_b = eng.session.create()
    with _switch_session(sid_a):
        eng._recovery._err1210_run_begin()
        assert eng._run_state().err1210_run_seq == 1
        a = _attempt(eng, fake, sid_a)
        assert a.recovered is True
        again = _attempt(eng, fake, sid_a)
        assert again.exhausted is True and again.provider_retry_count == 0
    with _switch_session(sid_b):
        eng._recovery._err1210_run_begin()
        assert eng._run_state().err1210_run_seq == 1
        b = _attempt(eng, fake, sid_b)
        assert b.recovered is True
    assert len(fake.calls) == 2
    assert set(eng._err1210_attempted) == {sid_a, sid_b}


def test_retired_prompt_recovery_fields_are_absent(tmp_path, monkeypatch):
    eng, _ = _engine(tmp_path, monkeypatch)
    with _switch_session(eng.session.create()):
        st = eng._run_state()
        for name in (
            "last_build_injections",
            "last_build_defer_replayed",
            "deferred_replay_refs",
            "deferred_replay_slots",
            "auto_continue_1210",
        ):
            assert not hasattr(st, name)
